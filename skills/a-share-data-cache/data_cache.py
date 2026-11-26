#!/usr/bin/env python3
"""
a-share-data-cache - A股多源数据调度引擎（无缓存版）

核心功能:
- pytdx通达信(最高优先级，无限制+毫秒级) → 东财直连 → 新浪 → 腾讯
- 纯实时获取，零缓存开销
"""

import os
import random
import sys
import threading
import json
import time
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union

# 东财限流器（防封禁铁律：串行、间隔≥1s+随机抖动）
_EM_LOCK = threading.Lock()
_EM_LAST_REQUEST = {"_time": 0.0}
_EM_MIN_INTERVAL = float(os.environ.get("EM_MIN_INTERVAL", "1.2"))

def _em_throttle():
    """东财串行限流: 间隔≥_EM_MIN_INTERVAL + 随机抖动"""
    with _EM_LOCK:
        now = time.time()
        elapsed = now - _EM_LAST_REQUEST["_time"]
        if elapsed < _EM_MIN_INTERVAL:
            sleep_time = _EM_MIN_INTERVAL - elapsed + random.uniform(0.3, 1.5)
            time.sleep(sleep_time)
        _EM_LAST_REQUEST["_time"] = time.time()

def _em_get(url, params=None, headers=None, timeout=15):
    """东财统一请求入口，内置限流"""
    import requests as req
    merged_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.eastmoney.com/",
    }
    if headers:
        merged_headers.update(headers)
    _em_throttle()
    return req.get(url, params=params, headers=merged_headers, timeout=timeout)

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore

from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================
# 数据源枚举
# ============================================================

class DataSource(Enum):
    PYTDX = "pytdx"         # 通达信行情接口（无限制+毫秒级）⭐最高优先级
    AKSHARE = "akshare"     # AKShare开源库（无限制）
    SINA = "sina"           # 新浪财经API（无限制）
    TENCENT = "tencent"     # 腾讯财经API（无限制）


# ============================================================
# DataFetcher - 四源数据获取器
# ============================================================

class DataFetcher:
    """四源并行数据获取：pytdx/东财直连/新浪/腾讯"""

    _PYTDX_API = None
    _PYTDX_CONNECTED = False

    # --- 新浪财经 API ---
    SINA_HQ_URL = "http://hq.sinajs.cn/list={symbols}"
    SINA_KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={datalen}"
    SINA_HEADERS = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }

    # --- 腾讯财经 API ---
    TENCENT_HQ_URL = "http://qt.gtimg.cn/q={symbols}"
    TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},{period},,,{count},qfq"
    TENCENT_BOARD_URL = "http://data.gtimg.cn/flashdata/hushen/latest/board.txt"
    TENCENT_HEADERS = {
        "Referer": "https://finance.qq.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }

    # --- pytdx 通达信行情接口（无限制）⭐新增 ---
    @classmethod
    def _get_pytdx_api(cls):
        """获取pytdx API实例，自动连接最优服务器"""
        if cls._PYTDX_API is None or not cls._PYTDX_CONNECTED:
            try:
                from pytdx.hq import TdxHq_API
                api = TdxHq_API()
                
                servers = [
                    ("119.147.212.81", 7709),   # 深圳-主力
                    ("14.17.75.50", 7709),       # 上海-主力
                    ("112.74.214.43", 7727),     # 备用1
                    ("218.75.126.9", 7727),      # 备用2
                ]
                
                best_ip, best_port = None, None
                best_time = float('inf')
                
                for ip, port in servers:
                    try:
                        start = time.time()
                        api.connect(ip, port)
                        elapsed = (time.time() - start) * 1000
                        if elapsed < best_time:
                            best_time = elapsed
                            best_ip, best_port = ip, port
                        api.disconnect()
                    except:
                        continue
                
                if best_ip:
                    api.connect(best_ip, best_port)
                    cls._PYTDX_API = api
                    cls._PYTDX_CONNECTED = True
                    logger.info(f"pytdx connected to {best_ip}:{best_port} ({best_time:.0f}ms)")
                else:
                    logger.warning("pytdx: all servers unreachable")
            except ImportError:
                logger.warning("pytdx not installed, skipping pytdx data source")
            except Exception as e:
                logger.warning(f"pytdx connection failed: {e}")
        
        return cls._PYTDX_API if cls._PYTDX_CONNECTED else None

    @staticmethod
    def _code_to_market(code: str) -> int:
        """股票代码转市场代码：0=上海, 1=深圳"""
        code_str = str(code)
        if code_str.startswith(('6', '9')):
            return 0  # 上海
        elif code_str.startswith(('0', '3')):
            return 1  # 深圳
        else:
            return 0

    def fetch_pytdx_quote(self, symbols: List[str]) -> Optional[Dict[str, Any]]:
        """pytdx通达信实时行情（无限制）⭐新增"""
        api = self._get_pytdx_api()
        if not api:
            return None
        
        try:
            pytdx_symbols = []
            for sym in symbols:
                market = self._code_to_market(sym)
                pytdx_symbols.append((market, str(sym)))
            
            if not pytdx_symbols:
                return None
            
            results = {}
            for i in range(0, len(pytdx_symbols), 800):
                batch = pytdx_symbols[i:i+800]
                quotes = api.get_security_quotes(batch)
                
                if quotes:
                    for q in quotes:
                        code = str(q.get('code', ''))
                        results[code] = {
                            "name": q.get('instrument_name', ''),
                            "price": q.get('price'),
                            "prev_close": q.get('last_close'),
                            "open": q.get('open_price'),
                            "high": q.get('high_price'),
                            "low": q.get('low_price'),
                            "volume": q.get('volume', 0),
                            "amount": q.get('money', 0),
                            "bid1": q.get('bid1'),
                            "ask1": q.get('ask1'),
                        }
                        pc = results[code]["prev_close"]
                        p = results[code]["price"]
                        if pc and p:
                            results[code]["change_pct"] = round((p - pc) / pc * 100, 2)
            
            return results if results else None
        except Exception as e:
            logger.warning(f"pytdx quote fetch failed: {e}")
            self._PYTDX_CONNECTED = False
            return None

    def fetch_pytdx_kline(self, symbol: str, period: str = "daily", 
                          count: int = 100) -> Optional[List[Dict]]:
        """pytdx通达信历史K线（支持日/周/月/5/15/30/60分钟）⭐新增"""
        api = self._get_pytdx_api()
        if not api:
            return None
        
        try:
            market = self._code_to_market(symbol)
            
            period_map = {
                'daily': 8,      # K线日K数据
                'weekly': 32,    # K线周K数据  
                'monthly': 16,   # K线月K数据
            }
            
            category = period_map.get(period, 8)
            
            if period.startswith('min'):
                minutes = int(period.replace('min', ''))
                data = api.get_history_minute_time_data(market, str(symbol), 
                                                        unit=minutes * 60, count=count)
            else:
                data = api.get_security_bars(category, market, str(symbol), start=0, count=count)
            
            if not data:
                return None
            
            klines = []
            for bar in data:
                klines.append({
                    "date": bar.get('datetime', ''),
                    "open": bar.get('open'),
                    "close": bar.get('close'),
                    "high": bar.get('high'),
                    "low": bar.get('low'),
                    "volume": bar.get('vol', 0),
                })
            
            return klines if klines else None
        except Exception as e:
            logger.warning(f"pytdx kline fetch failed for {symbol}: {e}")
            self._PYTDX_CONNECTED = False
            return None

    def fetch_pytdx_transaction(self, symbol: str, count: int = 100) -> Optional[List[Dict]]:
        """pytdx通达信分笔成交数据（Level-1逐笔）⭐新增"""
        api = self._get_pytdx_api()
        if not api:
            return None
        
        try:
            market = self._code_to_market(symbol)
            
            stats = api.get_traffic_stats(market, str(symbol))
            total_count = stats.get('count', count) if stats else count
            
            data = api.get_transaction_data(market, str(symbol), 
                                            start=max(0, total_count - count), count=count)
            
            if not data:
                return None
            
            ticks = []
            for tick in data:
                ticks.append({
                    "time": tick.get('time'),
                    "price": tick.get('price'),
                    "volume": tick.get('vol', 0),
                    "direction": tick.get('type', ''),
                    "amount": tick.get('money', 0),
                })
            
            return ticks if ticks else None
        except Exception as e:
            logger.warning(f"pytdx transaction fetch failed for {symbol}: {e}")
            self._PYTDX_CONNECTED = False
            return None

    # --- HTTP请求工具 ---
    def __init__(self):
        self.session = None
        try:
            import requests as req
            self.session = req.Session()
            self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        except ImportError:
            logger.warning("requests not installed, using urllib")

    def _http_get(self, url: str, headers: Optional[Dict] = None, timeout: int = 15,
                  encoding: str = "utf-8") -> Optional[str]:
        """HTTP GET请求"""
        try:
            if self.session:
                resp = self.session.get(url, headers=headers or {}, timeout=timeout)
                resp.encoding = "gbk" if "sina" in url else encoding
                if resp.status_code == 200:
                    return resp.text
            else:
                import urllib.request
                req_obj = urllib.request.Request(url, headers=headers or {})
                with urllib.request.urlopen(req_obj, timeout=timeout) as resp:
                    data = resp.read()
                    enc = "gbk" if "sina" in url else encoding
                    return data.decode(enc, errors="replace")
        except Exception as e:
            logger.debug(f"HTTP GET failed for {url}: {e}")
        return None

    # --- 新浪数据源 ---
    def fetch_sina_quote(self, symbols: List[str]) -> Optional[Dict[str, Any]]:
        """新浪财经实时行情"""
        sina_symbols = ",".join(symbols)
        url = self.SINA_HQ_URL.format(symbols=sina_symbols)
        raw = self._http_get(url, headers=self.SINA_HEADERS)
        if not raw:
            return None

        results = {}
        for line in raw.strip().split("\n"):
            m = re.match(r'var hq_str_(\w+)="(.*)";', line)
            if not m:
                continue
            sym_code = m.group(1)
            parts = m.group(2).split(",")
            if len(parts) < 32:
                continue

            try:
                results[sym_code] = {
                    "name": parts[0],
                    "open": float(parts[1]) if parts[1] else None,
                    "prev_close": float(parts[2]) if parts[2] else None,
                    "price": float(parts[3]) if parts[3] else None,
                    "high": float(parts[4]) if parts[4] else None,
                    "low": float(parts[5]) if parts[5] else None,
                    "volume": int(parts[8]) if parts[8] else None,
                    "amount": float(parts[9]) if parts[9] else None,
                }
                pc = results[sym_code]["prev_close"]
                p = results[sym_code]["price"]
                if pc and p:
                    results[sym_code]["change_pct"] = round((p - pc) / pc * 100, 2)
            except (ValueError, IndexError):
                continue

        return results if results else None

    def fetch_sina_kline(self, symbol: str, scale: int = 240, datalen: int = 100) -> Optional[List[Dict]]:
        """新浪历史K线"""
        url = self.SINA_KLINE_URL.format(symbol=symbol, scale=scale, datalen=datalen)
        raw = self._http_get(url, headers=self.SINA_HEADERS, timeout=20)
        if not raw:
            return None

        try:
            data = json.loads(raw)
            items = data.get("data", []) or []
            klines = []
            for item in (items or []):
                klines.append({
                    "date": item.get("day", ""),
                    "open": float(item.get("open", 0)),
                    "close": float(item.get("close", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "volume": float(item.get("volume", 0)),
                })
            return klines if klines else None
        except (json.JSONDecodeError, ValueError):
            return None

    # --- 腾讯数据源 ---
    def fetch_tencent_quote(self, symbols: List[str]) -> Optional[Dict[str, Any]]:
        """腾讯财经实时行情"""
        tencent_symbols = ",".join(symbols)
        url = self.TENCENT_HQ_URL.format(symbols=tencent_symbols)
        raw = self._http_get(url, headers=self.TENCENT_HEADERS, timeout=15, encoding="gbk")
        if not raw:
            return None

        results = {}
        for line in raw.strip().split("\n"):
            m = re.match(r'v_(\w+)="(.*)";', line)
            if not m:
                continue
            sym_code = m.group(1)
            parts = m.group(2).split("~")
            if len(parts) < 45:
                continue

            try:
                results[sym_code] = {
                    "name": parts[1],
                    "code": parts[2],
                    "price": float(parts[3]) if parts[3] else None,
                    "prev_close": float(parts[4]) if parts[4] else None,
                    "open": float(parts[5]) if parts[5] else None,
                    "volume": int(float(parts[6])) if parts[6] else None,
                    "high": float(parts[33]) if len(parts) > 33 and parts[33] else None,
                    "low": float(parts[34]) if len(parts) > 34 and parts[34] else None,
                }
                pc = results[sym_code]["prev_close"]
                p = results[sym_code]["price"]
                if pc and p:
                    results[sym_code]["change_pct"] = round((p - pc) / pc * 100, 2)
            except (ValueError, IndexError):
                continue

        return results if results else None

    def fetch_tencent_kline(self, symbol: str, period: str = "day", count: int = 100) -> Optional[List[Dict]]:
        """腾讯历史K线"""
        url = self.TENCENT_KLINE_URL.format(symbol=symbol, period=period, count=count)
        raw = self._http_get(url, headers=self.TENCENT_HEADERS, timeout=20)
        if not raw:
            return None

        try:
            data = json.loads(raw)
            days = (data.get("data") or {}).get(symbol, []) or []
            klines = []
            for day_data in (days or []):
                date_str = day_data[0]
                vals = day_data[1:]
                klines.append({
                    "date": date_str,
                    "open": float(vals[0]) if len(vals) > 0 else 0,
                    "close": float(vals[1]) if len(vals) > 1 else 0,
                    "high": float(vals[2]) if len(vals) > 2 else 0,
                    "low": float(vals[3]) if len(vals) > 3 else 0,
                    "volume": float(vals[4]) if len(vals) > 4 else 0,
                })
            return klines if klines else None
        except (json.JSONDecodeError, ValueError):
            return None

    # --- 东财直连数据源（替代 AKShare）---
    def fetch_akshare_quote(self, symbols: Optional[List[str]] = None) -> Optional[pd.DataFrame]:
        """A股实时行情 — 东财 push2 直连（原 ak.stock_zh_a_spot_em，走限流）"""
        try:
            r = _em_get("https://push2.eastmoney.com/api/qt/clist/get", params={
                "fid": "f3", "po": "1", "np": "1", "fltt": "2", "invt": "2",
                "ut": "b2884a393a59ad64002292a3e90d46a5",
                "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f2,f3,f4,f5,f6,f7,f8,f10,f12,f14",
                "pn": "1", "pz": "5000"
            })
            data = r.json().get("data", {}).get("diff", [])
            if not data:
                return None
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
            } for d in data])
            if symbols:
                df = df[df["代码"].isin(symbols)]
            return df
        except Exception as e:
            logger.debug(f"EastMoney quote failed: {e}")
            return None

    def fetch_akshare_kline(self, symbol: str, period: str = "daily",
                            start_date: Optional[str] = None, end_date: Optional[str] = None) -> Optional[pd.DataFrame]:
        """历史K线 — 东财直连（原 ak.stock_zh_a_hist，走限流）"""
        try:
            freq_map = {"daily": "101", "weekly": "102", "monthly": "103"}
            freq = freq_map.get(period, "101")
            market = "1" if symbol.startswith("6") else "0"

            # 默认获取最近 365 天的数据
            count = 365
            if start_date and end_date:
                from datetime import datetime as dt
                d1 = dt.strptime(start_date, "%Y%m%d")
                d2 = dt.strptime(end_date, "%Y%m%d")
                count = max(count, (d2 - d1).days + 1)

            r = _em_get(f"https://push2his.eastmoney.com/api/qt/stock/kline/get", params={
                "secid": f"{market}.{symbol}",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": freq, "fqt": "1", "beg": "0", "end": "20500000",
                "lmt": str(count), "ut": "b2884a393a59ad64002292a3e90d46a5"
            })
            data = r.json().get("data", {}).get("klines", [])
            if not data:
                return None
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
            df = pd.DataFrame(rows)
            # Apply date filters if provided
            if start_date:
                df = df[df["日期"] >= start_date.replace("20", "")[:8] if len(start_date) == 8 else start_date[:4]+start_date[4:6]+start_date[6:]]
            return df
        except Exception as e:
            logger.debug(f"EastMoney kline failed for {symbol}: {e}")
            return None

    def fetch_akshare_finance(self, symbol: str) -> Optional[pd.DataFrame]:
        """财务摘要 — 腾讯财经直连（原 ak.stock_financial_abstract_ths）"""
        try:
            import requests as req
            prefix = "sh" if symbol.startswith("6") else "sz"
            r = req.get(f"https://qt.gtimg.cn/q={prefix}{symbol}", 
                       headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            text = r.text
            if not text or "=" not in text:
                return None
            # Parse Tencent finance response (pipe-delimited)
            parts = text.split("=")[1].split("~")
            if len(parts) < 50:
                return None
            result = {
                "代码": symbol,
                "名称": parts[1] if len(parts) > 1 else "",
                "最新价": float(parts[3]) if len(parts) > 3 else 0,
                "涨跌幅": float(parts[32]) if len(parts) > 32 else 0,
                "PE_TTM": float(parts[39]) if len(parts) > 39 and parts[39] else None,
                "PB": float(parts[40]) if len(parts) > 40 and parts[40] else None,
                "总市值": float(parts[37]) / 1e4 if len(parts) > 37 else 0,
                "流通市值": float(parts[38]) / 1e4 if len(parts) > 38 else 0,
                "换手率": float(parts[35]) if len(parts) > 35 else 0,
            }
            return pd.DataFrame([result])
        except Exception as e:
            logger.debug(f"EastMoney finance failed for {symbol}: {e}")
            return None


# ============================================================
# SmartDispatcher - 智能调度器（无缓存，直接获取）
# ============================================================

class SmartDispatcher:
    """四源智能调度：pytdx → 东财直连 → 新浪 → 腾讯"""

    def __init__(self):
        self.fetcher = DataFetcher()
        # 调度优先级：pytdx(最快+无限制) → 东财直连 → 新浪 → 腾讯
        self._fallback_order = [DataSource.PYTDX, DataSource.AKSHARE, DataSource.SINA, DataSource.TENCENT]

    @staticmethod
    def _to_sina_sym(code: str) -> str:
        """转新浪格式：600519→s_sh600519, 000001→s_sz000001"""
        code_str = str(code).zfill(6)
        if code_str.startswith(('6', '9')):
            return f"s_sh{code_str}"
        else:
            return f"s_sz{code_str}"

    @staticmethod
    def _to_tencent_sym(code: str) -> str:
        """转腾讯格式：600519→sh600519, 000001→sz000001"""
        code_str = str(code).zfill(6)
        if code_str.startswith(('6', '9')):
            return f"sh{code_str}"
        else:
            return f"sz{code_str}"

    # --- 核心调度方法 ---
    def dispatch_quote(self, symbols: List[str]) -> Dict[str, Any]:
        """获取实时行情 - 直接轮询数据源"""
        result = {"symbols": {}, "source": None, "warnings": []}

        for source in self._fallback_order:
            data = None
            start_t = time.time()
            
            try:
                if source == DataSource.PYTDX:
                    data = self.fetcher.fetch_pytdx_quote(symbols)
                elif source == DataSource.AKSHARE:
                    df = self.fetcher.fetch_akshare_quote(symbols)
                    if df is not None and len(df) > 0:
                        data = {}
                        for _, row in df.iterrows():
                            code = str(row.get("代码", ""))
                            data[code] = {k: (float(v) if isinstance(v, (int, float)) else v)
                                         for k, v in row.to_dict().items()}
                elif source == DataSource.SINA:
                    sina_syms = [self._to_sina_sym(s) for s in symbols]
                    data = self.fetcher.fetch_sina_quote(sina_syms)
                elif source == DataSource.TENCENT:
                    tencent_syms = [self._to_tencent_sym(s) for s in symbols]
                    data = self.fetcher.fetch_tencent_quote(tencent_syms)

            except Exception as e:
                logger.debug(f"{source.value} failed: {e}")
                continue

            if data and len(data) > 0:
                result["symbols"] = data
                result["source"] = source.value
                return result

        # 四源全部失败：返回空结果并告警，不做自然语言兜底查询
        result["warnings"].append("⚠️ 所有数据源不可用")
        return result

    def dispatch_kline(self, symbol: str, period: str = "daily", count: int = 100) -> Dict[str, Any]:
        """获取K线数据 - 直接轮询数据源"""
        result = {"symbol": symbol, "data": None, "source": None, "warnings": []}

        # pytdx优先（支持分钟级）
        if period.startswith('min'):
            data = self.fetcher.fetch_pytdx_kline(symbol, period=period, count=count)
            if data:
                result["data"] = data
                result["source"] = "pytdx"
                return result

        # AKShare日线/周线/月线
        df = self.fetcher.fetch_akshare_kline(symbol, period=period)
        if df is not None and len(df) > 0:
            result["data"] = df.to_dict(orient="records")
            result["source"] = "akshare"
            return result

        # pytdx日线/周线/月线
        data = self.fetcher.fetch_pytdx_kline(symbol, period=period, count=count)
        if data:
            result["data"] = data
            result["source"] = "pytdx"
            return result

        # 腾讯K线
        tencent_sym = self._to_tencent_sym(symbol)
        data = self.fetcher.fetch_tencent_kline(tencent_sym, period="day", count=count)
        if data:
            result["data"] = data
            result["source"] = "tencent"
            return result

        # 新浪K线
        sina_sym = self._to_sina_sym(symbol)
        data = self.fetcher.fetch_sina_kline(sina_sym, scale=240, datalen=count)
        if data:
            result["data"] = data
            result["source"] = "sina"
            return result

        result["warnings"].append("⚠️ 所有K线数据源不可用")
        return result

    def dispatch_finance(self, symbol: str) -> Dict[str, Any]:
        """获取财务数据"""
        result = {"symbol": symbol, "data": None, "source": None, "warnings": []}

        df = self.fetcher.fetch_akshare_finance(symbol)
        if df is not None and len(df) > 0:
            result["data"] = df.to_dict(orient="records")
            result["source"] = "akshare"
            return result

        result["warnings"].append("⚠️ 财务数据获取失败")
        return result


# ============================================================
# CLI入口
# ============================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="A股多源数据调度引擎（无缓存版）")
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # 行情查询
    quote_parser = subparsers.add_parser("quote", help="实时行情查询")
    quote_parser.add_argument("symbols", nargs="+", help="股票代码，如 600519 000001")
    
    # K线查询
    kline_parser = subparsers.add_parser("kline", help="K线数据查询")
    kline_parser.add_argument("symbol", help="股票代码")
    kline_parser.add_argument("--period", default="daily", choices=["daily", "weekly", "monthly", "min5", "min15", "min30", "min60"])
    kline_parser.add_argument("--count", type=int, default=100)
    
    # 财务查询
    finance_parser = subparsers.add_parser("finance", help="财务数据查询")
    finance_parser.add_argument("symbol", help="股票代码")
    
    # pytdx测试
    test_parser = subparsers.add_parser("test-pytdx", help="测试pytdx连通性")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    dispatcher = SmartDispatcher()
    
    if args.command == "quote":
        result = dispatcher.dispatch_quote(args.symbols)
        print(f"\n📊 实时行情 (数据源: {result['source']})")
        print("=" * 60)
        for code, data in result["symbols"].items():
            name = data.get("name", "")
            price = data.get("price", "?")
            change_pct = data.get("change_pct", "?")
            volume = data.get("volume", "?")
            print(f"  {name}({code}): ¥{price} | {'🔴' if float(change_pct or 0) < 0 else '🟢'} {change_pct}% | 量: {volume}")
        for w in result.get("warnings", []):
            print(f"\n  {w}")
    
    elif args.command == "kline":
        result = dispatcher.dispatch_kline(args.symbol, period=args.period, count=args.count)
        if result["data"]:
            data = result["data"]
            print(f"\n📈 K线数据 ({args.symbol}, 来源: {result['source']})")
            print("=" * 60)
            print(f"  {'日期':<12} {'开盘':>8} {'收盘':>8} {'最高':>8} {'最低':>8} {'成交量':>12}")
            for item in data[:20]:
                date = str(item.get("date", ""))[:10]
                print(f"  {date:<12} {item.get('open', 0):>8.2f} {item.get('close', 0):>8.2f} {item.get('high', 0):>8.2f} {item.get('low', 0):>8.2f} {item.get('volume', 0):>12}")
            if len(data) > 20:
                print(f"  ... (共{len(data)}条)")
    
    elif args.command == "finance":
        result = dispatcher.dispatch_finance(args.symbol)
        if result["data"]:
            print(f"\n💰 财务数据 ({args.symbol}, 来源: {result['source']})")
            print("=" * 60)
            for item in result["data"][:5]:
                if isinstance(item, dict):
                    for k, v in item.items():
                        print(f"  {k}: {v}")
    
    elif args.command == "test-pytdx":
        print("🔌 pytdx连通性测试...")
        result = dispatcher.fetcher.fetch_pytdx_quote(["600519", "000001"])
        if result:
            for code, data in result.items():
                name = data.get("name", "")
                price = data.get("price", "?")
                print(f"  ✅ {name}({code}): ¥{price}")
        else:
            print("  ❌ pytdx获取行情失败（非交易时间正常）")


if __name__ == "__main__":
    main()
