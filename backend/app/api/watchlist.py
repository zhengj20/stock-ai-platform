"""自选股API路由 - 关联用户ID，支持持久化存储"""
import asyncio
from fastapi import APIRouter, Query, Request, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user, get_current_admin
from app.models.user import User
from app.models.watchlist import WatchlistItem


router = APIRouter(dependencies=[Depends(get_current_user)])


def _fetch_quotes_sync(code_list):
    """同步获取行情（在线程池中运行）"""
    from app.core.pytdx_source import pytdx_data
    return pytdx_data.get_realtime_quote(code_list) or []


class WatchlistStock(BaseModel):
    code: str
    name: str = ""
    group: str = "默认"


class BatchDiagnosisRequest(BaseModel):
    stocks: list[WatchlistStock]


class AddWatchlistRequest(BaseModel):
    stock_code: str
    stock_name: str = ""
    group: str = "默认"


class RemoveWatchlistRequest(BaseModel):
    stock_code: str


def _get_advice_from_score(score):
    """根据评分生成买卖建议"""
    if score >= 75:
        return "强烈买入"
    elif score >= 60:
        return "买入"
    elif score >= 40:
        return "持有观望"
    elif score >= 25:
        return "卖出减仓"
    else:
        return "强烈卖出"


def _calc_batch_diagnosis(code_list):
    """批量计算诊断评分，复用StockService._calc_indicators保证算法一致"""
    import pandas as pd
    from app.core.pytdx_source import pytdx_data
    from app.services.stock_service import StockService

    service = StockService()
    diagnosis_map = {}

    # 并行获取所有K线（一次拿完，避免串行等待）
    kline_data = pytdx_data.get_batch_klines(code_list, period=4, count=120, max_workers=5)

    for code in code_list:
        try:
            klines = kline_data.get(code, []) or []
            if not klines:
                raise ValueError("no kline data")

            df = pd.DataFrame(klines)
            for col in ['close', 'open', 'high', 'low', 'volume']:
                df[col] = pd.to_numeric(df[col])

            # 复用个股诊断的指标计算（算法完全一致）
            indicators = service._calc_indicators(df)
            score = indicators.get('WEIGHTED_SCORE', 50)
            advice = _get_advice_from_score(score)
        except Exception:
            score, advice = 50, "持有观望"

        diagnosis_map[code] = {"diagnosis_score": int(round(score)), "advice": advice}

    return diagnosis_map


@router.get("/watchlist/quotes")
async def get_watchlist_quotes(
    codes: str = Query(..., description="股票代码列表，逗号分隔，如 600519,000001"),
):
    """批量获取自选股实时行情（仅行情数据）"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        return {"stocks": []}

    from app.core.pytdx_source import pytdx_data as _pytdx
    # 直接调用，不用 asyncio.to_thread（避免线程池连接问题）
    quotes = _pytdx.get_realtime_quote(code_list) or []
    quote_map = {q["code"]: q for q in quotes}

    # pytdx 失败时降级到腾讯备选源
    missing_codes = [c for c in code_list if c not in quote_map or not quote_map[c].get('price')]
    if missing_codes:
        try:
            from app.core.data_sources import TencentSource
            tq = TencentSource.get_quotes(missing_codes) or {}
            for code, q in tq.items():
                if code not in quote_map or not quote_map[code].get('price'):
                    quote_map[code] = {
                        "code": code,
                        "name": q.get("name", ""),
                        "price": q.get("price", 0),
                        "last_close": q.get("last_close", 0),
                        "open": q.get("open", 0),
                        "high": q.get("high", 0),
                        "low": q.get("low", 0),
                        "volume": q.get("vol", q.get("volume", 0)),
                        "amount": q.get("amount_wan", q.get("amount", 0)) * (10000 if "amount_wan" in q else 1),
                        "change_pct": q.get("change_pct", 0),
                        "bid1": q.get("bid1", 0),
                        "ask1": q.get("ask1", 0),
                    }
        except Exception:
            pass

    results = []
    for code in code_list:
        if code not in quote_map:
            continue
        q = quote_map[code]
        results.append({
            "code": code,
            "name": q.get("name", ""),
            "price": q.get("price", 0),
            "last_close": q.get("last_close", 0),
            "change_pct": round(q.get("change_pct", 0), 2),
            "volume": q.get("volume", 0),
            "amount": q.get("amount", 0),
            "high": q.get("high", 0),
            "low": q.get("low", 0),
            "open": q.get("open", 0),
        })

    return {"stocks": results, "count": len(results)}


@router.post("/watchlist/batch-diagnosis")
async def batch_watchlist_diagnosis(req: BatchDiagnosisRequest):
    """自选股批量诊断摘要 - 并行获取行情+K线，复用_calc_batch_diagnosis保证算法一致"""
    import pandas as pd
    from app.core.pytdx_source import pytdx_data
    from app.services.stock_service import StockService

    code_list = [s.code for s in req.stocks]
    stock_map = {s.code: s for s in req.stocks}

    def _sync_batch():
        # 并行拉行情和K线
        quotes = pytdx_data.get_realtime_quote(code_list) or []
        quote_map = {q["code"]: q for q in quotes}

        kline_data = pytdx_data.get_batch_klines(code_list, period=4, count=120, max_workers=5)

        service = StockService()
        results = []
        for stock in req.stocks:
            code = stock.code
            quote = quote_map.get(code, {})

            try:
                klines = kline_data.get(code, []) or []
                if not klines:
                    raise ValueError("no kline data")

                df = pd.DataFrame(klines)
                for col in ['close', 'open', 'high', 'low', 'volume']:
                    df[col] = pd.to_numeric(df[col])

                indicators = service._calc_indicators(df)
                score = indicators.get('WEIGHTED_SCORE', 50)
                advice = _get_advice_from_score(score)

                ma5 = indicators.get('MA5')
                ma10 = indicators.get('MA10')
                ma20 = indicators.get('MA20')
                rsi6 = indicators.get('RSI6', 50.0)
                macd_signal = indicators.get('MACD_SIGNAL', '中性')
            except Exception:
                score, advice = 50, "持有观望"
                ma5 = ma10 = ma20 = None
                rsi6 = 50.0
                macd_signal = "未知"

            results.append({
                "code": code,
                "name": stock.name or quote.get("name", ""),
                "group": stock.group,
                "price": quote.get("price", 0),
                "change_pct": round(quote.get("change_pct", 0), 2),
                "volume": quote.get("volume", 0),
                "amount": quote.get("amount", 0),
                "ma5": ma5, "ma10": ma10, "ma20": ma20,
                "rsi6": rsi6, "macd_signal": macd_signal,
                "diagnosis_score": int(round(score)),
                "advice": advice,
            })
        return {"stocks": results, "count": len(results)}

    return await asyncio.to_thread(_sync_batch)


@router.get("/watchlist/search")
async def search_for_watchlist(query: str = Query(..., description="搜索关键词")):
    """搜索股票（用于添加到自选股）"""
    from app.services.stock_service import StockService
    service = StockService()
    return await service.search_stocks(query)


# ========== 持久化自选股操作 ==========

@router.get("/watchlist/my")
async def get_my_watchlist(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户的自选股列表"""
    user_id = current_user.id

    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user_id)
        .order_by(WatchlistItem.sort_order.asc())
        .all()
    )

    stocks = [
        {
            "id": item.id,
            "stock_code": item.stock_code,
            "stock_name": item.stock_name,
            "group": item.group,
            "sort_order": item.sort_order,
            "created_at": item.created_at,
        } for item in items
    ]

    return {"stocks": stocks, "count": len(stocks)}


@router.get("/watchlist/all")
async def get_all_watchlist(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: Optional[int] = None,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """获取所有用户自选股（仅管理员可用）"""
    query = db.query(WatchlistItem)

    if user_id:
        query = query.filter(WatchlistItem.user_id == user_id)

    total = query.count()
    items = query.order_by(WatchlistItem.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    stocks = [
        {
            "id": item.id,
            "user_id": item.user_id,
            "stock_code": item.stock_code,
            "stock_name": item.stock_name,
            "group": item.group,
            "sort_order": item.sort_order,
            "created_at": item.created_at,
        } for item in items
    ]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "stocks": stocks,
    }


@router.post("/watchlist/add")
async def add_to_watchlist(
    req: AddWatchlistRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """添加股票到自选股"""
    user_id = current_user.id

    # 检查是否已存在
    existing = db.query(WatchlistItem).filter(
        WatchlistItem.user_id == user_id,
        WatchlistItem.stock_code == req.stock_code,
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="该股票已在自选股中")

    # 获取当前最大排序号
    max_order = db.query(WatchlistItem.sort_order).filter(
        WatchlistItem.user_id == user_id
    ).order_by(WatchlistItem.sort_order.desc()).first()
    next_order = (max_order[0] + 1) if max_order else 0

    item = WatchlistItem(
        user_id=user_id,
        stock_code=req.stock_code,
        stock_name=req.stock_name or req.stock_code,
        group=req.group,
        sort_order=next_order,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该股票已在自选股中")
    db.refresh(item)

    return {"status": "ok", "id": item.id, "message": f"已添加 {req.stock_name or req.stock_code}"}


@router.delete("/watchlist/remove/{stock_code}")
async def remove_from_watchlist(
    stock_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从自选股中移除股票"""
    user_id = current_user.id

    item = db.query(WatchlistItem).filter(
        WatchlistItem.user_id == user_id,
        WatchlistItem.stock_code == stock_code,
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="自选股中不存在该股票")

    db.delete(item)
    db.commit()

    return {"status": "ok", "message": f"已移除 {stock_code}"}


@router.put("/watchlist/update-group")
async def update_watchlist_group(
    stock_code: str = Query(..., description="股票代码"),
    group: str = Query(..., description="新分组名称"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新自选股分组"""
    user_id = current_user.id

    item = db.query(WatchlistItem).filter(
        WatchlistItem.user_id == user_id,
        WatchlistItem.stock_code == stock_code,
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="自选股中不存在该股票")

    item.group = group
    db.commit()
    return {"status": "ok", "message": f"已移到「{group}」"}


@router.put("/watchlist/reorder")
async def reorder_watchlist(
    order: List[str] = Query(..., description="股票代码列表，按新顺序排列"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重新排序自选股"""
    user_id = current_user.id

    for idx, code in enumerate(order):
        item = db.query(WatchlistItem).filter(
            WatchlistItem.user_id == user_id,
            WatchlistItem.stock_code == code,
        ).first()
        if item:
            item.sort_order = idx

    db.commit()
    return {"status": "ok", "message": "排序已更新"}