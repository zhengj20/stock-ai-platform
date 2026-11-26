#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股智能预警系统 (Smart Alert System)
=====================================
提供全方位的股票预警功能，包括：
1. 个股异动预警（技术指标、量价异动、价格突破）
2. 板块轮动预警（资金流入、热点追踪）
3. 风险预警（止损位、基本面恶化）
4. 自定义预警规则
5. 多渠道通知（控制台、日志、可扩展）

用法:
    # 监控单只股票
    python smart_alert.py monitor --stock 600519
    
    # 监控股票池
    python smart_alert.py monitor --pool "600519,300750,002594"
    
    # 使用预设规则
    python smart_alert.py monitor --stock 600519 --rules "macd_cross,kdj_oversold,breakout"
    
    # 自定义阈值
    python smart_alert.py monitor --stock 600519 --volume-ratio 2.0 --price-change 3.0

依赖: pip install pandas numpy requests

作者: Hermes Agent
版本: 1.0.0
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from abc import ABC, abstractmethod

import pandas as pd
import numpy as np
import requests


# ============================================================================
# 预警级别和类型定义
# ============================================================================

class AlertLevel(Enum):
    """预警级别"""
    INFO = "INFO"           # 信息
    WARNING = "WARNING"     # 警告
    CRITICAL = "CRITICAL"   # 严重
    EMERGENCY = "EMERGENCY" # 紧急


class AlertType(Enum):
    """预警类型"""
    # 技术指标类
    MACD_GOLDEN_CROSS = "MACD_GOLDEN_CROSS"           # MACD金叉
    MACD_DEATH_CROSS = "MACD_DEATH_CROSS"             # MACD死叉
    KDJ_OVERSOLD = "KDJ_OVERSOLD"                     # KDJ超卖
    KDJ_OVERBOUGHT = "KDJ_OVERBOUGHT"                 # KDJ超买
    RSI_OVERSOLD = "RSI_OVERSOLD"                     # RSI超卖
    RSI_OVERBOUGHT = "RSI_OVERBOUGHT"                 # RSI超买
    
    # 量价异动类
    VOLUME_BREAKOUT = "VOLUME_BREAKOUT"               # 放量突破
    PRICE_BREAKOUT = "PRICE_BREAKOUT"                 # 价格突破
    PRICE_DROP = "PRICE_DROP"                         # 大幅下跌
    
    # 趋势类
    TREND_REVERSAL = "TREND_REVERSAL"                 # 趋势反转
    SUPPORT_BREAK = "SUPPORT_BREAK"                   # 跌破支撑
    RESISTANCE_BREAK = "RESISTANCE_BREAK"             # 突破阻力
    
    # 风险类
    STOP_LOSS = "STOP_LOSS"                           # 止损预警
    HIGH_VOLATILITY = "HIGH_VOLATILITY"               # 高波动预警

    # 持仓感知类（需传入 holding_context）
    POSITION_STOP_LOSS = "POSITION_STOP_LOSS"         # 成本价止损
    POSITION_TAKE_PROFIT = "POSITION_TAKE_PROFIT"     # 成本价止盈
    POSITION_TRAILING_STOP = "POSITION_TRAILING_STOP" # 移动止损
    POSITION_COST_PRESSURE = "POSITION_COST_PRESSURE" # 成本压力位
    
    # 板块类
    SECTOR_INFLOW = "SECTOR_INFLOW"                   # 板块资金流入
    SECTOR_OUTFLOW = "SECTOR_OUTFLOW"                 # 板块资金流出


class ActionSignal(Enum):
    """交易信号"""
    BUY = "BUY"            # 买入 - 底部信号，适合建仓
    ADD = "ADD"            # 加仓 - 趋势确认，适合追加仓位
    REDUCE = "REDUCE"      # 减仓 - 顶部信号，适合降低风险
    SELL = "SELL"          # 卖出 - 强烈卖出信号，清仓或止损
    HOLD = "HOLD"          # 观望 - 中性信号


@dataclass
class Alert:
    """预警信息"""
    timestamp: str
    stock_code: str
    stock_name: str
    alert_type: AlertType
    alert_level: AlertLevel
    message: str
    current_value: float
    threshold_value: float
    recommendation: str
    action_signal: Optional[str] = None  # BUY/ADD/REDUCE/SELL/HOLD
    metadata: Optional[Dict] = None


# ============================================================================
# 数据获取模块
# ============================================================================

class AlertDataFetcher:
    """预警数据获取器"""

    @staticmethod
    def _ensure_exchange_prefix(code: str) -> str:
        """为股票代码添加交易所前缀（腾讯财经API需要）"""
        code = code.strip()
        if len(code) < 6:
            return code
        # 已有前缀则直接返回
        if code.startswith(('sh', 'sz', 'bj')):
            return code
        # 根据代码段判断交易所
        if code.startswith(('60', '68')):
            return f"sh{code}"
        elif code.startswith(('00', '30', '01', '02', '03')):
            return f"sz{code}"
        elif code.startswith(('4', '8')):
            return f"bj{code}"
        return code

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self._rt_cache: dict = {}          # {code: (ts, data)}
        self._rt_cache_ttl = 60            # 同一股票 60 秒内复用
        self._last_request_time = 0        # 请求间隔控制
        self._min_interval = 0.5           # 最小请求间隔（秒）

    def fetch_realtime_data(self, stock_code: str) -> Dict[str, Any]:
        """获取实时行情数据（带 60s 短时缓存 + 请求节流）"""
        import time as _t
        now = _t.time()
        cached = self._rt_cache.get(stock_code)
        if cached and now - cached[0] < self._rt_cache_ttl:
            return cached[1]

        # 请求间隔控制（避免过于频繁）
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            _t.sleep(self._min_interval - elapsed)
        self._last_request_time = _t.time()

        try:
            # 使用腾讯财经API（需要交易所前缀）
            url = f"https://qt.gtimg.cn/q={self._ensure_exchange_prefix(stock_code)}"
            r = self.session.get(url, timeout=10)

            # 解析腾讯财经数据格式
            data = r.text.split('~')
            if len(data) < 45:
                return {}

            result = {
                "code": stock_code,
                "name": data[1],
                "current_price": float(data[3]) if data[3] else 0,
                "open_price": float(data[5]) if data[5] else 0,
                "high_price": float(data[33]) if data[33] else 0,
                "low_price": float(data[34]) if data[34] else 0,
                "pre_close": float(data[4]) if data[4] else 0,
                "volume": float(data[6]) if data[6] else 0,
                "amount": float(data[37]) if data[37] else 0,
                "change_pct": float(data[32]) if data[32] else 0,
                "turnover": float(data[38]) if data[38] else 0,
            }
            self._rt_cache[stock_code] = (_t.time(), result)
            return result
        except Exception as e:
            print(f"  ⚠️ {stock_code} 实时数据获取失败: {e}")
            return {}
    
    def fetch_history_data(self, stock_code: str, days: int = 60) -> pd.DataFrame:
        """获取历史行情数据"""
        try:
            # 使用百度股市通API
            url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
            params = {
                "all": "1", "isIndex": "false", "isBk": "false", "isBlock": "false",
                "isFutures": "false", "isStock": "true", "newFormat": "1",
                "group": "quotation_kline_ab", "finClientType": "pc",
                "code": stock_code, "start_time": "", "ktype": "1",
            }
            headers = {
                "Accept": "application/vnd.finance-web.v1+json",
                "Origin": "https://gushitong.baidu.com",
                "Referer": "https://gushitong.baidu.com/",
            }
            r = self.session.get(url, params=params, headers=headers, timeout=15)
            data = r.json()

            result = data.get("Result", {})
            md = result.get("newMarketData", {})
            keys = md.get("keys", [])
            rows_str = md.get("marketData", "").split(";")

            if not rows_str or len(rows_str) <= 1:
                return pd.DataFrame()

            col_map = {}
            for i, k in enumerate(keys):
                if k == 'time': col_map[i] = 'date'
                elif k == 'open': col_map[i] = 'open'
                elif k == 'close': col_map[i] = 'close'
                elif k == 'high': col_map[i] = 'high'
                elif k == 'low': col_map[i] = 'low'
                elif k == 'volume': col_map[i] = 'volume'
                elif k == 'amount': col_map[i] = 'amount'
                elif k == 'turnoverratio': col_map[i] = 'turnover'

            rows = []
            for row_str in rows_str:
                if not row_str.strip():
                    continue
                parts = row_str.split(",")
                row_dict = {}
                for idx, val in enumerate(parts):
                    col_name = col_map.get(idx)
                    if col_name:
                        try:
                            clean_val = val.lstrip('+')
                            row_dict[col_name] = float(clean_val) if clean_val else 0.0
                        except ValueError:
                            row_dict[col_name] = val
                rows.append(row_dict)

            df = pd.DataFrame(rows)
            if df.empty:
                return pd.DataFrame()

            if 'date' in df.columns:
                df['date'] = df['date'].astype(str).str[:10]
                df = df.sort_values('date').reset_index(drop=True)
                return df.tail(days + 10).reset_index(drop=True)

            return df.tail(days + 10).reset_index(drop=True)

        except Exception as e:
            print(f"  ⚠️ {stock_code} 历史数据获取失败: {e}")
        return pd.DataFrame()


# ============================================================================
# 预警规则基类
# ============================================================================

class AlertRule(ABC):
    """预警规则基类"""
    
    def __init__(self, name: str, alert_type: AlertType, 
                 alert_level: AlertLevel, enabled: bool = True):
        self.name = name
        self.alert_type = alert_type
        self.alert_level = alert_level
        self.enabled = enabled
    
    @abstractmethod
    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        """检查是否触发预警"""
        pass


# ============================================================================
# 内置预警规则
# ============================================================================

class MACDGoldenCrossRule(AlertRule):
    """MACD金叉规则"""
    
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__("MACD金叉", AlertType.MACD_GOLDEN_CROSS, AlertLevel.INFO)
        self.fast = fast
        self.slow = slow
        self.signal = signal
    
    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.slow + self.signal:
            return None
        
        close = history_df['close'].astype(float)
        
        # 计算MACD
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.signal, adjust=False).mean()
        
        # 检查金叉
        if len(dif) >= 2:
            if dif.iloc[-2] < dea.iloc[-2] and dif.iloc[-1] > dea.iloc[-1]:
                return Alert(
                    timestamp=datetime.now().isoformat(),
                    stock_code=current_data.get('code', ''),
                    stock_name=current_data.get('name', ''),
                    alert_type=self.alert_type,
                    alert_level=self.alert_level,
                    message=f"MACD金叉：DIF上穿DEA，可能开启上涨趋势",
                    current_value=float(dif.iloc[-1]),
                    threshold_value=float(dea.iloc[-1]),
                    recommendation="关注买入机会，可考虑建仓或加仓",
                    action_signal="ADD"
                )
        
        return None


class MACDDeathCrossRule(AlertRule):
    """MACD死叉规则"""
    
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__("MACD死叉", AlertType.MACD_DEATH_CROSS, AlertLevel.WARNING)
        self.fast = fast
        self.slow = slow
        self.signal = signal
    
    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.slow + self.signal:
            return None
        
        close = history_df['close'].astype(float)
        
        # 计算MACD
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.signal, adjust=False).mean()
        
        # 检查死叉
        if len(dif) >= 2:
            if dif.iloc[-2] > dea.iloc[-2] and dif.iloc[-1] < dea.iloc[-1]:
                return Alert(
                    timestamp=datetime.now().isoformat(),
                    stock_code=current_data.get('code', ''),
                    stock_name=current_data.get('name', ''),
                    alert_type=self.alert_type,
                    alert_level=self.alert_level,
                    message=f"MACD死叉：DIF下穿DEA，可能开启下跌趋势",
                    current_value=float(dif.iloc[-1]),
                    threshold_value=float(dea.iloc[-1]),
                    recommendation="注意风险，可考虑减仓或止损",
                    action_signal="SELL"
                )
        
        return None


class KDJOversoldRule(AlertRule):
    """KDJ超卖规则"""
    
    def __init__(self, n: int = 9, threshold: float = 20):
        super().__init__("KDJ超卖", AlertType.KDJ_OVERSOLD, AlertLevel.INFO)
        self.n = n
        self.threshold = threshold
    
    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.n:
            return None
        
        high = history_df['high'].astype(float)
        low = history_df['low'].astype(float)
        close = history_df['close'].astype(float)
        
        # 计算KDJ
        lowest_low = low.rolling(window=self.n, min_periods=1).min()
        highest_high = high.rolling(window=self.n, min_periods=1).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100
        
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d
        
        # 检查超卖
        if j.iloc[-1] < self.threshold and k.iloc[-1] > d.iloc[-1]:
            return Alert(
                timestamp=datetime.now().isoformat(),
                stock_code=current_data.get('code', ''),
                stock_name=current_data.get('name', ''),
                alert_type=self.alert_type,
                alert_level=self.alert_level,
                message=f"KDJ超卖：J值={j.iloc[-1]:.1f}，可能超跌反弹",
                current_value=float(j.iloc[-1]),
                threshold_value=self.threshold,
                recommendation="关注反弹机会，可考虑逢低买入",
                action_signal="BUY"
            )
        
        return None


class KDJOverboughtRule(AlertRule):
    """KDJ超买规则"""
    
    def __init__(self, n: int = 9, threshold: float = 80):
        super().__init__("KDJ超买", AlertType.KDJ_OVERBOUGHT, AlertLevel.WARNING)
        self.n = n
        self.threshold = threshold
    
    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.n:
            return None
        
        high = history_df['high'].astype(float)
        low = history_df['low'].astype(float)
        close = history_df['close'].astype(float)
        
        # 计算KDJ
        lowest_low = low.rolling(window=self.n, min_periods=1).min()
        highest_high = high.rolling(window=self.n, min_periods=1).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100
        
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d
        
        # 检查超买
        if j.iloc[-1] > self.threshold and k.iloc[-1] < d.iloc[-1]:
            return Alert(
                timestamp=datetime.now().isoformat(),
                stock_code=current_data.get('code', ''),
                stock_name=current_data.get('name', ''),
                alert_type=self.alert_type,
                alert_level=self.alert_level,
                message=f"KDJ超买：J值={j.iloc[-1]:.1f}，可能超涨回调",
                current_value=float(j.iloc[-1]),
                threshold_value=self.threshold,
                recommendation="注意回调风险，可考虑减仓",
                action_signal="REDUCE"
            )
        
        return None


class VolumeBreakoutRule(AlertRule):
    """放量突破规则"""
    
    def __init__(self, volume_ratio: float = 2.0, price_change: float = 2.0):
        super().__init__("放量突破", AlertType.VOLUME_BREAKOUT, AlertLevel.INFO)
        self.volume_ratio = volume_ratio
        self.price_change = price_change
    
    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < 20:
            return None
        
        # 计算成交量比率
        volume = history_df['volume'].astype(float)
        vol_ma5 = volume.rolling(window=5, min_periods=1).mean()
        vol_ratio = volume.iloc[-1] / vol_ma5.iloc[-1] if vol_ma5.iloc[-1] > 0 else 0
        
        # 计算价格变化
        close = history_df['close'].astype(float)
        price_change = (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100 if close.iloc[-2] > 0 else 0
        
        # 检查放量上涨
        if vol_ratio >= self.volume_ratio and price_change >= self.price_change:
            return Alert(
                timestamp=datetime.now().isoformat(),
                stock_code=current_data.get('code', ''),
                stock_name=current_data.get('name', ''),
                alert_type=self.alert_type,
                alert_level=self.alert_level,
                message=f"放量突破：成交量放大{vol_ratio:.1f}倍，价格上涨{price_change:.1f}%",
                current_value=vol_ratio,
                threshold_value=self.volume_ratio,
                recommendation="关注突破有效性，可考虑追涨",
                action_signal="ADD"
            )
        
        return None


class PriceDropRule(AlertRule):
    """大幅下跌规则"""
    
    def __init__(self, threshold: float = -5.0):
        super().__init__("大幅下跌", AlertType.PRICE_DROP, AlertLevel.CRITICAL)
        self.threshold = threshold
    
    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        # 使用实时数据
        change_pct = current_data.get('change_pct', 0)
        
        if change_pct <= self.threshold:
            return Alert(
                timestamp=datetime.now().isoformat(),
                stock_code=current_data.get('code', ''),
                stock_name=current_data.get('name', ''),
                alert_type=self.alert_type,
                alert_level=self.alert_level,
                message=f"大幅下跌：当前跌幅{change_pct:.2f}%",
                current_value=change_pct,
                threshold_value=self.threshold,
                recommendation="注意风险，检查是否需要止损",
                action_signal="SELL"
            )
        
        return None


class StopLossRule(AlertRule):
    """止损预警规则"""
    
    def __init__(self, stop_loss_pct: float = -8.0):
        super().__init__("止损预警", AlertType.STOP_LOSS, AlertLevel.CRITICAL)
        self.stop_loss_pct = stop_loss_pct
    
    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty:
            return None
        
        # 计算近期高点
        high = history_df['high'].astype(float)
        recent_high = high.tail(20).max()
        
        current_price = current_data.get('current_price', 0)
        if recent_high > 0:
            drawdown = (current_price - recent_high) / recent_high * 100
            
            if drawdown <= self.stop_loss_pct:
                return Alert(
                    timestamp=datetime.now().isoformat(),
                    stock_code=current_data.get('code', ''),
                    stock_name=current_data.get('name', ''),
                    alert_type=self.alert_type,
                    alert_level=self.alert_level,
                    message=f"止损预警：从近期高点回撤{drawdown:.2f}%",
                    current_value=drawdown,
                    threshold_value=self.stop_loss_pct,
                    recommendation="建议执行止损操作，控制亏损",
                    action_signal="SELL"
                )
        
        return None


class RSIOversoldRule(AlertRule):
    """RSI超卖规则"""

    def __init__(self, period: int = 14, threshold: float = 30):
        super().__init__("RSI超卖", AlertType.RSI_OVERSOLD, AlertLevel.INFO)
        self.period = period
        self.threshold = threshold

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.period + 5:
            return None

        close = history_df['close'].astype(float)
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)

        avg_gain = gain.ewm(com=self.period - 1, min_periods=self.period, adjust=False).mean()
        avg_loss = loss.ewm(com=self.period - 1, min_periods=self.period, adjust=False).mean()

        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - 100 / (1 + rs)

        if len(rsi) >= 2:
            if rsi.iloc[-2] <= self.threshold and rsi.iloc[-1] > self.threshold:
                return Alert(
                    timestamp=datetime.now().isoformat(),
                    stock_code=current_data.get('code', ''),
                    stock_name=current_data.get('name', ''),
                    alert_type=self.alert_type,
                    alert_level=self.alert_level,
                    message=f"RSI超卖反弹：RSI从{rsi.iloc[-2]:.1f}回升至{rsi.iloc[-1]:.1f}",
                    current_value=float(rsi.iloc[-1]),
                    threshold_value=self.threshold,
                    recommendation="关注超卖反弹机会，可考虑逢低买入",
                    action_signal="BUY"
                )

        return None


class RSIOverboughtRule(AlertRule):
    """RSI超买规则"""

    def __init__(self, period: int = 14, threshold: float = 70):
        super().__init__("RSI超买", AlertType.RSI_OVERBOUGHT, AlertLevel.WARNING)
        self.period = period
        self.threshold = threshold

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.period + 5:
            return None

        close = history_df['close'].astype(float)
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)

        avg_gain = gain.ewm(com=self.period - 1, min_periods=self.period, adjust=False).mean()
        avg_loss = loss.ewm(com=self.period - 1, min_periods=self.period, adjust=False).mean()

        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - 100 / (1 + rs)

        if len(rsi) >= 2:
            if rsi.iloc[-2] >= self.threshold and rsi.iloc[-1] < self.threshold:
                return Alert(
                    timestamp=datetime.now().isoformat(),
                    stock_code=current_data.get('code', ''),
                    stock_name=current_data.get('name', ''),
                    alert_type=self.alert_type,
                    alert_level=self.alert_level,
                    message=f"RSI超买回落：RSI从{rsi.iloc[-2]:.1f}回落至{rsi.iloc[-1]:.1f}",
                    current_value=float(rsi.iloc[-1]),
                    threshold_value=self.threshold,
                    recommendation="注意超买回调风险，可考虑减仓",
                    action_signal="REDUCE"
                )

        return None


class HighVolatilityRule(AlertRule):
    """高波动预警规则"""

    def __init__(self, volatility_threshold: float = 3.0):
        super().__init__("高波动预警", AlertType.HIGH_VOLATILITY, AlertLevel.WARNING)
        self.volatility_threshold = volatility_threshold

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < 20:
            return None

        close = history_df['close'].astype(float)
        returns = close.pct_change().dropna()

        if len(returns) >= 20:
            daily_volatility = returns.tail(20).std()
            annualized_volatility = daily_volatility * np.sqrt(252) * 100

            if annualized_volatility > self.volatility_threshold * 100:
                return Alert(
                    timestamp=datetime.now().isoformat(),
                    stock_code=current_data.get('code', ''),
                    stock_name=current_data.get('name', ''),
                    alert_type=self.alert_type,
                    alert_level=self.alert_level,
                    message=f"高波动预警：年化波动率{annualized_volatility:.1f}%",
                    current_value=annualized_volatility,
                    threshold_value=self.volatility_threshold * 100,
                    recommendation="注意风险控制，可考虑降低仓位",
                    action_signal="REDUCE"
                )

        return None


class MAGoldenCrossRule(AlertRule):
    """均线金叉规则 - 短期均线上穿长期均线"""

    def __init__(self, short: int = 5, long: int = 20):
        super().__init__("均线金叉", AlertType.TREND_REVERSAL, AlertLevel.INFO)
        self.short = short
        self.long = long

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.long + 2:
            return None

        close = history_df['close'].astype(float)
        ma_short = close.rolling(window=self.short, min_periods=1).mean()
        ma_long = close.rolling(window=self.long, min_periods=1).mean()

        if len(ma_short) >= 2:
            if ma_short.iloc[-2] < ma_long.iloc[-2] and ma_short.iloc[-1] > ma_long.iloc[-1]:
                return Alert(
                    timestamp=datetime.now().isoformat(),
                    stock_code=current_data.get('code', ''),
                    stock_name=current_data.get('name', ''),
                    alert_type=self.alert_type,
                    alert_level=self.alert_level,
                    message=f"均线金叉：MA{self.short}上穿MA{self.long}，趋势转强",
                    current_value=float(ma_short.iloc[-1]),
                    threshold_value=float(ma_long.iloc[-1]),
                    recommendation="趋势确认信号，可考虑加仓或建仓",
                    action_signal="ADD"
                )

        return None


class MADeathCrossRule(AlertRule):
    """均线死叉规则 - 短期均线下穿长期均线"""

    def __init__(self, short: int = 5, long: int = 20):
        super().__init__("均线死叉", AlertType.TREND_REVERSAL, AlertLevel.WARNING)
        self.short = short
        self.long = long

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.long + 2:
            return None

        close = history_df['close'].astype(float)
        ma_short = close.rolling(window=self.short, min_periods=1).mean()
        ma_long = close.rolling(window=self.long, min_periods=1).mean()

        if len(ma_short) >= 2:
            if ma_short.iloc[-2] > ma_long.iloc[-2] and ma_short.iloc[-1] < ma_long.iloc[-1]:
                return Alert(
                    timestamp=datetime.now().isoformat(),
                    stock_code=current_data.get('code', ''),
                    stock_name=current_data.get('name', ''),
                    alert_type=self.alert_type,
                    alert_level=self.alert_level,
                    message=f"均线死叉：MA{self.short}下穿MA{self.long}，趋势转弱",
                    current_value=float(ma_short.iloc[-1]),
                    threshold_value=float(ma_long.iloc[-1]),
                    recommendation="趋势走弱信号，可考虑减仓或止损",
                    action_signal="SELL"
                )

        return None


class BollingerLowerBounceRule(AlertRule):
    """布林带下轨反弹规则"""

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        super().__init__("布林带下轨反弹", AlertType.SUPPORT_BREAK, AlertLevel.INFO)
        self.period = period
        self.std_dev = std_dev

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.period + 2:
            return None

        close = history_df['close'].astype(float)
        ma = close.rolling(window=self.period, min_periods=1).mean()
        std = close.rolling(window=self.period, min_periods=1).std()
        lower_band = ma - self.std_dev * std

        if len(close) >= 2:
            prev_close = close.iloc[-2]
            curr_close = close.iloc[-1]
            prev_lower = lower_band.iloc[-2]
            curr_lower = lower_band.iloc[-1]

            if prev_close <= prev_lower and curr_close > curr_lower:
                return Alert(
                    timestamp=datetime.now().isoformat(),
                    stock_code=current_data.get('code', ''),
                    stock_name=current_data.get('name', ''),
                    alert_type=self.alert_type,
                    alert_level=self.alert_level,
                    message=f"布林带下轨反弹：价格从下轨{curr_lower:.2f}回升至{curr_close:.2f}",
                    current_value=float(curr_close),
                    threshold_value=float(curr_lower),
                    recommendation="超跌区域反弹信号，可考虑逢低买入",
                    action_signal="BUY"
                )

        return None


class BollingerUpperReversalRule(AlertRule):
    """布林带上轨回落规则"""

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        super().__init__("布林带上轨回落", AlertType.RESISTANCE_BREAK, AlertLevel.WARNING)
        self.period = period
        self.std_dev = std_dev

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.period + 2:
            return None

        close = history_df['close'].astype(float)
        ma = close.rolling(window=self.period, min_periods=1).mean()
        std = close.rolling(window=self.period, min_periods=1).std()
        upper_band = ma + self.std_dev * std

        if len(close) >= 2:
            prev_close = close.iloc[-2]
            curr_close = close.iloc[-1]
            prev_upper = upper_band.iloc[-2]
            curr_upper = upper_band.iloc[-1]

            if prev_close >= prev_upper and curr_close < curr_upper:
                return Alert(
                    timestamp=datetime.now().isoformat(),
                    stock_code=current_data.get('code', ''),
                    stock_name=current_data.get('name', ''),
                    alert_type=self.alert_type,
                    alert_level=self.alert_level,
                    message=f"布林带上轨回落：价格从上轨{prev_upper:.2f}回落至{curr_close:.2f}",
                    current_value=float(curr_close),
                    threshold_value=float(curr_upper),
                    recommendation="超涨区域回调信号，可考虑减仓",
                    action_signal="REDUCE"
                )

        return None


class BreakoutHighRule(AlertRule):
    """突破N日新高规则"""

    def __init__(self, days: int = 20):
        super().__init__("突破N日新高", AlertType.PRICE_BREAKOUT, AlertLevel.INFO)
        self.days = days

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.days + 1:
            return None

        high = history_df['high'].astype(float)
        close = history_df['close'].astype(float)

        recent_high = high.iloc[-self.days - 1:-1].max()
        curr_close = close.iloc[-1]

        if curr_close > recent_high:
            return Alert(
                timestamp=datetime.now().isoformat(),
                stock_code=current_data.get('code', ''),
                stock_name=current_data.get('name', ''),
                alert_type=self.alert_type,
                alert_level=self.alert_level,
                message=f"突破{self.days}日新高：收盘价{curr_close:.2f}突破近期高点{recent_high:.2f}",
                current_value=float(curr_close),
                threshold_value=float(recent_high),
                recommendation="强势突破信号，可考虑追涨加仓",
                action_signal="ADD"
            )

        return None


class BreakdownLowRule(AlertRule):
    """跌破N日新低规则"""

    def __init__(self, days: int = 20):
        super().__init__("跌破N日新低", AlertType.SUPPORT_BREAK, AlertLevel.WARNING)
        self.days = days

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        if history_df.empty or len(history_df) < self.days + 1:
            return None

        low = history_df['low'].astype(float)
        close = history_df['close'].astype(float)

        recent_low = low.iloc[-self.days - 1:-1].min()
        curr_close = close.iloc[-1]

        if curr_close < recent_low:
            return Alert(
                timestamp=datetime.now().isoformat(),
                stock_code=current_data.get('code', ''),
                stock_name=current_data.get('name', ''),
                alert_type=self.alert_type,
                alert_level=self.alert_level,
                message=f"跌破{self.days}日新低：收盘价{curr_close:.2f}跌破近期低点{recent_low:.2f}",
                current_value=float(curr_close),
                threshold_value=float(recent_low),
                recommendation="破位下行信号，可考虑减仓或止损",
                action_signal="SELL"
            )

        return None


# ============================================================================
# 持仓感知规则（需要 holding_context）
# ============================================================================

# 不同持仓类型的止损/止盈阈值
POSITION_THRESHOLDS = {
    "short": {"stop_loss": -5, "take_profit": 10, "trailing_stop": -4},
    "mid":   {"stop_loss": -8, "take_profit": 18, "trailing_stop": -6},
    "long":  {"stop_loss": -12, "take_profit": 30, "trailing_stop": -8},
}


class PositionStopLossRule(AlertRule):
    """基于成本价的止损预警（按持仓类型动态阈值）"""

    def __init__(self):
        super().__init__("持仓成本止损", AlertType.POSITION_STOP_LOSS, AlertLevel.CRITICAL)

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        ctx = current_data.get("holding_context")
        if not ctx or not ctx.get("cost_price"):
            return None
        cost_price = ctx["cost_price"]
        current_price = current_data.get("current_price", 0)
        if current_price <= 0 or cost_price <= 0:
            return None
        position_type = ctx.get("position_type", "short")
        threshold = POSITION_THRESHOLDS.get(position_type, POSITION_THRESHOLDS["short"])
        loss_pct = (current_price - cost_price) / cost_price * 100

        if loss_pct <= threshold["stop_loss"]:
            return Alert(
                timestamp=datetime.now().isoformat(),
                stock_code=current_data.get("code", ""),
                stock_name=current_data.get("name", ""),
                alert_type=self.alert_type,
                alert_level=self.alert_level,
                message=(
                    f"成本止损：现价{current_price:.2f} vs 成本{cost_price:.2f}，"
                    f"浮亏{loss_pct:.1f}%触及{position_type}线止损位{threshold['stop_loss']}%"
                ),
                current_value=loss_pct,
                threshold_value=float(threshold["stop_loss"]),
                recommendation=(
                    f"已亏损{abs(loss_pct):.1f}%，"
                    f"{'短线建议立即止损' if position_type == 'short' else '建议评估是否继续持有'}"
                ),
                action_signal="SELL",
                metadata={"cost_price": cost_price, "loss_pct": round(loss_pct, 2), "position_type": position_type},
            )
        return None


class PositionTakeProfitRule(AlertRule):
    """基于成本价的止盈预警（按持仓类型动态阈值）"""

    def __init__(self):
        super().__init__("持仓成本止盈", AlertType.POSITION_TAKE_PROFIT, AlertLevel.INFO)

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        ctx = current_data.get("holding_context")
        if not ctx or not ctx.get("cost_price"):
            return None
        cost_price = ctx["cost_price"]
        current_price = current_data.get("current_price", 0)
        if current_price <= 0 or cost_price <= 0:
            return None
        position_type = ctx.get("position_type", "short")
        threshold = POSITION_THRESHOLDS.get(position_type, POSITION_THRESHOLDS["short"])
        profit_pct = (current_price - cost_price) / cost_price * 100

        if profit_pct >= threshold["take_profit"]:
            return Alert(
                timestamp=datetime.now().isoformat(),
                stock_code=current_data.get("code", ""),
                stock_name=current_data.get("name", ""),
                alert_type=self.alert_type,
                alert_level=self.alert_level,
                message=(
                    f"持仓止盈：现价{current_price:.2f} vs 成本{cost_price:.2f}，"
                    f"浮盈{profit_pct:.1f}%达到{position_type}线止盈位{threshold['take_profit']}%"
                ),
                current_value=profit_pct,
                threshold_value=float(threshold["take_profit"]),
                recommendation=(
                    f"已盈利{profit_pct:.1f}%，"
                    f"{'短线建议锁定利润' if position_type == 'short' else '中长线可考虑部分减仓'}"
                ),
                action_signal="REDUCE",
                metadata={"cost_price": cost_price, "profit_pct": round(profit_pct, 2), "position_type": position_type},
            )
        return None


class PositionTrailingStopRule(AlertRule):
    """移动止损：从最高盈利回撤超过阈值"""

    def __init__(self):
        super().__init__("移动止损", AlertType.POSITION_TRAILING_STOP, AlertLevel.CRITICAL)

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        ctx = current_data.get("holding_context")
        if not ctx or not ctx.get("cost_price"):
            return None
        cost_price = ctx["cost_price"]
        current_price = current_data.get("current_price", 0)
        if current_price <= 0 or cost_price <= 0:
            return None
        position_type = ctx.get("position_type", "short")
        threshold = POSITION_THRESHOLDS.get(position_type, POSITION_THRESHOLDS["short"])

        profit_pct = (current_price - cost_price) / cost_price * 100
        max_profit = ctx.get("max_profit_ratio", 0)

        if max_profit < 10:
            return None
        drawdown = profit_pct - max_profit

        if drawdown <= threshold["trailing_stop"]:
            return Alert(
                timestamp=datetime.now().isoformat(),
                stock_code=current_data.get("code", ""),
                stock_name=current_data.get("name", ""),
                alert_type=self.alert_type,
                alert_level=self.alert_level,
                message=(
                    f"移动止损：当前盈利{profit_pct:.1f}%，从最高{max_profit:.1f}%回撤{drawdown:.1f}%，"
                    f"超过{position_type}线阈值{threshold['trailing_stop']}%"
                ),
                current_value=drawdown,
                threshold_value=float(threshold["trailing_stop"]),
                recommendation="利润大幅回吐，建议立即止盈锁利",
                action_signal="SELL",
                metadata={"cost_price": cost_price, "profit_pct": round(profit_pct, 2), "max_profit": round(max_profit, 2), "drawdown": round(drawdown, 2)},
            )
        return None


class PositionCostPressureRule(AlertRule):
    """成本压力位：价格在成本价附近（±3%），形成压力/支撑"""

    def __init__(self):
        super().__init__("成本压力位", AlertType.POSITION_COST_PRESSURE, AlertLevel.INFO)

    def check(self, current_data: Dict, history_df: pd.DataFrame) -> Optional[Alert]:
        ctx = current_data.get("holding_context")
        if not ctx or not ctx.get("cost_price"):
            return None
        cost_price = ctx["cost_price"]
        current_price = current_data.get("current_price", 0)
        if current_price <= 0 or cost_price <= 0:
            return None

        deviation = (current_price - cost_price) / cost_price * 100
        if abs(deviation) > 3:
            return None

        if deviation >= 0:
            msg = f"现价{current_price:.2f}接近成本价{cost_price:.2f}（上方{deviation:.1f}%），注意成本压力位"
            rec = "上方套牢盘抛压较重，突破需放量配合"
            signal = "HOLD"
        else:
            msg = f"现价{current_price:.2f}接近成本价{cost_price:.2f}（下方{abs(deviation):.1f}%），关注成本支撑"
            rec = "成本价附近有支撑，若跌破需关注止损"
            signal = "HOLD"

        return Alert(
            timestamp=datetime.now().isoformat(),
            stock_code=current_data.get("code", ""),
            stock_name=current_data.get("name", ""),
            alert_type=self.alert_type,
            alert_level=self.alert_level,
            message=msg,
            current_value=deviation,
            threshold_value=0.0,
            recommendation=rec,
            action_signal=signal,
            metadata={"cost_price": cost_price, "deviation_pct": round(deviation, 2)},
        )


# ============================================================================
# 规则管理器
# ============================================================================

class RuleManager:
    """规则管理器"""

    _rules: Dict[str, type] = {
        "macd_golden_cross": MACDGoldenCrossRule,
        "macd_death_cross": MACDDeathCrossRule,
        "kdj_oversold": KDJOversoldRule,
        "kdj_overbought": KDJOverboughtRule,
        "rsi_oversold": RSIOversoldRule,
        "rsi_overbought": RSIOverboughtRule,
        "volume_breakout": VolumeBreakoutRule,
        "price_drop": PriceDropRule,
        "stop_loss": StopLossRule,
        "high_volatility": HighVolatilityRule,
        "ma_golden_cross": MAGoldenCrossRule,
        "ma_death_cross": MADeathCrossRule,
        "bollinger_lower_bounce": BollingerLowerBounceRule,
        "bollinger_upper_reversal": BollingerUpperReversalRule,
        "breakout_high": BreakoutHighRule,
        "breakdown_low": BreakdownLowRule,
        "position_stop_loss": PositionStopLossRule,
        "position_take_profit": PositionTakeProfitRule,
        "position_trailing_stop": PositionTrailingStopRule,
        "position_cost_pressure": PositionCostPressureRule,
    }
    
    @classmethod
    def register(cls, name: str, rule_class: type):
        """注册新规则"""
        cls._rules[name] = rule_class
    
    @classmethod
    def get(cls, name: str, **kwargs) -> Optional[AlertRule]:
        """获取规则实例"""
        if name in cls._rules:
            return cls._rules[name](**kwargs)
        return None
    
    @classmethod
    def list_rules(cls) -> List[str]:
        """列出所有可用规则"""
        return list(cls._rules.keys())
    
    @classmethod
    def get_default_rules(cls) -> List[AlertRule]:
        """获取默认规则集"""
        return [
            MACDGoldenCrossRule(),
            MACDDeathCrossRule(),
            KDJOversoldRule(),
            KDJOverboughtRule(),
            RSIOversoldRule(),
            RSIOverboughtRule(),
            VolumeBreakoutRule(),
            PriceDropRule(),
            StopLossRule(),
            HighVolatilityRule(),
            MAGoldenCrossRule(),
            MADeathCrossRule(),
            BollingerLowerBounceRule(),
            BollingerUpperReversalRule(),
            BreakoutHighRule(),
            BreakdownLowRule(),
            PositionStopLossRule(),
            PositionTakeProfitRule(),
            PositionTrailingStopRule(),
            PositionCostPressureRule(),
        ]


# ============================================================================
# 预警去重/冷却机制
# ============================================================================

class AlertDeduplicator:
    """预警去重和冷却管理器"""

    def __init__(self, cooldown_minutes: int = 30):
        self.cooldown_minutes = cooldown_minutes
        self._history: Dict[str, float] = {}

    def should_alert(self, alert: Alert) -> bool:
        """检查是否应该发送预警（按股票+操作信号去重，避免同一只股票短时间内重复提醒）"""
        key = f"{alert.stock_code}:{alert.action_signal}"
        now = time.time()
        last_time = self._history.get(key, 0)

        if now - last_time < self.cooldown_minutes * 60:
            return False

        self._history[key] = now
        return True

    def get_cooldown_status(self) -> Dict[str, Any]:
        """获取冷却状态"""
        now = time.time()
        result = {}
        for key, last_time in self._history.items():
            remaining = max(0, self.cooldown_minutes - (now - last_time) / 60)
            if remaining > 0:
                result[key] = {"remaining_minutes": round(remaining, 1)}
        return result


# ============================================================================
# 通知器
# ============================================================================

class AlertNotifier(ABC):
    """通知器基类"""
    
    @abstractmethod
    def notify(self, alert: Alert):
        """发送通知"""
        pass


class ConsoleNotifier(AlertNotifier):
    """控制台通知器"""
    
    def notify(self, alert: Alert):
        """打印到控制台"""
        level_colors = {
            AlertLevel.INFO: "\033[94m",      # 蓝色
            AlertLevel.WARNING: "\033[93m",    # 黄色
            AlertLevel.CRITICAL: "\033[91m",   # 红色
            AlertLevel.EMERGENCY: "\033[95m",  # 紫色
        }
        reset_color = "\033[0m"
        
        color = level_colors.get(alert.alert_level, "")
        
        print(f"\n{color}{'='*60}")
        print(f"🚨 预警通知 - {alert.alert_level.value}")
        print(f"{'='*60}")
        print(f"时间: {alert.timestamp}")
        print(f"股票: {alert.stock_name} ({alert.stock_code})")
        print(f"类型: {alert.alert_type.value}")
        print(f"消息: {alert.message}")
        print(f"建议: {alert.recommendation}")
        print(f"{'='*60}{reset_color}")


class LogNotifier(AlertNotifier):
    """日志通知器"""
    
    def __init__(self, log_dir: str = "./alerts"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def notify(self, alert: Alert):
        """写入日志文件"""
        log_file = self.log_dir / f"alerts_{datetime.now().strftime('%Y%m%d')}.json"
        
        # 读取现有日志
        alerts = []
        if log_file.exists():
            with open(log_file, 'r', encoding='utf-8') as f:
                alerts = json.load(f)
        
        # 添加新预警
        alerts.append(asdict(alert))
        
        # 写入日志
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)


class CompositeNotifier(AlertNotifier):
    """组合通知器"""
    
    def __init__(self, notifiers: List[AlertNotifier]):
        self.notifiers = notifiers
    
    def notify(self, alert: Alert):
        """发送给所有通知器"""
        for notifier in self.notifiers:
            try:
                notifier.notify(alert)
            except Exception as e:
                print(f"  ⚠️ 通知发送失败: {e}")


# ============================================================================
# 预警监控器
# ============================================================================

class AlertMonitor:
    """预警监控器"""

    def __init__(self, rules: Optional[List[AlertRule]] = None,
                 notifier: Optional[AlertNotifier] = None,
                 cooldown_minutes: int = 30):
        self.rules = rules or RuleManager.get_default_rules()
        self.notifier = notifier or CompositeNotifier([
            ConsoleNotifier(),
            LogNotifier()
        ])
        self.data_fetcher = AlertDataFetcher()
        self.alert_history: List[Alert] = []
        self.deduplicator = AlertDeduplicator(cooldown_minutes=cooldown_minutes)
    
    def monitor_stock(self, stock_code: str, rules: Optional[List[str]] = None, holding_context: Optional[Dict] = None) -> List[Alert]:
        """监控单只股票"""
        alerts = []
        active_rules = self.rules
        if rules is not None:
            all_rules = {r.name: r for r in RuleManager.get_default_rules()}
            active_rules = [all_rules[r] for r in rules if r in all_rules] or self.rules

        # 持仓股：排除与成本判断重复的通用规则
        if holding_context:
            active_rules = [r for r in active_rules if r.name not in ('stop_loss', 'price_drop')]

        print(f"\n📊 监控 {stock_code}...")

        current_data = self.data_fetcher.fetch_realtime_data(stock_code)
        if not current_data:
            print(f"  ⚠️ 无法获取 {stock_code} 实时数据")
            return alerts

        if holding_context:
            current_data["holding_context"] = holding_context

        history_df = self.data_fetcher.fetch_history_data(stock_code, days=60)

        for rule in active_rules:
            if not rule.enabled:
                continue

            try:
                alert = rule.check(current_data, history_df)
                if alert:
                    if self.deduplicator.should_alert(alert):
                        alerts.append(alert)
                        self.alert_history.append(alert)
                        self.notifier.notify(alert)
                    else:
                        print(f"  ⏸️ {rule.name} 预警在冷却期内，跳过")
            except Exception as e:
                print(f"  ⚠️ 规则 {rule.name} 检查失败: {e}")

        return alerts
    
    def monitor_pool(self, stock_codes: List[str], rules: Optional[List[str]] = None, holding_context_map: Optional[Dict[str, Dict]] = None) -> Dict[str, List[Alert]]:
        """监控股票池（并行获取数据，大幅提速）"""
        import concurrent.futures

        all_alerts = {}
        print(f"\n📊 监控股票池: {len(stock_codes)} 只股票")

        def _check_one(code):
            ctx = (holding_context_map or {}).get(code)
            alerts = self.monitor_stock(code, rules, holding_context=ctx)
            return code, alerts

        # 降低并发数避免API限流（2-3个worker足够）
        max_workers = min(3, len(stock_codes) or 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_check_one, c): c for c in stock_codes}
            for future in concurrent.futures.as_completed(futures):
                code, alerts = future.result()
                if alerts:
                    all_alerts[code] = alerts

        return all_alerts
    
    def run_continuous_monitor(self, stock_codes: List[str], 
                              duration_minutes: int = 60,
                              check_interval: int = 60):
        """持续监控"""
        print("=" * 60)
        print("🚨 智能预警系统 - 持续监控模式")
        print("=" * 60)
        print(f"   监控股票: {len(stock_codes)} 只")
        print(f"   监控时长: {duration_minutes} 分钟")
        print(f"   检查间隔: {check_interval} 秒")
        print("=" * 60)
        
        start_time = time.time()
        end_time = start_time + duration_minutes * 60
        
        check_count = 0
        total_alerts = 0
        
        while time.time() < end_time:
            check_count += 1
            print(f"\n🔄 第 {check_count} 次检查 ({datetime.now().strftime('%H:%M:%S')})")
            
            all_alerts = self.monitor_pool(stock_codes)
            
            # 统计预警数量
            alert_count = sum(len(alerts) for alerts in all_alerts.values())
            total_alerts += alert_count
            
            if alert_count > 0:
                print(f"  ✅ 本次发现 {alert_count} 个预警")
            
            # 等待下次检查
            remaining_time = end_time - time.time()
            if remaining_time > check_interval:
                print(f"  ⏳ 等待 {check_interval} 秒后进行下次检查...")
                time.sleep(check_interval)
            else:
                break
        
        print("\n" + "=" * 60)
        print("📊 监控结束")
        print(f"   总检查次数: {check_count}")
        print(f"   总预警数量: {total_alerts}")
        print("=" * 60)
    
    def get_alert_history(self, stock_code: Optional[str] = None,
                         alert_type: Optional[AlertType] = None) -> List[Alert]:
        """获取预警历史"""
        filtered = self.alert_history
        
        if stock_code:
            filtered = [a for a in filtered if a.stock_code == stock_code]
        
        if alert_type:
            filtered = [a for a in filtered if a.alert_type == alert_type]
        
        return filtered


# ============================================================================
# 主入口
# ============================================================================

class SmartAlertSystem:
    """智能预警系统 - 主入口"""
    
    def __init__(self):
        self.monitor = AlertMonitor()
    
    def monitor_stock(self, stock_code: str, 
                     rules: Optional[List[str]] = None,
                     holding_context: Optional[Dict] = None) -> List[Alert]:
        """监控单只股票"""
        print("=" * 60)
        print("🚨 智能预警系统")
        print("=" * 60)
        print(f"   股票代码: {stock_code}")
        if rules:
            print(f"   启用规则: {', '.join(rules)}")
        print("=" * 60)
        
        # 如果指定了规则，使用指定规则
        if rules:
            self.monitor.rules = []
            for rule_name in rules:
                rule = RuleManager.get(rule_name)
                if rule:
                    self.monitor.rules.append(rule)
        
        # 运行监控
        alerts = self.monitor.monitor_stock(stock_code, holding_context=holding_context)
        
        # 打印摘要
        self._print_summary(stock_code, alerts)
        
        return alerts
    
    def monitor_pool(self, stock_codes: List[str],
                    rules: Optional[List[str]] = None,
                    holding_context_map: Optional[Dict[str, Dict]] = None) -> Dict[str, List[Alert]]:
        """监控股票池"""
        print("=" * 60)
        print("🚨 智能预警系统 - 批量监控")
        print("=" * 60)
        print(f"   监控股票: {len(stock_codes)} 只")
        print("=" * 60)
        
        # 如果指定了规则，使用指定规则
        if rules:
            self.monitor.rules = []
            for rule_name in rules:
                rule = RuleManager.get(rule_name)
                if rule:
                    self.monitor.rules.append(rule)
        
        # 运行监控
        all_alerts = self.monitor.monitor_pool(stock_codes, holding_context_map=holding_context_map)
        
        # 打印摘要
        self._print_pool_summary(all_alerts)
        
        return all_alerts
    
    def run_continuous(self, stock_codes: List[str],
                      duration_minutes: int = 60,
                      check_interval: int = 60):
        """持续监控"""
        self.monitor.run_continuous_monitor(
            stock_codes, duration_minutes, check_interval
        )
    
    def list_rules(self):
        """列出可用规则"""
        print("\n📋 可用预警规则:")
        for name in RuleManager.list_rules():
            print(f"   - {name}")
    
    def _print_summary(self, stock_code: str, alerts: List[Alert]):
        """打印监控摘要"""
        print("\n" + "=" * 60)
        print("📊 监控结果摘要")
        print("=" * 60)
        print(f"   股票: {stock_code}")
        print(f"   预警数量: {len(alerts)}")
        
        if alerts:
            print("\n   预警列表:")
            for i, alert in enumerate(alerts, 1):
                print(f"   {i}. [{alert.alert_level.value}] {alert.alert_type.value}")
                print(f"      {alert.message}")
                print(f"      建议: {alert.recommendation}")
        else:
            print("   ✅ 未发现预警")
        
        print("=" * 60)
    
    def _print_pool_summary(self, all_alerts: Dict[str, List[Alert]]):
        """打印股票池监控摘要"""
        print("\n" + "=" * 60)
        print("📊 批量监控结果摘要")
        print("=" * 60)
        
        total_alerts = sum(len(alerts) for alerts in all_alerts.values())
        print(f"   总预警数量: {total_alerts}")
        
        if all_alerts:
            print("\n   各股票预警:")
            for stock_code, alerts in all_alerts.items():
                print(f"   {stock_code}: {len(alerts)} 个预警")
                for alert in alerts:
                    print(f"     - [{alert.alert_level.value}] {alert.alert_type.value}")
        else:
            print("   ✅ 所有股票均未发现预警")
        
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="A股智能预警系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 监控单只股票
  python smart_alert.py monitor --stock 600519

  # 监控股票池
  python smart_alert.py monitor --pool "600519,300750,002594"

  # 使用指定规则
  python smart_alert.py monitor --stock 600519 --rules "macd_golden_cross,kdj_oversold"

  # 持续监控
  python smart_alert.py continuous --pool "600519,300750" --duration 60

  # 列出可用规则
  python smart_alert.py list
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # monitor子命令
    monitor_parser = subparsers.add_parser("monitor", help="监控股票")
    monitor_parser.add_argument("--stock", type=str, help="单只股票代码")
    monitor_parser.add_argument("--pool", type=str, help="股票池，逗号分隔")
    monitor_parser.add_argument("--rules", type=str, help="启用规则，逗号分隔")
    
    # continuous子命令
    continuous_parser = subparsers.add_parser("continuous", help="持续监控")
    continuous_parser.add_argument("--pool", type=str, required=True, help="股票池，逗号分隔")
    continuous_parser.add_argument("--duration", type=int, default=60, help="监控时长（分钟）")
    continuous_parser.add_argument("--interval", type=int, default=60, help="检查间隔（秒）")
    
    # list子命令
    list_parser = subparsers.add_parser("list", help="列出可用规则")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    system = SmartAlertSystem()
    
    if args.command == "monitor":
        # 解析股票代码
        if args.stock:
            stock_codes = [args.stock]
        elif args.pool:
            stock_codes = [s.strip() for s in args.pool.split(",")]
        else:
            print("❌ 请指定 --stock 或 --pool")
            sys.exit(1)
        
        # 解析规则
        rules = None
        if args.rules:
            rules = [r.strip() for r in args.rules.split(",")]
        
        # 运行监控
        if len(stock_codes) == 1:
            system.monitor_stock(stock_codes[0], rules)
        else:
            system.monitor_pool(stock_codes, rules)
    
    elif args.command == "continuous":
        stock_codes = [s.strip() for s in args.pool.split(",")]
        system.run_continuous(stock_codes, args.duration, args.interval)
    
    elif args.command == "list":
        system.list_rules()


if __name__ == "__main__":
    main()
