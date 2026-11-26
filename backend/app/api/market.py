"""市场看板API路由"""
import asyncio
from fastapi import APIRouter, Query, Depends
from typing import Optional
from app.services.market_service import MarketService
from app.core.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])
market_service = MarketService()

# 请求去重锁：相同参数请求在飞时共享同一个 Future
_inflight: dict[str, asyncio.Future] = {}


async def deduplicate(key: str, func):
    """如果相同 key 的请求正在执行，等待其结果；否则执行并缓存 Future。"""
    if key in _inflight and not _inflight[key].done():
        return await _inflight[key]

    future = asyncio.get_running_loop().create_future()
    _inflight[key] = future

    try:
        result = await func()
        if not future.done():
            future.set_result(result)
        return result
    except Exception as e:
        if not future.done():
            future.set_exception(e)
        raise
    finally:
        _inflight.pop(key, None)


async def with_timeout(key: str, func, timeout: float):
    """带超时的去重请求。"""
    try:
        return await asyncio.wait_for(deduplicate(key, func), timeout=timeout)
    except asyncio.TimeoutError:
        return {
            'error': '请求超时',
            'message': f'数据拉取超过{timeout}秒，请稍后重试',
            'timestamp': '',
        }


@router.get("/market/sentiment")
async def get_market_sentiment(date: Optional[str] = Query(None, description="日期，格式：YYYY-MM-DD")):
    """获取市场情绪指标（17项指标+综合评分）"""
    key = f"sentiment:{date}"
    return await with_timeout(key, lambda: asyncio.to_thread(market_service.get_sentiment, date), timeout=90)


@router.get("/market/sentiment/quick")
async def get_market_sentiment_quick(
    date: Optional[str] = Query(None, description="日期，格式：YYYY-MM-DD"),
    refresh: int = Query(0, description="强制刷新（1=强制）"),
):
    """快路径：不含资金流拆分（30s 超时）

    用于首屏快速渲染，5min 内命中前端 useCachedFetch 缓存。
    money_flow 数据优先使用东方财富大盘资金流，兜底同花顺行业资金流合计。
    """
    key = f"sentiment_quick:{date}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        market_service.get_market_sentiment, date, refresh == 1, False
    ), timeout=30)


@router.get("/market/sectors")
async def get_sector_overview(
    sector_type: str = Query("industry", description="板块类型：industry/concept"),
    top: int = Query(30, description="显示前N名"),
    refresh: int = Query(0, description="强制刷新（1=强制）"),
):
    """获取板块行情总览"""
    key = f"sectors:{sector_type}:{top}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        market_service.get_sector_overview, sector_type, top, refresh == 1
    ), timeout=45)


@router.get("/market/sectors/flow")
async def get_sector_flow(
    sector_type: str = Query("industry", description="板块类型：industry/concept"),
    top: int = Query(10, description="显示前N名")
):
    """获取板块资金流向"""
    key = f"sector_flow:{sector_type}:{top}"
    return await with_timeout(key, lambda: asyncio.to_thread(market_service.get_sector_flow, sector_type, top), timeout=45)


@router.get("/market/sectors/strength")
async def get_sector_strength(period: int = Query(20, description="RPS计算周期（日）")):
    """获取板块强度排名"""
    key = f"sector_strength:{period}"
    return await with_timeout(key, lambda: asyncio.to_thread(market_service.get_sector_strength, period), timeout=45)


@router.get("/market/hot")
async def get_hot_sectors(
    top: int = Query(10, description="显示前N个"),
    refresh: int = Query(0, description="强制刷新（1=强制）"),
):
    """获取热点题材"""
    key = f"hot:{top}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        market_service.get_hot_sectors, top, refresh == 1
    ), timeout=45)


@router.get("/market/signals")
async def get_rotation_signals(
    refresh: int = Query(0, description="强制刷新（1=强制）"),
):
    """获取板块轮动信号"""
    key = "signals"
    return await with_timeout(key, lambda: asyncio.to_thread(
        market_service.get_rotation_signals, refresh == 1
    ), timeout=60)


@router.get("/market/daily-report")
async def get_daily_report(
    style: str = Query("detailed", description="报告风格：concise/detailed/professional"),
    fmt: str = Query("json", description="输出格式：json/markdown/html")
):
    """获取每日复盘报告"""
    key = f"daily_report:{style}:{fmt}"
    return await with_timeout(key, lambda: asyncio.to_thread(market_service.get_daily_report, style, fmt), timeout=120)


@router.get("/market/northbound")
async def get_northbound_flow():
    """获取北向资金实时流向"""
    key = "northbound"
    return await with_timeout(key, lambda: asyncio.to_thread(market_service.get_northbound_flow), timeout=30)


@router.get("/market/indices/kline")
async def get_indices_with_kline(
    codes: str = Query("000001,399001,399006,000300,000016,000688", description="指数代码,逗号分隔"),
    n: int = Query(30, description="K线根数"),
):
    """获取指数列表 + 最近 N 日 K 线（pytdx 直连，无东财依赖）"""
    code_list = [c.strip() for c in codes.split(',') if c.strip()]
    key = f"indices_kline:{codes}:{n}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        market_service.get_indices_with_kline, code_list, n
    ), timeout=20)


@router.get("/market/limit_up_pool")
async def get_limit_up_pool(refresh: int = Query(0, description="强制刷新: 1=跳过缓存")):
    """获取涨停板池（同花顺 data.10jqka.com.cn）

    字段：板型分布（连板/一字/换手/开板）+ 总封单 + 连板最高 + 涨停股列表（行业、原因、封单）
    """
    key = "limit_up_pool"
    return await with_timeout(key, lambda: asyncio.to_thread(
        market_service.get_limit_up_pool, bool(refresh)
    ), timeout=30)


@router.get("/market/limit_down_pool")
async def get_limit_down_pool(refresh: int = Query(0, description="强制刷新: 1=跳过缓存")):
    """获取跌停板池（东财 push2 + 腾讯兜底）

    字段：跌停股列表（代码、名称、最新价、涨跌幅、成交额、换手率、行业、封单额等）
    """
    key = "limit_down_pool"
    return await with_timeout(key, lambda: asyncio.to_thread(
        market_service.get_limit_down_pool, bool(refresh)
    ), timeout=30)


@router.get("/market/ths_hot_rank")
async def get_ths_hot_rank(
    top: int = Query(30, description="显示前N个"),
    refresh: int = Query(0, description="强制刷新: 1=跳过缓存"),
):
    """获取同花顺热门个股榜（THS 人工归因 + 资金流 + 涨幅 综合评分）"""
    key = f"ths_hot_rank:{top}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        market_service.get_ths_hot_rank, top, bool(refresh)
    ), timeout=60)


@router.get("/market/dashboard/combined")
async def get_dashboard_combined(
    top: int = Query(30, description="热门榜显示前N个"),
    force: int = Query(0, description="强制刷新（1=强制）"),
):
    """合并端点：资金流拆分 + THS热门榜，共享底层数据源。

    优化前：capitalFlow (~30s) + thsHotRank (~15s) = 2个独立请求
    优化后：一次拉取 THS 热点归因 + 资金流 + 腾讯报价，~20-25s
    """
    key = f"dashboard_combined:{top}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        market_service.get_dashboard_combined, top, force == 1
    ), timeout=45)


@router.get("/market/dashboard/full")
async def get_market_dashboard_full(
    force: int = Query(0, description="强制刷新（1=强制）"),
):
    """市场看板完整聚合：一次性返回首页所有模块数据。

    优化前：8个独立请求（sentiment + 2*sectors + hot + signals + indices + northbound + limitUp + combined）
    优化后：1个请求，后端并发拉取，总耗时 = 最慢接口（约30-45s）

    包含模块：
    - sentiment_quick: 市场情绪（不含资金流，快速版）
    - sectors_industry: 行业板块
    - sectors_concept: 概念板块
    - hot_sectors: 热门板块
    - rotation_signals: 轮动信号
    - indices_kline: 指数K线
    - northbound_flow: 北向资金
    - limit_up_pool: 涨停板池
    - dashboard_combined: 资金流 + THS热门榜
    """
    key = f"market_dashboard_full"
    return await with_timeout(key, lambda: asyncio.to_thread(
        market_service.get_market_dashboard, force == 1
    ), timeout=120)


@router.get("/market/trading-date")
async def get_trading_date():
    """获取当前交易日信息，供前端轮询检测交易日切换
    
    返回：
    - trading_date: 当前交易日（YYYYMMDD格式）
    - trading_date_display: 显示格式（YYYY-MM-DD）
    - is_trading_day: 是否为交易日
    - is_trading_hours: 是否在交易时段
    - update_time: 更新时间
    """
    from app.core.trading_calendar import get_last_trade_date, is_trading_day, is_trading_hours
    from datetime import datetime
    
    now = datetime.now()
    trading_date = get_last_trade_date()
    is_trading = is_trading_day(now)
    is_hours = is_trading_hours(now)
    
    return {
        "trading_date": trading_date,
        "trading_date_display": f"{trading_date[:4]}-{trading_date[4:6]}-{trading_date[6:]}",
        "is_trading_day": is_trading,
        "is_trading_hours": is_hours,
        "update_time": now.strftime("%H:%M:%S"),
    }


@router.get("/market/precompute/status")
async def get_precompute_status():
    """获取预计算服务状态"""
    try:
        from app.services.precompute_service import precompute_service
        last_update = precompute_service.get_last_update()
        return {
            "status": "running" if precompute_service._running else "stopped",
            "last_update": last_update,
            "redis_available": precompute_service._redis_available,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/market/precompute/force")
async def force_precompute():
    """强制执行一次预计算"""
    try:
        from app.services.precompute_service import precompute_service
        precompute_service.force_precompute()
        return {"status": "success", "message": "预计算已触发"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/market/precompute/sector-stats")
async def get_precomputed_sector_stats():
    """获取预计算的板块统计（优先从Redis读取）"""
    try:
        from app.services.precompute_service import precompute_service
        stats = precompute_service.get_sector_stats()
        if stats:
            return {"source": "precomputed", "data": stats}
        # 降级到实时计算
        return await with_timeout("precompute:sector", lambda: asyncio.to_thread(
            market_service.get_sectors, 'industry', 30
        ), timeout=30)
    except Exception as e:
        return {"error": str(e)}


@router.get("/market/precompute/limit-stocks")
async def get_precomputed_limit_stocks():
    """获取预计算的涨跌停数据（优先从Redis读取）"""
    try:
        from app.services.precompute_service import precompute_service
        data = precompute_service.get_limit_stocks()
        if data:
            return {"source": "precomputed", "data": data}
        # 降级到实时计算
        return await with_timeout("precompute:limit", lambda: asyncio.to_thread(
            market_service.get_limit_up_pool
        ), timeout=30)
    except Exception as e:
        return {"error": str(e)}


@router.get("/market/precompute/breadth")
async def get_precomputed_breadth():
    """获取预计算的全市场广度（优先从Redis读取）"""
    try:
        from app.services.precompute_service import precompute_service
        breadth = precompute_service.get_market_breadth()
        if breadth:
            return {"source": "precomputed", "data": breadth}
        # 降级到实时计算
        return await with_timeout("precompute:breadth", lambda: asyncio.to_thread(
            market_service.get_market_sentiment, None, False, False
        ), timeout=30)
    except Exception as e:
        return {"error": str(e)}
