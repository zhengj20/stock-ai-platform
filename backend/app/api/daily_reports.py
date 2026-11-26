"""每日复盘报告API路由"""
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user, get_current_admin
from app.models.user import User
from app.services.daily_report_service import daily_report_service
from app.core.trading_calendar import is_trading_day, get_last_trade_date

router = APIRouter()


def _get_default_report_date() -> str:
    """获取默认报告日期：交易时间用今天，非交易时间用最近交易日"""
    now = datetime.now()
    # 交易日且在交易时间（9:00-15:00）
    if is_trading_day(now):
        hour_min = now.hour * 60 + now.minute
        if 540 <= hour_min <= 900:  # 9:00-15:00
            return now.strftime("%Y-%m-%d")
    # 非交易时间，使用最近交易日
    trade_date = get_last_trade_date()
    return datetime.strptime(trade_date, '%Y%m%d').strftime('%Y-%m-%d')


@router.get("/market/daily-reports")
async def list_reports(
    days: int = Query(default=30, ge=1, le=90, description="获取最近N天的报告"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取复盘报告列表"""
    return daily_report_service.list_reports(db, days)


@router.get("/market/daily-reports/latest")
async def get_latest_report(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取最新一条复盘报告（含完整AI文本）"""
    report = daily_report_service.get_latest_report(db)
    if not report:
        return {"message": "暂无报告"}
    return report


@router.get("/market/daily-reports/{report_date}")
async def get_report_by_date(
    report_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取指定日期的复盘报告（含完整AI文本）"""
    # 验证日期格式
    try:
        datetime.strptime(report_date, "%Y-%m-%d")
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="日期格式错误，应为 YYYY-MM-DD")

    report = daily_report_service.get_report_detail(db, report_date)
    if not report:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"{report_date} 的报告不存在")
    return report


@router.post("/market/daily-reports/generate")
async def generate_report(
    report_date: str = Query(default=None, description="指定日期，默认最近交易日"),
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """手动触发生成复盘报告（仅管理员）"""
    if report_date is None:
        report_date = _get_default_report_date()

    # 验证是否为交易日
    check_dt = datetime.strptime(report_date, "%Y-%m-%d")
    if not is_trading_day(check_dt):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"{report_date} 非交易日，不生成报告")

    try:
        result = await daily_report_service.generate_report(db, report_date, force=True)
        return {"status": "ok", "report": result}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"报告生成失败: {str(e)}")


@router.post("/market/daily-reports/cleanup")
async def cleanup_reports(
    days: int = Query(default=30, ge=7, le=90, description="保留天数"),
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """清理过期报告（仅管理员）"""
    deleted = daily_report_service.cleanup_old_reports(db, days)
    return {"status": "ok", "deleted_count": deleted}
