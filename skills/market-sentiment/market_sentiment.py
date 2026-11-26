#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股市场情绪量化指标计算工具
============================
基于东方财富公开行情接口（涨停板行情中心 + 指数K线，免费、无需 API Key）获取全市场行情数据，自动化计算17项市场情绪指标。

用法:
    python market_sentiment.py [选项]
    
    基本使用:
        python market_sentiment.py                          # 今日情绪报告
        python market_sentiment.py --date 2026-06-23        # 指定日期回查
        python market_sentiment.py --history 10             # 近10日历史情绪数据
        python market_sentiment.py --report                 # 详细HTML风格报告
        python market_sentiment.py --trend                  # 情绪趋势分析
    
    选项:
        --date DATE         指定查询日期 (YYYY-MM-DD)
        --history DAYS      获取近N日历史情绪数据并保存
        --report            输出详细格式化的情绪报告
        --trend             附加情绪趋势判断
        --config FILE       自定义权重配置文件路径
        --output DIR        结果输出目录 (默认: ./sentiment_data/)
        --verbose           显示详细计算过程

依赖:
    pip install pandas numpy requests openpyxl
"""

import os
import sys
import json
import re
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
import numpy as np
import requests

# ---------------------------------------------------------------------------
# 免费公开行情接口（东方财富涨停板行情中心 + 指数K线，均无需凭证）
# ---------------------------------------------------------------------------
_EM_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
_EM_POOL_URL = "https://push2ex.eastmoney.com"
_EM_UT = "7eea3edcaed734bea9cbfc24409ed989"
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EM_ZDFB_URL = "https://push2ex.eastmoney.com/getTopicZDFenBu"
_HEADERS = {"User-Agent": "Mozilla/5.0"}

# 腾讯K线（无成交额字段，仅作为东财限流时的交易日历兜底），多入口轮换
_TX_KLINE_PATH = "/appstock/app/fqkline/get"
_TX_HOSTS = ["https://web.ifzq.gtimg.cn", "https://ifzq.gtimg.cn",
             "https://proxy.finance.qq.com/ifzqgtimg"]
_TX_INDEX = "sh000001"

# 沪市综指 + 深市综指（深证综指覆盖深市全部个股，成交额之和即两市成交额）
_MARKET_INDEXES = [("1.000001", "上证指数"), ("0.399102", "深证综指")]

# 东财涨停板行情中心的四个池子（每个池子只认自己的排序字段，sort 传错会返回空列表）
_POOL_ENDPOINTS = (
    ("zt", "getTopicZTPool", "fbt:asc"),
    ("zb", "getTopicZBPool", "fbt:asc"),
    ("dt", "getTopicDTPool", "fund:asc"),
    ("yzt", "getYesterdayZTPool", "zs:desc"),
)


def _get(url: str, params: Dict[str, Any] = None, headers: Dict[str, str] = None, retries: int = 3):
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


def _tx_kline(symbol: str, days: int) -> List[list]:
    """
    腾讯指数日K行（升序）：日期,开盘,收盘,最高,最低,成交量。

    三个入口等价、限流互相独立，逐个尝试。腾讯不提供成交额/换手率字段，
    因此仅在东财被限流时用于交易日历与指数涨跌幅兜底。
    """
    param = f"{symbol},day,,,{max(days, 1)},qfq"
    for host in _TX_HOSTS:
        try:
            resp = _get(host + _TX_KLINE_PATH, {"param": param},
                        {"Referer": "https://gu.qq.com/"}, retries=2)
            node = (resp.json().get("data") or {}).get(symbol) or {}
        except Exception:
            continue
        # 指数没有除权概念，只有 day
        items = node.get("day") or node.get("qfqday") or []
        if items:
            return [list(it[:6]) for it in items][-days:]
    return []


def _tx_dates(symbol: str, days: int) -> List[str]:
    """腾讯指数日K的日期序列（升序 YYYY-MM-DD）"""
    return [str(r[0]) for r in _tx_kline(symbol, days)]


def _em_pool(endpoint: str, day: str, sort: str) -> List[Dict[str, Any]]:
    """
    东财涨停板行情中心池子（day 形如 20261125），取数失败时抛出异常。

    endpoint: getTopicZTPool 涨停 / getTopicZBPool 炸板 /
              getTopicDTPool 跌停 / getYesterdayZTPool 昨日涨停今表现
    """
    resp = _get(f"{_EM_POOL_URL}/{endpoint}", {
        "ut": _EM_UT, "dpt": "wz.ztzt", "Pageindex": 0,
        "pagesize": 1000, "date": day, "sort": sort,
    }, _EM_HEADERS, retries=3)
    return (resp.json().get("data") or {}).get("pool") or []


# ---------------------------------------------------------------------------
# 默认权重配置
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS = {
    # --- 涨跌统计类 (总分30) ---
    "limit_up_down_ratio":   8.0,   # 涨停/跌停比
    "advance_decline_ratio":  7.0,   # 上涨/下跌家数比
    "limit_up_count":        5.0,   # 涨停家数绝对值
    "speed_indicator":       3.0,   # 涨速指标
    "market_breadth":        7.0,   # 市场广度（上涨占比）

    # --- 连板高度类 (总分25) ---
    "max_consecutive_limit": 8.0,   # 最高连板天数
    "consecutive_distribution": 5.0, # 连板梯队分布
    "yesterday_premium":     6.0,   # 昨日涨停今日溢价率
    "break_board_rate":      6.0,   # 炸板率

    # --- 量能指标类 (总分25) ---
    "turnover_percentile":   7.0,   # 换手率分位数
    "volume_change_rate":    6.0,   # 成交额变化率
    "volume_ratio_stats":    6.0,   # 量比分布统计
    "north_flow":            6.0,   # 北向资金净流入

    # --- 恐慌贪婪指标 (总分20) ---
    "fear_greed_index":      10.0,  # 恐惧贪婪指数
    "vix_analog":            10.0,  # VIX类比指标
}

# ---------------------------------------------------------------------------
# 情绪状态阈值配置
# ---------------------------------------------------------------------------
SENTIMENT_THRESHOLDS = {
    "freezing":   {"min": 0,   "max": 25,  "label": "冰点",   "emoji": "🥶"},
    "weak":       {"min": 25,  "max": 40,  "label": "低迷",   "emoji": "😔"},
    "moderate":   {"min": 40,  "max": 60,  "label": "温和",   "emoji": "😐"},
    "excited":    {"min": 60,  "max": 80,  "label": "亢奋",   "emoji": "🔥"},
    "overheated": {"min": 80,  "max": 100, "label": "过热",   "emoji": "💥"},
}


# ===================================================================
# 数据获取层
# ===================================================================

class MarketDataFetcher:
    """通过公开接口获取市场原始数据（东方财富涨停板行情中心 + 指数K线）"""

    def __init__(self, api_key: Optional[str] = None):
        # 公开接口无需任何凭证；保留形参仅为兼容既有调用
        self._pool_cache: Dict[str, Optional[Dict[str, List[Dict[str, Any]]]]] = {}
        self._kline_cache: Dict[str, pd.DataFrame] = {}

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _index_kline(self, secid: str, days: int = 30) -> pd.DataFrame:
        """指数日K（含成交额与换手率），返回升序 [date, close, pct_change, amount, turnover]"""
        cache_key = f"{secid}"
        if cache_key not in self._kline_cache:
            try:
                resp = _get(_EM_KLINE_URL, {
                    "secid": secid,
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    "klt": "101", "fqt": "1", "end": "20500000",
                    "lmt": str(max(days, 1)), "ut": _EM_UT,
                }, retries=4)
                klines = (resp.json().get("data") or {}).get("klines") or []
            except Exception as e:
                print(f"  ⚠️ 获取指数K线失败({secid}): {e}")
                klines = []
            # 字段顺序：日期,开,收,高,低,量,额,振幅,涨跌幅,涨跌额,换手率
            rows = [line.split(",") for line in klines]
            df = pd.DataFrame(rows, columns=[
                "date", "open", "close", "high", "low", "volume",
                "amount", "amplitude", "pct_change", "change", "turnover",
            ])
            for col in ["close", "amount", "pct_change", "turnover"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            self._kline_cache[cache_key] = df
        return self._kline_cache[cache_key]

    def trading_days(self, days: int = 20) -> List[str]:
        """近N个交易日（升序 YYYYMMDD），东财指数K线被限流时回退腾讯K线"""
        df = self._index_kline(_MARKET_INDEXES[0][0], days)
        dates = df["date"].tail(days).tolist() if not df.empty else _tx_dates(_TX_INDEX, days)
        return [str(d).replace("-", "") for d in dates]

    def _pools(self, day: str) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        """
        某交易日的涨停/炸板/跌停/昨日涨停四个池子（按日缓存），day 形如 20261125。

        东财偶发断连会让某个池子取数失败，此时整日重试一次；仍失败返回 None，
        该日不计入统计（避免把"取数失败"误当成"当日无涨停"）。
        """
        if day not in self._pool_cache:
            self._pool_cache[day] = self._load_pools(day)
        return self._pool_cache[day]

    @staticmethod
    def _load_pools(day: str) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        failed: List[str] = []
        pools: Dict[str, List[Dict[str, Any]]] = {}
        for attempt in (1, 2):
            pools, failed = {}, []
            for name, endpoint, sort in _POOL_ENDPOINTS:
                try:
                    pools[name] = _em_pool(endpoint, day, sort)
                except Exception:
                    pools[name] = []
                    failed.append(name)
            if not failed:
                return pools
            if attempt == 1:
                time.sleep(1.0)
        print(f"  ⚠️ {day} 池数据取数失败: {'/'.join(failed)}")
        return None

    @staticmethod
    def _is_limit_up(stock: Dict[str, Any]) -> bool:
        """按板块涨跌幅限制判断该股的涨停阈值"""
        code = str(stock.get("c") or "")
        limit = 19.8 if code.startswith(("30", "301", "688", "689")) else 9.8
        try:
            return float(stock.get("zdp") or 0) >= limit
        except (TypeError, ValueError):
            return False

    def _day_record(self, day: str) -> Optional[Dict[str, Any]]:
        """汇总某交易日的涨跌停 / 连板 / 炸板 / 昨日涨停表现"""
        pools = self._pools(day)
        if not pools:
            return None
        zt, zb, dt, yzt = pools["zt"], pools["zb"], pools["dt"], pools["yzt"]
        if not (zt or zb or dt or yzt):
            return None
        boards = [int(s.get("lbc") or 1) for s in zt]
        premium = [float(s.get("zdp") or 0) for s in yzt]
        return {
            "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
            "limit_up": len(zt),
            "limit_down": len(dt),
            "broken": len(zb),
            "max_board": max(boards) if boards else 0,
            "board_2": sum(1 for b in boards if b == 2),
            "board_3": sum(1 for b in boards if b == 3),
            "board_4plus": sum(1 for b in boards if b >= 4),
            "yzt_count": len(yzt),
            "yzt_keep": sum(1 for s in yzt if self._is_limit_up(s)),
            "yzt_premium": round(sum(premium) / len(premium), 2) if premium else 0.0,
        }

    # ------------------------------------------------------------------
    # 对外数据接口（DataFrame 均按日期降序，iloc[0] 为最近交易日）
    # ------------------------------------------------------------------
    def fetch_limit_up_down_history(self, days: int = 20) -> pd.DataFrame:
        """
        近N个交易日涨跌停、炸板与连板梯队数据（逐日取东财涨停板行情中心池子）。

        该接口只提供约两周内的池子快照，更早的日期无数据，返回行数会少于 days。

        列: date, limit_up 涨停家数, limit_down 跌停家数, broken 炸板家数,
            max_board 最高连板, board_2/board_3/board_4plus 连板梯队,
            yzt_count 昨日涨停数, yzt_keep 其中今日仍涨停数, yzt_premium 昨日涨停今日平均涨幅%
        """
        rows = []
        for day in self.trading_days(days):
            try:
                rec = self._day_record(day)
            except Exception as e:
                print(f"  ⚠️ 获取 {day} 涨跌停数据失败: {e}")
                rec = None
            if rec:
                rows.append(rec)
            time.sleep(0.2)
        if not rows:
            print("  ⚠️ 未获取到涨跌停数据（接口不可用或非交易时段）")
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("date", ascending=False).reset_index(drop=True)

    def fetch_advance_decline_history(self, days: int = 20) -> pd.DataFrame:
        """
        全市场上涨/下跌家数（东财涨跌幅分布）。

        注意：该接口只提供最新交易日快照，无历史序列，
        因此返回的行数为 1；涉及涨跌家数的历史回溯指标会因缺数据而跳过。
        """
        try:
            resp = _get(_EM_ZDFB_URL, {"ut": _EM_UT, "dpt": "wz.ztzt"}, _EM_HEADERS, retries=2)
            data = resp.json().get("data") or {}
            fenbu = data.get("fenbu") or []
        except Exception as e:
            print(f"  ⚠️ 获取涨跌家数数据失败: {e}")
            return pd.DataFrame()
        advance = decline = flat = 0
        for item in fenbu:
            for bucket, count in item.items():
                try:
                    level, count = int(bucket), int(count)
                except (TypeError, ValueError):
                    continue
                if level > 0:
                    advance += count
                elif level < 0:
                    decline += count
                else:
                    flat += count
        if not (advance or decline):
            return pd.DataFrame()
        qdate = str(data.get("qdate") or "")
        date = f"{qdate[:4]}-{qdate[4:6]}-{qdate[6:]}" if len(qdate) == 8 else ""
        return pd.DataFrame([{"date": date, "advance": advance,
                              "decline": decline, "flat": flat}])

    def fetch_volume_turnover_history(self, days: int = 20) -> pd.DataFrame:
        """
        近N个交易日两市成交额与换手率（沪市综指 + 深市综指）。

        列: date, volume 两市成交额（元）, turnover_rate 换手率%（按两市成交额加权）
        """
        frames = {}
        for secid, _name in _MARKET_INDEXES:
            df = self._index_kline(secid, days)
            if not df.empty:
                frames[secid] = df.set_index("date")
        if not frames:
            print("  ⚠️ 获取量价数据失败")
            return pd.DataFrame()
        if len(frames) < len(_MARKET_INDEXES):
            print(f"  ⚠️ 仅取到 {len(frames)}/{len(_MARKET_INDEXES)} 个指数，成交额与换手率不完整")
        dates = sorted(set().union(*[set(f.index) for f in frames.values()]), reverse=True)
        rows = []
        for d in dates:
            amount = 0.0
            weighted = 0.0
            for f in frames.values():
                if d not in f.index:
                    continue
                a = float(f.at[d, "amount"] or 0)
                t = float(f.at[d, "turnover"] or 0)
                amount += a
                weighted += a * t
            if amount <= 0:
                continue
            rows.append({"date": d, "volume": amount,
                         "turnover_rate": round(weighted / amount, 4)})
        return pd.DataFrame(rows)

    def fetch_index_history(self, days: int = 30) -> pd.DataFrame:
        """上证指数近N日涨跌幅（东财被限流时用腾讯K线的收盘价推算）"""
        df = self._index_kline(_MARKET_INDEXES[0][0], days)
        if df.empty:
            rows = _tx_kline(_TX_INDEX, days)
            if not rows:
                return pd.DataFrame()
            print("  ⚠️ 东财指数K线不可用，涨跌幅改用腾讯K线计算")
            df = pd.DataFrame({
                "date": [str(r[0]) for r in rows],
                "close": pd.to_numeric([r[2] for r in rows], errors="coerce"),
            })
            df["pct_change"] = (df["close"] / df["close"].shift(1) - 1) * 100
        out = df[["date", "pct_change"]].dropna().copy()
        return out.sort_values("date", ascending=False).reset_index(drop=True)

    def fetch_north_flow(self) -> Optional[float]:
        """
        北向资金净流入。

        自 2024-08 起北向资金净买入额已停止披露，无公开数据源，
        因此恒返回 None，恐惧贪婪指数会按剩余权重归一化。
        """
        return None


# ===================================================================
# 指标计算层
# ===================================================================

class SentimentIndicators:
    """市场情绪指标计算器"""

    def __init__(self, fetcher: MarketDataFetcher):
        self.fetcher = fetcher

    # ------------------------------------------------------------------
    # 涨跌统计类 (1-4)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_row(df: pd.DataFrame, date: Optional[str], idx: int = 0) -> Any:
        """安全获取DataFrame行，优先按日期匹配，否则取第idx行"""
        if df.empty or len(df) == 0:
            return None
        if date is not None and "date" in df.columns:
            # 尝试多种日期格式匹配
            for pattern in [date, date.replace("-", ""), date[:7]]:
                mask = df["date"].astype(str).str.contains(pattern, na=False)
                if mask.any():
                    return df[mask].iloc[0]
        return df.iloc[idx]

    @staticmethod
    def limit_up_down_count(df_ltd: pd.DataFrame, date: Optional[str] = None) -> Dict[str, int]:
        """指标1: 全市场涨停家数/跌停家数"""
        if df_ltd.empty:
            return {"limit_up": 0, "limit_down": 0}
        row = SentimentIndicators._get_row(df_ltd, date)
        if row is None:
            return {"limit_up": 0, "limit_down": 0}
        return {
            "limit_up": int(row.get("limit_up", 0)),
            "limit_down": int(row.get("limit_down", 0)),
        }

    @staticmethod
    def limit_up_down_ratio(df_ltd: pd.DataFrame, date: Optional[str] = None) -> float:
        """指标2: 涨停/跌停比 (LTD Ratio)"""
        counts = SentimentIndicators.limit_up_down_count(df_ltd, date)
        ld = max(counts["limit_down"], 1)
        return round(counts["limit_up"] / ld, 2)

    @staticmethod
    def advance_decline_stats(df_ad: pd.DataFrame, date: Optional[str] = None) -> Dict[str, int]:
        """
        指标3: 上涨家数/下跌家数/平盘家数

        数据源只提供最新交易日的快照，请求更早日期时返回 0（该日无数据）。
        """
        empty = {"advance": 0, "decline": 0, "unchanged": 0}
        if df_ad.empty:
            return empty
        row = SentimentIndicators._get_row(df_ad, date)
        if row is None:
            return empty
        row_date = str(row.get("date", ""))[:10]
        req_date = str(date)[:10] if date else ""
        if req_date and row_date and req_date < row_date:
            return empty
        return {
            "advance": int(row.get("advance", 0)),
            "decline": int(row.get("decline", 0)),
            "unchanged": int(row.get("flat", 0)),
        }

    @staticmethod
    def speed_indicator(advance: int, total: int = 5400) -> float:
        """指标4: 涨速指标（上涨占比，替代5分钟涨幅>3%的家数）"""
        if total <= 0:
            return 0.0
        return round((advance / total) * 100, 2)

    # ------------------------------------------------------------------
    # 连板高度类 (5-8)
    # ------------------------------------------------------------------

    @staticmethod
    def max_consecutive_limit(df_ltd: pd.DataFrame, date: Optional[str] = None) -> int:
        """指标5: 最高连板天数（涨停池连板数的最大值）"""
        row = SentimentIndicators._get_row(df_ltd, date)
        if row is None or "max_board" not in df_ltd.columns:
            return 0
        return int(row.get("max_board", 0) or 0)

    @staticmethod
    def consecutive_distribution(df_ltd: pd.DataFrame, date: Optional[str] = None) -> Dict[str, int]:
        """指标6: 连板梯队分布（2板 / 3板 / 4板及以上的家数）"""
        row = SentimentIndicators._get_row(df_ltd, date)
        if row is None:
            return {"2板": 0, "3板": 0, "4板+": 0}
        return {
            "2板": int(row.get("board_2", 0) or 0),
            "3板": int(row.get("board_3", 0) or 0),
            "4板+": int(row.get("board_4plus", 0) or 0),
        }

    @staticmethod
    def yesterday_premium(df_ltd: pd.DataFrame, date: Optional[str] = None) -> float:
        """指标7: 昨日涨停个股今日平均涨幅（溢价率%）"""
        row = SentimentIndicators._get_row(df_ltd, date)
        if row is None or "yzt_premium" not in df_ltd.columns:
            return 0.0
        return float(row.get("yzt_premium", 0.0) or 0.0)

    @staticmethod
    def break_board_rate(df_ltd: pd.DataFrame, date: Optional[str] = None) -> float:
        """指标8: 炸板率 = 炸板家数 /（涨停家数 + 炸板家数）"""
        row = SentimentIndicators._get_row(df_ltd, date)
        if row is None or "broken" not in df_ltd.columns:
            return 0.0
        limit_up = int(row.get("limit_up", 0) or 0)
        broken = int(row.get("broken", 0) or 0)
        if limit_up + broken <= 0:
            return 0.0
        return round(broken / (limit_up + broken) * 100, 2)

    # ------------------------------------------------------------------
    # 量能指标类 (9-12)
    # ------------------------------------------------------------------

    @staticmethod
    def _series(df: pd.DataFrame, col: str, date: Optional[str] = None) -> pd.Series:
        """
        取某列的数值序列，使 iloc[0] 为指定日期（默认最近交易日）。

        数据源统一按日期降序，因此 iloc[1:] 即该日期之前的历史；
        指定日期没有数据时（如非交易日），回退到该日期之前最近的交易日。
        """
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if date is None or "date" not in df.columns or df.empty:
            return series
        dates = df["date"].astype(str).str[:10].tolist()
        target = str(date)[:10]
        pos = next((i for i, d in enumerate(dates) if d <= target), None)
        if pos is None:
            return series
        return series[series.index.isin(df.index[pos:])]

    @staticmethod
    def turnover_percentile(df_vol: pd.DataFrame, lookback: int = 20,
                            date: Optional[str] = None) -> float:
        """指标9: 全市场换手率分位数（vs近N日）"""
        if df_vol.empty or "turnover_rate" not in df_vol.columns:
            return 50.0
        rates = SentimentIndicators._series(df_vol, "turnover_rate", date).reset_index(drop=True)
        if len(rates) < 2:
            return 50.0
        current = rates.iloc[0]
        history = rates.iloc[1:].tail(lookback - 1)
        if len(history) == 0:
            return 50.0
        percentile = (history < current).sum() / len(history) * 100
        return round(percentile, 2)

    @staticmethod
    def volume_change_rate(df_vol: pd.DataFrame, window: int = 5,
                           date: Optional[str] = None) -> float:
        """指标10: 成交额较前N日均值变化率"""
        if df_vol.empty or "volume" not in df_vol.columns:
            return 0.0
        volumes = SentimentIndicators._series(df_vol, "volume", date).reset_index(drop=True)
        if len(volumes) < window + 1:
            return 0.0
        current = volumes.iloc[0]
        avg_prev = volumes.iloc[1:window + 1].mean()
        if avg_prev <= 0:
            return 0.0
        change_rate = ((current - avg_prev) / avg_prev) * 100
        return round(change_rate, 2)

    @staticmethod
    def volume_ratio_stats(df_vol: pd.DataFrame, window: int = 5,
                           date: Optional[str] = None) -> Dict[str, float]:
        """指标11: 量比分布统计"""
        if df_vol.empty or "volume" not in df_vol.columns:
            return {"mean": 0.0, "std": 0.0, "current_ratio": 1.0}
        volumes = SentimentIndicators._series(df_vol, "volume", date).reset_index(drop=True)
        if len(volumes) < window + 1:
            return {"mean": 0.0, "std": 0.0, "current_ratio": 1.0}
        current = volumes.iloc[0]
        history = volumes.iloc[1:window + 1]
        mean_vol = history.mean()
        std_vol = history.std()
        vol_ratio = round(current / mean_vol, 2) if mean_vol > 0 else 1.0
        return {
            "mean": round(float(mean_vol), 2),
            "std": round(float(std_vol), 2),
            "current_ratio": vol_ratio,
        }

    def north_flow(self) -> Optional[float]:
        """指标12: 北向资金净流入（百万）"""
        return self.fetcher.fetch_north_flow()

    # ------------------------------------------------------------------
    # 恐慌贪婪指标 (16-17)
    # ------------------------------------------------------------------

    @staticmethod
    def fear_greed_index(
        ltd_ratio: float,
        advance_pct: Optional[float],
        turnover_pctile: float,
        volume_change: float,
        max_board: int,
        premium_rate: float,
    ) -> float:
        """指标16: A股版恐惧贪婪指数 (0-100)"""
        scores = []

        # 涨停/跌停比贡献 (权重25%)
        if ltd_ratio >= 10:
            s = 95
        elif ltd_ratio >= 5:
            s = 80
        elif ltd_ratio >= 3:
            s = 65
        elif ltd_ratio >= 1.5:
            s = 50
        elif ltd_ratio >= 0.8:
            s = 35
        else:
            s = max(5, int(ltd_ratio * 40))
        scores.append(s)

        # 上涨占比贡献 (权重25%)，该日无涨跌家数数据时取中性值
        if advance_pct is None:
            s = 50
        elif advance_pct >= 70:
            s = 90
        elif advance_pct >= 60:
            s = 75
        elif advance_pct >= 50:
            s = 55
        elif advance_pct >= 40:
            s = 35
        else:
            s = max(5, int(advance_pct * 1.2))
        scores.append(s)

        # 换手率分位数贡献 (权重15%)
        s = min(95, max(5, turnover_pctile))
        scores.append(s)

        # 成交额变化率贡献 (权重10%)
        if volume_change >= 20:
            s = 85
        elif volume_change >= 10:
            s = 70
        elif volume_change >= 0:
            s = 55
        elif volume_change >= -10:
            s = 40
        else:
            s = max(5, 30 + int(volume_change))
        scores.append(s)

        # 连板高度贡献 (权重15%)
        if max_board >= 7:
            s = 90
        elif max_board >= 5:
            s = 70
        elif max_board >= 3:
            s = 50
        else:
            s = max(10, max_board * 12)
        scores.append(s)

        # 溢价率贡献 (权重10%)
        if premium_rate >= 10:
            s = 85
        elif premium_rate >= 5:
            s = 70
        elif premium_rate >= 0:
            s = 55
        else:
            s = max(5, 45 + int(premium_rate))
        scores.append(s)

        weights = [25, 25, 15, 10, 15, 10]
        total_weight = sum(weights)
        fg_index = sum(s * w for s, w in zip(scores, weights)) / total_weight
        return round(min(100, max(0, fg_index)), 1)

    @staticmethod
    def vix_analog(df_idx: pd.DataFrame, window: int = 20,
                   date: Optional[str] = None) -> float:
        """指标17: VIX类比指标（基于波动率隐含情绪）"""
        if df_idx.empty or "pct_change" not in df_idx.columns:
            return 25.0
        returns = SentimentIndicators._series(df_idx, "pct_change", date).reset_index(drop=True)
        if len(returns) < window:
            return 25.0
        # 计算近N日波动率（年化）
        vol = returns.iloc[:window].std() * math.sqrt(242)
        # VIX类比：波动率越高，恐慌越大；映射到10-80范围
        if vol <= 10:
            vix = 15
        elif vol >= 40:
            vix = 75
        else:
            vix = 15 + (vol - 10) / 30 * 60
        return round(min(80, max(10, vix)), 2)

    # ------------------------------------------------------------------
    # 综合情绪指数 (13-15)
    # ------------------------------------------------------------------

    @staticmethod
    def composite_score(indicators: Dict[str, Any], weights: Optional[Dict[str, float]] = None) -> float:
        """指标13: 综合情绪评分（0-100分，加权合成）"""
        w = weights or DEFAULT_WEIGHTS

        def _num(key: str, default: float) -> float:
            """取指标数值；取数缺失（None）时以默认值占位，该项不参与加权"""
            val = indicators.get(key)
            return default if val is None else float(val)

        # 取数缺失（None）的指标不参与加权，权重按剩余项归一化
        w = {k: v for k, v in w.items() if indicators.get(k) is not None}
        if not w:
            return 50.0

        # 将各指标归一化到0-100
        normalized = {}

        # LTD Ratio (越高越好)
        ltd_r = indicators.get("limit_up_down_ratio", 1.0)
        normalized["limit_up_down_ratio"] = min(100, max(0, ltd_r * 10))

        # 涨跌家数比
        ad_r = _num("advance_decline_ratio", 1.0)
        normalized["advance_decline_ratio"] = min(100, max(0, ad_r * 50))

        # 涨停家数绝对值
        lu_c = indicators.get("limit_up_count", 0)
        normalized["limit_up_count"] = min(100, max(0, (lu_c / 200) * 100))

        # 涨速指标
        spd = _num("speed_indicator", 50.0)
        normalized["speed_indicator"] = min(100, max(0, spd))

        # 市场广度
        breadth = _num("market_breadth", 50.0)
        normalized["market_breadth"] = min(100, max(0, breadth))

        # 最高连板天数
        mc = indicators.get("max_consecutive_limit", 3)
        normalized["max_consecutive_limit"] = min(100, max(0, (mc / 9) * 100))

        # 连板梯队分布（总分）
        cd = indicators.get("consecutive_distribution", {})
        cd_total = sum(cd.values()) if isinstance(cd, dict) else 0
        normalized["consecutive_distribution"] = min(100, max(0, (cd_total / 200) * 100))

        # 溢价率（负值映射到低分）
        yp = _num("yesterday_premium", 0.0)
        normalized["yesterday_premium"] = min(100, max(0, 50 + yp * 3))

        # 炸板率（越低越好，反转）
        bb = _num("break_board_rate", 50.0)
        normalized["break_board_rate"] = min(100, max(0, (1 - bb / 100) * 100))

        # 换手率分位数
        tp = indicators.get("turnover_percentile", 50.0)
        normalized["turnover_percentile"] = min(100, max(0, tp))

        # 成交额变化率（正向）
        vc = indicators.get("volume_change_rate", 0.0)
        normalized["volume_change_rate"] = min(100, max(0, 50 + vc * 2))

        # 量比分布统计
        vr = indicators.get("volume_ratio_stats", {})
        cr = vr.get("current_ratio", 1.0) if isinstance(vr, dict) else 1.0
        normalized["volume_ratio_stats"] = min(100, max(0, (cr / 2) * 50))

        # 北向资金（正向）
        nf = _num("north_flow", 0.0)
        normalized["north_flow"] = min(100, max(0, 50 + nf / 1000))

        # 恐惧贪婪指数
        fg = indicators.get("fear_greed_index", 50.0)
        normalized["fear_greed_index"] = min(100, max(0, fg))

        # VIX类比（反向：VIX越高，情绪越低）
        vix = indicators.get("vix_analog", 25.0)
        normalized["vix_analog"] = min(100, max(0, (1 - vix / 80) * 100))

        # 加权合成
        total_weight = sum(w.values())
        score = 0.0
        for key, weight in w.items():
            val = normalized.get(key, 50.0)
            score += val * (weight / total_weight)

        return round(min(100, max(0, score)), 1)

    @staticmethod
    def sentiment_label(score: float) -> Dict[str, Any]:
        """指标14: 情绪状态分类"""
        for state, cfg in SENTIMENT_THRESHOLDS.items():
            if cfg["min"] <= score < cfg["max"]:
                return {
                    "state": state,
                    "label": cfg["label"],
                    "emoji": cfg["emoji"],
                    "score_range": f"{cfg['min']}-{cfg['max']}",
                }
        # 边界情况
        if score >= 100:
            return {"state": "overheated", "label": "过热", "emoji": "💥", "score_range": "80-100"}
        return {"state": "freezing", "label": "冰点", "emoji": "🥶", "score_range": "0-25"}

    @staticmethod
    def sentiment_trend(history_scores: List[float], window: int = 3) -> Dict[str, Any]:
        """指标15: 情绪趋势判断（连续N日变化方向）"""
        if len(history_scores) < 2:
            return {"direction": "未知", "consecutive_days": 0, "trend_strength": "弱"}

        # 计算每日变化
        changes = [history_scores[i] - history_scores[i + 1] for i in range(len(history_scores) - 1)]

        # 判断连续方向（最近的N日）
        recent_changes = changes[:min(window, len(changes))]
        all_positive = all(c > 0 for c in recent_changes)
        all_negative = all(c < 0 for c in recent_changes)

        if all_positive:
            direction = "上升"
            consecutive = len(recent_changes)
        elif all_negative:
            direction = "下降"
            consecutive = len(recent_changes)
        else:
            # 混合方向，看最近一次变化
            direction = "震荡" if recent_changes[0] == 0 else ("上升" if recent_changes[0] > 0 else "下降")
            consecutive = 1

        # 趋势强度
        avg_change = abs(sum(recent_changes) / len(recent_changes))
        if avg_change >= 15:
            strength = "强"
        elif avg_change >= 5:
            strength = "中"
        else:
            strength = "弱"

        return {
            "direction": direction,
            "consecutive_days": consecutive,
            "trend_strength": strength,
            "recent_changes": [round(c, 1) for c in recent_changes],
        }


# ===================================================================
# 报告生成层
# ===================================================================

class SentimentReport:
    """情绪报告生成器"""

    def __init__(self, output_dir: str = "./sentiment_data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.output_dir / "sentiment_history.json"

    @staticmethod
    def generate_report(
        date: str,
        indicators: Dict[str, Any],
        composite_score: float,
        sentiment_info: Dict[str, Any],
        trend_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成格式化的情绪报告"""
        lines = []
        sep = "=" * 60

        lines.append(sep)
        lines.append(f"  A股市场情绪量化分析报告")
        lines.append(f"  日期: {date}")
        lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(sep)

        # --- 涨跌统计类 ---
        lines.append("\n【一、涨跌统计类指标】")
        lines.append("-" * 40)
        lu = indicators.get("limit_up_count", 0)
        ld = indicators.get("limit_down_count", 0)
        lines.append(f"  涨停家数: {lu}")
        lines.append(f"  跌停家数: {ld}")
        lines.append(f"  涨跌停比 (LTD Ratio): {indicators.get('limit_up_down_ratio', 0)}")

        ad = indicators.get("advance_decline_stats", {})
        adv = ad.get("advance", 0) if isinstance(ad, dict) else 0
        dec = ad.get("decline", 0) if isinstance(ad, dict) else 0
        unc = ad.get("unchanged", 0) if isinstance(ad, dict) else 0
        lines.append(f"  上涨家数: {adv}")
        lines.append(f"  下跌家数: {dec}")
        lines.append(f"  平盘家数: {unc}")
        ad_ratio = indicators.get("advance_decline_ratio")
        spd = indicators.get("speed_indicator")
        lines.append(f"  涨跌家数比: {ad_ratio if ad_ratio is not None else '数据不可用（接口仅提供最新交易日快照）'}")
        lines.append(f"  涨速指标 (上涨占比): {str(spd) + '%' if spd is not None else '数据不可用'}")

        # --- 连板高度类 ---
        lines.append("\n【二、连板高度类指标】")
        lines.append("-" * 40)
        lines.append(f"  最高连板天数: {indicators.get('max_consecutive_limit', 0)}天")
        cd = indicators.get("consecutive_distribution", {})
        if isinstance(cd, dict):
            for k, v in cd.items():
                lines.append(f"    {k}: {v}家")
        lines.append(f"  昨日涨停今日溢价率: {indicators.get('yesterday_premium', 0)}%")
        lines.append(f"  炸板率: {indicators.get('break_board_rate', 0)}%")

        # --- 量能指标类 ---
        lines.append("\n【三、量能指标类】")
        lines.append("-" * 40)
        lines.append(f"  换手率分位数 (vs近20日): {indicators.get('turnover_percentile', 0)}%")
        lines.append(f"  成交额较5日均值变化: {indicators.get('volume_change_rate', 0)}%")
        vr = indicators.get("volume_ratio_stats", {})
        if isinstance(vr, dict):
            lines.append(f"  量比 (当前/均值): {vr.get('current_ratio', 1.0)}")
            lines.append(f"  5日均成交额: {vr.get('mean', 0)}")
        nf = indicators.get("north_flow", None)
        if nf is not None:
            direction_str = "净流入" if nf > 0 else ("净流出" if nf < 0 else "持平")
            lines.append(f"  北向资金 {direction_str}: {abs(nf):.2f}百万")
        else:
            lines.append("  北向资金: 数据不可用")

        # --- 恐慌贪婪指标 ---
        lines.append("\n【四、恐慌贪婪指标】")
        lines.append("-" * 40)
        fg = indicators.get("fear_greed_index", 50.0)
        fg_label = "极度恐惧" if fg < 20 else ("恐惧" if fg < 40 else ("中性" if fg < 60 else ("贪婪" if fg < 80 else "极度贪婪")))
        lines.append(f"  A股恐惧贪婪指数: {fg} ({fg_label})")
        vix = indicators.get("vix_analog", 25.0)
        vix_label = "低波动(乐观)" if vix < 20 else ("正常" if vix < 35 else ("高波动(恐慌)" if vix < 50 else "极高波动"))
        lines.append(f"  VIX类比指标: {vix} ({vix_label})")

        # --- 综合情绪指数 ---
        lines.append("\n【五、综合情绪指数】")
        lines.append("-" * 40)
        emoji = sentiment_info.get("emoji", "")
        label = sentiment_info.get("label", "")
        lines.append(f"  {emoji} 综合评分: {composite_score}/100")
        lines.append(f"  {emoji} 情绪状态: {label}")

        if trend_info:
            lines.append("\n【六、情绪趋势判断】")
            lines.append("-" * 40)
            lines.append(f"  趋势方向: {trend_info.get('direction', '未知')}")
            lines.append(f"  连续天数: {trend_info.get('consecutive_days', 0)}天")
            lines.append(f"  趋势强度: {trend_info.get('trend_strength', '弱')}")
            rc = trend_info.get("recent_changes", [])
            if rc:
                arrows = ["↑" if c > 0 else ("↓" if c < 0 else "→") for c in rc]
                lines.append(f"  近{len(rc)}日变化: {' '.join(arrows)} ({', '.join(str(c) for c in rc)})")

        lines.append("\n" + sep)
        return "\n".join(lines)

    def save_result(self, date: str, indicators: Dict[str, Any], composite_score: float,
                    sentiment_info: Dict[str, Any], trend_info: Optional[Dict[str, Any]] = None):
        """保存结果到JSON文件"""
        record = {
            "date": date,
            "timestamp": datetime.now().isoformat(),
            "indicators": indicators,
            "composite_score": composite_score,
            "sentiment_state": sentiment_info,
        }
        if trend_info:
            record["trend"] = trend_info

        # 追加到历史文件
        history = self._load_history()
        # 避免重复
        existing_dates = [r.get("date") for r in history]
        if date not in existing_dates:
            history.append(record)
            # 按日期排序（最新的在前）
            history.sort(key=lambda x: x.get("date", ""), reverse=True)

        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        print(f"  💾 结果已保存至: {self.history_file}")

    def _load_history(self) -> List[Dict]:
        """加载历史数据"""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
            except (json.JSONDecodeError, IOError):
                pass
        return []

    def load_history(self, days: Optional[int] = None) -> List[Dict]:
        """加载历史情绪数据"""
        history = self._load_history()
        if days and days > 0:
            return history[:days]
        return history


# ===================================================================
# 主程序入口
# ===================================================================

def load_weights(config_path: Optional[str] = None) -> Dict[str, float]:
    """加载权重配置"""
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # 检查默认配置文件
    default_cfg = Path(__file__).parent / "sentiment_weights.json"
    if default_cfg.exists():
        with open(default_cfg, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_WEIGHTS


def run_single_day(date_str: Optional[str] = None, verbose: bool = False,
                   config_path: Optional[str] = None, output_dir: str = "./sentiment_data"):
    """运行单日情绪分析"""

    weights = load_weights(config_path)
    fetcher = MarketDataFetcher()
    calc = SentimentIndicators(fetcher)
    report_gen = SentimentReport(output_dir)

    # 确定日期
    if date_str:
        query_date = date_str
    else:
        query_date = datetime.now().strftime("%Y-%m-%d")

    print(f"\n📊 A股市场情绪量化分析 - {query_date}")
    print("=" * 50)

    # --- 获取原始数据 ---
    if verbose:
        print("\n[1/3] 获取市场原始数据...")

    df_ltd = fetcher.fetch_limit_up_down_history(20)
    df_ad = fetcher.fetch_advance_decline_history(20)
    df_vol = fetcher.fetch_volume_turnover_history(20)
    df_idx = fetcher.fetch_index_history(30)

    if verbose:
        print(f"  涨跌停数据: {len(df_ltd)}行")
        print(f"  涨跌家数数据: {len(df_ad)}行")
        print(f"  量价数据: {len(df_vol)}行")
        print(f"  指数数据: {len(df_idx)}行")

    # --- 计算指标 ---
    if verbose:
        print("\n[2/3] 计算情绪指标...")

    indicators = {}

    # 涨跌统计类 (1-4)
    ltd_counts = calc.limit_up_down_count(df_ltd, query_date)
    indicators["limit_up_count"] = ltd_counts["limit_up"]
    indicators["limit_down_count"] = ltd_counts["limit_down"]
    indicators["limit_up_down_ratio"] = calc.limit_up_down_ratio(df_ltd, query_date)

    ad_stats = calc.advance_decline_stats(df_ad, query_date)
    indicators["advance_decline_stats"] = ad_stats
    ad_total = ad_stats["advance"] + ad_stats["decline"] + ad_stats.get("unchanged", 0)
    if ad_total > 0:
        indicators["advance_decline_ratio"] = round(
            ad_stats["advance"] / max(ad_stats["decline"], 1), 2
        )
        indicators["speed_indicator"] = calc.speed_indicator(ad_stats["advance"], ad_total)
        indicators["market_breadth"] = round((ad_stats["advance"] / ad_total) * 100, 2)
    else:
        # 涨跌家数只有最新交易日快照，该日无数据则相关指标不参与加权
        indicators["advance_decline_ratio"] = None
        indicators["speed_indicator"] = None
        indicators["market_breadth"] = None

    # 连板高度类 (5-8)
    indicators["max_consecutive_limit"] = calc.max_consecutive_limit(df_ltd, query_date)
    indicators["consecutive_distribution"] = calc.consecutive_distribution(df_ltd, query_date)
    indicators["yesterday_premium"] = calc.yesterday_premium(df_ltd, query_date)
    indicators["break_board_rate"] = calc.break_board_rate(df_ltd, query_date)

    # 量能指标类 (9-12)
    indicators["turnover_percentile"] = calc.turnover_percentile(df_vol, date=query_date)
    indicators["volume_change_rate"] = calc.volume_change_rate(df_vol, date=query_date)
    indicators["volume_ratio_stats"] = calc.volume_ratio_stats(df_vol, date=query_date)
    nf = calc.north_flow()
    indicators["north_flow"] = round(nf, 2) if nf is not None else None

    # 恐慌贪婪指标 (16-17)
    fg_index = calc.fear_greed_index(
        ltd_ratio=indicators["limit_up_down_ratio"],
        advance_pct=indicators["market_breadth"],
        turnover_pctile=indicators["turnover_percentile"],
        volume_change=indicators["volume_change_rate"],
        max_board=indicators["max_consecutive_limit"],
        premium_rate=indicators["yesterday_premium"],
    )
    indicators["fear_greed_index"] = fg_index

    vix_val = calc.vix_analog(df_idx, date=query_date)
    indicators["vix_analog"] = vix_val

    # --- 综合情绪指数 (13-15) ---
    if verbose:
        print("\n[3/3] 合成综合情绪指数...")

    composite = calc.composite_score(indicators, weights)
    sentiment_info = calc.sentiment_label(composite)

    # 趋势判断（需要历史数据）
    trend_info = None
    history = report_gen._load_history()
    if len(history) >= 2:
        hist_scores = [r.get("composite_score", 50.0) for r in history[:10]]
        # 插入当前分数到最前面
        hist_scores_with_current = [composite] + hist_scores
        trend_info = calc.sentiment_trend(hist_scores_with_current, window=3)

    # --- 生成报告 ---
    report_text = report_gen.generate_report(
        query_date, indicators, composite, sentiment_info, trend_info
    )
    print(report_text)

    # --- 保存结果 ---
    report_gen.save_result(query_date, indicators, composite, sentiment_info, trend_info)

    return {
        "date": query_date,
        "indicators": indicators,
        "composite_score": composite,
        "sentiment_state": sentiment_info,
        "trend": trend_info,
    }


def run_history(days: int = 10, config_path: Optional[str] = None,
                output_dir: str = "./sentiment_data"):
    """获取近N日历史情绪数据"""
    weights = load_weights(config_path)
    fetcher = MarketDataFetcher()
    calc = SentimentIndicators(fetcher)
    report_gen = SentimentReport(output_dir)

    print(f"\n📊 A股市场情绪历史回查 - 近{days}日")
    print("=" * 50)

    # 获取历史数据
    df_ltd = fetcher.fetch_limit_up_down_history(days + 5)
    df_ad = fetcher.fetch_advance_decline_history(days + 5)
    df_vol = fetcher.fetch_volume_turnover_history(days + 5)
    df_idx = fetcher.fetch_index_history(30)

    results = []
    for i in range(min(days, len(df_ltd))):
        date_row = df_ltd.iloc[i] if "date" in df_ltd.columns else None
        date_str = str(date_row.get("date", "")) if date_row is not None else ""
        # 清理日期格式
        date_clean = re.sub(r"[^\d-]", "", date_str)[:10]

        indicators = {}

        # 涨跌统计类
        ltd_counts = calc.limit_up_down_count(df_ltd, date_clean)
        indicators["limit_up_count"] = ltd_counts["limit_up"]
        indicators["limit_down_count"] = ltd_counts["limit_down"]
        indicators["limit_up_down_ratio"] = calc.limit_up_down_ratio(df_ltd, date_clean)

        ad_stats = calc.advance_decline_stats(df_ad, date_clean)
        indicators["advance_decline_stats"] = ad_stats
        ad_total = ad_stats["advance"] + ad_stats["decline"] + ad_stats.get("unchanged", 0)
        if ad_total > 0:
            indicators["advance_decline_ratio"] = round(
                ad_stats["advance"] / max(ad_stats["decline"], 1), 2
            )
            indicators["speed_indicator"] = calc.speed_indicator(ad_stats["advance"], ad_total)
            indicators["market_breadth"] = round((ad_stats["advance"] / ad_total) * 100, 2)
        else:
            indicators["advance_decline_ratio"] = None
            indicators["speed_indicator"] = None
            indicators["market_breadth"] = None

        # 连板高度类
        indicators["max_consecutive_limit"] = calc.max_consecutive_limit(df_ltd, date_clean)
        indicators["consecutive_distribution"] = calc.consecutive_distribution(df_ltd, date_clean)
        indicators["yesterday_premium"] = calc.yesterday_premium(df_ltd, date_clean)
        indicators["break_board_rate"] = calc.break_board_rate(df_ltd, date_clean)

        # 量能指标类
        indicators["turnover_percentile"] = calc.turnover_percentile(df_vol, date=date_clean)
        indicators["volume_change_rate"] = calc.volume_change_rate(df_vol, date=date_clean)
        vr = calc.volume_ratio_stats(df_vol, date=date_clean)
        indicators["volume_ratio_stats"] = vr
        indicators["north_flow"] = None  # 历史数据不单独查询北向

        # 恐慌贪婪指标
        fg_index = calc.fear_greed_index(
            ltd_ratio=indicators["limit_up_down_ratio"],
            advance_pct=indicators["market_breadth"],
            turnover_pctile=indicators["turnover_percentile"],
            volume_change=indicators["volume_change_rate"],
            max_board=indicators["max_consecutive_limit"],
            premium_rate=indicators.get("yesterday_premium", 0.0),
        )
        indicators["fear_greed_index"] = fg_index
        indicators["vix_analog"] = calc.vix_analog(df_idx, date=date_clean)

        # 综合评分
        composite = calc.composite_score(indicators, weights)
        sentiment_info = calc.sentiment_label(composite)

        results.append({
            "date": date_clean,
            "indicators": indicators,
            "composite_score": composite,
            "sentiment_state": sentiment_info,
        })

    # 趋势判断
    if len(results) >= 2:
        scores = [r["composite_score"] for r in results]
        trend_info = calc.sentiment_trend(scores, window=min(3, len(scores) - 1))
    else:
        trend_info = None

    # 输出表格
    print(f"\n{'日期':<12} {'涨停':>5} {'跌停':>5} {'涨跌比':>6} {'上涨':>6} {'下跌':>6} "
          f"{'最高板':>5} {'换手分位':>7} {'恐惧贪婪':>7} {'综合评分':>7} {'状态'}")
    print("-" * 90)

    for r in results:
        d = r["date"]
        ind = r["indicators"]
        lu = ind.get("limit_up_count", 0)
        ld = ind.get("limit_down_count", 0)
        lr = ind.get("limit_up_down_ratio", 0)
        ad_s = ind.get("advance_decline_stats", {})
        adv = ad_s.get("advance", 0) if isinstance(ad_s, dict) else 0
        dec = ad_s.get("decline", 0) if isinstance(ad_s, dict) else 0
        # 涨跌家数只有最新交易日快照，历史日期无数据时以 - 占位
        adv_txt, dec_txt = (str(adv) if adv else "-"), (str(dec) if dec else "-")
        mb = ind.get("max_consecutive_limit", 0)
        tp = ind.get("turnover_percentile", 0)
        fg = ind.get("fear_greed_index", 0)
        cs = r["composite_score"]
        si = r["sentiment_state"]
        emoji = si.get("emoji", "")
        label = si.get("label", "")

        print(f"{d:<12} {lu:>5} {ld:>5} {lr:>6.1f} {adv_txt:>6} {dec_txt:>6} "
              f"{mb:>5} {tp:>7.1f}% {fg:>7.1f} {cs:>7.1f} {emoji}{label}")

    if trend_info:
        print(f"\n📈 情绪趋势: {trend_info.get('direction', '未知')} "
              f"(连续{trend_info.get('consecutive_days', 0)}天, 强度:{trend_info.get('trend_strength', '弱')})")

    # 保存历史数据
    for r in results:
        report_gen.save_result(r["date"], r["indicators"], r["composite_score"],
                               r["sentiment_state"])

    return results


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="A股市场情绪量化指标计算工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python market_sentiment.py                          # 今日情绪报告
  python market_sentiment.py --date 2026-06-23        # 指定日期回查
  python market_sentiment.py --history 10             # 近10日历史数据
  python market_sentiment.py --report                 # 详细报告模式
  python market_sentiment.py --trend                  # 附加趋势分析
  python market_sentiment.py --config weights.json    # 自定义权重
        """,
    )

    parser.add_argument("--date", type=str, help="指定查询日期 (YYYY-MM-DD)")
    parser.add_argument("--history", type=int, metavar="DAYS", help="获取近N日历史情绪数据")
    parser.add_argument("--report", action="store_true", help="输出详细格式化的情绪报告")
    parser.add_argument("--trend", action="store_true", help="附加情绪趋势判断")
    parser.add_argument("--config", type=str, metavar="FILE", help="自定义权重配置文件路径 (JSON)")
    parser.add_argument("--output", type=str, default="./sentiment_data", help="结果输出目录")
    parser.add_argument("--verbose", action="store_true", help="显示详细计算过程")

    args = parser.parse_args()

    if args.history:
        run_history(
            days=args.history,
            config_path=args.config,
            output_dir=args.output,
        )
    else:
        result = run_single_day(
            date_str=args.date,
            verbose=args.verbose or args.report,
            config_path=args.config,
            output_dir=args.output,
        )

        if args.trend and result.get("trend"):
            trend = result["trend"]
            print(f"\n📈 情绪趋势分析:")
            print(f"   方向: {trend['direction']}")
            print(f"   连续天数: {trend['consecutive_days']}天")
            print(f"   强度: {trend['trend_strength']}")


if __name__ == "__main__":
    main()
