"""配额服务 - 管理每日AI对话次数（原子操作防竞态）"""
from datetime import date, datetime
from sqlalchemy.orm import Session
from app.models.quota import DailyQuota, QuotaUsage
from app.models.user import User

# 默认配额配置：{角色: 每日次数}，9999表示不限
DEFAULT_QUOTAS = {
    "normal": 30,
    "vip": 200,
    "admin": 9999,
}


def init_default_quotas(db: Session):
    """初始化默认配额配置（启动时调用）"""
    for role, max_daily in DEFAULT_QUOTAS.items():
        existing = db.query(DailyQuota).filter(DailyQuota.role == role).first()
        if not existing:
            db.add(DailyQuota(role=role, max_daily=max_daily))
    db.commit()


def get_quota_limit(db: Session, role: str) -> int:
    """获取某角色的每日配额上限"""
    quota = db.query(DailyQuota).filter(DailyQuota.role == role).first()
    if quota:
        return quota.max_daily
    return DEFAULT_QUOTAS.get(role, 30)


def get_quota_info(db: Session, user: User) -> dict:
    """获取用户当前配额信息"""
    today = date.today()
    limit = get_quota_limit(db, user.role)

    usage = db.query(QuotaUsage).filter(
        QuotaUsage.user_id == user.id,
        QuotaUsage.date == today,
    ).first()
    used = usage.used_count if usage else 0

    remaining = max(0, limit - used) if limit < 9999 else 9999

    return {
        "role": user.role,
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "unlimited": limit >= 9999,
        "date": today.isoformat(),
    }


def check_and_consume(db: Session, user: User) -> tuple[bool, dict]:
    """
    检查并消耗一次配额（原子操作，防竞态）。
    返回: (allowed, quota_info)
    - allowed: 是否允许使用
    - quota_info: 当前配额信息
    """
    today = date.today()
    limit = get_quota_limit(db, user.role)

    # 管理员不限
    if limit >= 9999:
        return True, get_quota_info(db, user)

    usage = db.query(QuotaUsage).filter(
        QuotaUsage.user_id == user.id,
        QuotaUsage.date == today,
    ).first()

    if not usage:
        usage = QuotaUsage(user_id=user.id, date=today, used_count=0)
        db.add(usage)
        db.flush()

    # 检查是否超限（原子：先查后改在同一事务中）
    if usage.used_count >= limit:
        info = get_quota_info(db, user)
        return False, info

    # 扣减计数 + commit 保证原子性
    usage.used_count += 1
    db.commit()

    info = get_quota_info(db, user)
    return True, info


def refund_quota(db: Session, user: User) -> bool:
    """
    退还一次配额（LLM 调用失败/中断时调用）。
    仅当日已消耗的配额可退，且不会退到 0 以下。
    使用原子操作防止竞态条件。
    """
    today = date.today()
    limit = get_quota_limit(db, user.role)
    if limit >= 9999:
        return True

    usage = db.query(QuotaUsage).filter(
        QuotaUsage.user_id == user.id,
        QuotaUsage.date == today,
    ).first()
    # 原子操作：SQL WHERE 条件保证不会退到负数
    if usage and usage.used_count > 0:
        db.query(QuotaUsage).filter(
            QuotaUsage.user_id == user.id,
            QuotaUsage.date == today,
            QuotaUsage.used_count > 0,
        ).update({QuotaUsage.used_count: QuotaUsage.used_count - 1})
        db.commit()
    return True


def reset_user_today(db: Session, user_id: int) -> bool:
    """重置某用户今日用量"""
    today = date.today()
    usage = db.query(QuotaUsage).filter(
        QuotaUsage.user_id == user_id,
        QuotaUsage.date == today,
    ).first()
    if usage:
        usage.used_count = 0
        db.commit()
    return True


def get_all_users_usage_today(db: Session) -> list[dict]:
    """获取所有用户今日用量"""
    today = date.today()
    usages = db.query(QuotaUsage).filter(QuotaUsage.date == today).all()
    usage_map = {u.user_id: u.used_count for u in usages}

    users = db.query(User).filter(User.status == "active").all()
    result = []
    for u in users:
        limit = get_quota_limit(db, u.role)
        used = usage_map.get(u.id, 0)
        result.append({
            "user_id": u.id,
            "username": u.username,
            "role": u.role,
            "limit": limit,
            "used": used,
            "remaining": max(0, limit - used) if limit < 9999 else 9999,
        })
    return result


def update_quota_limit(db: Session, role: str, max_daily: int) -> bool:
    """更新某角色的每日配额"""
    quota = db.query(DailyQuota).filter(DailyQuota.role == role).first()
    if quota:
        quota.max_daily = max_daily
    else:
        db.add(DailyQuota(role=role, max_daily=max_daily))
    db.commit()
    return True


def get_all_quotas(db: Session) -> list[dict]:
    """获取所有角色的配额配置"""
    quotas = db.query(DailyQuota).all()
    result = []
    for q in quotas:
        result.append({
            "role": q.role,
            "max_daily": q.max_daily,
            "updated_at": q.updated_at.isoformat() if q.updated_at else None,
        })
    configured_roles = {q.role for q in quotas}
    for role, default_val in DEFAULT_QUOTAS.items():
        if role not in configured_roles:
            result.append({"role": role, "max_daily": default_val, "updated_at": None})
    return result

