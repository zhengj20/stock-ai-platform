"""个股诊断API路由"""
import asyncio
import json
import logging
import urllib.request
from fastapi import APIRouter, Query, Depends
from typing import Optional
from app.services.stock_service import StockService
from app.core.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)])
# 消息面接口进程级内存缓存：{key: (timestamp, response)}
_NEWS_CACHE: dict = {}
stock_service = StockService()


def _fetch_sina_kline(code: str, count: int = 200) -> list[dict]:
    """新浪K线兜底（日K，前复权）"""
    prefix = "sh" if code.startswith("6") else "sz"
    sym = f"{prefix}{code}"
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": sym,
        "scale": "240",
        "ma": "no",
        "datalen": str(count),
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{url}?{query}")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = json.loads(res.read().decode("utf-8"))
        if not isinstance(raw, list) or len(raw) == 0:
            return []
        results = []
        for item in raw:
            results.append({
                "date": item.get("day", ""),
                "open": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "close": float(item.get("close", 0)),
                "volume": int(float(item.get("volume", 0))),
            })
        return results
    except Exception as e:
        logger.debug(f"新浪K线获取失败 ({code}): {e}")
        return []


@router.get("/stock/technical/{stock_code}")
async def get_technical_indicators(
    stock_code: str,
    period: str = Query("近一年", description="时间范围：近一年/近两年/近半年")
):
    """获取技术指标分析（MACD/KDJ/RSI/BOLL等10项指标）"""
    if not stock_code or len(stock_code) != 6:
        return {"status": "error", "message": f"股票代码无效: {stock_code}"}
    return await stock_service.get_technical_indicators(stock_code, period)


@router.get("/stock/patterns/{stock_code}")
async def get_kline_patterns(
    stock_code: str,
    periods: int = Query(200, description="扫描K线数量"),
    direction: str = Query("all", description="信号方向：all/bullish/bearish")
):
    """获取K线形态识别（21种形态）"""
    if not stock_code or len(stock_code) != 6:
        return {"status": "error", "message": f"股票代码无效: {stock_code}"}
    return await stock_service.get_kline_patterns(stock_code, periods, direction)


@router.get("/stock/factors")
async def get_multi_factor_score(
    stocks: str = Query(..., description="股票代码列表，逗号分隔"),
    factors: Optional[str] = Query(None, description="因子列表，逗号分隔"),
    weight: str = Query("equal_weight", description="权重方法：equal_weight/ic_weight/custom"),
    top_n: int = Query(10, description="输出前N只")
):
    """获取多因子评分（27个量化因子）"""
    stock_list = [s.strip() for s in stocks.split(",")]
    factor_list = [f.strip() for f in factors.split(",")] if factors else None
    return await stock_service.get_multi_factor_score(stock_list, factor_list, weight, top_n)


@router.get("/stock/diagnosis/{stock_code}")
async def get_stock_diagnosis(stock_code: str):
    """获取个股综合诊断报告（行情+指标+形态+基本面），整体超时25秒"""
    import asyncio, logging
    log = logging.getLogger(__name__)
    try:
        result = await asyncio.wait_for(
            stock_service.get_stock_diagnosis(stock_code),
            timeout=25.0,
        )
        return result
    except asyncio.TimeoutError:
        log.warning(f"Diagnosis timeout for {stock_code} (>25s)")
        return {"error": True, "error_msg": "诊断数据加载超时，请稍后重试", "stock_code": stock_code, "timeout": True}
    except Exception as e:
        log.error(f"Diagnosis failed for {stock_code}: {e}", exc_info=True)
        return {"error": True, "error_msg": str(e), "stock_code": stock_code}


@router.get("/stock/search")
async def search_stocks(query: str = Query(..., description="自然语言选股条件")):
    """智能选股搜索"""
    return await stock_service.search_stocks(query)


@router.get("/stock/suggest")
async def suggest_stocks(q: str = Query("", description="股票代码或名称前缀")):
    """股票搜索建议（用于前端自动补全）"""
    if not q.strip():
        return []
    from app.services.stock_service import _get_all_stock_list
    all_stocks = _get_all_stock_list()
    q_upper = q.strip().upper()

    import unicodedata
    def _norm(s):
        return unicodedata.normalize('NFKC', s).replace(' ', '')

    q_norm = _norm(q_upper)
    matched = []
    for s in all_stocks:
        if q_upper in s['code'] or q_norm in _norm(s['name']):
            matched.append({'code': s['code'], 'name': s['name']})
            if len(matched) >= 10:
                break
    if not matched:
        from app.services.stock_service import STOCK_NAMES
        for code, name in STOCK_NAMES.items():
            if q_upper in code or q_norm in _norm(name):
                matched.append({'code': code, 'name': name})
                if len(matched) >= 10:
                    break
    return matched


@router.get("/stock/news/{stock_code}")
async def get_stock_news(
    stock_code: str,
    top_n: int = Query(5, ge=3, le=20),
):
    """获取个股相关新闻/公告（用于诊断页面消息面分析），整体超时8秒
    
    优先级：资讯新闻 > 概念板块资讯 > 巨潮公告
    优化：只搜索股票名称，按优先级依次获取，快速返回
    """
    from app.services.news_service import search_news

    # 进程级内存缓存（60秒内直接返回）
    import time as _t
    cache_key = f"news_{stock_code}_{top_n}"
    now = _t.time()
    cached = _NEWS_CACHE.get(cache_key)
    if cached and (now - cached[0]) < 60:
        return cached[1]

    # 获取股票名称（快速，3秒超时）
    name = ""
    try:
        name = await asyncio.wait_for(
            asyncio.to_thread(stock_service._get_stock_name, stock_code),
            timeout=2.0
        )
    except Exception as e:
        logger.debug(f"获取股票名称失败 ({stock_code}): {e}")
        name = stock_code

    def _analyze_sentiment(title, negation_words):
        """分析标题情绪"""
        if not title:
            return "neutral"
        
        positive_kw = ["利好", "上涨", "增长", "突破", "新高", "增持", "买入", "超预期", "反弹", "回暖"]
        negative_kw = ["利空", "下跌", "下滑", "减持", "卖出", "暴雷", "亏损", "风险", "调查", "回调", "低迷"]
        
        pos_positions = [(title.find(kw), kw) for kw in positive_kw if kw in title]
        neg_positions = [(title.find(kw), kw) for kw in negative_kw if kw in title]
        
        pos_positions = [(p, kw) for p, kw in pos_positions if p >= 0]
        neg_positions = [(p, kw) for p, kw in neg_positions if p >= 0]
        
        if not pos_positions and not neg_positions:
            return "neutral"
        
        def _has_negation_before(pos):
            prefix = title[:pos]
            for neg in negation_words:
                if neg in prefix:
                    return True
            return False
        
        score = 0
        for pos, kw in pos_positions:
            if _has_negation_before(pos):
                score -= 1
            else:
                score += 1
        
        for pos, kw in neg_positions:
            if _has_negation_before(pos):
                score += 1
            else:
                score -= 1
        
        if score > 0:
            return "positive"
        elif score < 0:
            return "negative"
        return "neutral"

    def _fetch_news():
        items = []
        seen_titles = set()
        
        # 优先级1：搜索股票名称（资讯新闻）- 直接同步调用
        try:
            news_batch = search_news(name, top_n=top_n * 2)
            logger.info(f"搜索'{name}'(资讯): {len(news_batch)}条")
            for it in news_batch:
                t = it.get("title", "")
                if t and t not in seen_titles:
                    seen_titles.add(t)
                    it["search_from"] = "个股"
                    items.append(it)
        except Exception as e:
            logger.debug(f"搜索'{name}'失败: {e}")
        
        # 如果已经有足够数据，直接返回（不查板块和公告）
        if len(items) >= top_n:
            pass
        else:
            # 优先级2：获取概念板块资讯 - 同步调用，超时由外层控制
            try:
                from app.core.data_sources import EastMoneySource
                concept_blocks = EastMoneySource.get_concept_blocks(stock_code) or []
                
                for block in (concept_blocks or [])[:1]:  # 只取第1个概念板块
                    block_name = block.get("name", "")
                    if block_name and block_name not in seen_titles:
                        try:
                            block_news = search_news(block_name, top_n=top_n - len(items))
                            logger.info(f"搜索'{block_name}'(概念): {len(block_news)}条")
                            for it in block_news:
                                t = it.get("title", "")
                                if t and t not in seen_titles:
                                    seen_titles.add(t)
                                    it["search_from"] = "板块"
                                    items.append(it)
                        except Exception as e:
                            logger.debug(f"搜索'{block_name}'失败: {e}")
            except Exception as e:
                logger.debug(f"获取概念板块失败 ({stock_code}): {e}")
        
        # 如果仍然数据不足，尝试巨潮公告 - 同步调用，超时由外层控制
        if len(items) < top_n:
            try:
                from app.core.data_sources_clean import CNInfoSource
                announcements = CNInfoSource.get_announcements(stock_code, page_size=top_n - len(items)) or []
                
                for it in (announcements or []):
                    t = it.get("title", "")
                    if t and t not in seen_titles:
                        seen_titles.add(t)
                        it["search_from"] = "公告"
                        items.append(it)
                
                logger.info(f"巨潮公告: {len(announcements)}条")
            except Exception as e:
                logger.debug(f"获取巨潮公告失败 ({stock_code}): {e}")

        # 去重截取
        deduped = []
        final_seen = set()
        for it in items:
            key = it.get("title", "")
            if key not in final_seen and it.get("title"):
                final_seen.add(key)
                deduped.append(it)
                if len(deduped) >= top_n:
                    break

        # 情绪判断
        negation_words = ["不", "未", "无", "非", "没", "难", "难以", "不再", "不惧", "不怕", "逆势"]
        for item in deduped:
            title = item.get("title", "")
            sentiment = _analyze_sentiment(title, negation_words)
            item["sentiment"] = sentiment

        logger.info(f"{stock_code}({name}) 新闻: {len(deduped)}条")
        return {"stock_code": stock_code, "name": name, "news": deduped, "count": len(deduped)}

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_fetch_news),
            timeout=8.0  # 整体超时8秒
        )
        _NEWS_CACHE[cache_key] = (_t.time(), result)
        return result
    except asyncio.TimeoutError:
        logger.warning(f"获取{stock_code}新闻超时(8s)，返回空数据")
        result = {"stock_code": stock_code, "name": name, "news": [], "count": 0, "error": True, "timeout": True}
        _NEWS_CACHE[cache_key] = (_t.time(), result)
        return result
    except Exception as e:
        logger.warning(f"获取{stock_code}新闻失败: {e}")
        result = {"stock_code": stock_code, "name": name, "news": [], "count": 0, "error": True}
        _NEWS_CACHE[cache_key] = (_t.time(), result)
        return result


@router.get("/stock/kline/{stock_code}")
async def get_kline_data(
    stock_code: str,
    period: str = Query("daily", description="周期：daily/weekly/monthly"),
    count: int = Query(200, description="K线数量")
):
    """获取K线数据（用于前端图表），pytdx优先+新浪兜底"""
    from app.core.pytdx_source import pytdx_data

    period_map = {"daily": 4, "weekly": 5, "monthly": 6}
    period_code = period_map.get(period, 4)

    klines = []
    try:
        klines = await asyncio.to_thread(pytdx_data.get_kline, stock_code, period=period_code, count=count) or []
    except Exception as e:
        logger.error(f"pytdx K线获取失败 ({stock_code}): {e}")

    # pytdx返回空时，用新浪API兜底（仅日线支持）
    if not klines and period == "daily":
        try:
            sina_klines = await asyncio.to_thread(_fetch_sina_kline, stock_code, count)
            if sina_klines:
                logger.info(f"K线pytdx为空，新浪兜底成功 ({stock_code}): {len(sina_klines)}条")
                klines = sina_klines
        except Exception as e:
            logger.error(f"新浪K线兜底失败 ({stock_code}): {e}")

    result = []
    for k in klines:
        dt = k['date']
        if hasattr(dt, 'strftime'):
            date_str = dt.strftime('%Y-%m-%d')
        else:
            date_str = str(dt)[:10]
        result.append({
            'time': date_str,
            'open': round(k['open'], 2),
            'high': round(k['high'], 2),
            'low': round(k['low'], 2),
            'close': round(k['close'], 2),
            'volume': k.get('volume', 0),
        })

    return {'stock_code': stock_code, 'period': period, 'klines': result}


# 资金面深度分析接口已移除（东财datacenter接口不稳定，数据不可用）
# @router.get("/stock/margin/{stock_code}")
# async def get_margin_trading(stock_code: str, page_size: int = Query(30, description="返回条数")):
#     """获取融资融券明细"""
#     from app.core.data_sources import EastMoneyDataCenter
#     data = await asyncio.to_thread(EastMoneyDataCenter.margin_trading, stock_code, page_size)
#     return {'stock_code': stock_code, 'margin_data': data}


# @router.get("/stock/block-trade/{stock_code}")
# async def get_block_trade(stock_code: str, page_size: int = Query(20, description="返回条数")):
#     """获取大宗交易"""
#     from app.core.data_sources import EastMoneyDataCenter
#     data = await asyncio.to_thread(EastMoneyDataCenter.block_trade, stock_code, page_size)
#     return {'stock_code': stock_code, 'block_trades': data}


# @router.get("/stock/holders/{stock_code}")
# async def get_holder_change(stock_code: str, page_size: int = Query(10, description="返回条数")):
#     """获取股东户数变化"""
#     from app.core.data_sources import EastMoneyDataCenter
#     data = await asyncio.to_thread(EastMoneyDataCenter.holder_num_change, stock_code, page_size)
#     return {'stock_code': stock_code, 'holder_changes': data}


# @router.get("/stock/dividend/{stock_code}")
# async def get_dividend_history(stock_code: str, page_size: int = Query(20, description="返回条数")):
#     """获取分红送转历史"""
#     from app.core.data_sources import EastMoneyDataCenter
#     data = await asyncio.to_thread(EastMoneyDataCenter.dividend_history, stock_code, page_size)
#     return {'stock_code': stock_code, 'dividends': data}


# @router.get("/stock/flow-history/{stock_code}")
# async def get_flow_history_120d(stock_code: str):
#     """获取个股120日资金流历史"""
#     from app.core.data_sources import EastMoneyFlowHistory
#     data = await asyncio.to_thread(EastMoneyFlowHistory.get_120d_flow, stock_code)
#     return {'stock_code': stock_code, 'flow_history': data}


@router.get("/industry/reports")
async def get_industry_reports(industry: str = Query("", description="行业名称，空则返回全部"), page_size: int = Query(20, description="返回条数")):
    """获取行业研报"""
    from app.core.data_sources import EastMoneyIndustryReport
    data = await asyncio.to_thread(EastMoneyIndustryReport.get_industry_reports, industry, page_size)
    return {'industry': industry or '全部', 'reports': data}


@router.get("/stock/dragon-tiger/seats/{stock_code}")
async def get_dragon_tiger_seats(
    stock_code: str, 
    trade_date: str = Query(None, description="交易日期 YYYY-MM-DD，默认当日"),
    look_back: int = Query(30, description="回看天数")
):
    """获取龙虎榜席位明细（上榜记录+买卖席位TOP5+机构统计）"""
    from app.core.data_sources import EastMoneyDataCenter
    data = await asyncio.to_thread(EastMoneyDataCenter.dragon_tiger_seats, stock_code, trade_date, look_back)
    return {'stock_code': stock_code, 'data': data}


@router.get("/stock/lockup/{stock_code}")
async def get_lockup_expiry(
    stock_code: str,
    trade_date: str = Query(None, description="交易日期 YYYY-MM-DD，默认当日"),
    forward_days: int = Query(90, description="未来查看天数")
):
    """获取限售解禁日历（历史+未来待解禁）"""
    from app.core.data_sources import EastMoneyDataCenter
    data = await asyncio.to_thread(EastMoneyDataCenter.lockup_expiry, stock_code, trade_date, forward_days)
    return {'stock_code': stock_code, 'data': data}


@router.get("/market/northbound/history")
async def get_northbound_history(n: int = Query(20, description="返回天数")):
    """获取北向资金历史（本地CSV自缓存）"""
    from app.core.data_sources import THSNorthboundSource
    data = await asyncio.to_thread(THSNorthboundSource.get_history, n)
    return {'history': data}