"""策略中心API路由"""
import asyncio
import logging
from fastapi import APIRouter, Query, Depends
from typing import Optional
from app.services.strategy_service import StrategyService, _add_meta
from app.core.auth import get_current_user, get_current_admin
from app.core.trading_calendar import should_force_refresh
from app.core.cache import NS_STRATEGY

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)])
strategy_service = StrategyService()


def _should_force(refresh: bool) -> bool:
    """手动刷新参数过滤
    
    策略：
    - 交易时间：允许 force_refresh
    - 非交易时间：仅当缓存为空时允许 force_refresh（首次加载），否则忽略
    """
    if not refresh:
        return False
    
    # 交易时间允许 force
    if should_force_refresh():
        return True
    
    # 非交易时间：检查缓存是否有数据，有则不强制刷新
    # 由 service 层判断缓存是否为空
    return True  # 放行，由 service 层决定是否真正刷新


def _wrap_response(result):
    """为响应添加元数据（日期、更新时间）"""
    if isinstance(result, dict) and ("stocks" in result or "combined_stocks" in result or "todayList" in result or "gainers" in result or "performance" in result):
        return _add_meta(result)
    # 兜底：只要是 dict 且没有 data_date，就添加元数据
    if isinstance(result, dict) and not result.get("data_date"):
        return _add_meta(result)
    return result


@router.get("/strategy/comparison")
async def get_strategy_comparison(refresh: bool = Query(False, description="强制刷新缓存")):
    """获取策略对比表"""
    return await asyncio.to_thread(strategy_service.get_strategy_comparison, force_refresh=_should_force(refresh))


@router.get("/dragon/today")
async def get_dragon_list_today(
    refresh: bool = Query(False, description="强制刷新缓存")
):
    """获取今日龙虎榜"""
    # 非交易时间 refresh=true 不绕过 SWR 缓存（与其他 dragon 端点保持一致）
    result = await asyncio.to_thread(strategy_service.get_dragon_list_today, force_refresh=_should_force(refresh))
    return _wrap_response(result)


@router.get("/dragon/strategy")
async def get_dragon_strategy(
    strategy_type: str = Query("all", description="策略类型：institution/synergy/resonance/premium/all"),
    refresh: bool = Query(False, description="强制刷新缓存"),
    top_n: int = Query(15, description="输出前N只"),
    market_cap: Optional[str] = Query(None, description="市值范围：large/mid/small"),
    min_amount: Optional[int] = Query(None, description="成交额下限(万元)"),
    change_range: Optional[str] = Query(None, description="涨跌幅区间"),
    exclude_st: Optional[str] = Query(None, description="排除ST股：true/false")
):
    """执行龙虎榜选股策略"""
    kwargs = {'strategy_type': strategy_type, 'force_refresh': refresh, 'top_n': top_n}
    if market_cap:
        kwargs['market_cap'] = market_cap
    if min_amount is not None:
        kwargs['min_amount'] = min_amount
    if change_range is not None:
        kwargs['change_range'] = change_range
    if exclude_st == 'true':
        kwargs['exclude_st'] = True
    result = await asyncio.to_thread(strategy_service.get_dragon_list_strategy, **kwargs)
    return _wrap_response(result)


@router.post("/dragon/refresh")
async def refresh_dragon_cache(current_user = Depends(get_current_admin)):
    """手动清除龙虎榜所有缓存（下次请求将重新拉取）"""
    StrategyService.clear_dragon_cache()
    return {'status': 'success', 'message': '龙虎榜缓存已清除'}


@router.get("/dragon/history/{date}")
async def get_dragon_history(date: str):
    """获取历史龙虎榜"""
    result = await asyncio.to_thread(strategy_service.get_dragon_list_history, date)
    return _wrap_response(result)


@router.post("/ml/train")
async def train_ml_model(
    days: int = Query(250, description="训练数据天数"),
    stocks: int = Query(100, description="训练股票数量"),
    model: str = Query("lightgbm", description="模型类型：lightgbm/xgboost"),
    current_user = Depends(get_current_admin)
):
    """训练ML选股模型（管理员操作）"""
    return await asyncio.to_thread(strategy_service.train_ml_model, days, stocks, model)


@router.get("/ml/status")
async def get_ml_model_status(
    current_user = Depends(get_current_user)
):
    """获取ML模型状态（所有用户可查看）"""
    return await asyncio.to_thread(strategy_service.get_ml_model_status)


@router.get("/ml/predict")
async def predict_ml_stocks(
    top_n: int = Query(30, description="输出前N只"),
    refresh: bool = Query(False, description="强制刷新缓存"),
    market_cap: Optional[str] = Query(None, description="市值范围：large/mid/small"),
    min_amount: Optional[int] = Query(None, description="成交额下限(万元)"),
    change_range: Optional[str] = Query(None, description="涨跌幅区间：no_limit_up/no_limit_down/no_limit/up/down"),
    exclude_st: Optional[str] = Query(None, description="排除ST股：true/false")
):
    """ML选股预测"""
    kwargs = {'top_n': top_n, 'force_refresh': refresh}
    if market_cap:
        kwargs['market_cap'] = market_cap
    if min_amount is not None:
        kwargs['min_amount'] = min_amount
    if change_range is not None:
        kwargs['change_range'] = change_range
    if exclude_st == 'true':
        kwargs['exclude_st'] = True
    result = await asyncio.to_thread(strategy_service.predict_ml_stocks, **kwargs)
    return _wrap_response(result)


@router.get("/strategy/multi-factor-picks")
async def get_multi_factor_picks(
    top_n: int = Query(20, description="输出前N只"),
    market_cap: Optional[str] = Query(None, description="市值范围：large/mid/small"),
    min_amount: Optional[int] = Query(None, description="成交额下限(万元)"),
    change_range: Optional[str] = Query(None, description="涨跌幅区间：no_limit_up/no_limit_down/no_limit/up/down"),
    exclude_st: Optional[str] = Query(None, description="排除ST股：true/false"),
    refresh: bool = Query(False, description="强制刷新缓存")
):
    """多因子选股 - 支持筛选条件"""
    kwargs = {'top_n': top_n, 'force_refresh': refresh}
    if market_cap:
        kwargs['market_cap'] = market_cap
    if min_amount is not None:
        kwargs['min_amount'] = min_amount
    if change_range is not None:
        kwargs['change_range'] = change_range
    if exclude_st == 'true':
        kwargs['exclude_st'] = True
    result = await asyncio.to_thread(strategy_service.get_multi_factor_picks, **kwargs)
    return _wrap_response(result)


@router.get("/strategy/low-absorption-picks")
async def get_low_absorption_picks(
    top_n: int = Query(20, description="输出前N只"),
    market_cap: Optional[str] = Query(None, description="市值范围：large/mid/small"),
    min_amount: Optional[int] = Query(None, description="成交额下限(万元)"),
    change_range: Optional[str] = Query(None, description="涨跌幅区间：no_limit_up/no_limit_down/no_limit/up/down"),
    exclude_st: Optional[str] = Query(None, description="排除ST股：true/false"),
    refresh: bool = Query(False, description="强制刷新缓存")
):
    """低吸企稳选股 - 超跌反弹策略"""
    kwargs = {'top_n': top_n, 'force_refresh': refresh}
    if market_cap:
        kwargs['market_cap'] = market_cap
    if min_amount is not None:
        kwargs['min_amount'] = min_amount
    if change_range is not None:
        kwargs['change_range'] = change_range
    if exclude_st == 'true':
        kwargs['exclude_st'] = True
    result = await asyncio.to_thread(strategy_service.get_low_absorption_picks, **kwargs)
    return _wrap_response(result)


@router.get("/strategy/capital-flow-picks")
async def get_capital_flow_picks(
    top_n: int = Query(20, description="输出前N只"),
    market_cap: Optional[str] = Query(None, description="市值范围：large/mid/small"),
    min_amount: Optional[int] = Query(None, description="成交额下限(万元)"),
    change_range: Optional[str] = Query(None, description="涨跌幅区间：no_limit_up/no_limit_down/no_limit/up/down"),
    exclude_st: Optional[str] = Query(None, description="排除ST股：true/false"),
    refresh: bool = Query(False, description="强制刷新缓存")
):
    """资金流向选股 - 量价配合策略"""
    kwargs = {'top_n': top_n, 'force_refresh': refresh}
    if market_cap:
        kwargs['market_cap'] = market_cap
    if min_amount is not None:
        kwargs['min_amount'] = min_amount
    if change_range is not None:
        kwargs['change_range'] = change_range
    if exclude_st == 'true':
        kwargs['exclude_st'] = True
    result = await asyncio.to_thread(strategy_service.get_capital_flow_picks, **kwargs)
    return _wrap_response(result)


@router.get("/strategy/volume-price-divergence")
async def get_volume_price_divergence_picks(
    top_n: int = Query(20, description="输出前N只"),
    market_cap: Optional[str] = Query(None, description="市值范围：large/mid/small"),
    min_amount: Optional[int] = Query(None, description="成交额下限(万元)"),
    change_range: Optional[str] = Query(None, description="涨跌幅区间"),
    exclude_st: Optional[str] = Query(None, description="排除ST股：true/false"),
    refresh: bool = Query(False, description="强制刷新缓存")
):
    """量价背离选股 - 识别底背离/顶背离/量价齐升等模式"""
    kwargs = {'top_n': top_n, 'force_refresh': _should_force(refresh)}
    if market_cap:
        kwargs['market_cap'] = market_cap
    if min_amount is not None:
        kwargs['min_amount'] = min_amount
    if change_range is not None:
        kwargs['change_range'] = change_range
    if exclude_st == 'true':
        kwargs['exclude_st'] = True
    result = await asyncio.to_thread(strategy_service.get_volume_price_divergence_picks, **kwargs)
    return _wrap_response(result)


@router.get("/strategy/leader-picks")
async def get_leader_picks(
    sector_type: str = Query("industry", description="板块类型：industry/concept"),
    top_n: int = Query(3, description="每板块龙头数"),
    sector_count: int = Query(10, description="板块数量"),
    market_cap: Optional[str] = Query(None, description="市值范围：large/mid/small"),
    min_amount: Optional[int] = Query(None, description="成交额下限(万元)"),
    exclude_st: Optional[str] = Query("true", description="排除ST股：true/false"),
    refresh: bool = Query(False, description="强制刷新缓存")
):
    """龙头选股 - 每个板块取综合评分最高的 N 只龙头股

    评分维度：板块内涨幅 25% + 成交额 20% + 市值 10% + 技术分 20% + 基本面 10% + 连板数 15%
    板块筛选：5日板块强度（避免一日游板块）+ 当日涨幅 + 主力净流入
    """
    kwargs = {
        'sector_type': sector_type,
        'top_n': top_n,
        'sector_count': sector_count,
        'force_refresh': _should_force(refresh),
    }
    if market_cap:
        kwargs['market_cap'] = market_cap
    if min_amount is not None:
        kwargs['min_amount'] = min_amount
    if exclude_st is not None:
        kwargs['exclude_st'] = (exclude_st == 'true')
    result = await asyncio.to_thread(strategy_service.get_leader_picks, **kwargs)
    return _wrap_response(result)


@router.get("/strategy/combo")
async def get_strategy_combo(
    top_n: int = Query(20, description="输出前N只"),
    mode: str = Query("vote", description="融合模式：vote/weight"),
    refresh: bool = Query(False, description="强制刷新缓存"),
    market_cap: Optional[str] = Query(None, description="市值范围：large/mid/small"),
    min_amount: Optional[int] = Query(None, description="成交额下限(万元)"),
    change_range: Optional[str] = Query(None, description="涨跌幅区间"),
    exclude_st: Optional[str] = Query(None, description="排除ST股：true/false")
):
    """策略组合引擎 - 多策略信号融合"""
    kwargs = {'top_n': top_n, 'mode': mode, 'force_refresh': refresh}
    if market_cap:
        kwargs['market_cap'] = market_cap
    if min_amount is not None:
        kwargs['min_amount'] = min_amount
    if change_range is not None:
        kwargs['change_range'] = change_range
    if exclude_st == 'true':
        kwargs['exclude_st'] = True

    # 先尝试直接返回缓存（子策略各自有缓存，组合层只做融合）
    from app.services.strategy_service import _get_strategy_target_date as get_target_date_fn
    target_date = get_target_date_fn()
    # cache_key 必须与 strategy_service.get_strategy_combo 中构造方式一致（exclude_st 实际值）
    actual_exclude_st = (exclude_st == 'true')
    cache_key = f'strategy_combo_{mode}_{top_n}_{actual_exclude_st}_{target_date}'
    cached = StrategyService._get_dragon_cache(cache_key, namespace=NS_STRATEGY)
    if cached and not refresh:
        return _wrap_response(cached)

    result = await asyncio.to_thread(strategy_service.get_strategy_combo, **kwargs)
    return _wrap_response(result)


@router.get("/dragon/hot-money")
async def get_hot_money_tracking():
    """获取活跃游资追踪数据"""
    result = await asyncio.to_thread(strategy_service.get_hot_money_tracking)
    return _wrap_response(result)


@router.get("/dragon/capital-flow")
async def get_dragon_capital_flow(refresh: bool = Query(False, description="强制刷新缓存")):
    """龙虎榜主力资金净流向 - 机构vs游资对比"""
    result = await asyncio.to_thread(strategy_service.get_dragon_capital_flow, force_refresh=_should_force(refresh))
    return _wrap_response(result)


@router.get("/dragon/seat-detail")
async def get_dragon_seat_detail(refresh: bool = Query(False, description="强制刷新缓存")):
    """龙虎榜机构席位明细 - 买卖方席位金额"""
    result = await asyncio.to_thread(strategy_service.get_dragon_seat_detail, force_refresh=_should_force(refresh))
    return _wrap_response(result)


@router.get("/dragon/sector-analysis")
async def get_dragon_sector_analysis(refresh: bool = Query(False, description="强制刷新缓存")):
    """龙虎榜板块归属分析 - 按行业/概念聚合"""
    result = await asyncio.to_thread(strategy_service.get_dragon_sector_analysis, force_refresh=_should_force(refresh))
    return _wrap_response(result)


@router.get("/dragon/consecutive")
async def get_dragon_consecutive(days: int = Query(5, description="查询天数")):
    """龙虎榜连续上榜 - 近N日多次上榜的股票"""
    result = await asyncio.to_thread(strategy_service.get_dragon_consecutive, days)
    return _wrap_response(result)


@router.get("/dragon/next-day-performance")
async def get_dragon_next_day_performance(refresh: bool = Query(False, description="强制刷新缓存")):
    """龙虎榜次日表现追踪 - 上榜后1/3/5日涨跌"""
    result = await asyncio.to_thread(strategy_service.get_dragon_next_day_performance, force_refresh=_should_force(refresh))
    return _wrap_response(result)


# ── 异步任务API ──────────────────────────────────────

@router.post("/task/submit/{task_type}")
async def submit_task(task_type: str, top_n: int = Query(20, description="返回数量")):
    """提交异步任务
    
    支持的任务类型：
    - combo: 组合策略
    - dragon: 龙虎榜分析
    - market: 市场概览
    """
    try:
        from app.services.task_queue import (
            submit_combo_strategy_task,
            submit_dragon_analysis_task,
            submit_market_overview_task
        )
        
        if task_type == "combo":
            task_id = submit_combo_strategy_task(top_n=top_n)
        elif task_type == "dragon":
            task_id = submit_dragon_analysis_task()
        elif task_type == "market":
            task_id = submit_market_overview_task()
        else:
            return {"error": f"未知任务类型: {task_type}"}
        
        return {"task_id": task_id, "status": "submitted", "task_type": task_type}
    except Exception as e:
        return {"error": str(e)}


@router.get("/task/status/{task_id}")
async def get_task_status(task_id: str):
    """获取任务状态"""
    try:
        from app.services.task_queue import task_queue
        task_info = task_queue.get_task(task_id)
        if not task_info:
            return {"error": "任务不存在"}
        return task_info.to_dict()
    except Exception as e:
        return {"error": str(e)}


@router.post("/task/cancel/{task_id}")
async def cancel_task(task_id: str):
    """取消任务"""
    try:
        from app.services.task_queue import task_queue
        success = task_queue.cancel_task(task_id)
        if success:
            return {"status": "success", "message": "任务已取消"}
        else:
            return {"status": "failed", "message": "无法取消任务（可能已完成或不存在）"}
    except Exception as e:
        return {"error": str(e)}

@router.post("/kline/preload")
async def preload_klines(current_user = Depends(get_current_admin)):
    """预加载全市场K线到Redis缓存（管理员操作）"""
    try:
        from app.core.data_sources import TencentSource
        full_market = TencentSource.get_full_market()
        if not full_market:
            return {"status": "error", "message": "全市场数据为空"}
        
        # 按成交额排序，取TOP500预加载
        sorted_by_amount = sorted(full_market, key=lambda x: float(x.get("f10", 0) or 0), reverse=True)
        codes = [str(item.get("f12", "")) for item in sorted_by_amount[:500] 
                 if str(item.get("f12", "")).isdigit() and len(str(item.get("f12", ""))) == 6]
        
        from app.services.strategy_service import _preload_daily_klines
        _preload_daily_klines(codes)
        
        return {"status": "success", "message": f"预加载 {len(codes)} 只股票的K线"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/strategy/info")
async def get_strategy_info():
    """获取策略信息（前端展示用）— 包含回测统计和ML模型状态"""
    from app.services.ml_model_service import ml_model_service
    
    # 获取各策略的回测结果
    backtest_results = {}
    for strategy_key, profile in [
        ("multifactor", "trend_breakout"),
        ("ml", "balanced"), 
        ("lowabs", "oversold_bounce"),
        ("volprice_div", "capital_resonance"),
    ]:
        try:
            bt_result = backtester.backtest_strategy(profile, days=30)
            backtest_results[strategy_key] = {
                "win_rate": bt_result.get("win_rate", 0),
                "avg_return": bt_result.get("avg_return", 0),
                "total_trades": bt_result.get("total_trades", 0),
                "max_drawdown": bt_result.get("max_drawdown", 0),
            }
        except Exception as e:
            logger.debug(f"获取回测结果失败 ({strategy_key}): {e}")
            backtest_results[strategy_key] = {}
    
    # 获取ML模型状态
    ml_info = ml_model_service.get_model_info()
    
    return {
        "strategies": [
            {
                "name": "趋势突破",
                "key": "multifactor",
                "description": "全市场扫描，筛选均线多头排列+放量突破的活跃标的。综合技术面(60%)+基本面(40%)评分。",
                "profile": "trend_breakout",
                "weights": {"动量": "25%", "均线": "20%", "量比": "15%", "MACD": "15%"},
                "candidate_pool": "全市场TOP300（按成交额）",
                "backtest": backtest_results.get("multifactor", {}),
            },
            {
                "name": "技术评分", 
                "key": "ml",
                "description": "LightGBM/XGBoost机器学习模型预测。模型不可用时自动降级为因子引擎评分。",
                "profile": "balanced",
                "weights": {"动量": "20%", "均线": "15%", "量比": "15%", "MACD": "15%"},
                "candidate_pool": "全市场TOP300（按成交额）",
                "ml_model_status": {
                    "loaded": ml_info.get("classifier_loaded") or ml_info.get("regressor_loaded"),
                    "features": ml_info.get("feature_count", 0),
                    "file_exists": ml_info.get("classifier_exists") or ml_info.get("regressor_exists"),
                },
                "backtest": backtest_results.get("ml", {}),
            },
            {
                "name": "低吸企稳",
                "key": "lowabs", 
                "description": "筛选跌幅3%-10%+超卖信号(RSI<35或KDJ-J<25)的股票，缩量筑底加分。",
                "profile": "oversold_bounce",
                "weights": {"RSI": "25%", "KDJ": "20%", "量比": "15%", "跌幅": "15%"},
                "candidate_pool": "全市场跌幅3%-10%",
                "backtest": backtest_results.get("lowabs", {}),
            },
            {
                "name": "量价关系",
                "key": "volprice_div",
                "description": "识别底背离、顶背离、量价齐升等6种量价模式。候选池来自龙虎榜+涨停池。",
                "profile": "capital_resonance", 
                "weights": {"量比": "20%", "MACD": "20%", "动量": "15%"},
                "candidate_pool": "龙虎榜+涨停池",
                "backtest": backtest_results.get("volprice_div", {}),
            },
        ],
        "ml_model_info": ml_info,
    }
