#!/usr/bin/env python3
"""
A股K线形态识别系统
==================
基于腾讯/东方财富公开行情接口（免费公开接口，无需 API Key）和pandas实现的经典K线形态自动识别工具。

支持18种经典K线形态的扫描与检测，输出带置信度评分的信号报告。

用法:
    python kline_patterns.py <股票代码> [周期数] [--output report.html] [--report stats.json]
    python kline_patterns.py 000001 200 --direction bullish --min-confidence 0.6
"""

import sys
import json
import re
import time
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any

import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 数据获取层：腾讯行情为主源、东方财富为兜底（免费公开接口，无需任何 API Key）
# ---------------------------------------------------------------------------

_TX_KLINE_PATH = "/appstock/app/fqkline/get"
_TX_SMARTBOX_URL = "https://smartbox.gtimg.cn/s3/"
_TX_HOSTS = ["https://web.ifzq.gtimg.cn", "https://ifzq.gtimg.cn",
             "https://proxy.finance.qq.com/ifzqgtimg"]
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _get(url: str, params: Dict[str, str] = None, headers: Dict[str, str] = None,
         retries: int = 3):
    """
    请求公开行情接口，带退避重试。

    行情源对短时间内的高频请求会直接断开连接（RemoteDisconnected），
    因此做退避重试，并在 HTTPS / HTTP 之间交替重试。
    """
    last_err: Optional[Exception] = None
    merged = dict(_HEADERS)
    if headers:
        merged.update(headers)
    for attempt in range(retries):
        target = url
        if attempt % 2 == 1 and url.startswith("https://"):
            target = "http://" + url[len("https://"):]
        try:
            return requests.get(target, params=params, headers=merged, timeout=20)
        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"行情接口请求失败: {url} -> {last_err}")


def _resolve_code_by_name(name: str) -> Tuple[str, str]:
    """按股票名称检索，返回 (6位代码, 带市场前缀的symbol)"""
    resp = _get(_TX_SMARTBOX_URL, {"v": "3", "q": name, "t": "all"},
                {"Referer": "https://gu.qq.com/"})
    resp.encoding = "gbk"
    hint = resp.text.partition('"')[2].rstrip('"')
    for item in hint.split("^"):
        parts = item.split("~")
        # 格式：市场~代码~名称~拼音~类型，只取A股
        if len(parts) >= 5 and parts[4] == "GP-A":
            return parts[1], parts[0] + parts[1]
    raise RuntimeError(f"未找到股票：{name}")


def _norm_code(stock_code: str) -> Tuple[str, Optional[str]]:
    """归一化为 (6位代码, 显式symbol)；传名称时先检索代码"""
    s = str(stock_code).strip()
    m = re.fullmatch(r"(?i)(sh|sz|bj)?(\d{6})", s)
    if m:
        code = m.group(2)
        return code, (m.group(1).lower() + code) if m.group(1) else None
    return _resolve_code_by_name(s)


def _tx_symbol(code: str) -> str:
    """腾讯行情 symbol：6/5/9 沪，4/8 北交所，其余深市"""
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def _secid(code: str) -> str:
    """东财 secid：1.=沪、0.=深"""
    return f"{'1' if code.startswith(('6', '5', '9')) else '0'}.{code}"


def _fetch_tx_kline(code: str, bars: int, symbol: str = None) -> List[list]:
    """腾讯K线（前复权日线）：日期,开盘,收盘,最高,最低,成交量(手)"""
    symbol = symbol or _tx_symbol(code)
    # 腾讯单次最多 640 根
    param = f"{symbol},day,,,{min(bars, 640)},qfq"
    for host in _TX_HOSTS:
        try:
            resp = _get(host + _TX_KLINE_PATH, {"param": param},
                        {"Referer": "https://gu.qq.com/"}, retries=2)
            node = (resp.json().get("data") or {}).get(symbol) or {}
        except Exception:
            continue
        # 有除权的标的返回 qfqday；从未除权的标的和指数只有 day
        items = node.get("qfqday") or node.get("day") or []
        if items:
            return [list(it[:6]) for it in items]
    return []


def _fetch_em_kline(code: str, bars: int, symbol: str = None) -> List[list]:
    """东财K线（前复权日线），作为腾讯不可用时的兜底"""
    secid = f"{'1' if symbol and symbol[:2] == 'sh' else '0'}.{code}" if symbol else _secid(code)
    try:
        resp = _get(_EM_KLINE_URL, {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101", "fqt": "1", "end": "20500101", "lmt": str(bars), "ut": _EM_UT,
        })
        klines = ((resp.json().get("data") or {}).get("klines")) or []
    except Exception:
        return []
    rows = []
    for line in klines:
        f = line.split(",")
        if len(f) < 6:
            continue
        # 东财列序：日期,开,收,高,低,量 → 与腾讯对齐
        rows.append([f[0], f[1], f[2], f[3], f[4], f[5]])
    return rows


def fetch_kline(stock_code: str, periods: int = 200) -> pd.DataFrame:
    """
    获取A股历史K线数据（前复权日线）。

    Parameters
    ----------
    stock_code : str
        6位股票代码（如 '000001'）或股票名称
    periods : int
        获取最近N个交易日的日K线数据

    Returns
    -------
    pd.DataFrame with columns: date, open, high, low, close, volume（按日期升序）
    """
    code, symbol = _norm_code(stock_code)
    bars = max(int(periods), 3)
    rows = _fetch_tx_kline(code, bars, symbol) or _fetch_em_kline(code, bars, symbol)
    if not rows:
        raise RuntimeError(f"未获取到 {stock_code} 的K线数据")

    df = pd.DataFrame({
        "date": [r[0] for r in rows],
        "open": [r[1] for r in rows],
        "close": [r[2] for r in rows],
        "high": [r[3] for r in rows],
        "low": [r[4] for r in rows],
        "volume": [r[5] for r in rows],
    })
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = df["volume"].fillna(0)

    df = df.dropna(subset=["open", "high", "low", "close"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.drop_duplicates(subset=["date"], keep="last")

    return df.sort_values("date").reset_index(drop=True).tail(bars).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Pattern detection base types
# ---------------------------------------------------------------------------

class PatternSignal:
    """K线形态信号"""

    def __init__(self, name: str, date: Any, direction: str, confidence: float,
                 description: str = "", index: int = -1):
        self.name = name              # 形态名称
        self.date = date              # 出现日期
        self.direction = direction    # 'bullish' / 'bearish' / 'neutral'
        self.confidence = confidence  # 0.0 ~ 1.0
        self.description = description
        self.index = index            # K线在DataFrame中的索引

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "date": str(self.date),
            "direction": self.direction,
            "confidence": round(self.confidence, 2),
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Helper functions for candlestick properties
# ---------------------------------------------------------------------------

def _body(df: pd.DataFrame) -> pd.Series:
    """实体大小（绝对值）"""
    return (df["close"] - df["open"]).abs()


def _body_signed(df: pd.DataFrame) -> pd.Series:
    """带符号的实体（阳>0, 阴<0）"""
    return df["close"] - df["open"]


def _upper_shadow(df: pd.DataFrame) -> pd.Series:
    """上影线长度"""
    return df["high"] - df[["open", "close"]].max(axis=1)


def _lower_shadow(df: pd.DataFrame) -> pd.Series:
    """下影线长度"""
    return df[["open", "close"]].min(axis=1) - df["low"]


def _range(df: pd.DataFrame) -> pd.Series:
    """K线总振幅"""
    return df["high"] - df["low"]


def _is_bullish(df: pd.DataFrame) -> pd.Series:
    """是否为阳线"""
    return df["close"] >= df["open"]


def _is_bearish(df: pd.DataFrame) -> pd.Series:
    """是否为阴线"""
    return df["close"] < df["open"]


def _avg_body(n: int = 20) -> callable:
    """返回计算N日平均实体的函数"""
    def f(df):
        return _body(df).rolling(n, min_periods=1).mean()
    return f


def _trend_direction(df: pd.DataFrame, i: int, lookback: int = 20) -> str:
    """判断i位置处的趋势方向"""
    start = max(0, i - lookback)
    if start >= i:
        return "unknown"
    segment = df.iloc[start:i + 1]
    if len(segment) < 5:
        return "unknown"
    price_change = (segment["close"].iloc[-1] - segment["close"].iloc[0]) / segment["close"].iloc[0]
    if price_change > 0.03:
        return "up"
    elif price_change < -0.03:
        return "down"
    return "flat"


# ---------------------------------------------------------------------------
# Single-candle patterns (单根K线形态)
# ---------------------------------------------------------------------------

def detect_big_yang(df: pd.DataFrame, threshold: float = 0.03) -> List[PatternSignal]:
    """1. 大阳线：实体 > 3%"""
    signals = []
    body_pct = (df["close"] - df["open"]) / df["open"]
    for i in range(len(df)):
        if body_pct.iloc[i] > threshold:
            conf = min(1.0, abs(body_pct.iloc[i]) / 0.06)  # 越大越自信
            signals.append(PatternSignal(
                name="大阳线", date=df["date"].iloc[i], direction="bullish",
                confidence=conf * 0.85,
                description=f"实体涨幅 {body_pct.iloc[i]:.2%}", index=i
            ))
    return signals


def detect_big_yin(df: pd.DataFrame, threshold: float = 0.03) -> List[PatternSignal]:
    """1. 大阴线：实体 < -3%"""
    signals = []
    body_pct = (df["close"] - df["open"]) / df["open"]
    for i in range(len(df)):
        if body_pct.iloc[i] < -threshold:
            conf = min(1.0, abs(body_pct.iloc[i]) / 0.06)
            signals.append(PatternSignal(
                name="大阴线", date=df["date"].iloc[i], direction="bearish",
                confidence=conf * 0.85,
                description=f"实体跌幅 {body_pct.iloc[i]:.2%}", index=i
            ))
    return signals


def detect_doji(df: pd.DataFrame) -> List[PatternSignal]:
    """2. 十字星：开盘≈收盘，上下影线明显"""
    signals = []
    body = _body(df)
    rng = _range(df)
    for i in range(len(df)):
        if rng.iloc[i] == 0:
            continue
        body_ratio = body.iloc[i] / rng.iloc[i]
        upper = _upper_shadow(df).iloc[i]
        lower = _lower_shadow(df).iloc[i]
        shadow_total = upper + lower

        if body_ratio < 0.1 and shadow_total > 0:
            # Check shadows are significant
            shadow_ratio = shadow_total / rng.iloc[i]
            conf = min(1.0, (1 - body_ratio) * 0.7 + shadow_ratio * 0.3)
            direction = "neutral"
            signals.append(PatternSignal(
                name="十字星", date=df["date"].iloc[i], direction=direction,
                confidence=conf * 0.65,
                description=f"实体占比 {body_ratio:.1%}, 上影 {_upper_shadow(df).iloc[i]:.2f}, 下影 {_lower_shadow(df).iloc[i]:.2f}",
                index=i
            ))
    return signals


def detect_hammer(df: pd.DataFrame) -> List[PatternSignal]:
    """3. 锤子线：小实体在顶部，长下影线"""
    signals = []
    body = _body(df)
    upper = _upper_shadow(df)
    lower = _lower_shadow(df)

    for i in range(len(df)):
        if body.iloc[i] == 0:
            continue
        # Lower shadow > 2x body, upper shadow < body
        if lower.iloc[i] >= 2 * body.iloc[i] and upper.iloc[i] <= body.iloc[i]:
            trend = _trend_direction(df, i)
            if trend in ("down", "flat"):
                conf = min(1.0, (lower.iloc[i] / (body.iloc[i] + upper.iloc[i] + lower.iloc[i])) * 0.8 + 0.2)
                signals.append(PatternSignal(
                    name="锤子线", date=df["date"].iloc[i], direction="bullish",
                    confidence=conf * 0.75,
                    description=f"下影线 {lower.iloc[i]:.2f}, 实体 {body.iloc[i]:.2f}", index=i
                ))
    return signals


def detect_inverted_hammer(df: pd.DataFrame) -> List[PatternSignal]:
    """3. 倒锤子线：小实体在底部，长上影线"""
    signals = []
    body = _body(df)
    upper = _upper_shadow(df)
    lower = _lower_shadow(df)

    for i in range(len(df)):
        if body.iloc[i] == 0:
            continue
        if upper.iloc[i] >= 2 * body.iloc[i] and lower.iloc[i] <= body.iloc[i]:
            trend = _trend_direction(df, i)
            if trend in ("down", "flat"):
                conf = min(1.0, (upper.iloc[i] / (body.iloc[i] + upper.iloc[i] + lower.iloc[i])) * 0.8 + 0.2)
                signals.append(PatternSignal(
                    name="倒锤子线", date=df["date"].iloc[i], direction="bullish",
                    confidence=conf * 0.65,
                    description=f"上影线 {upper.iloc[i]:.2f}, 实体 {body.iloc[i]:.2f}", index=i
                ))
    return signals


def detect_hanging_man(df: pd.DataFrame) -> List[PatternSignal]:
    """4. 上吊线：锤子形态出现在上涨趋势中"""
    signals = []
    body = _body(df)
    upper = _upper_shadow(df)
    lower = _lower_shadow(df)

    for i in range(len(df)):
        if body.iloc[i] == 0:
            continue
        if lower.iloc[i] >= 2 * body.iloc[i] and upper.iloc[i] <= body.iloc[i]:
            trend = _trend_direction(df, i)
            if trend == "up":
                conf = min(1.0, (lower.iloc[i] / (body.iloc[i] + upper.iloc[i] + lower.iloc[i])) * 0.8 + 0.2)
                signals.append(PatternSignal(
                    name="上吊线", date=df["date"].iloc[i], direction="bearish",
                    confidence=conf * 0.7,
                    description=f"上涨趋势中的锤子形态，下影 {lower.iloc[i]:.2f}", index=i
                ))
    return signals


def detect_shooting_star(df: pd.DataFrame) -> List[PatternSignal]:
    """4. 射击之星：倒锤形态出现在上涨趋势中"""
    signals = []
    body = _body(df)
    upper = _upper_shadow(df)
    lower = _lower_shadow(df)

    for i in range(len(df)):
        if body.iloc[i] == 0:
            continue
        if upper.iloc[i] >= 2 * body.iloc[i] and lower.iloc[i] <= body.iloc[i]:
            trend = _trend_direction(df, i)
            if trend == "up":
                conf = min(1.0, (upper.iloc[i] / (body.iloc[i] + upper.iloc[i] + lower.iloc[i])) * 0.8 + 0.2)
                signals.append(PatternSignal(
                    name="射击之星", date=df["date"].iloc[i], direction="bearish",
                    confidence=conf * 0.75,
                    description=f"上涨趋势中的倒锤形态，上影 {upper.iloc[i]:.2f}", index=i
                ))
    return signals


def detect_spinning_top(df: pd.DataFrame) -> List[PatternSignal]:
    """5. 纺锤线：小实体+长上下影线"""
    signals = []
    body = _body(df)
    rng = _range(df)

    for i in range(len(df)):
        if rng.iloc[i] == 0:
            continue
        body_ratio = body.iloc[i] / rng.iloc[i]
        upper = _upper_shadow(df).iloc[i]
        lower = _lower_shadow(df).iloc[i]

        # Small body (<30% of range) and both shadows significant
        if body_ratio < 0.3 and upper > 0 and lower > 0:
            shadow_ratio = (upper + lower) / rng.iloc[i]
            conf = min(1.0, shadow_ratio * 0.7 + (1 - body_ratio) * 0.3)
            direction = "neutral"
            signals.append(PatternSignal(
                name="纺锤线", date=df["date"].iloc[i], direction=direction,
                confidence=conf * 0.55,
                description=f"实体占比 {body_ratio:.1%}, 上影 {upper:.2f}, 下影 {lower:.2f}", index=i
            ))
    return signals


def detect_dragonfly_doji(df: pd.DataFrame) -> List[PatternSignal]:
    """6. 蜻蜓十字/T字线：开盘≈收盘≈最高价，长下影线"""
    signals = []
    body = _body(df)
    rng = _range(df)
    lower = _lower_shadow(df)

    for i in range(len(df)):
        if rng.iloc[i] == 0:
            continue
        body_ratio = body.iloc[i] / rng.iloc[i]
        upper = _upper_shadow(df).iloc[i]

        # Open ≈ close ≈ high, long lower shadow
        if body_ratio < 0.1 and upper <= body.iloc[i] * 2 + 0.01:
            if lower.iloc[i] > body.iloc[i] * 3 or (lower.iloc[i] / rng.iloc[i]) > 0.5:
                conf = min(1.0, (lower.iloc[i] / rng.iloc[i]) * 0.8 + 0.2)
                signals.append(PatternSignal(
                    name="蜻蜓十字/T字线", date=df["date"].iloc[i], direction="bullish",
                    confidence=conf * 0.75,
                    description=f"下影 {lower.iloc[i]:.2f}, 实体占比 {body_ratio:.1%}", index=i
                ))
    return signals


def detect_marubozu_bull(df: pd.DataFrame) -> List[PatternSignal]:
    """7. 光头光脚阳线：无上下影线的阳线"""
    signals = []
    for i in range(len(df)):
        o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
        if c >= o and abs(h - c) < 0.01 and abs(l - o) < 0.01:
            body_size = (c - o) / o
            conf = min(1.0, abs(body_size) * 20 + 0.3)
            signals.append(PatternSignal(
                name="光头光脚阳线", date=df["date"].iloc[i], direction="bullish",
                confidence=conf * 0.85,
                description=f"涨幅 {body_size:.2%}", index=i
            ))
    return signals


def detect_marubozu_bear(df: pd.DataFrame) -> List[PatternSignal]:
    """7. 光头光脚阴线：无上下影线的阴线"""
    signals = []
    for i in range(len(df)):
        o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
        if c < o and abs(h - o) < 0.01 and abs(l - c) < 0.01:
            body_size = (c - o) / o
            conf = min(1.0, abs(body_size) * 20 + 0.3)
            signals.append(PatternSignal(
                name="光头光脚阴线", date=df["date"].iloc[i], direction="bearish",
                confidence=conf * 0.85,
                description=f"跌幅 {body_size:.2%}", index=i
            ))
    return signals


# ---------------------------------------------------------------------------
# Two/three-candle patterns (双根/三根K线形态)
# ---------------------------------------------------------------------------

def detect_morning_star(df: pd.DataFrame) -> List[PatternSignal]:
    """8. 早晨之星：阴线 + 小实体星线(向下跳空) + 阳线"""
    signals = []
    body = _body(df)
    for i in range(2, len(df)):
        c0, o0 = df["close"].iloc[i-2], df["open"].iloc[i-2]
        c1, o1 = df["close"].iloc[i-1], df["open"].iloc[i-1]
        c2, o2 = df["close"].iloc[i],   df["open"].iloc[i]

        # First: bearish candle with decent body
        if not (c0 < o0 and abs(c0 - o0) / o0 > 0.01):
            continue
        # Second: small body, gap down
        if body.iloc[i-1] / max(o1, c1) > 0.15:
            continue
        if o1 > min(o0, c0):  # should gap down or at least not gap up significantly
            pass  # allow some flexibility
        # Third: bullish candle that closes into first candle's body
        if not (c2 > o2 and abs(c2 - o2) / o2 > 0.01):
            continue
        midpoint_first = (o0 + c0) / 2
        if c2 < midpoint_first:
            continue

        penetration = (c2 - c0) / (o0 - c0) if (o0 - c0) != 0 else 0
        conf = min(1.0, 0.5 + penetration * 0.3 + (1 - body.iloc[i-1] / max(o1, c1)) * 0.2)

        signals.append(PatternSignal(
            name="早晨之星", date=df["date"].iloc[i], direction="bullish",
            confidence=conf * 0.85,
            description=f"三根K线反转，第三根深入第一根实体 {penetration:.1%}", index=i
        ))
    return signals


def detect_evening_star(df: pd.DataFrame) -> List[PatternSignal]:
    """8. 黄昏之星：阳线 + 小实体星线(向上跳空) + 阴线"""
    signals = []
    body = _body(df)
    for i in range(2, len(df)):
        c0, o0 = df["close"].iloc[i-2], df["open"].iloc[i-2]
        c1, o1 = df["close"].iloc[i-1], df["open"].iloc[i-1]
        c2, o2 = df["close"].iloc[i],   df["open"].iloc[i]

        # First: bullish candle with decent body
        if not (c0 > o0 and abs(c0 - o0) / o0 > 0.01):
            continue
        # Second: small body, gap up
        if body.iloc[i-1] / max(o1, c1) > 0.15:
            continue
        # Third: bearish candle that closes into first candle's body
        if not (c2 < o2 and abs(c2 - o2) / o2 > 0.01):
            continue
        midpoint_first = (o0 + c0) / 2
        if c2 > midpoint_first:
            continue

        penetration = (c0 - c2) / (c0 - o0) if (c0 - o0) != 0 else 0
        conf = min(1.0, 0.5 + penetration * 0.3 + (1 - body.iloc[i-1] / max(o1, c1)) * 0.2)

        signals.append(PatternSignal(
            name="黄昏之星", date=df["date"].iloc[i], direction="bearish",
            confidence=conf * 0.85,
            description=f"三根K线反转，第三根深入第一根实体 {penetration:.1%}", index=i
        ))
    return signals


def detect_bullish_engulfing(df: pd.DataFrame) -> List[PatternSignal]:
    """9. 阳包阴吞没：阴线后出现更大的阳线完全包裹"""
    signals = []
    for i in range(1, len(df)):
        o0, c0 = df["open"].iloc[i-1], df["close"].iloc[i-1]
        o1, c1 = df["open"].iloc[i],   df["close"].iloc[i]

        # First: bearish, Second: bullish and engulfs
        if c0 >= o0 or c1 <= o1:
            continue
        if o1 <= c0 and c1 >= o0:  # second body completely covers first
            engulf_ratio = (c1 - o1) / max(o0 - c0, 0.01)
            conf = min(1.0, 0.5 + min(engulf_ratio, 3) * 0.15)
            signals.append(PatternSignal(
                name="阳包阴吞没", date=df["date"].iloc[i], direction="bullish",
                confidence=conf * 0.82,
                description=f"第二根实体 {c1-o1:.2f} 完全包裹第一根实体 {o0-c0:.2f}", index=i
            ))
    return signals


def detect_bearish_engulfing(df: pd.DataFrame) -> List[PatternSignal]:
    """9. 阴包阳吞没：阳线后出现更大的阴线完全包裹"""
    signals = []
    for i in range(1, len(df)):
        o0, c0 = df["open"].iloc[i-1], df["close"].iloc[i-1]
        o1, c1 = df["open"].iloc[i],   df["close"].iloc[i]

        if c0 <= o0 or c1 >= o1:
            continue
        if o1 >= c0 and c1 <= o0:
            engulf_ratio = (o1 - c1) / max(c0 - o0, 0.01)
            conf = min(1.0, 0.5 + min(engulf_ratio, 3) * 0.15)
            signals.append(PatternSignal(
                name="阴包阳吞没", date=df["date"].iloc[i], direction="bearish",
                confidence=conf * 0.82,
                description=f"第二根实体 {o1-c1:.2f} 完全包裹第一根实体 {c0-o0:.2f}", index=i
            ))
    return signals


def detect_dark_cloud_cover(df: pd.DataFrame) -> List[PatternSignal]:
    """10. 乌云盖顶：阳线后阴线开盘跳空高开，收盘深入50%以上"""
    signals = []
    for i in range(1, len(df)):
        o0, c0 = df["open"].iloc[i-1], df["close"].iloc[i-1]
        o1, c1 = df["open"].iloc[i],   df["close"].iloc[i]

        # First: bullish, Second: bearish with gap up open
        if not (c0 > o0 and c1 < o1):
            continue
        if o1 <= c0:  # no gap up
            continue
        body_first = c0 - o0
        penetration = (o1 - c1) / body_first if body_first > 0 else 0

        if penetration >= 0.5:
            conf = min(1.0, 0.4 + penetration * 0.3 + 0.2)
            signals.append(PatternSignal(
                name="乌云盖顶", date=df["date"].iloc[i], direction="bearish",
                confidence=conf * 0.75,
                description=f"阴线深入阳线实体 {penetration:.1%}", index=i
            ))
    return signals


def detect_piercing_line(df: pd.DataFrame) -> List[PatternSignal]:
    """10. Piercing Line：阴线后阳线开盘跳空低开，收盘深入50%以上"""
    signals = []
    for i in range(1, len(df)):
        o0, c0 = df["open"].iloc[i-1], df["close"].iloc[i-1]
        o1, c1 = df["open"].iloc[i],   df["close"].iloc[i]

        if not (c0 < o0 and c1 > o1):
            continue
        if o1 >= c0:  # no gap down
            continue
        body_first = o0 - c0
        penetration = (c1 - o1) / body_first if body_first > 0 else 0

        if penetration >= 0.5:
            conf = min(1.0, 0.4 + penetration * 0.3 + 0.2)
            signals.append(PatternSignal(
                name="Piercing Line", date=df["date"].iloc[i], direction="bullish",
                confidence=conf * 0.75,
                description=f"阳线深入阴线实体 {penetration:.1%}", index=i
            ))
    return signals


def detect_flat_top(df: pd.DataFrame, tolerance: float = 0.01) -> List[PatternSignal]:
    """11. 平头顶部：相邻K线最高价基本一致"""
    signals = []
    for i in range(1, len(df)):
        h0 = df["high"].iloc[i-1]
        h1 = df["high"].iloc[i]
        if h0 == 0:
            continue
        diff_pct = abs(h1 - h0) / max(h0, h1)
        if diff_pct < tolerance:
            conf = min(1.0, (1 - diff_pct / tolerance) * 0.7 + 0.2)
            signals.append(PatternSignal(
                name="平头顶部", date=df["date"].iloc[i], direction="bearish",
                confidence=conf * 0.65,
                description=f"最高价差 {diff_pct:.3%}, 阻力位 ~{h1:.2f}", index=i
            ))
    return signals


def detect_flat_bottom(df: pd.DataFrame, tolerance: float = 0.01) -> List[PatternSignal]:
    """11. 平头底部：相邻K线最低价基本一致"""
    signals = []
    for i in range(1, len(df)):
        l0 = df["low"].iloc[i-1]
        l1 = df["low"].iloc[i]
        if l0 == 0:
            continue
        diff_pct = abs(l1 - l0) / max(l0, l1)
        if diff_pct < tolerance:
            conf = min(1.0, (1 - diff_pct / tolerance) * 0.7 + 0.2)
            signals.append(PatternSignal(
                name="平头底部", date=df["date"].iloc[i], direction="bullish",
                confidence=conf * 0.65,
                description=f"最低价差 {diff_pct:.3%}, 支撑位 ~{l1:.2f}", index=i
            ))
    return signals


def detect_three_white_soldiers(df: pd.DataFrame) -> List[PatternSignal]:
    """12. 上升三法：大阳线 + 小阴线回调 + 大阳线创新高"""
    # Simplified as "Three White Soldiers" (三连阳) variant of rising three methods
    signals = []
    for i in range(4, len(df)):
        o0, c0 = df["open"].iloc[i-4], df["close"].iloc[i-4]
        o1, c1 = df["open"].iloc[i-3], df["close"].iloc[i-3]
        o2, c2 = df["open"].iloc[i-2], df["close"].iloc[i-2]
        o3, c3 = df["open"].iloc[i-1], df["close"].iloc[i-1]
        o4, c4 = df["open"].iloc[i],   df["close"].iloc[i]

        # First: strong bullish candle
        if not (c0 > o0 and (c0 - o0) / o0 > 0.02):
            continue
        # Middle three: small bearish candles staying above first low
        mid_lows = [df["low"].iloc[i-3], df["low"].iloc[i-2], df["low"].iloc[i-1]]
        if any(l < df["low"].iloc[i-4] for l in mid_lows):
            continue
        # Check middle candles are small and mostly bearish
        avg_mid_body = np.mean([abs(c - o) for c, o in [(c1,o1),(c2,o2),(c3,o3)]])
        first_body = c0 - o0
        if avg_mid_body > first_body * 0.5:
            continue
        # Fifth: strong bullish candle breaking above first high
        if not (c4 > o4 and c4 > df["high"].iloc[i-4]):
            continue

        conf = min(1.0, 0.6 + ((c4 - c0) / c0) * 5)
        signals.append(PatternSignal(
            name="上升三法", date=df["date"].iloc[i], direction="bullish",
            confidence=conf * 0.8,
            description=f"大阳线后三日整理，第五根突破创新高 {c4:.2f}", index=i
        ))
    return signals


def detect_three_black_crows(df: pd.DataFrame) -> List[PatternSignal]:
    """12. 下降三法：大阴线 + 小阳线反弹 + 大阴线创新低"""
    signals = []
    for i in range(4, len(df)):
        o0, c0 = df["open"].iloc[i-4], df["close"].iloc[i-4]
        o1, c1 = df["open"].iloc[i-3], df["close"].iloc[i-3]
        o2, c2 = df["open"].iloc[i-2], df["close"].iloc[i-2]
        o3, c3 = df["open"].iloc[i-1], df["close"].iloc[i-1]
        o4, c4 = df["open"].iloc[i],   df["close"].iloc[i]

        # First: strong bearish candle
        if not (c0 < o0 and abs(c0 - o0) / o0 > 0.02):
            continue
        # Middle three: small bullish candles staying below first high
        mid_highs = [df["high"].iloc[i-3], df["high"].iloc[i-2], df["high"].iloc[i-1]]
        if any(h > df["high"].iloc[i-4] for h in mid_highs):
            continue
        avg_mid_body = np.mean([abs(c - o) for c, o in [(c1,o1),(c2,o2),(c3,o3)]])
        first_body = abs(c0 - o0)
        if avg_mid_body > first_body * 0.5:
            continue
        # Fifth: strong bearish candle breaking below first low
        if not (c4 < o4 and c4 < df["low"].iloc[i-4]):
            continue

        conf = min(1.0, 0.6 + abs((c4 - c0) / c0) * 5)
        signals.append(PatternSignal(
            name="下降三法", date=df["date"].iloc[i], direction="bearish",
            confidence=conf * 0.8,
            description=f"大阴线后三日整理，第五根突破创新低 {c4:.2f}", index=i
        ))
    return signals


# ---------------------------------------------------------------------------
# Multi-candle patterns (多根K线形态)
# ---------------------------------------------------------------------------

def _find_peaks(df: pd.DataFrame, window: int = 5, order: int = 3) -> List[int]:
    """Find local peaks in close prices"""
    # Simple peak detection (no external dependencies beyond pandas/numpy)
    closes = df["close"].values
    peaks = []
    for i in range(window, len(closes) - window):
        is_peak = True
        for j in range(i - window, i + window + 1):
            if j != i and closes[j] >= closes[i]:
                is_peak = False
                break
        if is_peak:
            peaks.append(i)
    return peaks


def _find_troughs(df: pd.DataFrame, window: int = 5, order: int = 3) -> List[int]:
    """Find local troughs in close prices"""
    closes = df["close"].values
    troughs = []
    for i in range(window, len(closes) - window):
        is_trough = True
        for j in range(i - window, i + window + 1):
            if j != i and closes[j] <= closes[i]:
                is_trough = False
                break
        if is_trough:
            troughs.append(i)
    return troughs


def detect_head_shoulders_top(df: pd.DataFrame, window: int = 8) -> List[PatternSignal]:
    """13. 头肩顶：左肩-头部(最高)-右肩，突破颈线"""
    signals = []
    peaks = _find_peaks(df, window=window)

    for k in range(len(peaks) - 2):
        left_shoulder_idx = peaks[k]
        head_idx = peaks[k + 1]
        right_shoulder_idx = peaks[k + 2]

        h_left = df["close"].iloc[left_shoulder_idx]
        h_head = df["close"].iloc[head_idx]
        h_right = df["close"].iloc[right_shoulder_idx]

        # Head must be highest
        if not (h_head > h_left and h_head > h_right):
            continue
        # Shoulders should be roughly equal (within 15%)
        shoulder_diff = abs(h_left - h_right) / max(h_left, h_right)
        if shoulder_diff > 0.15:
            continue

        # Find troughs between shoulders for neckline
        neck_candidates = []
        for i in range(left_shoulder_idx + 1, right_shoulder_idx):
            if df["close"].iloc[i] < min(h_left, h_right) * 0.98:
                neck_candidates.append(df["low"].iloc[i])

        if not neck_candidates:
            continue
        neckline = np.mean(neck_candidates)

        # Check for breakdown below neckline after right shoulder
        post_rs = df.iloc[right_shoulder_idx:]
        if len(post_rs) < 3:
            continue
        min_after = post_rs["low"].min()
        if min_after > neckline:
            continue

        conf = min(1.0, (1 - shoulder_diff / 0.15) * 0.4 + 0.3 + 0.2)
        signals.append(PatternSignal(
            name="头肩顶", date=df["date"].iloc[right_shoulder_idx], direction="bearish",
            confidence=conf * 0.8,
            description=f"左肩 {h_left:.2f}, 头部 {h_head:.2f}, 右肩 {h_right:.2f}, 颈线 ~{neckline:.2f}",
            index=right_shoulder_idx
        ))
    return signals


def detect_head_shoulders_bottom(df: pd.DataFrame, window: int = 8) -> List[PatternSignal]:
    """13. 头肩底：左肩-头部(最低)-右肩，突破颈线"""
    signals = []
    troughs = _find_troughs(df, window=window)

    for k in range(len(troughs) - 2):
        left_idx = troughs[k]
        head_idx = troughs[k + 1]
        right_idx = troughs[k + 2]

        l_left = df["close"].iloc[left_idx]
        l_head = df["close"].iloc[head_idx]
        l_right = df["close"].iloc[right_idx]

        # Head must be lowest
        if not (l_head < l_left and l_head < l_right):
            continue
        shoulder_diff = abs(l_left - l_right) / max(l_left, l_right)
        if shoulder_diff > 0.15:
            continue

        # Neckline from peaks between shoulders
        neck_candidates = []
        for i in range(left_idx + 1, right_idx):
            if df["close"].iloc[i] > max(l_left, l_right) * 1.02:
                neck_candidates.append(df["high"].iloc[i])

        if not neck_candidates:
            continue
        neckline = np.mean(neck_candidates)

        # Check breakout above neckline
        post_rs = df.iloc[right_idx:]
        if len(post_rs) < 3:
            continue
        max_after = post_rs["high"].max()
        if max_after < neckline:
            continue

        conf = min(1.0, (1 - shoulder_diff / 0.15) * 0.4 + 0.3 + 0.2)
        signals.append(PatternSignal(
            name="头肩底", date=df["date"].iloc[right_idx], direction="bullish",
            confidence=conf * 0.8,
            description=f"左肩 {l_left:.2f}, 头部 {l_head:.2f}, 右肩 {l_right:.2f}, 颈线 ~{neckline:.2f}",
            index=right_idx
        ))
    return signals


def detect_double_top(df: pd.DataFrame, window: int = 8) -> List[PatternSignal]:
    """14. 双顶M头：两个相近高点，中间有回调"""
    signals = []
    peaks = _find_peaks(df, window=window)

    for k in range(len(peaks) - 1):
        i1 = peaks[k]
        i2 = peaks[k + 1]

        if i2 - i1 < 5:  # Need enough candles between peaks
            continue

        h1 = df["high"].iloc[i1]
        h2 = df["high"].iloc[i2]

        # Peaks should be at similar levels (within 3%)
        diff_pct = abs(h2 - h1) / max(h1, h2)
        if diff_pct > 0.03:
            continue

        # Check for pullback between peaks
        mid_lows = df["low"].iloc[i1+1:i2].min()
        if mid_lows >= min(h1, h2) * 0.95:
            continue

        # Check breakdown after second peak
        post = df.iloc[i2:]
        if len(post) < 3:
            continue
        trough_between = df["low"].iloc[i1+1:i2].min()
        neckline = trough_between
        min_after = post["low"].min()

        if min_after >= neckline * 0.98:
            # Still valid but not confirmed breakdown - lower confidence
            conf = 0.45
        else:
            conf = min(1.0, 0.6 + (1 - diff_pct / 0.03) * 0.2)

        signals.append(PatternSignal(
            name="双顶M头", date=df["date"].iloc[i2], direction="bearish",
            confidence=conf * 0.75,
            description=f"第一顶 {h1:.2f}, 第二顶 {h2:.2f}, 价差 {diff_pct:.2%}", index=i2
        ))
    return signals


def detect_double_bottom(df: pd.DataFrame, window: int = 8) -> List[PatternSignal]:
    """14. 双底W底：两个相近低点，中间有反弹"""
    signals = []
    troughs = _find_troughs(df, window=window)

    for k in range(len(troughs) - 1):
        i1 = troughs[k]
        i2 = troughs[k + 1]

        if i2 - i1 < 5:
            continue

        l1 = df["low"].iloc[i1]
        l2 = df["low"].iloc[i2]

        diff_pct = abs(l2 - l1) / max(l1, l2)
        if diff_pct > 0.03:
            continue

        mid_highs = df["high"].iloc[i1+1:i2].max()
        if mid_highs <= max(l1, l2) * 1.05:
            continue

        post = df.iloc[i2:]
        if len(post) < 3:
            continue
        peak_between = df["high"].iloc[i1+1:i2].max()
        neckline = peak_between
        max_after = post["high"].max()

        if max_after <= neckline * 1.02:
            conf = 0.45
        else:
            conf = min(1.0, 0.6 + (1 - diff_pct / 0.03) * 0.2)

        signals.append(PatternSignal(
            name="双底W底", date=df["date"].iloc[i2], direction="bullish",
            confidence=conf * 0.75,
            description=f"第一底 {l1:.2f}, 第二底 {l2:.2f}, 价差 {diff_pct:.2%}", index=i2
        ))
    return signals


def detect_symmetrical_triangle(df: pd.DataFrame, window: int = 10) -> List[PatternSignal]:
    """15. 对称三角形：高点下降、低点上升"""
    signals = []
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    # Find multiple peaks and troughs in recent data
    n = len(df)
    if n < 20:
        return signals

    # Look for converging trendlines
    for start in range(0, n - 15):
        segment_h = highs[start:start+15]
        segment_l = lows[start:start+15]

        peaks_local = _find_peaks(df.iloc[start:start+15], window=3)
        troughs_local = _find_troughs(df.iloc[start:start+15], window=3)

        if len(peaks_local) < 2 or len(troughs_local) < 2:
            continue

        # Check descending highs and ascending lows
        peak_vals = [highs[start + p] for p in peaks_local]
        trough_vals = [lows[start + t] for t in troughs_local]

        desc_highs = all(peak_vals[j] > peak_vals[j+1] for j in range(len(peak_vals)-1))
        asc_lows = all(trough_vals[j] < trough_vals[j+1] for j in range(len(trough_vals)-1))

        if desc_highs and asc_lows:
            # Check convergence
            first_range = peak_vals[0] - trough_vals[0]
            last_range = peak_vals[-1] - trough_vals[-1]
            if last_range < first_range * 0.6:
                conf = min(1.0, (1 - last_range / first_range) * 0.7 + 0.2)
                signals.append(PatternSignal(
                    name="对称三角形", date=df["date"].iloc[start + len(peaks_local)], direction="neutral",
                    confidence=conf * 0.65,
                    description=f"高点收敛 {peak_vals[0]:.2f}->{peak_vals[-1]:.2f}, "
                                f"低点收敛 {trough_vals[0]:.2f}->{trough_vals[-1]:.2f}",
                    index=start + len(peaks_local)
                ))
    return signals


def detect_rising_triangle(df: pd.DataFrame, window: int = 10) -> List[PatternSignal]:
    """15. 上升三角形：高点水平、低点上升 → 看涨"""
    signals = []
    n = len(df)
    if n < 20:
        return signals

    highs = df["high"].values
    lows = df["low"].values

    for start in range(0, n - 15):
        segment_h = highs[start:start+15]
        segment_l = lows[start:start+15]

        peaks_local = _find_peaks(df.iloc[start:start+15], window=3)
        troughs_local = _find_troughs(df.iloc[start:start+15], window=3)

        if len(peaks_local) < 2 or len(troughs_local) < 2:
            continue

        peak_vals = [highs[start + p] for p in peaks_local]
        trough_vals = [lows[start + t] for t in troughs_local]

        # Flat highs (within 3%) and ascending lows
        high_range_pct = (max(peak_vals) - min(peak_vals)) / max(peak_vals) if max(peak_vals) > 0 else 1
        asc_lows = all(trough_vals[j] < trough_vals[j+1] for j in range(len(trough_vals)-1))

        if high_range_pct < 0.03 and asc_lows:
            conf = min(1.0, (1 - high_range_pct / 0.03) * 0.5 + 0.3)
            signals.append(PatternSignal(
                name="上升三角形", date=df["date"].iloc[start + len(peaks_local)], direction="bullish",
                confidence=conf * 0.7,
                description=f"高点水平 ~{np.mean(peak_vals):.2f}, 低点上升 {trough_vals[0]:.2f}->{trough_vals[-1]:.2f}",
                index=start + len(peaks_local)
            ))
    return signals


def detect_falling_triangle(df: pd.DataFrame, window: int = 10) -> List[PatternSignal]:
    """15. 下降三角形：高点下降、低点水平 → 看跌"""
    signals = []
    n = len(df)
    if n < 20:
        return signals

    highs = df["high"].values
    lows = df["low"].values

    for start in range(0, n - 15):
        peaks_local = _find_peaks(df.iloc[start:start+15], window=3)
        troughs_local = _find_troughs(df.iloc[start:start+15], window=3)

        if len(peaks_local) < 2 or len(troughs_local) < 2:
            continue

        peak_vals = [highs[start + p] for p in peaks_local]
        trough_vals = [lows[start + t] for t in troughs_local]

        # Descending highs and flat lows
        desc_highs = all(peak_vals[j] > peak_vals[j+1] for j in range(len(peak_vals)-1))
        low_range_pct = (max(trough_vals) - min(trough_vals)) / max(trough_vals) if max(trough_vals) > 0 else 1

        if desc_highs and low_range_pct < 0.03:
            conf = min(1.0, (1 - low_range_pct / 0.03) * 0.5 + 0.3)
            signals.append(PatternSignal(
                name="下降三角形", date=df["date"].iloc[start + len(peaks_local)], direction="bearish",
                confidence=conf * 0.7,
                description=f"高点下降 {peak_vals[0]:.2f}->{peak_vals[-1]:.2f}, 低点水平 ~{np.mean(trough_vals):.2f}",
                index=start + len(peaks_local)
            ))
    return signals


def detect_bull_flag(df: pd.DataFrame, flagpole_len: int = 5, flag_len: int = 8) -> List[PatternSignal]:
    """16. 上升旗形：急涨后小幅回调（向下倾斜通道）"""
    signals = []
    n = len(df)
    if n < flagpole_len + flag_len + 3:
        return signals

    closes = df["close"].values

    for i in range(flagpole_len, n - flag_len):
        # Flagpole: strong upward move
        pole_start_price = closes[i - flagpole_len]
        pole_end_price = closes[i]
        if pole_start_price == 0:
            continue
        pole_pct = (pole_end_price - pole_start_price) / pole_start_price

        if pole_pct < 0.05:  # Need at least 5% move for flagpole
            continue

        # Flag: slight downward consolidation
        flag_segment = closes[i:i + flag_len]
        if len(flag_segment) < 4:
            continue

        flag_start = flag_segment[0]
        flag_end = flag_segment[-1]
        flag_range = max(flag_segment) - min(flag_segment)

        # Flag should be a slight pullback (downward sloping)
        if flag_end >= flag_start * 1.02:
            continue
        # Pullback shouldn't exceed 50% of pole gain
        pullback_pct = (flag_start - flag_end) / flag_start
        if pullback_pct > pole_pct * 0.6:
            continue

        conf = min(1.0, pole_pct * 3 + (1 - pullback_pct / (pole_pct * 0.5)) * 0.2)
        signals.append(PatternSignal(
            name="上升旗形", date=df["date"].iloc[i + flag_len], direction="bullish",
            confidence=conf * 0.7,
            description=f"旗杆涨幅 {pole_pct:.1%}, 旗面回调 {pullback_pct:.1%}",
            index=i + flag_len
        ))
    return signals


def detect_bear_flag(df: pd.DataFrame, flagpole_len: int = 5, flag_len: int = 8) -> List[PatternSignal]:
    """16. 下降旗形：急跌后小幅反弹（向上倾斜通道）"""
    signals = []
    n = len(df)
    if n < flagpole_len + flag_len + 3:
        return signals

    closes = df["close"].values

    for i in range(flagpole_len, n - flag_len):
        pole_start_price = closes[i - flagpole_len]
        pole_end_price = closes[i]
        if pole_start_price == 0:
            continue
        pole_pct = (pole_end_price - pole_start_price) / pole_start_price

        if pole_pct > -0.05:
            continue

        flag_segment = closes[i:i + flag_len]
        if len(flag_segment) < 4:
            continue

        flag_start = flag_segment[0]
        flag_end = flag_segment[-1]

        # Flag should be slight upward consolidation (rebound)
        if flag_end <= flag_start * 0.98:
            continue
        rebound_pct = (flag_end - flag_start) / flag_start
        if rebound_pct > abs(pole_pct) * 0.6:
            continue

        conf = min(1.0, abs(pole_pct) * 3 + (1 - rebound_pct / (abs(pole_pct) * 0.5)) * 0.2)
        signals.append(PatternSignal(
            name="下降旗形", date=df["date"].iloc[i + flag_len], direction="bearish",
            confidence=conf * 0.7,
            description=f"旗杆跌幅 {pole_pct:.1%}, 旗面反弹 {rebound_pct:.1%}",
            index=i + flag_len
        ))
    return signals


def detect_rounding_top(df: pd.DataFrame, window: int = 20) -> List[PatternSignal]:
    """17. 圆弧顶：价格走圆弧轨迹后下跌"""
    signals = []
    n = len(df)
    if n < window * 2:
        return signals

    closes = df["close"].values

    for start in range(0, n - window * 2):
        segment = closes[start:start + window * 2]
        mid = window

        # First half should be rising (or flat), second half falling
        first_half = segment[:mid]
        second_half = segment[mid:]

        if len(first_half) < 5 or len(second_half) < 5:
            continue

        # Check overall arc shape
        rise_pct = (first_half[-1] - first_half[0]) / first_half[0] if first_half[0] > 0 else 0
        fall_pct = (second_half[-1] - second_half[0]) / second_half[0] if second_half[0] > 0 else 0

        # Peak in the middle region
        peak_idx = np.argmax(segment)
        if abs(peak_idx - mid) > window * 0.3:
            continue

        peak_price = segment[peak_idx]
        left_edge = first_half[0]
        right_edge = second_half[-1]

        # Both edges should be lower than peak
        if left_edge >= peak_price * 0.95 or right_edge >= peak_price * 0.95:
            continue

        conf = min(1.0, (peak_price - right_edge) / peak_price * 2 + 0.3)
        signals.append(PatternSignal(
            name="圆弧顶", date=df["date"].iloc[start + mid], direction="bearish",
            confidence=conf * 0.65,
            description=f"顶点 {peak_price:.2f}, 左端 {left_edge:.2f}, 右端 {right_edge:.2f}",
            index=start + mid
        ))
    return signals


def detect_rounding_bottom(df: pd.DataFrame, window: int = 20) -> List[PatternSignal]:
    """17. 圆弧底：价格走圆弧轨迹后上涨"""
    signals = []
    n = len(df)
    if n < window * 2:
        return signals

    closes = df["close"].values

    for start in range(0, n - window * 2):
        segment = closes[start:start + window * 2]
        mid = window

        first_half = segment[:mid]
        second_half = segment[mid:]

        if len(first_half) < 5 or len(second_half) < 5:
            continue

        # Valley in the middle region
        valley_idx = np.argmin(segment)
        if abs(valley_idx - mid) > window * 0.3:
            continue

        valley_price = segment[valley_idx]
        left_edge = first_half[0]
        right_edge = second_half[-1]

        # Both edges should be higher than valley
        if left_edge <= valley_price * 1.05 or right_edge <= valley_price * 1.05:
            continue

        conf = min(1.0, (right_edge - valley_price) / valley_price * 2 + 0.3)
        signals.append(PatternSignal(
            name="圆弧底", date=df["date"].iloc[start + mid], direction="bullish",
            confidence=conf * 0.65,
            description=f"谷底 {valley_price:.2f}, 左端 {left_edge:.2f}, 右端 {right_edge:.2f}",
            index=start + mid
        ))
    return signals


def detect_v_reversal_bull(df: pd.DataFrame, min_move_pct: float = 0.15) -> List[PatternSignal]:
    """18. V型反转（看涨）：急剧下跌后迅速反弹"""
    signals = []
    n = len(df)
    if n < 20:
        return signals

    closes = df["close"].values

    for i in range(5, n - 3):
        # Find a sharp decline followed by sharp recovery
        pre = closes[max(0, i-10):i]
        post = closes[i:min(n, i+10)]

        if len(pre) < 3 or len(post) < 3:
            continue

        drop_pct = (pre[0] - closes[i]) / pre[0] if pre[0] > 0 else 0
        recovery_pct = (closes[min(len(post)-1, i+9)] - closes[i]) / closes[i] if closes[i] > 0 else 0

        # Both drop and recovery should be significant
        if drop_pct < min_move_pct or recovery_pct < min_move_pct:
            continue

        conf = min(1.0, (drop_pct + recovery_pct) * 2)
        signals.append(PatternSignal(
            name="V型反转", date=df["date"].iloc[i], direction="bullish",
            confidence=conf * 0.7,
            description=f"跌幅 {drop_pct:.1%}, 反弹 {recovery_pct:.1%}", index=i
        ))
    return signals


def detect_v_reversal_bear(df: pd.DataFrame, min_move_pct: float = 0.15) -> List[PatternSignal]:
    """18. V型反转（看跌）：急剧上涨后迅速下跌"""
    signals = []
    n = len(df)
    if n < 20:
        return signals

    closes = df["close"].values

    for i in range(5, n - 3):
        pre = closes[max(0, i-10):i]
        post = closes[i:min(n, i+10)]

        if len(pre) < 3 or len(post) < 3:
            continue

        rise_pct = (closes[i] - pre[0]) / pre[0] if pre[0] > 0 else 0
        drop_pct = (pre[-1] - post[min(len(post)-1, 9)]) / closes[i] if closes[i] > 0 else 0

        if rise_pct < min_move_pct or drop_pct < min_move_pct:
            continue

        conf = min(1.0, (rise_pct + drop_pct) * 2)
        signals.append(PatternSignal(
            name="V型反转", date=df["date"].iloc[i], direction="bearish",
            confidence=conf * 0.7,
            description=f"涨幅 {rise_pct:.1%}, 跌幅 {drop_pct:.1%}", index=i
        ))
    return signals


# ---------------------------------------------------------------------------
# Master scanner
# ---------------------------------------------------------------------------

ALL_DETECTORS = [
    # Single-candle patterns
    ("大阳线", detect_big_yang, "bullish"),
    ("大阴线", detect_big_yin, "bearish"),
    ("十字星", detect_doji, "neutral"),
    ("锤子线", detect_hammer, "bullish"),
    ("倒锤子线", detect_inverted_hammer, "bullish"),
    ("上吊线", detect_hanging_man, "bearish"),
    ("射击之星", detect_shooting_star, "bearish"),
    ("纺锤线", detect_spinning_top, "neutral"),
    ("蜻蜓十字/T字线", detect_dragonfly_doji, "bullish"),
    ("光头光脚阳线", detect_marubozu_bull, "bullish"),
    ("光头光脚阴线", detect_marubozu_bear, "bearish"),

    # Two/three-candle patterns
    ("早晨之星", detect_morning_star, "bullish"),
    ("黄昏之星", detect_evening_star, "bearish"),
    ("阳包阴吞没", detect_bullish_engulfing, "bullish"),
    ("阴包阳吞没", detect_bearish_engulfing, "bearish"),
    ("乌云盖顶", detect_dark_cloud_cover, "bearish"),
    ("Piercing Line", detect_piercing_line, "bullish"),
    ("平头顶部", detect_flat_top, "bearish"),
    ("平头底部", detect_flat_bottom, "bullish"),
    ("上升三法", detect_three_white_soldiers, "bullish"),
    ("下降三法", detect_three_black_crows, "bearish"),

    # Multi-candle patterns
    ("头肩顶", detect_head_shoulders_top, "bearish"),
    ("头肩底", detect_head_shoulders_bottom, "bullish"),
    ("双顶M头", detect_double_top, "bearish"),
    ("双底W底", detect_double_bottom, "bullish"),
    ("对称三角形", detect_symmetrical_triangle, "neutral"),
    ("上升三角形", detect_rising_triangle, "bullish"),
    ("下降三角形", detect_falling_triangle, "bearish"),
    ("上升旗形", detect_bull_flag, "bullish"),
    ("下降旗形", detect_bear_flag, "bearish"),
    ("圆弧顶", detect_rounding_top, "bearish"),
    ("圆弧底", detect_rounding_bottom, "bullish"),
    ("V型反转(看涨)", detect_v_reversal_bull, "bullish"),
    ("V型反转(看跌)", detect_v_reversal_bear, "bearish"),
]


def scan_patterns(df: pd.DataFrame, direction_filter: str = "all",
                  min_confidence: float = 0.5) -> List[PatternSignal]:
    """
    扫描所有K线形态。

    Parameters
    ----------
    df : pd.DataFrame
        K线数据，包含 date/open/high/low/close/volume 列
    direction_filter : str
        'bullish' / 'bearish' / 'all' / 'neutral'
    min_confidence : float
        最低置信度阈值 (0-1)

    Returns
    -------
    List[PatternSignal]
    """
    all_signals = []

    for name, detector, default_dir in ALL_DETECTORS:
        try:
            signals = detector(df)
            for sig in signals:
                # Apply filters
                if direction_filter != "all" and sig.direction != direction_filter:
                    continue
                if sig.confidence < min_confidence:
                    continue
                all_signals.append(sig)
        except Exception as e:
            print(f"  ⚠️ 检测 '{name}' 时出错: {e}", file=sys.stderr)

    # Sort by date, then confidence descending
    all_signals.sort(key=lambda s: (s.date if hasattr(s.date, '__lt__') else str(s.date), -s.confidence))

    return all_signals


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def direction_label(d: str) -> str:
    """方向标签"""
    labels = {"bullish": "🟢看涨", "bearish": "🔴看跌", "neutral": "⚪中性"}
    return labels.get(d, d)


def confidence_bar(c: float, width: int = 10) -> str:
    """置信度进度条"""
    filled = round(c * width)
    empty = width - filled
    return f"{'█' * filled}{'░' * empty} {c:.0%}"


def print_report(signals: List[PatternSignal], stock_code: str, periods: int):
    """在终端打印格式化的K线形态识别报告"""
    bullish = [s for s in signals if s.direction == "bullish"]
    bearish = [s for s in signals if s.direction == "bearish"]
    neutral = [s for s in signals if s.direction == "neutral"]

    width = 72
    print("=" * width)
    print(f"  K线形态识别报告 - {stock_code} (最近{periods}根K线)")
    print("=" * width)
    print()

    # Bullish signals
    if bullish:
        print(f"  📈 看涨信号 ({len(bullish)}个):")
        _print_signal_table(bullish, width)
        print()

    # Bearish signals
    if bearish:
        print(f"  📉 看跌信号 ({len(bearish)}个):")
        _print_signal_table(bearish, width)
        print()

    # Neutral signals
    if neutral:
        print(f"  ⚪ 中性信号 ({len(neutral)}个):")
        _print_signal_table(neutral, width)
        print()

    if not signals:
        print("  ℹ️ 未检测到符合条件的K线形态。")
        print("     尝试降低 --min-confidence 阈值或增加扫描周期数。")
        print()

    # Summary
    print("-" * width)
    total = len(signals)
    print(f"  总计: {total}个信号 | "
          f"看涨:{len(bullish)} | 看跌:{len(bearish)} | 中性:{len(neutral)}")

    if signals:
        avg_conf = np.mean([s.confidence for s in signals])
        print(f"  平均置信度: {avg_conf:.0%}")
    print("=" * width)


def _print_signal_table(signals: List[PatternSignal], width: int):
    """打印信号表格"""
    # Header
    header = f"    {'形态名称':<14} {'日期':<12} {'方向':<8} {'置信度':>10}"
    print(header)
    sep = "  " + "-" * (len(header) - 2)
    print(sep)

    for sig in signals:
        date_str = str(sig.date)[:10]
        row = f"    {sig.name:<14} {date_str:<12} {direction_label(sig.direction):<8} " \
              f"{confidence_bar(sig.confidence):>10}"
        print(row)


def generate_html_report(signals: List[PatternSignal], stock_code: str, periods: int,
                         output_path: str):
    """生成HTML格式报告"""
    bullish = [s for s in signals if s.direction == "bullish"]
    bearish = [s for s in signals if s.direction == "bearish"]
    neutral = [s for s in signals if s.direction == "neutral"]

    def signal_rows(sig_list):
        rows = ""
        for sig in sig_list:
            date_str = str(sig.date)[:10]
            dir_label = direction_label(sig.direction)
            bar = confidence_bar(sig.confidence, 8)
            desc = sig.description.replace('"', '&quot;')
            rows += f"""<tr>
                <td>{sig.name}</td>
                <td>{date_str}</td>
                <td>{dir_label}</td>
                <td style="font-family:monospace">{bar}</td>
                <td><small>{desc}</small></td>
            </tr>\n"""
        return rows

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>K线形态识别报告 - {stock_code}</title>
<style>
body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 20px; background: #f5f5f5; }}
.container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
h1 {{ color: #333; text-align: center; }}
h2 {{ color: #555; border-bottom: 2px solid #eee; padding-bottom: 8px; }}
table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #eee; }}
th {{ background: #f8f9fa; font-weight: 600; color: #333; }}
tr:hover {{ background: #f8f9fa; }}
.summary {{ display: flex; gap: 20px; margin: 20px 0; justify-content: center; }}
.card {{ padding: 15px 25px; border-radius: 8px; text-align: center; color: white; min-width: 120px; }}
.bullish-card {{ background: #28a745; }}
.bearish-card {{ background: #dc3545; }}
.neutral-card {{ background: #6c757d; }}
.total-card {{ background: #007bff; }}
.card .num {{ font-size: 2em; font-weight: bold; }}
.card .label {{ font-size: 0.9em; opacity: 0.9; }}
</style>
</head>
<body>
<div class="container">
<h1>K线形态识别报告 - {stock_code}</h1>
<p style="text-align:center;color:#888;">扫描最近 {periods} 根日K线 | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="summary">
    <div class="card total-card"><div class="num">{len(signals)}</div><div class="label">总信号</div></div>
    <div class="card bullish-card"><div class="num">{len(bullish)}</div><div class="label">🟢 看涨</div></div>
    <div class="card bearish-card"><div class="num">{len(bearish)}</div><div class="label">🔴 看跌</div></div>
    <div class="card neutral-card"><div class="num">{len(neutral)}</div><div class="label">⚪ 中性</div></div>
</div>

"""

    if bullish:
        html += f'<h2>📈 看涨信号 ({len(bullish)}个)</h2>\n'
        html += '<table><tr><th>形态名称</th><th>日期</th><th>方向</th><th>置信度</th><th>说明</th></tr>\n'
        html += signal_rows(bullish) + '</table>\n\n'

    if bearish:
        html += f'<h2>📉 看跌信号 ({len(bearish)}个)</h2>\n'
        html += '<table><tr><th>形态名称</th><th>日期</th><th>方向</th><th>置信度</th><th>说明</th></tr>\n'
        html += signal_rows(bearish) + '</table>\n\n'

    if neutral:
        html += f'<h2>⚪ 中性信号 ({len(neutral)}个)</h2>\n'
        html += '<table><tr><th>形态名称</th><th>日期</th><th>方向</th><th>置信度</th><th>说明</th></tr>\n'
        html += signal_rows(neutral) + '</table>\n\n'

    if not signals:
        html += '<p style="text-align:center;color:#888;">未检测到符合条件的K线形态。</p>\n'

    avg_conf = np.mean([s.confidence for s in signals]) if signals else 0
    html += f"""
<hr>
<p style="color:#888;text-align:center;font-size:0.9em;">
平均置信度: {avg_conf:.0%} | 本工具仅供技术分析参考，不构成投资建议
</p>
</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ HTML报告已保存: {output_path}")


def generate_json_report(signals: List[PatternSignal], stock_code: str, periods: int,
                         output_path: str):
    """生成JSON格式统计报告"""
    bullish = [s for s in signals if s.direction == "bullish"]
    bearish = [s for s in signals if s.direction == "bearish"]
    neutral = [s for s in signals if s.direction == "neutral"]

    report = {
        "stock_code": stock_code,
        "periods_scanned": periods,
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_signals": len(signals),
            "bullish_count": len(bullish),
            "bearish_count": len(bearish),
            "neutral_count": len(neutral),
            "avg_confidence": round(float(np.mean([s.confidence for s in signals])), 4) if signals else 0,
        },
        "pattern_counts": {},
        "signals": [s.to_dict() for s in signals],
    }

    # Count by pattern name
    from collections import Counter
    pattern_counter = Counter(s.name for s in signals)
    report["pattern_counts"] = dict(pattern_counter.most_common())

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON统计报告已保存: {output_path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="A股K线形态识别系统 - 自动检测经典K线形态",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python kline_patterns.py 000001 200
  python kline_patterns.py 600519 300 --output report.html --report stats.json
  python kline_patterns.py 000858 150 --direction bullish --min-confidence 0.6
        """
    )
    parser.add_argument("stock_code", help="A股股票代码（6位数字），如 000001")
    parser.add_argument("periods", type=int, default=200, nargs="?",
                        help="扫描最近N根K线 (默认: 200)")
    parser.add_argument("--output", "-o", help="HTML报告输出路径")
    parser.add_argument("--report", "-r", help="JSON统计报告输出路径")
    parser.add_argument("--direction", "-d", default="all",
                        choices=["bullish", "bearish", "neutral", "all"],
                        help="信号方向过滤 (默认: all)")
    parser.add_argument("--min-confidence", "-c", type=float, default=0.5,
                        help="最低置信度阈值 0-1 (默认: 0.5)")

    args = parser.parse_args()

    # Validate stock code
    if not args.stock_code.isdigit() or len(args.stock_code) != 6:
        print("❌ 股票代码应为6位数字，如 000001")
        sys.exit(1)

    print(f"🔍 正在获取 {args.stock_code} 最近 {args.periods} 根日K线数据...")
    try:
        df = fetch_kline(args.stock_code, args.periods)
    except Exception as e:
        print(f"❌ 获取K线数据失败: {e}")
        sys.exit(1)

    if len(df) < 5:
        print(f"❌ K线数据不足 ({len(df)}行)，至少需要5根K线")
        sys.exit(1)

    print(f"✅ 获取到 {len(df)} 根K线 ({df['date'].iloc[0].strftime('%Y-%m-%d')} ~ "
          f"{df['date'].iloc[-1].strftime('%Y-%m-%d')})")
    print()

    # Scan patterns
    print("🔎 正在扫描K线形态...")
    signals = scan_patterns(df, direction_filter=args.direction, min_confidence=args.min_confidence)

    # Print terminal report
    print()
    print_report(signals, args.stock_code, args.periods)

    # Generate output files if requested
    if args.output:
        generate_html_report(signals, args.stock_code, args.periods, args.output)
    if args.report:
        generate_json_report(signals, args.stock_code, args.periods, args.report)


if __name__ == "__main__":
    main()
