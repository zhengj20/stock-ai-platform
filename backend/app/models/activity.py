"""用户活动日志模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class UserActivity(Base):
    __tablename__ = "user_activities"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(50), nullable=False)  # login / logout / api_call / admin_action
    detail = Column(Text, nullable=True)  # JSON字符串，详细记录
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)

    # 关联
    user = relationship("User", back_populates="activities")
