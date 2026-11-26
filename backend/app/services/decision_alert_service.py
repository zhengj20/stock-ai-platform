"""决策算法预警服务 - 整合7个算法+持仓感知"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class DecisionAlertService:
    """决策算法预警服务
    
    将决策中心的7个量化算法应用于自选股和持仓股的批量监控，
    结合持仓感知（成本价/持仓类型/盈亏）生成智能预警。
    """

    def __init__(self):
        from app.services.decision_algo_service import (
            TDSequentialAlgo,
            MARadarAlgo,
            ChannelBreakoutAlgo,
            MagicWaveAlgo,
            AnomalyDetectAlgo,
            BottomOpportunityAlgo,
            TrendStrengthAlgo,
        )
        self.algos = {
            "td_sequential": TDSequentialAlgo,
            "ma_radar": MARadarAlgo,
            "channel_breakout": ChannelBreakoutAlgo,
            "magic_wave": MagicWaveAlgo,
            "anomaly_detect": AnomalyDetectAlgo,
            "bottom_opportunity": BottomOpportunityAlgo,
            "trend_strength": TrendStrengthAlgo,
        }

    def _format_klines(self, klines: list) -> list[dict]:
        """格式化K线数据为算法所需格式"""
        formatted = []
        for k in klines:
            dt = k["date"]
            date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
            formatted.append({
                "date": date_str,
                "open": round(k["open"], 2),
                "high": round(k["high"], 2),
                "low": round(k["low"], 2),
                "close": round(k["close"], 2),
                "volume": k.get("volume", 0),
            })
        return formatted

    def _run_algos(self, klines: list[dict]) -> dict:
        """运行全部7个算法并返回结果"""
        results = {}
        for name, algo in self.algos.items():
            try:
                if name == "channel_breakout":
                    results[name] = algo.analyze(klines, 20)
                else:
                    results[name] = algo.analyze(klines)
            except Exception as e:
                logger.debug(f"算法 {name} 执行失败: {e}")
                results[name] = {"signal": "neutral"}
        return results

    def _calc_composite_score(self, signals: dict) -> tuple[int, str, int, int]:
        """计算综合评分和信号（纳入全部7个算法）"""
        all_algos = [
            "td_sequential", "ma_radar", "channel_breakout",
            "magic_wave", "anomaly_detect", "bottom_opportunity", "trend_strength"
        ]
        
        buy_signals = sum(1 for a in all_algos if signals.get(a, {}).get("signal") == "buy")
        sell_signals = sum(1 for a in all_algos if signals.get(a, {}).get("signal") == "sell")
        total_algos = len(all_algos)
        
        # 综合评分：买入信号贡献正分，卖出信号贡献负分，中性为50分基准
        buy_ratio = buy_signals / total_algos
        sell_ratio = sell_signals / total_algos
        composite_score = round(50 + (buy_ratio - sell_ratio) * 50, 0)
        composite_score = max(0, min(100, composite_score))
        
        overall_signal = (
            "strong_buy" if buy_signals >= 5
            else "buy" if buy_signals >= 3
            else "strong_sell" if sell_signals >= 5
            else "sell" if sell_signals >= 3
            else "neutral"
        )
        return composite_score, overall_signal, buy_signals, sell_signals

    def _generate_alerts(
        self,
        stock_code: str,
        stock_name: str,
        signals: dict,
        composite_score: int,
        overall_signal: str,
        holding_context: Optional[dict] = None,
    ) -> list[dict]:
        """根据算法信号和持仓上下文生成预警"""
        alerts = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. 综合信号预警
        if overall_signal in ("strong_buy", "buy"):
            alerts.append({
                "stock_code": stock_code,
                "stock_name": stock_name,
                "alert_type": "DECISION_BUY",
                "alert_level": "CRITICAL" if overall_signal == "strong_buy" else "WARNING",
                "message": f"决策算法看多信号（{overall_signal}），综合评分{composite_score}分",
                "current_value": composite_score,
                "threshold_value": 60,
                "recommendation": "建议关注买入机会",
                "action_signal": "BUY" if overall_signal == "strong_buy" else "ADD",
                "timestamp": timestamp,
                "_source": "决策算法",
                "_sourceKey": "decision",
                "_algo_signals": {k: v.get("signal") for k, v in signals.items()},
            })
        elif overall_signal in ("strong_sell", "sell"):
            alerts.append({
                "stock_code": stock_code,
                "stock_name": stock_name,
                "alert_type": "DECISION_SELL",
                "alert_level": "CRITICAL" if overall_signal == "strong_sell" else "WARNING",
                "message": f"决策算法看空信号（{overall_signal}），综合评分{composite_score}分",
                "current_value": composite_score,
                "threshold_value": 40,
                "recommendation": "建议关注卖出或减仓",
                "action_signal": "SELL" if overall_signal == "strong_sell" else "REDUCE",
                "timestamp": timestamp,
                "_source": "决策算法",
                "_sourceKey": "decision",
                "_algo_signals": {k: v.get("signal") for k, v in signals.items()},
            })

        # 2. 单算法强信号预警
        algo_alerts = {
            "magic_wave": {
                "buy_msg": "神奇电波红波（MACD+RSI多头）",
                "sell_msg": "神奇电波绿波（MACD+RSI空头）",
            },
            "anomaly_detect": {
                "buy_msg": "异动拉升信号（放量/连续上涨/大振幅）",
            },
            "bottom_opportunity": {
                "buy_msg": "底部寻机信号（RSI超卖/MACD底背离）",
            },
            "td_sequential": {
                "buy_msg": "TD序列买入Setup完成",
                "sell_msg": "TD序列卖出Setup完成",
            },
            "channel_breakout": {
                "buy_msg": "通道突破上轨",
                "sell_msg": "通道跌破下轨",
            },
        }

        for algo_name, config in algo_alerts.items():
            signal = signals.get(algo_name, {}).get("signal", "neutral")
            if signal == "buy" and "buy_msg" in config:
                alerts.append({
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "alert_type": f"ALGO_{algo_name.upper()}_BUY",
                    "alert_level": "INFO",
                    "message": config["buy_msg"],
                    "current_value": 0,
                    "threshold_value": 0,
                    "recommendation": "关注该算法信号",
                    "action_signal": "ADD",
                    "timestamp": timestamp,
                    "_source": "决策算法",
                    "_sourceKey": "decision",
                    "_algo_detail": signals.get(algo_name),
                })
            elif signal == "sell" and "sell_msg" in config:
                alerts.append({
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "alert_type": f"ALGO_{algo_name.upper()}_SELL",
                    "alert_level": "WARNING",
                    "message": config["sell_msg"],
                    "current_value": 0,
                    "threshold_value": 0,
                    "recommendation": "关注该算法信号",
                    "action_signal": "REDUCE",
                    "timestamp": timestamp,
                    "_source": "决策算法",
                    "_sourceKey": "decision",
                    "_algo_detail": signals.get(algo_name),
                })

        # 3. 持仓感知预警（仅对持仓股）
        if holding_context and holding_context.get("cost_price", 0) > 0:
            cost_price = holding_context["cost_price"]
            position_type = holding_context.get("position_type", "short")
            profit_ratio = holding_context.get("profit_ratio", 0)

            # 持仓类型阈值
            thresholds = {
                "short": {"stop_loss": -5, "take_profit": 10},
                "mid": {"stop_loss": -8, "take_profit": 18},
                "long": {"stop_loss": -12, "take_profit": 30},
            }
            thresh = thresholds.get(position_type, thresholds["short"])

            # 算法信号与持仓状态结合
            if overall_signal in ("sell", "strong_sell") and profit_ratio < 0:
                alerts.append({
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "alert_type": "POSITION_DECISION_SELL",
                    "alert_level": "CRITICAL",
                    "message": f"持仓浮亏{profit_ratio:.1f}%，且决策算法看空，建议止损",
                    "current_value": profit_ratio,
                    "threshold_value": thresh["stop_loss"],
                    "recommendation": f"当前浮亏{profit_ratio:.1f}%，触及{position_type}线止损位",
                    "action_signal": "SELL",
                    "timestamp": timestamp,
                    "_source": "决策算法",
                    "_sourceKey": "decision",
                })
            elif overall_signal in ("buy", "strong_buy") and profit_ratio > thresh["take_profit"]:
                alerts.append({
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "alert_type": "POSITION_DECISION_HOLD",
                    "alert_level": "INFO",
                    "message": f"持仓浮盈{profit_ratio:.1f}%，且决策算法看多，建议继续持有",
                    "current_value": profit_ratio,
                    "threshold_value": thresh["take_profit"],
                    "recommendation": f"当前浮盈{profit_ratio:.1f}%，达到{position_type}线止盈位，但算法仍看多",
                    "action_signal": "HOLD",
                    "timestamp": timestamp,
                    "_source": "决策算法",
                    "_sourceKey": "decision",
                })

        return alerts

    def monitor_stocks(
        self,
        stock_list: list[dict],
        holding_context_map: Optional[dict] = None,
    ) -> dict:
        """批量监控股票，返回预警结果
        
        Args:
            stock_list: 股票列表 [{"code": "600519", "name": "贵州茅台"}, ...]
            holding_context_map: 持仓上下文 {"600519": {"cost_price": 1800, "position_type": "long", ...}}
        
        Returns:
            {"alerts": [...], "stocks": [...], "summary": {...}}
        """
        from app.core.pytdx_source import pytdx_data

        all_alerts = []
        stock_results = []

        for stock in stock_list:
            code = stock.get("code", "")
            name = stock.get("name", code)
            if len(code) != 6:
                continue

            try:
                klines = pytdx_data.get_kline(code, period=4, count=250)
                if not klines or len(klines) < 30:
                    continue

                formatted = self._format_klines(klines)
                signals = self._run_algos(formatted)
                composite_score, overall_signal, buy_count, sell_count = self._calc_composite_score(signals)

                holding_ctx = holding_context_map.get(code) if holding_context_map else None
                alerts = self._generate_alerts(code, name, signals, composite_score, overall_signal, holding_ctx)
                all_alerts.extend(alerts)

                stock_results.append({
                    "code": code,
                    "name": name,
                    "composite_score": composite_score,
                    "overall_signal": overall_signal,
                    "buy_signal_count": buy_count,
                    "sell_signal_count": sell_count,
                    "signals": {k: v.get("signal") for k, v in signals.items()},
                })
            except Exception as e:
                logger.debug(f"决策算法监控失败 ({code}): {e}")

        return {
            "alerts": all_alerts,
            "stocks": stock_results,
            "summary": {
                "total": len(stock_results),
                "alert_count": len(all_alerts),
                "buy_signals": sum(1 for s in stock_results if s["overall_signal"] in ("buy", "strong_buy")),
                "sell_signals": sum(1 for s in stock_results if s["overall_signal"] in ("sell", "strong_sell")),
            },
        }


# 全局单例
decision_alert_service = DecisionAlertService()
