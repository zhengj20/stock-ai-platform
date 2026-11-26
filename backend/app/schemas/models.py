"""数据模型定义"""
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class MarketSentiment(BaseModel):
    """市场情绪"""
    date: str
    score: int  # 0-100
    status: str  # 冰点/低迷/温和/亢奋/过热
    trend: str  # 上升/下降/震荡
    indicators: dict[str, Any]


class SectorInfo(BaseModel):
    """板块信息"""
    name: str
    change_pct: float
    turnover: float
    flow_net: float  # 资金净流入


class StockQuote(BaseModel):
    """股票行情"""
    code: str
    name: str
    price: float
    change_pct: float
    volume: float
    amount: float


class TechnicalIndicator(BaseModel):
    """技术指标"""
    name: str
    value: dict[str, Any]
    signal: str  # 买入/卖出/中性


class KlinePattern(BaseModel):
    """K线形态"""
    name: str
    direction: str  # bullish/bearish/neutral
    confidence: float
    date: str


class MultiFactorResult(BaseModel):
    """多因子评分结果"""
    rank: int
    stock_name: str
    stock_code: str
    total_score: float
    factor_scores: dict[str, float]


class StrategySignal(BaseModel):
    """策略信号"""
    strategy_name: str
    stock_code: str
    signal_strength: float
    action: str  # 买入/卖出/观望
    details: dict[str, Any]


class DragonListEntry(BaseModel):
    """龙虎榜条目"""
    code: str
    name: str
    price: float = 0.0
    change_pct: float = 0.0
    reason: str = ''  # 上榜原因
    net_amount: float = 0.0  # 净买入额
    direction: str = '持平'  # 资金方向：净买入/净卖出/持平
