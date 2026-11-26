"""持仓管理API路由 - 所有用户可用，管理员可查看全部"""
import asyncio
from fastapi import APIRouter, Query, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user, get_current_admin
from app.models.user import User
from app.models.holding import Holding


router = APIRouter()


class AddHoldingRequest(BaseModel):
    stock_code: str
    stock_name: str = ""
    quantity: int = 0
    cost_price: float = 0.0
    buy_date: Optional[str] = None
    buy_reason: Optional[str] = None
    notes: Optional[str] = None
    position_type: str = "short"  # short/mid/long


class UpdateHoldingRequest(BaseModel):
    quantity: Optional[int] = None
    cost_price: Optional[float] = None
    buy_date: Optional[str] = None
    buy_reason: Optional[str] = None
    notes: Optional[str] = None
    position_type: Optional[str] = None


def _fetch_quotes_sync(code_list):
    """同步获取行情（在线程池中运行）"""
    from app.core.pytdx_source import pytdx_data
    return pytdx_data.get_realtime_quote(code_list) or []


@router.get("/my")
def get_my_holdings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的持仓列表"""
    holdings = db.query(Holding).filter(
        Holding.user_id == current_user.id
    ).order_by(Holding.created_at.desc()).all()

    return {
        "holdings": [_format_holding(h) for h in holdings]
    }


@router.get("/all")
def get_all_holdings(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """获取所有用户持仓（仅管理员可用）"""
    query = db.query(Holding)

    if user_id:
        query = query.filter(Holding.user_id == user_id)

    total = query.count()
    holdings = query.order_by(Holding.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "holdings": [_format_holding(h) for h in holdings],
    }


@router.post("/add")
def add_holding(
    request: AddHoldingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """添加持仓"""
    # 检查是否已存在
    existing = db.query(Holding).filter(
        Holding.user_id == current_user.id,
        Holding.stock_code == request.stock_code,
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="该股票已在持仓中")

    # 获取股票名称（如果未提供）
    stock_name = request.stock_name
    if not stock_name:
        try:
            quotes = _fetch_quotes_sync([request.stock_code])
            if quotes:
                stock_name = quotes[0].get("name", "")
        except Exception:
            pass

    holding = Holding(
        user_id=current_user.id,
        stock_code=request.stock_code,
        stock_name=stock_name,
        quantity=request.quantity,
        cost_price=request.cost_price,
        buy_date=request.buy_date,
        buy_reason=request.buy_reason,
        notes=request.notes,
        position_type=request.position_type,
    )

    try:
        db.add(holding)
        db.commit()
        db.refresh(holding)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="添加失败，该股票已在持仓中")

    return {"success": True, "holding": _format_holding(holding)}


@router.put("/{holding_id}")
def update_holding(
    holding_id: int,
    request: UpdateHoldingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新持仓"""
    holding = db.query(Holding).filter(
        Holding.id == holding_id,
        Holding.user_id == current_user.id,
    ).first()

    if not holding:
        raise HTTPException(status_code=404, detail="持仓不存在")

    # 更新字段
    if request.quantity is not None:
        holding.quantity = request.quantity
    if request.cost_price is not None:
        holding.cost_price = request.cost_price
    if request.buy_date is not None:
        holding.buy_date = request.buy_date
    if request.buy_reason is not None:
        holding.buy_reason = request.buy_reason
    if request.notes is not None:
        holding.notes = request.notes
    if request.position_type is not None:
        holding.position_type = request.position_type

    db.commit()
    db.refresh(holding)

    return {"success": True, "holding": _format_holding(holding)}


@router.delete("/{holding_id}")
def delete_holding(
    holding_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除持仓"""
    holding = db.query(Holding).filter(
        Holding.id == holding_id,
        Holding.user_id == current_user.id,
    ).first()

    if not holding:
        raise HTTPException(status_code=404, detail="持仓不存在")

    db.delete(holding)
    db.commit()

    return {"success": True}


@router.post("/sync-prices")
def sync_holding_prices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """同步持仓现价"""
    holdings = db.query(Holding).filter(
        Holding.user_id == current_user.id
    ).all()

    if not holdings:
        return {"success": True, "updated": 0}

    # 获取所有持仓股票的代码
    stock_codes = [h.stock_code for h in holdings]

    # 批量获取行情
    try:
        quotes = _fetch_quotes_sync(stock_codes)
        quote_map = {q.get("code"): q for q in quotes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取行情失败: {str(e)}")

    updated_count = 0
    for holding in holdings:
        quote = quote_map.get(holding.stock_code)
        if quote:
            current_price = quote.get("price", 0)
            if current_price > 0:
                holding.current_price = current_price
                holding.market_value = current_price * holding.quantity
                if holding.cost_price > 0:
                    holding.profit = (current_price - holding.cost_price) * holding.quantity
                    holding.profit_ratio = (current_price - holding.cost_price) / holding.cost_price * 100
                updated_count += 1

    db.commit()

    return {"success": True, "updated": updated_count}


@router.get("/summary")
def get_holdings_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取持仓汇总信息"""
    holdings = db.query(Holding).filter(
        Holding.user_id == current_user.id
    ).all()

    total_market_value = sum(h.market_value for h in holdings)
    total_profit = sum(h.profit for h in holdings)
    total_cost = sum(h.cost_price * h.quantity for h in holdings)
    profit_ratio = (total_profit / total_cost * 100) if total_cost > 0 else 0

    return {
        "count": len(holdings),
        "total_market_value": round(total_market_value, 2),
        "total_profit": round(total_profit, 2),
        "profit_ratio": round(profit_ratio, 2),
    }


def _format_holding(holding: Holding) -> dict:
    """格式化持仓数据"""
    return {
        "id": holding.id,
        "user_id": holding.user_id,
        "stock_code": holding.stock_code,
        "stock_name": holding.stock_name,
        "quantity": holding.quantity,
        "cost_price": holding.cost_price,
        "current_price": holding.current_price,
        "market_value": holding.market_value,
        "profit": holding.profit,
        "profit_ratio": holding.profit_ratio,
        "buy_date": holding.buy_date,
        "buy_reason": holding.buy_reason,
        "notes": holding.notes,
        "position_type": holding.position_type,
        "created_at": holding.created_at.strftime("%Y-%m-%d %H:%M:%S") if holding.created_at else None,
        "updated_at": holding.updated_at.strftime("%Y-%m-%d %H:%M:%S") if holding.updated_at else None,
    }
