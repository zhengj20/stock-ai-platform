"""
统一因子引擎 — 所有Tab共享的指标计算 + 评分系统

设计原则：
1. 单一实现：KDJ/RSI/MACD等指标只在此处实现，全项目复用
2. 标准化输出：所有因子归一化到 0~100 分
3. 策略模板：预定义多套权重配置，按策略类型切换
"""

import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# =====================================================
# 技术指标计算（单一实现）
# =====================================================

class Indicators:
    """技术指标计算器 — 标准算法，全项目复用"""

    @staticmethod
    def ema(data, period):
        if not data or len(data) < period:
            return sum(data) / len(data) if data else 0.0
        multiplier = 2.0 / (period + 1)
        ema_val = sum(data[:period]) / period
        for price in data[period:]:
            ema_val = (price - ema_val) * multiplier + ema_val
        return ema_val

    @staticmethod
    def sma(data, period):
        if len(data) < period:
            return sum(data) / len(data) if data else 0.0
        return sum(data[-period:]) / period

    @staticmethod
    def macd(closes):
        if len(closes) < 26:
            return None
        ema12 = Indicators.ema(closes, 12)
        ema26 = Indicators.ema(closes, 26)
        dif = ema12 - ema26
        all_dif = []
        for i in range(12, len(closes)):
            e12 = Indicators.ema(closes[:i + 1], 12)
            e26 = Indicators.ema(closes[:i + 1], 26) if i >= 25 else e12
            all_dif.append(e12 - e26)
        dea = None
        macd_bar = 0.0
        prev_dif = None
        prev_dea = None
        if len(all_dif) >= 9:
            dea = Indicators.ema(all_dif, 9)
            macd_bar = 2 * (dif - dea)
            if len(all_dif) >= 2:
                prev_dif = all_dif[-2]
                prev_all_dif = all_dif[:-1]
                prev_dea = Indicators.ema(prev_all_dif, 9) if len(prev_all_dif) >= 9 else dea
        signal = "none"
        if prev_dif is not None and prev_dea is not None:
            if dif > 0 and prev_dif <= 0:
                signal = "golden_cross"
            elif dif < 0 and prev_dif >= 0:
                signal = "death_cross"
            elif macd_bar > 0 and dea is not None and (prev_dea or 0) < dea:
                signal = "bullish"
            elif macd_bar < 0 and dea is not None and (prev_dea or 0) > dea:
                signal = "bearish"
        return {"dif": round(dif, 4), "dea": round(dea, 4) if dea else None, "macd_bar": round(macd_bar, 4), "signal": signal}

    @staticmethod
    def rsi(closes, period=6):
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        avg_gain = sum(max(d, 0) for d in deltas[:period]) / period
        avg_loss = sum(max(-d, 0) for d in deltas[:period]) / period
        for i in range(period, len(deltas)):
            gain = max(deltas[i], 0)
            loss = max(-deltas[i], 0)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - 100.0 / (1.0 + rs), 1)

    @staticmethod
    def kdj(closes, highs, lows, period=9):
        if len(closes) < period or len(highs) < period or len(lows) < period:
            return None
        k_val = 50.0
        d_val = 50.0
        for i in range(period - 1, len(closes)):
            low_n = min(lows[i - period + 1:i + 1])
            high_n = max(highs[i - period + 1:i + 1])
            rsv = (closes[i] - low_n) / (high_n - low_n) * 100 if (high_n - low_n) > 0 else 50.0
            k_val = (2.0 / 3.0) * k_val + (1.0 / 3.0) * rsv
            d_val = (2.0 / 3.0) * d_val + (1.0 / 3.0) * k_val
        j_val = 3.0 * k_val - 2.0 * d_val
        signal = "none"
        if len(closes) >= period + 1:
            prev_k = 50.0
            prev_d = 50.0
            for i in range(period - 1, len(closes) - 1):
                low_n = min(lows[i - period + 1:i + 1])
                high_n = max(highs[i - period + 1:i + 1])
                rsv = (closes[i] - low_n) / (high_n - low_n) * 100 if (high_n - low_n) > 0 else 50.0
                prev_k = (2.0 / 3.0) * prev_k + (1.0 / 3.0) * rsv
                prev_d = (2.0 / 3.0) * prev_d + (1.0 / 3.0) * prev_k
            if k_val > d_val and prev_k <= prev_d:
                signal = "golden_cross"
            elif k_val < d_val and prev_k >= prev_d:
                signal = "death_cross"
        return {"k": round(k_val, 1), "d": round(d_val, 1), "j": round(j_val, 1), "signal": signal}

    @staticmethod
    def boll(closes, period=20, std_dev=2.0):
        if len(closes) < period:
            return None
        mid = Indicators.sma(closes, period)
        variance = sum((x - mid) ** 2 for x in closes[-period:]) / period
        std = math.sqrt(variance)
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        bandwidth = (upper - lower) / mid * 100 if mid > 0 else 0
        price_pos = 50.0
        if upper != lower:
            price_pos = (closes[-1] - lower) / (upper - lower) * 100
        return {"upper": round(upper, 2), "mid": round(mid, 2), "lower": round(lower, 2), "bandwidth": round(bandwidth, 2), "price_position": round(min(100, max(0, price_pos)), 1)}

    @staticmethod
    def volume_ratio(volumes, short_period=5, long_period=20):
        if not volumes or len(volumes) < short_period:
            return 1.0
        avg_short = sum(volumes[-short_period:]) / short_period
        avg_long = sum(volumes[-long_period:]) / long_period if len(volumes) >= long_period else avg_short
        if avg_long == 0:
            return 1.0
        return round(avg_short / avg_long, 2)

    @staticmethod
    def momentum(closes, period=5):
        if len(closes) < period + 1 or closes[-period] == 0:
            return 0.0
        return round((closes[-1] - closes[-period]) / closes[-period] * 100, 2)

    @staticmethod
    def atr(highs, lows, closes, period=14):
        if len(closes) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            trs.append(tr)
        if len(trs) < period:
            return sum(trs) / len(trs) if trs else 0.0
        atr_val = sum(trs[:period]) / period
        for tr in trs[period:]:
            atr_val = (atr_val * (period - 1) + tr) / period
        return round(atr_val, 4)

    @staticmethod
    def max_drawdown(closes, period=60):
        if len(closes) < 2:
            return 0.0
        window = closes[-period:] if len(closes) >= period else closes
        peak = window[0]
        max_dd = 0.0
        for price in window:
            if price > peak:
                peak = price
            dd = (peak - price) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        return round(max_dd, 2)


# =====================================================
# 因子计算（从OHLCV数据提取标准化因子）
# =====================================================

class FactorCalculator:
    """因子计算器 — 接收K线数据，输出标准化因子字典"""

    @staticmethod
    def compute_all(closes, volumes, highs, lows):
        if len(closes) < 20:
            return None
        ma5 = Indicators.sma(closes, 5)
        ma10 = Indicators.sma(closes, 10)
        ma20 = Indicators.sma(closes, 20)
        ma60 = Indicators.sma(closes, 60) if len(closes) >= 60 else None
        macd_info = Indicators.macd(closes)
        rsi6 = Indicators.rsi(closes, 6)
        rsi14 = Indicators.rsi(closes, 14)
        kdj_info = Indicators.kdj(closes, highs, lows)
        boll_info = Indicators.boll(closes)
        vol_ratio = Indicators.volume_ratio(volumes, 5, 20)
        mom_5d = Indicators.momentum(closes, 5)
        mom_10d = Indicators.momentum(closes, 10) if len(closes) >= 11 else 0.0
        mom_20d = Indicators.momentum(closes, 20) if len(closes) >= 21 else 0.0
        atr_val = Indicators.atr(highs, lows, closes)
        max_dd = Indicators.max_drawdown(closes)
        ma_alignment = FactorCalculator._check_ma_alignment(closes[-1], ma5, ma10, ma20, ma60)
        return {
            "ma5": round(ma5, 2), "ma10": round(ma10, 2), "ma20": round(ma20, 2),
            "ma60": round(ma60, 2) if ma60 else None,
            "macd": macd_info, "rsi6": rsi6, "rsi14": rsi14, "kdj": kdj_info,
            "boll": boll_info, "volume_ratio": vol_ratio,
            "momentum_5d": mom_5d, "momentum_10d": mom_10d, "momentum_20d": mom_20d,
            "atr": atr_val, "max_drawdown": max_dd, "ma_alignment": ma_alignment,
        }

    @staticmethod
    def _check_ma_alignment(price, ma5, ma10, ma20, ma60):
        if price > ma5 > ma10 > ma20:
            return "bullish"
        elif price < ma5 < ma10 < ma20:
            return "bearish"
        elif price > ma5 > ma10:
            return "short_bullish"
        elif price < ma5 < ma10:
            return "short_bearish"
        else:
            return "neutral"


# =====================================================
# 标准化评分器（因子 -> 0~100分）
# =====================================================

class StandardScorer:
    PROFILES = {
        "trend_breakout": {
            "momentum_5d": 0.25, "ma_alignment": 0.20, "volume_ratio": 0.15,
            "macd_signal": 0.15, "rsi6": 0.10, "kdj_j": 0.10, "boll_position": 0.05,
        },
        "oversold_bounce": {
            "rsi6": 0.25, "kdj_j": 0.20, "volume_ratio": 0.15,
            "decline_20d": 0.15, "macd_signal": 0.10, "boll_position": 0.10, "momentum_5d": 0.05,
        },
        "capital_resonance": {
            "volume_ratio": 0.20, "macd_signal": 0.20, "momentum_5d": 0.15,
            "ma_alignment": 0.15, "rsi6": 0.10, "kdj_j": 0.10, "boll_position": 0.10,
        },
        "balanced": {
            "momentum_5d": 0.20, "ma_alignment": 0.15, "volume_ratio": 0.15,
            "macd_signal": 0.15, "rsi6": 0.10, "kdj_j": 0.10, "boll_position": 0.08, "stability": 0.07,
        },
    }

    @classmethod
    def score(cls, factors, profile="balanced", extra=None):
        weights = cls.PROFILES.get(profile, cls.PROFILES["balanced"])
        total_weight = sum(weights.values())
        weighted_sum = 0.0
        for factor_name, weight in weights.items():
            raw_score = cls._get_factor_score(factors, factor_name, extra)
            if raw_score is not None:
                weighted_sum += raw_score * weight
        actual_weight = sum(w for f, w in weights.items() if cls._get_factor_score(factors, f, extra) is not None)
        if actual_weight == 0:
            return 50.0
        final = weighted_sum / actual_weight * total_weight
        return round(min(98, max(10, final)), 1)

    @classmethod
    def _get_factor_score(cls, factors, name, extra=None):
        if name == "momentum_5d":
            val = factors.get("momentum_5d")
            if val is None: return None
            return cls._sigmoid_score(val, center=2, scale=5)
        elif name == "ma_alignment":
            alignment = factors.get("ma_alignment", "neutral")
            return {"bullish": 90, "short_bullish": 70, "neutral": 50, "short_bearish": 30, "bearish": 15}.get(alignment, 50)
        elif name == "volume_ratio":
            val = factors.get("volume_ratio", 1.0)
            if 1.0 <= val <= 2.0: return min(95, 60 + (val - 1.0) * 35)
            elif 2.0 < val <= 3.0: return max(40, 80 - (val - 2.0) * 20)
            elif val > 3.0: return max(25, 60 - (val - 3.0) * 15)
            else: return max(20, 40 + val * 20)
        elif name == "macd_signal":
            macd = factors.get("macd")
            if not macd: return None
            base = {"golden_cross": 95, "bullish": 75, "none": 50, "bearish": 30, "death_cross": 15}.get(macd.get("signal", "none"), 50)
            bar = macd.get("macd_bar", 0)
            if bar is not None: base += max(-10, min(10, bar * 20))
            return min(98, max(10, base))
        elif name == "rsi6":
            val = factors.get("rsi6", 50)
            if 40 <= val <= 60: return 80
            elif 30 <= val < 40: return 65
            elif 60 < val <= 70: return 70
            elif val < 20: return 30
            elif val > 80: return 25
            else: return 50
        elif name == "kdj_j":
            kdj = factors.get("kdj")
            if not kdj: return None
            j_val = kdj.get("j", 50)
            base = cls._sigmoid_score(j_val, center=40, scale=20)
            sig = kdj.get("signal", "none")
            if sig == "golden_cross": base = min(98, base + 15)
            elif sig == "death_cross": base = max(10, base - 15)
            return base
        elif name == "boll_position":
            boll = factors.get("boll")
            if not boll: return None
            pos = boll.get("price_position", 50)
            return max(15, 90 - abs(pos - 50) * 1.2)
        elif name == "decline_20d":
            val = (extra or {}).get("decline_20d", factors.get("momentum_20d"))
            if val is None: return None
            decline = val
            if 5 <= decline <= 20: return min(95, 40 + (decline - 5) * 3.7)
            elif decline > 20: return max(30, 80 - (decline - 20) * 3)
            else: return max(15, 30 - decline * 3)
        elif name == "stability":
            atr_val = factors.get("atr", 0)
            price = factors.get("_price") or (factors.get("ma20") or 10)
            if price <= 0: return None
            atr_pct = atr_val / price * 100
            if 2 <= atr_pct <= 5: return 80
            elif atr_pct < 2: return max(40, 60 + atr_pct * 10)
            else: return max(20, 70 - (atr_pct - 5) * 8)
        return None

    @staticmethod
    def _sigmoid_score(value, center=0, scale=10):
        try:
            z = (value - center) / scale
            return round(100.0 / (1.0 + math.exp(-z)), 1)
        except (OverflowError, ValueError):
            return 50.0


# =====================================================
# 量价关系分类器
# =====================================================

class VolumePriceClassifier:
    @staticmethod
    def classify(change_pct, vol_ratio):
        if change_pct < -2 and vol_ratio > 1.1:
            return "底背离", min(95, int(60 + (vol_ratio - 1) * 30 + abs(change_pct) * 2))
        elif change_pct > 2 and vol_ratio < 0.7:
            return "顶背离", min(85, int(40 + (1 - vol_ratio) * 40))
        elif change_pct > 1 and vol_ratio > 1.1:
            return "量价齐升", min(95, int(65 + (vol_ratio - 1) * 20 + change_pct * 2))
        elif change_pct < -0.3 and vol_ratio < 0.7:
            return "缩量回调", min(80, int(50 + (1 - vol_ratio) * 20))
        elif change_pct > 0 and vol_ratio > 1.0:
            return "温和放量", min(85, int(55 + (vol_ratio - 1) * 15 + change_pct))
        elif change_pct < 0 and vol_ratio > 1.0:
            return "放量下跌", min(70, int(40 + (vol_ratio - 1) * 20))
        elif -1 <= change_pct <= 1 and vol_ratio < 0.8:
            return "缩量横盘", min(65, int(40 + (1 - vol_ratio) * 15))
        else:
            return "", 0

    @staticmethod
    def classify_simple(change_pct, vol_ratio):
        rel_type, _ = VolumePriceClassifier.classify(change_pct, vol_ratio)
        return rel_type or "无明显特征"


# =====================================================
# 便捷函数（向后兼容）
# =====================================================

def compute_indicators_from_klines(klines):
    """从K线列表计算全部指标（便捷入口）"""
    if not klines or len(klines) < 20:
        return None
    closes = [k["close"] for k in klines]
    volumes = [k["volume"] for k in klines]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    factors = FactorCalculator.compute_all(closes, volumes, highs, lows)
    if not factors:
        return None
    score = StandardScorer.score(factors, "balanced")
    kdj_j = factors.get("kdj", {}).get("j", 50)
    vol_ratio = factors.get("volume_ratio", 1.0)
    rsi6 = factors.get("rsi6", 50)
    momentum = factors.get("momentum_5d", 0)
    decline_20d = -factors.get("momentum_20d", 0) if factors.get("momentum_20d") else 0.0
    return {
        "score": score,
        "momentum": min(95, max(30, round(50 + momentum * 5, 1))),
        "liquidity": min(90, max(30, round(vol_ratio * 20, 1))),
        "tech": StandardScorer.score(factors, "balanced"),
        "kdj_j": kdj_j,
        "vol_ratio": vol_ratio,
        "rsi6": rsi6,
        "decline_20d": round(decline_20d, 1),
        "factors": factors,
    }


def compute_score_for_strategy(factors, strategy_type="balanced", extra=None):
    """按策略类型计算评分"""
    profile_map = {
        "multi_factor": "trend_breakout",
        "ml_prediction": "balanced",
        "capital_flow": "capital_resonance",
        "low_absorption": "oversold_bounce",
        "volume_price_divergence": "capital_resonance",
    }
    profile = profile_map.get(strategy_type, "balanced")
    return StandardScorer.score(factors, profile, extra)

