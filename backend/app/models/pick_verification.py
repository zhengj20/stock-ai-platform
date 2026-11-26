"""选股验证模型"""
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Index
from datetime import datetime
from app.core.database import Base


class PickVerification(Base):
    """选股前向验证记录"""
    __tablename__ = "pick_verification"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pick_date = Column(Date, nullable=False)
    strategy_type = Column(String(50), nullable=False)
    stock_code = Column(String(6), nullable=False)
    stock_name = Column(String(20), nullable=True)
    pick_score = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=True)
    return_1d = Column(Float, nullable=True)
    return_3d = Column(Float, nullable=True)
    return_5d = Column(Float, nullable=True)
    return_10d = Column(Float, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_pick_verification_date_strategy", "pick_date", "strategy_type"),
        Index("idx_pick_verification_stock_code", "stock_code"),
        Index("idx_pick_verification_pick_date", "pick_date"),
    )
