"""配额模型 - 每日AI对话次数限制"""
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class DailyQuota(Base):
    """每角色每日AI对话配额配置"""
    __tablename__ = "daily_quotas"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(20), unique=True, nullable=False, index=True)  # normal / vip / admin
    max_daily = Column(Integer, nullable=False, default=30)  # 每日最大次数，9999表示不限
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<DailyQuota(role='{self.role}', max_daily={self.max_daily})>"


class QuotaUsage(Base):
    """每用户每日AI对话实际用量"""
    __tablename__ = "quota_usages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)  # 计数日期
    used_count = Column(Integer, nullable=False, default=0)

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_user_date"),
    )

    def __repr__(self):
        return f"<QuotaUsage(user_id={self.user_id}, date={self.date}, used={self.used_count})>"
