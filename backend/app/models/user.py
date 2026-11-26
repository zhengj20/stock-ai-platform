"""用户模型 - 用户 + 邀请码"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="normal")  # normal / vip / admin
    status = Column(String(20), default="active")  # active / disabled
    invite_code = Column(String(20), nullable=True)  # 注册时使用的邀请码
    remark = Column(Text, nullable=True)  # 管理员备注
    expiry_start_date = Column(DateTime, nullable=True)  # 有效期开始日期
    expiry_date = Column(DateTime, nullable=True)  # 账号到期时间，None表示永不过期
    created_at = Column(DateTime, default=datetime.now)
    last_login = Column(DateTime, nullable=True)

    # 关联
    chat_sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    watchlist_items = relationship("WatchlistItem", back_populates="user", cascade="all, delete-orphan")
    activities = relationship("UserActivity", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(32), unique=True, index=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # 创建者ID
    used_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # 使用者ID
    used_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    # 关联
    creator = relationship("User", foreign_keys=[created_by])
    user = relationship("User", foreign_keys=[used_by])

    def __repr__(self):
        status = "已使用" if self.used_at else "未使用"
        return f"<InviteCode(code='{self.code}', {status})>"
