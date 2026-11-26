"""决策中心API路由：算法信号聚合+选股扫描"""
import asyncio
import json
import logging
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from app.core.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)])

# 扫描历史缓存（内存缓存，生产环境建议用Redis）
_scan_history: list[dict] = []
MAX_HISTORY = 50


def _format_klines(klines: list) -> list[dict]:
    """格式化K线数据为算法所需格式"""
    formatted = []
    for k in klines:
        dt = k["date"]
        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        formatted.append({
            "date": date_str,
            "open": round(k["open"], 2),
            "high": round(k["high"], 2),
            "low": round(k["low"], 2),
            "close": round(k["close"], 2),
            "volume": k.get("volume", 0),
        })
    return formatted


def _calc_composite_score(signals: dict) -> tuple[int, str, int, int]:
    """计算综合评分和信号（纳入全部7个算法）
    
    Returns:
        (composite_score, overall_signal, buy_count, sell_count)
    """
    all_algos = [
        "td_sequential", "ma_radar", "channel_breakout",
        "magic_wave", "anomaly_detect", "bottom_opportunity", "trend_strength"
    ]
    buy_algos = ["td_sequential", "channel_breakout", "magic_wave", "anomaly_detect", "bottom_opportunity"]
    
    buy_signals = sum(1 for a in all_algos if signals.get(a, {}).get("signal") == "buy")
    sell_signals = sum(1 for a in all_algos if signals.get(a, {}).get("signal") == "sell")
    total_algos = len(all_algos)
    
    # 综合评分：买入信号贡献正分，卖出信号贡献负分，中性为50分基准
    buy_ratio = buy_signals / total_algos
    sell_ratio = sell_signals / total_algos
    composite_score = round(50 + (buy_ratio - sell_ratio) * 50, 0)
    composite_score = max(0, min(100, composite_score))
    
    overall_signal = (
        "strong_buy" if buy_signals >= 5
        else "buy" if buy_signals >= 3
        else "strong_sell" if sell_signals >= 5
        else "sell" if sell_signals >= 3
        else "neutral"
    )
    
    return composite_score, overall_signal, buy_signals, sell_signals


@router.get("/decision/signals/{stock_code}")
async def get_decision_signals(
    stock_code: str,
    period: int = Query(250, ge=60, le=500, description="K线周期"),
):
    """获取个股决策信号（7个算法全覆盖）"""
    from app.core.pytdx_source import pytdx_data

    if not stock_code or len(stock_code) != 6:
        raise HTTPException(status_code=400, detail=f"股票代码无效: {stock_code}")

    try:
        logger.info(f"开始获取K线数据: {stock_code}, period={period}")
        klines = await asyncio.to_thread(
            pytdx_data.get_kline, stock_code, period=4, count=period
        )
        logger.info(f"获取K线结果: {stock_code}, 条数={len(klines) if klines else 0}")
        if not klines:
            error_msg = f"无法获取K线数据: {stock_code} (pytdx返回空数据，请检查网络连接和股票代码)"
            logger.error(error_msg)
            return {"status": "error", "message": error_msg}

        formatted = _format_klines(klines)

        # 调用全部7个算法
        from app.services.decision_algo_service import (
            TDSequentialAlgo,
            MARadarAlgo,
            ChannelBreakoutAlgo,
            MagicWaveAlgo,
            AnomalyDetectAlgo,
            BottomOpportunityAlgo,
            TrendStrengthAlgo,
        )

        signals = {
            "td_sequential": TDSequentialAlgo.analyze(formatted),
            "ma_radar": MARadarAlgo.analyze(formatted),
            "channel_breakout": ChannelBreakoutAlgo.analyze(formatted, 20),
            "magic_wave": MagicWaveAlgo.analyze(formatted),
            "anomaly_detect": AnomalyDetectAlgo.analyze(formatted),
            "bottom_opportunity": BottomOpportunityAlgo.analyze(formatted),
            "trend_strength": TrendStrengthAlgo.analyze(formatted),
        }

        # 综合评分（纳入全部7个算法）
        composite_score, overall_signal, buy_count, sell_count = _calc_composite_score(signals)

        return {
            "stock_code": stock_code,
            "composite_score": composite_score,
            "overall_signal": overall_signal,
            "buy_signal_count": buy_count,
            "sell_signal_count": sell_count,
            "signals": signals,
        }

    except Exception as e:
        logger.error(f"决策信号计算失败 ({stock_code}): {e}")
        return {"status": "error", "message": str(e)}


@router.get("/decision/scan")
async def scan_stocks_by_algo(
    algo: str = Query(
        "magic_wave",
        description="算法类型: td_sequential/ma_radar/channel_breakout/magic_wave/anomaly_detect/bottom_opportunity/trend_strength",
    ),
    signal: str = Query("buy", description="信号方向: buy/sell"),
    top_n: int = Query(20, ge=5, le=100, description="返回数量"),
    min_score: int = Query(0, ge=0, le=100, description="最低综合分筛选"),
):
    """按算法条件扫描股票（并发优化版）"""
    from app.core.pytdx_source import pytdx_data, FullMarketCache
    from app.services.decision_algo_service import (
        TDSequentialAlgo,
        MARadarAlgo,
        ChannelBreakoutAlgo,
        MagicWaveAlgo,
        AnomalyDetectAlgo,
        BottomOpportunityAlgo,
        TrendStrengthAlgo,
    )

    algo_map = {
        "td_sequential": TDSequentialAlgo.analyze,
        "ma_radar": MARadarAlgo.analyze,
        "channel_breakout": ChannelBreakoutAlgo.analyze,
        "magic_wave": MagicWaveAlgo.analyze,
        "anomaly_detect": AnomalyDetectAlgo.analyze,
        "bottom_opportunity": BottomOpportunityAlgo.analyze,
        "trend_strength": TrendStrengthAlgo.analyze,
    }

    analyze_func = algo_map.get(algo)
    if not analyze_func:
        raise HTTPException(status_code=400, detail=f"未知算法: {algo}")

    # 获取候选股票池（扩展策略）
    all_stocks = FullMarketCache.get_all_stocks()
    
    if not all_stocks:
        logger.warning("FullMarketCache为空，使用扩展备用候选池")
        candidate_codes = [
            "600519", "601318", "600036", "600900", "601288",
            "600030", "601166", "600048", "601398", "600028",
            "000001", "000002", "000858", "002714", "002415",
            "002594", "300750", "603259", "002475", "000651",
            "601888", "300059", "002352", "600809", "601012",
            "600276", "000333", "000568", "002371", "002493",
            "300015", "300124", "300274", "300498", "300601",
            "600196", "600309", "600570", "600690", "600837",
            "601211", "601601", "601628", "601668", "601688",
            "000425", "000725", "002027", "002353", "002120",
            "002241", "002304", "002352", "002410", "002460",
            "300033", "300122", "300136", "300142", "300223",
            "600000", "600009", "600010", "600011", "600015",
            "600016", "600018", "600019", "600020", "600021",
        ]
    else:
        max_scan = min(len(all_stocks), top_n * 20, 1200)
        candidate_codes = [s["code"] for s in all_stocks[:max_scan]]

    # 去重
    seen = set()
    unique_codes = []
    for code in candidate_codes:
        if code not in seen and len(code) == 6:
            seen.add(code)
            unique_codes.append(code)
    candidate_codes = unique_codes

    async def process_one_stock(code: str) -> Optional[dict]:
        """处理单只股票（并发任务）"""
        try:
            klines = await asyncio.to_thread(
                pytdx_data.get_kline, code, period=4, count=250
            )
            if not klines or len(klines) < 30:
                return None

            formatted = _format_klines(klines)
            result = analyze_func(formatted)

            # 提取行情数据
            last_bar = formatted[-1]
            prev_bar = formatted[-2] if len(formatted) > 1 else last_bar
            close = last_bar["close"]
            prev_close = prev_bar["close"]
            change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0

            close_5d = formatted[-5]["close"] if len(formatted) >= 5 else close
            change_5d_pct = round((close - close_5d) / close_5d * 100, 2) if close_5d else 0

            close_20d = formatted[-20]["close"] if len(formatted) >= 20 else close
            change_20d_pct = round((close - close_20d) / close_20d * 100, 2) if close_20d else 0

            vol = last_bar.get("volume", 0)
            vol_5d = sum(k.get("volume", 0) for k in formatted[-5:]) / min(5, len(formatted)) if formatted else 0
            volume_ratio = round(vol / vol_5d, 2) if vol_5d > 0 else 0

            # 计算分数
            score = 0
            if algo == "bottom_opportunity":
                score = result.get("bottom_score", 0)
            elif algo == "trend_strength":
                score = result.get("strength", 0)
            elif algo == "magic_wave":
                strength_map = {"strong": 85, "medium": 60, "weak": 35, "none": 10}
                score = strength_map.get(result.get("strength", "none"), 20)
            elif algo == "anomaly_detect":
                strength_map = {"strong": 80, "medium": 55, "weak": 30, "none": 10}
                score = strength_map.get(result.get("strength", "none"), 10)
            elif algo == "td_sequential":
                buy_progress = result.get("buy_setup_progress", 0) or 0
                sell_progress = result.get("sell_setup_progress", 0) or 0
                score = min(buy_progress * 10, 90) if signal == "buy" else min(sell_progress * 10, 90)
            elif algo == "channel_breakout":
                position = result.get("position_in_channel", 50) or 50
                score = max(0, (position - 50) * 2) if signal == "buy" else max(0, (50 - position) * 2)
            elif algo == "ma_radar":
                bullish_count = result.get("bullish_count", 0) or 0
                bearish_count = result.get("bearish_count", 0) or 0
                score = min(bullish_count * 12, 84) if signal == "buy" else min(bearish_count * 12, 84)

            # 信号过滤
            sig = result.get("signal", "neutral")
            has_signal = sig in ("buy", "sell")
            if signal == "buy" and has_signal and sig != "buy":
                return None
            if signal == "sell" and has_signal and sig != "sell":
                return None
            if not has_signal and score < 15:
                return None
            if score < min_score:
                return None

            # 获取股票名称
            stock_name = code
            try:
                from app.services.stock_service import StockService
                ss = StockService()
                stock_name = await asyncio.wait_for(
                    asyncio.to_thread(ss._get_stock_name, code), timeout=2.0
                )
            except Exception:
                pass

            high_20d = max(k["high"] for k in formatted[-20:]) if len(formatted) >= 20 else max(k["high"] for k in formatted)
            low_20d = min(k["low"] for k in formatted[-20:]) if len(formatted) >= 20 else min(k["low"] for k in formatted)

            return {
                "code": code,
                "name": stock_name,
                "signal": result.get("signal", "neutral"),
                "score": score,
                "algo_result": result,
                "close": close,
                "change_pct": change_pct,
                "change_5d_pct": change_5d_pct,
                "change_20d_pct": change_20d_pct,
                "volume_ratio": volume_ratio,
                "high_20d": high_20d,
                "low_20d": low_20d,
            }
        except Exception as e:
            logger.debug(f"扫描股票失败 ({code}): {e}")
            return None

    # 并发处理（限制并发数避免过载）
    sem = asyncio.Semaphore(20)
    async def bounded_process(code):
        async with sem:
            return code, await process_one_stock(code)

    tasks = [bounded_process(code) for code in candidate_codes]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for item in results_raw:
        if isinstance(item, Exception):
            continue
        code, result = item
        if result:
            results.append(result)

    # 按分数排序
    results.sort(key=lambda x: x["score"], reverse=True)
    
    # 保存扫描历史
    history_record = {
        "id": len(_scan_history) + 1,
        "algo": algo,
        "signal_filter": signal,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_found": len(results),
        "top_stocks": [{"code": s["code"], "name": s["name"], "score": s["score"]} for s in results[:5]],
    }
    _scan_history.insert(0, history_record)
    if len(_scan_history) > MAX_HISTORY:
        _scan_history.pop()

    logger.info(
        f"选股扫描完成: algo={algo}, signal={signal}, "
        f"候选{len(candidate_codes)}只, 最终{len(results)}只"
    )
    return {
        "algo": algo,
        "signal_filter": signal,
        "total_found": len(results),
        "stocks": results[:top_n],
    }


@router.get("/decision/scan-history")
async def get_scan_history():
    """获取扫描历史记录"""
    return {"history": _scan_history}


@router.get("/decision/watchlist-signals")
async def get_watchlist_signals(
    stock_codes: str = Query(..., description="股票代码列表，逗号分隔"),
    full: bool = Query(False, description="是否返回全部7个算法结果"),
):
    """批量获取自选股决策信号"""
    from app.core.pytdx_source import pytdx_data
    from app.services.decision_algo_service import (
        TDSequentialAlgo,
        MARadarAlgo,
        ChannelBreakoutAlgo,
        MagicWaveAlgo,
        AnomalyDetectAlgo,
        BottomOpportunityAlgo,
        TrendStrengthAlgo,
    )

    codes = [c.strip() for c in stock_codes.split(",") if c.strip()]
    results = []
    kline_fail_codes = []

    async def process_one(code: str) -> tuple[Optional[dict], Optional[str]]:
        if len(code) != 6:
            return None, code
        try:
            klines = await asyncio.to_thread(
                pytdx_data.get_kline, code, period=4, count=250
            )
            if not klines or len(klines) < 20:
                logger.debug(f"K线数据不足 ({code}): 获取到{len(klines) if klines else 0}条，需要至少20条")
                return None, code

            formatted = _format_klines(klines)

            # 提取行情数据
            last_bar = formatted[-1]
            prev_bar = formatted[-2] if len(formatted) > 1 else last_bar
            close = last_bar["close"]
            prev_close = prev_bar["close"]
            change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0

            close_5d = formatted[-5]["close"] if len(formatted) >= 5 else close
            change_5d_pct = round((close - close_5d) / close_5d * 100, 2) if close_5d else 0

            vol = last_bar.get("volume", 0)
            vol_5d = sum(k.get("volume", 0) for k in formatted[-5:]) / min(5, len(formatted)) if formatted else 0
            volume_ratio = round(vol / vol_5d, 2) if vol_5d > 0 else 0

            # 获取股票名称
            stock_name = code
            try:
                from app.services.stock_service import StockService
                ss = StockService()
                stock_name = await asyncio.wait_for(
                    asyncio.to_thread(ss._get_stock_name, code), timeout=2.0
                )
            except Exception:
                pass

            # 快速算法
            ma = MARadarAlgo.analyze(formatted)
            wave = MagicWaveAlgo.analyze(formatted)
            strength = TrendStrengthAlgo.analyze(formatted)

            stock_result = {
                "code": code,
                "name": stock_name,
                "close": close,
                "change_pct": change_pct,
                "change_5d_pct": change_5d_pct,
                "volume_ratio": volume_ratio,
                "ma_trend": ma.get("trend", "unknown"),
                "wave": wave.get("wave", "neutral"),
                "wave_strength": wave.get("strength", "none"),
                "trend_score": strength.get("strength", 0),
            }

            # 全量算法
            if full:
                td = TDSequentialAlgo.analyze(formatted)
                channel = ChannelBreakoutAlgo.analyze(formatted, 20)
                anomaly = AnomalyDetectAlgo.analyze(formatted)
                bottom = BottomOpportunityAlgo.analyze(formatted)

                all_signals = {
                    "td_sequential": td,
                    "ma_radar": ma,
                    "channel_breakout": channel,
                    "magic_wave": wave,
                    "anomaly_detect": anomaly,
                    "bottom_opportunity": bottom,
                    "trend_strength": strength,
                }
                composite_score, overall_signal, buy_count, sell_count = _calc_composite_score(all_signals)

                stock_result.update({
                    "signals": all_signals,
                    "composite_score": composite_score,
                    "overall_signal": overall_signal,
                    "buy_signal_count": buy_count,
                    "sell_signal_count": sell_count,
                })

            return stock_result, None
        except Exception as e:
            logger.warning(f"获取自选股信号失败 ({code}): {e}")
            return None, code

    # 并发处理
    tasks = [process_one(code) for code in codes]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    for item in results_raw:
        if isinstance(item, Exception):
            continue
        result, fail_code = item
        if fail_code:
            kline_fail_codes.append(fail_code)
        elif result:
            results.append(result)

    logger.info(
        f"自选股信号: 请求{len(codes)}只, 成功{len(results)}只, "
        f"失败{kline_fail_codes}只(full={full})"
    )
    return {
        "total": len(results),
        "stocks": results,
        "fail_count": len(kline_fail_codes),
        "fail_codes": kline_fail_codes if kline_fail_codes else None,
    }


class MonitorRequest(BaseModel):
    stock_list: List[dict] = Field(..., description="股票列表")
    holding_context_map: Optional[dict] = Field(None, description="持仓上下文")


@router.post("/decision/monitor")
async def monitor_decision_alerts(request: MonitorRequest):
    """决策算法预警监控"""
    from app.services.decision_alert_service import decision_alert_service

    if not request.stock_list:
        raise HTTPException(status_code=400, detail="请提供股票列表")

    try:
        result = await asyncio.to_thread(
            decision_alert_service.monitor_stocks,
            request.stock_list,
            request.holding_context_map,
        )
        return {
            "status": "success",
            "message": f"监控完成，共{result['summary']['total']}只股票",
            "data": result,
        }
    except Exception as e:
        logger.error(f"决策算法监控失败: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/decision/monitor-watchlist")
async def monitor_watchlist_decision(
    request: dict,
    current_user=None,
    db=None,
):
    """监控自选股决策算法信号"""
    from app.services.decision_alert_service import decision_alert_service
    from app.core.database import get_db
    from app.core.auth import get_current_user
    from app.models.watchlist import WatchlistItem

    if db is None:
        from app.core.database import SessionLocal
        db = SessionLocal()
    
    try:
        items = db.query(WatchlistItem).filter(
            WatchlistItem.user_id == current_user.id if current_user else True
        ).all()

        if not items:
            return {"status": "error", "message": "自选股为空"}

        stock_list = [{"code": item.stock_code, "name": item.stock_name} for item in items]
        result = await asyncio.to_thread(decision_alert_service.monitor_stocks, stock_list)

        return {
            "status": "success",
            "message": "自选股决策监控完成",
            "data": result,
        }
    except Exception as e:
        logger.error(f"自选股决策监控失败: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


@router.post("/decision/monitor-holdings")
async def monitor_holdings_decision(
    request: dict,
    current_user=None,
    db=None,
):
    """监控持仓决策算法信号（含持仓感知）"""
    from app.services.decision_alert_service import decision_alert_service
    from app.models.holding import Holding

    if db is None:
        from app.core.database import SessionLocal
        db = SessionLocal()

    try:
        items = db.query(Holding).filter(
            Holding.user_id == current_user.id if current_user else True
        ).all()

        if not items:
            return {"status": "error", "message": "持仓为空"}

        stock_list = [{"code": item.stock_code, "name": item.stock_name} for item in items]

        holding_context_map = {}
        for item in items:
            if item.cost_price > 0:
                holding_context_map[item.stock_code] = {
                    "cost_price": item.cost_price,
                    "quantity": item.quantity,
                    "position_type": item.position_type or "short",
                    "profit_ratio": item.profit_ratio or 0,
                }

        result = await asyncio.to_thread(
            decision_alert_service.monitor_stocks, stock_list, holding_context_map
        )

        return {
            "status": "success",
            "message": "持仓决策监控完成",
            "data": result,
        }
    except Exception as e:
        logger.error(f"持仓决策监控失败: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()
