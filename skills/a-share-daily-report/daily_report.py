#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股自动化日报生成器 (A-Share Daily Report Generator)
=====================================================
整合多个分析模块，收盘后自动生成综合市场复盘报告。

功能模块:
  1. 大盘走势总结 (Market Overview)
  2. 板块强弱排行 (Sector Ranking)
  3. 市场情绪分析 (Sentiment Analysis)
  4. 异动个股追踪 (Unusual Activity)
  5. 技术面信号汇总 (Technical Signals)
  6. 明日展望与策略建议 (Outlook & Strategy)

用法:
    python daily_report.py                          # 今日报告(详细模式)
    python daily_report.py --style concise          # 简洁版
    python daily_report.py --style professional     # 专业版
    python daily_report.py --date 2026-06-23        # 指定日期回查
    python daily_report.py --format json            # 仅JSON数据版
    python daily_report.py --format html            # 仅HTML完整版
    python daily_report.py --format all             # 全部格式输出
    python daily_report.py --cronjob                # 定时任务模式(静默)
    python daily_report.py --force-refresh          # 强制刷新所有数据

依赖: pandas, numpy, requests + 已安装的A股分析Skills
"""

import os
import random
import sys
import threading
import time as _time
import json
import argparse
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple


# ════════════════════════════════════════
# 直连数据源辅助函数（替代 akshare）
# ════════════════════════════════════════

# 东财限流器（防封禁铁律：串行、间隔≥1s+随机抖动）
_EM_LOCK = threading.Lock()
_EM_LAST_REQUEST = {"_time": 0.0}
_EM_MIN_INTERVAL = float(os.environ.get("EM_MIN_INTERVAL", "1.2"))

def _em_throttle():
    """东财串行限流: 间隔≥_EM_MIN_INTERVAL + 随机抖动"""
    with _EM_LOCK:
        now = _time.time()
        elapsed = now - _EM_LAST_REQUEST["_time"]
        if elapsed < _EM_MIN_INTERVAL:
            sleep_time = _EM_MIN_INTERVAL - elapsed + random.uniform(0.3, 1.5)
            _time.sleep(sleep_time)
        _EM_LAST_REQUEST["_time"] = _time.time()

def _em_get(url, params=None, timeout=15):
    """东财统一请求入口，内置限流"""
    import requests as req
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.eastmoney.com/",
    }
    _em_throttle()
    return req.get(url, params=params, headers=headers, timeout=timeout)

def _em_clist_all(fs: str, fields: str, page_size: int = 200,
                  max_pages: int = 60) -> List[Dict[str, Any]]:
    """东财clist接口分页拉取 — 单次约返回200条，需翻页取满（失败返回已取到的部分）"""
    rows: List[Dict[str, Any]] = []
    try:
        page, total = 1, None
        while page <= max_pages:
            r = _em_get("https://push2.eastmoney.com/api/qt/clist/get", params={
                "fid": "f12", "po": "1", "np": "1", "fltt": "2", "invt": "2",
                "ut": "b2884a393a59ad64002292a3e90d46a5",
                "fs": fs, "fields": fields,
                "pn": str(page), "pz": str(page_size)
            })
            data = r.json().get("data", {}) or {}
            diff = data.get("diff") or []
            if total is None:
                total = int(data.get("total") or 0)
            if not diff:
                break
            rows.extend(diff)
            page_size = len(diff)  # 服务端可能压缩单页条数，按实际条数翻页
            if total and len(rows) >= total:
                break
            page += 1
    except Exception:
        pass
    return rows

_FULL_MARKET_CACHE: Dict[str, Any] = {}

def _get_full_market() -> pd.DataFrame:
    """获取全市场行情 — 东财clist分页拉取（替代 ak.stock_zh_a_spot_em()）
    进程内缓存，供涨跌家数统计与放量突破筛选复用"""
    if _FULL_MARKET_CACHE.get("df") is not None:
        return _FULL_MARKET_CACHE["df"]
    rows = _em_clist_all("m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
                         "f2,f3,f4,f5,f6,f7,f8,f10,f12,f14")
    df = pd.DataFrame([{
        "代码": str(d.get("f12", "")),
        "名称": d.get("f14", ""),
        "最新价": d.get("f2", 0),
        "涨跌幅": d.get("f3", 0),
        "涨跌额": d.get("f4", 0),
        "成交量": d.get("f5", 0),
        "成交额": d.get("f6", 0),
        "振幅": d.get("f7", 0),
        "换手率": d.get("f8", 0),
        "量比": d.get("f10", 0),
    } for d in rows]) if rows else pd.DataFrame()
    if len(df):
        _FULL_MARKET_CACHE["df"] = df
    return df

# 指数代码与股票代码可能重号（如000001既是上证指数也是平安银行），需显式指定市场前缀
INDEX_MARKET = {"000001": "1", "399001": "0", "399006": "0"}

def _get_stock_hist(symbol: str, period: str = "daily", count: int = 120,
                    market: Optional[str] = None) -> pd.DataFrame:
    """获取K线历史 — 东财 push2his 直连"""
    try:
        # 使用东财 K 线 API
        freq_map = {"daily": "101", "weekly": "102", "monthly": "103"}
        freq = freq_map.get(period, "101")
        if market is None:
            market = "1" if symbol.startswith("6") else "0"
        r = _em_get(f"https://push2his.eastmoney.com/api/qt/stock/kline/get", params={
            "secid": f"{market}.{symbol}",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": freq, "fqt": "1", "beg": "0", "end": "20500000",
            "lmt": str(count), "ut": "b2884a393a59ad64002292a3e90d46a5"
        })
        data = r.json().get("data", {}).get("klines", [])
        if not data:
            return pd.DataFrame()
        rows = []
        for item in data:
            parts = item.split(",")
            rows.append({
                "日期": parts[0][:10] if len(parts) > 0 else "",
                "开盘": float(parts[1]) if len(parts) > 1 else 0,
                "收盘": float(parts[2]) if len(parts) > 2 else 0,
                "最高": float(parts[3]) if len(parts) > 3 else 0,
                "最低": float(parts[4]) if len(parts) > 4 else 0,
                "成交量": float(parts[5]) if len(parts) > 5 else 0,
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

def _get_limit_pool(kind: str = "zt", date_str: str = None) -> List[Dict[str, Any]]:
    """获取涨停池/跌停池 — 东财 push2ex getTopicZTPool / getTopicDTPool
    kind: zt(涨停) / dt(跌停)；返回中文字段字典列表，取不到返回空列表"""
    try:
        url_map = {"zt": "https://push2ex.eastmoney.com/getTopicZTPool",
                   "dt": "https://push2ex.eastmoney.com/getTopicDTPool"}
        url = url_map.get(kind)
        if not url:
            return []
        if not date_str:
            date_str = datetime.now().strftime("%Y%m%d")
        r = _em_get(url, params={
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt",
            "Pageindex": "0",
            "pagesize": "500",
            "sort": "fbt:asc" if kind == "zt" else "fund:desc",
            "date": date_str.replace("-", ""),
            "_": int(_time.time() * 1000),
        })
        pool = ((r.json().get("data") or {}).get("pool")) or []
        rows = []
        for it in pool:
            rows.append({
                "代码": str(it.get("c", "")),
                "名称": it.get("n", ""),
                "涨跌幅": round(float(it.get("zdp", 0) or 0), 2),
                "所属行业": it.get("hybk", "") or "",
                "成交额": float(it.get("amount", 0) or 0),
                "连板数": int(it.get("lbc", 1) or 1),
            })
        return rows
    except Exception:
        return []

def _get_industry_boards() -> pd.DataFrame:
    """获取行业板块 — 东财板块行情（含成交额/上涨家数/主力净流入）"""
    rows = _em_clist_all("m:90+t:2+f:!50", "f12,f14,f2,f3,f6,f62,f104", max_pages=10)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{
        "板块代码": str(d.get("f12", "")),
        "板块名称": d.get("f14", ""),
        "涨跌幅": d.get("f3", 0),
        "成交额": d.get("f6", 0),
        "主力净流入": d.get("f62", 0),
        "上涨家数": d.get("f104", 0),
    } for d in rows])

def _get_concept_boards() -> pd.DataFrame:
    """获取概念板块 — 东财板块行情"""
    rows = _em_clist_all("m:90+t:3+f:!50", "f12,f14,f2,f3,f6,f104", max_pages=10)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{
        "板块代码": str(d.get("f12", "")),
        "板块名称": d.get("f14", ""),
        "涨跌幅": d.get("f3", 0),
        "成交额": d.get("f6", 0),
        "上涨家数": d.get("f104", 0),
    } for d in rows])

def _get_north_flow() -> Optional[float]:
    """北向资金当日净流入（百万）— 同花顺 hsgtApi 龙虎榜北向口径"""
    try:
        import requests as req
        r = req.get("https://data.hexin.cn/market/hsgtApi/method/dayChart/",
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                             "Referer": "https://data.hexin.cn/"}, timeout=10)
        d = r.json()
        hgt, sgt = d.get("hgt") or [], d.get("sgt") or []
        n = min(len(hgt), len(sgt))
        # 取最后一个沪股通/深股通均有值的时点（盘中累计，末点即当日净流入，单位：亿元）
        for i in range(n - 1, -1, -1):
            try:
                h, s = float(hgt[i]), float(sgt[i])
            except (TypeError, ValueError):
                continue
            return round((h + s) * 100, 2)  # 亿元 → 百万
    except Exception as e:
        logger.warning(f"北向资金获取失败: {e}")
    return None


# ============================================================
# 路径配置 - 自动定位skills目录
# ============================================================
SKILL_DIR = Path(__file__).parent.resolve()
REPORTS_DIR = SKILL_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# 父级skills目录（所有子skill的根）
PARENT_SKILLS_DIR = SKILL_DIR.parent

# 注册各模块路径（含父级skills目录）
if str(PARENT_SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_SKILLS_DIR))
for subdir in ["market-sentiment", "sector-rotation", "dragon-list",
               "tech-indicators", "kline-patterns", "a-share-data-cache"]:
    p = PARENT_SKILLS_DIR / subdir
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger(__name__)

# ============================================================
# 权重股/蓝筹股列表（用于技术面信号扫描）
# ============================================================
WEIGHT_STOCKS = [
    # 上证50核心
    "600519", "贵州茅台",
    "601318", "中国平安",
    "600036", "招商银行",
    "600276", "恒瑞医药",
    "600900", "长江电力",
    # 沪深300核心
    "000858", "五粮液",
    "000333", "美的集团",
    "002415", "海康威视",
    "601012", "隆基绿能",
    "300750", "宁德时代",
    "002594", "比亚迪",
    # 科技龙头
    "002475", "立讯精密",
    "688981", "中芯国际",
    "603986", "兆易创新",
    "002230", "科大讯飞",
    # 金融地产
    "600030", "中信证券",
    "601166", "兴业银行",
    "600048", "保利发展",
]

# ============================================================
# 工具函数
# ============================================================

def is_trading_day(date: datetime = None) -> bool:
    """判断是否为A股交易日（通过腾讯财经API，含节假日排除）"""
    from trading_utils import is_trading_day as _api_is_trading_day
    return _api_is_trading_day()


def parse_date(date_str: Optional[str] = None) -> str:
    """解析日期字符串，返回YYYY-MM-DD格式"""
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.now().strftime("%Y-%m-%d")


def format_pct(val: Optional[float]) -> str:
    """格式化百分比"""
    if val is None:
        return "-"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.2f}%"


def format_amount(yuan: Optional[float]) -> str:
    """格式化金额显示"""
    if yuan is None:
        return "-"
    abs_yuan = abs(yuan)
    if abs_yuan >= 1e12:
        return f"{yuan / 1e12:.2f}万亿"
    elif abs_yuan >= 1e8:
        return f"{yuan / 1e8:.2f}亿"
    elif abs_yuan >= 1e4:
        return f"{yuan / 1e4:.2f}万"
    else:
        return f"{yuan:.0f}"


# ============================================================
# 数据获取层 - 通过 SmartDispatcher
# ============================================================

class ReportDataFetcher:
    """日报数据获取器，统一调度所有数据源"""

    def __init__(self, force_refresh: bool = False):
        from data_cache import SmartDispatcher
        self.dispatcher = SmartDispatcher()
        self.force_refresh = force_refresh

    # --- 指数行情 ---
    def fetch_index_quotes(self) -> Dict[str, Any]:
        """获取三大指数行情（上证/深证/创业板）"""
        indices = {
            "上证指数": {"code": "000001", "sina": "s_sh000001"},
            "深证成指": {"code": "399001", "sina": "s_sz399001"},
            "创业板指": {"code": "399006", "sina": "s_sz399006"},
        }

        results = {}
        # 尝试AKShare获取全市场行情摘要
        try:
            df_spot = _get_full_market()
            if df_spot is not None and len(df_spot) > 0:
                total_stocks = len(df_spot)
                up_count = int((df_spot["涨跌幅"] > 0).sum())
                down_count = int((df_spot["涨跌幅"] < 0).sum())
                flat_count = total_stocks - up_count - down_count
                results["_market_breadth"] = {
                    "total": total_stocks,
                    "up": up_count,
                    "down": down_count,
                    "flat": flat_count,
                }
        except Exception:
            pass

        # 通过新浪获取指数行情
        sina_codes = [v["sina"] for v in indices.values()]
        sina_str = ",".join(sina_codes)
        url = f"http://hq.sinajs.cn/list={sina_str}"
        headers = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        }

        try:
            import requests as req
            resp = req.get(url, headers=headers, timeout=15)
            resp.encoding = "gbk"
            if resp.status_code == 200:
                for line in resp.text.strip().split("\n"):
                    m = __import__("re").match(r'var hq_str_(\w+)="(.*)";', line)
                    if not m:
                        continue
                    sym_key = m.group(1)
                    parts = m.group(2).split(",")
                    if len(parts) < 32:
                        continue

                    # 找到对应的指数名称
                    idx_name = None
                    for name, info in indices.items():
                        if info["sina"] == sym_key:
                            idx_name = name
                            break
                    if not idx_name:
                        continue

                    try:
                        price = float(parts[3]) if parts[3] else 0
                        prev_close = float(parts[2]) if parts[2] else 0
                        open_p = float(parts[1]) if parts[1] else 0
                        high = float(parts[4]) if parts[4] else 0
                        low = float(parts[5]) if parts[5] else 0
                        volume = int(float(parts[8])) if parts[8] else 0  # 手
                        amount = float(parts[9]) if parts[9] else 0  # 元

                        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0

                        results[idx_name] = {
                            "code": indices[idx_name]["code"],
                            "name": idx_name,
                            "open": open_p,
                            "prev_close": prev_close,
                            "price": price,
                            "high": high,
                            "low": low,
                            "change_pct": change_pct,
                            "volume": volume,
                            "amount": amount,
                        }
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            logger.warning(f"新浪指数行情获取失败: {e}")

        # 如果新浪失败，尝试pytdx
        if not any(k.startswith("上证") or k.startswith("深证") or k.startswith("创业") for k in results):
            try:
                from data_cache import DataFetcher
                fetcher = DataFetcher()
                pytdx_data = fetcher.fetch_pytdx_quote(["000001", "399001", "399006"])
                if pytdx_data:
                    name_map = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指"}
                    for code, data in pytdx_data.items():
                        idx_name = name_map.get(code)
                        if idx_name:
                            results[idx_name] = {
                                "code": code,
                                "name": idx_name,
                                "open": data.get("open"),
                                "prev_close": data.get("prev_close"),
                                "price": data.get("price"),
                                "high": data.get("high"),
                                "low": data.get("low"),
                                "change_pct": data.get("change_pct", 0),
                                "volume": data.get("volume", 0),
                                "amount": data.get("amount", 0),
                            }
            except Exception as e:
                logger.warning(f"pytdx指数行情获取失败: {e}")

        return results

    # --- 年内累计涨跌 ---
    def fetch_ytd_change(self, index_code: str) -> Optional[float]:
        """获取指数年初至今涨跌幅"""
        try:
            year = datetime.now().year
            df = _get_stock_hist(symbol=index_code, period="daily",
                                 count=320, market=INDEX_MARKET.get(index_code))
            if df is not None and len(df) > 0:
                df = df[df["日期"].astype(str) >= f"{year}-01-01"]
            if df is not None and len(df) >= 2:
                first_close = float(df["收盘"].iloc[0])
                last_close = float(df["收盘"].iloc[-1])
                if first_close:
                    return round((last_close - first_close) / first_close * 100, 2)
        except Exception:
            pass
        return None

    # --- K线数据（用于支撑阻力位分析）---
    def fetch_index_kline(self, index_code: str, days: int = 60) -> Optional[pd.DataFrame]:
        """获取指数K线数据（东财K线接口，指数代码需显式指定市场前缀）"""
        try:
            df = _get_stock_hist(symbol=index_code, period="daily",
                                 count=days * 2, market=INDEX_MARKET.get(index_code))
            if df is not None and len(df) > 0:
                col_map = {"日期": "date", "开盘": "open", "最高": "high",
                           "最低": "low", "收盘": "close", "成交量": "volume"}
                df.rename(columns=col_map, inplace=True)
                for col in ["open", "high", "low", "close"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                if "volume" in df.columns:
                    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
                return df.tail(days).reset_index(drop=True)
        except Exception:
            pass
        return None

    # --- 全市场行情（涨跌家数）---
    def fetch_market_breadth(self) -> Dict[str, Any]:
        """全市场涨跌家数统计：东财全市场快照 + 涨停池/跌停池
        取不到即返回None，不做任何估算"""
        try:
            df = _get_full_market()
            if df is not None and len(df) > 0:
                chg = pd.to_numeric(df["涨跌幅"], errors="coerce")
                total = int(chg.notna().sum())
                up = int((chg > 0).sum())
                down = int((chg < 0).sum())
                zt = _get_limit_pool("zt")
                dt = _get_limit_pool("dt")
                return {
                    "total": total, "up": up, "down": down, "flat": total - up - down,
                    "limit_up": len(zt) if zt else None,
                    "limit_down": len(dt) if dt else None,
                }
        except Exception:
            pass

        return {"total": None, "up": None, "down": None, "flat": None,
                "limit_up": None, "limit_down": None}

    # --- 北向资金 ---
    def fetch_north_flow(self) -> Optional[float]:
        """获取北向资金净流入（百万）"""
        return _get_north_flow()

    # --- 涨停股列表 ---
    def fetch_limit_up_stocks(self) -> List[Dict[str, Any]]:
        """获取今日涨停股列表"""
        stocks = []
        for row in _get_limit_pool("zt")[:50]:
            stocks.append({
                "code": row["代码"],
                "name": row["名称"],
                "pct_change": row["涨跌幅"],
                "sector": row["所属行业"],
                "amount": row["成交额"],
                "consecutive": row["连板数"],
            })
        return stocks

    # --- 放量突破个股 ---
    def fetch_volume_breakout(self) -> List[Dict[str, Any]]:
        """获取成交量突增3倍以上的个股"""
        try:
            df = _get_full_market()
            if df is not None and len(df) > 0:
                # 筛选量比>3的个股（放量）
                if "量比" in df.columns:
                    df["量比"] = pd.to_numeric(df["量比"], errors="coerce")
                    breakout = df[df["量比"] >= 3.0].copy()
                    breakout = breakout.sort_values("量比", ascending=False).head(20)
                    stocks = []
                    for _, row in breakout.iterrows():
                        stocks.append({
                            "code": str(row.get("代码", "")),
                            "name": str(row.get("名称", "")),
                            "volume_ratio": float(row.get("量比", 0)) if pd.notna(row.get("量比")) else 0,
                            "pct_change": float(row.get("涨跌幅", 0)) if pd.notna(row.get("涨跌幅")) else 0,
                            "price": float(row.get("最新价", 0)) if pd.notna(row.get("最新价")) else 0,
                        })
                    return stocks
        except Exception:
            pass
        return []


# ============================================================
# 模块1: 大盘走势总结 (Market Overview)
# ============================================================

class MarketOverviewGenerator:
    """大盘走势分析"""

    def __init__(self, fetcher: ReportDataFetcher):
        self.fetcher = fetcher

    def generate(self) -> Dict[str, Any]:
        data = {"indices": {}, "ytd": {}, "support_resistance": {}, "breadth": {}}

        # 获取指数行情
        index_data = self.fetcher.fetch_index_quotes()
        for name, info in index_data.items():
            if name.startswith("_"):
                continue
            data["indices"][name] = info

            # 年内累计涨跌
            ytd = self.fetcher.fetch_ytd_change(info.get("code", ""))
            data["ytd"][name] = ytd

            # 支撑阻力位分析（基于近60日K线）
            kline_df = self.fetcher.fetch_index_kline(info.get("code", ""), days=60)
            if kline_df is not None and "close" in kline_df.columns:
                closes = kline_df["close"].dropna()
                if len(closes) >= 20:
                    ma5 = round(float(closes.tail(5).mean()), 2)
                    ma10 = round(float(closes.tail(10).mean()), 2)
                    ma20 = round(float(closes.tail(20).mean()), 2)
                    recent_high = round(float(kline_df["high"].tail(20).max()), 2) if "high" in kline_df.columns else None
                    recent_low = round(float(kline_df["low"].tail(20).min()), 2) if "low" in kline_df.columns else None

                    current_price = info.get("price", closes.iloc[-1])
                    data["support_resistance"][name] = {
                        "ma5": ma5, "ma10": ma10, "ma20": ma20,
                        "recent_high_20d": recent_high,
                        "recent_low_20d": recent_low,
                        "current_price": current_price,
                    }

        # 涨跌家数统计
        data["breadth"] = self.fetcher.fetch_market_breadth()

        return data


# ============================================================
# 模块2: 板块强弱排行 (Sector Ranking)
# ============================================================

class SectorRankingGenerator:
    """板块排名分析"""

    def __init__(self, fetcher: ReportDataFetcher):
        self.fetcher = fetcher

    def generate(self) -> Dict[str, Any]:
        data = {
            "industry_top10": [], "industry_bottom10": [],
            "concept_hot": [], "capital_flow_top10": [],
            "rotation_signal": "",
        }

        # 通过东财板块接口获取行业/概念数据
        try:
            # 行业板块涨幅排行
            df_industry = _get_industry_boards()
            if df_industry is not None and len(df_industry) > 0:
                df_industry["涨跌幅"] = pd.to_numeric(df_industry["涨跌幅"], errors="coerce")
                df_industry["成交额"] = pd.to_numeric(df_industry["成交额"], errors="coerce").fillna(0)

                # TOP10涨幅
                top10 = df_industry.sort_values("涨跌幅", ascending=False).head(10)
                for _, row in top10.iterrows():
                    data["industry_top10"].append({
                        "name": str(row.get("板块名称", "")),
                        "pct_change": round(float(row.get("涨跌幅", 0)), 2),
                        "amount": float(row.get("成交额", 0)),
                        "up_count": int(row.get("上涨家数", 0)) if pd.notna(row.get("上涨家数")) else 0,
                    })

                # BOTTOM10跌幅
                bottom10 = df_industry.sort_values("涨跌幅").head(10)
                for _, row in bottom10.iterrows():
                    data["industry_bottom10"].append({
                        "name": str(row.get("板块名称", "")),
                        "pct_change": round(float(row.get("涨跌幅", 0)), 2),
                        "amount": float(row.get("成交额", 0)),
                    })

                # 主力资金净流入TOP10（东财板块主力净额 f62）
                if "主力净流入" in df_industry.columns:
                    df_industry["主力净流入"] = pd.to_numeric(df_industry["主力净流入"], errors="coerce")
                    flow_top = df_industry.sort_values("主力净流入", ascending=False).head(10)
                    for _, row in flow_top.iterrows():
                        net = row.get("主力净流入")
                        if pd.isna(net):
                            continue
                        data["capital_flow_top10"].append({
                            "name": str(row.get("板块名称", "")),
                            "net_inflow_approx": round(float(net) / 1e8, 2),
                            "pct_change": round(float(row.get("涨跌幅", 0)), 2),
                        })

                # 轮动信号：最强vs最弱板块对比
                if data["industry_top10"] and data["industry_bottom10"]:
                    strongest = data["industry_top10"][0]["name"]
                    weakest = data["industry_bottom10"][0]["name"]
                    data["rotation_signal"] = f"资金从「{weakest}」流出，向「{strongest}」集中"

            # 概念板块热度（涨停家数最多的概念）
            df_concept = _get_concept_boards()
            if df_concept is not None and len(df_concept) > 0:
                df_concept["涨跌幅"] = pd.to_numeric(df_concept["涨跌幅"], errors="coerce")
                hot = df_concept.sort_values("涨跌幅", ascending=False).head(10)
                for _, row in hot.iterrows():
                    data["concept_hot"].append({
                        "name": str(row.get("板块名称", "")),
                        "pct_change": round(float(row.get("涨跌幅", 0)), 2),
                        "up_count": int(row.get("上涨家数", 0)) if pd.notna(row.get("上涨家数")) else 0,
                    })

        except Exception as e:
            logger.warning(f"板块数据获取失败(akshare): {e}")

        # 备用：调用sector-rotation模块
        if not data["industry_top10"]:
            try:
                from sector_rotation import SectorRotationAnalyzer, INDUSTRY_SECTORS
                analyzer = SectorRotationAnalyzer()
                results = []
                for name in INDUSTRY_SECTORS[:20]:  # 限制数量节省API配额
                    q = analyzer.fetcher.get_sector_quote(name, is_concept=False)
                    if q["change_pct"] is not None:
                        results.append(q)

                results.sort(key=lambda x: -(x["change_pct"] or 0))
                for r in results[:10]:
                    data["industry_top10"].append({
                        "name": r["name"],
                        "pct_change": round(r["change_pct"], 2),
                        "amount": (r["turnover"] / 1e8) if r["turnover"] else 0,
                    })
            except Exception as e:
                logger.warning(f"sector-rotation模块调用失败: {e}")

        return data


# ============================================================
# 模块3: 市场情绪分析 (Sentiment Analysis)
# ============================================================

class SentimentAnalysisGenerator:
    """市场情绪分析"""

    def __init__(self, fetcher: ReportDataFetcher):
        self.fetcher = fetcher

    def generate(self) -> Dict[str, Any]:
        data = {
            "composite_score": None,
            "sentiment_label": "",
            "fear_greed_index": None,
            "trend_direction": "",
            "limit_up_count": 0,
            "limit_down_count": 0,
            "max_consecutive_board": 0,
            "north_flow": None,
        }

        # 调用market-sentiment模块
        try:
            from market_sentiment import (
                MarketDataFetcher, SentimentIndicators, SentimentReport,
                SENTIMENT_THRESHOLDS
            )
            fetcher = MarketDataFetcher()

            # 获取原始数据
            df_ltd = fetcher.fetch_limit_up_down_history(days=20)
            df_ad = fetcher.fetch_advance_decline_history(days=20)
            df_vol = fetcher.fetch_volume_turnover_history(days=20)
            df_idx = fetcher.fetch_index_history(days=30)

            indicators = SentimentIndicators(fetcher)
            today_str = datetime.now().strftime("%Y-%m-%d")

            # 计算各项指标
            ltd_counts = SentimentIndicators.limit_up_down_count(df_ltd, today_str)
            ad_stats = SentimentIndicators.advance_decline_stats(df_ad, today_str)
            ltd_ratio = SentimentIndicators.limit_up_down_ratio(df_ltd, today_str)
            advance_pct = SentimentIndicators.speed_indicator(
                ad_stats.get("advance", 0), total=5400
            )

            max_board = SentimentIndicators.max_consecutive_limit(df_ltd, today_str)
            premium_rate = SentimentIndicators.yesterday_premium(df_ltd)
            turnover_pctile = SentimentIndicators.turnover_percentile(df_vol)
            volume_change = SentimentIndicators.volume_change_rate(df_vol)

            # 恐惧贪婪指数
            fg_index = SentimentIndicators.fear_greed_index(
                ltd_ratio, advance_pct, turnover_pctile,
                volume_change, max_board, premium_rate
            )

            # 综合评分
            all_indicators = {
                "limit_up_down_ratio": ltd_ratio,
                "advance_decline_ratio": ad_stats["advance"] / max(ad_stats["decline"], 1),
                "limit_up_count": ltd_counts["limit_up"],
                "speed_indicator": advance_pct,
                "market_breadth": advance_pct,
                "max_consecutive_limit": max_board,
                "consecutive_distribution": SentimentIndicators.consecutive_distribution(df_ltd, today_str),
                "yesterday_premium": premium_rate,
                "break_board_rate": SentimentIndicators.break_board_rate(df_ltd, df_ad, today_str),
                "turnover_percentile": turnover_pctile,
                "volume_change_rate": volume_change,
                "volume_ratio_stats": SentimentIndicators.volume_ratio_stats(df_vol),
                "north_flow": indicators.north_flow(),
                "fear_greed_index": fg_index,
                "vix_analog": SentimentIndicators.vix_analog(df_idx),
            }

            composite = SentimentIndicators.composite_score(all_indicators)
            sentiment_info = SentimentIndicators.sentiment_label(composite)

            # 情绪趋势（读取历史数据）
            trend_info = {"direction": "未知", "consecutive_days": 0, "trend_strength": "弱"}
            try:
                hist_file = Path(__file__).parent.parent / "market-sentiment" / "sentiment_data" / "sentiment_history.json"
                if hist_file.exists():
                    with open(hist_file, "r", encoding="utf-8") as f:
                        history = json.load(f)
                    scores = [h.get("composite_score", 50) for h in history[-10:] if "composite_score" in h]
                    if len(scores) >= 2:
                        trend_info = SentimentIndicators.sentiment_trend(scores, window=3)
            except Exception:
                pass

            data["composite_score"] = composite
            data["sentiment_label"] = sentiment_info.get("label", "")
            data["sentiment_emoji"] = sentiment_info.get("emoji", "")
            data["fear_greed_index"] = fg_index
            data["trend_direction"] = trend_info.get("direction", "未知")
            data["trend_strength"] = trend_info.get("trend_strength", "弱")
            data["limit_up_count"] = ltd_counts["limit_up"]
            data["limit_down_count"] = ltd_counts["limit_down"]
            data["max_consecutive_board"] = max_board
            data["north_flow"] = all_indicators.get("north_flow")

        except Exception as e:
            logger.warning(f"market-sentiment模块调用失败: {e}")
            # 降级：仅在有真实涨跌家数时按上涨占比估算，否则标记暂无数据
            breadth = self.fetcher.fetch_market_breadth()
            up, total = breadth.get("up"), breadth.get("total")
            if up is not None and total:
                data["composite_score"] = round(min(100, max(0, up / total * 100)), 1)
                if data["composite_score"] < 30:
                    data["sentiment_label"] = "低迷"
                    data["sentiment_emoji"] = "😔"
                elif data["composite_score"] < 50:
                    data["sentiment_label"] = "温和偏弱"
                    data["sentiment_emoji"] = "😐"
                elif data["composite_score"] < 70:
                    data["sentiment_label"] = "温和偏强"
                    data["sentiment_emoji"] = "🙂"
                else:
                    data["sentiment_label"] = "亢奋"
                    data["sentiment_emoji"] = "🔥"
            else:
                data["sentiment_label"] = "暂无数据"
                data["sentiment_emoji"] = ""

        # 北向资金（如果上面没获取到）
        if data["north_flow"] is None:
            data["north_flow"] = self.fetcher.fetch_north_flow()

        return data


# ============================================================
# 模块4: 异动个股追踪 (Unusual Activity)
# ============================================================

class UnusualActivityGenerator:
    """异动个股追踪"""

    def __init__(self, fetcher: ReportDataFetcher):
        self.fetcher = fetcher

    def generate(self) -> Dict[str, Any]:
        data = {
            "limit_up_stocks": [],
            "volume_breakout": [],
            "dragon_list_top5": [],
            "hot_money_seats": [],
        }

        # 涨停股列表（按板块分类）
        limit_ups = self.fetcher.fetch_limit_up_stocks()
        data["limit_up_stocks"] = limit_ups[:30]

        # 放量突破个股
        breakout = self.fetcher.fetch_volume_breakout()
        data["volume_breakout"] = breakout[:15]

        # 龙虎榜机构净买入TOP5（调用dragon-list模块）
        try:
            from dragon_list import DragonListFetcher, SeatAnalyzer, DragonListStrategy
            dl_fetcher = DragonListFetcher()
            df = dl_fetcher.fetch_today()

            if df is not None and len(df) > 0:
                analyzer = SeatAnalyzer()
                analyzed = analyzer.analyze_seats(df)

                strategy = DragonListStrategy()
                inst_top = strategy.institution_buy(analyzed)
                if inst_top is not None and len(inst_top) > 0:
                    for _, row in inst_top.head(5).iterrows():
                        data["dragon_list_top5"].append({
                            "code": str(row.get("code", "")),
                            "name": str(row.get("name", "")),
                            "pct_change": float(row.get("pct_change", 0)) if pd.notna(row.get("pct_change")) else 0,
                            "net_amount": float(row.get("net_amount", 0)) if pd.notna(row.get("net_amount")) else 0,
                            "buy_seat": str(row.get("seat_buy", "")),
                        })

                # 游资活跃席位
                synergy = strategy.synergy_board(analyzed)
                if synergy is not None and len(synergy) > 0:
                    for _, row in synergy.head(5).iterrows():
                        data["hot_money_seats"].append({
                            "code": str(row.get("code", "")),
                            "name": str(row.get("name", "")),
                            "buyer_count": int(row.get("buyer_count", 0)) if pd.notna(row.get("buyer_count")) else 0,
                        })

        except Exception as e:
            logger.warning(f"dragon-list模块调用失败: {e}")

        return data


# ============================================================
# 模块5: 技术面信号汇总 (Technical Signals)
# ============================================================

class TechnicalSignalsGenerator:
    """技术面信号分析"""

    def __init__(self, fetcher: ReportDataFetcher):
        self.fetcher = fetcher

    def generate(self) -> Dict[str, Any]:
        data = {
            "macd_golden_cross": [],
            "macd_death_cross": [],
            "rsi_overbought": [],
            "rsi_oversold": [],
            "kline_patterns": [],
        }

        # 对权重股进行技术分析
        stock_codes = [s for i, s in enumerate(WEIGHT_STOCKS) if i % 2 == 0]  # 取代码

        for code in stock_codes[:15]:  # 限制数量节省API配额
            try:
                kline_result = self.fetcher.dispatcher.dispatch_kline(code, period="daily")
                if not kline_result["data"] or len(kline_result["data"]) < 30:
                    continue

                df = pd.DataFrame(kline_result["data"])
                for col in ["open", "high", "low", "close"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                if "volume" in df.columns:
                    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)

                df.dropna(subset=["close"], inplace=True)
                if len(df) < 30:
                    continue

                close = df["close"]
                high = df["high"] if "high" in df.columns else close
                low = df["low"] if "low" in df.columns else close

                # MACD信号
                from tech_indicators import calc_macd, calc_rsi
                macd_data = calc_macd(close)
                dif = macd_data["DIF"]
                dea = macd_data["DEA"]

                last_dif = dif.iloc[-1] if not pd.isna(dif.iloc[-1]) else 0
                prev_dif = dif.iloc[-2] if len(dif) > 1 and not pd.isna(dif.iloc[-2]) else 0
                last_dea = dea.iloc[-1] if not pd.isna(dea.iloc[-1]) else 0
                prev_dea = dea.iloc[-2] if len(dea) > 1 and not pd.isna(dea.iloc[-2]) else 0

                # 金叉：DIF从下向上穿越DEA
                if prev_dif <= prev_dea and last_dif > last_dea:
                    data["macd_golden_cross"].append({
                        "code": code,
                        "name": WEIGHT_STOCKS[WEIGHT_STOCKS.index(code) + 1] if (WEIGHT_STOCKS.index(code) + 1) < len(WEIGHT_STOCKS) else "",
                        "dif": round(float(last_dif), 4),
                        "dea": round(float(last_dea), 4),
                    })
                # 死叉：DIF从上向下穿越DEA
                elif prev_dif >= prev_dea and last_dif < last_dea:
                    data["macd_death_cross"].append({
                        "code": code,
                        "name": WEIGHT_STOCKS[WEIGHT_STOCKS.index(code) + 1] if (WEIGHT_STOCKS.index(code) + 1) < len(WEIGHT_STOCKS) else "",
                        "dif": round(float(last_dif), 4),
                        "dea": round(float(last_dea), 4),
                    })

                # RSI信号
                rsi_data = calc_rsi(close, periods=[6, 12, 24])
                rsi6 = rsi_data.get("RSI6", pd.Series([50]))
                last_rsi6 = rsi6.iloc[-1] if not pd.isna(rsi6.iloc[-1]) else 50

                stock_name = WEIGHT_STOCKS[WEIGHT_STOCKS.index(code) + 1] if (WEIGHT_STOCKS.index(code) + 1) < len(WEIGHT_STOCKS) else ""
                if last_rsi6 > 70:
                    data["rsi_overbought"].append({
                        "code": code, "name": stock_name,
                        "rsi6": round(float(last_rsi6), 2),
                    })
                elif last_rsi6 < 30:
                    data["rsi_oversold"].append({
                        "code": code, "name": stock_name,
                        "rsi6": round(float(last_rsi6), 2),
                    })

            except Exception as e:
                logger.debug(f"技术分析失败 [{code}]: {e}")
                continue

        # K线形态识别（对前5只权重股）
        try:
            from kline_patterns import PatternDetector, fetch_kline
            detector = PatternDetector()
            for code in stock_codes[:5]:
                try:
                    df = fetch_kline(code, periods=200)
                    patterns = detector.detect_all(df)
                    if patterns:
                        name = WEIGHT_STOCKS[WEIGHT_STOCKS.index(code) + 1] if (WEIGHT_STOCKS.index(code) + 1) < len(WEIGHT_STOCKS) else ""
                        for p in patterns[:3]:  # 取最近3个形态
                            data["kline_patterns"].append({
                                "code": code,
                                "name": name,
                                "pattern": p.get("pattern", ""),
                                "direction": p.get("direction", ""),
                                "confidence": p.get("confidence", 0),
                                "date": str(p.get("date", "")),
                            })
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"kline-patterns模块调用失败: {e}")

        return data


# ============================================================
# 模块6: 明日展望与策略建议 (Outlook & Strategy)
# ============================================================

class OutlookGenerator:
    """基于综合数据生成明日展望"""

    @staticmethod
    def generate(sentiment: Dict, overview: Dict, sectors: Dict) -> Dict[str, Any]:
        score = sentiment.get("composite_score", 50) or 50
        label = sentiment.get("sentiment_label", "温和")
        trend = sentiment.get("trend_direction", "未知")

        # 操作建议
        if score < 25:
            action_advice = "🥶 冰点区域：市场极度悲观，可积极布局优质标的。关注超跌反弹机会，分批建仓。"
            risk_level = "低（估值底部）"
        elif score < 40:
            action_advice = "😔 低迷区域：情绪偏弱但已接近底部区间。建议观望为主，精选个股逢低吸纳。"
            risk_level = "中低"
        elif score < 60:
            action_advice = "😐 温和区域：多空均衡，正常波动区间。保持现有仓位，适度调仓换股。"
            risk_level = "中等"
        elif score < 80:
            action_advice = "🔥 亢奋区域：做多热情高涨，注意追高风险。建议逐步减仓高位品种，锁定利润。"
            risk_level = "中高"
        else:
            action_advice = "💥 过热区域：情绪极端乐观，警惕回调风险。建议大幅减仓，保留现金等待机会。"
            risk_level = "高（估值顶部）"

        # 趋势修正
        if trend == "上升":
            action_advice += "\n   📈 情绪趋势向上，短期动能偏多。"
        elif trend == "下降":
            action_advice += "\n   📉 情绪趋势向下，注意防守。"

        # 重点关注板块
        focus_sectors = []
        if sectors.get("industry_top10"):
            for s in sectors["industry_top10"][:3]:
                focus_sectors.append(s["name"])

        # 风险提示
        risk_warnings = []
        limit_up = sentiment.get("limit_up_count", 0) or 0
        limit_down = sentiment.get("limit_down_count", 0) or 0
        if limit_down > 50:
            risk_warnings.append(f"⚠️ 今日跌停{limit_down}家，恐慌情绪蔓延")
        if limit_up > 150:
            risk_warnings.append("⚠️ 今日涨停超150家，短期过热信号明显")

        north_flow = sentiment.get("north_flow")
        if north_flow is not None and north_flow < -2000:
            risk_warnings.append(f"⚠️ 北向资金大幅净流出{format_amount(north_flow * 1e6)}")

        # 外围市场提示
        today_weekday = datetime.now().weekday()
        if today_weekday == 4:  # Friday
            risk_warnings.append("📅 周末效应：关注周末政策消息面变化")
        elif today_weekday == 0:  # Monday
            risk_warnings.append("📅 周一开盘：注意外围市场周末消息影响")

        return {
            "action_advice": action_advice,
            "risk_level": risk_level,
            "focus_sectors": focus_sectors,
            "risk_warnings": risk_warnings,
            "score": score,
            "label": label,
            "trend": trend,
        }


# ============================================================
# 报告生成引擎 (Report Generator)
# ============================================================

class ReportGenerator:
    """多格式报告生成器"""

    def __init__(self, date_str: str, output_dir: Path = None):
        self.date_str = date_str
        self.output_dir = output_dir or REPORTS_DIR / date_str
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # --- Markdown报告 ---
    def generate_markdown(self, data: Dict[str, Any], style: str = "detailed") -> str:
        lines = []
        sep = "=" * 60

        lines.append(f"# 📊 A股市场日报 - {self.date_str}")
        lines.append(f"\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"> 报告风格: {'简洁' if style == 'concise' else '详细' if style == 'detailed' else '专业'}")
        lines.append("")

        # === 1. 大盘走势总结 ===
        overview = data.get("overview", {})
        indices = overview.get("indices", {})
        ytd = overview.get("ytd", {})
        breadth = overview.get("breadth", {})
        sr = overview.get("support_resistance", {})

        lines.append(sep)
        lines.append("## 一、大盘走势总结")
        lines.append(sep)
        lines.append("")

        if indices:
            lines.append("| 指数 | 最新价 | 涨跌幅 | 成交量(手) | 成交额(亿) | 年初至今 |")
            lines.append("|------|--------|--------|-----------|----------|---------|")
            for name, info in indices.items():
                price = info.get("price", 0) or 0
                chg = format_pct(info.get("change_pct"))
                vol = f"{(info.get('volume', 0) or 0) / 1e4:.0f}万" if info.get("volume") else "-"
                amt = format_amount(info.get("amount", 0))
                ytd_str = format_pct(ytd.get(name))
                lines.append(f"| {name} | {price:.2f} | {chg} | {vol} | {amt} | {ytd_str} |")
            lines.append("")

        if breadth and breadth.get("total") is not None:
            up = breadth.get("up", 0)
            down = breadth.get("down", 0)
            flat = breadth.get("flat", 0)
            total = breadth.get("total", 0)
            lu = breadth.get("limit_up")
            ld = breadth.get("limit_down")
            lines.append(f"**涨跌家数统计**: 📈上涨 {up}家 | 📉下跌 {down}家 | ➡️平盘 {flat}家 (总计{total}家)")
            if lu or ld:
                lines.append(f"**涨跌停统计**: 🔴涨停 {lu or 0}家 | 🟢跌停 {ld or 0}家")
            lines.append("")
        else:
            lines.append("**涨跌家数统计**: 暂无数据")
            lines.append("")

        # 支撑阻力位（专业模式）
        if style == "professional" and sr:
            lines.append("### 关键支撑/阻力位")
            for name, levels in sr.items():
                cp = levels.get("current_price", 0) or 0
                ma5 = levels.get("ma5", 0) or 0
                ma20 = levels.get("ma20", 0) or 0
                rh = levels.get("recent_high_20d")
                rl = levels.get("recent_low_20d")
                lines.append(f"- **{name}**: MA5={ma5}, MA20={ma20}" +
                           (f", 20日高={rh}" if rh else "") +
                           (f", 20日低={rl}" if rl else ""))
            lines.append("")

        # === 2. 板块强弱排行 ===
        sectors = data.get("sectors", {})
        if style != "concise" or True:  # 简洁模式也显示板块
            lines.append(sep)
            lines.append("## 二、板块强弱排行")
            lines.append(sep)
            lines.append("")

            top_n = 5 if style == "concise" else 10

            if not sectors.get("industry_top10"):
                lines.append("行业板块涨跌排行: 暂无数据")
                lines.append("")

            if sectors.get("industry_top10"):
                lines.append("### 📈 行业板块涨幅TOP{}".format(top_n))
                lines.append("| 排名 | 板块名称 | 涨跌幅 | 成交额(亿) |")
                lines.append("|------|---------|--------|----------|")
                for i, s in enumerate(sectors["industry_top10"][:top_n]):
                    amt = format_amount(s.get("amount", 0))
                    lines.append(f"| {i+1} | {s['name']} | {format_pct(s.get('pct_change'))} | {amt} |")
                lines.append("")

            if sectors.get("industry_bottom10"):
                lines.append("### 📉 行业板块跌幅TOP{}".format(min(top_n, len(sectors["industry_bottom10"]))))
                lines.append("| 排名 | 板块名称 | 涨跌幅 |")
                lines.append("|------|---------|--------|")
                for i, s in enumerate(sectors["industry_bottom10"][:top_n]):
                    lines.append(f"| {i+1} | {s['name']} | {format_pct(s.get('pct_change'))} |")
                lines.append("")

            if sectors.get("concept_hot"):
                lines.append("### 🔥 概念题材热度榜TOP{}".format(top_n))
                lines.append("| 排名 | 概念名称 | 涨跌幅 | 上涨家数 |")
                lines.append("|------|---------|--------|---------|")
                for i, s in enumerate(sectors["concept_hot"][:top_n]):
                    lines.append(f"| {i+1} | {s['name']} | {format_pct(s.get('pct_change'))} | {s.get('up_count', '-')} |")
                lines.append("")

            if sectors.get("capital_flow_top10"):
                lines.append("### 💰 资金净流入TOP{}".format(top_n))
                lines.append("| 排名 | 板块名称 | 净流入(亿) | 涨跌幅 |")
                lines.append("|------|---------|----------|--------|")
                for i, s in enumerate(sectors["capital_flow_top10"][:top_n]):
                    lines.append(f"| {i+1} | {s['name']} | {format_amount(s.get('net_inflow_approx', 0) * 1e8)} | {format_pct(s.get('pct_change'))} |")
                lines.append("")

            if sectors.get("rotation_signal"):
                lines.append(f"**🔄 板块轮动信号**: {sectors['rotation_signal']}")
                lines.append("")

        # === 3. 市场情绪分析 ===
        sentiment = data.get("sentiment", {})
        lines.append(sep)
        lines.append("## 三、市场情绪分析")
        lines.append(sep)
        lines.append("")

        score = sentiment.get("composite_score", "-") or "-"
        label = sentiment.get("sentiment_label", "")
        emoji = sentiment.get("sentiment_emoji", "😐")
        fg = sentiment.get("fear_greed_index")
        trend_dir = sentiment.get("trend_direction", "未知")

        lines.append(f"**综合情绪评分**: {'暂无数据' if score == '-' else f'{score}分'} ({emoji}{label})")
        if fg is not None:
            fg_label = "极度恐惧" if fg < 20 else ("恐惧" if fg < 40 else ("中性" if fg < 60 else ("贪婪" if fg < 80 else "极度贪婪")))
            lines.append(f"**恐惧贪婪指数**: {fg} ({fg_label})")
        lines.append(f"**情绪趋势**: {trend_dir}")
        lines.append("")

        lu = sentiment.get("limit_up_count", 0) or 0
        ld = sentiment.get("limit_down_count", 0) or 0
        mc = sentiment.get("max_consecutive_board", 0) or 0
        nf = sentiment.get("north_flow")

        lines.append(f"- 📊 涨停家数: {lu} | 跌停家数: {ld}")
        lines.append(f"- 🔗 最高连板: {mc}天")
        if nf is not None:
            direction_str = "净流入" if nf > 0 else ("净流出" if nf < 0 else "持平")
            lines.append(f"- 🌊 北向资金 {direction_str}: {format_amount(abs(nf) * 1e6)}")
        else:
            lines.append("- 🌊 北向资金: 暂无数据")
        lines.append("")

        # === 4. 异动个股追踪 ===
        activity = data.get("activity", {})
        if style != "concise":
            lines.append(sep)
            lines.append("## 四、异动个股追踪")
            lines.append(sep)
            lines.append("")

            if activity.get("limit_up_stocks"):
                # 按板块分类
                by_sector = {}
                for s in activity["limit_up_stocks"]:
                    sec = s.get("sector", "其他") or "其他"
                    by_sector.setdefault(sec, []).append(s)

                lines.append(f"### 🚀 今日涨停股 ({len(activity['limit_up_stocks'])}家)")
                top_sectors = sorted(by_sector.items(), key=lambda x: -len(x[1]))[:5]
                for sec_name, stocks in top_sectors:
                    stock_strs = [f"{s.get('name', s.get('code', ''))}" for s in stocks[:8]]
                    lines.append(f"- **{sec_name}** ({len(stocks)}家): {', '.join(stock_strs)}")
                lines.append("")
            else:
                lines.append("### 🚀 今日涨停股: 暂无数据")
                lines.append("")

            if activity.get("volume_breakout"):
                lines.append("### 📊 放量突破个股（量比>3）")
                lines.append("| 代码 | 名称 | 涨跌幅 | 量比 |")
                lines.append("|------|------|--------|-----|")
                for s in activity["volume_breakout"][:10]:
                    lines.append(f"| {s.get('code', '')} | {s.get('name', '')} | {format_pct(s.get('pct_change'))} | {s.get('volume_ratio', 0):.2f} |")
                lines.append("")

            if activity.get("dragon_list_top5"):
                lines.append("### 🏆 龙虎榜机构净买入TOP5")
                lines.append("| 代码 | 名称 | 涨跌幅 | 净买入(万) | 买出席位 |")
                lines.append("|------|------|--------|----------|---------|")
                for s in activity["dragon_list_top5"]:
                    net_wan = (s.get("net_amount", 0) / 1e4) if s.get("net_amount") else 0
                    lines.append(f"| {s['code']} | {s['name']} | {format_pct(s.get('pct_change'))} | {format_amount(net_wan * 1e4)} | {s.get('buy_seat', '-')} |")
                lines.append("")

        # === 5. 技术面信号汇总（专业模式）===
        tech = data.get("tech_signals", {})
        if style == "professional" and (tech.get("macd_golden_cross") or tech.get("rsi_overbought") or tech.get("kline_patterns")):
            lines.append(sep)
            lines.append("## 五、技术面信号汇总")
            lines.append(sep)
            lines.append("")

            if tech.get("macd_golden_cross"):
                stocks = [f"{s.get('name', s.get('code', ''))}" for s in tech["macd_golden_cross"]]
                lines.append(f"### 📈 MACD金叉权重股: {', '.join(stocks) if stocks else '无'}")

            if tech.get("macd_death_cross"):
                stocks = [f"{s.get('name', s.get('code', ''))}" for s in tech["macd_death_cross"]]
                lines.append(f"### 📉 MACD死叉权重股: {', '.join(stocks) if stocks else '无'}")

            if tech.get("rsi_overbought"):
                stocks = [f"{s.get('name', s.get('code', ''))}(RSI={s.get('rsi6', 0)})" for s in tech["rsi_overbought"]]
                lines.append(f"### ⚠️ RSI超买(>70): {', '.join(stocks) if stocks else '无'}")

            if tech.get("rsi_oversold"):
                stocks = [f"{s.get('name', s.get('code', ''))}(RSI={s.get('rsi6', 0)})" for s in tech["rsi_oversold"]]
                lines.append(f"### 💡 RSI超卖(<30): {', '.join(stocks) if stocks else '无'}")

            if tech.get("kline_patterns"):
                lines.append("")
                lines.append("### 🕯️ K线形态识别")
                for p in tech["kline_patterns"][:10]:
                    direction_emoji = "📈" if p.get("direction", "").lower() in ["bullish", "看多", "多头"] else ("📉" if p.get("direction", "").lower() in ["bearish", "看空", "空头"] else "➡️")
                    lines.append(f"- {direction_emoji} **{p.get('name', p.get('code', ''))}**: {p.get('pattern', '')} (置信度:{p.get('confidence', 0):.1%}) [{p.get('date', '')}]")
            lines.append("")

        # === 6. 明日展望与策略建议 ===
        outlook = data.get("outlook", {})
        lines.append(sep)
        lines.append("## 六、明日展望与策略建议")
        lines.append(sep)
        lines.append("")

        if outlook.get("action_advice"):
            for line in outlook["action_advice"].split("\n"):
                lines.append(line)
            lines.append("")

        lines.append(f"**风险等级**: {outlook.get('risk_level', '中等')}")
        lines.append("")

        if outlook.get("focus_sectors"):
            lines.append(f"**🎯 重点关注板块**: {', '.join(outlook['focus_sectors'])}")
            lines.append("")

        if outlook.get("risk_warnings"):
            lines.append("**⚠️ 风险提示**:")
            for w in outlook["risk_warnings"]:
                lines.append(f"- {w}")
            lines.append("")

        # Footer
        lines.append("---")
        lines.append(f"*本报告由A股自动化日报系统生成，仅供参考，不构成投资建议。*")
        lines.append(f"*数据更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        return "\n".join(lines)

    # --- HTML报告 ---
    def generate_html(self, data: Dict[str, Any], style: str = "detailed") -> str:
        md_content = self.generate_markdown(data, style=style)

        # 简单的Markdown到HTML转换（内嵌样式）
        html_parts = []
        html_parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股市场日报 - """ + self.date_str + """</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; color: #333; line-height: 1.6; padding: 20px; }
  .container { max-width: 960px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); padding: 40px; }
  h1 { text-align: center; color: #1a1a2e; font-size: 28px; margin-bottom: 8px; border-bottom: 3px solid #e74c3c; padding-bottom: 16px; }
  .subtitle { text-align: center; color: #888; font-size: 14px; margin-bottom: 30px; }
  h2 { color: #2c3e50; font-size: 20px; margin: 30px 0 15px; padding-left: 12px; border-left: 4px solid #e74c3c; }
  h3 { color: #34495e; font-size: 16px; margin: 20px 0 10px; }
  table { width: 100%; border-collapse: collapse; margin: 10px 0 20px; font-size: 14px; }
  th { background: #f8f9fa; color: #555; padding: 10px 12px; text-align: left; border-bottom: 2px solid #dee2e6; font-weight: 600; }
  td { padding: 8px 12px; border-bottom: 1px solid #eee; }
  tr:hover { background: #f8f9fa; }
  .positive { color: #e74c3c; font-weight: 600; }
  .negative { color: #27ae60; font-weight: 600; }
  blockquote { border-left: 4px solid #ddd; padding: 10px 15px; margin: 10px 0; background: #f8f9fa; border-radius: 0 4px 4px 0; color: #666; }
  strong { color: #2c3e50; }
  .score-box { text-align: center; padding: 20px; margin: 15px 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px; color: #fff; }
  .score-box .score { font-size: 48px; font-weight: 700; }
  .score-box .label { font-size: 18px; margin-top: 5px; }
  ul, ol { padding-left: 24px; margin: 10px 0; }
  li { margin: 4px 0; }
  hr { border: none; border-top: 1px solid #eee; margin: 30px 0; }
  .footer { text-align: center; color: #999; font-size: 12px; margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; }
</style>
</head>
<body>
<div class="container">
""")

        # Convert markdown to HTML (simple conversion)
        for line in md_content.split("\n"):
            if line.startswith("# "):
                html_parts.append(f"<h1>{self._md_to_html(line[2:])}</h1>")
            elif line.startswith("## "):
                html_parts.append(f"<h2>{self._md_to_html(line[3:])}</h2>")
            elif line.startswith("### "):
                html_parts.append(f"<h3>{self._md_to_html(line[4:])}</h3>")
            elif line.startswith("> "):
                html_parts.append(f"<blockquote>{self._md_to_html(line[2:])}</blockquote>")
            elif line.startswith("|") and "---" not in line:
                # Table handling done below
                pass
            elif line.startswith("---"):
                html_parts.append("<hr>")
            elif line.startswith("*"):
                content = line.strip("* ")
                html_parts.append(f"<p class='footer'>{self._md_to_html(content)}</p>")
            elif line.startswith("- "):
                html_parts.append(f"<li>{self._md_to_html(line[2:])}</li>")
            elif line.startswith("**") and line.endswith("**"):
                html_parts.append(f"<p><strong>{self._md_to_html(line.strip('* '))}</strong></p>")
            elif line.strip():
                html_parts.append(f"<p>{self._md_to_html(line)}</p>")

        # Handle tables (re-process)
        table_blocks = self._extract_tables(md_content)
        for tbl in table_blocks:
            html_table = "<table>\n"
            rows = tbl.split("\n")
            for i, row in enumerate(rows):
                cells = [c.strip() for c in row.split("|") if c.strip()]
                if i == 0:
                    html_table += "  <tr>" + "".join(f"<th>{self._color_pct(c)}</th>" for c in cells) + "</tr>\n"
                elif i == 1 and all(all(ch in '-|' for ch in cell) for cell in cells):
                    continue  # separator row
                else:
                    html_table += "  <tr>" + "".join(f"<td>{self._color_pct(c)}</td>" for c in cells) + "</tr>\n"
            html_table += "</table>\n"

        # Insert tables back (replace placeholder approach - just append at end of relevant sections)
        # For simplicity, we'll rebuild the HTML with proper table insertion
        final_html = self._build_full_html(md_content, data)

        html_parts.append("""</div>
</body>
</html>""")

        return final_html if final_html else "\n".join(html_parts)

    def _build_full_html(self, md_content: str, data: Dict[str, Any]) -> str:
        """Build complete HTML with proper table rendering"""
        html = []
        in_table = False
        table_rows = []

        lines = md_content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]

            # Table detection
            if line.startswith("|") and "---" not in line:
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if not in_table:
                    html.append("<table>")
                    html.append(f"  <tr>{''.join(f'<th>{self._color_pct(c)}</th>' for c in cells)}</tr>")
                    in_table = True
                else:
                    html.append(f"  <tr>{''.join(f'<td>{self._color_pct(c)}</td>' for c in cells)}</tr>")
                i += 1
                # Skip separator row
                if i < len(lines) and lines[i].startswith("|") and all(all(ch in '-| ' for ch in cell.strip()) for cell in lines[i].split("|")):
                    i += 1
                continue
            elif in_table:
                html.append("</table>")
                in_table = False

            # Regular markdown conversion
            if line.startswith("# "):
                html.append(f"<h1>{self._md_to_html(line[2:])}</h1>")
            elif line.startswith("## "):
                html.append(f"<h2>{self._md_to_html(line[3:])}</h2>")
            elif line.startswith("### "):
                html.append(f"<h3>{self._md_to_html(line[4:])}</h3>")
            elif line.startswith("> "):
                html.append(f"<blockquote>{self._md_to_html(line[2:])}</blockquote>")
            elif line.startswith("---"):
                html.append("<hr>")
            elif line.startswith("*") and not line.startswith("**"):
                content = line.strip("* ")
                html.append(f"<p class='footer'>{self._md_to_html(content)}</p>")
            elif line.startswith("- "):
                html.append(f"<li>{self._md_to_html(line[2:])}</li>")
            elif line.startswith("**") and line.endswith("**"):
                html.append(f"<p><strong>{self._md_to_html(line.strip('* '))}</strong></p>")
            elif line.strip():
                html.append(f"<p>{self._md_to_html(line)}</p>")

            i += 1

        if in_table:
            html.append("</table>")

        # Wrap in HTML document
        sentiment = data.get("sentiment", {})
        score = sentiment.get("composite_score", "-") or "-"
        label = sentiment.get("sentiment_label", "")
        emoji = sentiment.get("sentiment_emoji", "😐")

        full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股市场日报 - {self.date_str}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; color: #333; line-height: 1.6; padding: 20px; }}
  .container {{ max-width: 960px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); padding: 40px; }}
  h1 {{ text-align: center; color: #1a1a2e; font-size: 28px; margin-bottom: 8px; border-bottom: 3px solid #e74c3c; padding-bottom: 16px; }}
  .subtitle {{ text-align: center; color: #888; font-size: 14px; margin-bottom: 30px; }}
  h2 {{ color: #2c3e50; font-size: 20px; margin: 30px 0 15px; padding-left: 12px; border-left: 4px solid #e74c3c; }}
  h3 {{ color: #34495e; font-size: 16px; margin: 20px 0 10px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 10px 0 20px; font-size: 14px; }}
  th {{ background: #f8f9fa; color: #555; padding: 10px 12px; text-align: left; border-bottom: 2px solid #dee2e6; font-weight: 600; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; }}
  tr:hover {{ background: #f8f9fa; }}
  .positive {{ color: #e74c3c; font-weight: 600; }}
  .negative {{ color: #27ae60; font-weight: 600; }}
  blockquote {{ border-left: 4px solid #ddd; padding: 10px 15px; margin: 10px 0; background: #f8f9fa; border-radius: 0 4px 4px 0; color: #666; }}
  strong {{ color: #2c3e50; }}
  ul, ol {{ padding-left: 24px; margin: 10px 0; }}
  li {{ margin: 4px 0; }}
  hr {{ border: none; border-top: 1px solid #eee; margin: 30px 0; }}
  .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; }}
</style>
</head>
<body>
<div class="container">
""" + "\n".join(html) + """
</div>
</body>
</html>"""
        return full_html

    def _md_to_html(self, text: str) -> str:
        """Simple markdown to HTML conversion for inline elements"""
        # Bold
        text = text.replace("**", "<strong>")  # Will need closing tags
        parts = text.split("<strong>")
        if len(parts) > 1:
            result_parts = [parts[0]]
            for p in parts[1:]:
                idx = p.find("<strong>")
                if idx >= 0:
                    result_parts.append(f"<strong>{p[:idx]}</strong>{p[idx:]}")
                else:
                    result_parts.append(f"<strong>{p}</strong>")
            text = "".join(result_parts)
        return text

    def _color_pct(self, val: str) -> str:
        """Add color class to percentage values"""
        import re
        m = re.match(r'^([+-]?\d+\.?\d*)%$', val.strip())
        if m:
            num = float(m.group(1))
            cls = "positive" if num > 0 else ("negative" if num < 0 else "")
            return f'<span class="{cls}">{val}</span>' if cls else val
        return val

    def _extract_tables(self, text: str) -> List[str]:
        """Extract markdown tables from text"""
        tables = []
        current_table = []
        for line in text.split("\n"):
            if line.startswith("|"):
                current_table.append(line)
            else:
                if len(current_table) >= 3:  # header + separator + at least one row
                    tables.append("\n".join(current_table))
                current_table = []
        if len(current_table) >= 3:
            tables.append("\n".join(current_table))
        return tables

    # --- JSON报告 ---
    def generate_json(self, data: Dict[str, Any]) -> str:
        """生成JSON结构化数据"""
        output = {
            "report_date": self.date_str,
            "generated_at": datetime.now().isoformat(),
            "data_source": "a-share-daily-report",
            "sections": {
                "market_overview": data.get("overview", {}),
                "sector_ranking": data.get("sectors", {}),
                "sentiment_analysis": data.get("sentiment", {}),
                "unusual_activity": data.get("activity", {}),
                "technical_signals": data.get("tech_signals", {}),
                "outlook_strategy": data.get("outlook", {}),
            }
        }
        return json.dumps(output, ensure_ascii=False, indent=2, default=str)

    # --- 保存报告 ---
    def save(self, content: str, fmt: str) -> Path:
        """保存报告文件"""
        ext_map = {"markdown": ".md", "html": ".html", "json": ".json"}
        filepath = self.output_dir / f"daily_report_{self.date_str}{ext_map.get(fmt, '.txt')}"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath


# ============================================================
# 主报告引擎 (Main Report Engine)
# ============================================================

class DailyReportEngine:
    """日报生成主引擎"""

    def __init__(self, date_str: str = None, style: str = "detailed",
                 output_dir: Path = None, force_refresh: bool = False):
        self.date_str = parse_date(date_str)
        self.style = style  # concise / detailed / professional
        self.output_dir = output_dir or REPORTS_DIR
        self.force_refresh = force_refresh

    def run(self) -> Dict[str, Any]:
        """执行完整的报告生成流程"""
        print(f"\n{'='*60}")
        print(f"📊 A股自动化日报 - {self.date_str}")
        print(f"⏰ 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🎨 报告风格: {'简洁' if self.style == 'concise' else '详细' if self.style == 'detailed' else '专业'}")
        print(f"{'='*60}\n")

        # 交易日检查
        report_date = datetime.strptime(self.date_str, "%Y-%m-%d")
        if not is_trading_day(report_date):
            print("⚠️ 今日非交易日，跳过报告生成。")
            return {}

        fetcher = ReportDataFetcher(force_refresh=self.force_refresh)

        # 并行收集各模块数据（顺序执行但独立）
        data = {}

        # 1. 大盘走势总结
        print("📈 [1/6] 获取大盘走势数据...")
        try:
            overview_gen = MarketOverviewGenerator(fetcher)
            data["overview"] = overview_gen.generate()
            indices = data["overview"].get("indices", {})
            for name, info in indices.items():
                chg = format_pct(info.get("change_pct"))
                print(f"   {name}: {chg}")
        except Exception as e:
            print(f"   ❌ 大盘数据获取失败: {e}")
            data["overview"] = {}

        # 2. 板块强弱排行
        print("\n🏆 [2/6] 分析板块强弱...")
        try:
            sector_gen = SectorRankingGenerator(fetcher)
            data["sectors"] = sector_gen.generate()
            top = data["sectors"].get("industry_top10", [])
            if top:
                print(f"   📈 最强板块: {top[0]['name']} ({format_pct(top[0].get('pct_change'))})")
        except Exception as e:
            print(f"   ❌ 板块数据获取失败: {e}")
            data["sectors"] = {}

        # 3. 市场情绪分析
        print("\n🧠 [3/6] 计算市场情绪...")
        try:
            sentiment_gen = SentimentAnalysisGenerator(fetcher)
            data["sentiment"] = sentiment_gen.generate()
            score = data["sentiment"].get("composite_score", "-") or "-"
            label = data["sentiment"].get("sentiment_label", "")
            emoji = data["sentiment"].get("sentiment_emoji", "😐")
            print(f"   综合评分: {score}分 ({emoji}{label})")
        except Exception as e:
            print(f"   ❌ 情绪分析失败: {e}")
            data["sentiment"] = {}

        # 4. 异动个股追踪
        print("\n🔍 [4/6] 追踪异动个股...")
        try:
            activity_gen = UnusualActivityGenerator(fetcher)
            data["activity"] = activity_gen.generate()
            lu_count = len(data["activity"].get("limit_up_stocks", []))
            print(f"   🚀 涨停股: {lu_count}家")
        except Exception as e:
            print(f"   ❌ 异动追踪失败: {e}")
            data["activity"] = {}

        # 5. 技术面信号汇总（仅专业模式）
        if self.style == "professional":
            print("\n📐 [5/6] 扫描技术面信号...")
            try:
                tech_gen = TechnicalSignalsGenerator(fetcher)
                data["tech_signals"] = tech_gen.generate()
                gc = len(data["tech_signals"].get("macd_golden_cross", []))
                dc = len(data["tech_signals"].get("macd_death_cross", []))
                print(f"   MACD金叉: {gc}只 | 死叉: {dc}只")
            except Exception as e:
                print(f"   ❌ 技术信号扫描失败: {e}")
                data["tech_signals"] = {}
        else:
            data["tech_signals"] = {}

        # 6. 明日展望与策略建议
        print("\n🔮 [6/6] 生成明日展望...")
        try:
            outlook = OutlookGenerator.generate(
                data.get("sentiment", {}),
                data.get("overview", {}),
                data.get("sectors", {})
            )
            data["outlook"] = outlook
            print(f"   风险等级: {outlook.get('risk_level', '中等')}")
        except Exception as e:
            print(f"   ❌ 展望生成失败: {e}")
            data["outlook"] = {}

        return data


# ============================================================
# CLI入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="A股自动化日报生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python daily_report.py                          # 今日报告(详细模式)
  python daily_report.py --style concise          # 简洁版
  python daily_report.py --style professional     # 专业版+技术信号
  python daily_report.py --date 2026-06-23        # 指定日期回查
  python daily_report.py --format all             # 全部格式输出
  python daily_report.py --cronjob                # 定时任务模式(静默)
        """
    )

    parser.add_argument("--date", type=str, default=None, help="报告日期 (YYYY-MM-DD)，默认今日")
    parser.add_argument("--style", choices=["concise", "detailed", "professional"],
                        default="detailed", help="报告风格: concise(简洁)/detailed(详细)/professional(专业)")
    parser.add_argument("--format", dest="output_format", choices=["markdown", "html", "json", "all"],
                        default="all", help="输出格式")
    parser.add_argument("--output", type=str, default=None, help="报告保存目录")
    parser.add_argument("--force-refresh", action="store_true", help="强制刷新所有数据（不走缓存）")
    parser.add_argument("--cronjob", action="store_true", help="定时任务模式（静默运行，仅生成文件）")

    args = parser.parse_args()

    # 交易日检查
    report_date_str = parse_date(args.date)
    report_date = datetime.strptime(report_date_str, "%Y-%m-%d")
    if not is_trading_day(report_date):
        if not args.cronjob:
            print(f"⚠️ {report_date_str} 非交易日，跳过报告生成。")
        return

    # 创建引擎
    output_dir = Path(args.output) if args.output else None
    engine = DailyReportEngine(
        date_str=args.date,
        style=args.style,
        output_dir=output_dir,
        force_refresh=args.force_refresh,
    )

    # 生成数据
    data = engine.run()
    if not data:
        return

    # 创建报告生成器
    reporter = ReportGenerator(report_date_str, output_dir)

    # 生成并保存各格式
    formats = ["markdown", "html", "json"] if args.output_format == "all" else [args.output_format]

    for fmt in formats:
        try:
            if fmt == "markdown":
                content = reporter.generate_markdown(data, style=args.style)
                filepath = reporter.save(content, "markdown")
                if not args.cronjob:
                    print(f"\n✅ Markdown报告已保存: {filepath}")
            elif fmt == "html":
                content = reporter.generate_html(data, style=args.style)
                filepath = reporter.save(content, "html")
                if not args.cronjob:
                    print(f"✅ HTML报告已保存: {filepath}")
            elif fmt == "json":
                content = reporter.generate_json(data)
                filepath = reporter.save(content, "json")
                if not args.cronjob:
                    print(f"✅ JSON数据已保存: {filepath}")

        except Exception as e:
            print(f"❌ 生成{fmt}格式失败: {e}")

    # 终端输出简洁版摘要（非cronjob模式）
    if not args.cronjob and "markdown" in formats:
        md = reporter.generate_markdown(data, style="concise")
        print("\n" + "=" * 60)
        print("📋 报告摘要:")
        print("=" * 60)
        # 只打印前40行作为预览
        preview_lines = md.split("\n")[:50]
        for line in preview_lines:
            if line.strip():
                print(line)

    if not args.cronjob:
        print(f"\n{'='*60}")
        print("✅ 日报生成完成！")
        print(f"📁 报告目录: {reporter.output_dir}")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
