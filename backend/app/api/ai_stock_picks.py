"""AI股票推荐API路由"""
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user, get_current_admin
from app.models.user import User
from app.services.ai_stock_pick_service import ai_stock_pick_service
from app.core.trading_calendar import is_trading_day, get_last_trade_date
from app.main import limiter

router = APIRouter()


def _get_default_pick_date() -> str:
    """获取默认推荐日期：交易时间用今天，非交易时间用最近交易日"""
    now = datetime.now()
    # 交易日且在交易时间（9:00-15:00）
    if is_trading_day(now):
        hour_min = now.hour * 60 + now.minute
        if 540 <= hour_min <= 900:  # 9:00-15:00
            return now.strftime("%Y-%m-%d")
    # 非交易时间，使用最近交易日
    trade_date = get_last_trade_date()
    return datetime.strptime(trade_date, '%Y%m%d').strftime('%Y-%m-%d')


@router.get("/ai-stock-picks")
async def list_picks(
    days: int = Query(default=30, ge=1, le=90, description="获取最近N天的推荐"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取股票推荐列表"""
    return ai_stock_pick_service.list_picks(db, days)


@router.get("/ai-stock-picks/latest")
async def get_latest_pick(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取最新一条推荐"""
    pick = ai_stock_pick_service.get_latest_pick(db)
    if not pick:
        return {"message": "暂无推荐"}
    return pick


@router.get("/ai-stock-picks/{pick_date}")
async def get_pick_by_date(
    pick_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取指定日期的推荐详情"""
    # 验证日期格式
    try:
        datetime.strptime(pick_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，应为 YYYY-MM-DD")

    pick = ai_stock_pick_service.get_pick_by_date(db, pick_date)
    if not pick:
        raise HTTPException(status_code=404, detail=f"{pick_date} 的推荐不存在")
    return pick


@router.post("/ai-stock-picks/generate")
@limiter.limit("5/minute")  # AI 选股生成限流：单 IP 每分钟最多 5 次（重操作）
async def generate_pick(
    request: Request,
    date: str = Query(default=None, description="指定日期，默认最近交易日"),
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """手动生成股票推荐（仅管理员）"""
    if date is None:
        date = _get_default_pick_date()

    # 验证是否为交易日
    check_dt = datetime.strptime(date, "%Y-%m-%d")
    if not is_trading_day(check_dt):
        raise HTTPException(status_code=400, detail=f"{date} 非交易日，不生成推荐")

    try:
        result = await ai_stock_pick_service.generate_picks(db, date, force=True)
        return {"status": "ok", "pick": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"推荐生成失败: {str(e)}")


@router.post("/ai-stock-picks/cleanup")
async def cleanup_picks(
    days: int = Query(default=30, ge=7, le=90, description="保留天数"),
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """清理过期推荐（仅管理员）"""
    deleted = ai_stock_pick_service.cleanup_old_picks(db, days)
    return {"status": "ok", "deleted_count": deleted}
