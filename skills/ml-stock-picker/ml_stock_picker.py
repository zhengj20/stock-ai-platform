#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股机器学习选股系统 (ML Stock Picker)
=====================================
基于LightGBM/XGBoost的量化选股模型，融合技术指标、量价特征、基本面因子和市场情绪。

用法:
    # 训练模式
    python ml_stock_picker.py train --days 250
    python ml_stock_picker.py train --stocks "贵州茅台,宁德时代,比亚迪" --label-type classification
    python ml_stock_picker.py train --model xgboost --tune-hyperparams --cv-folds 5

    # 预测模式
    python ml_stock_picker.py predict
    python ml_stock_picker.py predict --top_n 30 --exclude_st --min_cap 50
    python ml_stock_picker.py predict --compare-multi-factor

依赖: pip install lightgbm xgboost scikit-learn pandas numpy requests

作者: Hermes Agent
版本: 1.0.0
"""

import os
import sys
import json
import time
import argparse
import pickle
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

# ML库导入
try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False
    print("⚠️  lightgbm未安装，运行 pip install lightgbm")

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    print("⚠️  xgboost未安装，运行 pip install xgboost")

try:
    from sklearn.model_selection import TimeSeriesSplit, cross_val_score, RandomizedSearchCV
    from sklearn.metrics import (accuracy_score, precision_score, recall_score, f1_score,
                                  mean_squared_error, r2_score)
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    print("⚠️  scikit-learn未安装，运行 pip install scikit-learn")

import requests

# mootdx 导入（通达信行情，不封IP）
try:
    from mootdx.quotes import Quotes
    HAS_MOOTDX = True
except ImportError:
    HAS_MOOTDX = False
    print("⚠️  mootdx未安装，运行 pip install mootdx")


def _tdx_client():
    """创建 mootdx 客户端"""
    servers = [('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709)]
    import socket
    for ip, port in servers:
        try:
            with socket.create_connection((ip, port), timeout=2):
                return Quotes.factory(market='std', server=(ip, port))
        except Exception:
            continue
    return Quotes.factory(market='std')


def _stock_name_to_code(name: str) -> Optional[str]:
    """股票名称 → 6位代码"""
    mapping = {
        "贵州茅台": "600519", "宁德时代": "300750", "比亚迪": "002594",
        "东方财富": "300059", "招商银行": "600036", "中国平安": "601318",
        "五粮液": "000858", "恒瑞医药": "600276", "隆基绿能": "601012",
        "中信证券": "600030", "万科A": "000002", "美的集团": "000333",
        "格力电器": "000651", "海天味业": "603288", "药明康德": "603259",
        "立讯精密": "002475", "兆易创新": "603986", "中芯国际": "688981",
        "北方华创": "002371", "海康威视": "002415",
    }
    return mapping.get(name)


# ============================================================================
# 免费公开数据层（东方财富数据中心/涨跌停池 + 腾讯名称检索）
# ============================================================================

_TX_SMARTBOX_URL = "https://smartbox.gtimg.cn/s3/"
_EM_DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_EM_EX_URL = "https://push2ex.eastmoney.com"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _get(url: str, params: Dict = None, headers: Dict = None, retries: int = 3):
    """
    请求公开接口，带退避重试。

    行情源对高频请求会直接断开连接（RemoteDisconnected），
    因此做退避重试，并在 HTTPS / HTTP 之间交替重试。
    """
    last_err = None
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
    raise RuntimeError(f"接口请求失败: {url} -> {last_err}")


def _safe_float(val) -> Optional[float]:
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(str(val).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def _resolve_code_by_name(name: str) -> str:
    """腾讯 smartbox 按名称检索A股，返回6位代码"""
    resp = _get(_TX_SMARTBOX_URL, {"v": "3", "q": name, "t": "all"},
                {"Referer": "https://gu.qq.com/"})
    resp.encoding = "gbk"
    hint = resp.text.partition('"')[2].rstrip('"')
    for item in hint.split("^"):
        parts = item.split("~")
        if len(parts) >= 5 and parts[4] == "GP-A":
            return parts[1]
    raise RuntimeError(f"未找到股票：{name}")


def _code_of(stock_name: str) -> Optional[str]:
    """先查内置映射，再走腾讯检索"""
    code = _stock_name_to_code(stock_name)
    if code:
        return code
    try:
        return _resolve_code_by_name(stock_name)
    except Exception:
        return None


def _secid(code: str) -> str:
    """东财 secid（1.=沪、0.=深）"""
    return f"{'1' if code.startswith(('6', '5', '9')) else '0'}.{code}"


def _em_datacenter(report: str, flt: str, sort_columns: str = None,
                   page_size: int = 8) -> List[Dict]:
    """东方财富数据中心公开报表（按 sort_columns 倒序）"""
    records: List[Dict] = []
    page = 1
    while True:
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
        page += 1
    return records


def fundamental_snapshot(stock_name: str) -> Dict:
    """
    个股基本面快照（估值 + 最新报告期财务），东财免费接口。

    估值字段：PE_TTM / PB_MRQ / PS_TTM / TOTAL_MARKET_CAP(元)
    财务字段：ROEJQ / ZZCJLL / XSMLL / XSJLL / ZCFZL /
              TOTALOPERATEREVETZ / PARENTNETPROFITTZ（均为%）
    """
    code = _code_of(stock_name)
    if not code:
        return {}
    snap: Dict = {}
    try:
        rows = _em_datacenter("RPT_VALUEANALYSIS_DET", f'(SECURITY_CODE="{code}")',
                              sort_columns="TRADE_DATE", page_size=1)
        if rows:
            snap.update(rows[0])
    except Exception as e:
        print(f"  ⚠️ 获取{stock_name}估值失败: {e}")
    try:
        secucode = f"{code}.{'SH' if _secid(code).startswith('1.') else 'SZ'}"
        reports = _em_datacenter("RPT_F10_FINANCE_MAINFINADATA", f'(SECUCODE="{secucode}")',
                                 sort_columns="REPORT_DATE", page_size=1)
        if reports:
            snap["__report__"] = reports[0]
    except Exception as e:
        print(f"  ⚠️ 获取{stock_name}财务数据失败: {e}")
    return snap


def pool_count(pool: str, trade_date: Optional[str] = None) -> Optional[int]:
    """
    东财涨停池(pool='ZT')/跌停池(pool='DT')家数。

    trade_date 格式 'YYYY-MM-DD' 或 'YYYYMMDD'，缺省为最新交易日。
    """
    date_compact = trade_date.replace("-", "") if trade_date else \
        datetime.now().strftime("%Y%m%d")
    endpoint = "getTopicZTPool" if pool == "ZT" else "getTopicDTPool"
    sort = "fbt:asc" if pool == "ZT" else "fund:asc"
    try:
        payload = _get(f"{_EM_EX_URL}/{endpoint}", {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": "1",
            "sort": sort, "date": date_compact,
        }, {"Referer": "https://quote.eastmoney.com/"}).json()
        data = payload.get("data") or {}
        tc = data.get("tc")
        return int(tc) if tc is not None else None
    except Exception:
        return None

_TX_KLINE_PATH = "/appstock/app/fqkline/get"
_TX_KLINE_HOSTS = ["https://web.ifzq.gtimg.cn", "https://ifzq.gtimg.cn",
                   "https://proxy.finance.qq.com/ifzqgtimg"]


def _tx_day_chunk(symbol: str, host: str, count: int, end: str = "") -> List[list]:
    """腾讯日线单段请求（end 为 'YYYYMMDD'，缺省取最新）"""
    resp = _get(host + _TX_KLINE_PATH,
                {"param": f"{symbol},day,,{end},{count},qfq"},
                {"Referer": "https://gu.qq.com/"}, retries=2)
    node = (resp.json().get("data") or {}).get(symbol) or {}
    # 有除权的标的返回 qfqday；从未除权的标的只有 day
    return node.get("qfqday") or node.get("day") or []


def _fetch_tx_daily(stock_name: str, days: int) -> pd.DataFrame:
    """
    腾讯前复权日线（三个入口限流互相独立，逐个尝试），免费公开接口。

    返回列：date / 开盘价 / 收盘价 / 最高价 / 最低价 / 成交量（手），
    按日期升序，取最近 days+10 条。源无换手率/成交额字段，不做伪造。
    """
    code = _code_of(stock_name)
    if not code:
        print(f"  ⚠️ {stock_name} 无法解析股票代码")
        return pd.DataFrame()
    prefix = "sh" if code.startswith(("6", "5", "9")) else \
        "bj" if code.startswith(("4", "8")) else "sz"
    symbol = prefix + code
    span = days + 10
    rows: List[list] = []
    for host in _TX_KLINE_HOSTS:
        rows = []
        try:
            items = _tx_day_chunk(symbol, host, min(span, 640))
            if items:
                rows = [list(r) for r in items]
                if span > 640:
                    earliest = str(rows[0][0])[:10].replace("-", "")
                    prev = (datetime.strptime(earliest, "%Y%m%d") -
                            timedelta(days=1)).strftime("%Y%m%d")
                    older = _tx_day_chunk(symbol, host, span - 640, prev)
                    rows = [list(r) for r in older] + rows
        except Exception:
            rows = []
        if rows:
            break
    if not rows:
        print(f"  ⚠️ {stock_name} K线数据为空")
        return pd.DataFrame()
    # 行序：日期,开盘,收盘,最高,最低,成交量(手)
    df = pd.DataFrame([r[:6] for r in rows],
                      columns=["date", "开盘价", "收盘价", "最高价", "最低价", "成交量"])
    for col in ["开盘价", "收盘价", "最高价", "最低价", "成交量"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = df["date"].astype(str).str[:10]
    df = df.sort_values("date").reset_index(drop=True)
    return df.tail(span).reset_index(drop=True)


# ============================================================================
# 特征工程模块 (Feature Engineering)
# ============================================================================

class FeatureEngineer:
    """特征工程 - 生成50+维度的量化特征"""
    
    def __init__(self):
        self._fund_cache: Dict[str, Dict] = {}
    
    # ------------------------------------------------------------------
    # 技术指标特征
    # ------------------------------------------------------------------
    
    @staticmethod
    def calc_ma(series: pd.Series, window: int) -> pd.Series:
        """计算移动平均线"""
        return series.rolling(window=window, min_periods=1).mean()
    
    @staticmethod
    def calc_ema(series: pd.Series, span: int) -> pd.Series:
        """计算指数移动平均线"""
        return series.ewm(span=span, adjust=False).mean()
    
    @staticmethod
    def calc_macd(close: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算MACD指标"""
        ema12 = FeatureEngineer.calc_ema(close, 12)
        ema26 = FeatureEngineer.calc_ema(close, 26)
        dif = ema12 - ema26
        dea = FeatureEngineer.calc_ema(dif, 9)
        hist = 2 * (dif - dea)
        return dif, dea, hist
    
    @staticmethod
    def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series,
                 n: int = 9, m1: int = 3, m2: int = 3) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算KDJ指标"""
        lowest_low = low.rolling(window=n, min_periods=1).min()
        highest_high = high.rolling(window=n, min_periods=1).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100
        
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        d = k.ewm(com=m2-1, adjust=False).mean()
        j = 3 * k - 2 * d
        return k, d, j
    
    @staticmethod
    def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """计算RSI指标"""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=period-1, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(com=period-1, min_periods=period, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - 100 / (1 + rs)
        return rsi
    
    @staticmethod
    def calc_bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算布林带指标"""
        ma = close.rolling(window=window, min_periods=1).mean()
        std = close.rolling(window=window, min_periods=1).std()
        upper = ma + num_std * std
        lower = ma - num_std * std
        pct_b = (close - lower) / (upper - lower + 1e-10)
        return upper, lower, pct_b
    
    def compute_technical_features(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """计算所有技术指标特征"""
        close_col = self._find_column(df, ["收盘价", "最新价", "收盘"])
        high_col = self._find_column(df, ["最高价", "最高"])
        low_col = self._find_column(df, ["最低价", "最低"])
        
        if not close_col:
            return {}
        
        close = df[close_col].astype(float)
        high = df[high_col].astype(float) if high_col else close
        low = df[low_col].astype(float) if low_col else close
        
        features = {}
        
        # MACD
        dif, dea, hist = self.calc_macd(close)
        features["MACD_DIF"] = dif
        features["MACD_DEA"] = dea
        features["MACD_HIST"] = hist
        features["MACD_DIF_CHG"] = dif.pct_change(5).fillna(0)
        
        # KDJ
        k, d, j = self.calc_kdj(high, low, close)
        features["KDJ_K"] = k
        features["KDJ_D"] = d
        features["KDJ_J"] = j
        
        # RSI
        features["RSI_6"] = self.calc_rsi(close, 6)
        features["RSI_14"] = self.calc_rsi(close, 14)
        
        # Bollinger Bands
        upper, lower, pct_b = self.calc_bollinger(close)
        features["BOLL_UPPER"] = upper
        features["BOLL_LOWER"] = lower
        features["BOLL_PCT"] = pct_b
        
        # MA Deviations (均线偏离度)
        for ma_window in [5, 10, 20]:
            ma = self.calc_ma(close, ma_window)
            features[f"MA{ma_window}_DEVIATION"] = ((close - ma) / (ma + 1e-10)) * 100
        
        return features
    
    # ------------------------------------------------------------------
    # 量价特征
    # ------------------------------------------------------------------
    
    def compute_volume_price_features(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """计算量价特征"""
        close_col = self._find_column(df, ["收盘价", "最新价", "收盘"])
        vol_col = self._find_column(df, ["成交量", "volume"])
        turnover_col = self._find_column(df, ["换手率", "turnover"])
        high_col = self._find_column(df, ["最高价", "最高"])
        low_col = self._find_column(df, ["最低价", "最低"])
        
        if not close_col:
            return {}
        
        close = df[close_col].astype(float)
        features = {}
        
        # 涨跌幅
        features["PRICE_CHANGE_1D"] = close.pct_change(1).fillna(0) * 100
        features["PRICE_CHANGE_5D"] = close.pct_change(5).fillna(0) * 100
        
        # 成交量变化率
        if vol_col:
            vol = df[vol_col].astype(float)
            features["VOL_CHANGE_5D"] = vol.pct_change(5).fillna(0) * 100
            vol_ma5 = vol.rolling(window=5, min_periods=1).mean()
            features["VOL_RATIO"] = (vol / (vol_ma5 + 1e-10))
        
        # 换手率分位
        if turnover_col:
            turnover = df[turnover_col].astype(float)
            rolling_rank = turnover.rolling(window=20, min_periods=1).rank(pct=True)
            features["TURNOVER_PCTILE"] = rolling_rank
        
        # 振幅
        if high_col and low_col:
            high = df[high_col].astype(float)
            low = df[low_col].astype(float)
            features["AMPLITUDE"] = ((high - low) / (close + 1e-10)) * 100
        
        return features
    
    # ------------------------------------------------------------------
    # 基本面特征（复用multi-factor模块的因子计算）
    # ------------------------------------------------------------------
    
    def compute_fundamental_features(self, stock_name: str) -> Dict[str, float]:
        """基本面特征（东财估值明细 + F10最新报告期主要财务，免费接口）"""
        if stock_name not in self._fund_cache:
            self._fund_cache[stock_name] = fundamental_snapshot(stock_name)
        snap = self._fund_cache[stock_name]
        report = snap.get("__report__") or {}
        cap = _safe_float(snap.get("TOTAL_MARKET_CAP"))

        raw = {
            "PE_TTM": _safe_float(snap.get("PE_TTM")),
            "PB": _safe_float(snap.get("PB_MRQ")),
            "PS_TTM": _safe_float(snap.get("PS_TTM")),
            "总市值(亿)": cap / 1e8 if cap else None,
            "ROE": _safe_float(report.get("ROEJQ")),
            "ROA": _safe_float(report.get("ZZCJLL")),
            "GROSS_MARGIN": _safe_float(report.get("XSMLL")),
            "NET_MARGIN": _safe_float(report.get("XSJLL")),
            "DEBT_RATIO": _safe_float(report.get("ZCFZL")),
            "REVENUE_GROWTH": _safe_float(report.get("TOTALOPERATEREVETZ")),
            "PROFIT_GROWTH": _safe_float(report.get("PARENTNETPROFITTZ")),
        }
        return {k: v for k, v in raw.items() if v is not None}
    
    # ------------------------------------------------------------------
    # 市场情绪特征（复用market-sentiment模块）
    # ------------------------------------------------------------------
    
    def compute_sentiment_features(self, date_str: Optional[str] = None) -> Dict[str, float]:
        """
        情绪特征（东财涨停池/跌停池家数，免费接口）

        - LIMIT_UP_DOWN_RATIO: 涨停家数 / 跌停家数（无跌停时取涨停家数）
        - SENTIMENT_SCORE: 涨停家数 / (涨停+跌停) × 100，衡量多空力量对比
        """
        limit_up = pool_count("ZT", date_str)
        limit_down = pool_count("DT", date_str)
        features: Dict[str, float] = {}

        if limit_up is None and limit_down is None:
            return features

        limit_up = limit_up or 0
        limit_down = limit_down or 0

        if limit_down > 0:
            features["LIMIT_UP_DOWN_RATIO"] = limit_up / limit_down
        else:
            features["LIMIT_UP_DOWN_RATIO"] = float(limit_up)

        total = limit_up + limit_down
        if total > 0:
            features["SENTIMENT_SCORE"] = min(100.0, max(0.0, limit_up / total * 100))

        return features
    
    # ------------------------------------------------------------------
    # 时间特征
    # ------------------------------------------------------------------
    
    @staticmethod
    def compute_time_features(date: pd.Timestamp) -> Dict[str, float]:
        """计算时间特征"""
        day_of_week = date.dayofweek  # 0=Monday, 4=Friday
        month = date.month
        
        # 财报季：4月(一季报)、8月(中报)、10月(三季报)
        is_earnings_season = 1.0 if month in [4, 8, 10] else 0.0
        
        return {
            "DAY_OF_WEEK": float(day_of_week),
            "MONTH": float(month),
            "IS_EARNINGS_SEASON": is_earnings_season
        }
    
    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    
    @staticmethod
    def _find_column(df: pd.DataFrame, keywords: List[str]) -> Optional[str]:
        """根据关键词查找列名"""
        for col in df.columns:
            c = str(col)
            for kw in keywords:
                if kw in c:
                    return col
        return None


# ============================================================================
# 标签生成模块 (Label Generation)
# ============================================================================

class LabelGenerator:
    """标签生成器"""
    
    @staticmethod
    def generate_return_labels(close_series: pd.Series, n_days: int = 1) -> pd.Series:
        """N日收益率标签（回归任务）"""
        future_close = close_series.shift(-n_days)
        return_label = (future_close - close_series) / (close_series + 1e-10) * 100
        return return_label.rename(f"RETURN_{n_days}D")
    
    @staticmethod
    def generate_classification_labels(close_series: pd.Series, n_days: int = 1,
                                        threshold: float = 3.0) -> pd.Series:
        """三分类标签（分类任务）"""
        future_close = close_series.shift(-n_days)
        return_pct = (future_close - close_series) / (close_series + 1e-10) * 100
        
        labels = pd.Series(0, index=return_pct.index, name=f"CLASS_{n_days}D")
        labels[return_pct > threshold] = 1      # 大涨
        labels[return_pct < -threshold] = -1    # 大跌
        
        return labels
    
    @staticmethod
    def generate_ranking_labels(daily_returns: pd.DataFrame) -> pd.Series:
        """分位数排名标签（排序任务）"""
        # daily_returns: rows=dates, columns=stocks
        ranks = daily_returns.rank(axis=1, pct=True) * 100
        return ranks


# ============================================================================
# 模型训练模块 (Model Training)
# ============================================================================

class ModelTrainer:
    """ML模型训练器"""
    
    def __init__(self):
        self.classifier = None
        self.regressor = None
        self.feature_names_ = []
        self.scaler = StandardScaler()
    
    # ------------------------------------------------------------------
    # LightGBM 分类器
    # ------------------------------------------------------------------
    
    @staticmethod
    def create_lgb_classifier(params: Optional[Dict] = None) -> lgb.LGBMClassifier:
        """创建LightGBM分类器（增强正则化防止过拟合）"""
        default_params = {
            "n_estimators": 500,
            "learning_rate": 0.03,
            "max_depth": 5,
            "num_leaves": 20,
            "min_child_samples": 50,
            "subsample": 0.7,
            "colsample_bytree": 0.7,
            "reg_alpha": 0.5,
            "reg_lambda": 0.5,
            "min_split_gain": 0.01,
            "random_state": 42,
            "verbose": -1,
            "n_jobs": -1,
        }
        if params:
            default_params.update(params)
        return lgb.LGBMClassifier(**default_params)
    
    @staticmethod
    def create_lgb_regressor(params: Optional[Dict] = None) -> lgb.LGBMRegressor:
        """创建LightGBM回归器（增强正则化防止过拟合）"""
        default_params = {
            "n_estimators": 500,
            "learning_rate": 0.03,
            "max_depth": 5,
            "num_leaves": 20,
            "min_child_samples": 50,
            "subsample": 0.7,
            "colsample_bytree": 0.7,
            "reg_alpha": 0.5,
            "reg_lambda": 0.5,
            "min_split_gain": 0.01,
            "random_state": 42,
            "verbose": -1,
            "n_jobs": -1,
        }
        if params:
            default_params.update(params)
        return lgb.LGBMRegressor(**default_params)
    
    # ------------------------------------------------------------------
    # XGBoost 备选模型
    # ------------------------------------------------------------------
    
    @staticmethod
    def create_xgb_classifier(params: Optional[Dict] = None) -> xgb.XGBClassifier:
        """创建XGBoost分类器（增强正则化防止过拟合）"""
        default_params = {
            "n_estimators": 500,
            "learning_rate": 0.03,
            "max_depth": 5,
            "subsample": 0.7,
            "colsample_bytree": 0.7,
            "reg_alpha": 0.5,
            "reg_lambda": 0.5,
            "min_child_weight": 5,
            "gamma": 0.1,
            "random_state": 42,
            "n_jobs": -1,
            "use_label_encoder": False,
            "eval_metric": "mlogloss",
        }
        if params:
            default_params.update(params)
        return xgb.XGBClassifier(**default_params)
    
    @staticmethod
    def create_xgb_regressor(params: Optional[Dict] = None) -> xgb.XGBRegressor:
        """创建XGBoost回归器（增强正则化防止过拟合）"""
        default_params = {
            "n_estimators": 500,
            "learning_rate": 0.03,
            "max_depth": 5,
            "subsample": 0.7,
            "colsample_bytree": 0.7,
            "reg_alpha": 0.5,
            "reg_lambda": 0.5,
            "min_child_weight": 5,
            "gamma": 0.1,
            "random_state": 42,
            "n_jobs": -1,
        }
        if params:
            default_params.update(params)
        return xgb.XGBRegressor(**default_params)
    
    # ------------------------------------------------------------------
    # 训练方法
    # ------------------------------------------------------------------
    
    def train_classifier(self, X_train: np.ndarray, y_train: np.ndarray,
                         X_val: Optional[np.ndarray] = None,
                         y_val: Optional[np.ndarray] = None,
                         model_name: str = "lightgbm",
                         tune_hyperparams: bool = False,
                         cv_folds: int = 5,
                         early_stopping_rounds: int = 50) -> Any:
        """训练分类模型（支持早停机制防止过拟合）"""
        
        if model_name == "xgboost":
            if not HAS_XGB:
                raise ImportError("XGBoost未安装")
            clf = self.create_xgb_classifier()
        else:
            if not HAS_LGB:
                raise ImportError("LightGBM未安装")
            clf = self.create_lgb_classifier()
        
        # 超参数调优
        if tune_hyperparams and HAS_SKLEARN:
            param_dist = {
                "n_estimators": [200, 300, 500],
                "learning_rate": [0.01, 0.03, 0.05],
                "max_depth": [4, 5, 6],
                "num_leaves": [15, 20, 31] if model_name == "lightgbm" else [7, 15, 31],
                "subsample": [0.7, 0.8],
                "colsample_bytree": [0.7, 0.8],
            }
            
            tscv = TimeSeriesSplit(n_splits=cv_folds)
            random_search = RandomizedSearchCV(
                clf, param_distributions=param_dist,
                n_iter=15, cv=tscv, scoring="f1",
                random_state=42, n_jobs=-1, verbose=0
            )
            random_search.fit(X_train, y_train)
            clf = random_search.best_estimator_
            print(f"  ✅ 超参数调优完成，最佳参数: {random_search.best_params_}")
        
        # 使用早停机制训练
        if X_val is not None and y_val is not None:
            if model_name == "xgboost":
                clf.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    verbose=False
                )
            else:
                clf.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    callbacks=[lgb.early_stopping(early_stopping_rounds, verbose=False)]
                )
        else:
            clf.fit(X_train, y_train)
        
        self.classifier = clf
        return clf
    
    def train_regressor(self, X_train: np.ndarray, y_train: np.ndarray,
                        X_val: Optional[np.ndarray] = None,
                        y_val: Optional[np.ndarray] = None,
                        model_name: str = "lightgbm",
                        tune_hyperparams: bool = False,
                        cv_folds: int = 5,
                        early_stopping_rounds: int = 50) -> Any:
        """训练回归模型（支持早停机制防止过拟合）"""
        
        if model_name == "xgboost":
            if not HAS_XGB:
                raise ImportError("XGBoost未安装")
            reg = self.create_xgb_regressor()
        else:
            if not HAS_LGB:
                raise ImportError("LightGBM未安装")
            reg = self.create_lgb_regressor()
        
        # 超参数调优
        if tune_hyperparams and HAS_SKLEARN:
            param_dist = {
                "n_estimators": [200, 300, 500],
                "learning_rate": [0.01, 0.03, 0.05],
                "max_depth": [4, 5, 6],
                "num_leaves": [15, 20, 31] if model_name == "lightgbm" else [7, 15, 31],
                "subsample": [0.7, 0.8],
                "colsample_bytree": [0.7, 0.8],
            }
            
            tscv = TimeSeriesSplit(n_splits=cv_folds)
            random_search = RandomizedSearchCV(
                reg, param_distributions=param_dist,
                n_iter=15, cv=tscv, scoring="neg_mean_squared_error",
                random_state=42, n_jobs=-1, verbose=0
            )
            random_search.fit(X_train, y_train)
            reg = random_search.best_estimator_
            print(f"  ✅ 超参数调优完成，最佳参数: {random_search.best_params_}")
        
        # 使用早停机制训练
        if X_val is not None and y_val is not None:
            if model_name == "xgboost":
                reg.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    verbose=False
                )
            else:
                reg.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    callbacks=[lgb.early_stopping(early_stopping_rounds, verbose=False)]
                )
        else:
            reg.fit(X_train, y_train)
        
        self.regressor = reg
        return reg
    
    # ------------------------------------------------------------------
    # 交叉验证
    # ------------------------------------------------------------------
    
    def cross_validate(self, X: np.ndarray, y: np.ndarray, model_name: str = "lightgbm",
                       task: str = "classification", cv_folds: int = 5) -> Dict[str, float]:
        """时间序列交叉验证"""
        if not HAS_SKLEARN:
            return {"cv_error": "scikit-learn未安装"}
        
        if task == "classification":
            if model_name == "xgboost":
                base_model = self.create_xgb_classifier()
            else:
                base_model = self.create_lgb_classifier()
            scoring = "f1"
        else:
            if model_name == "xgboost":
                base_model = self.create_xgb_regressor()
            else:
                base_model = self.create_lgb_regressor()
            scoring = "neg_mean_squared_error"
        
        tscv = TimeSeriesSplit(n_splits=cv_folds)
        scores = cross_val_score(base_model, X, y, cv=tscv, scoring=scoring)
        
        return {
            f"{task}_cv_mean": float(scores.mean()),
            f"{task}_cv_std": float(scores.std()),
            f"{task}_cv_scores": [float(s) for s in scores]
        }
    
    # ------------------------------------------------------------------
    # 特征重要性分析
    # ------------------------------------------------------------------
    
    def get_feature_importance(self, model: Any, feature_names: List[str],
                                top_n: int = 20) -> List[Dict]:
        """获取Top N重要特征"""
        importances = model.feature_importances_
        
        # 按重要性排序
        indices = np.argsort(importances)[::-1][:top_n]
        
        result = []
        for rank, idx in enumerate(indices, 1):
            result.append({
                "rank": rank,
                "feature": feature_names[idx],
                "importance": float(importances[idx])
            })
        
        return result
    
    # ------------------------------------------------------------------
    # 模型保存/加载
    # ------------------------------------------------------------------
    
    def save_model(self, output_dir: str = "./ml_output"):
        """保存训练好的模型"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        if self.classifier is not None:
            path = Path(output_dir) / "model_classifier.pkl"
            with open(path, "wb") as f:
                pickle.dump(self.classifier, f)
            print(f"  ✅ 分类器模型已保存: {path}")
        
        if self.regressor is not None:
            path = Path(output_dir) / "model_regressor.pkl"
            with open(path, "wb") as f:
                pickle.dump(self.regressor, f)
            print(f"  ✅ 回归器模型已保存: {path}")
    
    @staticmethod
    def load_model(model_path: str):
        """加载训练好的模型"""
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        return model


# ============================================================================
# 模型评估模块 (Model Evaluation)
# ============================================================================

class ModelEvaluator:
    """模型评估器"""
    
    @staticmethod
    def evaluate_classification(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
        """分类任务评估指标"""
        return {
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "precision_macro": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
            "recall_macro": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
            "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        }
    
    @staticmethod
    def evaluate_regression(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
        """回归任务评估指标"""
        return {
            "mse": float(mean_squared_error(y_true, y_pred)),
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "r2": float(r2_score(y_true, y_pred)),
        }
    
    @staticmethod
    def compute_ic_ir(predictions: np.ndarray, actual_returns: np.ndarray) -> Dict[str, float]:
        """计算IC（信息系数）和IR（信息比率）"""
        # Spearman相关系数作为IC
        from scipy.stats import spearmanr
        
        ic_values = []
        n = len(predictions)
        
        # 如果是面板数据，按时间窗口计算IC
        if isinstance(predictions, pd.DataFrame):
            for date in predictions.index:
                pred = predictions.loc[date].dropna()
                actual = actual_returns.loc[date].dropna() if isinstance(actual_returns, pd.DataFrame) else actual_returns
                common_idx = pred.index.intersection(actual.index if hasattr(actual, 'index') else pred.index)
                if len(common_idx) > 5:
                    ic, _ = spearmanr(pred[common_idx], actual[common_idx])
                    ic_values.append(ic)
        else:
            # 简单情况：直接计算整体IC
            mask = ~(np.isnan(predictions) | np.isnan(actual_returns))
            if mask.sum() > 5:
                ic, _ = spearmanr(predictions[mask], actual_returns[mask])
                ic_values.append(ic)
        
        if not ic_values:
            return {"ic_mean": 0.0, "ir": 0.0, "ic_count": 0}
        
        ic_arr = np.array(ic_values)
        ic_mean = float(np.mean(ic_arr))
        ic_std = float(np.std(ic_arr)) if len(ic_arr) > 1 else 1e-8
        
        return {
            "ic_mean": ic_mean,
            "ir": ic_mean / (ic_std + 1e-8),
            "ic_count": len(ic_values),
            "ic_std": ic_std
        }
    
    @staticmethod
    def group_backtest(predictions: np.ndarray, actual_returns: np.ndarray,
                       n_groups: int = 5) -> Dict[str, Any]:
        """分组回测：按预测得分分N组，看各组实际收益率"""
        # 将样本按预测值分为N组
        sorted_indices = np.argsort(predictions)
        group_size = len(sorted_indices) // n_groups
        
        groups = {}
        for g in range(n_groups):
            start = g * group_size
            end = (g + 1) * group_size if g < n_groups - 1 else len(sorted_indices)
            group_idx = sorted_indices[start:end]
            
            group_preds = predictions[group_idx]
            group_returns = actual_returns[group_idx]
            
            groups[f"group_{g+1}"] = {
                "size": len(group_idx),
                "pred_mean": float(np.mean(group_preds)),
                "return_mean": float(np.mean(group_returns)),
                "return_std": float(np.std(group_returns)),
                "best_return": float(np.max(group_returns)),
                "worst_return": float(np.min(group_returns))
            }
        
        # 多空收益（最高组 - 最低组）
        long_return = groups["group_1"]["return_mean"]  # 预测值最低的组
        short_return = groups[f"group_{n_groups}"]["return_mean"]  # 预测值最高的组
        
        return {
            "groups": groups,
            "long_short_spread": float(short_return - long_return),
            "monotonicity_check": ModelEvaluator._check_monotonicity(groups)
        }
    
    @staticmethod
    def _check_monotonicity(groups: Dict[str, Any]) -> bool:
        """检查分组收益是否单调递增"""
        returns = [groups[f"group_{i}"]["return_mean"] for i in range(1, len(groups)+1)]
        increasing = all(returns[i] >= returns[i-1] for i in range(1, len(returns)))
        return increasing
    
    @staticmethod
    def cumulative_returns(group_returns: Dict[str, float]) -> List[Dict]:
        """计算累计收益曲线数据"""
        curve = []
        cum_return = 0.0
        
        for date_str, ret in sorted(group_returns.items()):
            cum_return += ret
            curve.append({
                "date": date_str,
                "daily_return": float(ret),
                "cumulative_return": float(cum_return)
            })
        
        return curve


# ============================================================================
# 选股执行模块 (Stock Selection)
# ============================================================================

class StockSelector:
    """选股执行器"""
    
    def __init__(self):
        pass
    
    def select_stocks(self, model_classifier: Any, model_regressor: Any,
                      feature_names: List[str], stock_names: List[str],
                      top_n: int = 30, exclude_st: bool = True,
                      min_market_cap: Optional[float] = None,
                      max_market_cap: Optional[float] = None) -> pd.DataFrame:
        """对股票池打分排序，输出TOP N"""
        
        feature_engineer = FeatureEngineer()
        all_features = []
        stock_info = []
        
        print(f"\n📊 正在为 {len(stock_names)} 只股票计算特征...")
        
        for i, name in enumerate(stock_names):
            if (i + 1) % 10 == 0:
                print(f"  进度: {i+1}/{len(stock_names)}")
            
            # ST排除
            if exclude_st and ("ST" in name or "退" in name):
                continue
            
            try:
                # 获取历史行情数据计算技术特征
                daily_df = self._fetch_daily_data(name, days=60)
                
                if daily_df.empty:
                    continue
                
                tech_features = feature_engineer.compute_technical_features(daily_df)
                vol_features = feature_engineer.compute_volume_price_features(daily_df)
                
                # 基本面特征
                fund_features = feature_engineer.compute_fundamental_features(name)
                
                # 时间特征（使用最新日期）
                latest_date = pd.to_datetime(daily_df["date"].iloc[-1]) if "date" in daily_df.columns else datetime.now()
                time_features = FeatureEngineer.compute_time_features(latest_date)
                
                # 合并所有特征
                row_features = {}
                
                # 技术+量价特征（取最新值）
                for fname, fseries in {**tech_features, **vol_features}.items():
                    if len(fseries) > 0:
                        row_features[fname] = fseries.iloc[-1]
                
                # 基本面特征
                row_features.update(fund_features)
                
                # 时间特征
                row_features.update(time_features)
                
                all_features.append(row_features)
                stock_info.append({"stock_name": name})
            
            except Exception as e:
                print(f"  ⚠️ {name} 特征计算失败: {e}")
        
        if not all_features:
            return pd.DataFrame()
        
        # 构建DataFrame
        features_df = pd.DataFrame(all_features)
        
        # 确保列顺序与训练时一致
        missing_cols = set(feature_names) - set(features_df.columns)
        for col in missing_cols:
            features_df[col] = np.nan
        
        features_df = features_df[feature_names]
        
        # 用中位数填充缺失值（比填0更合理，避免引入系统性偏差）
        medians = features_df.median()
        features_df = features_df.fillna(medians)
        
        X = features_df.values.astype(np.float32)
        
        # 模型预测得分
        if model_classifier is not None:
            class_probs = model_classifier.predict_proba(X)
            classes = list(model_classifier.classes_)
            
            # 优先取"涨"(1)类别概率，不存在则取最大类别
            if 1 in classes:
                up_idx = classes.index(1)
                class_score = class_probs[:, up_idx]
            elif max(classes) > min(classes):
                # 二分类情况：取正类概率
                up_idx = classes.index(max(classes))
                class_score = class_probs[:, up_idx]
            else:
                class_score = np.zeros(len(X))
        else:
            class_score = np.zeros(len(X))
        
        if model_regressor is not None:
            reg_score = model_regressor.predict(X)
        else:
            reg_score = np.zeros(len(X))
        
        # 综合得分（分类概率 + 回归预测的标准化）
        reg_range = reg_score.max() - reg_score.min()
        if reg_range > 1e-10:
            reg_normalized = (reg_score - reg_score.min()) / reg_range
        else:
            reg_normalized = np.full_like(reg_score, 0.5)
        
        # 动态权重：如果只有一个模型可用，则全权委托
        if model_classifier is not None and model_regressor is not None:
            combined_score = 0.5 * class_score + 0.5 * reg_normalized
        elif model_classifier is not None:
            combined_score = class_score
        else:
            combined_score = reg_normalized
        
        # 构建结果DataFrame
        result_df = pd.DataFrame(stock_info[:len(all_features)])
        result_df["class_score"] = np.round(class_score, 4)
        result_df["regression_score"] = np.round(reg_score, 4)
        result_df["combined_score"] = np.round(combined_score, 4)
        
        # 市值过滤
        if min_market_cap or max_market_cap:
            cap_col = "market_cap"
            for col in features_df.columns:
                if "市值" in str(col):
                    cap_col = col
                    break
            
            if cap_col in features_df.columns:
                caps = features_df[cap_col].values
                mask = np.ones(len(caps), dtype=bool)
                if min_market_cap:
                    mask &= (caps >= min_market_cap)
                if max_market_cap:
                    mask &= (caps <= max_market_cap)
                result_df = result_df[mask]
        
        # 排序并取TOP N
        result_df = result_df.sort_values("combined_score", ascending=False).head(top_n)
        result_df["rank"] = range(1, len(result_df) + 1)
        
        return result_df.reset_index(drop=True)
    
    def _fetch_daily_data(self, stock_name: str, days: int = 60) -> pd.DataFrame:
        """获取个股历史行情数据（腾讯前复权日线，免费公开接口）"""
        return _fetch_tx_daily(stock_name, days)


# ============================================================================
# ML选股主类 (ML Stock Picker)
# ============================================================================

class MLStockPicker:
    """A股机器学习选股系统 - 主入口"""
    
    def __init__(self):
        self.feature_engineer = FeatureEngineer()
        self.trainer = ModelTrainer()
        self.evaluator = ModelEvaluator()
        self.selector = StockSelector()
    
    def train(self, days: int = 250, stock_names: Optional[List[str]] = None,
              label_type: str = "classification", model_name: str = "lightgbm",
              return_days: int = 1, tune_hyperparams: bool = False,
              cv_folds: int = 5, output_dir: str = "./ml_output") -> Dict[str, Any]:
        """训练ML选股模型"""
        
        print("=" * 60)
        print("🚀 A股机器学习选股系统 - 训练模式")
        print("=" * 60)
        print(f"   数据天数: {days}")
        print(f"   标签类型: {label_type}")
        print(f"   模型: {model_name}")
        print(f"   交叉验证折数: {cv_folds}")
        print(f"   超参数调优: {'是' if tune_hyperparams else '否'}")
        
        # 默认股票池（沪深300代表性成分股）
        if not stock_names:
            stock_names = [
                "贵州茅台", "宁德时代", "比亚迪", "东方财富", "招商银行",
                "中国平安", "五粮液", "恒瑞医药", "隆基绿能", "中信证券",
                "万科A", "美的集团", "格力电器", "海天味业", "药明康德",
                "立讯精密", "兆易创新", "中芯国际", "北方华创", "海康威视"
            ]
        
        print(f"\n📋 股票池: {len(stock_names)} 只")
        
        # ------------------------------------------------------------------
        # Step 1: 获取数据并计算特征
        # ------------------------------------------------------------------
        print("\n" + "=" * 40)
        print("Step 1/5: 获取历史数据 & 计算特征")
        print("=" * 40)
        
        all_data = {}  # stock_name -> DataFrame with features
        
        for i, name in enumerate(stock_names):
            if (i + 1) % 5 == 0:
                print(f"  进度: {i+1}/{len(stock_names)}")
            
            try:
                # 获取历史行情数据
                daily_df = self._fetch_daily_data(name, days=days + return_days + 10)

                if daily_df.empty or len(daily_df) < 30:
                    print(f"  ⚠️ {name} 数据不足，跳过")
                    continue
                
                # 计算技术特征
                tech_features = self.feature_engineer.compute_technical_features(daily_df)
                vol_features = self.feature_engineer.compute_volume_price_features(daily_df)
                
                # 基本面特征（获取一次，填充到所有行）
                fund_features = self.feature_engineer.compute_fundamental_features(name)
                
                # 时间特征
                dates = pd.to_datetime(daily_df["date"]) if "date" in daily_df.columns else None
                
                all_data[name] = {
                    "daily": daily_df,
                    "tech": tech_features,
                    "vol": vol_features,
                    "fundamental": fund_features,
                    "dates": dates
                }
                
            except Exception as e:
                print(f"  ⚠️ {name} 数据处理失败: {e}")
        
        if not all_data:
            raise RuntimeError("没有成功获取任何股票数据")
        
        # ------------------------------------------------------------------
        # Step 2: 构建特征矩阵和标签
        # ------------------------------------------------------------------
        print("\n" + "=" * 40)
        print("Step 2/5: 构建特征矩阵 & 生成标签")
        print("=" * 40)
        
        feature_names = []
        all_X_rows = []
        all_y_class = []
        all_y_reg = []
        all_dates = []
        all_stock_labels = []
        
        for name, data in all_data.items():
            tech = data["tech"]
            vol = data["vol"]
            fund = data["fundamental"]
            dates = data["dates"]
            
            # 合并技术+量价特征
            combined_features = {**tech, **vol}
            
            if not feature_names:
                feature_names = list(combined_features.keys()) + \
                               list(fund.keys()) + ["DAY_OF_WEEK", "MONTH", "IS_EARNINGS_SEASON"]
            
            # 获取收盘价序列用于标签生成
            close_col = self.feature_engineer._find_column(data["daily"], ["收盘价", "最新价", "收盘"])
            if not close_col:
                continue
            
            close_series = data["daily"][close_col].astype(float)
            
            # 生成标签
            reg_label = LabelGenerator.generate_return_labels(close_series, return_days)
            class_label = LabelGenerator.generate_classification_labels(close_series, return_days)
            
            n_rows = len(close_series)
            
            for idx in range(n_rows):
                row_features = {}
                
                # 技术+量价特征（取当前行值）
                for fname, fseries in combined_features.items():
                    if idx < len(fseries):
                        val = fseries.iloc[idx]
                        if not np.isnan(val) and abs(val) < 1e8:
                            row_features[fname] = float(val)
                
                # 基本面特征（填充到所有行）
                for fname, fval in fund.items():
                    row_features[fname] = fval
                
                # 时间特征
                if dates is not None and idx < len(dates):
                    time_feats = FeatureEngineer.compute_time_features(dates[idx])
                    row_features.update(time_feats)
                
                # 标签值
                y_reg_val = reg_label.iloc[idx] if idx < len(reg_label) else np.nan
                y_class_val = class_label.iloc[idx] if idx < len(class_label) else 0
                
                # 跳过NaN标签的行（通常是末尾几行）
                if pd.isna(y_reg_val):
                    continue
                
                all_X_rows.append(row_features)
                all_y_reg.append(float(y_reg_val))
                all_y_class.append(int(y_class_val))
                
                if dates is not None and idx < len(dates):
                    all_dates.append(str(dates[idx]))
                else:
                    all_dates.append("")
                
                all_stock_labels.append(name)
        
        # 构建DataFrame
        X_df = pd.DataFrame(all_X_rows)
        
        # 确保列顺序一致
        for col in feature_names:
            if col not in X_df.columns:
                X_df[col] = np.nan
        
        X_df = X_df[feature_names]
        
        # 填充缺失值（用中位数）
        medians = X_df.median()
        X_df = X_df.fillna(medians)
        
        y_reg = np.array(all_y_reg, dtype=np.float32)
        y_class = np.array(all_y_class, dtype=int)
        
        # 去除极端值（winsorize）
        for col in X_df.columns:
            lower = np.percentile(X_df[col], 1)
            upper = np.percentile(X_df[col], 99)
            X_df[col] = X_df[col].clip(lower=lower, upper=upper)
        
        X = X_df.values.astype(np.float32)
        
        print(f"  ✅ 特征矩阵: {X.shape[0]} 样本 × {X.shape[1]} 特征")
        print(f"  ✅ 标签分布 (分类): {-1}:{np.sum(y_class==-1)}, 0:{np.sum(y_class==0)}, 1:{np.sum(y_class==1)}")
        print(f"  ✅ 收益率范围: [{y_reg.min():.2f}%, {y_reg.max():.2f}%]")
        
        # ------------------------------------------------------------------
        # Step 3: 训练模型
        # ------------------------------------------------------------------
        print("\n" + "=" * 40)
        print("Step 3/5: 训练ML模型")
        print("=" * 40)
        
        train_report = {
            "timestamp": datetime.now().isoformat(),
            "stock_count": len(all_data),
            "sample_count": int(X.shape[0]),
            "feature_count": int(X.shape[1]),
            "features": feature_names,
            "model_name": model_name,
            "label_type": label_type,
        }
        
        # 训练分类器
        print(f"\n📐 训练 {model_name.upper()} 分类器...")
        try:
            clf = self.trainer.train_classifier(
                X, y_class, model_name=model_name,
                tune_hyperparams=tune_hyperparams, cv_folds=cv_folds
            )
            
            # 交叉验证
            print("  🔄 交叉验证中...")
            cv_results = self.trainer.cross_validate(X, y_class, model_name, "classification", cv_folds)
            train_report["classifier_cv"] = cv_results
            
            # 评估
            y_pred_class = clf.predict(X)
            class_metrics = self.evaluator.evaluate_classification(y_class, y_pred_class)
            train_report["classifier_metrics"] = class_metrics
            
            print(f"  ✅ 分类器评估: {class_metrics}")
            
        except Exception as e:
            print(f"  ❌ 分类器训练失败: {e}")
            clf = None
        
        # 训练回归器
        print(f"\n📐 训练 {model_name.upper()} 回归器...")
        try:
            reg = self.trainer.train_regressor(
                X, y_reg, model_name=model_name,
                tune_hyperparams=tune_hyperparams, cv_folds=cv_folds
            )
            
            # 交叉验证
            print("  🔄 交叉验证中...")
            cv_results_reg = self.trainer.cross_validate(X, y_reg, model_name, "regression", cv_folds)
            train_report["regressor_cv"] = cv_results_reg
            
            # 评估
            y_pred_reg = reg.predict(X)
            reg_metrics = self.evaluator.evaluate_regression(y_reg, y_pred_reg)
            train_report["regressor_metrics"] = reg_metrics
            
            print(f"  ✅ 回归器评估: {reg_metrics}")
            
        except Exception as e:
            print(f"  ❌ 回归器训练失败: {e}")
            reg = None
        
        # ------------------------------------------------------------------
        # Step 4: IC/IR分析 & 分组回测
        # ------------------------------------------------------------------
        print("\n" + "=" * 40)
        print("Step 4/5: IC/IR分析 & 分组回测")
        print("=" * 40)
        
        if reg is not None:
            y_pred_reg = reg.predict(X)
            
            # IC/IR
            ic_results = self.evaluator.compute_ic_ir(y_pred_reg, y_reg)
            train_report["ic_analysis"] = ic_results
            print(f"  ✅ IC均值: {ic_results['ic_mean']:.4f}, IR: {ic_results['ir']:.4f}")
            
            # 分组回测
            group_results = self.evaluator.group_backtest(y_pred_reg, y_reg)
            train_report["group_backtest"] = group_results
            
            print(f"  ✅ 多空收益差: {group_results['long_short_spread']:.2f}%")
            for g_name, g_data in group_results["groups"].items():
                print(f"     {g_name}: 平均收益率={g_data['return_mean']:.2f}%, "
                      f"标准差={g_data['return_std']:.2f}%")
        
        # ------------------------------------------------------------------
        # Step 5: 特征重要性 & 保存模型
        # ------------------------------------------------------------------
        print("\n" + "=" * 40)
        print("Step 5/5: 特征重要性分析 & 保存模型")
        print("=" * 40)
        
        # 分类器特征重要性
        if clf is not None:
            top_features_clf = self.trainer.get_feature_importance(clf, feature_names, top_n=20)
            train_report["classifier_top_features"] = top_features_clf
            
            print("\n📊 分类器 Top10 重要特征:")
            for f in top_features_clf[:10]:
                bar = "█" * int(f["importance"] * 50)
                print(f"   {f['rank']:2d}. {f['feature']:25s} {bar} ({f['importance']:.4f})")
        
        # 回归器特征重要性
        if reg is not None:
            top_features_reg = self.trainer.get_feature_importance(reg, feature_names, top_n=20)
            train_report["regressor_top_features"] = top_features_reg
            
            print("\n📊 回归器 Top10 重要特征:")
            for f in top_features_reg[:10]:
                bar = "█" * int(f["importance"] * 50)
                print(f"   {f['rank']:2d}. {f['feature']:25s} {bar} ({f['importance']:.4f})")
        
        # 保存模型
        self.trainer.save_model(output_dir)
        
        # 保存特征重要性JSON
        importance_path = Path(output_dir) / "feature_importance.json"
        importance_data = {
            "timestamp": datetime.now().isoformat(),
            "model_classifier": top_features_clf if clf is not None else [],
            "model_regressor": top_features_reg if reg is not None else [],
            "feature_names": feature_names,
        }
        with open(importance_path, "w", encoding="utf-8") as f:
            json.dump(importance_data, f, ensure_ascii=False, indent=2)
        print(f"\n  ✅ 特征重要性已保存: {importance_path}")
        
        # 保存训练报告JSON
        report_path = Path(output_dir) / "train_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(train_report, f, ensure_ascii=False, indent=2, default=str)
        print(f"  ✅ 训练报告已保存: {report_path}")
        
        # 保存特征名列表（供预测时使用）
        feature_names_path = Path(output_dir) / "feature_names.json"
        with open(feature_names_path, "w", encoding="utf-8") as f:
            json.dump({"features": feature_names}, f, ensure_ascii=False, indent=2)
        
        print("\n" + "=" * 60)
        print("✅ 训练完成！")
        print("=" * 60)
        
        return train_report
    
    def predict(self, stock_names: Optional[List[str]] = None,
                top_n: int = 30, exclude_st: bool = True,
                min_market_cap: Optional[float] = None,
                max_market_cap: Optional[float] = None,
                compare_multi_factor: bool = False,
                output_dir: str = "./ml_output") -> Dict[str, Any]:
        """预测选股"""
        
        print("=" * 60)
        print("🎯 A股机器学习选股系统 - 预测模式")
        print("=" * 60)
        
        # 加载模型
        output_path = Path(output_dir)
        
        clf = None
        reg = None
        
        clf_path = output_path / "model_classifier.pkl"
        if clf_path.exists():
            clf = self.trainer.load_model(str(clf_path))
            print(f"  ✅ 分类器模型已加载: {clf_path}")
        else:
            print(f"  ⚠️ 未找到分类器模型，请先运行训练")
        
        reg_path = output_path / "model_regressor.pkl"
        if reg_path.exists():
            reg = self.trainer.load_model(str(reg_path))
            print(f"  ✅ 回归器模型已加载: {reg_path}")
        else:
            print(f"  ⚠️ 未找到回归器模型，请先运行训练")
        
        if clf is None and reg is None:
            raise RuntimeError("没有可用的模型，请先运行 'python ml_stock_picker.py train'")
        
        # 加载特征名
        feature_names_path = output_path / "feature_names.json"
        if feature_names_path.exists():
            with open(feature_names_path, "r", encoding="utf-8") as f:
                feature_names = json.load(f)["features"]
        else:
            raise RuntimeError("未找到特征名文件，请先运行训练")
        
        # 默认股票池
        if not stock_names:
            stock_names = [
                "贵州茅台", "宁德时代", "比亚迪", "东方财富", "招商银行",
                "中国平安", "五粮液", "恒瑞医药", "隆基绿能", "中信证券",
                "万科A", "美的集团", "格力电器", "海天味业", "药明康德",
                "立讯精密", "兆易创新", "中芯国际", "北方华创", "海康威视"
            ]
        
        # 执行选股
        result_df = self.selector.select_stocks(
            clf, reg, feature_names, stock_names,
            top_n=top_n, exclude_st=exclude_st,
            min_market_cap=min_market_cap, max_market_cap=max_market_cap
        )
        
        if result_df.empty:
            print("  ❌ 没有符合条件的股票")
            return {"top_stocks": []}
        
        # 输出结果
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # CSV输出
        csv_path = output_path / f"prediction_{timestamp}.csv"
        result_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"\n  ✅ 选股结果已保存: {csv_path}")
        
        # JSON输出
        json_result = {
            "timestamp": datetime.now().isoformat(),
            "total_stocks_evaluated": len(stock_names),
            "top_n": top_n,
            "filters": {
                "exclude_st": exclude_st,
                "min_market_cap": min_market_cap,
                "max_market_cap": max_market_cap
            },
            "top_stocks": result_df.to_dict(orient="records")
        }
        
        json_path = output_path / f"prediction_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_result, f, ensure_ascii=False, indent=2)
        print(f"  ✅ JSON结果已保存: {json_path}")
        
        # 打印TOP30列表
        print("\n" + "=" * 60)
        print("🏆 ML选股 TOP30:")
        print("=" * 60)
        print(f"{'排名':>4s} | {'股票名称':<12s} | {'分类得分':>8s} | {'回归得分':>8s} | {'综合得分':>8s}")
        print("-" * 55)
        
        for _, row in result_df.iterrows():
            print(f"{int(row['rank']):4d} | {str(row['stock_name']):<12s} | "
                  f"{float(row['class_score']):8.4f} | {float(row['regression_score']):8.4f} | "
                  f"{float(row['combined_score']):8.4f}")
        
        # 对比多因子选股结果
        if compare_multi_factor:
            print("\n" + "=" * 60)
            print("📊 ML选股 vs 多因子选股对比")
            print("=" * 60)
            
            try:
                mf_result = self._compare_with_multi_factor(stock_names, top_n)
                if mf_result:
                    ml_stocks = set(result_df["stock_name"].values)
                    mf_stocks = set(mf_result.get("top_stocks", []))
                    
                    overlap = ml_stocks & mf_stocks
                    ml_only = ml_stocks - mf_stocks
                    mf_only = mf_stocks - ml_stocks
                    
                    print(f"\n  ML选股独有: {len(ml_only)} 只")
                    for s in sorted(ml_only):
                        print(f"    - {s}")
                    
                    print(f"\n  多因子选股独有: {len(mf_only)} 只")
                    for s in sorted(mf_only):
                        print(f"    - {s}")
                    
                    print(f"\n  两者共同选中: {len(overlap)} 只")
                    for s in sorted(overlap):
                        print(f"    - {s}")
            except Exception as e:
                print(f"  ⚠️ 多因子对比失败: {e}")
        
        return json_result
    
    def _compare_with_multi_factor(self, stock_names: List[str], top_n: int) -> Optional[Dict]:
        """与multi-factor模块的多因子选股结果对比"""
        try:
            # 尝试导入multi_factor模块
            mf_paths = [
                Path(__file__).parent / "multi_factor.py",
                Path(__file__).parent.parent / "multi-factor" / "multi_factor.py",
            ]
            
            for p in mf_paths:
                if p.exists():
                    sys.path.insert(0, str(p.parent))
                    try:
                        from multi_factor import MultiFactorSelector
                        selector = MultiFactorSelector()
                        
                        result = selector.run_selection(
                            stock_names=stock_names[:20],  # 限制数量避免API超限
                            standardize_method="zscore",
                            weight_method="equal_weight",
                            top_n=top_n,
                            output_dir=str(Path("./ml_output"))
                        )
                        
                        return result
                    except ImportError:
                        continue
        except Exception as e:
            print(f"  ⚠️ multi-factor模块导入失败: {e}")
        
        return None
    
    def _fetch_daily_data(self, stock_name: str, days: int = 250) -> pd.DataFrame:
        """获取个股历史行情数据（腾讯前复权日线，免费公开接口）"""
        return _fetch_tx_daily(stock_name, days)


# ============================================================================
# CLI入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="A股机器学习选股系统 (ML Stock Picker)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 训练模型（默认250天数据）
  python ml_stock_picker.py train --days 250

  # 指定股票池和标签类型
  python ml_stock_picker.py train --stocks "贵州茅台,宁德时代" --label-type classification

  # 启用超参数调优
  python ml_stock_picker.py train --tune-hyperparams --cv-folds 5

  # XGBoost备选模型
  python ml_stock_picker.py train --model xgboost

  # 预测选股
  python ml_stock_picker.py predict --top_n 30 --exclude_st

  # 对比ML与多因子选股结果
  python ml_stock_picker.py predict --compare-multi-factor
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # train子命令
    train_parser = subparsers.add_parser("train", help="训练ML选股模型")
    train_parser.add_argument("--days", type=int, default=250, help="训练数据天数 (默认: 250)")
    train_parser.add_argument("--stocks", type=str, default=None,
                             help="股票池，逗号分隔 (例: '贵州茅台,宁德时代,比亚迪')")
    train_parser.add_argument("--stock-count", type=int, default=None,
                             help="从默认股票池随机选取N只 (默认: 全部20只)")
    train_parser.add_argument("--label-type", type=str, default="classification",
                             choices=["classification", "regression"],
                             help="标签类型 (默认: classification)")
    train_parser.add_argument("--return-days", type=int, default=1,
                             help="N日收益率标签的N值 (默认: 1)")
    train_parser.add_argument("--model", type=str, default="lightgbm",
                             choices=["lightgbm", "xgboost"],
                             help="模型类型 (默认: lightgbm)")
    train_parser.add_argument("--cv-folds", type=int, default=5,
                             help="交叉验证折数 (默认: 5)")
    train_parser.add_argument("--tune-hyperparams", action="store_true",
                             help="启用超参数调优（RandomSearch）")
    train_parser.add_argument("--output-dir", type=str, default="./ml_output",
                             help="输出目录 (默认: ./ml_output)")
    
    # predict子命令
    predict_parser = subparsers.add_parser("predict", help="预测选股")
    predict_parser.add_argument("--stocks", type=str, default=None,
                               help="股票池，逗号分隔")
    predict_parser.add_argument("--top-n", type=int, default=30,
                               help="输出前N只股票 (默认: 30)")
    predict_parser.add_argument("--exclude-st", action="store_true", default=True,
                               help="排除ST股票 (默认: True)")
    predict_parser.add_argument("--min-cap", type=float, default=None,
                               help="最小市值（亿元）")
    predict_parser.add_argument("--max-cap", type=float, default=None,
                               help="最大市值（亿元）")
    predict_parser.add_argument("--compare-multi-factor", action="store_true",
                               help="对比ML选股与多因子选股结果")
    predict_parser.add_argument("--output-dir", type=str, default="./ml_output",
                               help="输出目录 (默认: ./ml_output)")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # 初始化选股器（免费公开接口，无需 API Key）
    picker = MLStockPicker()
    
    if not HAS_LGB and not HAS_XGB:
        print("❌ lightgbm和xgboost均未安装，请先运行: pip install lightgbm xgboost")
        sys.exit(1)
    
    # 解析股票列表
    stock_names = None
    if hasattr(args, "stocks") and args.stocks:
        stock_names = [s.strip() for s in args.stocks.split(",") if s.strip()]
    elif hasattr(args, "stock_count") and args.stock_count:
        # 从默认股票池随机选取N只
        import random
        default_pool = [
            "贵州茅台", "宁德时代", "比亚迪", "东方财富", "招商银行",
            "中国平安", "五粮液", "恒瑞医药", "隆基绿能", "中信证券",
            "万科A", "美的集团", "格力电器", "海天味业", "药明康德",
            "立讯精密", "兆易创新", "中芯国际", "北方华创", "海康威视"
        ]
        stock_names = random.sample(default_pool, min(args.stock_count, len(default_pool)))
        print(f"  从默认股票池随机选取: {stock_names}")
    
    if args.command == "train":
        result = picker.train(
            days=args.days,
            stock_names=stock_names,
            label_type=args.label_type,
            model_name=args.model,
            return_days=args.return_days,
            tune_hyperparams=args.tune_hyperparams,
            cv_folds=args.cv_folds,
            output_dir=args.output_dir
        )
    
    elif args.command == "predict":
        result = picker.predict(
            stock_names=stock_names,
            top_n=args.top_n,
            exclude_st=args.exclude_st,
            min_market_cap=args.min_cap,
            max_market_cap=args.max_cap,
            compare_multi_factor=args.compare_multi_factor,
            output_dir=args.output_dir
        )


if __name__ == "__main__":
    main()
