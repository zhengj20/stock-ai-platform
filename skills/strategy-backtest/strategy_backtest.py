#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股策略回测系统 (Strategy Backtesting System)
=============================================
提供完整的策略回测功能包括
1. 历史数据获取和处理
2. 策略信号生成
3. 交易模拟支持手续费滑点
4. 绩效评估夏普比率最大回撤胜率等
5. 风险分析
6. 可视化报告生成

用法:
    # 回测单个策略
    python strategy_backtest.py backtest --strategy macd --start 2023-01-01 --end 2024-01-01
    
    # 回测多个策略对比
    python strategy_backtest.py compare --strategies "macd,kdj,rsi" --start 2023-01-01
    
    # 自定义参数回测
    python strategy_backtest.py backtest --strategy macd --params '{"fast": 12, "slow": 26, "signal": 9}'

依赖: pip install pandas numpy matplotlib requests

作者: Hermes Agent
版本: 1.0.0
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, asdict
from enum import Enum

import pandas as pd
import numpy as np

# ============================================================================
# 数据结构定义
# ============================================================================

class SignalType(Enum):
    """交易信号类型"""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    """交易信号"""
    date: str
    stock_code: str
    signal_type: SignalType
    price: float
    reason: str
    confidence: float = 1.0


@dataclass
class Trade:
    """交易记录"""
    date: str
    stock_code: str
    direction: str  # BUY or SELL
    price: float
    shares: int
    amount: float
    commission: float
    slippage: float
    reason: str


@dataclass
class Position:
    """持仓信息"""
    stock_code: str
    shares: int
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    max_drawdown_duration: int
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_holding_days: float
    calmar_ratio: float
    sortino_ratio: float
    volatility: float
    trades: List[Dict]
    equity_curve: List[Dict]
    monthly_returns: List[Dict]


# ============================================================================
# 数据获取模块
# ============================================================================

class BacktestDataFetcher:
    """回测数据获取器 — 统一使用 pytdx 通达信数据源"""

    @staticmethod
    def _get_market(code: str) -> int:
        """根据股票代码判断市场: 1=沪市, 0=深市"""
        if code.startswith(('6', '5', '9', '11', '13')):
            return 1
        return 0

    def fetch_stock_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票历史K线数据（多源回退链：pytdx → 百度 → 同花顺 → 腾讯 → 新浪）

        2026-09 实测：本机房 IP 下 pytdx 数据层被风控（连接通但取数为空）、新浪被限流
        (HTTP 456)、腾讯 ifzq 被 WAF(501)——本模块原「pytdx → 新浪」两级回退实测返回
        空表。优先复用后端 app.core.pytdx_source 的共享回退链（百度/同花顺仍可用），
        全部失败再走本模块独立的新浪兜底。
        """
        # 计算需要获取的K线数量（按交易日估算）
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        total_days = (end_dt - start_dt).days + 60  # 多取60天作为缓冲
        count = max(int(total_days * 1.5), 300)  # 交易日约为自然日的2/3

        rows = self._fetch_kline_shared(stock_code, count)
        if not rows:
            # 共享链失败 → 本模块独立兜底（先 pytdx 再新浪）
            print(f"  [提示] {stock_code} 共享回退链无数据，尝试模块内 pytdx/新浪")
            rows = self._fetch_kline_pytdx(stock_code, count)
        if not rows:
            print(f"  [提示] {stock_code} pytdx 无数据，尝试新浪 HTTP 回退")
            rows = self._fetch_kline_sina(stock_code, count)
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df.sort_values('date').reset_index(drop=True)
        df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
        return df.reset_index(drop=True)

    def _fetch_kline_shared(self, stock_code: str, count: int) -> List[Dict]:
        """复用后端共享 K线回退链（pytdx 熔断自动走 HTTP 多源）。"""
        try:
            from app.core.pytdx_source import pytdx_data
            return pytdx_data.get_kline(stock_code, period=4, count=count) or []
        except Exception as e:
            print(f"  [警告] {stock_code} 共享K线链失败: {e}")
            return []

    def _fetch_kline_pytdx(self, stock_code: str, count: int) -> List[Dict]:
        """pytdx 日K线。返回 list[dict]，失败/被风控返回空列表。"""
        try:
            from pytdx.hq import TdxHq_API

            servers = [
                ('218.75.126.9', 7709),
                ('115.238.56.198', 7709),
                ('124.160.88.183', 7709),
                ('60.12.136.250', 7709),
            ]

            api = TdxHq_API()
            connected = False
            for host, port in servers:
                try:
                    if api.connect(host, port):
                        connected = True
                        break
                except Exception:
                    continue
            if not connected:
                return []

            market = self._get_market(stock_code)
            try:
                result = api.get_security_bars(4, market, stock_code, 0, count)
            finally:
                try:
                    api.disconnect()
                except Exception:
                    pass
            if not result:
                return []

            rows = []
            for k in result:
                dt = k.get('datetime', '')
                if isinstance(dt, tuple) and len(dt) >= 4:
                    date_str = f"{dt[0]}-{dt[1]:02d}-{dt[2]:02d}"
                elif isinstance(dt, str):
                    parts = dt.split(' ')
                    date_str = parts[0] if parts else dt
                else:
                    date_str = str(dt)[:10]

                rows.append({
                    'date': date_str,
                    'open': float(k.get('open', 0)),
                    'high': float(k.get('high', 0)),
                    'low': float(k.get('low', 0)),
                    'close': float(k.get('close', 0)),
                    'volume': float(k.get('vol', 0)),
                    'amount': float(k.get('amount', 0)),
                })
            return rows
        except Exception as e:
            print(f"  [警告] {stock_code} pytdx 获取失败: {e}")
            return []

    def _fetch_kline_sina(self, stock_code: str, count: int) -> List[Dict]:
        """新浪日K线兜底（实测最稳定，支持大 count，不受 pytdx 风控影响）。返回 list[dict]。"""
        import json
        import urllib.request
        prefix = "sh" if stock_code.startswith(('6', '5', '9', '11', '13')) else "sz"
        sym = f"{prefix}{stock_code}"
        url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               "CN_MarketData.getKLineData")
        query = f"symbol={sym}&scale=240&ma=no&datalen={count}"
        req = urllib.request.Request(f"{url}?{query}")
        req.add_header("User-Agent", "Mozilla/5.0")
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                raw = json.loads(res.read().decode("utf-8"))
        except Exception as e:
            print(f"  [警告] {stock_code} 新浪K线获取失败: {e}")
            return []
        if not isinstance(raw, list):
            return []
        rows = []
        for item in raw:
            try:
                rows.append({
                    'date': item.get("day", ""),
                    'open': float(item.get("open", 0)),
                    'high': float(item.get("high", 0)),
                    'low': float(item.get("low", 0)),
                    'close': float(item.get("close", 0)),
                    'volume': float(item.get("volume", 0)),
                    'amount': 0.0,
                })
            except (TypeError, ValueError):
                continue
        return rows

    def fetch_index_data(self, index_code: str = "000300", start_date: str = "2023-01-01",
                        end_date: str = "2024-01-01") -> pd.DataFrame:
        """获取指数数据作为基准"""
        return self.fetch_stock_data(index_code, start_date, end_date)


# ============================================================================
# 策略基类
# ============================================================================

class BaseStrategy:
    """策略基类"""
    
    def __init__(self, name: str, params: Optional[Dict] = None):
        self.name = name
        self.params = params or {}
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict] = []
    
    def generate_signals(self, df: pd.DataFrame) -> List[TradeSignal]:
        """生成交易信号子类实现"""
        raise NotImplementedError
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标子类实现"""
        raise NotImplementedError


# ============================================================================
# 内置策略
# ============================================================================

class MACDStrategy(BaseStrategy):
    """MACD策略"""
    
    def __init__(self, params: Optional[Dict] = None):
        default_params = {"fast": 12, "slow": 26, "signal": 9}
        if params:
            default_params.update(params)
        super().__init__("MACD", default_params)
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算MACD指标"""
        close = df['close'].astype(float)
        
        # EMA
        ema_fast = close.ewm(span=self.params['fast'], adjust=False).mean()
        ema_slow = close.ewm(span=self.params['slow'], adjust=False).mean()
        
        # DIF
        df['MACD_DIF'] = ema_fast - ema_slow
        
        # DEA
        df['MACD_DEA'] = df['MACD_DIF'].ewm(span=self.params['signal'], adjust=False).mean()
        
        # MACD柱
        df['MACD_HIST'] = 2 * (df['MACD_DIF'] - df['MACD_DEA'])
        
        return df
    
    def generate_signals(self, df: pd.DataFrame) -> List[TradeSignal]:
        """生成MACD交易信号"""
        df = self.calculate_indicators(df)
        signals = []
        
        for i in range(1, len(df)):
            # 金叉DIF上穿DEA
            if (df['MACD_DIF'].iloc[i-1] < df['MACD_DEA'].iloc[i-1] and
                df['MACD_DIF'].iloc[i] > df['MACD_DEA'].iloc[i]):
                signals.append(TradeSignal(
                    date=df['date'].iloc[i],
                    stock_code="",
                    signal_type=SignalType.BUY,
                    price=df['close'].iloc[i],
                    reason="MACD金叉"
                ))
            
            # 死叉DIF下穿DEA
            elif (df['MACD_DIF'].iloc[i-1] > df['MACD_DEA'].iloc[i-1] and
                  df['MACD_DIF'].iloc[i] < df['MACD_DEA'].iloc[i]):
                signals.append(TradeSignal(
                    date=df['date'].iloc[i],
                    stock_code="",
                    signal_type=SignalType.SELL,
                    price=df['close'].iloc[i],
                    reason="MACD死叉"
                ))
        
        return signals


class KDJStrategy(BaseStrategy):
    """KDJ策略"""
    
    def __init__(self, params: Optional[Dict] = None):
        default_params = {"n": 9, "m1": 3, "m2": 3, "oversold": 20, "overbought": 80}
        if params:
            default_params.update(params)
        super().__init__("KDJ", default_params)
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算KDJ指标"""
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        close = df['close'].astype(float)
        
        n = self.params['n']
        
        # RSV
        lowest_low = low.rolling(window=n, min_periods=1).min()
        highest_high = high.rolling(window=n, min_periods=1).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100
        
        # K, D, J — 标准 SMA 公式: K = 2/3 * prev_K + 1/3 * RSV
        k_vals = []
        d_vals = []
        k_start = 50.0
        d_start = 50.0
        for val in rsv:
            k_new = (2.0 / 3.0) * k_start + (1.0 / 3.0) * val
            d_new = (2.0 / 3.0) * d_start + (1.0 / 3.0) * k_new
            k_vals.append(k_new)
            d_vals.append(d_new)
            k_start = k_new
            d_start = d_new
        df['KDJ_K'] = k_vals
        df['KDJ_D'] = d_vals
        df['KDJ_J'] = 3 * pd.Series(k_vals) - 2 * pd.Series(d_vals)
        
        return df
    
    def generate_signals(self, df: pd.DataFrame) -> List[TradeSignal]:
        """生成KDJ交易信号"""
        df = self.calculate_indicators(df)
        signals = []
        
        oversold = self.params['oversold']
        overbought = self.params['overbought']
        
        for i in range(1, len(df)):
            # 超卖区金叉
            if (df['KDJ_J'].iloc[i-1] < oversold and
                df['KDJ_K'].iloc[i] > df['KDJ_D'].iloc[i] and
                df['KDJ_J'].iloc[i] > oversold):
                signals.append(TradeSignal(
                    date=df['date'].iloc[i],
                    stock_code="",
                    signal_type=SignalType.BUY,
                    price=df['close'].iloc[i],
                    reason=f"KDJ超卖金叉 (J={df['KDJ_J'].iloc[i]:.1f})"
                ))
            
            # 超买区死叉
            elif (df['KDJ_J'].iloc[i-1] > overbought and
                  df['KDJ_K'].iloc[i] < df['KDJ_D'].iloc[i] and
                  df['KDJ_J'].iloc[i] < overbought):
                signals.append(TradeSignal(
                    date=df['date'].iloc[i],
                    stock_code="",
                    signal_type=SignalType.SELL,
                    price=df['close'].iloc[i],
                    reason=f"KDJ超买死叉 (J={df['KDJ_J'].iloc[i]:.1f})"
                ))
        
        return signals


class RSIStrategy(BaseStrategy):
    """RSI策略"""
    
    def __init__(self, params: Optional[Dict] = None):
        default_params = {"period": 14, "oversold": 30, "overbought": 70}
        if params:
            default_params.update(params)
        super().__init__("RSI", default_params)
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算RSI指标"""
        close = df['close'].astype(float)
        
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        
        period = self.params['period']
        avg_gain = gain.ewm(com=period-1, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(com=period-1, min_periods=period, adjust=False).mean()
        
        rs = avg_gain / (avg_loss + 1e-10)
        df['RSI'] = 100 - 100 / (1 + rs)
        
        return df
    
    def generate_signals(self, df: pd.DataFrame) -> List[TradeSignal]:
        """生成RSI交易信号"""
        df = self.calculate_indicators(df)
        signals = []
        
        oversold = self.params['oversold']
        overbought = self.params['overbought']
        
        for i in range(1, len(df)):
            # 超卖反弹
            if (df['RSI'].iloc[i-1] < oversold and
                df['RSI'].iloc[i] > oversold):
                signals.append(TradeSignal(
                    date=df['date'].iloc[i],
                    stock_code="",
                    signal_type=SignalType.BUY,
                    price=df['close'].iloc[i],
                    reason=f"RSI超卖反弹 (RSI={df['RSI'].iloc[i]:.1f})"
                ))
            
            # 超买回落
            elif (df['RSI'].iloc[i-1] > overbought and
                  df['RSI'].iloc[i] < overbought):
                signals.append(TradeSignal(
                    date=df['date'].iloc[i],
                    stock_code="",
                    signal_type=SignalType.SELL,
                    price=df['close'].iloc[i],
                    reason=f"RSI超买回落 (RSI={df['RSI'].iloc[i]:.1f})"
                ))
        
        return signals


class BollingerStrategy(BaseStrategy):
    """布林带策略"""
    
    def __init__(self, params: Optional[Dict] = None):
        default_params = {"window": 20, "num_std": 2.0}
        if params:
            default_params.update(params)
        super().__init__("Bollinger", default_params)
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算布林带指标"""
        close = df['close'].astype(float)
        
        window = self.params['window']
        num_std = self.params['num_std']
        
        df['BB_MA'] = close.rolling(window=window, min_periods=1).mean()
        df['BB_STD'] = close.rolling(window=window, min_periods=1).std()
        df['BB_UPPER'] = df['BB_MA'] + num_std * df['BB_STD']
        df['BB_LOWER'] = df['BB_MA'] - num_std * df['BB_STD']
        df['BB_PCT'] = (close - df['BB_LOWER']) / (df['BB_UPPER'] - df['BB_LOWER'] + 1e-10)
        
        return df
    
    def generate_signals(self, df: pd.DataFrame) -> List[TradeSignal]:
        """生成布林带交易信号"""
        df = self.calculate_indicators(df)
        signals = []
        
        for i in range(1, len(df)):
            # 价格突破下轨后反弹
            if (df['close'].iloc[i-1] < df['BB_LOWER'].iloc[i-1] and
                df['close'].iloc[i] > df['BB_LOWER'].iloc[i]):
                signals.append(TradeSignal(
                    date=df['date'].iloc[i],
                    stock_code="",
                    signal_type=SignalType.BUY,
                    price=df['close'].iloc[i],
                    reason="布林带下轨反弹"
                ))
            
            # 价格突破上轨后回落
            elif (df['close'].iloc[i-1] > df['BB_UPPER'].iloc[i-1] and
                  df['close'].iloc[i] < df['BB_UPPER'].iloc[i]):
                signals.append(TradeSignal(
                    date=df['date'].iloc[i],
                    stock_code="",
                    signal_type=SignalType.SELL,
                    price=df['close'].iloc[i],
                    reason="布林带上轨回落"
                ))
        
        return signals


class DualMAStrategy(BaseStrategy):
    """双均线策略"""
    
    def __init__(self, params: Optional[Dict] = None):
        default_params = {"fast": 5, "slow": 20}
        if params:
            default_params.update(params)
        super().__init__("DualMA", default_params)
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算均线指标"""
        close = df['close'].astype(float)
        
        df['MA_FAST'] = close.rolling(window=self.params['fast'], min_periods=1).mean()
        df['MA_SLOW'] = close.rolling(window=self.params['slow'], min_periods=1).mean()
        
        return df
    
    def generate_signals(self, df: pd.DataFrame) -> List[TradeSignal]:
        """生成双均线交易信号"""
        df = self.calculate_indicators(df)
        signals = []
        
        for i in range(1, len(df)):
            # 金叉
            if (df['MA_FAST'].iloc[i-1] < df['MA_SLOW'].iloc[i-1] and
                df['MA_FAST'].iloc[i] > df['MA_SLOW'].iloc[i]):
                signals.append(TradeSignal(
                    date=df['date'].iloc[i],
                    stock_code="",
                    signal_type=SignalType.BUY,
                    price=df['close'].iloc[i],
                    reason=f"MA{self.params['fast']}/MA{self.params['slow']}金叉"
                ))
            
            # 死叉
            elif (df['MA_FAST'].iloc[i-1] > df['MA_SLOW'].iloc[i-1] and
                  df['MA_FAST'].iloc[i] < df['MA_SLOW'].iloc[i]):
                signals.append(TradeSignal(
                    date=df['date'].iloc[i],
                    stock_code="",
                    signal_type=SignalType.SELL,
                    price=df['close'].iloc[i],
                    reason=f"MA{self.params['fast']}/MA{self.params['slow']}死叉"
                ))
        
        return signals


# ============================================================================
# 策略管理器
# ============================================================================

class StrategyManager:
    """策略管理器 - 注册和获取策略"""
    
    _strategies: Dict[str, type] = {
        "macd": MACDStrategy,
        "kdj": KDJStrategy,
        "rsi": RSIStrategy,
        "bollinger": BollingerStrategy,
        "dualma": DualMAStrategy,
    }
    
    @classmethod
    def register(cls, name: str, strategy_class: type):
        """注册新策略"""
        cls._strategies[name.lower()] = strategy_class
    
    @classmethod
    def get(cls, name: str, params: Optional[Dict] = None) -> BaseStrategy:
        """获取策略实例"""
        if name.lower() not in cls._strategies:
            raise ValueError(f"未知策略: {name}可用策略: {list(cls._strategies.keys())}")
        return cls._strategies[name.lower()](params)
    
    @classmethod
    def list_strategies(cls) -> List[str]:
        """列出所有可用策略"""
        return list(cls._strategies.keys())


# ============================================================================
# 回测引擎
# ============================================================================

class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, initial_capital: float = 1000000.0,
                 commission_rate: float = 0.001,
                 slippage_rate: float = 0.001,
                 stamp_tax_rate: float = 0.001,
                 stop_loss_pct: float = -0.05,
                 take_profit_pct: float = 0.08):
        """
        初始化回测引擎

        Args:
            initial_capital: 初始资金
            commission_rate: 佣金费率双向
            slippage_rate: 滑点费率（基础值，动态调整）
            stamp_tax_rate: 印花税率仅卖出
            stop_loss_pct: 止损线（相对成本价，默认-5%）
            take_profit_pct: 止盈线（相对成本价，默认+8%）
        """
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
    
    def run_backtest(self, strategy: BaseStrategy, df: pd.DataFrame,
                    stock_code: str = "000001") -> BacktestResult:
        """运行回测"""
        # 生成信号
        signals = strategy.generate_signals(df)
        
        # 设置股票代码
        for signal in signals:
            signal.stock_code = stock_code
        
        # 模拟交易
        capital = self.initial_capital
        shares = 0
        avg_cost = 0.0
        trades = []
        equity_curve = []
        position = None
        
        # 记录每日收益
        daily_returns = []
        prev_equity = capital
        
        for i, row in df.iterrows():
            date = row['date']
            close = float(row['close'])
            
            # 检查是否有信号
            signal = next((s for s in signals if s.date == date), None)
            
            if signal:
                if signal.signal_type == SignalType.BUY and shares == 0:
                    # 买入（动态滑点：基于预估成交量占比）
                    volume = float(row.get('volume', 0))
                    est_shares = int(capital / close / 100) * 100  # 预估股数
                    trade_volume_ratio = est_shares / max(volume, 1)
                    dynamic_slippage = self.slippage_rate * (1 + trade_volume_ratio * 100)
                    dynamic_slippage = min(dynamic_slippage, 0.02)  # 上限2%

                    commission = capital * self.commission_rate
                    slippage = capital * dynamic_slippage
                    available_capital = capital - commission - slippage

                    shares = int(available_capital / close / 100) * 100  # 整手
                    if shares > 0:
                        cost = shares * close
                        commission = max(cost * self.commission_rate, 5.0)  # 最低5元
                        slippage = cost * dynamic_slippage
                        
                        capital -= (cost + commission + slippage)
                        avg_cost = close
                        
                        trades.append(Trade(
                            date=date,
                            stock_code=stock_code,
                            direction="BUY",
                            price=close,
                            shares=shares,
                            amount=cost,
                            commission=commission,
                            slippage=slippage,
                            reason=signal.reason
                        ))
                
                elif signal.signal_type == SignalType.SELL and shares > 0:
                    # 卖出（策略信号，动态滑点）
                    volume = float(row.get('volume', 0))
                    trade_volume_ratio = shares / max(volume, 1)
                    dynamic_slippage = self.slippage_rate * (1 + trade_volume_ratio * 100)
                    dynamic_slippage = min(dynamic_slippage, 0.02)  # 上限2%
                    
                    revenue = shares * close
                    commission = max(revenue * self.commission_rate, 5.0)  # 最低5元
                    slippage = revenue * dynamic_slippage
                    stamp_tax = revenue * self.stamp_tax_rate
                    
                    capital += (revenue - commission - slippage - stamp_tax)
                    
                    trades.append(Trade(
                        date=date,
                        stock_code=stock_code,
                        direction="SELL",
                        price=close,
                        shares=shares,
                        amount=revenue,
                        commission=commission,
                        slippage=slippage + stamp_tax,
                        reason=signal.reason
                    ))
                    
                    shares = 0
                    avg_cost = 0.0
            
            # 止损/止盈检查（持仓中触发强制平仓）
            if shares > 0 and avg_cost > 0:
                pnl_pct = (close - avg_cost) / avg_cost
                force_close = False
                force_reason = ""
                
                if self.stop_loss_pct < 0 and pnl_pct <= self.stop_loss_pct:
                    force_close = True
                    force_reason = f"止损触发 ({pnl_pct:.1%})"
                elif pnl_pct >= self.take_profit_pct:
                    force_close = True
                    force_reason = f"止盈触发 ({pnl_pct:.1%})"
                
                if force_close:
                    volume = float(row.get('volume', 0))
                    trade_volume_ratio = shares / max(volume, 1)
                    dynamic_slippage = self.slippage_rate * (1 + trade_volume_ratio * 100)
                    dynamic_slippage = min(dynamic_slippage, 0.02)
                    
                    revenue = shares * close
                    commission = max(revenue * self.commission_rate, 5.0)
                    slippage = revenue * dynamic_slippage
                    stamp_tax = revenue * self.stamp_tax_rate
                    
                    capital += (revenue - commission - slippage - stamp_tax)
                    
                    trades.append(Trade(
                        date=date,
                        stock_code=stock_code,
                        direction="SELL",
                        price=close,
                        shares=shares,
                        amount=revenue,
                        commission=commission,
                        slippage=slippage + stamp_tax,
                        reason=force_reason
                    ))
                    
                    shares = 0
                    avg_cost = 0.0
            
            # 计算当前权益
            market_value = shares * close
            equity = capital + market_value
            
            equity_curve.append({
                "date": date,
                "equity": equity,
                "capital": capital,
                "market_value": market_value,
                "shares": shares
            })
            
            # 计算日收益率
            if prev_equity > 0:
                daily_return = (equity - prev_equity) / prev_equity
                daily_returns.append(daily_return)
            prev_equity = equity
        
        # 计算绩效指标
        result = self._calculate_metrics(
            strategy.name, equity_curve, trades, daily_returns, df
        )
        
        return result
    
    def _calculate_metrics(self, strategy_name: str, equity_curve: List[Dict],
                          trades: List[Trade], daily_returns: List[float],
                          df: pd.DataFrame) -> BacktestResult:
        """计算绩效指标"""
        if not equity_curve:
            return BacktestResult(
                strategy_name=strategy_name,
                start_date="", end_date="",
                initial_capital=self.initial_capital,
                final_capital=self.initial_capital,
                total_return=0, annual_return=0,
                sharpe_ratio=0, max_drawdown=0,
                max_drawdown_duration=0, win_rate=0,
                profit_factor=0, total_trades=0,
                avg_holding_days=0, calmar_ratio=0,
                sortino_ratio=0, volatility=0,
                trades=[], equity_curve=[], monthly_returns=[]
            )
        
        # 基础指标
        start_date = equity_curve[0]['date']
        end_date = equity_curve[-1]['date']
        final_capital = equity_curve[-1]['equity']
        total_return = (final_capital - self.initial_capital) / self.initial_capital
        
        # 年化收益率（A股年交易日约242天）
        days = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days
        trading_days = max(1, int(days * 242 / 365))
        annual_return = (1 + total_return) ** (242 / max(trading_days, 1)) - 1 if days > 0 else 0
        
        # 夏普比率（扣除3%年化无风险利率）
        RISK_FREE_RATE = 0.03
        daily_rf = RISK_FREE_RATE / 252
        daily_returns_arr = np.array(daily_returns)
        if len(daily_returns_arr) > 0 and np.std(daily_returns_arr) > 0:
            sharpe_ratio = (np.mean(daily_returns_arr) - daily_rf) / np.std(daily_returns_arr) * np.sqrt(252)
        else:
            sharpe_ratio = 0
        
        # 最大回撤
        equities = [e['equity'] for e in equity_curve]
        peak = equities[0]
        max_drawdown = 0
        max_drawdown_duration = 0
        current_drawdown_duration = 0
        
        for eq in equities:
            if eq > peak:
                peak = eq
                current_drawdown_duration = 0
            else:
                drawdown = (peak - eq) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                current_drawdown_duration += 1
                max_drawdown_duration = max(max_drawdown_duration, current_drawdown_duration)
        
        # 胜率和盈亏比（按实际交易对配对：每次买入对应一次卖出）
        buy_trades = [t for t in trades if t.direction == "BUY"]
        sell_trades = [t for t in trades if t.direction == "SELL"]
        
        wins = 0
        losses = 0
        total_profit = 0.0
        total_loss = 0.0
        
        # 按时间顺序配对：遍历卖出交易，找到对应的最近未配对买入
        unmatched_buys = list(buy_trades)
        for sell in sell_trades:
            if not unmatched_buys:
                break
            buy = unmatched_buys.pop(0)  # FIFO配对
            
            pnl = (sell.price - buy.price) * buy.shares
            if pnl > 0:
                wins += 1
                total_profit += pnl
            else:
                losses += 1
                total_loss += abs(pnl)
        
        win_rate = wins / max(wins + losses, 1)
        profit_factor = total_profit / max(total_loss, 1e-8)
        
        # 平均持仓天数
        avg_holding_days = days / max(len(buy_trades), 1)
        
        # 波动率
        volatility = np.std(daily_returns_arr) * np.sqrt(252) if len(daily_returns_arr) > 0 else 0
        
        # Calmar比率
        calmar_ratio = annual_return / max(max_drawdown, 0.01)
        
        # Sortino比率
        downside_returns = daily_returns_arr[daily_returns_arr < 0]
        if len(downside_returns) > 0:
            downside_std = np.std(downside_returns)
            sortino_ratio = np.mean(daily_returns_arr) / max(downside_std, 1e-8) * np.sqrt(252)
        else:
            sortino_ratio = 0
        
        # 月度收益
        monthly_returns = self._calculate_monthly_returns(equity_curve)
        
        return BacktestResult(
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            annual_return=annual_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            max_drawdown_duration=max_drawdown_duration,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=len(buy_trades),
            avg_holding_days=avg_holding_days,
            calmar_ratio=calmar_ratio,
            sortino_ratio=sortino_ratio,
            volatility=volatility,
            trades=[asdict(t) for t in trades],
            equity_curve=equity_curve,
            monthly_returns=monthly_returns
        )
    
    def _calculate_monthly_returns(self, equity_curve: List[Dict]) -> List[Dict]:
        """计算月度收益"""
        if not equity_curve:
            return []
        
        monthly = {}
        prev_equity = equity_curve[0]['equity']
        
        for point in equity_curve:
            date = pd.to_datetime(point['date'])
            month_key = date.strftime('%Y-%m')
            
            if month_key not in monthly:
                monthly[month_key] = {
                    'month': month_key,
                    'start_equity': prev_equity,
                    'end_equity': point['equity']
                }
            
            monthly[month_key]['end_equity'] = point['equity']
            prev_equity = point['equity']
        
        # 计算月度收益率
        result = []
        for month_key, data in sorted(monthly.items()):
            monthly_return = (data['end_equity'] - data['start_equity']) / data['start_equity']
            result.append({
                'month': month_key,
                'return': monthly_return
            })
        
        return result


# ============================================================================
# 回测报告生成器
# ============================================================================

class BacktestReporter:
    """回测报告生成器"""
    
    @staticmethod
    def generate_report(result: BacktestResult, output_dir: str = "./backtest_output") -> str:
        """生成回测报告"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # 生成JSON报告
        report = {
            "strategy": result.strategy_name,
            "period": f"{result.start_date} ~ {result.end_date}",
            "initial_capital": result.initial_capital,
            "final_capital": result.final_capital,
            "performance": {
                "total_return": f"{result.total_return:.2%}",
                "annual_return": f"{result.annual_return:.2%}",
                "sharpe_ratio": f"{result.sharpe_ratio:.2f}",
                "max_drawdown": f"{result.max_drawdown:.2%}",
                "max_drawdown_duration": f"{result.max_drawdown_duration} 天",
                "win_rate": f"{result.win_rate:.2%}",
                "profit_factor": f"{result.profit_factor:.2f}",
                "calmar_ratio": f"{result.calmar_ratio:.2f}",
                "sortino_ratio": f"{result.sortino_ratio:.2f}",
                "volatility": f"{result.volatility:.2%}",
            },
            "trades": {
                "total_trades": result.total_trades,
                "avg_holding_days": f"{result.avg_holding_days:.1f} 天",
            },
            "monthly_returns": result.monthly_returns,
        }
        
        # 保存JSON报告
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = Path(output_dir) / f"backtest_report_{result.strategy_name}_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # 生成文本报告
        text_report = BacktestReporter._generate_text_report(result)
        text_path = Path(output_dir) / f"backtest_report_{result.strategy_name}_{timestamp}.txt"
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(text_report)
        
        # 生成权益曲线CSV
        equity_df = pd.DataFrame(result.equity_curve)
        equity_csv_path = Path(output_dir) / f"equity_curve_{result.strategy_name}_{timestamp}.csv"
        equity_df.to_csv(equity_csv_path, index=False)
        
        print(f"\n[成功] 回测报告已生成:")
        print(f"   JSON报告: {json_path}")
        print(f"   文本报告: {text_path}")
        print(f"   权益曲线: {equity_csv_path}")
        
        return str(text_path)
    
    @staticmethod
    def _generate_text_report(result: BacktestResult) -> str:
        """生成文本报告"""
        report = f"""
================================================================================
                    策略回测报告
================================================================================

策略名称: {result.strategy_name}
回测区间: {result.start_date} ~ {result.end_date}

--------------------------------------------------------------------------------
                            绩效概览
--------------------------------------------------------------------------------
初始资金:     {result.initial_capital:>15,.2f}
最终资金:     {result.final_capital:>15,.2f}
总收益率:     {result.total_return:>14.2%}
年化收益:     {result.annual_return:>14.2%}

--------------------------------------------------------------------------------
                            风险指标
--------------------------------------------------------------------------------
夏普比率:     {result.sharpe_ratio:>14.2f}
索提诺比率:   {result.sortino_ratio:>14.2f}
卡玛比率:     {result.calmar_ratio:>14.2f}
最大回撤:     {result.max_drawdown:>14.2%}
回撤持续:     {result.max_drawdown_duration:>14d} 天
年化波动:     {result.volatility:>14.2%}

--------------------------------------------------------------------------------
                            交易统计
--------------------------------------------------------------------------------
总交易次数:   {result.total_trades:>14d}
胜率:         {result.win_rate:>14.2%}
盈亏比:       {result.profit_factor:>14.2f}
平均持仓:     {result.avg_holding_days:>14.1f} 天

--------------------------------------------------------------------------------
                            月度收益
--------------------------------------------------------------------------------
"""
        for mr in result.monthly_returns:
            report += f"{mr['month']}:     {mr['return']:>14.2%}\n"
        
        report += """
================================================================================
                            免责声明
================================================================================
本回测结果仅供历史分析参考不代表未来收益
投资有风险入市需谨慎

================================================================================
"""
        return report
    
    @staticmethod
    def compare_strategies(results: List[BacktestResult], output_dir: str = "./backtest_output") -> str:
        """对比多个策略"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # 生成对比报告
        comparison = []
        for result in results:
            comparison.append({
                "strategy": result.strategy_name,
                "total_return": result.total_return,
                "annual_return": result.annual_return,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "total_trades": result.total_trades,
            })
        
        # 按夏普比率排序
        comparison.sort(key=lambda x: x['sharpe_ratio'], reverse=True)
        
        # 生成文本对比报告
        report = """
================================================================================
                        策略对比报告
================================================================================

排名 | 策略名称 | 年化收益 | 夏普比率 | 最大回撤 | 胜率   | 盈亏比
-----|----------|----------|----------|----------|--------|--------
"""
        for i, comp in enumerate(comparison, 1):
            report += f"{i:4d} | {comp['strategy']:8s} | {comp['annual_return']:>8.2%} | {comp['sharpe_ratio']:>8.2f} | {comp['max_drawdown']:>8.2%} | {comp['win_rate']:>6.2%} | {comp['profit_factor']:>6.2f}\n"
        
        report += """
================================================================================
"""
        
        # 保存报告
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = Path(output_dir) / f"strategy_comparison_{timestamp}.txt"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        
        # 保存JSON
        json_path = Path(output_dir) / f"strategy_comparison_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(comparison, f, ensure_ascii=False, indent=2)
        
        print(f"\n[成功] 策略对比报告已生成:")
        print(f"   文本报告: {report_path}")
        print(f"   JSON报告: {json_path}")
        
        return str(report_path)


# ============================================================================
# 主入口
# ============================================================================

class StrategyBacktester:
    """策略回测系统 - 主入口"""
    
    def __init__(self):
        self.data_fetcher = BacktestDataFetcher()
        self.engine = BacktestEngine()
        self.reporter = BacktestReporter()
    
    def backtest(self, stock_code: str, strategy_name: str,
                start_date: str, end_date: str,
                params: Optional[Dict] = None,
                initial_capital: float = 1000000.0,
                output_dir: str = "./backtest_output") -> BacktestResult:
        """运行单个策略回测"""
        print("=" * 60)
        print("[图表] 策略回测系统")
        print("=" * 60)
        print(f"   股票代码: {stock_code}")
        print(f"   策略: {strategy_name}")
        print(f"   区间: {start_date} ~ {end_date}")
        print(f"   初始资金: {initial_capital:,.2f}")
        
        # 获取数据
        print("\n 获取历史数据...")
        df = self.data_fetcher.fetch_stock_data(stock_code, start_date, end_date)
        
        if df.empty:
            raise RuntimeError(f"无法获取 {stock_code} 的历史数据")
        
        print(f"  [成功] 获取到 {len(df)} 条数据")
        
        # 创建策略
        strategy = StrategyManager.get(strategy_name, params)
        
        # 设置引擎
        self.engine.initial_capital = initial_capital
        
        # 运行回测
        print("\n 运行回测...")
        result = self.engine.run_backtest(strategy, df, stock_code)
        
        # 生成报告
        print("\n[报告] 生成报告...")
        self.reporter.generate_report(result, output_dir)
        
        # 打印摘要
        self._print_summary(result)
        
        return result
    
    def compare(self, stock_code: str, strategy_names: List[str],
               start_date: str, end_date: str,
               initial_capital: float = 1000000.0,
               output_dir: str = "./backtest_output") -> List[BacktestResult]:
        """对比多个策略"""
        print("=" * 60)
        print("[图表] 策略对比回测")
        print("=" * 60)
        print(f"   股票代码: {stock_code}")
        print(f"   策略: {', '.join(strategy_names)}")
        print(f"   区间: {start_date} ~ {end_date}")
        
        # 获取数据
        print("\n 获取历史数据...")
        df = self.data_fetcher.fetch_stock_data(stock_code, start_date, end_date)
        
        if df.empty:
            raise RuntimeError(f"无法获取 {stock_code} 的历史数据")
        
        print(f"  [成功] 获取到 {len(df)} 条数据")
        
        # 运行所有策略
        results = []
        for strategy_name in strategy_names:
            print(f"\n 运行 {strategy_name} 策略...")
            strategy = StrategyManager.get(strategy_name)
            self.engine.initial_capital = initial_capital
            result = self.engine.run_backtest(strategy, df, stock_code)
            results.append(result)
        
        # 生成对比报告
        print("\n[报告] 生成对比报告...")
        self.reporter.compare_strategies(results, output_dir)
        
        # 打印对比摘要
        self._print_comparison(results)
        
        return results
    
    def _print_summary(self, result: BacktestResult):
        """打印回测摘要"""
        print("\n" + "=" * 60)
        print("[图表] 回测结果摘要")
        print("=" * 60)
        print(f"  总收益率:   {result.total_return:.2%}")
        print(f"  年化收益:   {result.annual_return:.2%}")
        print(f"  夏普比率:   {result.sharpe_ratio:.2f}")
        print(f"  最大回撤:   {result.max_drawdown:.2%}")
        print(f"  胜率:       {result.win_rate:.2%}")
        print(f"  总交易:     {result.total_trades} 次")
        print("=" * 60)
    
    def _print_comparison(self, results: List[BacktestResult]):
        """打印策略对比"""
        print("\n" + "=" * 60)
        print("[图表] 策略对比结果")
        print("=" * 60)
        print(f"{'策略':<12s} | {'年化收益':>10s} | {'夏普比率':>10s} | {'最大回撤':>10s} | {'胜率':>8s}")
        print("-" * 60)
        
        for result in sorted(results, key=lambda x: x.sharpe_ratio, reverse=True):
            print(f"{result.strategy_name:<12s} | {result.annual_return:>10.2%} | {result.sharpe_ratio:>10.2f} | {result.max_drawdown:>10.2%} | {result.win_rate:>8.2%}")
        
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="A股策略回测系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 回测MACD策略
  python strategy_backtest.py backtest --stock 600519 --strategy macd --start 2023-01-01 --end 2024-01-01

  # 对比多个策略
  python strategy_backtest.py compare --stock 600519 --strategies "macd,kdj,rsi" --start 2023-01-01

  # 列出可用策略
  python strategy_backtest.py list
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # backtest子命令
    backtest_parser = subparsers.add_parser("backtest", help="回测单个策略")
    backtest_parser.add_argument("--stock", type=str, required=True, help="股票代码")
    backtest_parser.add_argument("--strategy", type=str, required=True, help="策略名称")
    backtest_parser.add_argument("--start", type=str, required=True, help="开始日期 (YYYY-MM-DD)")
    backtest_parser.add_argument("--end", type=str, required=True, help="结束日期 (YYYY-MM-DD)")
    backtest_parser.add_argument("--params", type=str, default=None, help="策略参数 (JSON)")
    backtest_parser.add_argument("--capital", type=float, default=1000000.0, help="初始资金")
    backtest_parser.add_argument("--output", type=str, default="./backtest_output", help="输出目录")
    
    # compare子命令
    compare_parser = subparsers.add_parser("compare", help="对比多个策略")
    compare_parser.add_argument("--stock", type=str, required=True, help="股票代码")
    compare_parser.add_argument("--strategies", type=str, required=True, help="策略列表逗号分隔")
    compare_parser.add_argument("--start", type=str, required=True, help="开始日期")
    compare_parser.add_argument("--end", type=str, required=True, help="结束日期")
    compare_parser.add_argument("--capital", type=float, default=1000000.0, help="初始资金")
    compare_parser.add_argument("--output", type=str, default="./backtest_output", help="输出目录")
    
    # list子命令
    list_parser = subparsers.add_parser("list", help="列出可用策略")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    backtester = StrategyBacktester()
    
    if args.command == "backtest":
        params = json.loads(args.params) if args.params else None
        backtester.backtest(
            stock_code=args.stock,
            strategy_name=args.strategy,
            start_date=args.start,
            end_date=args.end,
            params=params,
            initial_capital=args.capital,
            output_dir=args.output
        )
    
    elif args.command == "compare":
        strategies = [s.strip() for s in args.strategies.split(",")]
        backtester.compare(
            stock_code=args.stock,
            strategy_names=strategies,
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital,
            output_dir=args.output
        )
    
    elif args.command == "list":
        print("\n[列表] 可用策略:")
        for name in StrategyManager.list_strategies():
            print(f"   - {name}")


if __name__ == "__main__":
    main()
