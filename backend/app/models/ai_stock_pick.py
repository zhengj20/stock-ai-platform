"""AI股票推荐模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from app.core.database import Base


class AIStockPick(Base):
    """AI股票推荐（自动清理30天前数据）"""
    __tablename__ = "ai_stock_picks"

    id = Column(Integer, primary_key=True, index=True)
    pick_date = Column(String(10), nullable=False, unique=True, index=True)  # YYYY-MM-DD
    market_data = Column(Text, nullable=True)  # JSON: 市场数据快照
    picks_data = Column(Text, nullable=True)   # JSON: 股票推荐数据
    ai_report = Column(Text, nullable=True)    # AI生成的推荐报告文本
    prompt_version = Column(String(20), nullable=True)
    status = Column(String(20), default="completed")  # generating / completed / failed
    error_msg = Column(String(500), nullable=True)
    generated_at = Column(DateTime, default=datetime.now, index=True)
