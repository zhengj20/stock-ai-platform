#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股技术分析指标库
==================
基于腾讯/东方财富公开行情接口获取历史K线数据，自动计算10种经典技术指标并输出买卖信号。

支持指标：MACD, KDJ, RSI, BOLL, MA均线, SAR, CCI, WR, OBV, VOL成交量均线
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Union

import pandas as pd
import numpy as np
import requests


# ═══════════════════════════════════════════════════════════
# 数据获取层
# ═══════════════════════════════════════════════════════════

# 免费公开行情接口（腾讯为主源、东方财富为兜底，均无需凭证）
_TX_KLINE_PATH = "/appstock/app/fqkline/get"
_TX_SMARTBOX_URL = "https://smartbox.gtimg.cn/s3/"
_TX_HOSTS = ["https://web.ifzq.gtimg.cn", "https://ifzq.gtimg.cn",
             "https://proxy.finance.qq.com/ifzqgtimg"]
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_HEADERS = {"User-Agent": "Mozilla/5.0"}

# 时间范围描述 → 保留的交易日根数
_PERIOD_BARS = {
    "近一周": 5, "近一月": 20, "近三个月": 60, "近三月": 60, "近一季度": 60,
    "近半年": 120, "近六个月": 120, "近一年": 250, "近两年": 500, "近三年": 750,
}



def _get(url: str, params: Dict[str, str] = None, headers: Dict[str, str] = None, retries: int = 3):
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
    """
    归一化为 6 位数字代码。

    返回 (代码, 显式symbol)：入参自带 sh/sz/bj 前缀（指数如 sh000001）时
    原样保留该 symbol，否则 symbol 为 None 由代码推断；传名称时查全市场列表。
    """
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


def _secid_candidates(code: str) -> List[str]:
    """
    解析为东财 secid 候选列表（东财用 1.=沪、0.=深 前缀）。
    000xxx 存在歧义（深市个股 / 沪市指数），个股优先，无数据时回退指数。
    """
    if code.startswith(("6", "5", "9")):
        return [f"1.{code}"]
    if code.startswith("000"):
        return [f"0.{code}", f"1.{code}"]
    return [f"0.{code}"]


def _fetch_tx_kline(code: str, bars: int, symbol: str = None) -> List[list]:
    """腾讯K线（前复权日线）。三个入口等价、限流互相独立，逐个尝试。"""
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
            # 行序：日期,开盘,收盘,最高,最低,成交量(手)
            return [list(it[:6]) for it in items]
    return []


def _fetch_em_kline(code: str, bars: int, symbol: str = None) -> List[list]:
    """东财K线（前复权日线），作为腾讯不可用时的兜底。"""
    if symbol:
        candidates = [f"{'1' if symbol[:2] == 'sh' else '0'}.{code}"]
    else:
        candidates = _secid_candidates(code)
    for secid in candidates:
        try:
            resp = _get(_EM_KLINE_URL, {
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101", "fqt": "1", "beg": "0", "end": "20500000",
                "ut": _EM_UT,
            })
            klines = (resp.json().get("data") or {}).get("klines") or []
        except Exception:
            continue
        if klines:
            # 字段顺序：日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
            return [line.split(",")[:6] for line in klines[-bars:]]
    return []


def fetch_kline_df(stock_code: str, period: str = "近一年") -> pd.DataFrame:
    """
    获取股票历史K线数据（腾讯主源 + 东财兜底，均为免费公开接口），返回标准DataFrame。

    参数:
        stock_code: 股票代码或名称，如 "600519" / "贵州茅台"
        period:     时间范围描述，默认"近一年"（无法识别时按 250 根日线处理）

    返回:
        DataFrame 含列 [date, open, high, low, close, volume]，按日期升序
    """
    bars = _PERIOD_BARS.get(str(period).strip(), 250)
    code, symbol = _norm_code(stock_code)

    rows = _fetch_tx_kline(code, bars, symbol)
    if not rows:
        rows = _fetch_em_kline(code, bars, symbol)
    if not rows:
        raise RuntimeError(f"未获取到K线数据，请检查股票代码是否正确: {stock_code}")

    # 两个源的行序一致：日期,开盘,收盘,最高,最低,成交量
    df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = df["volume"].fillna(0)
    df.dropna(subset=["close"], inplace=True)
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df[["date", "open", "high", "low", "close", "volume"]]


# ═══════════════════════════════════════════════════════════
# 技术指标计算函数（纯numpy/pandas实现）
# ═══════════════════════════════════════════════════════════

def calc_ma(close: pd.Series, periods: List[int] = None) -> Dict[str, pd.Series]:
    """移动平均线 MA"""
    if periods is None:
        periods = [5, 10, 20, 60, 120, 250]
    result = {}
    for p in periods:
        result[f"MA{p}"] = close.rolling(window=p, min_periods=1).mean()
    return result


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
    """MACD (DIF / DEA / Histogram)"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    histogram = (dif - dea) * 2
    return {"DIF": dif, "DEA": dea, "MACD_Hist": histogram}


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3) -> Dict[str, pd.Series]:
    """KDJ (随机指标)"""
    lowest_low = low.rolling(window=n, min_periods=1).min()
    highest_high = high.rolling(window=n, min_periods=1).max()
    denom = highest_high - lowest_low
    rsv = (close - lowest_low) / denom.replace(0, np.nan) * 100

    k = pd.Series(np.nan, index=close.index)
    d = pd.Series(np.nan, index=close.index)
    k.iloc[0] = 50.0
    d.iloc[0] = 50.0
    for i in range(1, len(close)):
        k.iloc[i] = (m1 - 1) / m1 * k.iloc[i - 1] + 1 / m1 * rsv.iloc[i] if not np.isnan(rsv.iloc[i]) else k.iloc[i - 1]
        d.iloc[i] = (m2 - 1) / m2 * d.iloc[i - 1] + 1 / m2 * k.iloc[i]
    j = 3 * k - 2 * d
    return {"K": k, "D": d, "J": j}


def calc_rsi(close: pd.Series, periods: Union[int, List[int]] = None) -> Dict[str, pd.Series]:
    """RSI (相对强弱指数)"""
    if periods is None:
        periods = [6, 12, 24]
    # 支持传入单个int或List[int]
    if isinstance(periods, int):
        periods = [periods]
    result = {}
    delta = close.diff()
    for p in periods:
        gain = delta.clip(lower=0).rolling(window=p, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(window=p, min_periods=1).mean()
        # 正确处理边界：loss=0→RSI=100, gain=0→RSI=0
        rs = gain / loss.replace(0, np.nan)
        rsi = pd.Series(np.where(loss == 0, 100.0, 100 - 100 / (1 + rs)), index=close.index)
        result[f"RSI{p}"] = rsi.fillna(50)
    return result


def calc_boll(close: pd.Series, period: int = 20, num_std: float = 2.0) -> Dict[str, pd.Series]:
    """布林带 BOLL"""
    mid = close.rolling(window=period, min_periods=1).mean()
    std = close.rolling(window=period, min_periods=1).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return {"BOLL_UPPER": upper, "BOLL_MID": mid, "BOLL_LOWER": lower}


def calc_sar(high: pd.Series, low: pd.Series, af_init: float = 0.02, af_step: float = 0.02, af_max: float = 0.2) -> pd.Series:
    """抛物线转向指标 SAR"""
    n = len(high)
    sar = np.full(n, np.nan)
    trend = np.zeros(n, dtype=int)   # +1 uptrend, -1 downtrend
    ep = np.zeros(n)                 # extreme point
    af = np.zeros(n)

    # 初始化：假设上升趋势
    trend[0] = 1
    sar[0] = low.iloc[0]
    ep[0] = high.iloc[0]
    af[0] = af_init

    for i in range(1, n):
        if trend[i - 1] == 1:  # uptrend
            sar[i] = sar[i - 1] + af[i - 1] * (ep[i - 1] - sar[i - 1])
            if high.iloc[i] > ep[i - 1]:
                ep[i] = high.iloc[i]
            else:
                ep[i] = ep[i - 1]
            if low.iloc[i] < sar[i]:
                trend[i] = -1
                sar[i] = ep[i - 1]
                af[i] = af_init
            else:
                af[i] = min(af[i - 1] + af_step, af_max)
        else:  # downtrend
            sar[i] = sar[i - 1] + af[i - 1] * (ep[i - 1] - sar[i - 1])
            if low.iloc[i] < ep[i - 1]:
                ep[i] = low.iloc[i]
            else:
                ep[i] = ep[i - 1]
            if high.iloc[i] > sar[i]:
                trend[i] = 1
                sar[i] = ep[i - 1]
                af[i] = af_init
            else:
                af[i] = min(af[i - 1] + af_step, af_max)

    return pd.Series(sar, index=high.index)


def calc_cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """顺势指标 CCI"""
    tp = (high + low + close) / 3.0
    ma_tp = tp.rolling(window=period, min_periods=1).mean()
    mad = tp.rolling(window=period, min_periods=1).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    cci = (tp - ma_tp) / (0.015 * mad.replace(0, np.nan))
    return cci.fillna(0)


def calc_wr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Dict[str, pd.Series]:
    """威廉指标 WR (RWR)"""
    highest_high = high.rolling(window=period, min_periods=1).max()
    lowest_low = low.rolling(window=period, min_periods=1).min()
    wr = -100 * (highest_high - close) / (highest_high - lowest_low).replace(0, np.nan)
    return {f"WR{period}": wr.fillna(-50)}


def calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """能量潮 OBV"""
    diff = close.diff().fillna(0)
    obv = (np.sign(diff) * volume).cumsum()
    return pd.Series(obv, index=close.index)


def calc_vol(volume: pd.Series, periods: List[int] = None) -> Dict[str, pd.Series]:
    """成交量均线 VOL"""
    if periods is None:
        periods = [5, 10, 20]
    result = {}
    for p in periods:
        result[f"VOL_MA{p}"] = volume.rolling(window=p, min_periods=1).mean()
    return result


# ═══════════════════════════════════════════════════════════
# 信号判断辅助函数
# ═══════════════════════════════════════════════════════════

def _cross_signal(series_a: pd.Series, series_b: pd.Series) -> str:
    """判断金叉/死叉：series_a 上穿 series_b = 金叉，下穿 = 死叉"""
    if len(series_a) < 2:
        return "数据不足"
    curr_a, prev_a = series_a.iloc[-1], series_a.iloc[-2]
    curr_b, prev_b = series_b.iloc[-1], series_b.iloc[-2]
    if prev_a <= prev_b and curr_a > curr_b:
        return "🟢 金叉 (买入信号)"
    elif prev_a >= prev_b and curr_a < curr_b:
        return "🔴 死叉 (卖出信号)"
    else:
        direction = "多头排列" if curr_a > curr_b else "空头排列"
        return f"⚪ {direction}"


def _overbought_oversold(value: float, ob_level: float, os_level: float) -> str:
    """超买/超卖判断"""
    if value >= ob_level:
        return "⚠️ 超买区域 (考虑卖出)"
    elif value <= os_level:
        return "🟢 超卖区域 (考虑买入)"
    else:
        return "⚪ 正常区间"


def _format_val(v, decimals: int = 4) -> str:
    """格式化数值输出"""
    if pd.isna(v):
        return "N/A"
    return f"{v:.{decimals}f}"


# ═══════════════════════════════════════════════════════════
# 主分析引擎
# ═══════════════════════════════════════════════════════════

def analyze(stock_code: str, period: str = "近一年") -> Dict[str, Any]:
    """
    对指定股票进行完整的技术指标分析。

    参数:
        stock_code: 股票代码或名称
        period:     K线时间范围

    返回:
        包含所有指标计算结果和买卖信号的字典
    """
    print(f"\n{'='*60}")
    print(f"📊 A股技术分析指标库")
    print(f"{'='*60}")
    print(f"🔍 正在获取 [{stock_code}] {period} K线数据...")

    df = fetch_kline_df(stock_code, period)
    n = len(df)
    last_date = df["date"].iloc[-1]
    last_close = float(df["close"].iloc[-1])
    print(f"✅ 获取到 {n} 条K线数据 ({df['date'].iloc[0]} ~ {last_date})")
    print(f"   最新收盘价: ¥{last_close:.2f}\n")

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    results: Dict[str, Any] = {
        "stock": stock_code,
        "period": period,
        "data_range": f"{df['date'].iloc[0]} ~ {last_date}",
        "total_bars": n,
        "latest_close": last_close,
        "indicators": {}
    }

    # ── 1. MA均线系统 ────────────────────────────────
    print("━" * 60)
    print("📈 1. MA均线系统 (5/10/20/60/120/250日)")
    print("━" * 60)
    ma = calc_ma(close)
    ma_latest = {}
    for key, ser in ma.items():
        val = float(ser.iloc[-1]) if not pd.isna(ser.iloc[-1]) else None
        ma_latest[key] = _format_val(val, 2) if val is not None else "N/A"
        print(f"   {key:>8}: ¥{ma_latest[key]}")

    # 均线排列判断
    ma5 = float(ma["MA5"].iloc[-1]) if not pd.isna(ma["MA5"].iloc[-1]) else None
    ma10 = float(ma["MA10"].iloc[-1]) if not pd.isna(ma["MA10"].iloc[-1]) else None
    ma20 = float(ma["MA20"].iloc[-1]) if not pd.isna(ma["MA20"].iloc[-1]) else None
    if all(v is not None for v in [ma5, ma10, ma20]):
        if ma5 > ma10 > ma20:
            signal = "🟢 多头排列 (短期均线在上，趋势偏多)"
        elif ma5 < ma10 < ma20:
            signal = "🔴 空头排列 (短期均线在下，趋势偏空)"
        else:
            signal = "⚪ 交叉状态 (均线纠缠，方向不明)"
    else:
        signal = "⚠️ 数据不足判断排列"

    ma_cross = _cross_signal(ma["MA5"], ma["MA10"])
    print(f"\n   MA5/MA10: {ma_cross}")
    print(f"   均线排列: {signal}")

    results["indicators"]["MA"] = {
        "values": ma_latest,
        "cross_MA5_MA10": ma_cross,
        "alignment": signal
    }

    # ── 2. MACD ──────────────────────────────────────
    print(f"\n{'━'*60}")
    print("📈 2. MACD (指数平滑异同移动平均线)")
    print("━" * 60)
    macd = calc_macd(close)
    dif_val = float(macd["DIF"].iloc[-1])
    dea_val = float(macd["DEA"].iloc[-1])
    hist_val = float(macd["MACD_Hist"].iloc[-1])
    print(f"   DIF     : {_format_val(dif_val)}")
    print(f"   DEA     : {_format_val(dea_val)}")
    print(f"   Histogram: {_format_val(hist_val)}")

    macd_cross = _cross_signal(macd["DIF"], macd["DEA"])
    hist_prev = float(macd["MACD_Hist"].iloc[-2]) if n >= 2 else 0
    if hist_val > 0 and hist_val > hist_prev:
        hist_sig = "🟢 红柱放大 (多头动能增强)"
    elif hist_val > 0 and hist_val < hist_prev:
        hist_sig = "⚠️ 红柱缩小 (多头动能减弱)"
    elif hist_val < 0 and hist_val < hist_prev:
        hist_sig = "🔴 绿柱放大 (空头动能增强)"
    else:
        hist_sig = "⚠️ 绿柱缩小 (空头动能减弱)"

    print(f"\n   DIF/DEA: {macd_cross}")
    print(f"   柱状图:  {hist_sig}")

    results["indicators"]["MACD"] = {
        "DIF": round(dif_val, 4),
        "DEA": round(dea_val, 4),
        "Histogram": round(hist_val, 4),
        "cross_DIF_DEA": macd_cross,
        "histogram_signal": hist_sig
    }

    # ── 3. KDJ ───────────────────────────────────────
    print(f"\n{'━'*60}")
    print("📈 3. KDJ (随机指标)")
    print("━" * 60)
    kdj = calc_kdj(high, low, close)
    k_val = float(kdj["K"].iloc[-1]) if not pd.isna(kdj["K"].iloc[-1]) else None
    d_val = float(kdj["D"].iloc[-1]) if not pd.isna(kdj["D"].iloc[-1]) else None
    j_val = float(kdj["J"].iloc[-1]) if not pd.isna(kdj["J"].iloc[-1]) else None

    print(f"   K: {_format_val(k_val, 2) if k_val is not None else 'N/A'}")
    print(f"   D: {_format_val(d_val, 2) if d_val is not None else 'N/A'}")
    print(f"   J: {_format_val(j_val, 2) if j_val is not None else 'N/A'}")

    kdj_cross = _cross_signal(kdj["K"], kdj["D"]) if k_val and d_val else "数据不足"
    kdj_ob_os = ""
    if j_val is not None:
        if j_val > 100:
            kdj_ob_os = "⚠️ J值超买 (>100)"
        elif j_val < 0:
            kdj_ob_os = "🟢 J值超卖 (<0)"
        else:
            kdj_ob_os = "⚪ J值正常区间"

    print(f"\n   K/D线: {kdj_cross}")
    print(f"   J值状态: {kdj_ob_os}")

    results["indicators"]["KDJ"] = {
        "K": round(k_val, 2) if k_val else None,
        "D": round(d_val, 2) if d_val else None,
        "J": round(j_val, 2) if j_val else None,
        "cross_K_D": kdj_cross,
        "J_signal": kdj_ob_os
    }

    # ── 4. RSI ───────────────────────────────────────
    print(f"\n{'━'*60}")
    print("📈 4. RSI (相对强弱指数)")
    print("━" * 60)
    rsi = calc_rsi(close)
    rsi_info = {}
    for key, ser in rsi.items():
        val = float(ser.iloc[-1]) if not pd.isna(ser.iloc[-1]) else None
        sig = _overbought_oversold(val, 80, 20) if val is not None else "N/A"
        print(f"   {key:>6}: {_format_val(val, 2)}  →  {sig}")
        rsi_info[key] = {"value": round(val, 2) if val else None, "signal": sig}

    results["indicators"]["RSI"] = rsi_info

    # ── 5. BOLL布林带 ────────────────────────────────
    print(f"\n{'━'*60}")
    print("📈 5. BOLL (布林带)")
    print("━" * 60)
    boll = calc_boll(close)
    upper_val = float(boll["BOLL_UPPER"].iloc[-1])
    mid_val = float(boll["BOLL_MID"].iloc[-1])
    lower_val = float(boll["BOLL_LOWER"].iloc[-1])

    print(f"   上轨: ¥{_format_val(upper_val, 2)}")
    print(f"   中轨: ¥{_format_val(mid_val, 2)}")
    print(f"   下轨: ¥{_format_val(lower_val, 2)}")

    if last_close > upper_val:
        boll_sig = "⚠️ 股价突破上轨 (超买风险)"
    elif last_close < lower_val:
        boll_sig = "🟢 股价跌破下轨 (超卖机会)"
    elif last_close > mid_val:
        boll_sig = "⚪ 股价在中轨上方 (偏强)"
    else:
        boll_sig = "⚪ 股价在中轨下方 (偏弱)"

    bandwidth = ((upper_val - lower_val) / mid_val * 100) if mid_val > 0 else 0
    print(f"\n   带宽: {bandwidth:.2f}%")
    print(f"   信号: {boll_sig}")

    results["indicators"]["BOLL"] = {
        "upper": round(upper_val, 2),
        "mid": round(mid_val, 2),
        "lower": round(lower_val, 2),
        "bandwidth_pct": round(bandwidth, 2),
        "signal": boll_sig
    }

    # ── 6. SAR抛物线转向 ─────────────────────────────
    print(f"\n{'━'*60}")
    print("📈 6. SAR (抛物线转向指标)")
    print("━" * 60)
    sar = calc_sar(high, low)
    sar_val = float(sar.iloc[-1]) if not pd.isna(sar.iloc[-1]) else None
    print(f"   SAR: {_format_val(sar_val, 2) if sar_val is not None else 'N/A'}")

    if sar_val is not None:
        if last_close > sar_val:
            sar_sig = "🟢 上升趋势 (股价在SAR上方)"
        else:
            sar_sig = "🔴 下降趋势 (股价在SAR下方)"
        print(f"   信号: {sar_sig}")
    else:
        sar_sig = "N/A"

    results["indicators"]["SAR"] = {
        "value": round(sar_val, 2) if sar_val else None,
        "signal": sar_sig
    }

    # ── 7. CCI顺势指标 ───────────────────────────────
    print(f"\n{'━'*60}")
    print("📈 7. CCI (顺势指标)")
    print("━" * 60)
    cci = calc_cci(high, low, close)
    cci_val = float(cci.iloc[-1]) if not pd.isna(cci.iloc[-1]) else None
    print(f"   CCI(14): {_format_val(cci_val, 2)}")

    if cci_val is not None:
        if cci_val > 100:
            cci_sig = "⚠️ 强势区域 (>+100，可能超买)"
        elif cci_val < -100:
            cci_sig = "🟢 弱势区域 (<-100，可能超卖)"
        else:
            cci_sig = "⚪ 常态区间 (-100 ~ +100)"
        print(f"   信号: {cci_sig}")
    else:
        cci_sig = "N/A"

    results["indicators"]["CCI"] = {
        "value": round(cci_val, 2) if cci_val else None,
        "signal": cci_sig
    }

    # ── 8. WR威廉指标 ────────────────────────────────
    print(f"\n{'━'*60}")
    print("📈 8. WR (威廉指标)")
    print("━" * 60)
    wr = calc_wr(high, low, close)
    for key, ser in wr.items():
        val = float(ser.iloc[-1]) if not pd.isna(ser.iloc[-1]) else None
        # WR是反向指标：接近0=超买，接近-100=超卖
        sig = ""
        if val is not None:
            if val > -20:
                sig = "⚠️ 超买区域 (> -20)"
            elif val < -80:
                sig = "🟢 超卖区域 (< -80)"
            else:
                sig = "⚪ 正常区间"
        print(f"   {key}: {_format_val(val, 2)}  →  {sig}")

    results["indicators"]["WR"] = {}
    for key, ser in wr.items():
        val = float(ser.iloc[-1]) if not pd.isna(ser.iloc[-1]) else None
        sig = ""
        if val is not None:
            if val > -20:
                sig = "超买区域"
            elif val < -80:
                sig = "超卖区域"
            else:
                sig = "正常区间"
        results["indicators"]["WR"][key] = {
            "value": round(val, 2) if val else None,
            "signal": sig
        }

    # ── 9. OBV能量潮 ─────────────────────────────────
    print(f"\n{'━'*60}")
    print("📈 9. OBV (能量潮)")
    print("━" * 60)
    obv = calc_obv(close, volume)
    obv_val = float(obv.iloc[-1])
    obv_prev_5 = float(obv.iloc[-min(5, n)]) if n >= 5 else obv_val
    obv_change_pct = (obv_val - obv_prev_5) / abs(obv_prev_5) * 100 if obv_prev_5 != 0 else 0

    print(f"   OBV: {_format_val(obv_val, 0)}")
    print(f"   近5日变化: {obv_change_pct:+.2f}%")

    if obv_change_pct > 5:
        obv_sig = "🟢 资金持续流入 (OBV上升)"
    elif obv_change_pct < -5:
        obv_sig = "🔴 资金持续流出 (OBV下降)"
    else:
        obv_sig = "⚪ 资金平稳"

    print(f"   信号: {obv_sig}")

    results["indicators"]["OBV"] = {
        "value": round(obv_val, 0),
        "change_5d_pct": round(obv_change_pct, 2),
        "signal": obv_sig
    }

    # ── 10. VOL成交量均线 ────────────────────────────
    print(f"\n{'━'*60}")
    print("📈 10. VOL (成交量均线)")
    print("━" * 60)
    vol = calc_vol(volume)
    vol_latest = {}
    for key, ser in vol.items():
        val = float(ser.iloc[-1]) if not pd.isna(ser.iloc[-1]) else None
        formatted = f"{val:,.0f}" if val is not None else "N/A"
        print(f"   {key:>8}: {formatted}")
        vol_latest[key] = round(val, 0) if val else None

    # 量比判断
    vol5 = float(vol["VOL_MA5"].iloc[-1]) if not pd.isna(vol["VOL_MA5"].iloc[-1]) else 0
    vol10 = float(vol["VOL_MA10"].iloc[-1]) if not pd.isna(vol["VOL_MA10"].iloc[-1]) else 0
    last_vol = float(volume.iloc[-1])
    if vol10 > 0:
        vol_ratio = last_vol / vol5 * 100 if vol5 > 0 else 100
        print(f"\n   当日成交量/MA5: {vol_ratio:.1f}%")
        if vol_ratio > 150:
            vol_sig = "🟢 放量 (成交量显著放大)"
        elif vol_ratio < 50:
            vol_sig = "⚠️ 缩量 (成交量明显萎缩)"
        else:
            vol_sig = "⚪ 量能正常"
    else:
        vol_sig = "数据不足"

    print(f"   信号: {vol_sig}")

    results["indicators"]["VOL"] = {
        "values": vol_latest,
        "latest_volume": round(last_vol, 0),
        "signal": vol_sig
    }

    # ── 综合研判 ──────────────────────────────────────
    print(f"\n{'━'*60}")
    print("📊 综合研判")
    print("━" * 60)

    buy_signals = []
    sell_signals = []
    neutral_signals = []

    # MACD
    if "金叉" in macd_cross:
        buy_signals.append("MACD金叉")
    elif "死叉" in macd_cross:
        sell_signals.append("MACD死叉")
    else:
        neutral_signals.append("MACD无交叉")

    # KDJ
    if "金叉" in kdj_cross:
        buy_signals.append("KDJ金叉")
    elif "死叉" in kdj_cross:
        sell_signals.append("KDJ死叉")

    # RSI (取RSI6)
    rsi6_key = [k for k in rsi_info if "6" in k]
    if rsi6_key:
        rsi6_val = rsi_info[rsi6_key[0]]["value"]
        if rsi6_val is not None and rsi6_val < 20:
            buy_signals.append("RSI6超卖")
        elif rsi6_val is not None and rsi6_val > 80:
            sell_signals.append("RSI6超买")

    # SAR
    if "上升" in sar_sig:
        buy_signals.append("SAR上升趋势")
    elif "下降" in sar_sig:
        sell_signals.append("SAR下降趋势")

    # BOLL
    if "跌破下轨" in boll_sig:
        buy_signals.append("BOLL超卖")
    elif "突破上轨" in boll_sig:
        sell_signals.append("BOLL超买")

    # 均线排列
    if "多头" in signal:
        buy_signals.append("MA多头排列")
    elif "空头" in signal:
        sell_signals.append("MA空头排列")

    print(f"\n   🟢 买入信号 ({len(buy_signals)}): {', '.join(buy_signals) if buy_signals else '无'}")
    print(f"   🔴 卖出信号 ({len(sell_signals)}): {', '.join(sell_signals) if sell_signals else '无'}")
    print(f"   ⚪ 中性信号 ({len(neutral_signals)}): {', '.join(neutral_signals) if neutral_signals else '无'}")

    total = len(buy_signals) + len(sell_signals)
    if total == 0:
        overall = "⚪ 无明显方向，建议观望"
    elif len(buy_signals) > len(sell_signals):
        strength = min(len(buy_signals), 5)
        overall = f"🟢 偏多 ({len(buy_signals)}买 vs {len(sell_signals)}卖)"
    else:
        overall = f"🔴 偏空 ({len(sell_signals)}卖 vs {len(buy_signals)}买)"

    print(f"\n   📌 综合结论: {overall}")

    results["summary"] = {
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "neutral_signals": neutral_signals,
        "overall": overall
    }

    # ── 保存JSON结果 ──────────────────────────────────
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r'[<>:"/\\|?*]', '_', stock_code).strip()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"{safe_name}_{timestamp}.json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"💾 分析结果已保存至: {json_path}")
    print(f"{'='*60}\n")

    return results


# ═══════════════════════════════════════════════════════════
# CLI入口
# ═══════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("用法: python tech_indicators.py <股票代码或名称> [时间范围]")
        print()
        print("示例:")
        print('  python tech_indicators.py "600519"')
        print('  python tech_indicators.py "贵州茅台" "近半年"')
        print('  python tech_indicators.py "000001" "近两年"')
        sys.exit(1)

    stock_code = sys.argv[1]
    period = sys.argv[2] if len(sys.argv) > 2 else "近一年"

    try:
        analyze(stock_code, period)
    except Exception as e:
        print(f"\n❌ 分析失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
