"""缓存预加载API - 登录后后台拉取兜底数据"""
import asyncio
import logging
from fastapi import APIRouter, Depends
from app.core.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)])


# 4个并发后台线程，平衡速度与稳定性
_preload_sem = asyncio.Semaphore(4)


async def _fetch_with_timeout(coro, timeout=20.0):
    """带超时的异步调用，超时返回 None"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def _thread_limited(fn, *args, **kwargs):
    """通过信号量限制并发线程数"""
    async with _preload_sem:
        return await _fetch_with_timeout(asyncio.to_thread(fn, *args, **kwargs), timeout=20)


async def _stale_first_load(keys_map, fetch_map, *, stale_batch_reader=None, stale_reader=None):
    """stale-first 拉取 helper

    优先读 stale 缓存，缺失字段再并发拉取。返回 {field: data}。

    Args:
        keys_map: {frontend_field: cache_key}，声明要拉哪些字段
        fetch_map: {frontend_field: callable}，缺失时调哪个函数拉取
        stale_batch_reader: (cache_keys) -> {cache_key: data}，批量读 stale（用于 dragon 等 prefix 匹配）
        stale_reader: (cache_key) -> data | None，单 key 读 stale
    """
    if stale_batch_reader is not None:
        batch = stale_batch_reader(list(keys_map.values()))
        key_to_field = {k: f for f, k in keys_map.items()}
        result = {key_to_field[k]: v for k, v in batch.items() if k in key_to_field}
    else:
        result = {}
        for field, cache_key in keys_map.items():
            stale = stale_reader(cache_key)
            if stale:
                result[field] = stale

    missing = [f for f in keys_map if f not in result]
    if missing:
        tasks = [_thread_limited(fetch_map[f]) for f in missing]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for field, res in zip(missing, results):
            if res is not None and not isinstance(res, Exception):
                result[field] = res

    return result


@router.get("/cache/preload")
async def preload_cache():
    """返回所有模块的缓存快照

    策略：先读 stale 内存缓存（ms级），全空则尝试拉取（任何时段都兜底）。
    用于登录后后台预加载，写入前端IndexedDB。
    """
    result = {}

    # ── 龙虎榜：stale 走 prefix 批量匹配 + 按需拉取缺失项 ──
    try:
        from app.services.strategy_service import StrategyService
        s = StrategyService()

        # 前缀含末尾下划线，确保不匹配到旧版本（如 dragon_today_v5_…）
        # 前端契约字段名（usePreload.js 期望）→ 后端内部缓存前缀
        dragon_key_remap = {
            'dragon_today': 'dragon_today_v6_',
            'dragon_capital_flow': 'dragon_flow_',
            'dragon_seat_detail': 'dragon_seat_',
            'dragon_sector': 'dragon_sector_',
            'dragon_consecutive_5': 'dragon_consecutive_5_',
            'dragon_perf': 'dragon_perf_',
        }
        prefixes = list(dragon_key_remap.values())
        # prefix → frontend field
        prefix_to_field = {v: k for k, v in dragon_key_remap.items()}

        dragon_data = {}
        stale_batch = StrategyService._get_stale_cache_batch(prefixes)
        for prefix, data in stale_batch.items():
            if data is not None and prefix in prefix_to_field:
                dragon_data[prefix_to_field[prefix]] = data

        missing_fields = [f for f in dragon_key_remap if f not in dragon_data]
        if missing_fields:
            fetch_map = {
                'dragon_today': s.get_dragon_list_today,
                'dragon_capital_flow': s.get_dragon_capital_flow,
                'dragon_seat_detail': s.get_dragon_seat_detail,
                'dragon_sector': s.get_dragon_sector_analysis,
                'dragon_consecutive_5': lambda: s.get_dragon_consecutive(5),
                'dragon_perf': s.get_dragon_next_day_performance,
            }
            tasks = [_thread_limited(fetch_map[f]) for f in missing_fields]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for field, res in zip(missing_fields, results):
                if res is not None and not isinstance(res, Exception):
                    dragon_data[field] = res

        result['dragon'] = dragon_data
    except Exception as e:
        logger.warning(f"龙虎榜preload失败: {e}")
        result['dragon'] = {}

    # ── 智能选股：multi_factor 走 stale-first，combo 也加 stale 读避免重复 45s 计算 ──
    try:
        from app.services.strategy_service import StrategyService, _get_strategy_target_date
        s = StrategyService()

        strategy_data = await _stale_first_load(
            keys_map={'multi_factor': 'pick_multi_factor_20_None_None_None_True'},
            fetch_map={'multi_factor': lambda: s.get_multi_factor_picks(top_n=20, exclude_st=True)},
            stale_reader=lambda k: StrategyService._get_stale_cache(k),
        )

        # combo 单独处理：cache key 含 target_date，stale-first 后再拉
        target_date = _get_strategy_target_date()
        combo_cache_key = f'strategy_combo_vote_20_True_{target_date}'
        combo_stale = StrategyService._get_stale_cache(combo_cache_key)
        if combo_stale:
            strategy_data['combo'] = combo_stale
        else:
            combo_data = await _fetch_with_timeout(
                asyncio.to_thread(s.get_strategy_combo, mode='vote', top_n=20, exclude_st=True),
                timeout=45.0,
            )
            if combo_data is not None:
                strategy_data['combo'] = combo_data

        result['strategy'] = strategy_data
    except Exception as e:
        logger.warning(f"智能选股preload失败: {e}")
        result['strategy'] = {}

    # ── 市场看板 ──
    try:
        from app.services.market_service import MarketService
        m = MarketService()

        market_data = await _stale_first_load(
            keys_map={
                'sentiment': 'sentiment',
                'sectors_industry': 'sectors:industry:30',
                'hot': 'hot_sectors:10',
                'signals': 'rotation',
            },
            fetch_map={
                'sentiment': m.get_market_sentiment,
                'sectors_industry': lambda: m.get_sector_overview('industry', 30),
                'hot': lambda: m.get_hot_sectors(10),
                'signals': m.get_rotation_signals,
            },
            stale_reader=lambda k: MarketService._get_stale_cache(k),
        )

        # 北向资金（非交易时段从历史CSV获取）
        try:
            nb_stale = MarketService._get_stale_cache('northbound')
            if nb_stale:
                market_data['northbound'] = nb_stale
            else:
                nb_data = await _thread_limited(m.get_northbound_flow)
                if nb_data:
                    market_data['northbound'] = nb_data
        except Exception as ne:
            logger.debug(f"北向资金preload失败: {ne}")

        result['market'] = market_data
    except Exception as e:
        logger.warning(f"市场看板preload失败: {e}")
        result['market'] = {}

    # ── 板块深度分析 ──
    try:
        from app.core.cache import cache_get_stale, NS_MARKET
        from app.services.sector_analysis_service import sector_analysis_service

        sector_data = await _stale_first_load(
            keys_map={
                'rotation': 'sector_rotation_model:industry:30',
                'heat': 'sector_heat_rank:30',
                'chain': 'sector_analysis_industry_chain',
            },
            fetch_map={
                'rotation': lambda: sector_analysis_service.get_sector_rotation_model('industry', 30),
                'heat': lambda: sector_analysis_service.get_sector_heat_rank(30),
                'chain': sector_analysis_service.get_industry_chain_analysis,
            },
            stale_reader=lambda k: cache_get_stale(k, NS_MARKET),
        )

        result['sector_analysis'] = sector_data
    except Exception as e:
        logger.warning(f"板块分析preload失败: {e}")
        result['sector_analysis'] = {}

    return result
