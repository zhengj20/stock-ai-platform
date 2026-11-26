"""自选股模型"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(50), default="")
    group = Column(String(50), default="默认")  # 分组名称
    sort_order = Column(Integer, default=0)  # 排序序号
    created_at = Column(DateTime, default=datetime.now)

    # 关联
    user = relationship("User", back_populates="watchlist_items")

    # 唯一约束：同一用户不能重复添加同一只股票
    __table_args__ = (
        UniqueConstraint("user_id", "stock_code", name="uq_watchlist_user_stock"),
    )
