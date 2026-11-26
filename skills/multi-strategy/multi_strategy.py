#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股多策略库 (Multi-Strategy Library)
=====================================
实现多种经典交易策略的自动化执行和对比分析。

六大策略体系：
  1. 趋势跟踪策略（Trend Following）
  2. 均值回归策略（Mean Reversion）
  3. 动量策略（Momentum）
  4. 龙头战法策略（Dragon Head）
  5. 低吸蓝筹策略（Blue Chip Dip）
  6. 网格交易策略（Grid Trading）

依赖: pandas, numpy, requests
用法: python multi_strategy.py --strategy <策略名> [股票代码]
     python multi_strategy.py --all [股票列表文件]

作者: Hermes Agent
版本: 1.0.0
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
import numpy as np


# ═══════════════════════════════════════════════════════════
# 全局配置
# ═══════════════════════════════════════════════════════════

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 策略注册表：名称 -> (显示名, 函数, 参数说明)
STRATEGY_REGISTRY: Dict[str, Tuple[str, Any, str]] = {}


def register_strategy(display_name: str, description: str):
    """装饰器：注册策略到全局注册表"""
    def decorator(func):
        # 使用函数名去掉 strategy_ 前缀作为key，方便CLI调用
        key = func.__name__
        short_key = key.replace("strategy_", "", 1) if key.startswith("strategy_") else key
        STRATEGY_REGISTRY[key] = (display_name, func, description)
        STRATEGY_REGISTRY[short_key] = (display_name, func, description)
        return func
    return decorator


# ═══════════════════════════════════════════════════════════
# 数据获取层（腾讯 + 东方财富公开接口，免费无需凭证）
# ═══════════════════════════════════════════════════════════

_TX_KLINE_PATH = "/appstock/app/fqkline/get"
_TX_SMARTBOX_URL = "https://smartbox.gtimg.cn/s3/"
_TX_HOSTS = ["https://web.ifzq.gtimg.cn", "https://ifzq.gtimg.cn",
             "https://proxy.finance.qq.com/ifzqgtimg"]
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EM_DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_HEADERS = {"User-Agent": "Mozilla/5.0"}

# 时间范围描述 → 保留的交易日根数
_PERIOD_BARS = {
    "近一周": 5, "近一月": 20, "近三个月": 60, "近三月": 60, "近一季度": 60,
    "近半年": 120, "近六个月": 120, "近一年": 250, "近两年": 500, "近三年": 750,
    "近五年": 1250,
}

# 时间范围描述 → 年数（财务/估值序列用）
_PERIOD_YEARS = {
    "近一年": 1, "近两年": 2, "近三年": 3, "近五年": 5,
    "近半年": 1, "近三月": 1, "近三个月": 1,
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

    返回 (代码, 显式symbol)：入参自带 sh/sz/bj 前缀（指数如 sh000001）时原样保留，
    否则由代码推断；传名称时走腾讯检索。
    """
    import re
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


def _secid(code: str, symbol: Optional[str] = None) -> str:
    """东财 secid（1.=沪、0.=深）。000xxx 有歧义时个股优先（0.），与腾讯前缀一致。"""
    if symbol:
        return f"{'1' if symbol[:2] == 'sh' else '0'}.{code}"
    return f"{'1' if code.startswith(('6', '5', '9')) else '0'}.{code}"


def _fetch_tx_kline(code: str, bars: int, symbol: str = None) -> List[list]:
    """腾讯K线（前复权日线）。三个入口等价、限流互相独立，逐个尝试。"""
    import re
    symbol = symbol or _tx_symbol(code)
    # 腾讯单次最多 640 根，更长的区间分段拼接
    spans = [min(bars, 640)] if bars <= 640 else [640, bars - 640]
    rows: List[list] = []
    for host in _TX_HOSTS:
        for span in spans:
            try:
                resp = _get(host + _TX_KLINE_PATH,
                            {"param": f"{symbol},day,,,{span},qfq"},
                            {"Referer": "https://gu.qq.com/"}, retries=2)
                node = (resp.json().get("data") or {}).get(symbol) or {}
            except Exception:
                rows = []
                break
            # 有除权的标的返回 qfqday；从未除权的标的和指数只有 day
            items = node.get("qfqday") or node.get("day") or []
            if not items:
                rows = []
                break
            rows.extend(items)
        if rows:
            # 行序：日期,开盘,收盘,最高,低,成交量(手)
            return [list(r[:6]) for r in rows]
    return []


def _fetch_em_kline(code: str, bars: int, symbol: str = None) -> List[list]:
    """东财K线（前复权日线），作为腾讯不可用时的兜底。"""
    try:
        resp = _get(_EM_KLINE_URL, {
            "secid": _secid(code, symbol),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101", "fqt": "1", "beg": "0", "end": "20500000",
            "ut": _EM_UT,
        })
        klines = (resp.json().get("data") or {}).get("klines") or []
    except Exception:
        return []
    if not klines:
        return []
    # 字段顺序：日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
    return [line.split(",")[:6] for line in klines[-bars:]]


def fetch_kline_df(stock_code: str, period: str = "近一年") -> pd.DataFrame:
    """
    获取股票历史K线数据（腾讯主源 + 东财兜底），返回标准DataFrame。

    参数:
        stock_code: 股票代码、带市场前缀的代码或名称，如 "600519" / "sh000001" / "贵州茅台"
        period:     时间范围描述，默认"近一年"（无法识别时按 250 根日线处理）

    返回:
        DataFrame 含列 [date, open, high, low, close, volume]，按日期升序
    """
    bars = _PERIOD_BARS.get(str(period).strip(), 250)
    code, symbol = _norm_code(stock_code)

    rows = _fetch_tx_kline(code, bars, symbol) or _fetch_em_kline(code, bars, symbol)
    if not rows:
        raise RuntimeError(f"未获取到K线数据，请检查股票代码是否正确: {stock_code}")

    # 两个源的行序一致：日期,开盘,收盘,最高,最低,成交量
    df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])
    df = df.drop_duplicates(subset=["date"], keep="last")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = df["volume"].fillna(0)
    df.dropna(subset=["close"], inplace=True)
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df[["date", "open", "high", "low", "close", "volume"]]


def _em_datacenter(report: str, flt: str, sort_columns: str = None,
                   page_size: int = 500, max_pages: int = 3) -> List[Dict[str, Any]]:
    """
    东方财富数据中心公开接口（RPT_* 报表）。

    flt 为东财过滤表达式，如 '(SECURITY_CODE="600519")'。
    按 sort_columns 倒序分页取数，返回记录列表（调用方自行转正序）。
    """
    records: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params = {
            "reportName": report, "columns": "ALL", "filter": flt,
            "pageNumber": str(page), "pageSize": str(page_size),
            "source": "WEB", "client": "WEB",
        }
        if sort_columns:
            params["sortColumns"] = sort_columns
            params["sortTypes"] = "-1"
        try:
            payload = _get(_EM_DC_URL, params).json()
        except Exception:
            break
        data = (payload.get("result") or {}).get("data") or []
        records.extend(data)
        if len(data) < page_size:
            break
    return records


def _latest_price(code: str, symbol: Optional[str] = None) -> Optional[float]:
    """腾讯实时行情取最新价，失败返回 None"""
    try:
        resp = _get("https://qt.gtimg.cn/q=" + (symbol or _tx_symbol(code)), retries=2)
        resp.encoding = "gbk"
        fields = resp.text.split("~")
        price = pd.to_numeric(fields[3], errors="coerce")
        return float(price) if pd.notna(price) and price > 0 else None
    except Exception:
        return None


def fetch_financial_data(stock_code: str, indicators: List[str], period: str = "近三年") -> pd.DataFrame:
    """
    获取财务/估值数据，按 indicators 关键词拼装返回列。

    列名保留中文指标名，调用方按关键词取数：
      "市盈率"/"市净率" → 东财估值分析的日频历史序列（PE_TTM / PB_MRQ）
      "净资产收益率"/"ROE" → 东财F10主要财务的加权ROE（按报告期）
      "股息率" → 近12个月每股税前派息 / 最新价

    返回按时间升序；不同指标序列长度不同，短列以 NaN 补齐（调用方 dropna）。
    """
    import re
    code, symbol = _norm_code(stock_code)
    years = _PERIOD_YEARS.get(str(period).strip(), 3)
    keys = " ".join(str(i) for i in indicators)
    series: Dict[str, pd.Series] = {}

    # ── 估值：日频 PE / PB 历史 ──────────────────────────
    if "市盈" in keys or "市净" in keys or "PE" in keys.upper() or "PB" in keys.upper():
        cutoff = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
        rows = _em_datacenter("RPT_VALUEANALYSIS_DET", f'(SECURITY_CODE="{code}")',
                              sort_columns="TRADE_DATE",
                              max_pages=max(1, (365 * years) // 500 + 2))
        dates, pe, pb = [], [], []
        for r in reversed(rows):  # 东财倒序返回，转为升序
            d = str(r.get("TRADE_DATE", ""))[:10]
            if d < cutoff:
                continue
            dates.append(d)
            pe.append(r.get("PE_TTM"))
            pb.append(r.get("PB_MRQ"))
        if dates:
            idx = pd.Index(dates)
            if "市盈" in keys or "PE" in keys.upper():
                series["市盈率"] = pd.Series(pd.to_numeric(pe, errors="coerce"), index=idx)
            if "市净" in keys or "PB" in keys.upper():
                series["市净率"] = pd.Series(pd.to_numeric(pb, errors="coerce"), index=idx)

    # ── ROE：报告期加权净资产收益率 ────────────────────────
    if "净资产收益" in keys or "roe" in keys.lower():
        secucode = f"{code}.{'SH' if _secid(code, symbol).startswith('1.') else 'SZ'}"
        rows = _em_datacenter("RPT_F10_FINANCE_MAINFINADATA", f'(SECUCODE="{secucode}")',
                              sort_columns="REPORT_DATE", page_size=40)
        # 只取年报口径，保证跨年可比
        pairs = [(str(r.get("REPORT_DATE", ""))[:10], r.get("ROEJQ")) for r in reversed(rows)
                 if str(r.get("REPORT_DATE", ""))[5:10] == "12-31" and r.get("ROEJQ") is not None]
        if pairs:
            idx = pd.Index([p[0] for p in pairs][-years:])
            series["净资产收益率"] = pd.Series(
                [pd.to_numeric(p[1], errors="coerce") for p in pairs][-years:], index=idx)

    # ── 股息率：近12个月每股税前派息 / 最新价 ───────────────
    if "股息" in keys or "dividend" in keys.lower():
        rows = _em_datacenter("RPT_SHAREBONUS_DET", f'(SECURITY_CODE="{code}")',
                              sort_columns="EX_DIVIDEND_DATE", page_size=20)
        price = _latest_price(code, symbol)
        cutoff = datetime.now() - timedelta(days=365)
        dps = 0.0
        for r in rows:
            ex_date = str(r.get("EX_DIVIDEND_DATE", ""))[:10]
            try:
                if datetime.strptime(ex_date, "%Y-%m-%d") >= cutoff:
                    # PRETAX_BONUS_RMB 为"每10股派息额（元，含税）"
                    dps += float(r.get("PRETAX_BONUS_RMB") or 0) / 10.0
            except (ValueError, TypeError):
                continue
        if price and dps > 0:
            series["股息率"] = pd.Series([round(dps / price * 100, 2)])

    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series)


# ═══════════════════════════════════════════════════════════
# 技术指标计算（复用 tech-indicators 逻辑）
# ═══════════════════════════════════════════════════════════

def calc_ma(close: pd.Series, periods: List[int] = None) -> Dict[str, pd.Series]:
    """移动平均线 MA"""
    if periods is None:
        periods = [5, 10, 20, 60, 120, 250]
    return {f"MA{p}": close.rolling(window=p, min_periods=1).mean() for p in periods}


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
    """MACD"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    histogram = (dif - dea) * 2
    return {"DIF": dif, "DEA": dea, "MACD_Hist": histogram}


def calc_rsi(close: pd.Series, periods: List[int] = None) -> Dict[str, pd.Series]:
    """RSI"""
    if periods is None:
        periods = [6, 12, 24]
    result = {}
    delta = close.diff()
    for p in periods:
        gain = delta.clip(lower=0).rolling(window=p, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(window=p, min_periods=1).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        result[f"RSI{p}"] = rsi.fillna(50)
    return result


def calc_boll(close: pd.Series, period: int = 20, num_std: float = 2.0) -> Dict[str, pd.Series]:
    """布林带 BOLL"""
    mid = close.rolling(window=period, min_periods=1).mean()
    std = close.rolling(window=period, min_periods=1).std(ddof=0)
    return {
        "BOLL_UPPER": mid + num_std * std,
        "BOLL_MID": mid,
        "BOLL_LOWER": mid - num_std * std
    }


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9) -> Dict[str, pd.Series]:
    """KDJ"""
    lowest_low = low.rolling(window=n, min_periods=1).min()
    highest_high = high.rolling(window=n, min_periods=1).max()
    denom = highest_high - lowest_low
    rsv = (close - lowest_low) / denom.replace(0, np.nan) * 100
    k = pd.Series(np.nan, index=close.index)
    d = pd.Series(np.nan, index=close.index)
    k.iloc[0] = 50.0
    d.iloc[0] = 50.0
    for i in range(1, len(close)):
        k.iloc[i] = (2/3) * k.iloc[i-1] + (1/3) * rsv.iloc[i] if not np.isnan(rsv.iloc[i]) else k.iloc[i-1]
        d.iloc[i] = (2/3) * d.iloc[i-1] + (1/3) * k.iloc[i]
    j = 3 * k - 2 * d
    return {"K": k, "D": d, "J": j}


# ═══════════════════════════════════════════════════════════
# 信号判断辅助函数
# ═══════════════════════════════════════════════════════════

def _cross_signal(a: pd.Series, b: pd.Series) -> str:
    """金叉/死叉判断"""
    if len(a) < 2:
        return "数据不足"
    ca, pa = a.iloc[-1], a.iloc[-2]
    cb, pb = b.iloc[-1], b.iloc[-2]
    if pa <= pb and ca > cb:
        return "金叉"
    elif pa >= pb and ca < cb:
        return "死叉"
    else:
        return "无交叉"


def _signal_score(signals: List[bool]) -> float:
    """信号强度评分 (0-100)"""
    if not signals:
        return 0.0
    return round(sum(signals) / len(signals) * 100, 1)


def _get_limit_threshold(stock_code: str) -> float:
    """根据股票代码判断涨停阈值"""
    if not stock_code:
        return 9.5  # 默认主板
    code_str = str(stock_code).zfill(6)
    # 创业板(300/301)、科创板(688/689): 20%
    if code_str.startswith(("30", "301", "688", "689")):
        return 19.5
    # 北交所(8/4开头): 30%
    if code_str[0] in ("8", "4"):
        return 29.5
    # 主板: 10%
    return 9.5


def _is_limit_up(change_pct: float, stock_code: str) -> bool:
    """判断是否涨停（根据板块类型）"""
    threshold = _get_limit_threshold(stock_code)
    return change_pct >= threshold


# ═══════════════════════════════════════════════════════════
# 策略一：趋势跟踪策略（Trend Following）
# ═══════════════════════════════════════════════════════════

@register_strategy("双均线金叉/死叉", "MA5上穿MA20买入，下穿卖出")
def strategy_dual_ma_crossover(stock_code: str, ma_fast: int = 5, ma_slow: int = 20, period: str = "近一年") -> Dict[str, Any]:
    """双均线金叉/死叉策略"""
    df = fetch_kline_df(stock_code, period)
    close = df["close"]
    ma = calc_ma(close, [ma_fast, ma_slow])

    ma_f = ma[f"MA{ma_fast}"]
    ma_s = ma[f"MA{ma_slow}"]
    cross = _cross_signal(ma_f, ma_s)

    latest_close = float(df["close"].iloc[-1])
    latest_ma_f = round(float(ma_f.iloc[-1]), 2)
    latest_ma_s = round(float(ma_s.iloc[-1]), 2)

    # 信号强度：基于均线偏离度
    deviation = abs(latest_close - latest_ma_s) / latest_ma_s * 100 if latest_ma_s else 0
    strength = min(100, max(0, round(deviation * 5 + (80 if cross == "金叉" else 20), 1)))

    return {
        "strategy": f"双均线交叉(MA{ma_fast}/MA{ma_slow})",
        "stock": stock_code,
        "latest_close": latest_close,
        "signals": [
            {"type": "均线交叉", "value": cross, "action": "买入" if cross == "金叉" else ("卖出" if cross == "死叉" else "观望")},
            {"type": f"MA{ma_fast}", "value": latest_ma_f},
            {"type": f"MA{ma_slow}", "value": latest_ma_s}
        ],
        "signal_strength": strength,
        "risk_warning": ["均线策略在震荡市中易产生假信号", "建议配合成交量确认"] if cross == "金叉" else [],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


@register_strategy("三均线多头/空头排列", "MA5>MA10>MA20为多头，反之为空头")
def strategy_triple_ma_alignment(stock_code: str, period: str = "近一年") -> Dict[str, Any]:
    """三均线多头排列策略"""
    df = fetch_kline_df(stock_code, period)
    close = df["close"]
    ma = calc_ma(close, [5, 10, 20])

    ma5 = float(ma["MA5"].iloc[-1])
    ma10 = float(ma["MA10"].iloc[-1])
    ma20 = float(ma["MA20"].iloc[-1])

    if ma5 > ma10 > ma20:
        alignment = "多头排列"
        action = "买入/持有"
        strength = min(100, round((ma5 - ma20) / ma20 * 200 + 60, 1))
    elif ma5 < ma10 < ma20:
        alignment = "空头排列"
        action = "卖出/观望"
        strength = min(100, round((ma20 - ma5) / ma20 * 200 + 60, 1))
    else:
        alignment = "交叉状态"
        action = "观望"
        strength = 30.0

    return {
        "strategy": "三均线排列(MA5/MA10/MA20)",
        "stock": stock_code,
        "latest_close": float(df["close"].iloc[-1]),
        "signals": [
            {"type": "均线排列", "value": alignment, "action": action},
            {"type": "MA5", "value": round(ma5, 2)},
            {"type": "MA10", "value": round(ma10, 2)},
            {"type": "MA20", "value": round(ma20, 2)}
        ],
        "signal_strength": strength,
        "risk_warning": ["多头排列在趋势末端可能见顶", "空头排列在超跌后可能反弹"] if alignment != "交叉状态" else [],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


@register_strategy("MACD零轴上方金叉", "MACD DIF>0时金叉为强势买入信号")
def strategy_macd_above_zero(stock_code: str, period: str = "近一年") -> Dict[str, Any]:
    """MACD零轴上方金叉策略"""
    df = fetch_kline_df(stock_code, period)
    close = df["close"]
    macd = calc_macd(close)

    dif = float(macd["DIF"].iloc[-1])
    dea = float(macd["DEA"].iloc[-1])
    hist = float(macd["MACD_Hist"].iloc[-1])
    cross = _cross_signal(macd["DIF"], macd["DEA"])

    above_zero = dif > 0 and dea > 0
    buy_signal = (cross == "金叉" and above_zero)

    if buy_signal:
        action = "强势买入"
        strength = min(100, round(abs(dif - dea) / abs(dea) * 500 + 70, 1)) if dea else 70.0
    elif cross == "金叉":
        action = "弱势买入（零轴下方）"
        strength = min(100, round(abs(dif - dea) / abs(dea) * 300 + 40, 1)) if dea else 40.0
    elif cross == "死叉":
        action = "卖出"
        strength = min(100, round(abs(dif - dea) / abs(dea) * 500 + 60, 1)) if dea else 30.0
    else:
        action = "观望"
        strength = 25.0

    return {
        "strategy": "MACD零轴上方金叉",
        "stock": stock_code,
        "latest_close": float(df["close"].iloc[-1]),
        "signals": [
            {"type": "DIF", "value": round(dif, 4)},
            {"type": "DEA", "value": round(dea, 4)},
            {"type": "MACD柱状图", "value": round(hist, 4)},
            {"type": "金叉/死叉", "value": cross},
            {"type": "零轴位置", "value": "零轴上方" if above_zero else "零轴下方"},
            {"type": "操作建议", "value": action}
        ],
        "signal_strength": strength,
        "risk_warning": ["零轴下方金叉可靠性较低", "需配合成交量确认"] if not buy_signal else [],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


@register_strategy("突破N日新高/新低", "股价突破N日内最高价或跌破最低价")
def strategy_breakout_n_day(stock_code: str, n_days: int = 20, period: str = "近一年") -> Dict[str, Any]:
    """突破N日新高/新低策略"""
    df = fetch_kline_df(stock_code, period)
    close = df["close"]
    high = df["high"]

    latest_close = float(close.iloc[-1])

    if len(df) < n_days + 1:
        return {"strategy": f"突破{n_days}日新高/新低", "stock": stock_code, "error": "数据不足"}

    # 计算N日内高低点（排除当日）
    high_series = df["high"]
    low_series = df["low"]
    recent_high = float(high_series.iloc[-(n_days+1):-1].max())
    recent_low = float(low_series.iloc[-(n_days+1):-1].min())

    if latest_close > recent_high:
        signal_type = f"突破{n_days}日新高"
        action = "买入"
        strength = min(100, round((latest_close - recent_high) / recent_high * 500 + 70, 1))
    elif latest_close < recent_low:
        signal_type = f"跌破{n_days}日新低"
        action = "卖出/止损"
        strength = min(100, round((recent_low - latest_close) / recent_low * 500 + 70, 1))
    else:
        signal_type = "区间内运行"
        action = "观望"
        # 计算当前位置百分比
        pos_pct = (latest_close - recent_low) / (recent_high - recent_low) * 100 if recent_high != recent_low else 50
        strength = round(pos_pct, 1)

    return {
        "strategy": f"突破{n_days}日新高/新低",
        "stock": stock_code,
        "latest_close": latest_close,
        "signals": [
            {"type": "信号类型", "value": signal_type, "action": action},
            {"type": f"{n_days}日内最高价", "value": round(recent_high, 2)},
            {"type": f"{n_days}日内最低价", "value": round(recent_low, 2)}
        ],
        "signal_strength": strength,
        "risk_warning": ["突破需配合放量确认", "假突破风险较高，建议设置止损"] if action == "买入" else [],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


# ═══════════════════════════════════════════════════════════
# 策略二：均值回归策略（Mean Reversion）
# ═══════════════════════════════════════════════════════════

@register_strategy("RSI超卖反弹", "RSI<30买入，RSI>70卖出")
def strategy_rsi_reversal(stock_code: str, rsi_period: int = 14, oversold: float = 30, overbought: float = 70, period: str = "近一年") -> Dict[str, Any]:
    """RSI超卖反弹策略"""
    df = fetch_kline_df(stock_code, period)
    close = df["close"]

    # 自定义周期RSI计算
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=rsi_period, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(window=rsi_period, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = (100 - 100 / (1 + rs)).fillna(50)

    latest_rsi = float(rsi_series.iloc[-1])

    if latest_rsi < oversold:
        signal_type = "超卖区域"
        action = "买入（反弹预期）"
        strength = min(100, round((oversold - latest_rsi) * 3 + 60, 1))
    elif latest_rsi > overbought:
        signal_type = "超买区域"
        action = "卖出（回调预期）"
        strength = min(100, round((latest_rsi - overbought) * 3 + 60, 1))
    else:
        signal_type = "正常区间"
        action = "观望"
        strength = 40.0

    return {
        "strategy": f"RSI{rsi_period}超卖反弹",
        "stock": stock_code,
        "latest_close": float(df["close"].iloc[-1]),
        "signals": [
            {"type": f"RSI({rsi_period})", "value": round(latest_rsi, 2)},
            {"type": "信号类型", "value": signal_type, "action": action},
            {"type": "超卖线", "value": oversold},
            {"type": "超买线", "value": overbought}
        ],
        "signal_strength": strength,
        "risk_warning": ["强趋势中RSI可能长期处于极端值", "建议配合支撑/阻力位确认"] if action != "观望" else [],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


@register_strategy("BOLL下轨支撑/上轨压力", "布林带下轨买入、上轨卖出")
def strategy_boll_band(stock_code: str, period_param: int = 20, num_std: float = 2.0, period: str = "近一年") -> Dict[str, Any]:
    """BOLL下轨支撑/上轨压力策略"""
    df = fetch_kline_df(stock_code, period)
    close = df["close"]

    boll = calc_boll(close, period_param, num_std)
    upper = float(boll["BOLL_UPPER"].iloc[-1])
    mid = float(boll["BOLL_MID"].iloc[-1])
    lower = float(boll["BOLL_LOWER"].iloc[-1])
    latest_close = float(df["close"].iloc[-1])

    bandwidth = (upper - lower) / mid * 100 if mid > 0 else 0
    position_pct = (latest_close - lower) / (upper - lower) * 100 if upper != lower else 50

    if latest_close <= lower:
        signal_type = "跌破下轨"
        action = "买入（超卖反弹）"
        strength = min(100, round((lower - latest_close) / lower * 200 + 70, 1))
    elif latest_close >= upper:
        signal_type = "突破上轨"
        action = "卖出（超买回调）"
        strength = min(100, round((latest_close - upper) / upper * 200 + 70, 1))
    elif latest_close > mid:
        signal_type = "中轨上方运行"
        action = "持有/偏多"
        strength = round(position_pct, 1)
    else:
        signal_type = "中轨下方运行"
        action = "观望/偏空"
        strength = round(100 - position_pct, 1)

    return {
        "strategy": f"BOLL({period_param},{num_std})支撑压力",
        "stock": stock_code,
        "latest_close": latest_close,
        "signals": [
            {"type": "上轨", "value": round(upper, 2)},
            {"type": "中轨", "value": round(mid, 2)},
            {"type": "下轨", "value": round(lower, 2)},
            {"type": "带宽%", "value": round(bandwidth, 2)},
            {"type": "信号类型", "value": signal_type, "action": action}
        ],
        "signal_strength": strength,
        "risk_warning": ["窄幅震荡时布林带信号频繁", "趋势行情中沿轨运行不宜反向操作"],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


@register_strategy("布林带收窄突破", "BandWidth收缩后突破方向跟随")
def strategy_boll_squeeze(stock_code: str, period_param: int = 20, num_std: float = 2.0, squeeze_threshold: float = 5.0, lookback: int = 10, period: str = "近一年") -> Dict[str, Any]:
    """布林带收窄突破策略"""
    df = fetch_kline_df(stock_code, period)
    close = df["close"]

    boll = calc_boll(close, period_param, num_std)
    bandwidth_series = (boll["BOLL_UPPER"] - boll["BOLL_LOWER"]) / boll["BOLL_MID"] * 100

    latest_bw = float(bandwidth_series.iloc[-1])
    avg_bw = float(bandwidth_series.iloc[-lookback:].mean()) if len(df) >= lookback else latest_bw

    # 判断是否收窄（当前带宽 < 历史平均且低于阈值）
    is_squeeze = latest_bw < squeeze_threshold and latest_bw < avg_bw * 0.8

    latest_close = float(close.iloc[-1])
    upper = float(boll["BOLL_UPPER"].iloc[-1])
    lower = float(boll["BOLL_LOWER"].iloc[-1])

    if is_squeeze:
        if latest_close > boll["BOLL_MID"].iloc[-1]:
            signal_type = "收窄后向上突破"
            action = "买入（跟随方向）"
            strength = min(100, round((latest_bw / avg_bw) * 30 + 65, 1)) if avg_bw else 65.0
        else:
            signal_type = "收窄后向下跌破"
            action = "卖出/做空（跟随方向）"
            strength = min(100, round((latest_bw / avg_bw) * 30 + 65, 1)) if avg_bw else 65.0
    elif latest_close > upper:
        signal_type = "突破上轨（非收窄状态）"
        action = "观望（可靠性低）"
        strength = 40.0
    elif latest_close < lower:
        signal_type = "跌破下轨（非收窄状态）"
        action = "观望（可靠性低）"
        strength = 35.0
    else:
        signal_type = "正常波动区间"
        action = "等待收窄信号"
        strength = 25.0

    return {
        "strategy": f"BOLL收窄突破({period_param},{num_std})",
        "stock": stock_code,
        "latest_close": latest_close,
        "signals": [
            {"type": "当前带宽%", "value": round(latest_bw, 2)},
            {"type": f"近{lookback}日平均带宽%", "value": round(avg_bw, 2)},
            {"type": "是否收窄", "value": "是" if is_squeeze else "否"},
            {"type": "信号类型", "value": signal_type, "action": action}
        ],
        "signal_strength": strength,
        "risk_warning": ["收窄后突破方向可能判断错误", "需配合成交量放大确认"],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


# ═══════════════════════════════════════════════════════════
# 策略三：动量策略（Momentum）
# ═══════════════════════════════════════════════════════════

@register_strategy("N日涨幅排名选股", "20日/60日涨幅TOP10")
def strategy_n_day_momentum(stock_code: str, n_days: int = 20, period: str = "近一年") -> Dict[str, Any]:
    """N日涨幅排名策略"""
    df = fetch_kline_df(stock_code, period)
    close = df["close"]

    if len(df) < n_days + 1:
        return {"strategy": f"N日涨幅({n_days}日)", "stock": stock_code, "error": "数据不足"}

    current_price = float(close.iloc[-1])
    price_n_ago = float(close.iloc[-(n_days+1)])
    change_pct = (current_price - price_n_ago) / price_n_ago * 100

    # 计算动量评分（基于涨幅和波动率）
    returns = close.pct_change().dropna()
    volatility = float(returns.iloc[-n_days:].std() * np.sqrt(252) * 100) if len(returns) >= n_days else 0

    # Sharpe-like score
    avg_return = float(returns.iloc[-n_days:].mean()) if len(returns) >= n_days else 0
    sharpe_like = (avg_return / returns.iloc[-n_days:].std() * np.sqrt(n_days)) if volatility > 0 else 0

    strength = min(100, max(0, round(change_pct * 2 + 50, 1)))

    if change_pct > 10:
        signal_type = "强势上涨"
        action = "持有/追涨（注意风险）"
    elif change_pct > 3:
        signal_type = "温和上涨"
        action = "关注/逢低买入"
    elif change_pct > -3:
        signal_type = "横盘震荡"
        action = "观望"
    else:
        signal_type = "下跌趋势"
        action = "回避"

    return {
        "strategy": f"N日涨幅({n_days}日)",
        "stock": stock_code,
        "latest_close": current_price,
        "signals": [
            {"type": f"{n_days}日涨跌幅%", "value": round(change_pct, 2)},
            {"type": "信号类型", "value": signal_type, "action": action},
            {"type": "年化波动率%", "value": round(volatility, 2)},
            {"type": "类夏普比率", "value": round(sharpe_like, 3)}
        ],
        "signal_strength": strength,
        "risk_warning": ["涨幅过大可能面临回调", "需结合基本面判断持续性"],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


@register_strategy("相对强度RS策略", "个股vs沪深300，RS>80为强势股")
def strategy_relative_strength(stock_code: str, period: str = "近一年") -> Dict[str, Any]:
    """相对强度RS策略"""
    df = fetch_kline_df(stock_code, period)

    # 获取沪深300作为基准
    try:
        benchmark_df = fetch_kline_df("000300", period)
    except Exception:
        return {"strategy": "相对强度RS", "stock": stock_code, "error": "无法获取沪深300数据"}

    # 计算累计收益率比率
    stock_returns = df["close"] / df["close"].iloc[0]
    bench_returns = benchmark_df["close"] / benchmark_df["close"].iloc[0]

    # 对齐日期（取交集）
    common_dates = df["date"].intersection(benchmark_df["date"])
    if len(common_dates) < 2:
        return {"strategy": "相对强度RS", "stock": stock_code, "error": "日期不匹配"}

    stock_aligned = df[df["date"].isin(common_dates)]["close"] / df[df["date"].isin(common_dates)]["close"].iloc[0]
    bench_aligned = benchmark_df[benchmark_df["date"].isin(common_dates)]["close"] / benchmark_df[benchmark_df["date"].isin(common_dates)]["close"].iloc[0]

    # RS比率
    rs_ratio = (stock_aligned.iloc[-1] / bench_aligned.iloc[-1]) if bench_aligned.iloc[-1] > 0 else 0

    # RS百分位（简化：基于RS比率映射到0-100）
    rs_score = min(100, max(0, round(rs_ratio * 50 - 20, 1)))

    if rs_score > 80:
        signal_type = "强势股"
        action = "重点关注/买入"
        strength = rs_score
    elif rs_score > 60:
        signal_type = "偏强"
        action = "关注"
        strength = rs_score
    elif rs_score > 40:
        signal_type = "中性"
        action = "观望"
        strength = rs_score
    else:
        signal_type = "弱势股"
        action = "回避"
        strength = rs_score

    stock_total_return = float((stock_aligned.iloc[-1] - 1) * 100)
    bench_total_return = float((bench_aligned.iloc[-1] - 1) * 100)

    return {
        "strategy": "相对强度RS(vs沪深300)",
        "stock": stock_code,
        "latest_close": float(df["close"].iloc[-1]),
        "signals": [
            {"type": "RS比率", "value": round(rs_ratio, 4)},
            {"type": "RS评分(0-100)", "value": rs_score},
            {"type": "信号类型", "value": signal_type, "action": action},
            {"type": "个股累计收益%", "value": round(stock_total_return, 2)},
            {"type": "沪深300累计收益%", "value": round(bench_total_return, 2)}
        ],
        "signal_strength": strength,
        "risk_warning": ["RS高位可能面临均值回归", "需结合市场整体趋势判断"],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


@register_strategy("加速上涨策略", "近5日涨幅>前5日涨幅")
def strategy_acceleration(stock_code: str, recent_days: int = 5, prior_days: int = 5, period: str = "近一年") -> Dict[str, Any]:
    """加速上涨策略"""
    df = fetch_kline_df(stock_code, period)
    close = df["close"]

    total_needed = recent_days + prior_days + 1
    if len(df) < total_needed:
        return {"strategy": "加速上涨", "stock": stock_code, "error": "数据不足"}

    # 近N日涨幅
    recent_start = close.iloc[-(total_needed)]
    mid_point = close.iloc[-(recent_days+1)]
    prior_start = close.iloc[-(total_needed)]

    recent_change = (float(close.iloc[-1]) - float(mid_point)) / float(mid_point) * 100
    prior_change = (float(mid_point) - float(prior_start)) / float(prior_start) * 100

    is_accelerating = recent_change > prior_change and recent_change > 0

    if is_accelerating:
        signal_type = "加速上涨"
        action = "买入/持有（动能增强）"
        strength = min(100, round(recent_change * 3 + 50, 1))
    elif recent_change > 0 and prior_change < 0:
        signal_type = "止跌反弹"
        action = "关注（可能反转）"
        strength = min(100, round(recent_change * 2 + 40, 1))
    elif recent_change < prior_change:
        signal_type = "动能减弱"
        action = "减仓/观望"
        strength = max(0, round(50 - abs(recent_change) * 2, 1))
    else:
        signal_type = "平稳运行"
        action = "观望"
        strength = 35.0

    return {
        "strategy": f"加速上涨({recent_days}日vs{prior_days}日)",
        "stock": stock_code,
        "latest_close": float(close.iloc[-1]),
        "signals": [
            {"type": f"近{recent_days}日涨幅%", "value": round(recent_change, 2)},
            {"type": f"前{prior_days}日涨幅%", "value": round(prior_change, 2)},
            {"type": "信号类型", "value": signal_type, "action": action},
            {"type": "是否加速", "value": "是" if is_accelerating else "否"}
        ],
        "signal_strength": strength,
        "risk_warning": ["加速上涨后可能面临获利回吐", "需设置止损位"],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


# ═══════════════════════════════════════════════════════════
# 策略四：龙头战法策略（Dragon Head）
# ═══════════════════════════════════════════════════════════

@register_strategy("连板梯队选股", "2板以上、板块内最早涨停")
def strategy_consecutive_limit_up(stock_code: str, min_boards: int = 2, period: str = "近半年") -> Dict[str, Any]:
    """连板梯队选股策略"""
    df = fetch_kline_df(stock_code, period)

    if len(df) < 5:
        return {"strategy": "连板梯队", "stock": stock_code, "error": "数据不足"}

    close = df["close"]
    prev_close = df["close"].shift(1)

    # 判断涨停（根据板块类型自动识别阈值）
    daily_change = (close - prev_close) / prev_close * 100
    threshold = _get_limit_threshold(stock_code)
    is_limit_up = daily_change >= threshold

    # 计算连续涨停天数
    consecutive_boards = 0
    for i in range(len(df)-1, max(0, len(df)-20), -1):
        if is_limit_up.iloc[i]:
            consecutive_boards += 1
        else:
            break

    # 统计近N日涨停次数
    recent_days = min(20, len(df))
    total_limit_ups = int(is_limit_up.iloc[-recent_days:].sum())

    latest_close = float(close.iloc[-1])
    latest_change = float(daily_change.iloc[-1]) if not pd.isna(daily_change.iloc[-1]) else 0

    if consecutive_boards >= min_boards:
        signal_type = f"连板{consecutive_boards}天（龙头候选）"
        action = "重点关注/打板买入"
        strength = min(100, round(consecutive_boards * 20 + 40, 1))
    elif total_limit_ups >= 2:
        signal_type = f"近{recent_days}日涨停{total_limit_ups}次（活跃股）"
        action = "关注/逢低介入"
        strength = min(100, round(total_limit_ups * 15 + 30, 1))
    else:
        signal_type = "无连板特征"
        action = "不符合龙头战法条件"
        strength = 10.0

    return {
        "strategy": f"连板梯队(≥{min_boards}板)",
        "stock": stock_code,
        "latest_close": latest_close,
        "signals": [
            {"type": "连续涨停天数", "value": consecutive_boards},
            {"type": f"近{recent_days}日涨停次数", "value": total_limit_ups},
            {"type": "今日涨跌幅%", "value": round(latest_change, 2)},
            {"type": "信号类型", "value": signal_type, "action": action}
        ],
        "signal_strength": strength,
        "risk_warning": ["连板股波动剧烈，风险极高", "需结合板块效应和资金面判断", "打板策略需要快速执行能力"],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


@register_strategy("首板打板策略", "当日首次涨停，流通市值<100亿")
def strategy_first_limit_up(stock_code: str, max_market_cap: float = 100, period: str = "近半年") -> Dict[str, Any]:
    """首板打板策略"""
    df = fetch_kline_df(stock_code, period)

    if len(df) < 5:
        return {"strategy": "首板打板", "stock": stock_code, "error": "数据不足"}

    close = df["close"]
    prev_close = df["close"].shift(1)
    daily_change = (close - prev_close) / prev_close * 100

    latest_change = float(daily_change.iloc[-1]) if not pd.isna(daily_change.iloc[-1]) else 0
    threshold = _get_limit_threshold(stock_code)
    is_today_limit_up = latest_change >= threshold

    # 检查前一日是否涨停（排除连板）
    prev_was_limit_up = False
    if len(df) >= 2:
        prev_change = float(daily_change.iloc[-2]) if not pd.isna(daily_change.iloc[-2]) else 0
        prev_was_limit_up = prev_change >= threshold

    is_first_board = is_today_limit_up and not prev_was_limit_up

    # 估算流通市值（简化：用最新价*成交量近似）
    latest_close = float(close.iloc[-1])
    avg_volume = float(df["volume"].iloc[-20:].mean()) if len(df) >= 20 else 0
    estimated_daily_turnover = latest_close * avg_volume

    if is_first_board:
        signal_type = "首板涨停"
        action = "打板买入（符合条件）"
        strength = min(100, round(latest_change + 50, 1))
    elif is_today_limit_up:
        signal_type = "连板涨停（非首板）"
        action = "不符合首板条件"
        strength = 30.0
    else:
        signal_type = "未涨停"
        action = "等待信号"
        strength = 5.0

    return {
        "strategy": f"首板打板(市值<{max_market_cap}亿)",
        "stock": stock_code,
        "latest_close": latest_close,
        "signals": [
            {"type": "今日涨跌幅%", "value": round(latest_change, 2)},
            {"type": "是否涨停", "value": "是" if is_today_limit_up else "否"},
            {"type": "是否首板", "value": "是" if is_first_board else "否"},
            {"type": "信号类型", "value": signal_type, "action": action},
            {"type": "日均成交额(万)", "value": round(estimated_daily_turnover / 10000, 2)}
        ],
        "signal_strength": strength,
        "risk_warning": ["打板策略风险极高，需严格止损", "建议结合板块热点和资金流向判断", "流通市值数据需通过财务API确认"],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


@register_strategy("换手板策略", "换手率>5%且封板")
def strategy_turnover_limit_up(stock_code: str, min_turnover_pct: float = 5.0, period: str = "近半年") -> Dict[str, Any]:
    """换手板策略"""
    df = fetch_kline_df(stock_code, period)

    if len(df) < 10:
        return {"strategy": "换手板", "stock": stock_code, "error": "数据不足"}

    close = df["close"]
    prev_close = df["close"].shift(1)
    daily_change = (close - prev_close) / prev_close * 100
    volume = df["volume"]

    latest_change = float(daily_change.iloc[-1]) if not pd.isna(daily_change.iloc[-1]) else 0
    threshold = _get_limit_threshold(stock_code)
    is_limit_up = latest_change >= threshold

    # 换手率估算（成交量/流通股本，简化用近20日平均成交量占比）
    avg_volume_20 = float(volume.iloc[-20:].mean()) if len(df) >= 20 else float(volume.mean())
    latest_volume = float(volume.iloc[-1])
    turnover_ratio = (latest_volume / avg_volume_20 - 1) * 100 if avg_volume_20 > 0 else 0

    # 换手率是否达标（放量>5%即视为活跃）
    is_high_turnover = latest_volume > avg_volume_20 * (1 + min_turnover_pct / 100)

    if is_limit_up and is_high_turnover:
        signal_type = "换手板（涨停+放量）"
        action = "买入（资金活跃确认）"
        strength = min(100, round(latest_change + turnover_ratio * 0.5 + 30, 1))
    elif is_limit_up:
        signal_type = "缩量板（涨停但换手不足）"
        action = "谨慎关注（需观察次日换手）"
        strength = min(100, round(latest_change + 20, 1))
    else:
        signal_type = "未涨停"
        action = "等待信号"
        strength = max(0, round(turnover_ratio * 2, 1))

    return {
        "strategy": f"换手板(换手>{min_turnover_pct}%)",
        "stock": stock_code,
        "latest_close": float(close.iloc[-1]),
        "signals": [
            {"type": "今日涨跌幅%", "value": round(latest_change, 2)},
            {"type": "是否涨停", "value": "是" if is_limit_up else "否"},
            {"type": "成交量放大%", "value": round(turnover_ratio, 2)},
            {"type": "换手达标", "value": "是" if is_high_turnover else "否"},
            {"type": "信号类型", "value": signal_type, "action": action}
        ],
        "signal_strength": strength,
        "risk_warning": ["高换手涨停可能为出货信号", "需结合封单量和板块效应判断"],
        "data_range": f"{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}"
    }


# ═══════════════════════════════════════════════════════════
# 策略五：低吸蓝筹策略（Blue Chip Dip）
# ═══════════════════════════════════════════════════════════

@register_strategy("PE/PB低于行业均值", "估值低于行业均值20%以上")
def strategy_undervalued_pe_pb(stock_code: str, discount_threshold: float = 20.0, period: str = "近三年") -> Dict[str, Any]:
    """PE/PB低于行业均值策略"""
    # 获取财务数据
    try:
        df_fin = fetch_financial_data(stock_code, ["市盈率", "市净率"], period)
    except Exception as e:
        return {"strategy": "PE/PB低估", "stock": stock_code, "error": f"无法获取财务数据: {str(e)}"}

    if df_fin.empty:
        return {"strategy": "PE/PB低估", "stock": stock_code, "error": "未获取到估值数据"}

    # 提取PE和PB（尝试从列名中匹配）
    pe_values = []
    pb_values = []
    for col in df_fin.columns:
        cl = col.lower()
        if "市盈" in cl or "pe" in cl:
            vals = pd.to_numeric(df_fin[col], errors="coerce").dropna()
            if len(vals) > 0:
                pe_values.extend(vals.tolist())
        elif "市净" in cl or "pb" in cl:
            vals = pd.to_numeric(df_fin[col], errors="coerce").dropna()
            if len(vals) > 0:
                pb_values.extend(vals.tolist())

    latest_pe = float(pe_values[-1]) if pe_values else None
    latest_pb = float(pb_values[-1]) if pb_values else None

    # 行业均值估算（简化：用历史均值作为参考）
    avg_pe = float(np.mean(pe_values)) if len(pe_values) > 1 else latest_pe
    avg_pb = float(np.mean(pb_values)) if len(pb_values) > 1 else latest_pb

    pe_discount = ((avg_pe - latest_pe) / avg_pe * 100) if (latest_pe and avg_pe) else 0
    pb_discount = ((avg_pb - latest_pb) / avg_pb * 100) if (latest_pb and avg_pb) else 0

    is_undervalued_pe = pe_discount > discount_threshold
    is_undervalued_pb = pb_discount > discount_threshold

    signals_list = []
    buy_signals = []

    if latest_pe:
        signals_list.append({"type": "最新PE", "value": round(latest_pe, 2)})
        signals_list.append({"type": "历史平均PE", "value": round(avg_pe, 2)})
        signals_list.append({"type": "PE折价%", "value": round(pe_discount, 2)})
        if is_undervalued_pe:
            buy_signals.append(True)

    if latest_pb:
        signals_list.append({"type": "最新PB", "value": round(latest_pb, 2)})
        signals_list.append({"type": "历史平均PB", "value": round(avg_pb, 2)})
        signals_list.append({"type": "PB折价%", "value": round(pb_discount, 2)})
        if is_undervalued_pb:
            buy_signals.append(True)

    strength = _signal_score(buy_signals) if buy_signals else 10.0

    if len(buy_signals) >= 2:
        signal_type = "PE/PB双低估"
        action = "买入（深度价值）"
    elif len(buy_signals) == 1:
        signal_type = "单指标低估"
        action = "关注（部分低估）"
    else:
        signal_type = "估值合理/偏高"
        action = "观望"

    return {
        "strategy": f"PE/PB低估(折价>{discount_threshold}%)",
        "stock": stock_code,
        "signals": signals_list + [{"type": "信号类型", "value": signal_type, "action": action}],
        "signal_strength": strength,
        "risk_warning": ["低估值可能反映基本面恶化", "价值陷阱风险：需排除业绩下滑股"],
    }


@register_strategy("ROE稳定优质策略", "ROE>15%且连续3年稳定")
def strategy_roe_stable(stock_code: str, min_roe: float = 15.0, min_years: int = 3, period: str = "近三年") -> Dict[str, Any]:
    """ROE稳定优质策略"""
    try:
        df_fin = fetch_financial_data(stock_code, ["净资产收益率", "ROE"], period)
    except Exception as e:
        return {"strategy": "ROE稳定", "stock": stock_code, "error": f"无法获取财务数据: {str(e)}"}

    if df_fin.empty:
        return {"strategy": "ROE稳定", "stock": stock_code, "error": "未获取到ROE数据"}

    # 提取ROE值
    roe_values = []
    for col in df_fin.columns:
        cl = col.lower()
        if "净资产收益" in cl or "roe" in cl:
            vals = pd.to_numeric(df_fin[col], errors="coerce").dropna()
            if len(vals) > 0:
                roe_values.extend(vals.tolist())

    if not roe_values:
        return {"strategy": "ROE稳定", "stock": stock_code, "error": "未提取到有效ROE数据"}

    # 检查连续N年ROE>阈值
    consecutive_years = 0
    for val in reversed(roe_values):
        if val > min_roe:
            consecutive_years += 1
        else:
            break

    latest_roe = roe_values[-1] if roe_values else None
    avg_roe = float(np.mean(roe_values)) if roe_values else None
    roe_std = float(np.std(roe_values)) if len(roe_values) > 1 else 0

    is_stable = consecutive_years >= min_years and roe_std < 5  # 标准差<5视为稳定

    signals_list = [
        {"type": "最新ROE%", "value": round(latest_roe, 2) if latest_roe else None},
        {"type": "平均ROE%", "value": round(avg_roe, 2) if avg_roe else None},
        {"type": "ROE标准差", "value": round(roe_std, 2)},
        {"type": f"连续>{min_roe}%年数", "value": consecutive_years}
    ]

    if is_stable:
        signal_type = "ROE稳定优质"
        action = "买入（长期持有）"
        strength = min(100, round(avg_roe * 3 + 20, 1)) if avg_roe else 60.0
    elif consecutive_years >= min_years:
        signal_type = "ROE达标但波动较大"
        action = "关注（需观察稳定性）"
        strength = min(100, round(avg_roe * 2 + 30, 1)) if avg_roe else 40.0
    else:
        signal_type = "ROE不达标"
        action = "回避"
        strength = max(0, round(latest_roe * 2, 1)) if latest_roe else 10.0

    return {
        "strategy": f"ROE稳定(>{min_roe}%,≥{min_years}年)",
        "stock": stock_code,
        "signals": signals_list + [{"type": "信号类型", "value": signal_type, "action": action}],
        "signal_strength": strength,
        "risk_warning": ["高ROE可能不可持续", "需排除周期性行业高点"],
    }


@register_strategy("高股息回调策略", "股息率>3%且近6个月股价回调>10%")
def strategy_dividend_dip(stock_code: str, min_dividend_yield: float = 3.0, min_pullback_pct: float = 10.0, period: str = "近两年") -> Dict[str, Any]:
    """高股息回调策略"""
    # 获取K线数据判断回调
    df = fetch_kline_df(stock_code, period)

    if len(df) < 60:
        return {"strategy": "高股息回调", "stock": stock_code, "error": "K线数据不足"}

    close = df["close"]
    latest_close = float(close.iloc[-1])

    # 计算近6个月（约120个交易日）的最大回撤
    lookback = min(120, len(df))
    high_6m = float(close.iloc[-lookback:].max())
    pullback_pct = (high_6m - latest_close) / high_6m * 100

    # 获取股息率数据
    try:
        df_fin = fetch_financial_data(stock_code, ["股息率"], "近三年")
        dividend_values = []
        for col in df_fin.columns:
            if "股息" in col.lower() or "dividend" in col.lower():
                vals = pd.to_numeric(df_fin[col], errors="coerce").dropna()
                if len(vals) > 0:
                    dividend_values.extend(vals.tolist())
        latest_dividend_yield = float(dividend_values[-1]) if dividend_values else None
    except Exception:
        latest_dividend_yield = None

    buy_signals = []
    signals_list = [
        {"type": "最新价", "value": round(latest_close, 2)},
        {"type": f"近6个月最高价", "value": round(high_6m, 2)},
        {"type": "回调幅度%", "value": round(pullback_pct, 2)}
    ]

    if latest_dividend_yield:
        signals_list.append({"type": "股息率%", "value": round(latest_dividend_yield, 2)})
        if latest_dividend_yield >= min_dividend_yield:
            buy_signals.append(True)

    if pullback_pct >= min_pullback_pct:
        buy_signals.append(True)

    strength = _signal_score(buy_signals) if buy_signals else 10.0

    if len(buy_signals) >= 2:
        signal_type = "高股息+深度回调"
        action = "买入（安全边际充足）"
    elif len(buy_signals) == 1:
        signal_type = "部分条件满足"
        action = "关注"
    else:
        signal_type = "不符合低吸条件"
        action = "观望"

    return {
        "strategy": f"高股息回调(股息>{min_dividend_yield}%,回撤>{min_pullback_pct}%)",
        "stock": stock_code,
        "signals": signals_list + [{"type": "信号类型", "value": signal_type, "action": action}],
        "signal_strength": strength,
        "risk_warning": ["股息率可能随股价下跌被动升高", "需确认公司持续分红能力"],
    }


# ═══════════════════════════════════════════════════════════
# 策略六：网格交易策略（Grid Trading）
# ═══════════════════════════════════════════════════════════

@register_strategy("等差网格交易", "设定基准价和固定间距，计算买卖档位")
def strategy_grid_arithmetic(stock_code: str, base_price: Optional[float] = None, grid_spacing: float = 0.02, num_grids_up: int = 5, num_grids_down: int = 5, period: str = "近半年") -> Dict[str, Any]:
    """等差网格交易策略"""
    df = fetch_kline_df(stock_code, period)

    if len(df) < 20:
        return {"strategy": "等差网格", "stock": stock_code, "error": "数据不足"}

    latest_close = float(df["close"].iloc[-1])
    base = base_price or latest_close

    # 生成网格档位（等差）
    grid_levels = []
    for i in range(-num_grids_down, num_grids_up + 1):
        price = round(base * (1 + grid_spacing * i), 2)
        action = "买入" if i < 0 else ("基准价" if i == 0 else "卖出")
        grid_levels.append({
            "grid_level": i,
            "price": price,
            "action": action,
            "distance_from_base_pct": round(grid_spacing * i * 100, 2)
        })

    # 统计历史价格在各网格的分布
    close_series = df["close"]
    grid_stats = {}
    for level in grid_levels:
        p = level["price"]
        count = int((close_series.between(p - grid_spacing * base / 2, p + grid_spacing * base / 2)).sum())
        grid_stats[level["grid_level"]] = {"touch_count": count}

    # 评估网格合理性
    price_range = float(close_series.max() - close_series.min())
    total_grid_range = base * grid_spacing * (num_grids_up + num_grids_down)
    coverage_ratio = price_range / total_grid_range if total_grid_range > 0 else 0

    return {
        "strategy": f"等差网格(间距{grid_spacing*100}%)",
        "stock": stock_code,
        "latest_close": latest_close,
        "base_price": base,
        "grid_plan": grid_levels,
        "grid_stats": grid_stats,
        "analysis": {
            "价格区间": f"¥{float(close_series.min()):.2f} ~ ¥{float(close_series.max()):.2f}",
            "网格覆盖范围": f"¥{grid_levels[0]['price']:.2f} ~ ¥{grid_levels[-1]['price']:.2f}",
            "覆盖率": round(coverage_ratio, 2),
            "建议": "网格间距适中" if 0.5 < coverage_ratio < 2 else ("间距过宽，可加密" if coverage_ratio > 2 else "间距过密，可放宽")
        },
        "signal_strength": min(100, round(50 / max(coverage_ratio, 0.5), 1)),
        "risk_warning": ["单边下跌行情中网格会持续买入", "需预留充足资金应对极端行情"],
    }


@register_strategy("等比网格交易", "设定基准价和比例间距，计算买卖档位")
def strategy_grid_geometric(stock_code: str, base_price: Optional[float] = None, grid_ratio: float = 0.02, num_grids_up: int = 5, num_grids_down: int = 5, period: str = "近半年") -> Dict[str, Any]:
    """等比网格交易策略"""
    df = fetch_kline_df(stock_code, period)

    if len(df) < 20:
        return {"strategy": "等比网格", "stock": stock_code, "error": "数据不足"}

    latest_close = float(df["close"].iloc[-1])
    base = base_price or latest_close

    # 生成网格档位（等比）
    grid_levels = []
    for i in range(-num_grids_down, num_grids_up + 1):
        price = round(base * ((1 + grid_ratio) ** i), 2)
        action = "买入" if i < 0 else ("基准价" if i == 0 else "卖出")
        grid_levels.append({
            "grid_level": i,
            "price": price,
            "action": action,
            "distance_from_base_pct": round(((1 + grid_ratio) ** i - 1) * 100, 2)
        })

    # 统计历史价格在各网格的分布
    close_series = df["close"]
    grid_stats = {}
    for level in grid_levels:
        p = level["price"]
        half_width = p * grid_ratio / 2
        count = int((close_series.between(p - half_width, p + half_width)).sum())
        grid_stats[level["grid_level"]] = {"touch_count": count}

    # 评估网格合理性
    price_range = float(close_series.max() / close_series.min())
    total_grid_ratio = (1 + grid_ratio) ** (num_grids_up + num_grids_down)
    coverage_ratio = price_range / total_grid_ratio if total_grid_ratio > 0 else 0

    return {
        "strategy": f"等比网格(比例{grid_ratio*100}%)",
        "stock": stock_code,
        "latest_close": latest_close,
        "base_price": base,
        "grid_plan": grid_levels,
        "grid_stats": grid_stats,
        "analysis": {
            "价格区间": f"¥{float(close_series.min()):.2f} ~ ¥{float(close_series.max()):.2f}",
            "网格覆盖范围": f"¥{grid_levels[0]['price']:.2f} ~ ¥{grid_levels[-1]['price']:.2f}",
            "价格极值比": round(price_range, 3),
            "覆盖率": round(coverage_ratio, 2),
            "建议": "等比网格适合波动较大的标的" if price_range > 1.5 else "标的波动较小，等差网格可能更合适"
        },
        "signal_strength": min(100, round(50 / max(coverage_ratio, 0.3), 1)),
        "risk_warning": ["等比网格在低价区密集、高价区稀疏", "适合波动率较高的标的"],
    }


# ═══════════════════════════════════════════════════════════
# 批量扫描与组合执行
# ═══════════════════════════════════════════════════════════

def run_strategy(strategy_name: str, stock_code: str, **kwargs) -> Dict[str, Any]:
    """运行指定策略"""
    if strategy_name not in STRATEGY_REGISTRY:
        available = list(STRATEGY_REGISTRY.keys())
        raise ValueError(f"未知策略 '{strategy_name}'。可用策略: {available}")

    display_name, func, description = STRATEGY_REGISTRY[strategy_name]
    print(f"\n{'='*60}")
    print(f"📊 策略执行: {display_name}")
    print(f"   标的: {stock_code}")
    print(f"   说明: {description}")
    print(f"{'='*60}")

    try:
        result = func(stock_code, **kwargs)
        result["strategy_display"] = display_name
        return result
    except Exception as e:
        error_result = {
            "strategy": display_name,
            "stock": stock_code,
            "error": str(e),
            "signal_strength": 0
        }
        print(f"❌ 执行失败: {e}")
        return error_result


def run_all_strategies(stock_code: str) -> List[Dict[str, Any]]:
    """对单只股票运行所有策略"""
    results = []
    for name in STRATEGY_REGISTRY:
        result = run_strategy(name, stock_code)
        results.append(result)
    return results


def scan_stocks(strategy_name: str, stock_codes: List[str], **kwargs) -> Dict[str, Any]:
    """批量扫描多只股票"""
    print(f"\n{'='*60}")
    print(f"🔍 批量扫描: {stock_codes[0]}等{len(stock_codes)}只股票")
    print(f"   策略: {STRATEGY_REGISTRY[strategy_name][0] if strategy_name in STRATEGY_REGISTRY else strategy_name}")
    print(f"{'='*60}")

    results = []
    for code in stock_codes:
        try:
            result = run_strategy(strategy_name, code, **kwargs)
            results.append(result)
        except Exception as e:
            results.append({
                "strategy": strategy_name,
                "stock": code,
                "error": str(e),
                "signal_strength": 0
            })

    # 按信号强度排序
    valid_results = [r for r in results if "error" not in r]
    valid_results.sort(key=lambda x: x.get("signal_strength", 0), reverse=True)

    return {
        "strategy_name": STRATEGY_REGISTRY.get(strategy_name, (strategy_name))[0],
        "total_stocks": len(stock_codes),
        "valid_results": len(valid_results),
        "results": valid_results
    }


# ═══════════════════════════════════════════════════════════
# 结果输出与保存
# ═══════════════════════════════════════════════════════════

def format_strategy_result(result: Dict[str, Any]) -> str:
    """格式化策略结果为可读字符串"""
    lines = []
    strategy_name = result.get("strategy_display", result.get("strategy", "未知"))
    stock = result.get("stock", "")

    if "error" in result:
        return f"❌ [{strategy_name}] {stock}: {result['error']}"

    lines.append(f"\n{'━'*50}")
    lines.append(f"📊 策略: {strategy_name}")
    lines.append(f"   标的: {stock}")
    if "latest_close" in result:
        lines.append(f"   最新价: ¥{result['latest_close']:.2f}")

    # 信号列表
    signals = result.get("signals", [])
    if signals:
        lines.append(f"\n   📋 信号详情:")
        for sig in signals:
            val_str = f"{sig['value']}" if not isinstance(sig['value'], str) else sig['value']
            action_str = f" → {sig['action']}" if "action" in sig else ""
            lines.append(f"      • {sig['type']}: {val_str}{action_str}")

    # 信号强度
    strength = result.get("signal_strength", 0)
    emoji = "🟢" if strength >= 70 else ("🟡" if strength >= 40 else "🔴")
    lines.append(f"\n   {emoji} 信号强度: {strength}/100")

    # 风险提示
    warnings = result.get("risk_warning", [])
    if warnings:
        lines.append(f"\n   ⚠️ 风险提示:")
        for w in warnings:
            lines.append(f"      • {w}")

    # 网格计划表（特殊处理）
    grid_plan = result.get("grid_plan", [])
    if grid_plan:
        lines.append(f"\n   📐 网格交易计划表:")
        lines.append(f"      {'档位':>6} | {'价格':>10} | {'操作':>6} | {'距基准%':>8}")
        lines.append(f"      {'-'*6}-+-{'-'*10}-+-{'-'*6}-+-{'-'*8}")
        for g in grid_plan:
            lines.append(f"      {g['grid_level']:>6} | ¥{g['price']:>9.2f} | {g['action']:>6} | {g['distance_from_base_pct']:>7.2f}%")

    # 分析建议（网格策略）
    analysis = result.get("analysis", {})
    if analysis:
        lines.append(f"\n   💡 分析建议:")
        for k, v in analysis.items():
            lines.append(f"      • {k}: {v}")

    data_range = result.get("data_range", "")
    if data_range:
        lines.append(f"\n   📅 数据范围: {data_range}")

    return "\n".join(lines)


def save_results(results: List[Dict[str, Any]], output_path: Optional[Path] = None) -> Path:
    """保存结果到JSON文件"""
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_DIR / f"multi_strategy_{timestamp}.json"

    # 确保可序列化
    serializable_results = []
    for r in results:
        clean_r = {}
        for k, v in r.items():
            if isinstance(v, (str, int, float, bool, type(None), list, dict)):
                clean_r[k] = v
            else:
                clean_r[k] = str(v)
        serializable_results.append(clean_r)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable_results, f, ensure_ascii=False, indent=2)

    return output_path


# ═══════════════════════════════════════════════════════════
# 策略对比表生成
# ═══════════════════════════════════════════════════════════

def generate_strategy_comparison() -> str:
    """生成策略对比表"""
    comparison_data = [
        {"策略": "双均线交叉", "类别": "趋势跟踪", "胜率": "~55%", "盈亏比": "~1.5:1", "适用周期": "日线/周线", "市场环境": "趋势行情"},
        {"策略": "三均线排列", "类别": "趋势跟踪", "胜率": "~60%", "盈亏比": "~2:1", "适用周期": "日线/周线", "市场环境": "单边趋势"},
        {"策略": "MACD零轴金叉", "类别": "趋势跟踪", "胜率": "~58%", "盈亏比": "~1.8:1", "适用周期": "日线", "市场环境": "上升趋势"},
        {"策略": "突破N日新高", "类别": "趋势跟踪", "胜率": "~45%", "盈亏比": "~2.5:1", "适用周期": "日线/周线", "市场环境": "强势行情"},
        {"策略": "RSI超卖反弹", "类别": "均值回归", "胜率": "~60%", "盈亏比": "~1.3:1", "适用周期": "日线", "市场环境": "震荡市"},
        {"策略": "BOLL支撑压力", "类别": "均值回归", "胜率": "~55%", "盈亏比": "~1.2:1", "适用周期": "日线/60分钟", "市场环境": "区间震荡"},
        {"策略": "布林带收窄突破", "类别": "均值回归", "胜率": "~50%", "盈亏比": "~2:1", "适用周期": "日线/周线", "市场环境": "变盘期"},
        {"策略": "N日涨幅排名", "类别": "动量", "胜率": "~45%", "盈亏比": "~2.5:1", "适用周期": "周线/月线", "市场环境": "牛市/结构性行情"},
        {"策略": "相对强度RS", "类别": "动量", "胜率": "~55%", "盈亏比": "~2:1", "适用周期": "周线", "市场环境": "任何市场"},
        {"策略": "加速上涨", "类别": "动量", "胜率": "~40%", "盈亏比": "~3:1", "适用周期": "日线/60分钟", "市场环境": "强势行情"},
        {"策略": "连板梯队", "类别": "龙头战法", "胜率": "~35%", "盈亏比": "~3:1", "适用周期": "日线(T+1)", "市场环境": "热点题材"},
        {"策略": "首板打板", "类别": "龙头战法", "胜率": "~40%", "盈亏比": "~2.5:1", "适用周期": "日线(盘中)", "市场环境": "活跃市"},
        {"策略": "换手板", "类别": "龙头战法", "胜率": "~45%", "盈亏比": "~2:1", "适用周期": "日线(T+1)", "市场环境": "资金活跃期"},
        {"策略": "PE/PB低估", "类别": "低吸蓝筹", "胜率": "~65%", "盈亏比": "~1.5:1", "适用周期": "月线/季线", "市场环境": "任何市场(长期)"},
        {"策略": "ROE稳定优质", "类别": "低吸蓝筹", "胜率": "~70%", "盈亏比": "~2:1", "适用周期": "季线/年线", "市场环境": "价值投资"},
        {"策略": "高股息回调", "类别": "低吸蓝筹", "胜率": "~65%", "盈亏比": "~1.8:1", "适用周期": "月线", "市场环境": "熊市/震荡市"},
        {"策略": "等差网格", "类别": "网格交易", "胜率": "~70%", "盈亏比": "~1:1", "适用周期": "分钟/日线", "市场环境": "区间震荡"},
        {"策略": "等比网格", "类别": "网格交易", "胜率": "~65%", "盈亏比": "~1.2:1", "适用周期": "分钟/日线", "市场环境": "宽幅震荡"},
    ]

    lines = []
    lines.append("\n" + "="*90)
    lines.append("📊 A股多策略库 - 策略对比表")
    lines.append("="*90)

    header = f"{'策略':<14} | {'类别':<8} | {'胜率':>6} | {'盈亏比':>7} | {'适用周期':<12} | {'市场环境':<10}"
    lines.append(header)
    lines.append("-" * len(header))

    for row in comparison_data:
        line = f"{row['策略']:<14} | {row['类别']:<8} | {row['胜率']:>6} | {row['盈亏比']:>7} | {row['适用周期']:<12} | {row['市场环境']:<10}"
        lines.append(line)

    lines.append("="*90)
    lines.append("注: 胜率和盈亏比为历史回测参考值，实际表现因市场环境和执行质量而异。")
    lines.append("    数据仅供参考，不构成投资建议。\n")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# CLI入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="A股多策略库 - 多种经典交易策略的自动化执行和对比分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
可用策略列表:
  趋势跟踪:
    dual_ma_crossover     双均线金叉/死叉(MA5/MA20)
    triple_ma_alignment   三均线多头/空头排列
    macd_above_zero       MACD零轴上方金叉
    breakout_n_day        突破N日新高/新低

  均值回归:
    rsi_reversal          RSI超卖反弹
    boll_band             BOLL下轨支撑/上轨压力
    boll_squeeze          布林带收窄突破

  动量策略:
    n_day_momentum        N日涨幅排名选股
    relative_strength     相对强度RS策略
    acceleration          加速上涨策略

  龙头战法:
    consecutive_limit_up  连板梯队选股
    first_limit_up        首板打板策略
    turnover_limit_up     换手板策略

  低吸蓝筹:
    undervalued_pe_pb     PE/PB低于行业均值
    roe_stable            ROE稳定优质策略
    dividend_dip          高股息回调策略

  网格交易:
    grid_arithmetic       等差网格交易
    grid_geometric        等比网格交易

示例:
  # 执行单个策略
  python multi_strategy.py --strategy dual_ma_crossover 600519

  # 对单只股票运行所有策略
  python multi_strategy.py --all 贵州茅台

  # 批量扫描（从文件读取股票代码）
  python multi_strategy.py --strategy rsi_reversal --stocks stocks.txt

  # 查看策略对比表
  python multi_strategy.py --comparison

  # 自定义参数
  python multi_strategy.py --strategy breakout_n_day 000001 --n_days 60
        """
    )

    parser.add_argument("--strategy", "-s", type=str, help="指定策略名称")
    parser.add_argument("--all", "-a", action="store_true", help="运行所有策略")
    parser.add_argument("--stocks", type=str, help="股票代码列表文件路径（每行一个）")
    parser.add_argument("--comparison", "-c", action="store_true", help="显示策略对比表")
    parser.add_argument("stock_code", nargs="?", default=None, help="股票代码或名称")

    args = parser.parse_args()

    # 策略对比表
    if args.comparison:
        print(generate_strategy_comparison())
        return

    # 无参数时显示帮助
    if not args.strategy and not args.all and not args.stocks:
        parser.print_help()
        print("\n💡 提示: 使用 --comparison 查看策略对比表")
        return

    stock_codes = []

    # 从文件读取股票列表
    if args.stocks:
        stocks_path = Path(args.stocks)
        if stocks_path.exists():
            with open(stocks_path, "r", encoding="utf-8") as f:
                stock_codes = [line.strip() for line in f if line.strip()]
        else:
            print(f"❌ 文件不存在: {stocks_path}")
            return

    # 命令行传入股票代码
    if args.stock_code:
        stock_codes.append(args.stock_code)

    results = []

    if args.all and stock_codes:
        # 对所有股票运行所有策略
        for code in stock_codes:
            stock_results = run_all_strategies(code)
            results.extend(stock_results)
    elif args.strategy and stock_codes:
        # 批量扫描
        scan_result = scan_stocks(args.strategy, stock_codes)
        results = scan_result.get("results", [])
        print(f"\n{'='*60}")
        print(f"📊 扫描完成")
        print(f"   策略: {scan_result['strategy_name']}")
        print(f"   总股票数: {scan_result['total_stocks']}")
        print(f"   有效结果: {scan_result['valid_results']}")
        print(f"{'='*60}")

        # 打印Top10
        for i, r in enumerate(results[:10]):
            print(format_strategy_result(r))
    else:
        parser.print_help()
        return

    # 输出结果
    if results and not args.stocks:
        for r in results:
            print(format_strategy_result(r))

    # 保存JSON
    output_path = save_results(results)
    print(f"\n✅ 结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
