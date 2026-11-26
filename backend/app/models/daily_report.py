"""每日复盘报告模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, func
from datetime import datetime
from app.core.database import Base


class DailyReport(Base):
    """每日复盘报告（自动清理30天前数据）"""
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_date = Column(String(10), nullable=False, unique=True, index=True)  # YYYY-MM-DD
    market_data = Column(Text, nullable=True)  # JSON字符串，原始市场数据快照
    ai_report = Column(Text, nullable=True)  # AI生成的专业研报文本
    prompt_version = Column(String(20), nullable=True)  # prompt版本号，用于追溯
    status = Column(String(20), default="completed")  # generating / completed / failed
    error_msg = Column(String(500), nullable=True)
    generated_at = Column(DateTime, default=datetime.now, index=True)
