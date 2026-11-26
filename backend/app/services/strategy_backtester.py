"""
策略回测引擎 — 计算各选股策略的历史表现统计

功能：
1. 对每个策略，基于历史数据模拟选股（统一使用 pytdx 通达信数据源）
2. 计算胜率、平均收益率、最大回撤等指标
3. 支持按时间段、股票池自定义回测
4. 结果缓存到内存，避免重复计算
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import numpy as np

logger = logging.getLogger(__name__)


# 策略名称 → StandardScorer profile 映射
STRATEGY_PROFILE_MAP = {
    "macd": "trend_breakout",
    "kdj": "oversold_bounce",
    "rsi": "oversold_bounce",
    "bollinger": "balanced",
    "dualma": "trend_breakout",
    "trend_breakout": "trend_breakout",
    "oversold_bounce": "oversold_bounce",
    "capital_resonance": "capital_resonance",
    "balanced": "balanced",
}

# 策略名称 → 默认持有天数（按策略特性区分）
STRATEGY_HOLD_PERIODS = {
    "oversold_bounce": 5,       # 低吸企稳：短线反弹，1-5天
    "kdj": 5,                   # KDJ超卖反弹：短线
    "rsi": 5,                   # RSI超卖反弹：短线
    "capital_resonance": 10,    # 资金共振：中短线，5-10天
    "trend_breakout": 20,       # 趋势突破：中线持有，10-20天
    "macd": 20,                 # MACD金叉：中线
    "dualma": 20,               # 双均线：中线
    "bollinger": 30,            # 布林带：默认30天
    "balanced": 30,             # 均衡型：默认30天
}

# 策略名称 → 回测验证时使用的策略类型（用于BacktestFactorCalculator）
STRATEGY_BACKTEST_TYPE = {
    "multi_factor": "macd",       # 趋势突破用MACD验证
    "low_absorption": "kdj",      # 低吸企稳用KDJ验证
    "capital_flow": "capital_resonance",
    "ml_prediction": "balanced",
    "leader": "trend_breakout",
}


class StrategyBacktester:
    """策略回测引擎"""

    def __init__(self):
        self._cache = {}  # 内存缓存

    def backtest_strategy(self, strategy_name: str, days: Optional[int] = None,
                         stock_pool: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        回测指定策略的历史表现

        Args:
            strategy_name: 策略名称（macd/kdj/rsi/bollinger/dualma/trend_breakout/oversold_bounce/capital_resonance/balanced）
            days: 持有天数（None=按策略类型自动选择，默认30天）
            stock_pool: 股票池（可选，默认使用沪深300代表性成分股）

        Returns:
            回测结果字典，包含胜率、平均收益率等指标
        """
        if days is None:
            profile = STRATEGY_PROFILE_MAP.get(strategy_name, "balanced")
            days = STRATEGY_HOLD_PERIODS.get(profile, 30)
        # 检查缓存（包含股票池维度）
        pool_hash = hashlib.md5(",".join(sorted(stock_pool or [])).encode()).hexdigest()[:8]
        cache_key = f"{strategy_name}_{days}_{pool_hash}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if (datetime.now() - cached['timestamp']).total_seconds() < 3600:
                return cached['result']

        try:
            result = self._run_backtest(strategy_name, days, stock_pool)

            # 更新缓存
            self._cache[cache_key] = {
                'timestamp': datetime.now(),
                'result': result
            }

            return result

        except Exception as e:
            logger.warning(f"策略回测失败 ({strategy_name}): {e}")
            return self._default_result(strategy_name)

    def _run_backtest(self, strategy_name: str, days: int,
                     stock_pool: Optional[List[str]] = None) -> Dict[str, Any]:
        """执行回测"""
        from app.core.pytdx_source import pytdx_data
        from app.services.factor_engine import FactorCalculator, StandardScorer

        # 统一使用 pytdx 数据源
        end_date = datetime.now() - timedelta(days=1)
        start_date = end_date - timedelta(days=days * 2)

        # 默认股票池（沪深300代表性成分股）
        if not stock_pool:
            stock_pool = [
                "600519", "300750", "002594", "300059", "600036",
                "601318", "000858", "600276", "601012", "600030",
                "000002", "000333", "000651", "603288", "603259",
                "002475", "603986", "688981", "688012", "002415",
            ]

        # 策略名称 → profile 映射（修复：不再直接传 strategy_name）
        profile = STRATEGY_PROFILE_MAP.get(strategy_name, "balanced")

        # 回测统计
        total_trades = 0
        winning_trades = 0
        losing_trades = 0
        returns = []
        max_drawdown = 0.0
        peak_value = 100.0
        current_value = 100.0

        # 对每只股票进行回测
        for code in stock_pool[:20]:
            try:
                klines = pytdx_data.get_kline(code, period=4, count=max(days * 3, 200))
                if not klines or len(klines) < days + 20:
                    continue

                closes = [k['close'] for k in klines]
                volumes = [k['volume'] for k in klines]
                highs = [k['high'] for k in klines]
                lows = [k['low'] for k in klines]

                # 模拟每日选股和持有收益（优化：增量计算因子，避免 O(n²)）
                warmup = max(20, 60)  # 至少60天确保MA60/ATR14等指标稳定
                cooldown = days  # 冷却期：持仓期间不重复开仓
                last_trade_idx = -cooldown  # 上次交易索引

                for i in range(warmup, len(closes) - days):
                    # 冷却期内跳过（避免同一股票重复开仓）
                    if i - last_trade_idx < cooldown:
                        continue

                    # 每次只用最近 60 根 K 线计算因子（足够覆盖 MA60/ATR14 等指标）
                    lookback = min(60, i)
                    factors = FactorCalculator.compute_all(
                        closes[i - lookback:i],
                        volumes[i - lookback:i],
                        highs[i - lookback:i],
                        lows[i - lookback:i]
                    )

                    if not factors:
                        continue

                    score = StandardScorer.score(factors, profile)

                    if score >= 60:
                        entry_price = closes[i]
                        exit_idx = min(i + days, len(closes) - 1)
                        exit_price = closes[exit_idx]

                        if entry_price > 0:
                            return_pct = (exit_price - entry_price) / entry_price * 100
                            returns.append(return_pct)

                            total_trades += 1
                            if return_pct > 0:
                                winning_trades += 1
                            elif return_pct < 0:
                                losing_trades += 1

                            current_value *= (1 + return_pct / 100)
                            if current_value > peak_value:
                                peak_value = current_value

                            drawdown = (peak_value - current_value) / peak_value * 100
                            if drawdown > max_drawdown:
                                max_drawdown = drawdown

                            last_trade_idx = i

            except Exception as e:
                logger.debug(f"回测股票 {code} 失败: {e}")

        result = {
            'strategy': strategy_name,
            'backtest_days': days,
            'stock_count': len(stock_pool),
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': round(winning_trades / total_trades * 100, 1) if total_trades > 0 else 0,
            'avg_return': round(float(np.mean(returns)), 2) if returns else 0,
            'median_return': round(float(np.median(returns)), 2) if returns else 0,
            'max_drawdown': round(max_drawdown, 2),
            'sharpe_ratio': self._calculate_sharpe(returns),
            'profit_factor': self._calculate_profit_factor(returns),
        }

        return result

    def _calculate_sharpe(self, returns: List[float], risk_free_rate: float = 0.03) -> float:
        """计算夏普比率"""
        if not returns or len(returns) < 2:
            return 0.0

        avg_return = np.mean(returns)
        std_return = np.std(returns)

        if std_return == 0:
            return 0.0

        daily_rf = risk_free_rate / 252
        sharpe = (avg_return - daily_rf) / std_return * np.sqrt(252)
        return round(float(sharpe), 2)

    def _calculate_profit_factor(self, returns: List[float]) -> float:
        """计算盈亏比"""
        if not returns:
            return 0.0

        gains = [r for r in returns if r > 0]
        losses = [abs(r) for r in returns if r < 0]

        total_gains = sum(gains)
        total_losses = sum(losses)

        if total_losses == 0:
            return round(min(total_gains * 10, 999.99), 2) if total_gains > 0 else 0.0

        return round(total_gains / total_losses, 2)

    def _default_result(self, strategy_name: str, stock_code: str = '') -> Dict[str, Any]:
        """默认回测结果（当无法计算时）"""
        return {
            'stock': stock_code,
            'strategy': strategy_name,
            'backtest_days': 30,
            'stock_count': 0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0,
            'avg_return': 0,
            'median_return': 0,
            'max_drawdown': 0,
            'sharpe_ratio': 0,
            'profit_factor': 0,
            'composite_score': 50,
            'rating': '一般',
        }

    def quick_verify(self, stock_code: str, strategy_name: str = 'macd', days: int = 120) -> Dict[str, Any]:
        """快速验证 — 对单只股票跑短期回测返回关键指标"""
        from app.core.pytdx_source import pytdx_data
        from app.services.factor_engine import FactorCalculator, StandardScorer

        try:
            klines = pytdx_data.get_kline(stock_code, period=4, count=max(days * 3, 200))
            if not klines or len(klines) < days + 20:
                return self._default_result(strategy_name, stock_code)

            closes = [k['close'] for k in klines]
            volumes = [k['volume'] for k in klines]
            highs = [k['high'] for k in klines]
            lows = [k['low'] for k in klines]

            profile = STRATEGY_PROFILE_MAP.get(strategy_name, "balanced")
            returns = []
            total_trades = 0

            warmup = max(20, 60)  # 至少60天确保MA60/ATR14等指标稳定
            for i in range(warmup, len(closes) - days):
                lookback = min(60, i)
                factors = FactorCalculator.compute_all(
                    closes[i - lookback:i],
                    volumes[i - lookback:i],
                    highs[i - lookback:i],
                    lows[i - lookback:i]
                )
                if not factors:
                    continue

                score = StandardScorer.score(factors, profile)

                if score >= 60:
                    entry_price = closes[i]
                    exit_idx = min(i + days // 2, len(closes) - 1)
                    exit_price = closes[exit_idx]

                    if entry_price > 0:
                        return_pct = (exit_price - entry_price) / entry_price * 100
                        returns.append(return_pct)
                        total_trades += 1

            # 修复：正确的累计收益率计算 — 几何复合
            cumulative_return = 0.0
            if returns:
                compound = 1.0
                for r in returns:
                    compound *= (1 + r / 100)
                cumulative_return = (compound - 1) * 100

            result = {
                'stock': stock_code,
                'strategy': strategy_name,
                'period_days': days,
                'total_return_pct': round(cumulative_return, 2),
                'annual_return_pct': round(cumulative_return * (252 / max(days, 1)), 2),
                'sharpe_ratio': self._calculate_sharpe(returns),
                'max_drawdown': round(max([abs(r) for r in returns if r < 0], default=[0]), 2) if any(r < 0 for r in returns) else 0,
                'win_rate': round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1) if returns else 0,
                'profit_factor': self._calculate_profit_factor(returns),
                'total_trades': total_trades,
            }

            result['composite_score'] = self._calculate_composite_score(result)
            result['rating'] = self._score_to_rating(result['composite_score'])

            return result

        except Exception as e:
            logger.warning(f"Quick verify failed ({stock_code}): {e}")
            return self._default_result(strategy_name, stock_code)

    def _calculate_composite_score(self, result: Dict[str, Any]) -> int:
        """计算综合评分 (0-100)"""
        sharpe = result.get('sharpe_ratio', 0)
        win_rate_pct = result.get('win_rate', 50) / 100
        profit_factor = result.get('profit_factor', 1.0)
        max_dd = abs(result.get('max_drawdown', 20)) / 100

        sharpe_score = max(0, min(35, ((sharpe + 1) / 4) * 35))
        win_score = max(0, min(25, ((win_rate_pct - 0.4) / 0.3) * 25))
        pf_score = max(0, min(20, ((profit_factor - 0.5) / 1.5) * 20))
        dd_score = max(0, min(20, ((0.3 - max_dd) / 0.25) * 20))

        return round(sharpe_score + win_score + pf_score + dd_score)

    def _score_to_rating(self, score: int) -> str:
        """评分转评级"""
        if score >= 80:
            return "优秀"
        elif score >= 65:
            return "良好"
        elif score >= 50:
            return "一般"
        else:
            return "较差"

    def batch_verify(self, stock_codes: List[str], strategy_name: str = 'macd', days: int = 120) -> List[Dict[str, Any]]:
        """批量快速验证"""
        results = []
        for code in stock_codes[:20]:
            result = self.quick_verify(code, strategy_name, days)
            results.append(result)
        results.sort(key=lambda x: x.get('composite_score', 0), reverse=True)
        return results


# P2: Backtest factor calculator - convert backtest results into stock selection factors
class BacktestFactorCalculator:
    """基于回测结果的因子计算器"""

    @staticmethod
    def compute_backtest_factor(stock_code: str, strategy_name: str = 'macd', days: int = 120) -> Dict[str, Any]:
        """计算单只股票的回测因子"""
        result = backtester.quick_verify(stock_code, strategy_name, days)

        return {
            'backtest_score': result.get('composite_score', 50),
            'sharpe_ratio': result.get('sharpe_ratio', 0),
            'win_rate': result.get('win_rate', 50),
            'profit_factor': result.get('profit_factor', 1.0),
            'max_drawdown': abs(result.get('max_drawdown', 20)),
        }

    @staticmethod
    def compute_batch_backtest_factors(stock_codes: List[str], strategy_name: str = 'macd', days: int = 120) -> Dict[str, Any]:
        """批量计算回测因子"""
        results = backtester.batch_verify(stock_codes, strategy_name, days)
        return {r['stock']: {'backtest_score': r.get('composite_score', 50), **r}
                for r in results if 'stock' in r}


# Global backtester instance
backtester = StrategyBacktester()
