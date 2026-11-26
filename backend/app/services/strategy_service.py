"""策略服务 - 使用pytdx获取龙虎榜/策略数据（全市场扫描版）"""

import time
from concurrent import futures as concurrent_futures

import logging

from app.core.data_sources import EastMoneyDataCenter, EastMoneyZTPool, THSNorthboundSource, TencentSource
from app.core.data_utils import is_limit_up, is_limit_down

from collections import OrderedDict

from threading import Lock

import numpy as np

from datetime import datetime, timedelta

from app.core.pytdx_source import pytdx_data

from app.services.market_service import pd_not_nan

from app.services.stock_service import _fetch_real_financial

from app.core.cache import cache_get_stale, cache_set, swr_cache, NS_DRAGON, NS_STRATEGY
from app.services.factor_engine import (
    FactorCalculator, StandardScorer, VolumePriceClassifier, compute_indicators_from_klines
)
from app.services.ml_model_service import ml_model_service
from app.services.fundamental_factors import FundamentalFactorCalculator
from app.services.strategy_backtester import backtester, BacktestFactorCalculator
from app.core.trading_calendar import is_trading_day, is_trading_hours, get_last_trade_date

logger = logging.getLogger(__name__)


def _api_call_with_timeout(func, *args, timeout=10, **kwargs):
    """带超时的 API 调用包装器，防止 ECONNRESET（跨平台兼容）"""
    from app.core.data_sources import call_with_timeout
    default = {} if func.__name__.startswith("get_") else {"stocks": []}
    return call_with_timeout(func, timeout=timeout, default=default, *args, **kwargs)



def _rate_score(score: int) -> str:

    """根据评分给出可读评级

    ≥80 强烈推荐 / 70-79 推荐 / 60-69 观望 / <60 回避

    """

    if score >= 80:

        return '强烈推荐'

    elif score >= 70:

        return '推荐'

    elif score >= 60:

        return '观望'

    return '回避'

def _classify_divergence(change_pct, vol_ratio):
    """量价关系分类 -- 委托给统一因子引擎"""
    return VolumePriceClassifier.classify_simple(change_pct, vol_ratio) or ""

def _preload_klines_for_combo(strategy_list: list, target_date: str, exclude_st: bool):
    """组合策略K线预加载：收集候选股票，批量获取K线填充缓存。

    各子策略独立运行时各自请求pytdx K线，虽然3分钟缓存可以命中，
    但首次请求仍需建立TCP连接。预加载在组合策略执行前一次性批量获取，
    减少连接开销和总耗时。
    """
    try:
        # 收集需要分析K线的候选股票（去重）
        candidate_codes = set()

        def _add_candidates(codes_with_names, limit=30):
            for code, name in codes_with_names[:limit]:
                if code and not (exclude_st and 'ST' in name.upper()):
                    candidate_codes.add(code)

        # 涨停池：多因子策略需要
        if "multi_factor" in strategy_list:
            try:
                zt_pool = EastMoneyZTPool.get_zt_pool(target_date)
                if zt_pool:
                    _add_candidates(
                        [(str(item.get("c", "")), str(item.get("n", "") or "")) for item in zt_pool],
                        limit=30
                    )
            except Exception:
                pass

        # 龙虎榜：资金流策略需要（直接调datacenter避免循环导入）
        if "capital_flow" in strategy_list:
            try:
                raw_dragon = EastMoneyDataCenter.dragon_tiger_board(target_date)
                if raw_dragon:
                    _add_candidates(
                        [(str(item.get("SECURITY_CODE", "")), str(item.get("SECURITY_NAME_ABBR", "") or "")) for item in raw_dragon],
                        limit=30
                    )
            except Exception:
                pass

        # 量价背离：龙虎榜+涨停池+全市场成交额TOP
        if "volume_price_divergence" in strategy_list:
            try:
                dragon_data = EastMoneyDataCenter.dragon_tiger_board(target_date)
                if dragon_data:
                    _add_candidates(
                        [(str(item.get("SECURITY_CODE", "")), str(item.get("SECURITY_NAME_ABBR", "") or "")) for item in dragon_data],
                        limit=50
                    )
            except Exception:
                pass
            try:
                zt_pool = EastMoneyZTPool.get_zt_pool(target_date)
                if zt_pool:
                    _add_candidates(
                        [(str(item.get("c", "")), str(item.get("n", "") or "")) for item in zt_pool],
                        limit=50
                    )
            except Exception:
                pass

        # ML预测/低吸企稳：全市场成交额TOP200（预筛选后最多200只）
        if "ml_prediction" in strategy_list or "low_absorption" in strategy_list:
            try:
                from app.core.data_sources import TencentSource
                full_market = TencentSource.get_full_market()
                if full_market:
                    sorted_by_amount = sorted(full_market, key=lambda x: float(x.get("f10", 0) or 0), reverse=True)
                    for item in sorted_by_amount[:200]:
                        code = str(item.get("f12", ""))
                        name = str(item.get("f14", "") or "")
                        if code and not (exclude_st and 'ST' in name.upper()):
                            candidate_codes.add(code)
            except Exception:
                pass

        # 龙头选股：行业硬编码成分股 + 同花顺热点强势股
        if "leader" in strategy_list:
            try:
                from app.core.data_sources_clean import THSSectorBuilder, THSHotSource
                # 行业龙头股
                for codes in THSSectorBuilder._INDUSTRY_STOCKS.values():
                    for code in codes:
                        candidate_codes.add(str(code))
                # 同花顺热点强势股
                hot_items = THSHotSource.get_hot_reasons(page_size=200) or []
                for it in hot_items:
                    code = str(it.get("code", ""))
                    name = str(it.get("name", "") or "")
                    if code and not (exclude_st and 'ST' in name.upper()):
                        candidate_codes.add(code)
            except Exception:
                pass

        if candidate_codes:
            codes_list = list(candidate_codes)
            logger.info(f"组合策略K线预加载: {len(codes_list)}只候选股票")
            pytdx_data.get_batch_klines(codes_list, period=4, count=60, max_workers=10)
    except Exception as e:
        logger.debug(f"K线预加载失败（不影响正常执行）: {e}")


def _get_cached_kline(code: str, period: int = 4, count: int = 60):
    """从Redis缓存获取K线数据，未命中时实时拉取并写入缓存"""
    cache_key = f"kline_{code}_{period}_{count}"
    cached = StrategyService._get_dragon_cache(cache_key)
    if cached is not None:
        return cached
    try:
        klines = pytdx_data.get_kline(code, period=period, count=count)
        if klines:
            StrategyService._set_dragon_cache(cache_key, klines, ttl=1800)  # 30分钟TTL
        return klines
    except Exception as e:
        logger.debug(f"获取K线失败 ({code}): {e}")
        return None


def _preload_daily_klines(codes: list, period: int = 4, count: int = 60):
    """批量预加载全市场K线到Redis缓存（每日开盘前调用）"""
    if not codes:
        return
    logger.info(f"预加载 {len(codes)} 只股票的K线到Redis缓存")
    batch = pytdx_data.get_batch_klines(codes, period=period, count=count, max_workers=15)
    for code, klines in batch.items():
        if klines:
            cache_key = f"kline_{code}_{period}_{count}"
            StrategyService._set_dragon_cache(cache_key, klines, ttl=3600)  # 1小时TTL
    logger.info(f"K线预加载完成: {len(batch)}/{len(codes)} 只成功")

def _limit_pct(code: str, name: str = "") -> float:

    """根据股票代码和名称返回涨跌停幅度阈值"""

    # ST股（含*ST）：±5%
    if name and ('ST' in name.upper() or '*ST' in name.upper()):
        return 4.8  # 略低于5%，容差匹配实际ST股

    # 创业板(300/301)、科创板(688)：±20%
    if code.startswith(('300', '301', '688')):
        return 19.5

    # 北交所(8/4/9开头)：±30%
    elif code.startswith(('8', '4', '9')):
        return 29.5

    # 主板（上证60/深证00）：±10%
    return 9.5


def _get_adaptive_amount_threshold(quotes, min_threshold=1e7, default_threshold=5e7):
    """根据实际行情数据动态计算成交额阈值，非交易时间自动降低门槛"""
    if not quotes:
        return default_threshold
    amounts = sorted([q.get('amount', 0) for q in quotes if q.get('amount', 0) > 0])
    if not amounts:
        return min_threshold
    n = len(amounts)
    median_amount = amounts[n // 2]
    p75_amount = amounts[int(n * 0.75)]
    if median_amount < default_threshold * 0.3:
        threshold = max(min_threshold, p75_amount * 0.5)
        logger.info(f'成交额中位数偏低({median_amount:.0f})，使用自适应阈值: {threshold:.0f}')
    else:
        threshold = default_threshold
    return max(min_threshold, threshold)

def _is_limit_up(q: dict) -> bool:

    chg = q.get('change_pct', 0)

    code = str(q.get('code', ''))
    name = str(q.get('name', ''))

    return chg >= _limit_pct(code, name)

def _is_limit_down(q: dict) -> bool:

    chg = q.get('change_pct', 0)

    code = str(q.get('code', ''))
    name = str(q.get('name', ''))

    return chg <= -_limit_pct(code, name)

def _get_target_date() -> str:
    """获取目标日期：交易时间用今天，非交易时间用最近交易日"""
    now = datetime.now()
    # 交易日且在交易时间（9:00-15:00）
    if is_trading_day(now):
        hour_min = now.hour * 60 + now.minute
        if 540 <= hour_min <= 900:  # 9:00-15:00
            return now.strftime('%Y%m%d')
    return get_last_trade_date()


# 龙虎榜目标日期缓存（避免同一天重复查询东财API）
_dragon_target_date_cache = {'date': None, 'target': None, 'checked_at': None}


def _get_prev_trade_date() -> str:
    """获取上一个交易日（不含今天），格式 YYYYMMDD"""
    now = datetime.now()
    d = now - timedelta(days=1)
    for _ in range(30):
        if is_trading_day(d):
            return d.strftime('%Y%m%d')
        d -= timedelta(days=1)
    return (now - timedelta(days=1)).strftime('%Y%m%d')


def _get_dragon_target_date() -> str:
    """获取龙虎榜目标日期
    
    龙虎榜数据通常在收盘后18:00-20:00发布。盘中查询时，若今日数据尚未发布，
    自动回退到上一交易日，确保前端始终有数据可展示。
    """
    now = datetime.now()
    today_str = now.strftime('%Y%m%d')
    
    # 1. 非交易日直接返回上一交易日（不含今天）
    if not is_trading_day(now):
        return _get_prev_trade_date()
    
    # 2. 检查缓存（5分钟内不重复查询）
    cached = _dragon_target_date_cache
    if (cached['date'] == today_str and cached['checked_at']
            and (now - cached['checked_at']).total_seconds() < 300):
        return cached['target']
    
    # 3. 交易时间（9:00-15:00）或收盘后：查今天是否有龙虎榜数据
    from app.core.data_sources_clean import dragon_tiger_board
    data = dragon_tiger_board(today_str)
    target = today_str if data else _get_prev_trade_date()
    cached.update({'date': today_str, 'target': target, 'checked_at': now})
    return target


# 策略目标日期缓存（避免同一天重复检查）
_strategy_target_date_cache = {'date': None, 'target': None, 'checked_at': None}


def _get_strategy_target_date() -> str:
    """获取智能选股策略的目标日期

    与 _get_dragon_target_date 逻辑类似：交易时间内先检查今天是否有缓存的策略数据，
    没有则回退到上一交易日，确保前端始终有数据可展示。
    """
    now = datetime.now()
    today_str = now.strftime('%Y%m%d')

    # 1. 非交易日直接返回上一交易日
    if not is_trading_day(now):
        return _get_prev_trade_date()

    # 2. 检查缓存（5分钟内不重复查询）
    cached = _strategy_target_date_cache
    if (cached['date'] == today_str and cached['checked_at']
            and (now - cached['checked_at']).total_seconds() < 300):
        return cached['target']

    # 3. 检查内存缓存中是否有今天的策略数据（非空）
    has_today_data = False
    try:
        from app.services.strategy_service import StrategyService as _SS
        with _SS._cache_lock:
            for key, entry in _SS._dragon_cache.items():
                if today_str in key and not _SS._is_empty_data(entry.get('data')):
                    has_today_data = True
                    break
    except Exception:
        pass

    # 4. 检查 Redis 中是否有今天的策略数据
    if not has_today_data:
        try:
            from app.core.cache import cache_get_stale as _cgs
            # 检查常见的策略 key 前缀
            for prefix in ('multi_factor_', 'ml_prediction_', 'low_absorption_',
                           'capital_flow_', 'vol_price_div_', 'strategy_combo_'):
                test_key = f'{prefix}20_all_0_all_True_{today_str}'
                data = _cgs(test_key, namespace='strategy')
                if data is not None and not StrategyService._is_empty_data(data):
                    has_today_data = True
                    break
        except Exception:
            pass

    target = today_str if has_today_data else _get_prev_trade_date()
    cached.update({'date': today_str, 'target': target, 'checked_at': now})
    return target


def _format_display_date(date_str: str) -> str:
    """格式化日期为显示格式：2026-07-03"""
    try:
        dt = datetime.strptime(str(date_str), '%Y%m%d')
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return str(date_str)


def _format_update_time() -> str:
    """格式化更新时间：14:30:25"""
    return datetime.now().strftime('%H:%M:%S')


def _add_meta(result: dict, target_date: str = None) -> dict:
    """为策略结果添加元数据（日期、更新时间）"""
    if not isinstance(result, dict):
        return result
    td = target_date or _get_target_date()
    result.setdefault("data_date", _format_display_date(td))
    result.setdefault("update_time", _format_update_time())
    return result





# ═══════════════════════════════════════════════════════════════════

class StrategyService:
    """策略服务 - 龙虎榜/选股策略（直连API版）"""

    # ── 缓存配置 ────────────────────────────────────────────────
    _MAX_CACHE = 32  # 增大缓存容量，容纳更多子接口结果
    _dragon_cache: OrderedDict = OrderedDict()
    _cache_lock = Lock()
    _DRAGON_TTL = 300  # 5分钟（原始数据）
    
    # 子接口缓存 TTL 分级
    _TTL_TODAY = 180        # 今日龙虎榜：3分钟（盘中频繁刷新）
    _TTL_STRATEGY = 300     # 选股策略：5分钟
    _TTL_CAPITAL_FLOW = 300 # 资金流向：5分钟
    _TTL_SEAT = 600         # 席位详情：10分钟（低频查询）
    _TTL_SECTOR = 600       # 板块分析：10分钟（低频查询）
    _TTL_CONSECUTIVE = 300  # 连板统计：5分钟
    _TTL_PERFORMANCE = 300  # 次日表现：5分钟
    _TTL_COMBO = 600        # 组合策略：10分钟（计算成本高）

    @classmethod
    def _get_dragon_cache(cls, key: str, namespace: str = NS_DRAGON):
        with cls._cache_lock:
            cached = cls._dragon_cache.get(key)
            if not cached:
                # 内存未命中：回查 Redis（SWR）
                try:
                    from app.core.cache import cache_get as _cache_get
                    redis_data = _cache_get(key, namespace)
                    if redis_data is not None:
                        return redis_data
                except Exception:
                    pass
                return None
            # 使用自定义 TTL（空数据使用较短 TTL）
            ttl = cached.get('ttl', cls._DRAGON_TTL)
            if time.time() - cached['timestamp'] < ttl:
                cls._dragon_cache.move_to_end(key)
                return cached['data']
            # 非交易时间返回stale数据（即使过期）
            if not is_trading_hours():
                return cached['data']
            del cls._dragon_cache[key]
        return None

    @classmethod
    def _get_stale_cache(cls, key: str, namespace: str = NS_DRAGON):
        """获取缓存但不检查 TTL，用于 preload 兜底。
        优先读进程内缓存，再读 Redis/SQLite stale 缓存。
        """
        with cls._cache_lock:
            cached = cls._dragon_cache.get(key)
            if cached:
                return cached['data']
        # 进程内没有，尝试从 Redis/SQLite 读 stale 缓存（不检查TTL）
        try:
            from app.core.cache import cache_get_stale
            redis_data = cache_get_stale(key, namespace)
            if redis_data is not None:
                return redis_data
        except Exception:
            pass
        return None

    @classmethod
    def _get_stale_cache_batch(cls, keys: list, namespace: str = NS_DRAGON):
        """批量获取stale缓存，返回 {key_prefix: data}"""
        result = {}
        found_prefixes = set()
        with cls._cache_lock:
            for full_key, cached in cls._dragon_cache.items():
                for prefix in keys:
                    if prefix in found_prefixes:
                        continue
                    if full_key.startswith(prefix):
                        result[prefix] = cached['data']
                        found_prefixes.add(prefix)
                        break
        # 进程内没找到的，尝试从 Redis/SQLite 读（用目标日期构造完整 key）
        missing = [k for k in keys if k not in result]
        if missing:
            try:
                target_date = _get_target_date()
                from app.core.cache import cache_get_stale
                for prefix in missing:
                    full_key = f'{prefix}{target_date}'
                    stale_data = cache_get_stale(full_key, namespace)
                    if stale_data is not None:
                        result[prefix] = stale_data
            except Exception:
                pass
        return result

    @staticmethod
    def _is_empty_data(data) -> bool:
        """判断数据是否为空（用于决定是否使用短TTL缓存）

        返回 dict 但 stocks/list/sectors 为空列表时也视为空，
        避免空结果被正常 TTL 缓存导致后续请求一直返回空。
        """
        if not data:
            return True
        if isinstance(data, dict):
            # 检查常见的数据列表字段
            for key in ('stocks', 'list', 'sectors', 'seats', 'consecutive', 'performance', 'combined_stocks'):
                val = data.get(key)
                if isinstance(val, list) and len(val) == 0:
                    # 列表为空，再检查 total/count 是否也为 0
                    total = data.get('total') or data.get('count') or data.get('stock_count') or 0
                    if total == 0:
                        return True
            # 龙虎榜今日数据：stocks + gainers + losers 全空
            if 'stocks' in data and 'gainers' in data and 'losers' in data:
                if (not data['stocks'] and not data['gainers'] and not data['losers']
                    and not data.get('limit_up') and not data.get('limit_down')):
                    return True
            # 检查只有空结构的资源流向数据
            if 'institution' in data and 'hot_money' in data:
                inst = data['institution']
                hot = data['hot_money']
                if isinstance(inst, dict) and isinstance(hot, dict):
                    if inst.get('count', 0) == 0 and hot.get('count', 0) == 0:
                        return True
        return False

    @classmethod
    def _set_dragon_cache(cls, key: str, data, empty_ttl: int = 60, ttl: int = None, namespace: str = NS_DRAGON):
        """设置龙虎榜缓存（进程内存 + Redis）

        Args:
            data: 要缓存的数据
            empty_ttl: 空数据的缓存时间（秒），默认60秒，避免重复请求
            ttl: 自定义缓存 TTL（秒），None 则使用默认 _DRAGON_TTL
            namespace: Redis 命名空间，选股策略用 NS_STRATEGY，龙虎榜类用 NS_DRAGON
        """
        with cls._cache_lock:
            while len(cls._dragon_cache) >= cls._MAX_CACHE:
                cls._dragon_cache.popitem(last=False)
            # 空数据使用较短的 TTL，避免重复请求但仍允许重试
            is_empty = cls._is_empty_data(data)
            if ttl is not None:
                cache_ttl = empty_ttl if is_empty else ttl
            else:
                cache_ttl = empty_ttl if is_empty else cls._DRAGON_TTL
            cls._dragon_cache[key] = {'data': data, 'timestamp': time.time(), 'ttl': cache_ttl}

        # 同时写入 Redis，供 SWR 后台刷新使用
        try:
            from app.core.cache import cache_set as _cache_set
            redis_ttl = ttl if ttl is not None else cls._DRAGON_TTL
            _cache_set(key, data, ttl=redis_ttl, namespace=namespace)
        except Exception:
            pass  # Redis 写入失败不影响内存缓存

    @classmethod
    def clear_dragon_cache(cls):
        """清除龙虎榜缓存"""
        with cls._cache_lock:
            cls._dragon_cache.clear()
        logger.info("龙虎榜缓存已清除")

    @classmethod
    def _get_dragon_raw_data(cls, date: str = None, force_refresh: bool = False) -> list:
        """统一获取龙虎榜原始数据，避免重复请求东财API
        
        所有龙虎榜相关方法都应通过此方法获取数据，确保：
        1. 同一日期只请求一次 API
        2. 非交易时间也能返回缓存数据
        3. 字段名统一映射为前端需要的格式
        """
        if date is None:
            date = _get_dragon_target_date()
        
        cache_key = f'dragon_raw_{date}'
        if not force_refresh:
            cached = cls._get_dragon_cache(cache_key)
            if cached is not None:
                return cached
        
        # 从东财获取原始数据
        raw_data = EastMoneyDataCenter.dragon_tiger_board(date)

        # 去重：同一股票可能因多个上榜原因出现多条记录，按代码合并金额
        if raw_data:
            original_count = len(raw_data)
            aggregated = {}
            for item in raw_data:
                code = str(item.get("SECURITY_CODE", ""))
                if not code:
                    continue
                if code in aggregated:
                    existing = aggregated[code]
                    # 累加金额字段
                    existing["BILLBOARD_NET_AMT"] = float(existing.get("BILLBOARD_NET_AMT") or 0) + float(item.get("BILLBOARD_NET_AMT") or 0)
                    existing["BILLBOARD_BUY_AMT"] = float(existing.get("BILLBOARD_BUY_AMT") or 0) + float(item.get("BILLBOARD_BUY_AMT") or 0)
                    existing["BILLBOARD_SELL_AMT"] = float(existing.get("BILLBOARD_SELL_AMT") or 0) + float(item.get("BILLBOARD_SELL_AMT") or 0)
                    # 合并上榜原因（去重后拼接）
                    existing_reasons = set(str(existing.get("EXPLANATION", "") or "").split(";"))
                    new_reasons = str(item.get("EXPLANATION", "") or "").split(";")
                    for r in new_reasons:
                        if r.strip():
                            existing_reasons.add(r.strip())
                    existing["EXPLANATION"] = "; ".join(existing_reasons)
                else:
                    # 深拷贝第一条记录作为基准
                    aggregated[code] = dict(item)
            raw_data = list(aggregated.values())
            if original_count > len(raw_data):
                logger.info(f"龙虎榜去重: {original_count}条 → {len(raw_data)}只股票")

        # 统一字段映射：东财 datacenter 字段 → 前端需要的字段
        normalized = []
        if raw_data:
            for item in raw_data:
                # 金额字段映射（东财 datacenter 使用 BILLBOARD_ 前缀）
                net_amt = float(item.get("BILLBOARD_NET_AMT") or item.get("NET_AMT") or 0)
                buy_amt = float(item.get("BILLBOARD_BUY_AMT") or item.get("BUY_AMT") or 0)
                sell_amt = float(item.get("BILLBOARD_SELL_AMT") or item.get("SELL_AMT") or 0)
                change_pct = float(item.get("CHANGE_RATE") or item.get("CHANGE_RATE_PCT") or 0)
                
                # 计算总成交额
                total_amount = buy_amt + sell_amt
                
                # 根据净买入额推断资金方向
                if net_amt > 0:
                    direction = "净买入"
                elif net_amt < 0:
                    direction = "净卖出"
                else:
                    direction = "持平"
                
                # 获取最新价（优先使用 CLOSE_PRICE，其次 CHANGE_PRICE）
                price = float(item.get("CLOSE_PRICE") or item.get("CHANGE_PRICE") or 0)
                
                normalized.append({
                    "code": str(item.get("SECURITY_CODE", "")),
                    "name": str(item.get("SECURITY_NAME_ABBR", "")),
                    "price": price,
                    "change_pct": change_pct,
                    "net_amount": net_amt,
                    "buy_amount": buy_amt,
                    "sell_amount": sell_amt,
                    "total_amount": total_amount,
                    "direction": direction,
                    "reason": str(item.get("EXPLANATION", "") or item.get("REASON", "") or ""),
                    "trade_date": str(item.get("TRADE_DATE", "")).replace("-", "").replace(" ", "")[:8],
                    # 换手率：东财 datacenter 字段 TURNOVERRATE / TURNOVER_RATE
                    "turnover": float(item.get("TURNOVERRATE") or item.get("TURNOVER_RATE") or 0),
                    # 上榜后N日涨跌幅（东财直接提供，无需K线计算）
                    "d1_change_pct": float(item.get("D1_CLOSE_ADJCHRATE") or 0),
                    "d2_change_pct": float(item.get("D2_CLOSE_ADJCHRATE") or 0),
                    "d5_change_pct": float(item.get("D5_CLOSE_ADJCHRATE") or 0),
                    "d10_change_pct": float(item.get("D10_CLOSE_ADJCHRATE") or 0),
                    # 保留原始字段供特殊场景使用
                    "raw": item,
                })
        
        cls._set_dragon_cache(cache_key, normalized)
        return normalized

    @classmethod
    def _compute_technical_indicators(cls, closes, volumes, highs, lows):
        """技术指标计算 -- 委托给统一因子引擎（消除重复实现）"""
        if len(closes) < 20:
            return None
        klines = []
        for j in range(len(closes)):
            klines.append({
                "close": closes[j], "volume": volumes[j] if j < len(volumes) else 0,
                "high": highs[j] if j < len(highs) else closes[j],
                "low": lows[j] if j < len(lows) else closes[j],
            })
        result = compute_indicators_from_klines(klines)
        if not result:
            return None
        factors = result.get("factors", {})
        kdj_info = factors.get("kdj", {})
        return {
            "momentum": result["momentum"],
            "liquidity": result["liquidity"],
            "tech": result["tech"],
            "kdj_j": kdj_info.get("j", 50),
            "vol_ratio": factors.get("volume_ratio", 1.0),
            "rsi6": factors.get("rsi6", 50),
            "decline_20d": result["decline_20d"],
            "score": result["score"],
        }

    @classmethod
    def _calc_stock_indicators(cls, code: str) -> dict:
        """基于真实 K 线数据计算技术指标（替代 np.random）"""
        try:
            klines = pytdx_data.get_kline(code, period=4, count=60)
            if not klines or len(klines) < 20:
                return None

            closes = [k['close'] for k in klines]
            volumes = [k['volume'] for k in klines]
            highs = [k['high'] for k in klines]
            lows = [k['low'] for k in klines]

            indicators = cls._compute_technical_indicators(closes, volumes, highs, lows)
            if not indicators:
                return None

            # 预测分数（基于技术指标的综合评估）
            prediction_score = round(min(0.95, max(0.4, indicators['score'] / 100)), 3)
            indicators['prediction_score'] = prediction_score
            return indicators
        except Exception as e:
            logger.warning(f"计算指标失败 ({code}): {e}")
            return None

    def get_strategy_comparison(self, force_refresh: bool = False) -> dict:
        """获取策略对比表"""
        if not force_refresh:
            cached = self._get_dragon_cache('comparison')
            if cached:
                return cached

        # 龙虎榜数据16:30后才发布，_get_dragon_raw_data()内部自动回退到上一交易日
        dragon_date = _get_dragon_target_date()
        result = {
            "strategies": [
                {"name": "净买入排名", "description": "按龙虎榜净买入额排序（无法区分机构/游资）", "category": "资金面", "count": 0, "top_stocks": []},
                {"name": "高波动选股", "description": "筛选涨跌幅大的活跃标的", "category": "情绪面", "count": 0, "top_stocks": []},
                {"name": "溢价率选股", "description": "买入远大于卖出的标的", "category": "技术面", "count": 0, "top_stocks": []},
            ],
            "dragon_data_date": _format_display_date(dragon_date),
        }

        def _rank_scores(items, n=10):
            """排名打分：第1名100分，第n名25分，线性递减"""
            count = len(items)
            if count <= 1:
                return [100] if count else []
            return [round(100 - i * 75 / (count - 1)) for i in range(count)]

        # 使用统一的龙虎榜数据获取方法
        try:
            dragon_data = self._get_dragon_raw_data(force_refresh=force_refresh)
            if dragon_data:
                # 净买入排名 — 先过滤再排序，避免漏掉前20之外的净买入龙头
                institution_buy = sorted(
                    [item for item in dragon_data if item["net_amount"] > 0],
                    key=lambda x: x["net_amount"], reverse=True
                )[:10]
                result["strategies"][0]["count"] = len(institution_buy)
                scores = _rank_scores(institution_buy)
                result["strategies"][0]["top_stocks"] = [
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "net_amount": item["net_amount"],
                        "buy_amount": item.get("buy_amount", 0),
                        "sell_amount": item.get("sell_amount", 0),
                        "total_amount": item.get("total_amount", 0),
                        "reason": item.get("reason", ""),
                        "change_pct": item["change_pct"],
                        "price": item["price"],
                        "score": scores[i],
                    }
                    for i, item in enumerate(institution_buy)
                ]

                # 高波动选股
                hot_money = sorted(
                    [item for item in dragon_data if abs(item.get("change_pct", 0)) > 5],
                    key=lambda x: abs(x.get("change_pct", 0)), reverse=True
                )[:10]
                result["strategies"][1]["count"] = len(hot_money)
                scores = _rank_scores(hot_money)
                result["strategies"][1]["top_stocks"] = [
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "net_amount": item["net_amount"],
                        "buy_amount": item.get("buy_amount", 0),
                        "sell_amount": item.get("sell_amount", 0),
                        "total_amount": item.get("total_amount", 0),
                        "reason": item.get("reason", ""),
                        "change_pct": item["change_pct"],
                        "price": item["price"],
                        "score": scores[i],
                    }
                    for i, item in enumerate(hot_money)
                ]

                # 溢价率选股
                premium = sorted(
                    [item for item in dragon_data if item["buy_amount"] > item["sell_amount"] * 1.5],
                    key=lambda x: x["buy_amount"] - x["sell_amount"], reverse=True
                )[:10]
                result["strategies"][2]["count"] = len(premium)
                scores = _rank_scores(premium)
                result["strategies"][2]["top_stocks"] = [
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "net_amount": item["net_amount"],
                        "buy_amount": item.get("buy_amount", 0),
                        "sell_amount": item.get("sell_amount", 0),
                        "total_amount": item.get("total_amount", 0),
                        "reason": item.get("reason", ""),
                        "change_pct": item["change_pct"],
                        "price": item["price"],
                        "score": scores[i],
                    }
                    for i, item in enumerate(premium)
                ]
        except Exception as e:
            logger.warning(f"获取策略对比数据失败: {e}")

        result = _add_meta(result)
        self._set_dragon_cache('comparison', result)
        return result

    def get_dragon_list_today(self, force_refresh: bool = False) -> dict:
        """获取今日龙虎榜"""
        dragon_date = _get_dragon_target_date()  # 龙虎榜数据日期（可能回退到昨日）
        today_date = _get_target_date()  # 今日/涨跌停池日期

        cache_key = f'dragon_today_v6_{dragon_date}'
        if not force_refresh:
            cached = self._get_dragon_cache(cache_key)
            if cached:
                return cached

        try:
            dragon_data = self._get_dragon_raw_data(date=dragon_date, force_refresh=force_refresh)

            # 分离涨幅榜和跌幅榜（龙虎榜数据）
            gainers = [item for item in dragon_data if item.get("change_pct", 0) > 0]
            losers = [item for item in dragon_data if item.get("change_pct", 0) < 0]

            # 涨跌榜：使用今日涨停池/跌停池（实时数据）
            gainers_list = []
            losers_list = []
            limit_up_count = 0
            limit_down_count = 0

            try:
                zt_pool = EastMoneyZTPool.get_zt_pool(today_date) or []
                dt_pool = EastMoneyZTPool.get_dt_pool(today_date) or []
                zb_pool = EastMoneyZTPool.get_zb_pool(today_date) or []
                
                # 标记哪些在龙虎榜上
                dragon_codes = {item["code"] for item in dragon_data}
                dragon_reason_map = {item["code"]: item.get("reason", "") for item in dragon_data}

                # 先获取全市场数据，用于严格判断涨跌停和补充缺口
                full_market = TencentSource.get_full_market(allow_stale=True)
                full_limit_up_map = {}
                full_limit_down_map = {}
                
                if full_market:
                    for row in full_market:
                        f2 = float(row.get("f2", 0) or 0)
                        code = row.get("f12", "")
                        name = row.get("f14", "")
                        lup = float(row.get("f78", 0) or 0)
                        ldn = float(row.get("f81", 0) or 0)
                        if is_limit_up(f2, lup, code, name):
                            full_limit_up_map[code] = {
                                'name': name, 'price': f2, 'change_pct': float(row.get("f3", 0) or 0),
                                'amount': float(row.get("f10", 0) or 0), 'limit_up': lup,
                            }
                        elif is_limit_down(f2, ldn, code, name):
                            full_limit_down_map[code] = {
                                'name': name, 'price': f2, 'change_pct': float(row.get("f3", 0) or 0),
                                'amount': float(row.get("f10", 0) or 0), 'limit_down': ldn,
                            }
                    
                    limit_up_count = len(full_limit_up_map)
                    limit_down_count = len(full_limit_down_map)

                # 构建涨停显示列表：
                # 1. 先从THS涨停池中筛选满足严格涨停条件的（保留连板、封单等详细信息）
                # 2. 从全市场数据补充那些不在THS里但实际涨停的
                seen_gainer_codes = set()
                zt_extra_map = {str(it.get("c", "")): it for it in (zt_pool or []) if it.get("c")}

                if zt_pool and full_limit_up_map:
                    for item in zt_pool:
                        code = str(item.get("c", ""))
                        if code not in full_limit_up_map:
                            continue
                        price_raw = item.get("p", 0) or 0
                        try:
                            price = float(price_raw) / 100 if price_raw > 100 else float(price_raw)
                        except (ValueError, TypeError):
                            continue

                        gainers_list.append({
                            "code": code,
                            "name": str(item.get("n", "")),
                            "price": round(price, 2),
                            "change_pct": round(float(item.get("zdp", 0) or 0), 2),
                            "amount": float(item.get("jje", item.get("cje", 0)) or 0),
                            "on_dragon": code in dragon_codes,
                            "reason": dragon_reason_map.get(code, ""),
                            "lbc": int(item.get("lbc", 1) or 1),
                            "fund": float(item.get("fund", 0) or 0),
                            "zbc": int(item.get("zbc", 0) or 0),
                            "hybk": str(item.get("hybk", "") or ""),
                            "fbt": str(item.get("fbt", "") or ""),
                            "hs": round(float(item.get("hs", 0) or 0), 2),
                            "lbt": str(item.get("lbt", "") or ""),
                        })
                        seen_gainer_codes.add(code)

                # 从全市场数据补充不在THS涨停池里的涨停股
                for code, info in full_limit_up_map.items():
                    if code in seen_gainer_codes:
                        continue
                    extra = zt_extra_map.get(code, {})
                    gainers_list.append({
                        "code": code,
                        "name": info['name'],
                        "price": round(info['price'], 2),
                        "change_pct": round(info['change_pct'], 2),
                        "amount": info['amount'],
                        "on_dragon": code in dragon_codes,
                        "reason": dragon_reason_map.get(code, ""),
                        "lbc": int(extra.get("lbc", 1) or 1),
                        "fund": float(extra.get("fund", 0) or 0),
                        "zbc": int(extra.get("zbc", 0) or 0),
                        "hybk": str(extra.get("hybk", "") or ""),
                        "fbt": str(extra.get("fbt", "") or ""),
                        "hs": round(float(extra.get("hs", 0) or 0), 2),
                        "lbt": str(extra.get("lbt", "") or ""),
                    })
                    seen_gainer_codes.add(code)

                # 按涨幅从高到低排序
                gainers_list.sort(key=lambda x: -x["change_pct"])

                # 构建跌停显示列表：从东财跌停池中筛选满足严格跌停条件的
                seen_loser_codes = set()
                dt_extra_map = {str(it.get("c", "")): it for it in (dt_pool or []) if it.get("c")}

                if dt_pool and full_limit_down_map:
                    for item in dt_pool:
                        code = str(item.get("c", ""))
                        if code not in full_limit_down_map:
                            continue
                        price_raw = item.get("p", 0) or 0
                        try:
                            price = float(price_raw) / 100 if price_raw > 100 else float(price_raw)
                        except (ValueError, TypeError):
                            continue

                        losers_list.append({
                            "code": code,
                            "name": str(item.get("n", "")),
                            "price": round(price, 2),
                            "change_pct": round(float(item.get("zdp", 0) or 0), 2),
                            "amount": float(item.get("jje", item.get("cje", 0)) or 0),
                            "on_dragon": code in dragon_codes,
                            "reason": dragon_reason_map.get(code, ""),
                            "limit_days": int(item.get("days", 1) or 1),
                            "fund": float(item.get("fund", 0) or 0),
                            "open_count": int(item.get("oc", 0) or 0),
                            "hybk": str(item.get("hybk", "") or ""),
                            "hs": round(float(item.get("hs", 0) or 0), 2),
                            "lbt": str(item.get("lbt", "") or ""),
                        })
                        seen_loser_codes.add(code)

                # 从全市场数据补充不在东财跌停池里的跌停股
                for code, info in full_limit_down_map.items():
                    if code in seen_loser_codes:
                        continue
                    extra = dt_extra_map.get(code, {})
                    losers_list.append({
                        "code": code,
                        "name": info['name'],
                        "price": round(info['price'], 2),
                        "change_pct": round(info['change_pct'], 2),
                        "amount": info['amount'],
                        "on_dragon": code in dragon_codes,
                        "reason": dragon_reason_map.get(code, ""),
                        "limit_days": int(extra.get("days", 1) or 1),
                        "fund": float(extra.get("fund", 0) or 0),
                        "open_count": int(extra.get("oc", 0) or 0),
                        "hybk": str(extra.get("hybk", "") or ""),
                        "hs": round(float(extra.get("hs", 0) or 0), 2),
                        "lbt": str(extra.get("lbt", "") or ""),
                    })
                    seen_loser_codes.add(code)

                # 按跌幅从大到小排序（最跌的在前）
                losers_list.sort(key=lambda x: x["change_pct"])

                logger.info(f"涨跌停池: 涨停={limit_up_count}(展示{len(gainers_list)}), 跌停={limit_down_count}(展示{len(losers_list)},pool={len(dt_pool or [])})")

                # 用腾讯行情补充/覆盖成交额（THS/push2ex 的jje/cje经常为0）
                try:
                    all_codes = [g["code"] for g in gainers_list] + [l["code"] for l in losers_list]
                    if all_codes:
                        quotes_map = TencentSource.get_quotes(all_codes)
                        for item in gainers_list + losers_list:
                            q = quotes_map.get(item["code"], {})
                            # amount_wan 单位是万元，转换为元
                            quote_amount = float(q.get("amount_wan", 0) or 0) * 10000
                            current_amount = item.get("amount") or 0
                            # 原数据为0时补充，或腾讯数据更大时覆盖
                            if quote_amount > 0 and (current_amount == 0 or quote_amount > current_amount):
                                item["amount"] = round(quote_amount, 2)
                except Exception as e:
                    logger.debug(f"补充涨跌停成交额失败: {e}")

            except Exception as e:
                logger.warning(f"获取涨跌停池失败，显示空列表: {e}")
                # 不再用龙虎榜兜底估算涨跌停数量，直接返回0避免误导
                limit_up_count = 0
                limit_down_count = 0

            # 汇总统计（前端Tab1需要）
            total_net = sum(item["net_amount"] for item in dragon_data)
            inst_buy_count = sum(1 for item in dragon_data if item["net_amount"] > 0)
            inst_sell_count = sum(1 for item in dragon_data if item["net_amount"] < 0)
            total_amount = sum(item.get("total_amount", item["buy_amount"] + item["sell_amount"]) for item in dragon_data)

            result = {
                "date": today_date,  # 今日（涨跌榜用）
                "data_date": _format_display_date(today_date),  # 今日显示日期
                "dragon_data_date": _format_display_date(dragon_date),  # 龙虎榜实际数据日期（可能为昨日）
                "update_time": _format_update_time(),
                "total": len(dragon_data),
                "stocks": dragon_data[:100],
                "gainers": gainers_list,
                "losers": losers_list,
                "limit_up": limit_up_count,
                "limit_down": limit_down_count,
                "summary": {
                    "total_net": round(total_net, 2),
                    "inst_buy_count": inst_buy_count,
                    "inst_sell_count": inst_sell_count,
                    "total_amount": round(total_amount, 2),
                },
            }

            self._set_dragon_cache(cache_key, result, ttl=self._TTL_TODAY)
            return result
        except Exception as e:
            logger.warning(f"获取今日龙虎榜失败: {e}")
            return {"date": target_date, "dragon_data_date": _format_display_date(target_date), "update_time": _format_update_time(), "total": 0, "stocks": []}

    def get_dragon_list_strategy(self, strategy_type: str = "all", 
                                   force_refresh: bool = False, top_n: int = 15,
                                   market_cap: str = None, min_amount: int = None,
                                   change_range: str = None, exclude_st: bool = False) -> dict:
        """执行龙虎榜选股策略
        
        Args:
            strategy_type: 策略类型
                - institution: 机构净买入（筛选机构席位主导的股票）
                - hot_money: 游资共振（筛选游资席位活跃的股票）
                - premium: 溢价率选股（筛选大宗交易高溢价标的）
                - all: 全部龙虎榜股票
        """
        target_date = _get_dragon_target_date()  # 实际数据日期（可能回退到昨日）
        cache_key = f'dragon_strategy_{strategy_type}_{target_date}'
        if not force_refresh:
            cached = self._get_dragon_cache(cache_key)
            if cached:
                return cached

        try:
            dragon_data = self._get_dragon_raw_data(date=target_date, force_refresh=force_refresh)
            
            result = {
                "strategy": strategy_type,
                "date": target_date,
                "dragon_data_date": _format_display_date(target_date),
                "stocks": []
            }

            if dragon_data:
                # 根据策略类型差异化筛选（前端传入: institution/synergy/resonance/premium）
                # 各策略使用不同的排序维度，不互斥但侧重不同

                filtered_data = dragon_data

                if strategy_type == "institution":
                    # 机构净买入：所有净买入为正的，按净买入额降序（放宽条件）
                    filtered_data = sorted(
                        [item for item in dragon_data if item["net_amount"] > 0],
                        key=lambda x: x["net_amount"], reverse=True
                    )
                elif strategy_type == "synergy":
                    # 游资合力板：按涨跌幅绝对值排序，侧重波动大的股票
                    filtered_data = sorted(
                        [item for item in dragon_data if abs(item.get("change_pct", 0)) > 3],
                        key=lambda x: abs(x.get("change_pct", 0)), reverse=True
                    )
                elif strategy_type == "resonance":
                    # 机构+游资共振：净买入为正且成交额大的，综合评分排序
                    filtered_data = sorted(
                        [item for item in dragon_data if item["net_amount"] > 0],
                        key=lambda x: (x["net_amount"] + abs(x.get("change_pct", 0)) * 1e6), reverse=True
                    )
                elif strategy_type == "premium":
                    # 溢价策略：买入远大于卖出，按买卖差额排序（放宽倍数）
                    filtered_data = sorted(
                        [item for item in dragon_data if item["buy_amount"] > item["sell_amount"]],
                        key=lambda x: (x["buy_amount"] - x["sell_amount"]) / max(x["sell_amount"], 1), reverse=True
                    )
                # strategy_type == "hot_money" 兼容旧接口：同 synergy
                elif strategy_type == "hot_money":
                    filtered_data = sorted(
                        [item for item in dragon_data if abs(item.get("change_pct", 0)) > 5],
                        key=lambda x: abs(x.get("change_pct", 0)), reverse=True
                    )
                # strategy_type == "all" 时使用全部数据
                
                # 策略名称映射（中文）
                strategy_names = {
                    "institution": "机构净买入",
                    "synergy": "游资合力板",
                    "resonance": "机构+游资共振",
                    "premium": "溢价策略",
                    "hot_money": "游资合力板",
                    "all": "全部龙虎榜",
                }

                seen_codes = set()
                for item in filtered_data[:top_n * 2]:
                    stock_code = item["code"]
                    if stock_code in seen_codes:
                        continue
                    if exclude_st and 'ST' in (item["name"] or "").upper():
                        continue

                    # 计算策略评分（基于净买入额和涨跌幅）
                    net_score = min(100, max(30, 50 + item.get("net_amount", 0) / 1e7 * 10))
                    # 涨跌方向修正：涨幅加分，跌幅扣分（避免推荐下跌趋势的股票）
                    change_pct = item.get("change_pct", 0)
                    if change_pct >= 0:
                        change_score = min(100, max(30, 50 + change_pct * 2))
                    else:
                        change_score = max(20, 50 + change_pct * 2)
                    score = round((net_score + change_score) / 2)

                    stock = {
                        "code": item["code"],
                        "name": item["name"],
                        "price": item["price"],
                        "net_amount": item["net_amount"],
                        "buy_amount": item["buy_amount"],
                        "sell_amount": item["sell_amount"],
                        "change_pct": item["change_pct"],
                        "direction": item["direction"],
                        "signal_type": item["direction"],
                        "reason": item["reason"],
                        "total_amount": item["total_amount"],
                        "strategy": strategy_names.get(strategy_type, strategy_type),
                        "strategy_name": strategy_names.get(strategy_type, strategy_type),
                        "score": score,
                    }
                    
                    if change_range:
                        chg = stock["change_pct"]
                        if change_range == "positive" and chg < 0:
                            continue
                        elif change_range == "negative" and chg > 0:
                            continue
                    
                    result["stocks"].append(stock)
                    seen_codes.add(stock_code)
                    
                    if len(result["stocks"]) >= top_n:
                        break

            # 补充前端期望的 time 字段（上榜日期）
            dragon_date = result.get("dragon_data_date") or result.get("date", "")
            for s in result["stocks"]:
                if not s.get("time"):
                    s["time"] = dragon_date
            self._set_dragon_cache(cache_key, result)
            return result
        except Exception as e:
            logger.warning(f"龙虎榜策略执行失败: {e}")
            return {"strategy": strategy_type, "date": target_date, "data_date": _format_display_date(target_date), "update_time": _format_update_time(), "stocks": []}

    def get_dragon_list_history(self, date: str) -> dict:
        """获取历史龙虎榜"""
        try:
            # 统一日期格式：支持 YYYY-MM-DD 和 YYYYMMDD
            date_str = date.replace("-", "")
            
            # 使用统一方法获取数据
            dragon_data = self._get_dragon_raw_data(date=date_str)
            
            result = {
                "date": date_str,
                "total": len(dragon_data),
                "stocks": dragon_data[:50]
            }

            return result
        except Exception as e:
            logger.warning(f"获取历史龙虎榜失败 ({date}): {e}")
            return {"date": date, "total": 0, "stocks": []}

    def get_multi_factor_picks(self, top_n: int = 10, market_cap: str = None,
                                    min_amount: int = None, change_range: str = None,
                                    exclude_st: bool = False, force_refresh: bool = False) -> dict:
        """多因子选股策略 — 全市场扫描，基于趋势突破+量价配合评分

候选池：全市场（不再仅限涨停池），按成交额预筛选后计算技术指标。
评分：使用统一因子引擎 StandardScorer(trend_breakout) 模板。
"""
        target_date = _get_strategy_target_date()
        cache_key = f'multi_factor_{top_n}_{market_cap or "all"}_{min_amount or 0}_{change_range or "all"}_{exclude_st}_{target_date}'

        if not force_refresh:
            cached = self._get_dragon_cache(cache_key, namespace=NS_STRATEGY)
            if cached is not None:
                return cached
            # 非交易时间：返回stale缓存
            if not is_trading_hours():
                stale = self._get_stale_cache(cache_key, namespace=NS_STRATEGY)
                if stale is not None:
                    return stale

        result = {
            "strategy": "multi_factor",
            "stocks": []
        }

        try:
            # === 全市场扫描（替代涨停池）===
            full_market = TencentSource.get_full_market()
            if not full_market:
                logger.info("全市场数据为空，无多因子选股数据")
                self._set_dragon_cache(cache_key, result, namespace=NS_STRATEGY)
                return _add_meta(result, target_date)

            # 第一步：快速预筛选（价格/涨跌幅/ST过滤）
            pre_filtered = []
            for row in full_market:
                code = str(row.get("f12", ""))
                name = str(row.get("f14", "") or "")
                price = float(row.get("f2", 0) or 0)
                change_pct = float(row.get("f3", 0) or 0)

                if not code or len(code) != 6:
                    continue
                if exclude_st and 'ST' in name.upper():
                    continue
                # 排除价格过低、涨跌停（涨停追高风险/跌停暴雷风险）
                if price < 2.0:
                    continue
                if change_range == "positive" and change_pct <= 0:
                    continue
                elif change_range == "negative" and change_pct >= 0:
                    continue

                pre_filtered.append({
                    "code": code, "name": name, "price": price, "change_pct": change_pct,
                    "amount": float(row.get("f10", 0) or 0),
                    "turnover": float(row.get("f15", 0) or 0),
                })

            # 第二步：按成交额排序，取活跃股（限制K线请求量）
            pre_filtered.sort(key=lambda x: x["amount"], reverse=True)
            max_kline_stocks = min(len(pre_filtered), 300)
            candidates_pool = pre_filtered[:max_kline_stocks]

            # 第三步：市值/成交额筛选（获取实时行情）
            quote_map = {}
            if market_cap or min_amount:
                try:
                    all_codes = [item["code"] for item in candidates_pool[:top_n * 3]]
                    quotes = TencentSource.get_quotes(all_codes)
                    quote_map = {q_code: q for q_code, q in quotes.items()}
                except Exception as e:
                    logger.debug(f"多因子获取实时行情失败: {e}")

            # 第四步：批量获取K线（并行，利用缓存）
            codes_to_fetch = [item["code"] for item in candidates_pool]
            batch_klines = pytdx_data.get_batch_klines(codes_to_fetch, period=4, count=60, max_workers=10)

            # 第五步：计算因子 + 纯技术评分（不获取基本面，避免对300只股票串行网络请求）
            code_map = {item["code"]: item for item in candidates_pool}
            tech_candidates = []
            for code, klines in batch_klines.items():
                if not klines or len(klines) < 20:
                    continue
                item = code_map.get(code)
                if not item:
                    continue

                # 市值/成交额筛选
                q = quote_map.get(code, {})
                mcap_yi = float(q.get("mcap_yi", 0) or 0)
                amount_wan = float(q.get("amount_wan", 0) or 0)
                if market_cap == "large" and mcap_yi < 500:
                    continue
                elif market_cap == "mid" and (mcap_yi < 100 or mcap_yi >= 500):
                    continue
                elif market_cap == "small" and mcap_yi >= 100:
                    continue
                if min_amount and amount_wan < min_amount:
                    continue

                indicators = self._calc_indicators_from_klines(code, klines)
                if not indicators:
                    continue

                tech_candidates.append({
                    "code": code,
                    "name": item["name"],
                    "price": round(item["price"], 2),
                    "change_pct": round(item["change_pct"], 2),
                    **indicators,
                    "score": indicators['score'],
                })

            # 第六步：按技术分排序，仅对 top_n*3 只获取基本面数据计算综合评分
            tech_candidates.sort(key=lambda x: x["score"], reverse=True)
            fund_candidates = tech_candidates[:max(top_n * 3, top_n)]
            for stock in fund_candidates:
                code = stock["code"]
                factors_data = stock.get("factors") or {}
                try:
                    financial_data = _fetch_real_financial(code)
                    combined_score = FundamentalFactorCalculator.compute_combined_score(
                        factors_data, financial_data, technical_weight=0.6, fundamental_weight=0.4
                    )
                    fund_factors = FundamentalFactorCalculator.compute_from_financial(financial_data) or {}
                    stock["score"] = combined_score
                    stock["pe_score"] = fund_factors.get('pe_score')
                    stock["pb_score"] = fund_factors.get('pb_score')
                    stock["roe_score"] = fund_factors.get('roe_score')
                except Exception as e:
                    logger.debug(f"获取基本面数据失败 ({code}): {e}")
                    stock["pe_score"] = None
                    stock["pb_score"] = None
                    stock["roe_score"] = None

            result["stocks"] = sorted(fund_candidates, key=lambda x: x["score"], reverse=True)[:top_n]
            # 增加前端期望的字段名别名
            for s in result["stocks"]:
                s["momentum_score"] = s.get("momentum", 0)
                s["liquidity_score"] = s.get("liquidity", 0)
                s["technical_score"] = s.get("tech", 0)
                s["composite_score"] = s.get("score", 0)
            logger.info(f"多因子选股: 候选{len(tech_candidates)}, 取基本面{len(fund_candidates)}, 输出{len(result['stocks'])}")

        except Exception as e:
            logger.error(f"多因子选股失败: {e}", exc_info=True)

        # 回测验证：对所有结果计算macd策略回测因子
        try:
            all_codes = [p['code'] for p in result["stocks"] if p.get('code')]
            if all_codes:
                backtest_factors = BacktestFactorCalculator.compute_batch_backtest_factors(
                    all_codes, strategy_name='macd', days=120
                )
                for pick in result["stocks"]:
                    code = pick['code']
                    if code in backtest_factors and backtest_factors[code]:
                        bt = backtest_factors[code]
                        pick['backtest_score'] = bt.get('composite_score', None)
                        pick['backtest_win_rate'] = bt.get('win_rate', None)
                        pick['backtest_sharpe'] = bt.get('sharpe_ratio', None)
        except Exception as e:
            logger.debug(f"多因子选股回测验证失败: {e}")

        final_result = _add_meta(result, target_date)
        self._set_dragon_cache(cache_key, final_result, namespace=NS_STRATEGY)
        return final_result

    def predict_ml_stocks(self, top_n: int = 10, market_cap: str = None, min_amount: int = None, change_range: str = None, exclude_st: bool = False, force_refresh: bool = False) -> dict:
        """ML选股 - 全市场扫描，用技术指标综合评分筛选有上涨潜力的股票"""
        target_date = _get_strategy_target_date()
        cache_key = f'ml_prediction_{top_n}_{market_cap or "all"}_{min_amount or 0}_{change_range or "all"}_{exclude_st}_{target_date}'

        if not force_refresh:
            cached = self._get_dragon_cache(cache_key, namespace=NS_STRATEGY)
            if cached is not None:
                return cached

        try:
            result = {
                "strategy": "ml_prediction",
                "model": "lightgbm",
                "stocks": []
            }

            # 用腾讯财经获取全市场行情（不封IP）
            full_market = TencentSource.get_full_market()
            if not full_market:
                logger.info("腾讯全市场数据为空，无ML选股数据")
                return result

            # 第一步：用腾讯行情快速预筛选（不需要K线）
            pre_filter_codes = []
            for row in full_market:
                code = str(row.get("f12", ""))
                name = str(row.get("f14", "") or "")
                price = float(row.get("f2", 0) or 0)
                change_pct = float(row.get("f3", 0) or 0)

                if not code or len(code) != 6:
                    continue
                if exclude_st and 'ST' in name.upper():
                    continue
                # 排除价格过低、涨幅过大追高风险、跌幅过大暴雷风险
                if price < 2.0 or change_pct > 8.0 or change_pct < -7.0:
                    continue

                pre_filter_codes.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "change_pct": change_pct,
                    # 保留成交额和换手率用于活跃度排序
                    "amount": float(row.get("f10", 0) or 0),
                    "turnover": float(row.get("f15", 0) or 0),
                })

            # 第二步：涨跌幅筛选（前端参数）
            if change_range:
                def _change_filter(item):
                    cpct = item["change_pct"]
                    if change_range == "up": return cpct > 0
                    elif change_range == "down": return cpct < 0
                    elif change_range == "no_limit_up": return cpct < 9.5
                    elif change_range == "no_limit_down": return cpct > -9.5
                    return True
                pre_filter_codes = [item for item in pre_filter_codes if _change_filter(item)]

            # 第三步：按活跃度过滤，限制K线请求数量（成交额+换手率综合排序）
            pre_filter_codes.sort(
                key=lambda x: (x["amount"] * 0.7 + x["turnover"] * 1e6 * 0.3),
                reverse=True
            )
            max_kline_stocks = min(len(pre_filter_codes), 200)
            pre_filter_codes = pre_filter_codes[:max_kline_stocks]

            # 第四步：市值/成交额筛选（获取实时行情）
            quote_map_ml = {}
            if market_cap or min_amount:
                try:
                    all_codes_ml = [item["code"] for item in pre_filter_codes[:top_n * 3]]
                    quotes_ml = TencentSource.get_quotes(all_codes_ml)
                    quote_map_ml = {q_code: q for q_code, q in quotes_ml.items()}
                except Exception as e:
                    logger.debug(f"ML选股获取实时行情失败: {e}")

            # 第三步：批量获取K线（并行，利用缓存）
            codes_to_fetch = [item["code"] for item in pre_filter_codes]
            batch_klines = pytdx_data.get_batch_klines(codes_to_fetch, period=4, count=60, max_workers=10)

            # 第五步：计算指标并评分
            candidates = []
            code_map = {item["code"]: item for item in pre_filter_codes}

            for code, klines in batch_klines.items():
                if not klines or len(klines) < 20:
                    continue

                item = code_map.get(code)
                if not item:
                    continue

                # 市值/成交额筛选
                q_ml = quote_map_ml.get(code, {})
                mcap_yi_ml = float(q_ml.get("mcap_yi", 0) or 0)
                amount_wan_ml = float(q_ml.get("amount_wan", 0) or 0)
                if market_cap == "large" and mcap_yi_ml < 500:
                    continue
                elif market_cap == "mid" and (mcap_yi_ml < 100 or mcap_yi_ml >= 500):
                    continue
                elif market_cap == "small" and mcap_yi_ml >= 100:
                    continue
                if min_amount and amount_wan_ml < min_amount:
                    continue

                # 直接计算指标（复用_calc_stock_indicators逻辑但传入已有kline）
                indicators = self._calc_indicators_from_klines(code, klines)
                if not indicators:
                    continue

                score = indicators['score']
                momentum = indicators['momentum']
                rsi6 = indicators['rsi6']
                kdj_j = indicators['kdj_j']
                vol_ratio = indicators['vol_ratio']

                # 尝试使用真实ML模型预测（如果可用）
                ml_result = None
                try:
                    if ml_model_service.ensure_models_loaded():
                        # 从因子提取ML需要的特征（键名与训练模型一致）
                        factors_data = indicators.get("factors", {}) or {}
                        kdj_info = factors_data.get("kdj", {}) or {}
                        macd_info = factors_data.get("macd", {}) or {}
                        boll_info = factors_data.get("boll", {}) or {}
                        features_for_ml = {
                            "RSI_6": factors_data.get("rsi6", 50),
                            "RSI_14": factors_data.get("rsi14", 50),
                            "KDJ_K": kdj_info.get("k", 50),
                            "KDJ_D": kdj_info.get("d", 50),
                            "KDJ_J": kdj_info.get("j", 50),
                            "MACD_DIF": macd_info.get("dif", 0) if macd_info else 0,
                            "MACD_DEA": macd_info.get("dea", 0) if macd_info else 0,
                            "MACD_HIST": macd_info.get("macd_bar", 0) if macd_info else 0,
                            "BOLL_PCT": boll_info.get("price_position", 50),
                            "VOL_RATIO": vol_ratio,
                        }
                        
                        ml_result = ml_model_service.predict_single(features_for_ml)
                except Exception as e:
                    logger.debug(f"ML预测失败 ({code}): {e}")
                
                # 使用ML模型评分或降级到因子引擎
                if ml_result and ml_result.get('combined_score') is not None:
                    final_score = int(ml_result['combined_score'] * 100)
                    prediction_label = ml_result.get('prediction', '中性')
                    confidence = ml_result.get('confidence', 0.5)
                else:
                    # 降级：使用因子引擎评分
                    factors_data = indicators.get("factors") or {}
                    base_score = StandardScorer.score(factors_data, "balanced") if factors_data else score
                    
                    bonus = 0
                    if 40 <= momentum <= 75:
                        bonus += 3
                    if rsi6 < 70 and rsi6 > 30:
                        bonus += 2
                    kdj_info = factors_data.get("kdj", {}) if factors_data else {}
                    if kdj_info.get("signal") == "golden_cross":
                        bonus += 5
                    if 1.0 <= vol_ratio <= 2.5:
                        bonus += 3
                    
                    final_score = min(98, base_score + bonus)
                    prediction_label = '中性'
                    confidence = 0.5

                candidates.append({
                    "code": code,
                    "name": item["name"],
                    "price": round(item["price"], 2),
                    "change_pct": round(item["change_pct"], 2),
                    **indicators,
                    "score": final_score,
                    "ml_score": final_score,
                    "prediction": prediction_label,
                    "confidence": confidence,
                    "features": f"动量{momentum} RSI6={rsi6} KDJ-J={kdj_j} 量比{vol_ratio}",
                })

            # 按综合得分降序排列，取topN
            candidates.sort(key=lambda x: x["score"], reverse=True)
            result["stocks"] = candidates[:top_n]
            logger.info(f"ML选股: 全市场{len(full_market)}只, 预筛选{len(pre_filter_codes)}, 候选{len(candidates)}, 输出{len(result['stocks'])}")

            # 回测验证：对所有结果计算balanced策略回测因子
            try:
                all_codes = [p['code'] for p in result["stocks"] if p.get('code')]
                if all_codes:
                    backtest_factors = BacktestFactorCalculator.compute_batch_backtest_factors(
                        all_codes, strategy_name='balanced', days=120
                    )
                    for pick in result["stocks"]:
                        code = pick['code']
                        if code in backtest_factors and backtest_factors[code]:
                            bt = backtest_factors[code]
                            pick['backtest_score'] = bt.get('composite_score', None)
                            pick['backtest_win_rate'] = bt.get('win_rate', None)
                            pick['backtest_sharpe'] = bt.get('sharpe_ratio', None)
            except Exception as e:
                logger.debug(f"ML选股回测验证失败: {e}")

            self._set_dragon_cache(cache_key, result, ttl=self._TTL_STRATEGY, namespace=NS_STRATEGY)
            return _add_meta(result, target_date)
        except Exception as e:
            logger.warning(f"ML预测选股失败: {e}")
            return {"strategy": "ml_prediction", "model": "lightgbm", "stocks": []}

    @classmethod
    def _calc_indicators_from_klines(cls, code: str, klines: list) -> dict:
        """基于已有K线数据计算技术指标（避免重复网络请求）"""
        try:
            closes = [k['close'] for k in klines]
            volumes = [k['volume'] for k in klines]
            highs = [k['high'] for k in klines]
            lows = [k['low'] for k in klines]

            return cls._compute_technical_indicators(closes, volumes, highs, lows)
        except Exception as e:
            logger.debug(f"计算指标失败 ({code}): {e}")
            return None

    def get_low_absorption_picks(self, top_n: int = 10, market_cap: str = None, min_amount: int = None, change_range: str = None, exclude_st: bool = False, force_refresh: bool = False) -> dict:
        """低吸企稳选股 - 筛选短期急跌+出现超卖/缩量企稳信号的股票"""
        target_date = _get_strategy_target_date()
        cache_key = f'low_absorption_{top_n}_{market_cap or "all"}_{min_amount or 0}_{change_range or "all"}_{exclude_st}_{target_date}'

        if not force_refresh:
            cached = self._get_dragon_cache(cache_key, namespace=NS_STRATEGY)
            if cached is not None:
                return cached

        try:
            result = {
                "strategy": "low_absorption",
                "stocks": []
            }

            # 用腾讯财经获取全市场行情（不封IP，含涨跌幅/跌停价）
            full_market = TencentSource.get_full_market()
            if not full_market:
                logger.info("腾讯全市场数据为空，无低吸数据")
                return result

            # 第一步：快速预筛选跌幅适中的股票
            pre_filter_codes = []
            for row in full_market:
                code = str(row.get("f12", ""))
                name = str(row.get("f14", "") or "")
                price = float(row.get("f2", 0) or 0)
                change_pct = float(row.get("f3", 0) or 0)
                limit_down = float(row.get("f81", 0) or 0)

                if not code or len(code) != 6:
                    continue
                if exclude_st and 'ST' in name.upper():
                    continue
                if price < 2.0:
                    continue
                # 今日跌幅3%-10%（排除跌停股，避免接飞刀）
                if change_pct >= -3.0 or change_pct <= -10.5:
                    continue
                # 排除接近跌停的（现价与跌停价差距<1%，说明可能封死跌停）
                if limit_down > 0 and (price - limit_down) / limit_down < 0.01:
                    continue

                pre_filter_codes.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "change_pct": change_pct,
                    "amount": float(row.get("f10", 0) or 0),
                })

            # 涨跌幅筛选（前端参数，低吸策略默认只看下跌股）
            if change_range == "up":
                pre_filter_codes = [item for item in pre_filter_codes if item["change_pct"] > 0]
            elif change_range == "down":
                pass  # 已经是跌幅筛选

            # 按成交额排序，取活跃股
            pre_filter_codes.sort(key=lambda x: x.get("amount", 0), reverse=True)

            # 市值/成交额筛选（获取实时行情）
            quote_map_la = {}
            if market_cap or min_amount:
                try:
                    all_codes_la = [item["code"] for item in pre_filter_codes[:top_n * 3]]
                    quotes_la = TencentSource.get_quotes(all_codes_la)
                    quote_map_la = {q_code: q for q_code, q in quotes_la.items()}
                except Exception as e:
                    logger.debug(f"低吸选股获取实时行情失败: {e}")

            # 第二步：批量获取K线（并行，利用缓存）
            codes_to_fetch = [item["code"] for item in pre_filter_codes]
            batch_klines = pytdx_data.get_batch_klines(codes_to_fetch, period=4, count=60, max_workers=10)

            # 第三步：计算指标并筛选有企稳信号的
            candidates = []
            code_map = {item["code"]: item for item in pre_filter_codes}

            for code, klines in batch_klines.items():
                if not klines or len(klines) < 20:
                    continue

                item = code_map.get(code)
                if not item:
                    continue

                # 市值/成交额筛选
                q_la = quote_map_la.get(code, {})
                mcap_yi_la = float(q_la.get("mcap_yi", 0) or 0)
                amount_wan_la = float(q_la.get("amount_wan", 0) or 0)
                if market_cap == "large" and mcap_yi_la < 500:
                    continue
                elif market_cap == "mid" and (mcap_yi_la < 100 or mcap_yi_la >= 500):
                    continue
                elif market_cap == "small" and mcap_yi_la >= 100:
                    continue
                if min_amount and amount_wan_la < min_amount:
                    continue

                indicators = self._calc_indicators_from_klines(code, klines)
                if not indicators:
                    continue

                kdj_j_val = indicators['kdj_j']
                vol_ratio_val = indicators['vol_ratio']
                decline_20d_val = indicators['decline_20d']
                rsi6_val = indicators['rsi6']

                # 必须有超卖信号才能入选（RSI<35 或 KDJ-J<25）
                has_oversold = (rsi6_val < 35) or (kdj_j_val < 25)
                if not has_oversold:
                    continue

                # 使用统一因子引擎评分（oversold_bounce模板）
                factors = indicators.get("factors") or {}
                extra_factors = {"decline_20d": decline_20d_val}
                stability_score = StandardScorer.score(factors, "oversold_bounce", extra_factors) if factors else indicators['score']
                
                # 超卖加分（在基础评分之上）
                oversold_bonus = 0
                if rsi6_val < 30:
                    oversold_bonus += 8
                elif rsi6_val < 35:
                    oversold_bonus += 4
                if kdj_j_val < 20:
                    oversold_bonus += 8
                elif kdj_j_val < 25:
                    oversold_bonus += 4
                # 缩量筑底加分（量比<1.0说明抛压减轻）
                if vol_ratio_val < 0.8:
                    oversold_bonus += 6
                elif vol_ratio_val < 1.2:
                    oversold_bonus += 3
                # 20日有足够跌幅才值得低吸（>5%才有反弹空间）
                if decline_20d_val > 10:
                    oversold_bonus += 5
                elif decline_20d_val > 5:
                    oversold_bonus += 3

                final_score = min(95, stability_score + oversold_bonus)

                # 构建选股理由
                reasons_parts = []
                if rsi6_val < 30:
                    reasons_parts.append("RSI超卖")
                elif rsi6_val < 35:
                    reasons_parts.append("RSI偏低")
                if kdj_j_val < 20:
                    reasons_parts.append("KDJ-J深度超卖")
                elif kdj_j_val < 25:
                    reasons_parts.append("KDJ-J超卖")
                if vol_ratio_val < 0.8:
                    reasons_parts.append("缩量筑底")
                elif vol_ratio_val > 1.5:
                    reasons_parts.append("放量企稳")
                else:
                    reasons_parts.append("量能平稳")
                reasons_parts.append(f"20日跌幅{decline_20d_val}%")

                candidates.append({
                    "code": code,
                    "name": item["name"],
                    "price": round(item["price"], 2),
                    "change_pct": round(item["change_pct"], 2),
                    **indicators,
                    "score": final_score,
                    "absorption_score": oversold_bonus,
                    "stability_score": stability_score,
                    "composite_score": final_score,
                    "volume_ratio": vol_ratio_val,
                    "reason": "; ".join(reasons_parts),
                    "reasons": "; ".join(reasons_parts),
                })

            # 按企稳得分降序排列，取topN
            candidates.sort(key=lambda x: x["score"], reverse=True)
            result["stocks"] = candidates[:top_n]
            logger.info(f"低吸企稳选股: 预筛选{len(pre_filter_codes)}只, 候选{len(candidates)}, 输出{len(result['stocks'])}只")

            # 回测验证：对所有结果计算kdj策略回测因子
            try:
                all_codes = [p['code'] for p in result["stocks"] if p.get('code')]
                if all_codes:
                    backtest_factors = BacktestFactorCalculator.compute_batch_backtest_factors(
                        all_codes, strategy_name='kdj', days=120
                    )
                    for pick in result["stocks"]:
                        code = pick['code']
                        if code in backtest_factors and backtest_factors[code]:
                            bt = backtest_factors[code]
                            pick['backtest_score'] = bt.get('composite_score', None)
                            pick['backtest_win_rate'] = bt.get('win_rate', None)
                            pick['backtest_sharpe'] = bt.get('sharpe_ratio', None)
            except Exception as e:
                logger.debug(f"低吸选股回测验证失败: {e}")

            self._set_dragon_cache(cache_key, result, ttl=self._TTL_STRATEGY, namespace=NS_STRATEGY)
            return result
        except Exception as e:
            logger.warning(f"低吸策略选股失败: {e}")
            empty_result = {"strategy": "low_absorption", "stocks": []}
            self._set_dragon_cache(cache_key, empty_result, ttl=60, namespace=NS_STRATEGY)
            return empty_result

    def train_ml_model(self, days: int = 250, stocks: int = 100, model: str = "lightgbm") -> dict:
        """训练ML选股模型（调用 ml_stock_picker.py）"""
        import subprocess
        import os

        try:
            # 定位训练脚本路径
            script_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "skills", "ml-stock-picker")
            script_path = os.path.join(script_dir, "ml_stock_picker.py")

            if not os.path.exists(script_path):
                return {
                    "status": "error",
                    "message": f"训练脚本不存在: {script_path}"
                }

            # 执行训练（超时600秒=10分钟）
            logger.info(f"开始ML模型训练: days={days}, stocks={stocks}, model={model}")
            result = subprocess.run(
                ["python", script_path, "train", "--days", str(days), "--stock-count", str(stocks), "--model", model],
                capture_output=True, timeout=600, cwd=script_dir,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}
            )

            if result.returncode == 0:
                # 读取训练报告
                report_path = os.path.join(script_dir, "ml_output", "train_report.json")
                metrics = {}
                if os.path.exists(report_path):
                    import json
                    with open(report_path, 'r', encoding='utf-8') as f:
                        report = json.load(f)
                        metrics = report.get("classifier_metrics", {})

                return {
                    "status": "success",
                    "model": model,
                    "training_days": days,
                    "training_stocks": stocks,
                    "metrics": metrics,
                    "message": "ML模型训练完成",
                    "output_files": [
                        "ml_output/model_classifier.pkl",
                        "ml_output/model_regressor.pkl",
                        "ml_output/feature_importance.json",
                        "ml_output/train_report.json"
                    ]
                }
            else:
                stderr = result.stderr.decode("utf-8", errors="replace")[-500:] if result.stderr else "未知错误"
                return {
                    "status": "error",
                    "message": f"训练失败: {stderr}"
                }

        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "训练超时（超过10分钟）"}
        except Exception as e:
            logger.error(f"ML模型训练异常: {e}")
            return {"status": "error", "message": str(e)}

    def get_ml_model_status(self) -> dict:
        """获取ML模型状态"""
        try:
            info = ml_model_service.get_model_info()
            # 检查模型文件修改时间
            import os
            clf_path = info.get("classifier_file", "")
            reg_path = info.get("regressor_file", "")

            last_train_time = None
            if clf_path and os.path.exists(clf_path):
                mtime = os.path.getmtime(clf_path)
                from datetime import datetime
                last_train_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

            return {
                "loaded": info["classifier_loaded"] or info["regressor_loaded"],
                "features": info["feature_count"],
                "last_trained": last_train_time,
                "model_dir": info.get("model_dir", ""),
                "classifier_exists": info.get("classifier_exists", False),
                "regressor_exists": info.get("regressor_exists", False),
            }
        except Exception as e:
            logger.error(f"获取ML模型状态失败: {e}")
            return {"loaded": False, "features": 0, "error": str(e)}

    @staticmethod
    def _calc_continuous_inflow(code: str, max_days: int = 10) -> int:
        """已废弃：push2his.eastmoney.com 长期不可用，连续流入字段已下线。"""
        return -1

    def get_capital_flow_picks(self, top_n: int = 10, market_cap: str = None,
                                    min_amount: int = None, change_range: str = None,
                                    exclude_st: bool = False, force_refresh: bool = False) -> dict:
        """资金流选股 — 优先龙虎榜数据（快速），全市场兜底"""
        target_date = _get_strategy_target_date()
        cache_key = f'capital_flow_{top_n}_{market_cap or "all"}_{min_amount or 0}_{change_range or "all"}_{exclude_st}_{target_date}'

        if not force_refresh:
            cached = self._get_dragon_cache(cache_key, namespace=NS_STRATEGY)
            if cached is not None:
                return cached
            if not is_trading_hours():
                stale = self._get_stale_cache(cache_key, namespace=NS_STRATEGY)
                if stale is not None:
                    return stale

        # 龙虎榜数据16:30后才发布，_get_dragon_raw_data()内部自动回退到上一交易日
        dragon_date = _get_dragon_target_date()
        result = {
            "strategy": "capital_flow",
            "stocks": [],
            "continuous_flow": [],
            "volume_price": [],
            "dragon_data_date": _format_display_date(dragon_date),
        }

        dragon_data = self._get_dragon_raw_data()
        if not dragon_data:
            # 龙虎榜无数据时，用全市场量价数据填充 volume_price（兜底）
            try:
                from app.core.data_sources import TencentSource
                full_market = TencentSource.get_full_market(allow_stale=True)
                if full_market:
                    sorted_by_vol = sorted(full_market, key=lambda x: float(x.get("vol_ratio", 1) or 1), reverse=True)
                    for item in sorted_by_vol[:max(top_n // 2, 3)]:
                        code = str(item.get("code", ""))
                        name = str(item.get("name", "") or "")
                        if exclude_st and 'ST' in name.upper():
                            continue
                        result["volume_price"].append({
                            "code": code,
                            "name": name,
                            "price": float(item.get("price", 0) or 0),
                            "change_pct": float(item.get("change_pct", 0) or 0),
                            "volume_ratio": float(item.get("vol_ratio", 1) or 1),
                            "amount_ratio": round(float(item.get("vol_ratio", 1) or 1) * 1.1, 2),
                            "turnover_pct": float(item.get("turnover_pct") or item.get("hs") or 0),
                            "divergence": _classify_divergence(float(item.get("change_pct", 0) or 0), float(item.get("vol_ratio", 1) or 1)) or "正常",
                        })
            except Exception as e:
                logger.debug(f"量价配合分析兜底数据获取失败: {e}")
            return result

        sorted_by_net = sorted(dragon_data, key=lambda x: x.get("net_amount", 0), reverse=True)

        # 获取实时行情用于市值/成交额筛选
        quote_map = {}
        if market_cap or min_amount:
            try:
                from app.core.data_sources import TencentSource
                all_codes = [item["code"] for item in sorted_by_net[:top_n * 2]]
                quotes = TencentSource.get_quotes(all_codes)
                quote_map = {q_code: q for q_code, q in quotes.items()}
            except Exception as e:
                logger.debug(f"资金流获取实时行情失败: {e}")

        # 预计算indicators缓存
        indicators_cache = {}
        def _get_indicators(code):
            if code not in indicators_cache:
                indicators_cache[code] = self._calc_stock_indicators(code)
            return indicators_cache.get(code)

        # 收集候选股票（应用筛选条件）
        candidates = []
        for item in sorted_by_net[:top_n * 2]:
            name = item.get("name", "") or ""
            if exclude_st and 'ST' in name.upper():
                continue

            change_pct = float(item.get("change_pct", 0) or 0)
            if change_range == "positive" and change_pct < 0:
                continue
            elif change_range == "negative" and change_pct > 0:
                continue

            q = quote_map.get(item["code"], {})
            mcap_yi = float(q.get("mcap_yi", 0) or 0)
            amount_wan = float(q.get("amount_wan", 0) or 0)

            if market_cap == "large" and mcap_yi < 500:
                continue
            elif market_cap == "mid" and (mcap_yi < 100 or mcap_yi >= 500):
                continue
            elif market_cap == "small" and mcap_yi >= 100:
                continue

            if min_amount and amount_wan < min_amount:
                continue

            candidates.append(item)

        # 连续流入字段已下线（push2his.eastmoney.com 不可用，且 push2 实时资金流历史数据按股票粒度查询会
        # 严重拖慢主流程，故 continuous_flow 子列表也置空）

        # 构建主列表
        for item in candidates[:top_n]:
            change_pct = float(item.get("change_pct", 0) or 0)
            main_net_inflow = float(item.get("net_amount", 0) or 0)

            indicators = _get_indicators(item["code"])
            vol_ratio = indicators['vol_ratio'] if indicators else 1.0
            score = indicators['score'] if indicators else 50

            divergence_val = _classify_divergence(change_pct, vol_ratio) or "无明显特征"

            result["stocks"].append({
                "code": item["code"],
                "name": item.get("name", "") or "",
                "price": float(item.get("price", 0) or 0),
                "change_pct": change_pct,
                "main_net_inflow": main_net_inflow,
                "divergence": divergence_val,
                "vol_ratio": round(vol_ratio, 2),
                "turnover_pct": float(item.get("turnover_pct") or item.get("turnover") or 0),
                "score": score,
            })

        # 连续流入子列表：已下线（数据源不可用），直接置空保持接口兼容
        result["continuous_flow"] = []

        # 量价关系子列表
        for item in candidates[:max(top_n // 2, 3)]:
            indicators = _get_indicators(item["code"])
            vol_ratio = indicators['vol_ratio'] if indicators else 1.0
            result["volume_price"].append({
                "code": item["code"],
                "name": item.get("name", "") or "",
                "price": float(item.get("price", 0) or 0),
                "change_pct": float(item.get("change_pct", 0) or 0),
                "volume_ratio": vol_ratio,
                "amount_ratio": round(vol_ratio * 1.1, 2),
                "turnover_pct": float(item.get("turnover_pct") or item.get("turnover") or 0),
                "divergence": _classify_divergence(float(item.get("change_pct", 0) or 0), vol_ratio) or "正常",
            })

        # 兜底：如果候选为空或量价数据不足，从全市场获取
        if len(result["volume_price"]) < 3:
            try:
                from app.core.data_sources import TencentSource
                full_market = TencentSource.get_full_market(allow_stale=True)
                if full_market:
                    existing_codes = {v["code"] for v in result["volume_price"]}
                    sorted_by_vol = sorted(full_market, key=lambda x: float(x.get("vol_ratio", 1) or 1), reverse=True)
                    for item in sorted_by_vol[:max(top_n // 2, 5)]:
                        code = str(item.get("code", ""))
                        name = str(item.get("name", "") or "")
                        if exclude_st and 'ST' in name.upper():
                            continue
                        if code in existing_codes:
                            continue
                        result["volume_price"].append({
                            "code": code,
                            "name": name,
                            "price": float(item.get("price", 0) or 0),
                            "change_pct": float(item.get("change_pct", 0) or 0),
                            "volume_ratio": float(item.get("vol_ratio", 1) or 1),
                            "amount_ratio": round(float(item.get("vol_ratio", 1) or 1) * 1.1, 2),
                            "turnover_pct": float(item.get("turnover_pct") or item.get("hs") or 0),
                            "divergence": _classify_divergence(float(item.get("change_pct", 0) or 0), float(item.get("vol_ratio", 1) or 1)) or "正常",
                        })
                        if len(result["volume_price"]) >= max(top_n // 2, 3):
                            break
            except Exception as e:
                logger.debug(f"量价配合分析兜底数据获取失败: {e}")

        logger.info(f"资金流选股: {len(result['stocks'])}只, 量价配合{len(result['volume_price'])}只, 候选{len(candidates)}只")

        # 回测验证：对所有stocks结果计算capital_resonance策略回测因子
        try:
            all_codes = [p['code'] for p in result["stocks"] if p.get('code')]
            if all_codes:
                backtest_factors = BacktestFactorCalculator.compute_batch_backtest_factors(
                    all_codes, strategy_name='capital_resonance', days=120
                )
                for pick in result["stocks"]:
                    code = pick['code']
                    if code in backtest_factors and backtest_factors[code]:
                        bt = backtest_factors[code]
                        pick['backtest_score'] = bt.get('composite_score', None)
                        pick['backtest_win_rate'] = bt.get('win_rate', None)
                        pick['backtest_sharpe'] = bt.get('sharpe_ratio', None)
        except Exception as e:
            logger.debug(f"资金流选股回测验证失败: {e}")

        # 回测验证：对所有volume_price结果也计算回测因子
        try:
            vp_codes = [p['code'] for p in result["volume_price"] if p.get('code')]
            if vp_codes:
                vp_backtest_factors = BacktestFactorCalculator.compute_batch_backtest_factors(
                    vp_codes, strategy_name='capital_resonance', days=120
                )
                for pick in result["volume_price"]:
                    code = pick['code']
                    if code in vp_backtest_factors and vp_backtest_factors[code]:
                        bt = vp_backtest_factors[code]
                        pick['backtest_score'] = bt.get('composite_score', None)
                        pick['backtest_win_rate'] = bt.get('win_rate', None)
                        pick['backtest_sharpe'] = bt.get('sharpe_ratio', None)
        except Exception as e:
            logger.debug(f"资金流选股量价数据回测验证失败: {e}")

        self._set_dragon_cache(cache_key, result, namespace=NS_STRATEGY)
        return result

    def _analyze_volume_price_divergence(self, code: str) -> dict | None:
        """分析单只股票的量价背离关系，返回分析结果或None"""
        try:
            klines = pytdx_data.get_kline(code, period=4, count=60)
            if not klines or len(klines) < 20:
                return None

            closes = [k['close'] for k in klines]
            volumes = [k['volume'] for k in klines]
            amounts = [k.get('amount', 0) for k in klines]

            if not closes or not volumes:
                return None

            # 价格趋势：20日均线方向
            ma5_price = sum(closes[-5:]) / 5
            ma20_price = sum(closes[-20:]) / 20 if len(closes) >= 20 else ma5_price
            price_trend = (ma5_price - ma20_price) / ma20_price * 100 if ma20_price > 0 else 0

            # 近期涨跌幅（近5日）
            recent_change = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] > 0 else 0

            # 成交量趋势：近5日均量 vs 近20日均量
            avg_vol_5 = sum(volumes[-5:]) / 5
            avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else avg_vol_5
            vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1.0

            # 成交额趋势
            avg_amt_5 = sum(amounts[-5:]) / 5 if amounts else 0
            avg_amt_20 = sum(amounts[-20:]) / 20 if amounts and len(amounts) >= 20 else avg_amt_5
            amount_ratio = avg_amt_5 / avg_amt_20 if avg_amt_20 > 0 else 1.0

            # 量价关系分类（放宽阈值，覆盖更多股票）
            relation_type = ""
            score = 0

            if recent_change < -2 and vol_ratio > 1.1:
                # 价格下跌但放量 → 底背离（恐慌抛售/主力吸筹）
                relation_type = "底背离"
                score = min(95, int(60 + (vol_ratio - 1) * 30 + abs(recent_change) * 2))
            elif recent_change > 2 and vol_ratio < 0.7:
                # 价格上涨但缩量 → 顶背离（上涨动能不足）
                relation_type = "顶背离"
                score = min(95, int(60 + (1 - vol_ratio) * 40 + recent_change))
            elif recent_change > 1 and vol_ratio > 1.1:
                # 价格上涨且放量 → 量价齐升（健康上涨）
                relation_type = "量价齐升"
                score = min(95, int(65 + (vol_ratio - 1) * 20 + recent_change * 2))
            elif recent_change < -0.3 and vol_ratio < 0.7:
                # 价格下跌且缩量 → 缩量回调（洗盘）
                relation_type = "缩量回调"
                score = min(85, int(50 + (1 - vol_ratio) * 20))
            elif recent_change > 0 and vol_ratio > 1.0:
                # 温和放量上涨
                relation_type = "温和放量"
                score = min(80, int(55 + (vol_ratio - 1) * 15 + recent_change))
            elif recent_change < 0 and vol_ratio > 1.0:
                # 放量下跌（有资金介入迹象）
                relation_type = "放量下跌"
                score = min(75, int(45 + (vol_ratio - 1) * 20 + abs(recent_change)))
            elif recent_change > -1 and vol_ratio < 0.8:
                # 缩量横盘（蓄势整理）
                relation_type = "缩量横盘"
                score = min(70, int(40 + (1 - vol_ratio) * 15))
            else:
                # 无明显量价特征
                return None

            # 价格趋势加分：上升趋势中的底背离更可靠
            if relation_type == "底背离" and price_trend > 0:
                score = min(98, score + 10)

            latest_price = closes[-1]
            return {
                "code": code,
                "divergence_type": relation_type,
                "score": score,
                "recent_change": round(recent_change, 2),
                "vol_ratio": round(vol_ratio, 2),
                "amount_ratio": round(amount_ratio, 2),
                "price_trend": round(price_trend, 2),
                "latest_price": latest_price,
            }
        except Exception as e:
            logger.debug(f"量价分析失败 ({code}): {e}")
            return None

    def get_volume_price_divergence_picks(self, top_n: int = 20, market_cap: str = None,
                                                min_amount: int = None, change_range: str = None,
                                                exclude_st: bool = False, force_refresh: bool = False) -> dict:
        """量价背离选股策略

        逻辑：
        1. 从活跃股票池（龙虎榜+涨跌停池）获取候选股票
        2. 对每只股票获取60根日K线，分析量价关系
        3. 识别底背离、顶背离、量价齐升、缩量回调等模式
        4. 按评分排序，返回Top N

        优先推荐：底背离（看涨信号）> 温和放量 > 量价齐升 > 缩量回调
        """
        target_date = _get_strategy_target_date()
        # 龙虎榜数据16:30后才发布，盘中需回退到上一交易日
        dragon_date = _get_dragon_target_date()
        cache_key = f'vol_price_div_{top_n}_{exclude_st}_{market_cap}_{min_amount}_{change_range}_{target_date}'
        if not force_refresh:
            cached = self._get_dragon_cache(cache_key, namespace=NS_STRATEGY)
            if cached:
                return cached

        result = {
            "strategy": "volume_price_divergence",
            "stocks": [],
            "dragon_data_date": _format_display_date(dragon_date),
        }

        # 收集候选股票（去重）
        candidate_codes = []
        seen_codes = set()

        # 数据源1：龙虎榜（使用龙虎榜专用日期，避免盘中查询今日空数据）
        try:
            dragon_data = self._get_dragon_raw_data(date=dragon_date)
            if dragon_data:
                for item in dragon_data[:50]:
                    code = item.get("code", "")
                    name = item.get("name", "") or ""
                    if code and code not in seen_codes:
                        if exclude_st and 'ST' in name.upper():
                            continue
                        candidate_codes.append((code, name))
                        seen_codes.add(code)
                logger.info(f"量价背离候选: 龙虎榜{len(candidate_codes)}只")
        except Exception as e:
            logger.warning(f"龙虎榜获取失败: {e}")

        # 数据源2：涨停池（补充候选）
        if len(candidate_codes) < 30:
            try:
                zt_pool = EastMoneyZTPool.get_zt_pool(target_date)
                if zt_pool:
                    for item in zt_pool[:50]:
                        code = str(item.get("c", ""))
                        name = str(item.get("n", "") or "")
                        if code and code not in seen_codes:
                            if exclude_st and 'ST' in name.upper():
                                continue
                            candidate_codes.append((code, name))
                            seen_codes.add(code)
                    logger.info(f"量价背离候选: +涨停池{len(candidate_codes)}只")
            except Exception as e:
                logger.warning(f"涨停池获取失败: {e}")

        # 数据源3：全市场成交额TOP（兜底，确保有足够候选）
        if len(candidate_codes) < 60:
            try:
                from app.core.data_sources import TencentSource
                full_market = TencentSource.get_full_market()
                if full_market:
                    sorted_by_amount = sorted(full_market, key=lambda x: float(x.get("f10", 0) or 0), reverse=True)
                    for item in sorted_by_amount[:150]:
                        code = str(item.get("f12", ""))
                        name = str(item.get("f14", "") or "")
                        if code and code not in seen_codes:
                            if exclude_st and 'ST' in name.upper():
                                continue
                            candidate_codes.append((code, name))
                            seen_codes.add(code)
                    logger.info(f"量价关系候选: +全市场{len(candidate_codes)}只")
            except Exception as e:
                logger.warning(f"全市场数据获取失败: {e}")

        if not candidate_codes:
            logger.warning("量价背离选股: 无候选股票")
            return _add_meta(result, target_date)

        # 并行分析量价关系
        analyzed_stocks = []
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _analyze_one(args):
            code, name = args
            analysis = self._analyze_volume_price_divergence(code)
            if analysis:
                analysis["name"] = name
                return analysis
            return None

        with ThreadPoolExecutor(max_workers=10, thread_name_prefix="vpdiv") as executor:
            futures = {executor.submit(_analyze_one, item): item for item in candidate_codes}
            for future in as_completed(futures):
                try:
                    result_item = future.result(timeout=30)
                    if result_item:
                        analyzed_stocks.append(result_item)
                except Exception:
                    pass

        # 排序：优先底背离，然后按评分降序
        type_priority = {"底背离": 0, "温和放量": 1, "量价齐升": 2, "缩量回调": 3, "放量下跌": 4, "顶背离": 5, "缩量横盘": 6}
        analyzed_stocks.sort(key=lambda x: (type_priority.get(x["divergence_type"], 5), -x["score"]))

        # 批量获取实时行情（避免逐只请求）
        all_codes = [item["code"] for item in analyzed_stocks[:top_n]]
        quote_map = {}
        if all_codes:
            try:
                from app.core.data_sources import TencentSource
                quotes = TencentSource.get_quotes(all_codes)
                quote_map = quotes if isinstance(quotes, dict) else {}
            except Exception as e:
                logger.debug(f"批量获取实时行情失败: {e}")

        # 构建返回结果（应用筛选条件）
        for item in analyzed_stocks[:top_n * 2]:
            change_pct = item["recent_change"]

            # 涨跌幅筛选
            if change_range == "positive" and change_pct < 0:
                continue
            elif change_range == "negative" and change_pct > 0:
                continue

            q = quote_map.get(item["code"], {})
            mcap_yi = float(q.get("mcap_yi", 0) or 0)
            amount_wan = float(q.get("amount_wan", 0) or 0)

            # 市值筛选
            if market_cap == "large" and mcap_yi < 500:
                continue
            elif market_cap == "mid" and (mcap_yi < 100 or mcap_yi >= 500):
                continue
            elif market_cap == "small" and mcap_yi >= 100:
                continue

            # 成交额筛选（min_amount单位：万元）
            if min_amount and amount_wan < min_amount:
                continue

            stock = {
                "code": item["code"],
                "name": item["name"],
                "price": round(item["latest_price"], 2),
                "change_pct": change_pct,
                "divergence_type": item["divergence_type"],
                "vol_price_rel": item["divergence_type"],
                "vol_ratio": item["vol_ratio"],
                "amount_ratio": item["amount_ratio"],
                "price_trend": item["price_trend"],
                "score": item["score"],
                "hs": 0,
            }

            # 补充实时行情
            if q:
                stock["price"] = round(q.get("price", q.get("f2", item["latest_price"])), 2)
                stock["change_pct"] = round(q.get("change_pct", q.get("f3", change_pct)), 2)
                if q.get("turnover_pct"):
                    stock["hs"] = round(float(q["turnover_pct"]), 2)

            result["stocks"].append(stock)

            if len(result["stocks"]) >= top_n:
                break

        logger.info(f"量价背离选股: 候选{len(candidate_codes)}, 分析出{len(analyzed_stocks)}, 返回{len(result['stocks'])}")

        # 回测验证：对所有结果计算macd策略回测因子
        try:
            all_codes = [p['code'] for p in result["stocks"] if p.get('code')]
            if all_codes:
                backtest_factors = BacktestFactorCalculator.compute_batch_backtest_factors(
                    all_codes, strategy_name='macd', days=120
                )
                for pick in result["stocks"]:
                    code = pick['code']
                    if code in backtest_factors and backtest_factors[code]:
                        bt = backtest_factors[code]
                        pick['backtest_score'] = bt.get('composite_score', None)
                        pick['backtest_win_rate'] = bt.get('win_rate', None)
                        pick['backtest_sharpe'] = bt.get('sharpe_ratio', None)
        except Exception as e:
            logger.debug(f"量价背离选股回测验证失败: {e}")

        self._set_dragon_cache(cache_key, result, ttl=self._TTL_STRATEGY, namespace=NS_STRATEGY)
        return _add_meta(result, target_date)

    # ── 龙头选股 ────────────────────────────────────────────────────
    # 板块内综合评分最高的股票；筛选维度：5日板块强度（避免一日游）
    # 评分维度：板块内涨幅 25% + 成交额 20% + 市值 10% + 技术分 20% + 基本面 10% + 连板数 15%
    _TTL_LEADER = 300  # 5分钟
    _LEADER_SCORE_WEIGHTS = {
        "change_rank": 0.25,    # 板块内涨幅排名
        "amount_rank": 0.20,    # 板块内成交额排名
        "mcap_rank": 0.10,      # 板块内市值排名
        "technical": 0.20,      # 技术分（StandardScorer trend_breakout）
        "fundamental": 0.10,    # 基本面分
        "limit_days": 0.15,     # 连板数加分
    }

    def get_leader_picks(self, sector_type: str = "industry", top_n: int = 3,
                          sector_count: int = 10, market_cap: str = None,
                          min_amount: int = None, exclude_st: bool = True,
                          force_refresh: bool = False) -> dict:
        """龙头选股 — 每个板块取综合评分最高的 N 只龙头股

        Args:
            sector_type: 'industry'（行业）/ 'concept'（概念）
            top_n: 每板块龙头数（默认3）
            sector_count: 取前 N 个板块（默认10，按5日强度排序）
            market_cap: large/mid/small 市值过滤
            min_amount: 最小成交额（万元）
            exclude_st: 过滤 ST（默认True）
            force_refresh: 强制刷新
        """
        target_date = _get_strategy_target_date()
        cache_key = (f'leader_{sector_type}_{top_n}_{sector_count}_'
                     f'{market_cap or "all"}_{min_amount or 0}_{exclude_st}_{target_date}')

        if not force_refresh:
            cached = self._get_dragon_cache(cache_key, namespace=NS_STRATEGY)
            if cached is not None:
                return cached
            if not is_trading_hours():
                stale = self._get_stale_cache(cache_key, namespace=NS_STRATEGY)
                if stale is not None:
                    return stale

        result = {
            "strategy": "leader",
            "sector_type": sector_type,
            "sectors": [],
            "stocks": [],
        }

        try:
            # 1. 获取板块列表（复用 sector_analysis_service 的 _em_sector_list）
            from app.services.sector_analysis_service import _em_sector_list
            from app.core.data_sources_clean import (
                SectorHistoryCache, THSHotSource, THSSectorBuilder, EastMoneyZTPool
            )

            sectors_raw = _em_sector_list(sector_type)
            if not sectors_raw:
                logger.info(f"龙头选股: 板块列表为空 [{sector_type}]")
                self._set_dragon_cache(cache_key, result, ttl=self._TTL_LEADER, namespace=NS_STRATEGY)
                return _add_meta(result, target_date)

            # 1.5 概念板块：用同花顺热点 reason 反向聚合重建 sectors_raw
            # 避免东财概念名（如"人工智能"）与同花顺热点标签（如"AI眼镜"）对不上导致候选股为空
            concept_grouped = {}  # {tag: [items]}
            if sector_type == "concept":
                _hot_items = THSHotSource.get_hot_reasons(page_size=300) or []
                for it in _hot_items:
                    reason = (it.get("reason") or "").strip()
                    if not reason:
                        continue
                    primary_tag = reason.split("+")[0].strip()
                    if not primary_tag or primary_tag in ("首板涨停", "涨停", "连板", "连板涨停"):
                        continue
                    code = str(it.get("code", "") or "")
                    if not code:
                        continue
                    concept_grouped.setdefault(primary_tag, []).append({
                        "code": code,
                        "name": it.get("name", ""),
                        "sector_name": primary_tag,
                        "reason_detail": reason,
                        "change_pct": float(it.get("pct_change", 0) or 0),
                        "price": float(it.get("price", 0) or 0),
                    })

                # 用同花顺聚合结果覆盖 sectors_raw
                if concept_grouped:
                    sectors_raw_concept = []
                    for tag, items in concept_grouped.items():
                        if len(items) < 3:
                            continue  # 板块股票数 < 3 忽略
                        avg_change = sum(it["change_pct"] for it in items) / len(items)
                        sectors_raw_concept.append({
                            "name": tag,
                            "code": "",
                            "change_pct": avg_change,
                            "flow_net": 0,
                            "turnover_yi": 0,
                            "up_count": sum(1 for it in items if it["change_pct"] > 0),
                            "down_count": sum(1 for it in items if it["change_pct"] < 0),
                            "lead_stock": items[0]["name"] if items else "",
                        })
                    if sectors_raw_concept:
                        sectors_raw = sectors_raw_concept
                        logger.info(f"龙头选股[concept]: 同花顺聚合 {len(sectors_raw)} 个概念板块")

            # 2. 保存今日板块快照（用于 5 日强度累积）
            SectorHistoryCache.save_today_snapshot(sector_type, sectors_raw, target_date)

            # 3. 板块强度评分：5日平均涨幅 50% + 当日涨幅 30% + 主力净流入 20%
            sectors_scored = []
            for s in sectors_raw:
                name = s.get("name", "")
                if not name:
                    continue
                strength_5d = SectorHistoryCache.calc_strength(sector_type, name)
                change_pct = float(s.get("change_pct", 0) or 0)
                flow_net = float(s.get("flow_net", 0) or 0)
                turnover_yi = float(s.get("turnover_yi", 0) or 0)

                # 归一化（避免量纲差异）：板块涨幅/净流入/成交额相对值
                strength_score = (
                    strength_5d.get("change_avg", 0) * 0.5
                    + change_pct * 0.3
                    + max(-10, min(10, flow_net)) * 0.2  # 净流入 clip 到 [-10, 10]
                )
                sectors_scored.append({
                    "name": name,
                    "code": s.get("code", ""),
                    "change_pct": change_pct,
                    "flow_net": flow_net,
                    "turnover_yi": turnover_yi,
                    "up_count": int(s.get("up_count", 0) or 0),
                    "down_count": int(s.get("down_count", 0) or 0),
                    "lead_stock": s.get("lead_stock", ""),
                    "strength_5d_avg": strength_5d.get("change_avg", 0),
                    "strength_5d_days": strength_5d.get("days_available", 0),
                    "is_sustainable": strength_5d.get("is_sustainable", False),
                    "strength_score": round(strength_score, 2),
                })

            sectors_scored.sort(key=lambda x: x["strength_score"], reverse=True)
            top_sectors = sectors_scored[:sector_count]

            if not top_sectors:
                logger.info("龙头选股: 板块强度评分为空")
                self._set_dragon_cache(cache_key, result, ttl=self._TTL_LEADER, namespace=NS_STRATEGY)
                return _add_meta(result, target_date)

            # 4. 收集每个板块的候选股
            # 行业：用 THSSectorBuilder._INDUSTRY_STOCKS 硬编码成分股
            # 概念：用 THSHotSource.get_hot_reasons() 的 reason 字段反向聚合
            sector_candidates = {}  # {sector_name: [candidate dicts]}
            all_candidate_codes = set()

            if sector_type == "industry":
                industry_map = THSSectorBuilder._INDUSTRY_STOCKS
                for sec in top_sectors:
                    name = sec["name"]
                    codes = industry_map.get(name, [])
                    sector_candidates[name] = [{"code": c, "sector_name": name} for c in codes]
                    all_candidate_codes.update(codes)
            else:  # concept - 直接复用 1.5 步聚合同花顺热点得到的 concept_grouped
                for sec in top_sectors:
                    name = sec["name"]
                    items = concept_grouped.get(name, [])
                    sector_candidates[name] = items
                    all_candidate_codes.update([it["code"] for it in items])

            # 5. 批量获取所有候选股的实时行情（腾讯）
            all_codes_list = list(all_candidate_codes)
            quotes_map = {}
            if all_codes_list:
                try:
                    quotes_map = TencentSource.get_quotes(all_codes_list)
                except Exception as e:
                    logger.warning(f"龙头选股获取实时行情失败: {e}")

            # 6. 获取涨停池（用于连板数加分）
            zt_pool = []
            try:
                zt_pool = EastMoneyZTPool.get_zt_pool(target_date) or []
            except Exception as e:
                logger.debug(f"涨停池获取失败: {e}")
            limit_days_map = {}
            for item in zt_pool:
                code = str(item.get("c", ""))
                lbc = int(item.get("lbc", 1) or 1)
                if code:
                    limit_days_map[code] = lbc

            # 7. 对每个板块：预筛选 + 批量 K 线 + 评分
            for sec_idx, sec in enumerate(top_sectors):
                sector_name = sec["name"]
                candidates = sector_candidates.get(sector_name, [])
                if not candidates:
                    continue

                # 预筛选：剔除停牌/ST/价格过低
                pre_filtered = []
                for cand in candidates:
                    code = cand["code"]
                    q = quotes_map.get(code, {})
                    price = float(q.get("price", 0) or 0)
                    name = q.get("name", cand.get("name", ""))
                    change_pct = float(q.get("change_pct", 0) or 0)
                    amount_wan = float(q.get("amount_wan", 0) or 0)
                    mcap_yi = float(q.get("mcap_yi", 0) or 0)

                    if price <= 0:
                        continue
                    if exclude_st and 'ST' in (name or "").upper():
                        continue
                    if price < 2.0:
                        continue
                    if market_cap == "large" and mcap_yi < 500:
                        continue
                    elif market_cap == "mid" and (mcap_yi < 100 or mcap_yi >= 500):
                        continue
                    elif market_cap == "small" and mcap_yi >= 100:
                        continue
                    if min_amount and amount_wan < min_amount:
                        continue

                    pre_filtered.append({
                        "code": code, "name": name, "price": price,
                        "change_pct": change_pct, "amount_wan": amount_wan,
                        "mcap_yi": mcap_yi, "turnover_pct": float(q.get("turnover_pct", 0) or 0),
                        "pe": float(q.get("pe_ttm", 0) or 0),
                        "pb": float(q.get("pb", 0) or 0),
                        "sector_name": sector_name,
                    })

                if not pre_filtered:
                    continue

                # 板块内排序（用于排名评分）
                sorted_by_change = sorted(pre_filtered, key=lambda x: -x["change_pct"])
                sorted_by_amount = sorted(pre_filtered, key=lambda x: -x["amount_wan"])
                sorted_by_mcap = sorted(pre_filtered, key=lambda x: -x["mcap_yi"])
                rank_change = {s["code"]: i + 1 for i, s in enumerate(sorted_by_change)}
                rank_amount = {s["code"]: i + 1 for i, s in enumerate(sorted_by_amount)}
                rank_mcap = {s["code"]: i + 1 for i, s in enumerate(sorted_by_mcap)}
                total_in_sector = len(pre_filtered)

                # 取 TOP 30 进行 K 线分析（避免板块过大）
                top_candidates = sorted_by_amount[:30]
                codes_to_fetch = [c["code"] for c in top_candidates]

                # 批量获取 K 线
                batch_klines = pytdx_data.get_batch_klines(codes_to_fetch, period=4, count=60, max_workers=10)

                # 计算技术分 + 基本面分
                scored_candidates = []
                for cand in top_candidates:
                    code = cand["code"]
                    klines = batch_klines.get(code, [])
                    if not klines or len(klines) < 20:
                        # 无 K 线时仅用排名评分
                        tech_score = 50
                        factors_data = {}
                    else:
                        indicators = self._calc_indicators_from_klines(code, klines)
                        if not indicators:
                            tech_score = 50
                            factors_data = {}
                        else:
                            tech_score = indicators.get("score", 50)
                            factors_data = indicators.get("factors") or {}

                    # 基本面分（对 TOP top_n*3 才拉财务数据，避免对全部候选拉）
                    fund_score = 50
                    if cand in top_candidates[:max(top_n * 3, 3)]:
                        try:
                            financial_data = _fetch_real_financial(code)
                            fund_factors = FundamentalFactorCalculator.compute_from_financial(financial_data) or {}
                            combined = FundamentalFactorCalculator.compute_combined_score(
                                factors_data, financial_data,
                                technical_weight=0.6, fundamental_weight=0.4
                            )
                            tech_score = combined or tech_score
                            fund_score = (
                                (fund_factors.get('pe_score') or 50) * 0.4
                                + (fund_factors.get('pb_score') or 50) * 0.3
                                + (fund_factors.get('roe_score') or 50) * 0.3
                            )
                            cand["pe_score"] = fund_factors.get('pe_score')
                            cand["pb_score"] = fund_factors.get('pb_score')
                            cand["roe_score"] = fund_factors.get('roe_score')
                        except Exception as e:
                            logger.debug(f"龙头选股基本面获取失败 ({code}): {e}")

                    # 连板数
                    limit_days = limit_days_map.get(code, 0)
                    # 连板数评分：0板=0，首板=50，2板=70，3板=85，4板=95，5板+=100
                    if limit_days <= 0:
                        limit_score = 0
                    elif limit_days == 1:
                        limit_score = 50
                    elif limit_days == 2:
                        limit_score = 70
                    elif limit_days == 3:
                        limit_score = 85
                    elif limit_days == 4:
                        limit_score = 95
                    else:
                        limit_score = 100

                    # 板块内排名评分（归一化到 0-100，越靠前分越高）
                    rank_change_score = max(0, 100 - (rank_change[code] - 1) * 100 / max(total_in_sector - 1, 1))
                    rank_amount_score = max(0, 100 - (rank_amount[code] - 1) * 100 / max(total_in_sector - 1, 1))
                    rank_mcap_score = max(0, 100 - (rank_mcap[code] - 1) * 100 / max(total_in_sector - 1, 1))

                    # 综合评分
                    w = self._LEADER_SCORE_WEIGHTS
                    leader_score = (
                        rank_change_score * w["change_rank"]
                        + rank_amount_score * w["amount_rank"]
                        + rank_mcap_score * w["mcap_rank"]
                        + tech_score * w["technical"]
                        + fund_score * w["fundamental"]
                        + limit_score * w["limit_days"]
                    )
                    leader_score = round(leader_score, 2)

                    # 生成 reason 字段
                    reason_parts = []
                    if rank_change[code] == 1:
                        reason_parts.append("板块涨幅第1")
                    elif rank_change[code] <= 3:
                        reason_parts.append(f"板块涨幅第{rank_change[code]}")
                    if rank_amount[code] == 1:
                        reason_parts.append("成交额第1")
                    if limit_days >= 2:
                        reason_parts.append(f"{limit_days}连板")
                    elif limit_days == 1:
                        reason_parts.append("首板")
                    if tech_score >= 80:
                        reason_parts.append("趋势突破")
                    if fund_score >= 70:
                        reason_parts.append("基本面优")
                    reason = "、".join(reason_parts) if reason_parts else "板块活跃股"

                    scored_candidates.append({
                        "code": code,
                        "name": cand["name"],
                        "price": round(cand["price"], 2),
                        "change_pct": round(cand["change_pct"], 2),
                        "amount_wan": round(cand["amount_wan"], 0),
                        "market_cap_yi": round(cand["mcap_yi"], 1),
                        "pe": cand.get("pe") if cand.get("pe") else None,
                        "pb": cand.get("pb") if cand.get("pb") else None,
                        "pe_score": cand.get("pe_score"),
                        "pb_score": cand.get("pb_score"),
                        "roe_score": cand.get("roe_score"),
                        "technical_score": round(tech_score, 1),
                        "fundamental_score": round(fund_score, 1),
                        "limit_days": limit_days,
                        "leader_score": leader_score,
                        "rank_in_sector": rank_change[code],
                        "rank_in_sector_amount": rank_amount[code],
                        "rank_in_sector_mcap": rank_mcap[code],
                        "total_in_sector": total_in_sector,
                        "reason": reason,
                        "sector_name": sector_name,
                        "score": leader_score,  # 用于 combo 融合
                    })

                # 排序取 top_n
                scored_candidates.sort(key=lambda x: -x["leader_score"])
                leaders = scored_candidates[:top_n]

                if leaders:
                    sec_result = {
                        "sector_name": sector_name,
                        "sector_code": sec.get("code", ""),
                        "sector_rank": sec_idx + 1,
                        "sector_change_pct": sec["change_pct"],
                        "sector_flow_net_yi": sec["flow_net"],
                        "sector_amount_yi": sec["turnover_yi"],
                        "sector_up_count": sec["up_count"],
                        "sector_down_count": sec["down_count"],
                        "sector_strength_5d_avg": sec["strength_5d_avg"],
                        "sector_strength_5d_days": sec["strength_5d_days"],
                        "is_sustainable": sec["is_sustainable"],
                        "sector_strength_score": sec["strength_score"],
                        "leaders": leaders,
                    }
                    result["sectors"].append(sec_result)
                    # 扁平化列表（供 combo 融合）
                    for l in leaders:
                        flat = dict(l)
                        flat["strategy"] = "leader"
                        result["stocks"].append(flat)

            logger.info(
                f"龙头选股[{sector_type}]: 板块{len(top_sectors)}, "
                f"输出{len(result['sectors'])}板块/{len(result['stocks'])}只龙头"
            )

        except Exception as e:
            logger.error(f"龙头选股失败: {e}", exc_info=True)

        final_result = _add_meta(result, target_date)
        self._set_dragon_cache(cache_key, final_result, ttl=self._TTL_LEADER, namespace=NS_STRATEGY)
        return final_result

    def get_strategy_combo(self, strategies: list = None, top_n: int = 10, exclude_st: bool = False, force_refresh: bool = False, mode: str = 'vote') -> dict:
        """多策略组合
        
        Args:
            mode: 'vote' 投票融合（多数表决，只显示被至少2个策略选中的股票）
                  'weight' 加权融合（各策略权重不同，所有出现过的股票都参与排名）
        """
        try:
            # 缓存 key：组合策略结果缓存时间可延长（子策略各自有缓存）
            target_date = _get_strategy_target_date()
            cache_key = f'strategy_combo_{mode}_{top_n}_{exclude_st}_{target_date}'
            if not force_refresh:
                cached = self._get_dragon_cache(cache_key, namespace=NS_STRATEGY)
                if cached:
                    return cached

            # 策略中文名映射
            strategy_names_cn = {
                "multi_factor": "多因子",
                "capital_flow": "资金流",
                "ml_prediction": "ML预测",
                "low_absorption": "低吸企稳",
                "volume_price_divergence": "量价关系",
                "leader": "龙头股",
            }

            # 定义策略列表和对应的权重（6个策略：5个全市场扫描 + 1个板块视角）
            # leader 提供板块视角，与多因子形成互补但权重适中避免重复计票
            strategy_list = strategies or ["multi_factor", "capital_flow", "ml_prediction",
                                            "low_absorption", "volume_price_divergence", "leader"]
            weights = {
                "multi_factor": 0.28,
                "capital_flow": 0.20,
                "ml_prediction": 0.16,
                "low_absorption": 0.13,
                "volume_price_divergence": 0.13,
                "leader": 0.10,
            }

            # K线预加载优化：收集各策略可能需要的候选股票，批量获取K线填充缓存
            _preload_klines_for_combo(strategy_list, target_date, exclude_st)

            # 并行获取各策略的选股结果（传递 exclude_st）
            def _run_strategy(strategy):
                if strategy == "multi_factor":
                    return self.get_multi_factor_picks(top_n=top_n * 3, exclude_st=exclude_st).get("stocks", [])
                elif strategy == "capital_flow":
                    return self.get_capital_flow_picks(top_n=top_n * 3, exclude_st=exclude_st).get("stocks", [])
                elif strategy == "ml_prediction":
                    return self.predict_ml_stocks(top_n=top_n * 3, exclude_st=exclude_st).get("stocks", [])
                elif strategy == "low_absorption":
                    return self.get_low_absorption_picks(top_n=top_n * 3, exclude_st=exclude_st).get("stocks", [])
                elif strategy == "volume_price_divergence":
                    return self.get_volume_price_divergence_picks(top_n=top_n * 3, exclude_st=exclude_st).get("stocks", [])
                elif strategy == "leader":
                    # 龙头选股：取行业+概念合并的扁平化龙头列表
                    # 每板块 top_n=3，sector_count=top_n*2 保证足够的候选数量参与融合
                    leaders = []
                    for st in ("industry", "concept"):
                        try:
                            r = self.get_leader_picks(
                                sector_type=st, top_n=3,
                                sector_count=max(top_n * 2, 10),
                                exclude_st=exclude_st,
                            )
                            leaders.extend(r.get("stocks", []))
                        except Exception as e:
                            logger.warning(f"龙头选股[{st}]执行失败: {e}")
                    return leaders
                return []

            strategy_results = {}
            with concurrent_futures.ThreadPoolExecutor(max_workers=len(strategy_list)) as executor:
                futures_map = {executor.submit(_run_strategy, s): s for s in strategy_list}
                for future in concurrent_futures.as_completed(futures_map):
                    strategy = futures_map[future]
                    try:
                        strategy_results[strategy] = future.result(timeout=60)
                    except Exception as e:
                        logger.warning(f"策略[{strategy}]执行失败: {e}")
                        strategy_results[strategy] = []

            active_strategies = {k: v for k, v in strategy_results.items() if v}
            result = {"strategies": list(active_strategies.keys()), "combined_stocks": [], "mode": mode}

            if not active_strategies:
                return result

            if mode == 'vote':
                # 投票融合：统计每只股票被多少个策略选中，只显示被至少2个策略选中的
                vote_counts = {}

                for strategy_name, stocks in active_strategies.items():
                    for stock in stocks:
                        code = stock["code"]
                        if code not in vote_counts:
                            vote_counts[code] = {
                                "count": 0,
                                "strategies": [],
                                "data": stock,
                                "scores": []
                            }
                        vote_counts[code]["count"] += 1
                        vote_counts[code]["strategies"].append(strategy_names_cn.get(strategy_name, strategy_name))
                        vote_counts[code]["scores"].append(stock.get("score", stock.get("prediction_score", 0.7) * 100))

                # 动态投票阈值：随活跃策略数调整（至少占50%+1）
                min_votes = max(2, len(active_strategies) // 2 + 1)
                qualified = {k: v for k, v in vote_counts.items() if v["count"] >= min_votes}

                # 按票数降序，票数相同按平均得分排序
                ranked = sorted(
                    qualified.items(),
                    key=lambda x: (x[1]["count"], sum(x[1]["scores"]) / len(x[1]["scores"])),
                    reverse=True
                )

                for code, info in ranked[:top_n]:
                    stock_data = dict(info["data"])
                    stock_data["strategy_count"] = info["count"]
                    stock_data["strategies"] = " + ".join(info["strategies"])
                    stock_data["total_strategies"] = len(active_strategies)
                    stock_data["confidence"] = round(info["count"] / len(active_strategies) * 100, 1)
                    stock_data["score"] = round(sum(info["scores"]) / len(info["scores"]), 2)
                    stock_data["vote_score"] = stock_data["score"]
                    result["combined_stocks"].append(stock_data)

            elif mode == 'weight':
                # 加权融合：所有出现过的股票都参与排名，按加权得分排序
                stock_weighted_scores = {}

                for strategy_name, stocks in active_strategies.items():
                    weight = weights.get(strategy_name, 0.25)

                    if not stocks:
                        continue

                    for stock in stocks:
                        code = stock["code"]
                        raw_score = stock.get("score", stock.get("prediction_score", 0.7) * 100)

                        if code not in stock_weighted_scores:
                            stock_weighted_scores[code] = {
                                "weighted_score": 0.0,
                                "total_weight": 0.0,
                                "data": dict(stock),
                                "strategies": []
                            }

                        stock_weighted_scores[code]["weighted_score"] += raw_score * weight
                        stock_weighted_scores[code]["total_weight"] += weight
                        stock_weighted_scores[code]["strategies"].append(strategy_names_cn.get(strategy_name, strategy_name))

                # 计算最终加权得分并构建结果
                ranked = []
                for code, info in stock_weighted_scores.items():
                    final_data = dict(info["data"])
                    if info["total_weight"] > 0:
                        final_data["score"] = round(info["weighted_score"] / info["total_weight"], 2)
                    else:
                        final_data["score"] = 0
                    final_data["strategies"] = " + ".join(info["strategies"])
                    final_data["strategy_count"] = len(info["strategies"])
                    final_data["total_strategies"] = len(active_strategies)
                    final_data["confidence"] = round(len(info["strategies"]) / len(active_strategies) * 100, 1)
                    final_data["weight_score"] = final_data["score"]
                    ranked.append((code, final_data))

                # 按加权得分排序，确保排名与输出一致
                ranked.sort(key=lambda x: x[1]["weight_score"], reverse=True)

                for code, final_data in ranked[:top_n]:
                    result["combined_stocks"].append(final_data)

            # 最终ST过滤（兜底，防止子策略漏掉）
            if exclude_st:
                result["combined_stocks"] = [
                    s for s in result["combined_stocks"]
                    if 'ST' not in (s.get("name", "") or "").upper()
                ]

            # 合并实时行情：用今日实时涨跌幅覆盖策略数据中的涨跌幅
            try:
                from app.core.data_sources import TencentSource
                codes = [s.get("code") for s in result["combined_stocks"] if s.get("code")]
                quotes = TencentSource.get_quotes(codes)
                for stock in result["combined_stocks"]:
                    code = stock.get("code", "")
                    q = quotes.get(code)
                    if q:
                        stock["price"] = q.get("price", stock.get("price", 0))
                        stock["change_pct"] = q.get("change_pct", stock.get("change_pct", 0))
            except Exception as e:
                logger.debug(f"策略组合合并实时行情失败: {e}")

            # 缓存组合结果（计算成本高，延长TTL）
            result["stocks"] = result.get("combined_stocks", [])

            # 回测验证：对所有结果计算balanced策略回测因子
            try:
                all_codes = [p['code'] for p in result["stocks"] if p.get('code')]
                if all_codes:
                    backtest_factors = BacktestFactorCalculator.compute_batch_backtest_factors(
                        all_codes, strategy_name='balanced', days=120
                    )
                    for pick in result["stocks"]:
                        code = pick['code']
                        if code in backtest_factors and backtest_factors[code]:
                            bt = backtest_factors[code]
                            pick['backtest_score'] = bt.get('composite_score', None)
                            pick['backtest_win_rate'] = bt.get('win_rate', None)
                            pick['backtest_sharpe'] = bt.get('sharpe_ratio', None)
            except Exception as e:
                logger.debug(f"策略组合回测验证失败: {e}")

            self._set_dragon_cache(cache_key, result, ttl=self._TTL_COMBO, namespace=NS_STRATEGY)
            return result
        except Exception as e:
            logger.warning(f"策略组合失败: {e}")
            return {"strategies": [], "combined_stocks": [], "stocks": []}

    def get_hot_money_tracking(self, force_refresh: bool = False) -> dict:
        """游资追踪 - 返回活跃游资席位信息（模拟展示，非真实匹配）

        注意：龙虎榜原始数据不包含具体游资名称，此处为基于知名游资席位的模拟展示。
        实际使用时应接入真实的席位识别服务或人工标注数据库。
        """
        try:
            target_date = _get_dragon_target_date()
            dragon_data = self._get_dragon_raw_data(date=target_date, force_refresh=force_refresh)

            result = {
                "date": target_date,
                "is_simulated": True,  # 明确标注为模拟数据
                "hot_money_seats": [],
                "active_stocks": [],
            }

            if dragon_data:
                # 筛选净买入金额绝对值大于1000万的活跃股票（真实数据）
                for item in dragon_data[:50]:
                    net_amt = item["net_amount"]
                    if abs(net_amt) > 1e7:
                        result["active_stocks"].append({
                            "code": item["code"],
                            "name": item["name"],
                            "price": item["price"],
                            "net_amount": net_amt,
                            "buy_amount": item["buy_amount"],
                            "sell_amount": item["sell_amount"],
                            "change_pct": item["change_pct"],
                            "direction": item["direction"],
                            "reason": item["reason"],
                        })

            return result
        except Exception as e:
            logger.warning(f"游资追踪失败: {e}")
            return {"date": _get_dragon_target_date(), "is_simulated": True, "hot_money_seats": [], "active_stocks": []}

    def get_dragon_capital_flow(self, force_refresh: bool = False) -> dict:
        """龙虎榜资金流向 — 机构vs游资对比（基于真实席位数据）。

        通过查询 RPT_BILLBOARD_DAILYDETAILSBUY/SELL 明细表，
        OPERATEDEPT_CODE="0" 为机构专用席位，其余为非机构（游资/散户）席位。
        """
        target_date = _get_dragon_target_date()
        cache_key = f'dragon_flow_{target_date}'
        if not force_refresh:
            cached = self._get_dragon_cache(cache_key)
            if cached:
                return cached

        try:
            dragon_data = self._get_dragon_raw_data(date=target_date, force_refresh=force_refresh)
            
            empty_structure = {
                "net_buy": 0, "total_buy": 0, "total_sell": 0, "count": 0, "top_stocks": []
            }

            result = {
                "date": target_date,
                "total_net_buy": 0,
                "stock_count": 0,
                "institution": dict(empty_structure),
                "hot_money": dict(empty_structure),
            }
            
            if not dragon_data:
                self._set_dragon_cache(cache_key, result)
                return result

            total = sum(item["net_amount"] for item in dragon_data)
            result["total_net_buy"] = round(total, 2)
            result["stock_count"] = len(dragon_data)

            # 按真实席位数据分类：批量拉取全市场席位（2次请求+缓存），对所有上榜股票做精确分类
            date_em = target_date.replace("-", "")
            if len(date_em) == 8:
                date_em = f"{date_em[:4]}-{date_em[4:6]}-{date_em[6:8]}"

            all_seats = self._batch_query_all_seats(date_em)

            inst_stocks = []
            hot_stocks = []

            for item in dragon_data:
                code = item.get("code", "")
                if not code:
                    continue

                seat_info = all_seats.get(code, {
                    "inst_buy": 0, "inst_sell": 0, "buy_data": [], "sell_data": []
                })

                # 机构净买入 > 0 → 机构主导，否则游资主导
                inst_net = seat_info["inst_buy"] - seat_info["inst_sell"]
                stock_data = {
                    "code": item["code"], "name": item["name"], "price": item["price"],
                    "buy_amount": item["buy_amount"], "sell_amount": item["sell_amount"],
                    "net_amount": item["net_amount"], "change_pct": item["change_pct"],
                }

                if inst_net > 0:
                    inst_stocks.append(stock_data)
                else:
                    hot_stocks.append(stock_data)

            # 机构详情（按净买入额排序）
            inst_sorted = sorted(inst_stocks, key=lambda x: x["net_amount"], reverse=True)
            result["institution"] = {
                "net_buy": round(sum(item["net_amount"] for item in inst_stocks), 2),
                "total_buy": round(sum(item["buy_amount"] for item in inst_stocks), 2),
                "total_sell": round(sum(item["sell_amount"] for item in inst_stocks), 2),
                "count": len(inst_stocks),
                "top_stocks": [
                    {"code": s["code"], "name": s["name"], "price": s["price"],
                      "buy_amount": s["buy_amount"], "sell_amount": s["sell_amount"],
                      "net_amount": s["net_amount"], "change_pct": s["change_pct"]}
                    for s in inst_sorted
                ],
            }

            # 游资详情（按涨跌幅绝对值排序）
            hot_sorted = sorted(hot_stocks, key=lambda x: abs(x.get("change_pct", 0)), reverse=True)
            result["hot_money"] = {
                "net_buy": round(sum(item["net_amount"] for item in hot_stocks), 2),
                "total_buy": round(sum(item["buy_amount"] for item in hot_stocks), 2),
                "total_sell": round(sum(item["sell_amount"] for item in hot_stocks), 2),
                "count": len(hot_stocks),
                "top_stocks": [
                    {"code": s["code"], "name": s["name"], "price": s["price"],
                      "buy_amount": s["buy_amount"], "sell_amount": s["sell_amount"],
                      "net_amount": s["net_amount"], "change_pct": s["change_pct"]}
                    for s in hot_sorted
                ],
            }

            logger.info(f"龙虎榜资金流向: 机构{len(inst_stocks)}只, 游资{len(hot_stocks)}只（基于真实席位数据）")
            
            self._set_dragon_cache(cache_key, result, ttl=self._TTL_CAPITAL_FLOW)
            return result
        except Exception as e:
            logger.warning(f"龙虎榜资金流向失败: {e}")
            return {
                "date": target_date, "total_net_buy": 0,
                "institution": {"net_buy": 0, "total_buy": 0, "total_sell": 0, "count": 0, "top_stocks": []},
                "hot_money": {"net_buy": 0, "total_buy": 0, "total_sell": 0, "count": 0, "top_stocks": []},
            }

    def _query_stock_seats(self, code: str, trade_date: str) -> dict:
        """查询单只股票在指定日期的买卖席位（委托批量方法）。

        OPERATEDEPT_CODE="0" 表示机构专用席位。
        Returns: {inst_buy, inst_sell, buy_data, sell_data}
        """
        return self._batch_query_all_seats(trade_date).get(code, {
            "inst_buy": 0, "inst_sell": 0, "buy_data": [], "sell_data": []
        })

    @staticmethod
    def _batch_query_all_seats(trade_date: str) -> dict:
        """按日期批量拉取全市场龙虎榜席位明细（2次请求，替代逐只查询）。

        Returns: {code: {"inst_buy", "inst_sell", "buy_data", "sell_data"}}
        """
        cache_key = f'dragon_seats_batch_{trade_date}'
        cached = StrategyService._get_dragon_cache(cache_key)
        if cached is not None:
            return cached

        result = {}
        try:
            # 1. 批量拉取当日所有买入席位（不 filter SECURITY_CODE）
            buy_data_all = EastMoneyDataCenter.query(
                "RPT_BILLBOARD_DAILYDETAILSBUY",
                filter_str=f"(TRADE_DATE='{trade_date}')",
                page_size=500, sort_columns="BUY", sort_types="-1"
            ) or []

            # 2. 批量拉取当日所有卖出席位
            sell_data_all = EastMoneyDataCenter.query(
                "RPT_BILLBOARD_DAILYDETAILSSELL",
                filter_str=f"(TRADE_DATE='{trade_date}')",
                page_size=500, sort_columns="SELL", sort_types="-1"
            ) or []

            # 3. 按股票代码分组
            buy_by_code = {}
            for row in buy_data_all:
                c = str(row.get("SECURITY_CODE", ""))
                if c not in buy_by_code:
                    buy_by_code[c] = []
                buy_by_code[c].append(row)

            sell_by_code = {}
            for row in sell_data_all:
                c = str(row.get("SECURITY_CODE", ""))
                if c not in sell_by_code:
                    sell_by_code[c] = []
                sell_by_code[c].append(row)

            # 4. 合并所有涉及的代码
            all_codes = set(list(buy_by_code.keys()) + list(sell_by_code.keys()))
            for code in all_codes:
                buys = buy_by_code.get(code, [])[:10]
                sells = sell_by_code.get(code, [])[:10]

                inst_buy = sum((r.get("BUY") or 0) for r in buys if str(r.get("OPERATEDEPT_CODE", "")) == "0")
                inst_sell = sum((r.get("SELL") or 0) for r in sells if str(r.get("OPERATEDEPT_CODE", "")) == "0")

                result[code] = {
                    "inst_buy": inst_buy,
                    "inst_sell": inst_sell,
                    "buy_data": buys,
                    "sell_data": sells,
                }

            StrategyService._set_dragon_cache(cache_key, result)
        except Exception as e:
            logger.warning(f"批量查询席位失败 ({trade_date}): {e}")

        return result

    def get_dragon_seat_detail(self, force_refresh: bool = False) -> dict:
        """龙虎榜席位详情 — 基于真实买卖席位明细（RPT_BILLBOARD_DAILYDETAILSBUY/SELL）"""
        try:
            target_date = _get_dragon_target_date()
            cache_key = f'dragon_seat_{target_date}'
            if not force_refresh:
                cached = self._get_dragon_cache(cache_key)
                if cached:
                    return cached
            dragon_data = self._get_dragon_raw_data(date=target_date, force_refresh=force_refresh)

            result = {"date": target_date, "seats": []}
            if not dragon_data:
                return result

            date_em = target_date.replace("-", "")
            if len(date_em) == 8:
                date_em = f"{date_em[:4]}-{date_em[4:6]}-{date_em[6:8]}"

            for item in dragon_data[:15]:
                code = item.get("code", "")
                if not code:
                    continue

                # 查询真实买卖席位明细（一次调用获取所有数据）
                seat_info = self._query_stock_seats(code, date_em)
                buy_data = seat_info["buy_data"]
                sell_data = seat_info["sell_data"]

                # 统计机构席位数量（OPERATEDEPT_CODE="0"）
                inst_buy_count = sum(1 for r in buy_data if str(r.get("OPERATEDEPT_CODE", "")) == "0")
                inst_sell_count = sum(1 for r in sell_data if str(r.get("OPERATEDEPT_CODE", "")) == "0")

                result["seats"].append({
                    "code": item["code"],
                    "name": item["name"],
                    "price": item["price"],
                    "change_pct": item["change_pct"],
                    "buy_amount": item["buy_amount"],
                    "sell_amount": item["sell_amount"],
                    "net_amount": item["net_amount"],
                    "direction": item["direction"],
                    "reason": item["reason"],
                    "buy_seat_count": len(buy_data),
                    "sell_seat_count": len(sell_data),
                    "inst_buy_count": inst_buy_count,
                    "inst_sell_count": inst_sell_count,
                    "inst_buy_amt": seat_info["inst_buy"],
                    "inst_sell_amt": seat_info["inst_sell"],
                })

            self._set_dragon_cache(cache_key, result, ttl=self._TTL_SEAT)
            return result
        except Exception as e:
            logger.warning(f"龙虎榜席位详情失败: {e}")
            return {"date": target_date, "seats": []}

    @staticmethod
    def _match_reason_tags(reason: str) -> list[str]:
        """多标签匹配上榜原因，一只股票可同时命中多个分类。

        东财 EXPLANATION 字段示例：
          "当日涨幅偏离值达7%"
          "日换手率达20%"
          "日振幅达到15%"
          "连续三个交易日内涨幅偏离值累计达12%"
          "换手率达到30%且日均换手率异动"
        """
        tags = []
        if "涨幅偏离" in reason:
            tags.append("涨幅偏离")
        if "跌幅偏离" in reason:
            tags.append("跌幅偏离")
        if "换手" in reason:
            tags.append("换手率达标")
        if "振幅" in reason:
            tags.append("振幅异动")
        if "有价格涨跌幅限制的日收盘价格涨幅达到" in reason or "有价格涨跌幅限制的日收盘价格跌幅达到" in reason:
            tags.append("涨跌停")
        if not tags:
            tags = ["其他"]
        return tags

    def get_dragon_sector_analysis(self, force_refresh: bool = False) -> dict:
        """龙虎榜板块分析 — 多标签匹配，一只股票可同时属于多个分类"""
        try:
            target_date = _get_dragon_target_date()
            cache_key = f'dragon_sector_{target_date}'
            if not force_refresh:
                cached = self._get_dragon_cache(cache_key)
                if cached:
                    return cached
            dragon_data = self._get_dragon_raw_data(date=target_date, force_refresh=force_refresh)

            result = {"date": target_date, "sectors": []}
            if dragon_data:
                sector_map = {}
                sector_stocks = {}

                for item in dragon_data:
                    reason = item["reason"] or ""
                    net_amt = item["net_amount"]
                    tags = self._match_reason_tags(reason)

                    for sector_name in tags:
                        sector_map[sector_name] = sector_map.get(sector_name, 0) + net_amt
                        if sector_name not in sector_stocks:
                            sector_stocks[sector_name] = []
                        sector_stocks[sector_name].append(item)
                
                result["sectors"] = [
                    {
                        "name": k,
                        "category": k,
                        "net_amount": round(v, 2),
                        "net_buy": round(v, 2),
                        "count": len(sector_stocks.get(k, [])),
                        # 计算该分类的平均换手率
                        "avg_turnover": round(
                            sum(s.get("turnover", 0) for s in sector_stocks.get(k, [])) / max(len(sector_stocks.get(k, [])), 1), 2
                        ),
                        # 涨停数量统计
                        "limit_up_count": sum(1 for s in sector_stocks.get(k, []) if s.get("change_pct", 0) >= 9.5),
                        # 龙虎买入总额
                        "total_amount": round(sum(s.get("buy_amount", 0) for s in sector_stocks.get(k, [])), 2),
                        # 平均涨跌幅
                        "avg_change_pct": round(
                            sum(s.get("change_pct", 0) for s in sector_stocks.get(k, [])) / max(len(sector_stocks.get(k, [])), 1), 2
                        ),
                        "top_stocks": [
                            {
                                "code": s["code"],
                                "name": s["name"],
                                "price": s["price"],
                                "change_pct": s["change_pct"],
                                "net_amount": s["net_amount"],
                                "turnover": s.get("turnover", 0),
                            }
                            for s in sector_stocks.get(k, [])
                        ],
                    }
                    for k, v in sorted(sector_map.items(), key=lambda x: abs(x[1]), reverse=True)
                ]
            
            # 缓存板块分析（低频查询，延长TTL）
            self._set_dragon_cache(cache_key, result, ttl=self._TTL_SECTOR)
            return result
        except Exception as e:
            logger.warning(f"龙虎榜板块分析失败: {e}")
            return {"date": target_date, "sectors": []}

    def get_dragon_consecutive(self, days: int = 5) -> dict:
        """近N日多次上榜的股票（真正筛选连续/重复上榜）"""
        try:
            result = {"days": days, "consecutive_stocks": []}

            # 收集需要查询的交易日
            today = datetime.now()
            cache_key = f'dragon_consecutive_{days}_{today.strftime("%Y%m%d")}'
            cached = self._get_dragon_cache(cache_key)
            if cached:
                return cached

            dates_to_fetch = []
            for i in range(days):
                candidate = today - timedelta(days=i)
                if is_trading_day(candidate):
                    dates_to_fetch.append(candidate.strftime('%Y%m%d'))

            if not dates_to_fetch:
                return result

            # 优化：一次请求拉取多天数据（filter_str 用日期范围），而非逐天查询
            start_date = dates_to_fetch[-1]  # 最早
            end_date = dates_to_fetch[0]      # 最晚
            date_em_start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            date_em_end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

            raw_data = EastMoneyDataCenter.dragon_tiger_board_range(date_em_start, date_em_end)

            # 按股票聚合：统计上榜次数、累计净买入额（按 code+date 去重后累加）
            stock_map = {}
            if raw_data:
                for item in raw_data:
                    code = str(item.get("SECURITY_CODE", ""))
                    if not code:
                        continue
                    trade_date_str = str(item.get("TRADE_DATE", "")).replace("-", "").replace(" ", "")[:8]
                    if trade_date_str not in dates_to_fetch:
                        continue

                    if code not in stock_map:
                        stock_map[code] = {
                            "code": code,
                            "name": str(item.get("SECURITY_NAME_ABBR", "")),
                            "price": float(item.get("CLOSE_PRICE") or 0),
                            "count": 0,
                            "total_net": 0.0,
                            "dates": set(),
                            "reasons": set(),
                            # 按 date 累计当日净买入额（同一天多条记录先累加到当天）
                            "_daily_net": {},
                        }
                    entry = stock_map[code]
                    if trade_date_str not in entry["dates"]:
                        entry["count"] += 1
                        entry["dates"].add(trade_date_str)
                        # 按 date 累计净买入（同一天多条记录累加）
                        entry["_daily_net"][trade_date_str] = float(item.get("BILLBOARD_NET_AMT") or 0)
                    else:
                        entry["_daily_net"][trade_date_str] += float(item.get("BILLBOARD_NET_AMT") or 0)
                    reason = str(item.get("EXPLANATION", "") or "")
                    for r in reason.split(";"):
                        if r.strip():
                            entry["reasons"].add(r.strip())

                # 从 _daily_net 计算 total_net（避免同日重复计算）
                for entry in stock_map.values():
                    entry["total_net"] = sum(entry["_daily_net"].values())
                    del entry["_daily_net"]

            # 转换 set → list，筛选上榜次数 >= 2
            consecutive = []
            for v in stock_map.values():
                if v["count"] >= 2:
                    v["dates"] = sorted(v["dates"])
                    v["reasons"] = list(v["reasons"])
                    v["total_net"] = round(v["total_net"], 2)
                    consecutive.append(v)
            consecutive.sort(key=lambda x: x["count"], reverse=True)

            result["consecutive_stocks"] = consecutive[:30]

            self._set_dragon_cache(cache_key, result, ttl=self._TTL_CONSECUTIVE)
            return result
        except Exception as e:
            logger.warning(f"连板龙虎榜失败: {e}")
            return {"days": days, "consecutive_stocks": []}

    def get_dragon_next_day_performance(self, force_refresh: bool = False) -> dict:
        """龙虎榜次日表现 — 查最近 10 个交易日的龙虎榜，
        按股票代码去重保留最新一次上榜，D1/D2/D5/D10 来自东财 datacenter。

        修复：之前只查最近一个交易日，最新上榜股票 D1 还没形成（东财滞后），
        导致 2/5/10 日涨跌全部为空。改为查 10 个交易日窗口，
        同一只股票只保留最新一次上榜记录，字段值由该上榜日决定。
        """
        try:
            today_str = datetime.now().strftime('%Y%m%d')
            cache_key = f'dragon_perf_{today_str}'
            if not force_refresh:
                cached = self._get_dragon_cache(cache_key)
                if cached:
                    return cached

            # 查最近 10 个交易日的龙虎榜范围
            end_date = _get_prev_trade_date()
            if not end_date:
                logger.warning("无法找到上一个交易日")
                return {
                    "date": today_str, "prev_date": None,
                    "stats": {"count": 0, "valid_count": 0, "avg_day1": 0, "avg_day5": 0, "avg_day10": 0, "win_rate_day1": 0},
                    "performance": [],
                }
            end_dt = datetime.strptime(end_date, '%Y%m%d')
            start_date = (end_dt - timedelta(days=20)).strftime('%Y%m%d')  # 20 个自然日窗口覆盖 10 个交易日
            try:
                raw_range = EastMoneyDataCenter.dragon_tiger_board_range(start_date, end_date)
            except Exception as e:
                logger.warning(f"龙虎榜范围查询失败: {e}")
                raw_range = []

            if not raw_range:
                logger.info(f"近 10 个交易日({start_date}~{end_date})无龙虎榜数据")
                return {
                    "date": today_str, "prev_date": end_date,
                    "stats": {"count": 0, "valid_count": 0, "avg_day1": 0, "avg_day5": 0, "avg_day10": 0, "win_rate_day1": 0},
                    "performance": [],
                }

            # 字段归一化：复用 _get_dragon_raw_data 的映射规则，但只保留必要字段
            normalized = []
            for item in raw_range:
                code = str(item.get("SECURITY_CODE", ""))
                if not code:
                    continue
                trade_date = str(item.get("TRADE_DATE", "")).replace("-", "").replace(" ", "")[:8]
                normalized.append({
                    "code": code,
                    "name": str(item.get("SECURITY_NAME_ABBR", "")),
                    "dragon_date": trade_date,
                    "price": float(item.get("CLOSE_PRICE") or 0),
                    "change_pct": round(float(item.get("CHANGE_RATE") or 0), 2),
                    "net_amount": float(item.get("BILLBOARD_NET_AMT") or 0),
                    "d1_change_pct": float(item.get("D1_CLOSE_ADJCHRATE") or 0) or None,
                    "d2_change_pct": float(item.get("D2_CLOSE_ADJCHRATE") or 0) or None,
                    "d5_change_pct": float(item.get("D5_CLOSE_ADJCHRATE") or 0) or None,
                    "d10_change_pct": float(item.get("D10_CLOSE_ADJCHRATE") or 0) or None,
                })

            # 按股票代码去重，保留最新一次上榜（dragon_date 最大的）
            by_code: dict = {}
            for item in normalized:
                code = item["code"]
                if code not in by_code or item["dragon_date"] > by_code[code]["dragon_date"]:
                    by_code[code] = item
            unique_list = list(by_code.values())

            # 按上榜日分组，每组内按净买入额降序
            # 跨日均匀采样：老上榜日（≥10 个交易日前）优先展示，确保 day10 有数据；
            # 凑齐 30 条后停止。这样能覆盖到 1/2/5/10 日全部字段的真实数据
            by_date: dict = {}
            for item in unique_list:
                by_date.setdefault(item["dragon_date"], []).append(item)
            sorted_dates = sorted(by_date.keys())  # 老→新
            # 计算"距今几个交易日"用于排序优先级
            from app.core.trading_calendar import get_last_trade_date as _gltd
            today = _gltd() or datetime.now().strftime('%Y%m%d')
            trade_dates = sorted(set(d.replace("-", "") for d in by_date.keys() if d))
            # 给每个上榜日算出"距今几个交易日"
            date_to_age = {}
            for d in sorted_dates:
                d_str = d.replace("-", "")
                if d_str in trade_dates:
                    date_to_age[d] = len(trade_dates) - trade_dates.index(d_str) - 1
                else:
                    date_to_age[d] = 0
            # 排序：老上榜日（age 大的）优先
            sorted_dates_by_age = sorted(by_date.keys(), key=lambda d: -date_to_age.get(d, 0))
            sampled = []
            for date in sorted_dates_by_age:
                group = sorted(by_date[date], key=lambda x: x.get("net_amount") or 0, reverse=True)
                # 前 6 个上榜日（老）每个取 3 条（保证 18 条有 day10），其余每天 2 条
                per_date = 3 if len(sampled) < 18 else 2
                sampled.extend(group[:per_date])
                if len(sampled) >= 30:
                    break
            # 按上榜日从老→新排序
            unique_list_sorted = sorted(sampled[:30], key=lambda x: (x["dragon_date"], -(x.get("net_amount") or 0)))

            # 拿一次行情，仅用于 day1 fallback（最新上榜日 D1 未就绪时）
            quote_map: dict = {}
            try:
                codes = [u["code"] for u in unique_list_sorted[:30]]
                quotes = TencentSource.get_quotes(codes)
                quote_map = {qc: q for qc, q in quotes.items()}
            except Exception as e:
                logger.debug(f"获取次日表现实时行情失败: {e}")

            performance_list = []
            for item in unique_list_sorted[:30]:
                d1_pct = item.get("d1_change_pct")
                d2_pct = item.get("d2_change_pct")
                d5_pct = item.get("d5_change_pct")
                d10_pct = item.get("d10_change_pct")

                # day1 fallback: 最新上榜日 D1 未就绪时，用腾讯实时涨跌幅（仅对今日最新上榜的）
                q = quote_map.get(item["code"])
                if d1_pct is None and q and item["dragon_date"] == end_date:
                    raw_change = q.get("change_pct")
                    if raw_change is not None:
                        d1_pct = float(raw_change)

                performance_list.append({
                    "code": item["code"],
                    "name": item["name"],
                    "dragon_date": item["dragon_date"],
                    "price": item["price"],
                    "change_pct": item["change_pct"],
                    "net_amount": item["net_amount"],
                    "day1": round(d1_pct, 2) if d1_pct is not None else None,
                    "day2": round(d2_pct, 2) if d2_pct is not None else None,
                    "day5": round(d5_pct, 2) if d5_pct is not None else None,
                    "day10": round(d10_pct, 2) if d10_pct is not None else None,
                })

            # 统计：有有效 day1 数据的股票
            valid_items = [p for p in performance_list if p.get("day1") is not None]
            total_valid = len(valid_items)

            # 聚合多日统计
            day_stats = {}
            for day_key in ["day1", "day2", "day5", "day10"]:
                day_values = [p[day_key] for p in performance_list if p.get(day_key) is not None]
                if day_values:
                    day_positive = sum(1 for v in day_values if v > 0)
                    day_stats[f"avg_{day_key}"] = round(sum(day_values) / len(day_values), 2)
                    day_stats[f"win_rate_{day_key}"] = round(day_positive / len(day_values) * 100, 1)
                else:
                    day_stats[f"avg_{day_key}"] = 0
                    day_stats[f"win_rate_{day_key}"] = 0

            result = {
                "date": today_str,
                "prev_date": end_date,
                "stats": {
                    "count": len(performance_list),
                    "valid_count": total_valid,
                    "avg_day1": day_stats.get("avg_day1", 0),
                    "avg_day5": day_stats.get("avg_day5", 0),
                    "avg_day10": day_stats.get("avg_day10", 0),
                    "win_rate_day1": day_stats.get("win_rate_day1", 0),
                },
                "performance": performance_list,
            }

            self._set_dragon_cache(cache_key, result, ttl=self._TTL_PERFORMANCE)
            return result
        except Exception as e:
            logger.warning(f"龙虎榜次日表现失败: {e}")
            return {
                "date": datetime.now().strftime('%Y%m%d'),
                "prev_date": None,
                "stats": {"count": 0, "valid_count": 0, "avg_day1": 0, "avg_day5": 0, "avg_day10": 0, "win_rate_day1": 0},
                "performance": [],
            }
