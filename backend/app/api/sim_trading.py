"""模拟交易API路由"""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from app.core.database import get_db
from app.core.auth import get_current_user, get_current_admin
from app.models.user import User
from app.models.sim_trading import AIStrategyDecision
from app.services.trade_engine import TradeEngine
from app.services.ai_strategy_generator import AIStrategyGenerator
from app.services.pnl_calculator import PnLCalculator
from app.services.order_service import OrderService

from app.services.t_trade_service import TTradeService
from app.services.review_service import ReviewService
from app.services.risk_manager import RiskManager

router = APIRouter(prefix="/sim-trading", tags=["模拟交易"])


def _refresh_positions_prices(db: Session, account_id: int) -> None:
    """拉取实时行情并更新持仓现价/盈亏"""
    from app.models.sim_trading import SimPosition, SimAccount

    positions = db.query(SimPosition).filter(
        SimPosition.account_id == account_id
    ).all()

    if not positions:
        return

    codes = [p.stock_code for p in positions]
    quotes = TradeEngine.fetch_realtime_quotes(codes)

    if not quotes:
        return

    TradeEngine.update_position_prices(db, account_id, quotes)


def _fix_available_quantity_tplus1(db: Session, account_id: int, positions_list: list) -> None:
    """动态修正可卖数量：当天买入的不可卖出（T+1规则）

    通过交易记录重新计算每只股票的可卖数量：
    截至昨天的累计买入量 - 累计卖出量 = 可卖数量
    今日买入的不计入可卖。
    """
    from app.models.sim_trading import SimTrade
    from datetime import date as _date

    today_str = _date.today().strftime("%Y-%m-%d")
    
    # 获取所有持仓股票代码
    codes = [pos["stock_code"] for pos in positions_list]
    if not codes:
        return
    
    # 查询这些股票的所有交易记录（不含今日）
    all_trades = db.query(
        SimTrade.stock_code,
        SimTrade.trade_type,
        SimTrade.trade_quantity,
        SimTrade.trade_date
    ).filter(
        SimTrade.account_id == account_id,
        SimTrade.stock_code.in_(codes),
        SimTrade.trade_date < today_str  # 只统计昨日及之前的交易
    ).all()
    
    if not all_trades:
        # 无历史交易，所有持仓都是今日买入的，可卖为0
        for pos in positions_list:
            pos["available_quantity"] = 0
        return
    
    # 按股票汇总截至昨天的净持有量（买入-卖出）
    available_map = {}
    for trade in all_trades:
        code = trade.stock_code
        qty = trade.trade_quantity
        if code not in available_map:
            available_map[code] = 0
        if trade.trade_type == "buy":
            available_map[code] += qty
        elif trade.trade_type == "sell":
            available_map[code] -= qty
    
    # 修正返回数据中的可卖数量（不修改数据库，仅影响展示）
    for pos in positions_list:
        code = pos["stock_code"]
        net_available = max(0, available_map.get(code, 0))
        # 可卖不能超过总持仓
        pos["available_quantity"] = min(net_available, pos["total_quantity"])


class BuyRequest(BaseModel):
    stock_code: str = Field(pattern=r'^\d{6}$')
    stock_name: str = ""
    price: float
    quantity: int
    strategy_name: str = "手动交易"
    strategy_reason: str = ""
    position_type: str = "short"


class SellRequest(BaseModel):
    stock_code: str = Field(pattern=r'^\d{6}$')
    price: float
    quantity: int
    strategy_name: str = "手动交易"
    strategy_reason: str = ""


class StrategyConfig(BaseModel):
    max_single_position_ratio: float = 0.20
    total_position_ratio: float = 0.80
    stop_loss_ratio: float = 8
    take_profit_ratio: float = 15
    min_buy_amount: float = 5000
    # 是否强制 AI 遵守上述参数；False 时 AI 自主决定仓位/止损等
    enforce_params: bool = False


class OrderRequest(BaseModel):
    """委托单请求模型"""
    stock_code: str = Field(pattern=r'^\d{6}$')
    stock_name: str = ""
    order_type: str  # buy/sell
    order_price: float
    order_quantity: int
    expire_type: str = "day"  # day/3day/gtc
    position_type: str = "short"  # short=短线, mid=中线, long=长线
    strategy_name: str = "手动委托"
    strategy_reason: str = ""


class TTradeRequest(BaseModel):
    """做T请求模型"""
    stock_code: str
    buy_price: float
    sell_price: float
    quantity: int


@router.get("/account")
def get_account(
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取模拟账户信息，refresh=true 时拉取实时行情更新持仓现价/盈亏"""
    account = TradeEngine.get_or_create_account(db)
    # T+1: 自动解锁上一交易日买入的持仓
    try:
        TradeEngine.update_t_plus_1(db, account.id)
    except Exception as e:
        logger.debug(f"T+1更新失败: {e}")
    if refresh:
        _refresh_positions_prices(db, account.id)
    summary = TradeEngine.get_account_summary(db, account.id)
    # 动态修正可卖数量：当天买入的不可卖出（T+1规则）
    _fix_available_quantity_tplus1(db, account.id, summary.get("positions", []))
    return summary


@router.get("/positions")
def get_positions(
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取持仓列表，refresh=true 时拉取实时行情更新现价/盈亏"""
    account = TradeEngine.get_or_create_account(db)
    if refresh:
        _refresh_positions_prices(db, account.id)

    from app.models.sim_trading import SimPosition
    positions = db.query(SimPosition).filter(
        SimPosition.account_id == account.id
    ).all()
    
    return {
        "positions": [
            {
                "stock_code": p.stock_code,
                "stock_name": p.stock_name,
                "total_quantity": p.total_quantity,
                "available_quantity": p.available_quantity,
                "cost_price": p.cost_price,
                "current_price": p.current_price,
                "market_value": p.market_value,
                "profit": p.profit,
                "profit_ratio": p.profit_ratio,
                "position_type": p.position_type,
                "buy_date": p.buy_date,
                "buy_reason": p.buy_reason
            } for p in positions
        ]
    }


@router.get("/trades")
def get_trades(
    limit: int = Query(50, ge=1, le=200),
    trade_type: Optional[str] = None,
    trade_source: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取交易记录"""
    account = TradeEngine.get_or_create_account(db)

    from app.models.sim_trading import SimTrade
    query = db.query(SimTrade).filter(SimTrade.account_id == account.id)

    if trade_type:
        query = query.filter(SimTrade.trade_type == trade_type)
    if trade_source:
        query = query.filter(SimTrade.trade_source == trade_source)

    trades = query.order_by(SimTrade.created_at.desc()).limit(limit).all()

    return {
        "trades": [
            {
                "id": t.id,
                "stock_code": t.stock_code,
                "stock_name": t.stock_name,
                "trade_type": t.trade_type,
                "trade_price": t.trade_price,
                "trade_quantity": t.trade_quantity,
                "trade_amount": t.trade_amount,
                "commission": t.commission,
                "stamp_tax": t.stamp_tax,
                "transfer_fee": t.transfer_fee,
                "total_cost": t.total_cost,
                "profit": t.profit,
                "profit_ratio": t.profit_ratio,
                "trade_date": t.trade_date,
                "trade_time": t.trade_time,
                "strategy_name": t.strategy_name,
                "strategy_reason": t.strategy_reason,
                "position_type": t.position_type,
                "trade_source": getattr(t, 'trade_source', None) or "manual",
            } for t in trades
        ]
    }


@router.post("/buy")
def buy_stock(request: BuyRequest, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """买入股票"""
    account = TradeEngine.get_or_create_account(db)
    
    result = TradeEngine.buy(
        db=db,
        account_id=account.id,
        stock_code=request.stock_code,
        stock_name=request.stock_name,
        price=request.price,
        quantity=request.quantity,
        strategy_name=request.strategy_name,
        strategy_reason=request.strategy_reason,
        position_type=request.position_type
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


@router.post("/sell")
def sell_stock(request: SellRequest, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """卖出股票"""
    account = TradeEngine.get_or_create_account(db)
    
    result = TradeEngine.sell(
        db=db,
        account_id=account.id,
        stock_code=request.stock_code,
        price=request.price,
        quantity=request.quantity,
        strategy_name=request.strategy_name,
        strategy_reason=request.strategy_reason
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


@router.post("/strategy/next-day")
def generate_next_day_strategy(
    config: Optional[StrategyConfig] = None,
    db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)
):
    """生成收盘次日策略（基于今日收盘数据，生成明日交易计划）

    该策略标记为下一个交易日，次日盘中监控自动执行。
    """
    account = TradeEngine.get_or_create_account(db)

    # 尝试获取最近一次复盘报告注入策略
    from datetime import date as _date
    from app.models.sim_trading import SimDailyReview
    today_str = _date.today().strftime("%Y-%m-%d")
    latest_review = db.query(SimDailyReview).filter(
        SimDailyReview.account_id == account.id,
        SimDailyReview.review_date <= today_str,
        SimDailyReview.ai_review.isnot(None),
    ).order_by(SimDailyReview.review_date.desc()).first()
    review_analysis = latest_review.ai_review if latest_review else ""

    result = AIStrategyGenerator.generate_next_day_strategy(
        db=db,
        account_id=account.id,
        config=config.dict() if config else None,
        review_analysis=review_analysis,
        source="manual",
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    # 收盘后不自动执行，策略保持pending状态
    return result


@router.post("/strategy/midday")
def generate_midday_strategy(
    config: Optional[StrategyConfig] = None,
    db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)
):
    """生成午间策略调整（手动生成，需手动执行）"""
    import traceback as _tb
    try:
        account = TradeEngine.get_or_create_account(db)

        result = AIStrategyGenerator.generate_midday_strategy(
            db=db,
            account_id=account.id,
            config=config.dict() if config else None,
            source="manual",
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        # 手动生成的策略不自动执行，等待用户手动执行
        result["executed"] = False
        return result
    except HTTPException:
        raise
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).error(f"generate_midday_strategy error: {_tb.format_exc()}")
        raise HTTPException(status_code=500, detail=f"内部错误: {e}")


@router.post("/strategy/generate")
def generate_strategy(
    config: Optional[StrategyConfig] = None,
    db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)
):
    """生成盘中即时策略（手动生成，需手动执行）"""
    account = TradeEngine.get_or_create_account(db)
    
    result = AIStrategyGenerator.generate_strategy(
        db=db,
        account_id=account.id,
        config=config.dict() if config else None,
        source="manual",
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    # 手动生成的策略不自动执行，等待用户手动执行
    result["executed"] = False
    result["execution_result"] = {
        "success": True,
        "buy_orders": [],
        "sell_orders": [],
        "errors": [],
        "skipped": "手动生成的策略需手动执行",
        "mode": "order",
    }

    return result


@router.post("/strategy/execute/{decision_id}")
def execute_strategy(decision_id: int, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """执行AI交易策略"""
    account = TradeEngine.get_or_create_account(db)
    
    result = AIStrategyGenerator.execute_strategy(db, decision_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.delete("/strategy/{decision_id}")
def delete_strategy_decision(
    decision_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """删除指定 AI 策略决策记录。

    可用于：
    - 手动重新生成前清空 pending 策略（避免重复执行）
    - 清理无效或错误的策略记录

    已执行的策略（execution_status = 'executed'）也可删除，但不会回滚已产生的交易。
    """
    decision = db.query(AIStrategyDecision).filter(
        AIStrategyDecision.id == decision_id
    ).first()
    if not decision:
        raise HTTPException(status_code=404, detail=f"策略决策 {decision_id} 不存在")

    decision_info = {
        "id": decision.id,
        "decision_date": decision.decision_date,
        "execution_status": decision.execution_status,
        "buy_count": len(json.loads(decision.buy_list or "[]")),
        "sell_count": len(json.loads(decision.sell_list or "[]")),
    }

    db.delete(decision)
    db.commit()

    logger.info(
        f"管理员 {current_admin.username} 删除策略决策: id={decision_id}, "
        f"date={decision_info['decision_date']}, status={decision_info['execution_status']}"
    )

    return {
        "success": True,
        "message": "策略已删除",
        "deleted": decision_info,
    }


@router.get("/strategy/history")
def get_strategy_history(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取策略历史"""
    account = TradeEngine.get_or_create_account(db)
    
    history = AIStrategyGenerator.get_strategy_history(db, account.id, limit)
    
    return {"history": history}


@router.get("/strategy/detail/{decision_id}")
def get_strategy_detail(
    decision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取策略详情"""
    from app.models.sim_trading import AIStrategyDecision
    decision = db.query(AIStrategyDecision).filter(AIStrategyDecision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="策略不存在")
    return {
        "id": decision.id,
        "decision_id": decision.id,
        "decision_date": decision.decision_date,
        "mode": decision.strategy_mode or "intraday",
        "strategy_mode": decision.strategy_mode or "intraday",
        "market_sentiment": decision.market_sentiment,
        "position_ratio": decision.position_ratio,
        "market_analysis": {
            "sentiment": decision.market_sentiment or "neutral",
            "analysis": decision.ai_analysis or "",
        },
        "buy_list": json.loads(decision.buy_list or "[]"),
        "sell_signals": json.loads(decision.sell_list or "[]"),
        "ai_analysis": decision.ai_analysis,
        "strategy_summary": decision.strategy_summary,
        "execution_status": decision.execution_status,
        "created_at": decision.created_at.strftime("%Y-%m-%d %H:%M:%S") if decision.created_at else None,
        "executed_at": decision.executed_at.strftime("%Y-%m-%d %H:%M:%S") if decision.executed_at else None,
    }


@router.get("/stats/performance")
def get_performance_report(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取业绩报告"""
    account = TradeEngine.get_or_create_account(db)
    
    report = PnLCalculator.generate_performance_report(db, account.id)
    
    if not report["success"]:
        raise HTTPException(status_code=400, detail=report["error"])
    
    return report


@router.get("/stats/monthly")
def get_monthly_pnl(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取月度盈亏"""
    account = TradeEngine.get_or_create_account(db)
    
    monthly_pnl = PnLCalculator.calculate_monthly_pnl(db, account.id, year)
    
    return {"monthly_pnl": monthly_pnl}


@router.get("/stats/drawdown")
def get_drawdown_curve(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取回撤曲线"""
    account = TradeEngine.get_or_create_account(db)
    
    drawdown_curve = PnLCalculator.calculate_drawdown_curve(db, account.id)
    
    return {"drawdown_curve": drawdown_curve}


@router.get("/stats/win-loss")
def get_win_loss_distribution(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取盈亏分布"""
    account = TradeEngine.get_or_create_account(db)
    
    win_loss_dist = PnLCalculator.calculate_win_loss_distribution(db, account.id)
    
    return win_loss_dist


@router.get("/daily-pnl")
def get_daily_pnl(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取每日盈亏"""
    from datetime import date, timedelta
    from app.models.sim_trading import SimDailyPnl
    
    account = TradeEngine.get_or_create_account(db)
    
    start_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    daily_pnls = db.query(SimDailyPnl).filter(
        and_(
            SimDailyPnl.account_id == account.id,
            SimDailyPnl.trade_date >= start_date
        )
    ).order_by(SimDailyPnl.trade_date).all()
    
    return {
        "daily_pnls": [
            {
                "trade_date": p.trade_date,
                "daily_profit": p.daily_profit,
                "daily_profit_ratio": p.daily_profit_ratio,
                "total_assets": p.total_assets,
                "total_profit": p.total_profit,
                "total_profit_ratio": p.total_profit_ratio,
                "position_count": p.position_count,
                "win_count": p.win_count,
                "loss_count": p.loss_count,
                "win_rate": p.win_rate
            } for p in daily_pnls
        ]
    }


@router.post("/daily-pnl/record")
def record_daily_pnl(db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """记录今日盈亏"""
    account = TradeEngine.get_or_create_account(db)
    
    result = TradeEngine.record_daily_pnl(db, account.id)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


@router.post("/daily-pnl/backfill")
def backfill_daily_pnl(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """补录历史每日盈亏记录（定时任务未触发时手动调用）"""
    account = TradeEngine.get_or_create_account(db)
    
    result = TradeEngine.backfill_daily_pnl(db, account.id, start_date, end_date)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


class UpdatePricesRequest(BaseModel):
    prices: dict


@router.post("/update-prices")
def update_position_prices(
    request: UpdatePricesRequest,
    db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)
):
    """更新持仓价格"""
    account = TradeEngine.get_or_create_account(db)
    
    TradeEngine.update_position_prices(db, account.id, request.prices)
    
    return {"success": True}


@router.post("/update-t1")
def update_t_plus_1(db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """更新T+1可卖数量"""
    account = TradeEngine.get_or_create_account(db)

    result = TradeEngine.update_t_plus_1(db, account.id)

    return {
        "success": True,
        "unlocked_positions": result.get("unlocked", 0),
        "last_trade_date": result.get("last_trade_date"),
    }


# ═══════════════════════════════════════════════════════════════════
# 委托单接口
# ═══════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════
# 委托管理接口
# ═══════════════════════════════════════════════════════════════════


@router.get("/orders")
def get_orders(
    status: Optional[str] = None,
    order_type: Optional[str] = None,
    stock_code: Optional[str] = None,
    order_source: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    today_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取委托单列表"""
    account = TradeEngine.get_or_create_account(db)

    orders = OrderService.get_orders(
        db=db,
        account_id=account.id,
        status=status,
        order_type=order_type,
        stock_code=stock_code,
        order_source=order_source,
        limit=limit,
        today_only=today_only,
    )

    return {"orders": orders}


@router.post("/orders")
def create_order(request: OrderRequest, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """创建委托单"""
    account = TradeEngine.get_or_create_account(db)

    result = OrderService.create_order(
        db=db,
        account_id=account.id,
        stock_code=request.stock_code,
        stock_name=request.stock_name,
        order_type=request.order_type,
        order_price=request.order_price,
        order_quantity=request.order_quantity,
        expire_type=request.expire_type,
        position_type=request.position_type,
        strategy_name=request.strategy_name,
        strategy_reason=request.strategy_reason,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """撤销委托单"""
    result = OrderService.cancel_order(db=db, order_id=order_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


class RepriceRequest(BaseModel):
    """委托改价请求（P2-8）"""
    new_price: float


@router.post("/orders/{order_id}/reprice")
def reprice_order(
    order_id: int,
    req: RepriceRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """轻量改价：仅更新委托价格，不撤单重挂

    适用场景：限价单偏离市价 0.5-3% 长期不成交时，调用此端点微调价格。
    约束：新价偏离原价不得超过 ±10%，否则需撤单重挂。
    """
    result = OrderService.reprice_order(db=db, order_id=order_id, new_price=req.new_price)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/orders/match")
def match_orders(
    force: bool = Query(False, description="是否强制撮合（跳过交易时段检查）"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """手动撮合当前账户所有待成交委托单

    适用场景：AI 策略生成的委托单长期不成交时，管理员可手动触发撮合。
    - 默认遵循交易时段限制（与后台调度一致）
    - force=true 时跳过交易时段检查，非交易时段也可成交（模拟系统特性）
    """
    account = TradeEngine.get_or_create_account(db)
    result = OrderService.match_orders(db, account.id, force=force)
    return result


@router.delete("/orders/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """删除委托单记录（管理员）—— 自动释放冻结资源"""
    from app.models.sim_trading import SimOrder, SimAccount, SimPosition
    from sqlalchemy import and_

    order = db.query(SimOrder).filter(SimOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="委托单不存在")

    # 释放冻结资源（仅 pending/partial 状态需要）
    if order.status in ("pending", "partial"):
        remaining_qty = order.order_quantity - order.filled_quantity
        account = db.query(SimAccount).filter(SimAccount.id == order.account_id).first()

        if order.order_type == "buy" and account:
            # 释放冻结资金（使用与 cancel_order 一致的计算方式，包含手续费）
            frozen_amount = OrderService._calc_buy_frozen_amount(order.order_price, remaining_qty)
            account.frozen_capital = max(0, (account.frozen_capital or 0) - frozen_amount)
            account.current_capital += frozen_amount

        elif order.order_type == "sell":
            # 释放冻结持仓
            position = db.query(SimPosition).filter(
                and_(
                    SimPosition.account_id == order.account_id,
                    SimPosition.stock_code == order.stock_code,
                )
            ).first()
            if position:
                position.available_quantity += remaining_qty

    db.delete(order)
    db.commit()
    return {"success": True, "message": "委托记录已删除"}


# ═══════════════════════════════════════════════════════════════════
# 做T接口
# ═══════════════════════════════════════════════════════════════════


@router.get("/t-trades")
def get_t_trades(
    trade_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取做T记录"""
    account = TradeEngine.get_or_create_account(db)

    result = TTradeService.get_t_trade_history(
        db=db,
        account_id=account.id,
        trade_date=trade_date,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "查询做T记录失败"))

    # 字段映射：service 返回 trades，前端契约期望 t_trades
    return {
        "t_trades": result.get("trades", []),
        "summary": result.get("summary", {}),
    }


@router.get("/t-trades/stats")
def get_t_trade_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取做T统计指标：总次数/成功数/胜率/累计降本金额/按模式分组"""
    from app.models.sim_trading import SimTTrade
    from sqlalchemy import func, case, and_

    account = TradeEngine.get_or_create_account(db)

    # 总体统计（仅 closed，避免 pending 影响 win_rate）
    total_row = db.query(
        func.count().label("total"),
        func.sum(case(
            (SimTTrade.profit > 0, 1),
            else_=0,
        )).label("wins"),
        func.sum(SimTTrade.profit).label("total_profit"),
        func.avg(SimTTrade.profit).label("avg_profit"),
    ).filter(
        and_(
            SimTTrade.account_id == account.id,
            SimTTrade.status == "closed",
        )
    ).first()

    total = total_row.total or 0
    wins = total_row.wins or 0
    total_profit = total_row.total_profit or 0
    avg_profit = total_row.avg_profit or 0

    # 今日统计
    from datetime import date as _date
    today_str = _date.today().strftime("%Y-%m-%d")
    today_row = db.query(
        func.count().label("total"),
        func.sum(SimTTrade.profit).label("profit"),
    ).filter(
        and_(
            SimTTrade.account_id == account.id,
            SimTTrade.buy_date == today_str,
        )
    ).first()
    today_total = today_row.total or 0
    today_profit = today_row.profit or 0

    return {
        "success": True,
        "total": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
        "total_profit": round(total_profit, 2),
        "avg_profit": round(avg_profit, 2),
        "today_count": today_total,
        "today_profit": round(today_profit, 2),
    }


@router.post("/t-trades/detect")
def detect_t_trade(stock_code: str, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """检测做T机会"""
    result = TTradeService.detect_t_opportunity(db=db, stock_code=stock_code)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "检测做T机会失败"))

    return result


@router.post("/t-trades/execute")
def execute_t_trade(request: TTradeRequest, db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """执行做T"""
    account = TradeEngine.get_or_create_account(db)

    result = TTradeService.execute_t_trade(
        db=db,
        account_id=account.id,
        stock_code=request.stock_code,
        buy_price=request.buy_price,
        sell_price=request.sell_price,
        quantity=request.quantity,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


# ═══════════════════════════════════════════════════════════════════
# 管理员专用：重置模拟交易
# ═══════════════════════════════════════════════════════════════════


@router.post("/admin/reset")
def admin_reset_account(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """重置模拟交易账户：清空所有持仓、交易、委托、策略、盈亏、复盘、做T、监控列表，并将账户资金恢复到初始值。"""
    from datetime import datetime
    from app.models.sim_trading import (
        SimPosition, SimTrade, SimOrder, SimDailyPnl, SimTTrade,
        SimDailyReview, AIStrategyDecision, SimStrategyStats, SimWatchlist,
    )

    account = TradeEngine.get_or_create_account(db)
    aid = account.id

    deleted = {}
    deleted["positions"] = db.query(SimPosition).filter(SimPosition.account_id == aid).delete()
    deleted["trades"] = db.query(SimTrade).filter(SimTrade.account_id == aid).delete()
    deleted["orders"] = db.query(SimOrder).filter(SimOrder.account_id == aid).delete()
    deleted["daily_pnls"] = db.query(SimDailyPnl).filter(SimDailyPnl.account_id == aid).delete()
    deleted["t_trades"] = db.query(SimTTrade).filter(SimTTrade.account_id == aid).delete()
    deleted["daily_reviews"] = db.query(SimDailyReview).filter(SimDailyReview.account_id == aid).delete()
    deleted["strategy_decisions"] = db.query(AIStrategyDecision).filter(AIStrategyDecision.account_id == aid).delete()
    deleted["strategy_stats"] = db.query(SimStrategyStats).filter(SimStrategyStats.account_id == aid).delete()
    deleted["watchlist"] = db.query(SimWatchlist).filter(SimWatchlist.account_id == aid).delete()

    initial = float(account.initial_capital or 100000.0)
    account.current_capital = initial
    account.total_assets = initial
    account.frozen_capital = 0.0
    account.total_deposits = 0.0
    account.updated_at = datetime.now()

    db.commit()

    return {
        "success": True,
        "message": f"模拟交易已重置，已清空 {sum(deleted.values())} 条记录，账户资金已恢复至 {initial:,.2f} 元",
        "deleted": deleted,
        "account": TradeEngine.get_account_summary(db, aid),
    }


class InitialCapitalRequest(BaseModel):
    initial_capital: float


class DepositRequest(BaseModel):
    amount: float
    remark: Optional[str] = None


@router.get("/admin/initial-capital")
def get_initial_capital(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """获取模拟交易账户初始金额配置（管理员）"""
    account = TradeEngine.get_or_create_account(db)
    return {"initial_capital": float(account.initial_capital or 100000.0)}


@router.put("/admin/initial-capital")
def update_initial_capital(
    req: InitialCapitalRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """更新模拟交易账户初始金额（管理员）

    调整后：
    - 若账户尚无任何交易/持仓：直接修改 initial_capital 并同步 current_capital/total_assets
    - 若已有交易/持仓：只更新 initial_capital（作为后续盈亏计算的基准），不动现有 current/total
      提示管理员需要"重置账户"才能让新初始金额完全生效
    """
    new_capital = float(req.initial_capital)
    if new_capital < 1000:
        raise HTTPException(status_code=400, detail=f"初始金额不能小于 1,000 元（收到: {new_capital:,.2f})")
    if new_capital > 100_000_000:
        raise HTTPException(status_code=400, detail="初始金额不能大于 1 亿")

    try:
        from app.models.sim_trading import SimPosition, SimTrade
        account = TradeEngine.get_or_create_account(db)
        old = float(account.initial_capital or 0)
        account.initial_capital = new_capital

        has_trades = (
            db.query(SimPosition).filter(SimPosition.account_id == account.id).count() > 0
            or db.query(SimTrade).filter(SimTrade.account_id == account.id).count() > 0
        )

        if not has_trades:
            account.current_capital = new_capital
            account.total_assets = new_capital
            account.frozen_capital = 0.0
            apply_today = True
        else:
            apply_today = False

        db.commit()
        db.refresh(account)

        return {
            "success": True,
            "old_initial_capital": old,
            "new_initial_capital": new_capital,
            "applied_today": apply_today,
            "message": (
                "初始金额已更新，资金账户已重置" if apply_today
                else f"初始金额已更新为 {new_capital:,.2f} 元（已有交易数据，仅影响后续盈亏基准，建议重置账户以完整生效）"
            ),
            "account": TradeEngine.get_account_summary(db, account.id),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"更新初始金额失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新初始金额失败: {str(e)}")


@router.post("/admin/deposit")
def admin_deposit(
    req: DepositRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """管理员入金：增加账户可用资金（仅影响 current_capital，不改变 initial_capital）"""
    amount = float(req.amount)
    if amount < 100:
        raise HTTPException(status_code=400, detail=f"入金金额不能小于 100 元（收到: {amount:,.2f})")
    if amount > 100_000_000:
        raise HTTPException(status_code=400, detail="单次入金金额不能大于 1 亿")

    try:
        account = TradeEngine.get_or_create_account(db)
        before = float(account.current_capital or 0)

        account.current_capital = before + amount
        account.total_deposits = float(account.total_deposits or 0) + amount
        account.updated_at = datetime.now()

        # 使用统一计算函数更新总资产（而非简单累加，确保与持仓市值一致）
        account.total_assets = TradeEngine.calculate_total_assets(db, account=account)

        db.commit()
        db.refresh(account)

        return {
            "success": True,
            "amount": amount,
            "before_capital": before,
            "after_capital": account.current_capital,
            "remark": req.remark or "",
            "message": f"已成功入金 {amount:,.2f} 元，可用资金由 {before:,.2f} 增至 {account.current_capital:,.2f}",
            "account": TradeEngine.get_account_summary(db, account.id),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"入金失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"入金失败: {str(e)}")


# ═══════════════════════════════════════════════════════════════════
# 复盘接口
# ═══════════════════════════════════════════════════════════════════


@router.get("/reviews")
def get_reviews(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取复盘历史"""
    account = TradeEngine.get_or_create_account(db)

    reviews = ReviewService.get_review_history(
        db=db,
        account_id=account.id,
        limit=limit,
    )

    return {"reviews": reviews}


@router.get("/reviews/{review_date}")
def get_review(
    review_date: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定日期复盘"""
    account = TradeEngine.get_or_create_account(db)

    review = ReviewService.get_daily_review(
        db=db,
        account_id=account.id,
        review_date=review_date,
    )

    if not review:
        raise HTTPException(status_code=404, detail=f"未找到 {review_date} 的复盘记录")

    return review


@router.post("/reviews/generate")
def generate_review(
    review_date: Optional[str] = None,
    db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)
):
    """手动生成复盘"""
    from datetime import date as date_cls

    account = TradeEngine.get_or_create_account(db)

    if not review_date:
        review_date = date_cls.today().strftime("%Y-%m-%d")

    result = ReviewService.generate_daily_review(
        db=db,
        account_id=account.id,
        review_date=review_date,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "生成复盘失败"))

    return result


@router.get("/reviews/{review_date}/plan")
def get_tomorrow_plan(
    review_date: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取明日计划"""
    account = TradeEngine.get_or_create_account(db)

    result = ReviewService.generate_tomorrow_plan(
        db=db,
        account_id=account.id,
        review_date=review_date,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "生成明日计划失败"))

    return result


# ═══════════════════════════════════════════════════════════════════
# 风险管理接口
# ═══════════════════════════════════════════════════════════════════


@router.post("/risk/check")
def check_risk(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检查风险状态"""
    account = TradeEngine.get_or_create_account(db)

    result = RiskManager.check_all_risks(db=db, account_id=account.id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "风险检查失败"))

    return result


@router.post("/risk/execute")
def execute_risk_control(db: Session = Depends(get_db), current_admin: User = Depends(get_current_admin)):
    """执行风险控制"""
    account = TradeEngine.get_or_create_account(db)

    result = RiskManager.execute_risk_sells(db=db, account_id=account.id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "执行风险控制失败"))

    return result