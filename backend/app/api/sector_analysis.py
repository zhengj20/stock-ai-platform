"""板块深度分析API路由 — 涨停梯队/轮动量化/行业研报/热度排行/产业链/对比工具"""
import asyncio
from fastapi import APIRouter, Query, Depends
from typing import Optional

from app.services.sector_analysis_service import sector_analysis_service
from app.core.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

# 请求去重锁
_inflight: dict[str, asyncio.Future] = {}


async def deduplicate(key: str, func):
    """如果相同 key 的请求正在执行，等待其结果"""
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
    """带超时的去重请求"""
    try:
        return await asyncio.wait_for(deduplicate(key, func), timeout=timeout)
    except asyncio.TimeoutError:
        return {
            'error': '请求超时',
            'message': f'数据拉取超过{timeout}秒，请稍后重试',
        }


@router.get("/sector-analysis/limit-ladder")
async def get_limit_up_ladder(
    date: Optional[str] = Query(None, description="日期YYYYMMDD"),
    refresh: int = Query(0, description="强制刷新: 1=跳过缓存"),
):
    """涨停梯队分析：连板分布 + 炸板率 + 涨跌停对比 + 板块聚合
    
    数据源：东方财富 push2ex (涨停池/炸板池/跌停池/昨日涨停池)
    """
    key = f"limit_ladder:{date}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        sector_analysis_service.get_limit_up_ladder, date, refresh == 1
    ), timeout=45)


@router.get("/sector-analysis/rotation-model")
async def get_sector_rotation_model(
    sector_type: str = Query("industry", description="板块类型：industry/concept"),
    top_n: int = Query(30, description="显示前N名"),
    refresh: int = Query(0, description="强制刷新: 1=跳过缓存"),
):
    """板块轮动量化模型：综合评分 + 生命周期识别
    
    计算维度：RPS强度、资金流向得分、成交额变化率、涨跌家数比
    """
    key = f"rotation_model:{sector_type}:{top_n}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        sector_analysis_service.get_sector_rotation_model, sector_type, top_n, refresh == 1
    ), timeout=45)


@router.get("/sector-analysis/industry-reports")
async def get_industry_research_reports(
    top_n: int = Query(30, description="显示前N条"),
    refresh: int = Query(0, description="强制刷新: 1=跳过缓存"),
):
    """行业研报聚合：按行业分类的最新研报 + 评级统计
    
    数据源：东方财富 reportapi (qType=1 行业研报)
    """
    key = f"industry_reports:{top_n}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        sector_analysis_service.get_industry_research_reports, top_n, refresh == 1
    ), timeout=45)


@router.get("/sector-analysis/heat-rank")
async def get_sector_heat_rank(
    top_n: int = Query(30, description="显示前N个"),
    refresh: int = Query(0, description="强制刷新: 1=跳过缓存"),
):
    """板块热度排行：基于同花顺热榜+东财人气榜的概念反向聚合
    
    数据源：同花顺热榜(dq.10jqka) + 东财人气榜(emappdata)
    """
    key = f"heat_rank:{top_n}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        sector_analysis_service.get_sector_heat_rank, top_n, refresh == 1
    ), timeout=45)


@router.get("/sector-analysis/industry-chain")
async def get_industry_chain_analysis(
    refresh: int = Query(0, description="强制刷新: 1=跳过缓存"),
):
    """产业链深度分析：上下游关系 + 传导信号
    
    覆盖产业链：新能源、半导体、人工智能、医药生物、消费电子
    """
    key = "industry_chain"
    return await with_timeout(key, lambda: asyncio.to_thread(
        sector_analysis_service.get_industry_chain_analysis, refresh == 1
    ), timeout=45)


@router.get("/sector-analysis/comparison")
async def get_sector_comparison(
    names: Optional[str] = Query(None, description="板块名称，逗号分隔"),
    sector_type: str = Query("industry", description="板块类型：industry/concept"),
    refresh: int = Query(0, description="强制刷新: 1=跳过缓存"),
):
    """多板块对比工具：行情 + 资金流 + 强度 + 生命周期
    
    names为空时默认取前10个板块
    """
    name_list = [n.strip() for n in names.split(",") if n.strip()] if names else None
    key = f"comparison:{','.join(sorted(name_list or ['top']))}:{sector_type}"
    return await with_timeout(key, lambda: asyncio.to_thread(
        sector_analysis_service.get_sector_comparison, name_list, sector_type, refresh == 1
    ), timeout=45)
