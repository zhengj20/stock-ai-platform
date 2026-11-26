#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股多因子选股框架 (Multi-Factor Stock Selection Framework)

基于免费公开接口（东方财富数据中心/行情 + 腾讯行情）获取估值、财务与行情数据，
实现经典量化因子的计算与选股。

依赖: pandas, numpy, scipy(可选), requests
用法: python multi_factor.py [选项]

版本: 2.0.0
"""

import sys
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
import numpy as np
import requests

# scipy 可选依赖（仅IC加权时需要）
try:
    from scipy import stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ============================================================================
# 数据获取层（腾讯 + 东方财富公开接口，免费无需凭证）
# ============================================================================

_TX_KLINE_PATH = "/appstock/app/fqkline/get"
_TX_SMARTBOX_URL = "https://smartbox.gtimg.cn/s3/"
_TX_HOSTS = ["https://web.ifzq.gtimg.cn", "https://ifzq.gtimg.cn",
             "https://proxy.finance.qq.com/ifzqgtimg"]
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EM_DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


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

    返回 (代码, 显式symbol)：入参自带 sh/sz/bj 前缀（指数如 sh000300）时原样保留，
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
    """腾讯前复权日线（主源，量单位：手）。三个入口等价、限流互相独立，逐个尝试。"""
    symbol = symbol or _tx_symbol(code)
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


def _fetch_sina_kline(code: str, bars: int, symbol: str = None) -> List[list]:
    """新浪日线（备源，量单位：股；不复权）。"""
    try:
        resp = _get("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData",
                    {"symbol": symbol or _tx_symbol(code), "scale": "240",
                     "ma": "no", "datalen": str(bars)},
                    {"Referer": "https://finance.sina.com.cn/"}, retries=2)
        data = resp.json() or []
    except Exception:
        return []
    rows: List[list] = []
    for item in data:
        # 新浪字段序 open/high/low/close，转成与腾讯一致的 日期,开,收,高,低,量
        rows.append([item.get("day"), item.get("open"), item.get("close"),
                     item.get("high"), item.get("low"), item.get("volume")])
    return rows


def _fetch_em_kline_full(code: str, bars: int, symbol: str = None) -> List[list]:
    """东财前复权日线（含成交额/换手率，量单位：手）。该接口限流较凶，仅作补源。"""
    try:
        resp = _get(_EM_KLINE_URL, {
            "secid": _secid(code, symbol),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101", "fqt": "1", "lmt": str(bars), "end": "20500000",
            "ut": _EM_UT,
        }, {"Referer": "https://quote.eastmoney.com/"}, retries=2)
        klines = (resp.json().get("data") or {}).get("klines") or []
    except Exception:
        return []
    if not klines:
        return []
    # 字段顺序：日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
    return [line.split(",")[:11] for line in klines[-bars:]]


def fetch_kline_df(stock_code: str, bars: int = 250, symbol: Optional[str] = None) -> pd.DataFrame:
    """
    获取日线（腾讯前复权主源 → 新浪备源 → 东财补源）。

    返回按日期升序的 DataFrame，列：
      [date, open, high, low, close, volume(股), amount, turnover]
    amount / turnover 仅东财源提供，其余源为缺失，由调用方决定是否推算。
    """
    code, parsed_symbol = _norm_code(stock_code)
    symbol = symbol or parsed_symbol

    df: Optional[pd.DataFrame] = None
    vol_mult = 1.0  # 腾讯/东财量单位为手，新浪为股，统一到股
    rows = _fetch_tx_kline(code, bars, symbol)
    if rows:
        df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])
        vol_mult = 100.0
    else:
        sina_rows = _fetch_sina_kline(code, bars, symbol)
        if sina_rows:
            df = pd.DataFrame(sina_rows, columns=["date", "open", "close", "high", "low", "volume"])
        else:
            em_rows = _fetch_em_kline_full(code, bars, symbol)
            if em_rows:
                df = pd.DataFrame(em_rows, columns=[
                    "date", "open", "close", "high", "low", "volume",
                    "amount", "amplitude", "pct_chg", "chg", "turnover"])
                vol_mult = 100.0
    if df is None:
        raise RuntimeError(f"未获取到K线数据，请检查股票代码是否正确: {stock_code}")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce") * vol_mult

    if "amount" not in df.columns:
        df["amount"] = pd.NA
    if "turnover" not in df.columns:
        df["turnover"] = pd.NA
    for col in ["open", "high", "low", "close", "volume", "amount", "turnover"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.drop_duplicates(subset=["date"], keep="last")
    df.dropna(subset=["close"], inplace=True)
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df[["date", "open", "high", "low", "close", "volume", "amount", "turnover"]]


def _em_datacenter(report: str, flt: str, sort_columns: str = None,
                   page_size: int = 8, max_pages: int = 1) -> List[Dict[str, Any]]:
    """
    东方财富数据中心公开接口（RPT_* 报表），按 sort_columns 倒序取数。

    flt 为东财过滤表达式，如 '(SECUCODE="600519.SH")'。请求失败直接抛异常，
    由调用方决定降级策略。
    """
    records: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params = {
            "reportName": report, "columns": "ALL", "filter": flt,
            "pageNumber": str(page), "pageSize": str(page_size),
            "source": "WEB", "client": "PC",
        }
        if sort_columns:
            params["sortColumns"] = sort_columns
            params["sortTypes"] = "-1"
        payload = _get(_EM_DC_URL, params).json()
        data = (payload.get("result") or {}).get("data") or []
        records.extend(data)
        if len(data) < page_size:
            break
    return records


def fetch_latest_valuation(stock_code: str) -> Dict[str, Any]:
    """
    最新估值快照（东财每日估值分析明细）。

    关键字段：PE_TTM / PE_LAR / PB_MRQ / PS_TTM / PCF_OCF_TTM /
              TOTAL_MARKET_CAP(元) / CLOSE_PRICE / TRADE_DATE
    """
    code, _ = _norm_code(stock_code)
    rows = _em_datacenter("RPT_VALUEANALYSIS_DET", f'(SECURITY_CODE="{code}")',
                          sort_columns="TRADE_DATE", page_size=1)
    return rows[0] if rows else {}


def fetch_financial_reports(stock_code: str, periods: int = 8) -> List[Dict[str, Any]]:
    """
    东财F10主要财务指标（按报告期倒序）。

    关键字段：REPORT_DATE / EPSJB / EPSJBTZ / ROEJQ / ZZCJLL / XSMLL / XSJLL /
              ZCFZL / MGJYXJJE / TOTALOPERATEREVE(TZ) / PARENTNETPROFIT(TZ) /
              KCFJCXSYJLR(TZ)（TZ为同比增速%，比率均为%）
    """
    code, _ = _norm_code(stock_code)
    secucode = f"{code}.{'SH' if _secid(code).startswith('1.') else 'SZ'}"
    return _em_datacenter("RPT_F10_FINANCE_MAINFINADATA", f'(SECUCODE="{secucode}")',
                          sort_columns="REPORT_DATE", page_size=periods)


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


# ============================================================================
# 因子计算模块
# ============================================================================

class FactorCalculator:
    """多因子计算器 - 实现26个经典量化因子（免费公开接口取数）"""

    # 动量/波动/流动性因子最多需要60日窗口，130根K线留有余量
    _KLINE_BARS = 130

    def __init__(self):
        self._snap: Dict[str, Dict[str, Any]] = {}
        self._hs300_cache: Optional[pd.Series] = None

    # ------------------------------------------------------------------
    # 数据获取辅助方法
    # ------------------------------------------------------------------

    def _snapshot(self, stock_name: str) -> Dict[str, Any]:
        """按股票获取并缓存原始数据（估值/财报/K线），单类数据失败不影响其他因子"""
        if stock_name not in self._snap:
            code, symbol = _norm_code(stock_name)
            snap: Dict[str, Any] = {"code": code, "symbol": symbol,
                                    "val": {}, "reports": [], "kline": None}
            try:
                snap["val"] = fetch_latest_valuation(code)
            except Exception as e:
                print(f"  ⚠️ 获取{stock_name}估值数据失败: {e}")
            try:
                snap["reports"] = fetch_financial_reports(code)
            except Exception as e:
                print(f"  ⚠️ 获取{stock_name}财务数据失败: {e}")
            try:
                snap["kline"] = fetch_kline_df(code, self._KLINE_BARS, symbol)
            except Exception as e:
                print(f"  ⚠️ 获取{stock_name}K线数据失败: {e}")
            self._snap[stock_name] = snap
        return self._snap[stock_name]

    @staticmethod
    def _num(val) -> Optional[float]:
        """安全转换为float（None/NaN/非数值返回None）"""
        try:
            f = float(val)
            return f if f == f else None
        except (TypeError, ValueError):
            return None

    def _val(self, stock_name: str, key: str) -> Optional[float]:
        """从最新估值快照取字段"""
        return self._num(self._snapshot(stock_name)["val"].get(key))

    def _report(self, stock_name: str) -> Dict[str, Any]:
        """最新报告期财务数据"""
        reports = self._snapshot(stock_name)["reports"]
        return reports[0] if reports else {}

    def _yoy_report(self, stock_name: str) -> Dict[str, Any]:
        """去年同期报告期财务数据（按报告期月份匹配）"""
        reports = self._snapshot(stock_name)["reports"]
        if not reports:
            return {}
        cur = str(reports[0].get("REPORT_DATE", ""))[:10]
        if len(cur) != 10:
            return {}
        target = f"{int(cur[:4]) - 1}{cur[4:]}"
        for r in reports:
            if str(r.get("REPORT_DATE", ""))[:10] == target:
                return r
        return {}

    def _rep_num(self, stock_name: str, key: str) -> Optional[float]:
        """从最新报告期取财务字段"""
        return self._num(self._report(stock_name).get(key))

    def _kline(self, stock_name: str) -> Optional[pd.DataFrame]:
        return self._snapshot(stock_name)["kline"]

    def _closes(self, stock_name: str) -> pd.Series:
        df = self._kline(stock_name)
        return df["close"] if df is not None and len(df) else pd.Series(dtype=float)

    def _hs300_closes(self) -> pd.Series:
        """沪深300收盘价序列（缓存，失败返回空序列）"""
        if self._hs300_cache is None:
            try:
                df = fetch_kline_df("sh000300", self._KLINE_BARS)
                self._hs300_cache = df["close"]
            except Exception as e:
                print(f"  ⚠️ 获取沪深300行情失败: {e}")
                self._hs300_cache = pd.Series(dtype=float)
        return self._hs300_cache

    def _fetch_market_cap(self, stock_name: str) -> Optional[float]:
        """获取个股总市值（亿元）"""
        cap = self._val(stock_name, "TOTAL_MARKET_CAP")
        return cap / 1e8 if cap else None

    # ------------------------------------------------------------------
    # 价值因子 (Value Factors) - 信号方向: 越低越好
    # ------------------------------------------------------------------

    def calc_pe_ttm(self, stock_name: str) -> Optional[float]:
        """1. PE_TTM（市盈率-滚动）"""
        return self._val(stock_name, "PE_TTM")

    def calc_pb(self, stock_name: str) -> Optional[float]:
        """2. PB（市净率）"""
        return self._val(stock_name, "PB_MRQ")

    def calc_ps_ttm(self, stock_name: str) -> Optional[float]:
        """3. PS_TTM（市销率）"""
        return self._val(stock_name, "PS_TTM")

    def calc_pcf(self, stock_name: str) -> Optional[float]:
        """4. PCF（市现率，经营现金流TTM口径）"""
        return self._val(stock_name, "PCF_OCF_TTM")

    def calc_dividend_yield(self, stock_name: str) -> Optional[float]:
        """5. 股息率（近12个月每股税前派息/最新价，小数；越高越好）"""
        snap = self._snapshot(stock_name)
        try:
            rows = _em_datacenter("RPT_SHAREBONUS_DET",
                                  f'(SECURITY_CODE="{snap["code"]}")',
                                  sort_columns="EX_DIVIDEND_DATE", page_size=20)
        except Exception as e:
            print(f"  ⚠️ {stock_name} 分红数据获取失败: {e}")
            return None
        price = snap["val"].get("CLOSE_PRICE") or _latest_price(snap["code"], snap["symbol"])
        price = self._num(price)
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
            return dps / price
        return None

    # ------------------------------------------------------------------
    # 成长因子 (Growth Factors) - 信号方向: 越高越好（单位%）
    # ------------------------------------------------------------------

    def calc_revenue_growth(self, stock_name: str) -> Optional[float]:
        """6. 营收同比增长率（最新报告期）"""
        return self._rep_num(stock_name, "TOTALOPERATEREVETZ")

    def calc_net_profit_growth(self, stock_name: str) -> Optional[float]:
        """7. 净利润同比增长率（最新报告期，归母口径）"""
        return self._rep_num(stock_name, "PARENTNETPROFITTZ")

    def calc_roe_change(self, stock_name: str) -> Optional[float]:
        """8. ROE同比变化 = 本期加权ROE - 去年同期加权ROE（百分点）"""
        cur = self._rep_num(stock_name, "ROEJQ")
        prev = self._num(self._yoy_report(stock_name).get("ROEJQ"))
        if cur is not None and prev is not None:
            return cur - prev
        return None

    def calc_eps_growth(self, stock_name: str) -> Optional[float]:
        """9. EPS增长率（最新报告期基本EPS同比）"""
        return self._rep_num(stock_name, "EPSJBTZ")

    def calc_deducted_profit_growth(self, stock_name: str) -> Optional[float]:
        """10. 扣非净利润增速（最新报告期）"""
        return self._rep_num(stock_name, "KCFJCXSYJLRTZ")

    # ------------------------------------------------------------------
    # 质量因子 (Quality Factors) - ROE/ROA/毛利率越高越好，负债率越低越好
    # ------------------------------------------------------------------

    def calc_roe(self, stock_name: str) -> Optional[float]:
        """11. ROE（加权净资产收益率，%）"""
        return self._rep_num(stock_name, "ROEJQ")

    def calc_roa(self, stock_name: str) -> Optional[float]:
        """12. ROA（总资产收益率，%）"""
        return self._rep_num(stock_name, "ZZCJLL")

    def calc_gross_margin(self, stock_name: str) -> Optional[float]:
        """13. 毛利率（销售毛利率，%）"""
        return self._rep_num(stock_name, "XSMLL")

    def calc_net_margin(self, stock_name: str) -> Optional[float]:
        """14. 净利率（销售净利率，%）"""
        return self._rep_num(stock_name, "XSJLL")

    def calc_debt_ratio(self, stock_name: str) -> Optional[float]:
        """15. 资产负债率（%，越低越好）"""
        return self._rep_num(stock_name, "ZCFZL")

    def calc_ocf_to_net_profit(self, stock_name: str) -> Optional[float]:
        """16. 经营现金流/净利润比率（每股口径，%，>100为佳）"""
        ocf_ps = self._rep_num(stock_name, "MGJYXJJE")
        eps = self._rep_num(stock_name, "EPSJB")
        if ocf_ps is not None and eps:
            return ocf_ps / abs(eps) * 100
        return None

    # ------------------------------------------------------------------
    # 动量因子 (Momentum Factors) - 信号方向: 越高越好
    # ------------------------------------------------------------------

    def calc_momentum_20d(self, stock_name: str) -> Optional[float]:
        """17. 20日动量（价格变化率%）"""
        closes = self._closes(stock_name)
        if len(closes) >= 21:
            return (closes.iloc[-1] / closes.iloc[-21] - 1) * 100
        return None

    def calc_momentum_60d(self, stock_name: str) -> Optional[float]:
        """18. 60日动量（价格变化率%）"""
        closes = self._closes(stock_name)
        if len(closes) >= 61:
            return (closes.iloc[-1] / closes.iloc[-61] - 1) * 100
        return None

    def calc_relative_strength(self, stock_name: str, days: int = 60) -> Optional[float]:
        """19. 相对强度RS（vs沪深300）= 个股涨幅 / 沪深300涨幅"""
        closes = self._closes(stock_name)
        hs300 = self._hs300_closes()
        if len(closes) < days + 1 or len(hs300) < days + 1:
            return None
        stock_return = (closes.iloc[-1] / closes.iloc[-days - 1] - 1) * 100
        hs300_return = (hs300.iloc[-1] / hs300.iloc[-days - 1] - 1) * 100
        if abs(hs300_return) > 0.01:
            return stock_return / hs300_return
        return None

    def calc_breakout_signal(self, stock_name: str, n_days: int = 20) -> Optional[float]:
        """20. 突破信号（当前价距离N日高点的百分比，越接近0越强）"""
        df = self._kline(stock_name)
        if df is None or len(df) < n_days:
            return None
        current_price = df["close"].iloc[-1]
        highest_high = df["high"].iloc[-n_days:].max()
        if highest_high > 0:
            return (current_price / highest_high - 1) * 100
        return None

    # ------------------------------------------------------------------
    # 波动因子 (Volatility Factors) - 信号方向: 越低越好（通常）
    # ------------------------------------------------------------------

    def calc_historical_volatility(self, stock_name: str, days: int = 20) -> Optional[float]:
        """21. 20日历史波动率（年化%）"""
        closes = self._closes(stock_name)
        returns = closes.pct_change().dropna().tail(days)
        if len(returns) > 1:
            return returns.std() * np.sqrt(252) * 100
        return None

    def calc_beta(self, stock_name: str, days: int = 60) -> Optional[float]:
        """22. Beta系数（vs沪深300）"""
        closes = self._closes(stock_name)
        hs300 = self._hs300_closes()
        stock_returns = closes.pct_change().dropna()
        market_returns = hs300.pct_change().dropna()
        min_len = min(len(stock_returns), len(market_returns))
        if min_len < days:
            return None
        stock_r = stock_returns.tail(min_len).values[:days]
        market_r = market_returns.tail(min_len).values[:days]
        cov = np.cov(stock_r, market_r)[0][1]
        var_market = np.var(market_r, ddof=1)
        if var_market > 0:
            return cov / var_market
        return None

    def calc_max_drawdown(self, stock_name: str, days: int = 60) -> Optional[float]:
        """23. 最大回撤（近60日，负值越接近0越好）"""
        closes = self._closes(stock_name).tail(days)
        if len(closes) >= 10:
            rolling_max = closes.cummax()
            drawdowns = (closes - rolling_max) / rolling_max * 100
            return drawdowns.min()
        return None

    # ------------------------------------------------------------------
    # 流动性因子 (Liquidity Factors)
    # ------------------------------------------------------------------

    def calc_turnover_rate(self, stock_name: str, days: int = 20) -> Optional[float]:
        """24. 换手率（近N日平均，%；源不含换手字段时按 成交量/流通股本 计算）"""
        df = self._kline(stock_name)
        if df is None or df.empty:
            return None
        if df["turnover"].notna().any():
            turnovers = df["turnover"].dropna().tail(days)
        else:
            shares = self._float_shares(stock_name)
            if not shares:
                return None
            turnovers = df["volume"] / shares * 100
        if len(turnovers) > 0:
            return turnovers.mean()
        return None

    def _float_shares(self, stock_name: str) -> Optional[float]:
        """流通股本（股）= 流通市值 / 收盘价，来自估值快照的真实字段"""
        val = self._snapshot(stock_name)["val"]
        circ = self._num(val.get("NOTLIMITED_MARKETCAP_A"))
        price = self._num(val.get("CLOSE_PRICE"))
        if circ and price and price > 0:
            return circ / price
        return None

    def _amount_series(self, stock_name: str) -> pd.Series:
        """
        日成交额序列（元）。

        东财源含真实成交额时直接使用；腾讯/新浪源不含该字段时，
        按 成交量×典型价((最高+最低+收盘)/3) 推算，属常规近似而非虚构数据。
        """
        df = self._kline(stock_name)
        if df is None or df.empty:
            return pd.Series(dtype=float)
        if df["amount"].notna().any():
            return df["amount"]
        typical = (df["high"] + df["low"] + df["close"]) / 3
        return df["volume"] * typical

    def calc_amount_rank_percentile(self, stock_name: str, days: int = 20,
                                     all_stocks: Optional[List[str]] = None) -> Optional[float]:
        """25. 成交额排名分位（简化版：个股近N日平均成交额，单位亿元）"""
        amounts = self._amount_series(stock_name).dropna().tail(days)
        if len(amounts) > 0:
            return amounts.mean() / 1e8
        return None

    def calc_amihud(self, stock_name: str, days: int = 20) -> Optional[float]:
        """26. Amihud非流动性指标 = mean(|return| / 成交额)（越低越好，放大1e8倍）"""
        df = self._kline(stock_name)
        if df is None or df.empty:
            return None
        returns = df["close"].pct_change().abs()
        pair = pd.DataFrame({"r": returns, "a": self._amount_series(stock_name)}).dropna()
        pair = pair[pair["a"] > 0].tail(days)
        if len(pair) >= days:
            return (pair["r"] / pair["a"]).mean() * 1e8
        return None


# ============================================================================
# 因子标准化与合成模块
# ============================================================================

class FactorStandardizer:
    """因子标准化处理器"""
    
    @staticmethod
    def winsorize(series: pd.Series, lower_pct: float = 0.01, 
                  upper_pct: float = 0.99) -> pd.Series:
        """Min-Mad去极值（缩尾处理）"""
        if series.dropna().empty:
            return series
        
        q_low = series.quantile(lower_pct)
        q_high = series.quantile(upper_pct)
        return series.clip(lower=q_low, upper=q_high)
    
    @staticmethod
    def zscore(series: pd.Series) -> pd.Series:
        """Z-Score标准化"""
        mean = series.mean()
        std = series.std()
        if std == 0 or np.isnan(std):
            return pd.Series(0.0, index=series.index)
        return (series - mean) / std
    
    @staticmethod
    def rank_normalize(series: pd.Series) -> pd.Series:
        """排名标准化（0-1）"""
        ranked = series.rank(pct=True)
        return ranked
    
    @classmethod
    def standardize(cls, series: pd.Series, method: str = "zscore", 
                    winsorize_first: bool = True) -> pd.Series:
        """
        因子标准化主方法
        
        Args:
            series: 原始因子值序列
            method: 'zscore' | 'rank' | 'minmax'
            winsorize_first: 是否先做缩尾处理
        """
        s = series.copy()
        
        if winsorize_first:
            s = cls.winsorize(s)
        
        if method == "zscore":
            return cls.zscore(s)
        elif method == "rank":
            return cls.rank_normalize(s)
        elif method == "minmax":
            min_val = s.min()
            max_val = s.max()
            if max_val - min_val == 0:
                return pd.Series(0.5, index=s.index)
            return (s - min_val) / (max_val - min_val)
        else:
            raise ValueError(f"不支持的标准化方法: {method}")


# ============================================================================
# 多因子合成模块
# ============================================================================

class FactorCombiner:
    """多因子加权合成器"""
    
    # 因子信号方向定义（True=越高越好，False=越低越好）
    SIGNAL_DIRECTIONS = {
        # 价值因子 - 越低越好（取反后越高越好）
        "PE_TTM": False,
        "PB": False,
        "PS_TTM": False,
        "PCF": False,
        "股息率": True,
        
        # 成长因子 - 越高越好
        "营收同比增长率": True,
        "净利润同比增长率": True,
        "ROE同比变化": True,
        "EPS增长率": True,
        "扣非净利润增速": True,
        
        # 质量因子
        "ROE": True,
        "ROA": True,
        "毛利率": True,
        "净利率": True,
        "资产负债率": False,  # 越低越好
        "经营现金流/净利润比率": True,
        
        # 动量因子 - 越高越好
        "20日动量": True,
        "60日动量": True,
        "相对强度RS": True,
        "突破信号": True,
        
        # 波动因子 - 越低越好（低波策略）
        "20日历史波动率": False,
        "Beta系数": False,
        "最大回撤": True,  # 负值，越接近0越好
        
        # 流动性因子
        "换手率": True,   # 适中为佳，这里取高
        "成交额排名分位": True,
        "Amihud非流动性指标": False,  # 越低越好（流动性越高）
    }
    
    # 默认等权权重
    DEFAULT_WEIGHTS = {k: 1.0 for k in SIGNAL_DIRECTIONS.keys()}
    
    @classmethod
    def align_direction(cls, factor_df: pd.DataFrame) -> pd.DataFrame:
        """统一因子信号方向（全部转为越高越好）"""
        aligned = factor_df.copy()
        for col in aligned.columns:
            if col in cls.SIGNAL_DIRECTIONS and not cls.SIGNAL_DIRECTIONS[col]:
                aligned[col] = -aligned[col]
        return aligned
    
    @classmethod
    def equal_weight(cls, factor_df: pd.DataFrame) -> pd.Series:
        """等权合成：对每只股票，仅对可用因子求均值（skipna=True）"""
        aligned = cls.align_direction(factor_df)
        # pandas mean默认skipna=True，缺失因子不参与计算
        return aligned.mean(axis=1)
    
    @classmethod
    def custom_weight(cls, factor_df: pd.DataFrame, 
                       weights: Dict[str, float]) -> pd.Series:
        """自定义权重合成：缺失因子不参与计算，可用因子等比例放大权重"""
        aligned = cls.align_direction(factor_df)
        
        available_cols = [c for c in weights.keys() if c in aligned.columns]
        if not available_cols:
            return pd.Series(dtype=float, index=factor_df.index)
        
        total_weight = sum(weights[c] for c in available_cols)
        norm_weights = {c: weights[c] / total_weight for c in available_cols}
        
        # 计算每只股票加权得分，缺失值视为0贡献
        score = pd.Series(0.0, index=factor_df.index)
        for col in available_cols:
            col_filled = aligned[col].fillna(0)
            score += col_filled * norm_weights[col]
        
        return score
    
    @classmethod
    def ic_weight(cls, factor_df: pd.DataFrame, 
                  forward_returns: Optional[pd.Series] = None) -> pd.Series:
        """IC加权合成（需要未来收益率数据计算IC）"""
        aligned = cls.align_direction(factor_df)
        
        if forward_returns is not None and len(forward_returns) == len(aligned):
            # 计算每个因子的IC（与未来收益的相关系数）
            ic_values = {}
            for col in aligned.columns:
                x = aligned[col].dropna().values
                y = forward_returns.loc[aligned[col].dropna().index].values
                
                if HAS_SCIPY:
                    corr, _ = stats.pearsonr(x, y)
                else:
                    # numpy fallback for pearson correlation
                    mean_x, mean_y = x.mean(), y.mean()
                    std_x, std_y = x.std(ddof=1), y.std(ddof=1)
                    if std_x == 0 or std_y == 0:
                        corr = 0.0
                    else:
                        corr = np.corrcoef(x, y)[0][1]
                
                ic_values[col] = abs(corr)
            
            # IC加权（IC越大权重越高）
            total_ic = sum(ic_values.values())
            if total_ic > 0:
                weights = {k: v / total_ic for k, v in ic_values.items()}
            else:
                weights = cls.DEFAULT_WEIGHTS
            
            return cls.custom_weight(factor_df, weights)
        else:
            # 无未来收益数据时回退到等权
            return cls.equal_weight(factor_df)


# ============================================================================
# 选股主引擎
# ============================================================================

class MultiFactorSelector:
    """多因子选股主引擎"""
    
    def __init__(self):
        self.calculator = FactorCalculator()
        
        # 因子计算函数映射
        self.factor_functions = {
            # 价值因子
            "PE_TTM": self.calculator.calc_pe_ttm,
            "PB": self.calculator.calc_pb,
            "PS_TTM": self.calculator.calc_ps_ttm,
            "PCF": self.calculator.calc_pcf,
            "股息率": self.calculator.calc_dividend_yield,
            
            # 成长因子
            "营收同比增长率": self.calculator.calc_revenue_growth,
            "净利润同比增长率": self.calculator.calc_net_profit_growth,
            "ROE同比变化": self.calculator.calc_roe_change,
            "EPS增长率": self.calculator.calc_eps_growth,
            "扣非净利润增速": self.calculator.calc_deducted_profit_growth,
            
            # 质量因子
            "ROE": self.calculator.calc_roe,
            "ROA": self.calculator.calc_roa,
            "毛利率": self.calculator.calc_gross_margin,
            "净利率": self.calculator.calc_net_margin,
            "资产负债率": self.calculator.calc_debt_ratio,
            "经营现金流/净利润比率": self.calculator.calc_ocf_to_net_profit,
            
            # 动量因子
            "20日动量": self.calculator.calc_momentum_20d,
            "60日动量": self.calculator.calc_momentum_60d,
            "相对强度RS": self.calculator.calc_relative_strength,
            "突破信号": self.calculator.calc_breakout_signal,
            
            # 波动因子
            "20日历史波动率": self.calculator.calc_historical_volatility,
            "Beta系数": self.calculator.calc_beta,
            "最大回撤": self.calculator.calc_max_drawdown,
            
            # 流动性因子
            "换手率": self.calculator.calc_turnover_rate,
            "成交额排名分位": self.calculator.calc_amount_rank_percentile,
            "Amihud非流动性指标": self.calculator.calc_amihud,
        }
        
        # 因子分类
        self.factor_categories = {
            "价值因子": ["PE_TTM", "PB", "PS_TTM", "PCF", "股息率"],
            "成长因子": ["营收同比增长率", "净利润同比增长率", "ROE同比变化", 
                        "EPS增长率", "扣非净利润增速"],
            "质量因子": ["ROE", "ROA", "毛利率", "净利率", "资产负债率", 
                        "经营现金流/净利润比率"],
            "动量因子": ["20日动量", "60日动量", "相对强度RS", "突破信号"],
            "波动因子": ["20日历史波动率", "Beta系数", "最大回撤"],
            "流动性因子": ["换手率", "成交额排名分位", "Amihud非流动性指标"],
        }
    
    def compute_single_factor(self, stock_name: str, factor_name: str) -> Optional[float]:
        """计算单个股票的单个因子"""
        if factor_name not in self.factor_functions:
            raise ValueError(f"未知因子: {factor_name}")
        return self.factor_functions[factor_name](stock_name)
    
    def compute_factors_for_stock(self, stock_name: str, 
                                   factors: Optional[List[str]] = None) -> Dict[str, float]:
        """计算单个股票的多个因子"""
        if factors is None:
            factors = list(self.factor_functions.keys())
        
        results = {}
        for factor in factors:
            try:
                val = self.compute_single_factor(stock_name, factor)
                results[factor] = val
            except Exception as e:
                print(f"  ⚠️ {stock_name} [{factor}] 计算异常: {e}")
                results[factor] = None
        
        return results
    
    def compute_factors_for_stocks(self, stock_names: List[str],
                                    factors: Optional[List[str]] = None) -> pd.DataFrame:
        """批量计算多只股票的因子矩阵"""
        if factors is None:
            factors = list(self.factor_functions.keys())
        
        all_data = {}
        for i, name in enumerate(stock_names):
            print(f"\n[{i+1}/{len(stock_names)}] 正在计算 {name} 的因子...")
            stock_factors = self.compute_factors_for_stock(name, factors)
            all_data[name] = stock_factors
        
        df = pd.DataFrame(all_data).T
        return df
    
    def filter_stocks(self, factor_df: pd.DataFrame, 
                      filters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        筛选条件过滤
        
        Args:
            factor_df: 因子数据框（index=股票名）
            filters: 筛选条件字典，例如：
                {
                    "exclude_st": True,           # 排除ST股
                    "min_market_cap": 50,         # 最小市值(亿)
                    "max_market_cap": 2000,       # 最大市值(亿)
                    "industries": ["科技", "医药"], # 行业白名单
                }
        """
        if filters is None:
            return factor_df
        
        df = factor_df.copy()
        
        # 排除ST股（通过股票名称判断）
        if filters.get("exclude_st", False):
            st_mask = ~df.index.str.contains(r"ST|退", case=False, na=False)
            removed = df[~st_mask].index.tolist()
            if removed:
                print(f"  📌 排除ST股: {removed}")
            df = df[st_mask]
        
        # 市值过滤（需要额外获取市值数据）
        min_cap = filters.get("min_market_cap")
        max_cap = filters.get("max_market_cap")
        if min_cap is not None or max_cap is not None:
            market_caps = {}
            for name in df.index:
                cap = self.calculator._fetch_market_cap(name)
                market_caps[name] = cap
            
            cap_series = pd.Series(market_caps)
            mask = pd.Series(True, index=df.index)
            
            if min_cap is not None:
                mask &= (cap_series >= min_cap)
            if max_cap is not None:
                mask &= (cap_series <= max_cap)
            
            removed = df[~mask].index.tolist()
            if removed:
                print(f"  📌 市值过滤排除: {removed}")
            df = df[mask]
        
        return df
    
    def run_selection(self, stock_names: List[str],
                      factors: Optional[List[str]] = None,
                      filters: Optional[Dict[str, Any]] = None,
                      standardize_method: str = "zscore",
                      weight_method: str = "equal_weight",
                      custom_weights: Optional[Dict[str, float]] = None,
                      top_n: int = 20,
                      output_dir: str = "./output") -> Dict[str, Any]:
        """
        完整选股流程
        
        Args:
            stock_names: 股票名称列表
            factors: 要计算的因子列表（None=全部）
            filters: 筛选条件
            standardize_method: 'zscore' | 'rank' | 'minmax'
            weight_method: 'equal_weight' | 'ic_weight' | 'custom'
            custom_weights: 自定义权重字典
            top_n: 输出前N只股票
            output_dir: 输出目录
            
        Returns:
            选股结果字典
        """
        print("=" * 70)
        print("A股多因子选股框架 - Multi-Factor Stock Selection")
        print("=" * 70)
        
        # Step 1: 计算因子
        print("\n【Step 1】计算因子...")
        factor_df = self.compute_factors_for_stocks(stock_names, factors)
        print(f"\n✅ 因子矩阵: {factor_df.shape[0]} 只股票 × {factor_df.shape[1]} 个因子")
        
        # Step 2: 筛选过滤
        if filters:
            print("\n【Step 2】应用筛选条件...")
            factor_df = self.filter_stocks(factor_df, filters)
            print(f"✅ 筛选后剩余 {len(factor_df)} 只股票")
        
        # Step 3: 因子标准化
        print("\n【Step 3】因子标准化 (method={})...".format(standardize_method))
        standardized = pd.DataFrame(index=factor_df.index)
        for col in factor_df.columns:
            series = factor_df[col].dropna()
            if len(series) > 1:
                standardized[col] = FactorStandardizer.standardize(
                    factor_df[col], method=standardize_method, winsorize_first=True
                )
            else:
                standardized[col] = pd.Series(np.nan, index=factor_df.index)
        
        # Step 4: 多因子合成
        print("\n【Step 4】多因子合成 (method={})...".format(weight_method))
        if weight_method == "equal_weight":
            composite_score = FactorCombiner.equal_weight(standardized)
        elif weight_method == "ic_weight":
            composite_score = FactorCombiner.ic_weight(standardized)
        elif weight_method == "custom":
            if custom_weights is None:
                raise ValueError("自定义权重模式需要提供 weights 参数")
            composite_score = FactorCombiner.custom_weight(standardized, custom_weights)
        else:
            raise ValueError(f"不支持的加权方法: {weight_method}")
        
        # Step 5: 排名
        print("\n【Step 5】生成选股结果...")
        results_df = pd.DataFrame({
            "股票": factor_df.index,
            "综合得分": composite_score.values,
        })
        
        # 添加各因子分项得分
        for col in standardized.columns:
            results_df[col] = standardized[col].values
        
        # 排名（按综合得分降序）
        results_df = results_df.sort_values("综合得分", ascending=False).reset_index(drop=True)
        results_df["排名"] = range(1, len(results_df) + 1)
        
        # 调整列顺序：排名、股票、综合得分在前，因子分项在后
        base_cols = ["排名", "股票", "综合得分"]
        factor_cols = [c for c in standardized.columns]
        results_df = results_df[base_cols + factor_cols]
        
        # Step 6: 输出结果
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # CSV输出
        csv_file = output_path / f"选股结果_{timestamp}.csv"
        results_df.to_csv(csv_file, index=False, encoding="utf-8-sig")
        print(f"\n📊 CSV文件: {csv_file}")
        
        # JSON输出（包含元数据）
        json_output = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "stock_count": len(stock_names),
                "filtered_count": len(factor_df),
                "factor_count": len(standardized.columns),
                "factors_used": list(standardized.columns),
                "standardize_method": standardize_method,
                "weight_method": weight_method,
                "custom_weights": custom_weights,
                "filters": filters,
                "top_n": top_n,
            },
            "factor_categories": self.factor_categories,
            "signal_directions": FactorCombiner.SIGNAL_DIRECTIONS,
            "results": results_df.head(top_n).to_dict(orient="records"),
            "all_results": results_df.to_dict(orient="records"),
        }
        
        json_file = output_path / f"选股结果_{timestamp}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(json_output, f, ensure_ascii=False, indent=2, default=str)
        print(f"📄 JSON文件: {json_file}")
        
        # 终端打印Top N结果
        print("\n" + "=" * 70)
        print(f"🏆 Top {min(top_n, len(results_df))} 选股结果:")
        print("=" * 70)
        
        display_cols = ["排名", "股票", "综合得分"]
        top_results = results_df.head(top_n)[display_cols + factor_cols[:5]]
        print(top_results.to_string(index=False))
        
        if len(results_df) > top_n:
            print(f"\n... 共 {len(results_df)} 只股票，完整结果见输出文件")
        
        return json_output


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="A股多因子选股框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 1. 单因子筛选（PE_TTM）
  python multi_factor.py --stocks "贵州茅台,宁德时代,比亚迪" --factors PE_TTM

  # 2. 多因子组合选股（等权合成）
  python multi_factor.py --stocks "贵州茅台,宁德时代,比亚迪,东方财富,招商银行" \\
      --weight equal_weight --top_n 5

  # 3. 自定义权重选股
  python multi_factor.py --stocks "贵州茅台,宁德时代,比亚迪" \\
      --factors PE_TTM,PB,ROE,营收同比增长率 \\
      --weight custom --weights '{"PE_TTM":0.3,"PB":0.2,"ROE":0.3,"营收同比增长率":0.2}'

  # 4. 完整选股（全部因子 + ST排除）
  python multi_factor.py --stocks "贵州茅台,宁德时代,比亚迪,东方财富,招商银行,万科A" \\
      --exclude_st --min_cap 50 --top_n 10

  # 5. 指定输出目录
  python multi_factor.py --stocks "贵州茅台,宁德时代" --output_dir ./my_selections
        """
    )
    
    parser.add_argument("--stocks", type=str, required=True,
                        help="股票名称列表，逗号分隔，如 '贵州茅台,宁德时代,比亚迪'")
    parser.add_argument("--factors", type=str, default=None,
                        help="要计算的因子（逗号分隔），不指定则计算全部26个因子。"
                             "可选: PE_TTM,PB,PS_TTM,PCF,股息率,"
                             "营收同比增长率,净利润同比增长率,ROE同比变化,EPS增长率,扣非净利润增速,"
                             "ROE,ROA,毛利率,净利率,资产负债率,经营现金流/净利润比率,"
                             "20日动量,60日动量,相对强度RS,突破信号,"
                             "20日历史波动率,Beta系数,最大回撤,"
                             "换手率,成交额排名分位,Amihud非流动性指标")
    parser.add_argument("--weight", type=str, default="equal_weight",
                        choices=["equal_weight", "ic_weight", "custom"],
                        help="因子合成方法: equal_weight(等权) | ic_weight(IC加权) | custom(自定义)")
    parser.add_argument("--weights", type=str, default=None,
                        help='自定义权重JSON，如 \'{"PE_TTM":0.3,"PB":0.2}\'' )
    parser.add_argument("--standardize", type=str, default="zscore",
                        choices=["zscore", "rank", "minmax"],
                        help="因子标准化方法")
    parser.add_argument("--exclude_st", action="store_true",
                        help="排除ST股票")
    parser.add_argument("--min_cap", type=float, default=None,
                        help="最小市值（亿元）")
    parser.add_argument("--max_cap", type=float, default=None,
                        help="最大市值（亿元）")
    parser.add_argument("--top_n", type=int, default=20,
                        help="输出前N只股票")
    parser.add_argument("--output_dir", type=str, default="./output",
                        help="输出目录")
    
    args = parser.parse_args()
    
    # 解析参数
    stock_names = [s.strip() for s in args.stocks.split(",")]
    factors = [f.strip() for f in args.factors.split(",")] if args.factors else None
    
    custom_weights = None
    if args.weights:
        try:
            custom_weights = json.loads(args.weights)
        except json.JSONDecodeError as e:
            print(f"❌ 权重JSON解析失败: {e}")
            sys.exit(1)
    
    filters = {}
    if args.exclude_st:
        filters["exclude_st"] = True
    if args.min_cap is not None:
        filters["min_market_cap"] = args.min_cap
    if args.max_cap is not None:
        filters["max_market_cap"] = args.max_cap
    
    # 运行选股
    selector = MultiFactorSelector()
    
    try:
        result = selector.run_selection(
            stock_names=stock_names,
            factors=factors,
            filters=filters if filters else None,
            standardize_method=args.standardize,
            weight_method=args.weight,
            custom_weights=custom_weights,
            top_n=args.top_n,
            output_dir=args.output_dir,
        )
        
        print("\n✅ 选股完成！")
        
    except Exception as e:
        print(f"\n❌ 选股失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
