"""用户真实持仓数据模型（手动录入）"""
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, Index, UniqueConstraint
from datetime import datetime
from app.core.database import Base


class Holding(Base):
    """用户真实持仓（手动录入）"""
    __tablename__ = "holdings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(50), default="")

    # 持仓信息
    quantity = Column(Integer, nullable=False, default=0)  # 持仓数量
    cost_price = Column(Float, nullable=False, default=0.0)  # 成本价
    current_price = Column(Float, nullable=False, default=0.0)  # 当前价格
    market_value = Column(Float, nullable=False, default=0.0)  # 市值
    profit = Column(Float, nullable=False, default=0.0)  # 浮动盈亏
    profit_ratio = Column(Float, nullable=False, default=0.0)  # 盈亏比例(%)

    # 买入信息
    buy_date = Column(String(10), nullable=True)  # 买入日期 YYYY-MM-DD
    buy_reason = Column(Text, nullable=True)  # 买入理由
    notes = Column(Text, nullable=True)  # 备注

    # 持仓类型
    position_type = Column(String(20), default="short")  # short=短线, mid=中线, long=长线

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("user_id", "stock_code", name="uq_holding_user_stock"),
        Index("idx_holding_user", "user_id"),
    )
