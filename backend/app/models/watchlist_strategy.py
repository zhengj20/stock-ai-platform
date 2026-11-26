"""自选股AI策略数据模型（仅建议，不执行）"""
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class WatchlistStrategyDecision(Base):
    """自选股AI策略决策（仅建议，不执行）"""
    __tablename__ = "watchlist_strategy_decisions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # 策略信息
    decision_date = Column(String(10), nullable=False, index=True)  # 决策日期 YYYY-MM-DD
    decision_time = Column(String(8), nullable=False)  # 决策时间 HH:MM:SS
    strategy_mode = Column(String(20), nullable=False)  # morning/midday/afternoon/closing

    # 策略内容
    market_sentiment = Column(String(20))  # bullish/bearish/neutral
    market_analysis = Column(Text)  # 市场分析
    position_analysis = Column(Text)  # 持仓分析

    # 建议列表（JSON格式）
    holdings_suggestions = Column(Text)  # 持仓股票建议（卖出/减仓/持有/加仓）
    watchlist_suggestions = Column(Text)  # 自选股建议（买入/关注）

    # 仓位与市场环境（P0新增）
    position_ratio = Column(Float)  # 建议总仓位比例 0-100
    dynamic_max_position = Column(Float)  # 动态最大仓位比例 0-100
    suggested_allocation = Column(Text)  # 建议周期配置 JSON {"short":30,"mid":30,"long":20}
    market_stage = Column(String(30))  # 牛市(强势)/熊市(弱势)/震荡市

    # 决策依据摘要（P0新增，供前端展示）
    market_indicators = Column(Text)  # 市场指标 JSON: 板块排名/北向资金/龙虎榜/板块轮动

    # 元信息
    ai_analysis = Column(Text)  # AI完整分析
    risk_warning = Column(Text)  # 风险提示

    # 状态
    status = Column(String(20), default="active")  # active/archived

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_watchlist_strategy_user_date", "user_id", "decision_date", "decision_time"),
    )


class WatchlistStrategyConfig(Base):
    """自选股策略时间配置（仅管理员可配置）"""
    __tablename__ = "watchlist_strategy_config"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    # 按策略模式分组的时间配置（JSON格式）
    # 默认值: intraday=["10:25","14:10"], midday=["12:30"], closing=["16:00"]
    intraday_times = Column(Text, default='["10:25","14:10"]')
    midday_times = Column(Text, default='["12:30"]')
    closing_times = Column(Text, default='["16:00"]')

    # 兼容旧字段（废弃，但保留用于迁移）
    schedule_times = Column(Text, default=None)

    # 功能开关
    is_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
