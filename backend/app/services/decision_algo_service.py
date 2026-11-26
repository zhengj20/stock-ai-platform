"""决策中心算法服务：TD序列/均线雷达/通道突破/神奇电波/异动拉升"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _get_market_prefix(code: str) -> tuple[int, int]:
    """返回(市场代码, 股票代码数字)"""
    if code.startswith("6"):
        return 1, int(code)
    return 0, int(code)


class TDSequentialAlgo:
    """TD Sequential (汤姆·迪马克序列)

    通过识别9根连续看涨/看跌K线来预测趋势反转。
    买入信号：连续9根K线的收盘价低于4根前的收盘价
    卖出信号：连续9根K线的收盘价高于4根前的收盘价
    """

    @staticmethod
    def analyze(klines: list[dict]) -> dict:
        if not klines or len(klines) < 13:
            return {"setup": None, "countdown": None, "signal": "neutral"}

        closes = [k["close"] for k in klines]

        # 计算买入Setup（看跌反转）：连续9根收盘价 < 4根前收盘
        buy_setup_count = 0
        for i in range(len(closes) - 1, 3, -1):
            if closes[i] < closes[i - 4]:
                buy_setup_count += 1
                if buy_setup_count == 9:
                    break
            else:
                break

        # 计算卖出Setup（看涨反转）：连续9根收盘价 > 4根前收盘
        sell_setup_count = 0
        for i in range(len(closes) - 1, 3, -1):
            if closes[i] > closes[i - 4]:
                sell_setup_count += 1
                if sell_setup_count == 9:
                    break
            else:
                break

        setup = None
        signal = "neutral"

        if buy_setup_count >= 9:
            setup = {"type": "buy", "count": min(buy_setup_count, 13)}
            signal = "buy"
        elif sell_setup_count >= 9:
            setup = {"type": "sell", "count": min(sell_setup_count, 13)}
            signal = "sell"
        elif buy_setup_count >= 5 or sell_setup_count >= 5:
            setup = {
                "type": "buy" if buy_setup_count > sell_setup_count else "sell",
                "count": max(buy_setup_count, sell_setup_count),
            }

        # Countdown信号（在Setup完成后）
        countdown = None
        if setup and setup["count"] == 9:
            start_idx = len(closes) - 13
            if start_idx >= 0:
                if setup["type"] == "buy":
                    cd_count = sum(
                        1 for i in range(start_idx, min(start_idx + 13, len(closes)))
                        if closes[i] < closes[max(0, i - 9)]
                    )
                else:
                    cd_count = sum(
                        1 for i in range(start_idx, min(start_idx + 13, len(closes)))
                        if closes[i] > closes[max(0, i - 9)]
                    )
                if cd_count >= 1:
                    countdown = {"count": min(cd_count, 13)}
                    signal = setup["type"]

        return {
            "setup": setup,
            "countdown": countdown,
            "signal": signal,
            "buy_setup_progress": buy_setup_count,
            "sell_setup_progress": sell_setup_count,
        }


class MARadarAlgo:
    """均线雷达：多周期均线排列分析

    判断MA5/10/20/30/60/120/250的排列状态，识别多头/空头/震荡格局。
    """

    @staticmethod
    def analyze(klines: list[dict]) -> dict:
        if not klines or len(klines) < 250:
            return {"trend": "unknown", "ma_alignment": "neutral"}

        closes = [k["close"] for k in klines]
        periods = [5, 10, 20, 30, 60, 120, 250]
        mas = {}

        for p in periods:
            if len(closes) >= p:
                ma_val = sum(closes[-p:]) / p
                mas[p] = round(ma_val, 2)

        if not mas:
            return {"trend": "unknown", "ma_alignment": "neutral"}

        current_price = closes[-1]
        ma_values = list(mas.values())
        ma_keys = list(mas.keys())

        # 判断多头排列：短周期均线 > 长周期均线
        bullish_count = sum(
            1 for i in range(len(ma_values) - 1) if ma_values[i] > ma_values[i + 1]
        )
        bearish_count = len(ma_values) - 1 - bullish_count

        # 价格在所有短期均线之上
        price_above_short_ma = sum(
            1 for p in [5, 10, 20] if current_price > mas.get(p, 0)
        )

        if bullish_count >= 4 and price_above_short_ma >= 3:
            trend = "strong_bullish"
            alignment = "bullish_alignment"
        elif bullish_count >= 3:
            trend = "bullish"
            alignment = "partial_bullish"
        elif bearish_count >= 4:
            trend = "bearish"
            alignment = "bearish_alignment"
        else:
            trend = "sideways"
            alignment = "mixed"

        # 均线发散度（短期vs长期）
        divergence = 0
        if mas.get(5) and mas.get(250):
            divergence = round((mas[5] / mas[250] - 1) * 100, 2)

        # 信号判断：多头趋势买入，空头趋势卖出
        signal = "neutral"
        if trend in ("strong_bullish", "bullish"):
            signal = "buy"
        elif trend == "bearish":
            signal = "sell"

        return {
            "signal": signal,
            "trend": trend,
            "ma_alignment": alignment,
            "ma_values": mas,
            "current_price": current_price,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "divergence_pct": divergence,
        }


class ChannelBreakoutAlgo:
    """通道突破：基于Donchian Channel的突破检测

    使用N日最高/最低价构建通道，检测价格突破上轨（买入）或下轨（卖出）。
    """

    @staticmethod
    def analyze(klines: list[dict], period: int = 20) -> dict:
        if not klines or len(klines) < period + 1:
            return {"signal": "neutral", "breakout": None}

        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        closes = [k["close"] for k in klines]

        # Donchian Channel
        upper_band = max(highs[-period:])
        lower_band = min(lows[-period:])
        mid_band = (upper_band + lower_band) / 2

        current_price = closes[-1]
        prev_price = closes[-2] if len(closes) > 1 else current_price

        # 突破检测
        breakout = None
        signal = "neutral"

        if prev_price <= upper_band and current_price > upper_band:
            breakout = {"type": "upper", "price": round(upper_band, 2)}
            signal = "buy"
        elif prev_price >= lower_band and current_price < lower_band:
            breakout = {"type": "lower", "price": round(lower_band, 2)}
            signal = "sell"

        # 通道宽度（波动率指标）
        channel_width = round((upper_band - lower_band) / mid_band * 100, 2) if mid_band else 0

        # 价格在通道中的位置 (0-100%)
        position_in_channel = 0
        if upper_band != lower_band:
            position_in_channel = round(
                (current_price - lower_band) / (upper_band - lower_band) * 100, 1
            )

        # 回踩确认检测：突破上轨后回踩不破中轨，或跌破下轨后反弹不破中轨
        pullback_confirm = None
        if len(closes) >= 3:
            # 上轨突破后回踩确认
            if current_price > mid_band and prev_price <= mid_band and closes[-3] > upper_band:
                pullback_confirm = {"type": "upper_pullback", "status": "confirmed"}
            # 下轨跌破后反弹确认
            elif current_price < mid_band and prev_price >= mid_band and closes[-3] < lower_band:
                pullback_confirm = {"type": "lower_pullback", "status": "confirmed"}

        return {
            "signal": signal,
            "breakout": breakout,
            "upper_band": round(upper_band, 2),
            "lower_band": round(lower_band, 2),
            "mid_band": round(mid_band, 2),
            "channel_width_pct": channel_width,
            "position_in_channel": position_in_channel,
            "period": period,
            "pullback_confirm": pullback_confirm,
        }


class MagicWaveAlgo:
    """神奇电波：基于MACD+RSI的复合趋势指标

    红波（多头）：MACD金叉且RSI>50
    绿波（空头）：MACD死叉且RSI<50
    强度分级：强/中/弱
    """

    @staticmethod
    def _calc_macd(closes: list[float], fast=12, slow=26, signal=9) -> dict:
        if len(closes) < slow + signal:
            return {"macd_line": 0, "signal_line": 0, "histogram": 0, "prev_histogram": 0}

        # EMA计算
        def ema(data: list[float], period: int) -> list[float]:
            result = []
            multiplier = 2 / (period + 1)
            avg = sum(data[:period]) / period
            result.append(avg)
            for price in data[period:]:
                val = (price - avg) * multiplier + avg
                avg = val
                result.append(val)
            return result

        ema_fast = ema(closes, fast)
        ema_slow = ema(closes, slow)

        macd_line_list = [f - s for f, s in zip(ema_fast[slow - 1:], ema_slow)]
        signal_line_list = ema(macd_line_list, signal)

        if len(signal_line_list) < 2:
            return {"macd_line": 0, "signal_line": 0, "histogram": 0, "prev_histogram": 0}

        macd_val = macd_line_list[-1]
        signal_val = signal_line_list[-1]
        hist = macd_val - signal_val
        prev_hist = macd_line_list[-2] - signal_line_list[-2] if len(signal_line_list) >= 2 else 0

        return {
            "macd_line": round(macd_val, 4),
            "signal_line": round(signal_val, 4),
            "histogram": round(hist, 4),
            "prev_histogram": round(prev_hist, 4),
        }

    @staticmethod
    def _calc_rsi(closes: list[float], period=14) -> float:
        if len(closes) < period + 1:
            return 50.0

        gains = []
        losses = []
        for i in range(-period, 0):
            change = closes[i] - closes[i - 1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        for i in range(-period - 1, 0):
            change = closes[i] - closes[i - 1]
            avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    @staticmethod
    def analyze(klines: list[dict]) -> dict:
        if not klines or len(klines) < 35:
            return {"wave": "neutral", "strength": "none"}

        closes = [k["close"] for k in klines]
        macd = MagicWaveAlgo._calc_macd(closes)
        rsi = MagicWaveAlgo._calc_rsi(closes)

        # 金叉/死叉判断
        golden_cross = macd["histogram"] > 0 and macd["prev_histogram"] <= 0
        death_cross = macd["histogram"] < 0 and macd["prev_histogram"] >= 0
        histogram_expanding = abs(macd["histogram"]) > abs(macd["prev_histogram"])

        wave = "neutral"
        strength = "none"

        if golden_cross and rsi > 50:
            wave = "red"
            strength = "strong" if rsi > 60 else "medium"
        elif macd["histogram"] > 0 and rsi > 50:
            wave = "red"
            strength = (
                "strong" if histogram_expanding and rsi > 60 else "medium" if rsi > 55 else "weak"
            )
        elif death_cross and rsi < 50:
            wave = "green"
            strength = "strong" if rsi < 40 else "medium"
        elif macd["histogram"] < 0 and rsi < 50:
            wave = "green"
            strength = (
                "strong" if histogram_expanding and rsi < 40 else "medium" if rsi < 45 else "weak"
            )

        signal = "buy" if wave == "red" else ("sell" if wave == "green" else "neutral")

        return {
            "wave": wave,
            "strength": strength,
            "signal": signal,
            "macd": macd,
            "rsi": rsi,
            "golden_cross": golden_cross,
            "death_cross": death_cross,
        }


class AnomalyDetectAlgo:
    """异动拉升：检测异常放量/价格突变

    检测条件（满足任一即触发）：
    1. 当日涨幅>5%且成交量>20日均量*2
    2. 3日累计涨幅>8%
    3. 盘中振幅>7%且收盘在高位
    """

    @staticmethod
    def analyze(klines: list[dict]) -> dict:
        if not klines or len(klines) < 21:
            return {"signal": "neutral", "anomaly_type": None}

        closes = [k["close"] for k in klines]
        volumes = [k.get("volume", 0) for k in klines]
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]

        current = klines[-1]
        prev_close = closes[-2] if len(closes) > 1 else closes[-1]

        # 当日涨幅
        daily_change_pct = ((current["close"] - prev_close) / prev_close * 100) if prev_close else 0

        # 20日均量
        avg_volume_20 = sum(volumes[-20:]) / 20 if volumes else 0
        volume_ratio = current.get("volume", 0) / avg_volume_20 if avg_volume_20 else 0

        # 3日累计涨幅
        three_day_change = 0
        if len(closes) >= 4:
            three_day_change = (closes[-1] - closes[-4]) / closes[-4] * 100

        # 盘中振幅
        amplitude_pct = ((highs[-1] - lows[-1]) / prev_close * 100) if prev_close else 0

        # 收盘位置（相对当日高低）
        close_position = 0
        if highs[-1] != lows[-1]:
            close_position = (closes[-1] - lows[-1]) / (highs[-1] - lows[-1]) * 100

        anomaly_type = None
        signal = "neutral"
        strength = "none"

        # 条件1：放量拉升
        if daily_change_pct > 5 and volume_ratio > 2:
            anomaly_type = "volume_surge"
            signal = "buy"
            strength = "strong" if daily_change_pct > 7 else "medium"

        # 条件2：连续上涨
        elif three_day_change > 8:
            anomaly_type = "continuous_rise"
            signal = "buy"
            strength = "strong" if three_day_change > 12 else "medium"

        # 条件3：大振幅高位收盘
        elif amplitude_pct > 7 and close_position > 75:
            anomaly_type = "high_amplitude"
            signal = "buy"
            strength = "medium"

        return {
            "signal": signal,
            "anomaly_type": anomaly_type,
            "strength": strength,
            "daily_change_pct": round(daily_change_pct, 2),
            "volume_ratio": round(volume_ratio, 2),
            "three_day_change_pct": round(three_day_change, 2),
            "amplitude_pct": round(amplitude_pct, 2),
            "close_position_pct": round(close_position, 1),
        }


class BottomOpportunityAlgo:
    """底部寻机：识别超跌反弹机会

    综合RSI超卖、MACD底背离、缩量企稳等信号判断底部区域。
    """

    @staticmethod
    def analyze(klines: list[dict]) -> dict:
        if not klines or len(klines) < 50:
            return {"signal": "neutral", "bottom_score": 0}

        closes = [k["close"] for k in klines]
        volumes = [k.get("volume", 0) for k in klines]

        # RSI超卖检测
        rsi = MagicWaveAlgo._calc_rsi(closes)
        rsi_oversold = rsi < 30

        # MACD底背离：价格新低但MACD未新低
        macd_current = MagicWaveAlgo._calc_macd(closes[-20:])
        price_new_low = closes[-1] < min(closes[-20:-5]) if len(closes) >= 20 else False

        # 缩量企稳：近期成交量低于均量
        avg_vol_20 = sum(volumes[-20:]) / 20
        recent_vol_avg = sum(volumes[-5:]) / 5
        shrinking_volume = recent_vol_avg < avg_vol_20 * 0.7

        # 下跌幅度（从近期高点）
        recent_high = max(closes[-30:]) if len(closes) >= 30 else closes[-1]
        drop_from_high = (recent_high - closes[-1]) / recent_high * 100

        # 底部评分（0-100）
        bottom_score = 0
        signals_list = []

        if rsi_oversold:
            bottom_score += 30
            signals_list.append("rsi_oversold")
        elif rsi < 40:
            bottom_score += 15
            signals_list.append("rsi_low")

        if shrinking_volume:
            bottom_score += 20
            signals_list.append("shrinking_volume")

        if drop_from_high > 20:
            bottom_score += 20
            signals_list.append("deep_drop")
        elif drop_from_high > 15:
            bottom_score += 10
            signals_list.append("moderate_drop")

        if macd_current["histogram"] > 0:
            bottom_score += 15
            signals_list.append("macd_positive")

        # 价格企稳（最近3日不再创新低）
        if len(closes) >= 3:
            last_3_lows = closes[-3:]
            if last_3_lows[-1] > min(last_3_lows[:-1]):
                bottom_score += 15
                signals_list.append("price_stabilizing")

        signal = "neutral"
        strength = "none"
        if bottom_score >= 60:
            signal = "buy"
            strength = "strong"
        elif bottom_score >= 40:
            signal = "buy"
            strength = "medium"
        elif bottom_score >= 25:
            signal = "buy"
            strength = "weak"

        return {
            "signal": signal,
            "bottom_score": min(bottom_score, 100),
            "strength": strength,
            "signals": signals_list,
            "rsi": rsi,
            "drop_from_high_pct": round(drop_from_high, 2),
            "shrinking_volume": shrinking_volume,
        }


class TrendStrengthAlgo:
    """趋势强度评分：综合ADX+均线斜率+波动率

    输出0-100的趋势强度分，帮助判断是否适合趋势跟踪策略。
    """

    @staticmethod
    def analyze(klines: list[dict]) -> dict:
        if not klines or len(klines) < 30:
            return {"strength": 0, "trend_direction": "unknown"}

        closes = [k["close"] for k in klines]

        # ADX简化计算（方向性指数）
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]

        plus_dm = []
        minus_dm = []
        tr_list = []

        for i in range(1, len(klines)):
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]
            plus_dm.append(max(up_move, 0) if up_move > down_move else 0)
            minus_dm.append(max(down_move, 0) if down_move > up_move else 0)
            tr_list.append(
                max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            )

        period = 14
        if len(plus_dm) < period:
            return {"strength": 0, "trend_direction": "unknown"}

        avg_plus_dm = sum(plus_dm[-period:]) / period
        avg_minus_dm = sum(minus_dm[-period:]) / period
        avg_tr = sum(tr_list[-period:]) / period

        di_plus = (avg_plus_dm / avg_tr * 100) if avg_tr else 0
        di_minus = (avg_minus_dm / avg_tr * 100) if avg_tr else 0

        dx = abs(di_plus - di_minus) / (di_plus + di_minus) * 100 if (di_plus + di_minus) else 0

        # 均线斜率（MA5 vs MA20）
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        slope_pct = ((ma5 - ma20) / ma20 * 100) if ma20 else 0

        # 综合强度分
        strength_score = min(100, int(dx * 1.5 + abs(slope_pct) * 5))

        direction = "bullish" if slope_pct > 0 else "bearish"

        # 信号判断：强度>60且多头方向买入，强度>60且空头方向卖出
        signal = "neutral"
        if strength_score >= 60:
            signal = "buy" if direction == "bullish" else "sell"
        elif strength_score >= 40:
            signal = "buy" if direction == "bullish" and dx > 20 else "sell" if direction == "bearish" and dx > 20 else "neutral"

        return {
            "signal": signal,
            "strength": strength_score,
            "trend_direction": direction,
            "adx": round(dx, 2),
            "di_plus": round(di_plus, 2),
            "di_minus": round(di_minus, 2),
            "ma_slope_pct": round(slope_pct, 2),
        }
