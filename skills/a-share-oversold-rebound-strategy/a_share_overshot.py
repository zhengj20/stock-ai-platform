#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股超跌反弹隔日短线选股策略 — 自动化执行脚本 v2.3

数据源：新浪财经（全市场列表+实时行情+指数） + 东方财富（分时K线/历史K线）
运行方式：
  python a_share_overshot.py screen          # 14:30 选股池推送
  python a_share_overshot.py closehold       # 9:45 平仓提醒
  python a_share_overshot.py test            # 测试数据接口连通性

依赖：pip install pandas requests
"""

import json
import random
import sys
import threading
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# 注册父级skills目录（用于导入 trading_utils 等共享模块）
_skills_dir = str(Path(__file__).parent.parent)
if _skills_dir not in sys.path:
    sys.path.insert(0, _skills_dir)

import pandas as pd
import requests

# ─── 日志配置 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2

# ─── HTTP Sessions ─────────────────────────────────────
sina_session = requests.Session()
sina_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
})

em_session = requests.Session()
em_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
})

# ─── 东财限流器（防封禁铁律：串行、间隔≥1s+随机抖动）───
_EM_LOCK = threading.Lock()
_EM_LAST_REQUEST = {"_time": 0.0}
EM_MIN_INTERVAL = 1.2  # 秒，可通过环境变量 EM_MIN_INTERVAL 调整

def _em_throttle():
    """东财串行限流: 间隔≥EM_MIN_INTERVAL + 随机抖动"""
    with _EM_LOCK:
        now = time.time()
        elapsed = now - _EM_LAST_REQUEST["_time"]
        if elapsed < EM_MIN_INTERVAL:
            sleep_time = EM_MIN_INTERVAL - elapsed + random.uniform(0.3, 1.5)
            time.sleep(sleep_time)
        _EM_LAST_REQUEST["_time"] = time.time()

def em_get(url, params=None, headers=None, timeout=15):
    """东财统一请求入口，内置限流"""
    merged_headers = dict(em_session.headers)
    if headers:
        merged_headers.update(headers)
    _em_throttle()
    return em_session.get(url, params=params, headers=merged_headers, timeout=timeout)

# ─── 配置常量 ──────────────────────────────────────────
POOL_FILE = Path(__file__).parent / "pool.json"
MAX_STOCKS = 10           # 最多推荐只数（从3提升到10）
MAX_SECTOR_COUNT = 2      # 同板块最多只数
DROP_MIN = -8.5           # 跌幅下限（-8.5%）
DROP_MAX = -4.0           # 跌幅上限（-4%，放宽范围以覆盖更多企稳标的）
MARKET_DROP_LIMIT = -3.0  # 大盘跌超3%触发环境过滤（放宽至-3%）
MIN_CIRC_CAP = 5e8        # 最小流通市值 5亿
MAX_CIRC_CAP = 2e11       # 最大流通市值 2000亿
CRASH_THRESHOLD = -15     # 暴雷史跌幅阈值（-15%）
CRASH_WINDOW_DAYS = 90    # 暴雷史检查窗口（天）

# ─── 企稳评分权重 ──────────────────────────────────────
STABILIZE_SCORE_WEIGHTS = {
    "lower_shadow":   30,   # 下影线长度（收盘远离日内低点）
    "volume_shrink":  25,   # 缩量下跌（卖压衰竭信号）
    "ma_support":     20,   # 接近均线支撑位
    "recent_trend":   15,   # 此前趋势非持续下跌
    "turnover_health": 10,   # 换手率健康区间
}
STABILIZE_MIN_SCORE = 60    # 企稳评分最低阈值（满分100）


# ─── API重试包装器 ─────────────────────────────────────

def api_call(fn, *args, **kwargs):
    """带指数退避重试的API调用包装器"""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_DELAY * attempt
                logger.warning(f"API调用失败 (尝试 {attempt}/{MAX_RETRIES}): {e}，{wait}s后重试...")
                time.sleep(wait)
    raise RuntimeError(f"API调用经{MAX_RETRIES}次重试仍失败: {last_err}") from last_err


# ═══════════════════════════════════════════════════════
#  数据源层 — 新浪财经（主） + 东方财富（分时/历史备用）
# ═══════════════════════════════════════════════════════

def fetch_spot_data() -> pd.DataFrame:
    """
    获取A股实时行情快照（新浪财经分页API，按涨跌幅升序）
    
    优化：按涨跌幅升序拉取，命中目标跌幅范围后继续收集直到超出范围。
    新浪返回的市值单位为"万元"。
    """
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"

    all_rows = []
    page = 1
    per_page = 80

    while True:
        params = {
            "page": page, "num": per_page,
            "sort": "changepercent", "asc": "1",
            "node": "hs_a", "_s_r_a": "cur",
        }
        r = sina_session.get(url, params=params, timeout=30)
        r.raise_for_status()

        items = json.loads(r.text.strip())
        if not items:
            break

        for item in items:
            all_rows.append({
                "code": str(item["code"]),
                "name": str(item["name"]),
                "price": float(item.get("trade", 0)),
                "pct_change": float(item.get("changepercent", 0)),
                "change_amt": float(item.get("pricechange", 0)),
                "open_price": float(item.get("open", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "volume": int(float(item.get("volume", 0))),
                "turnover": float(item.get("amount", 0)),
                "pe_dynamic": float(item["per"]) if item.get("per") and abs(float(item["per"])) < 1e6 else None,
                "pb": float(item.get("pb", 0)) or None,
                # 新浪返回的是"万元"为单位，转为元
                "total_market_cap": float(item.get("mktcap", 0)) * 1e4,
                "circ_market_cap": float(item.get("nmc", 0)) * 1e4,
                "turnover_rate": float(item.get("turnoverratio", 0)),
            })

        # 检查本页最小涨跌幅是否已超出目标范围（升序排列，最小值在页首）
        min_pct = min(float(it.get("changepercent", 0)) for it in items)
        if min_pct > DROP_MAX + 1:  # 超过-5%即可停止（留余量）
            logger.info(f"      第{page}页最小涨跌幅={min_pct}%，已超出筛选范围，提前终止")
            break

        if len(items) < per_page:
            break
        page += 1
        time.sleep(0.2)

    df = pd.DataFrame(all_rows)
    logger.info(f"获取行情数据: {len(df)} 只股票 (新浪财经, {page}页)")
    return df


def fetch_market_index() -> dict:
    """获取三大指数涨跌幅（新浪财经实时行情）"""
    # 注意：必须用 list= 拼接在URL中，不能用params传参
    url = "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006"
    r = sina_session.get(url, timeout=15)
    r.raise_for_status()

    result = {}
    name_map = {
        "sh000001": "上证指数",
        "sz399001": "深证成指",
        "sz399006": "创业板指",
    }
    # 格式: var hq_str_sh000001="上证指数,开盘,昨收,当前,最高,最低,...";
    for line in r.text.strip().split("\n"):
        if "=" not in line or line.startswith("//"):
            continue
        key = line.split("=")[0].replace("var hq_str_", "").strip()
        val_part = line.split("=")[1].strip().strip('";')
        parts = val_part.split(",")
        if len(parts) >= 4:
            name = name_map.get(key, key)
            prev_close = float(parts[2])
            current = float(parts[3])
            pct = round((current - prev_close) / prev_close * 100, 2)
            result[name] = pct

    return result


def fetch_stock_minute(code: str) -> pd.DataFrame:
    """
    获取个股分时数据（东方财富API）
    
    code格式: 6位纯数字，如 '600519'
    前缀规则: 沪市(6xxxxx)→1., 深市(0xxxxx/3xxxxx)→0.
    
    注意：东方财富分时数据分隔符为逗号, 格式为 "日期时间,价格,开盘,最高,最低,成交量,成交额,振幅"
    """
    prefix = "1" if code.startswith("6") else "0"
    secid = f"{prefix}.{code}"

    url = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "iscr": "0", "ndays": "1",
    }
    r = em_get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    s_data = data.get("data", {}).get("trends", [])
    if not s_data:
        return pd.DataFrame()

    rows = []
    for item in s_data:
        # 东方财富分时数据格式: "2026-06-24 15:00,40.51,40.54,40.54,40.51,961,3897559.00,42.510"
        parts = item.split(",")
        if len(parts) >= 7:
            datetime_str = parts[0].strip()
            try:
                time_part = datetime_str.split(" ")[-1] if " " in datetime_str else datetime_str
                rows.append({
                    "time": pd.to_datetime(time_part, format="%H:%M", errors="coerce"),
                    "price": float(parts[1]),
                    "open_p": float(parts[2]) if len(parts) > 2 else 0,
                    "high_p": float(parts[3]) if len(parts) > 3 else 0,
                    "low_p": float(parts[4]) if len(parts) > 4 else 0,
                    "volume": int(float(parts[5])) if len(parts) > 5 else 0,
                })
            except (ValueError, IndexError):
                continue

    df = pd.DataFrame(rows)
    return df


def fetch_stock_history(code: str, days: int = 90) -> pd.DataFrame:
    """获取个股日K历史（新浪财经API）"""
    # 确定市场前缀
    prefix = "sh" if code.startswith("6") else "sz"
    symbol = f"{prefix}{code}"

    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": symbol,
        "scale": "240",   # 日K
        "ma": "false",
        "datalen": str(days),
    }
    r = sina_session.get(url, params=params, timeout=15)
    r.raise_for_status()

    klines = json.loads(r.text.strip())
    if not klines:
        return pd.DataFrame()

    rows = []
    for item in klines:
        try:
            close_p = float(item["close"])
            open_p = float(item["open"])
            rows.append({
                "date": item["day"],
                "open_p": open_p,
                "close_p": close_p,
                "high_p": float(item["high"]),
                "low_p": float(item["low"]),
                "volume": int(float(item["volume"])),
            })
        except (KeyError, ValueError):
            continue

    df = pd.DataFrame(rows)
    if not df.empty:
        # 计算涨跌幅
        df["pct_change"] = df["close_p"].pct_change() * 100
    return df


def fetch_sector_for_stock(code: str, spot_df: pd.DataFrame) -> str:
    """获取个股所属行业板块（东方财富API）"""
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        prefix = "1" if code.startswith("6") else "0"
        params = {
            "secid": f"{prefix}.{code}",
            "fields": "f57,f124",  # f57=所属行业, f124=所属概念
            "ut": "fa5fd1943c7b386f172d6893dbbd1",
        }
        r = em_get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", {})
            sector = data.get("f57", "") or data.get("f124", "")
            if sector and str(sector) != "nan":
                return str(sector)
    except Exception as e:
        logger.debug(f"获取 {code} 板块信息失败: {e}")

    # 备用：从新浪数据中推断（通过代码前缀）
    if code.startswith("68"):
        return "科创板"
    elif code.startswith("30"):
        return "创业板"
    elif code.startswith("6"):
        return "沪市主板"
    else:
        return "深市主板"


# ═══════════════════════════════════════════════════════
#  策略逻辑层
# ═══════════════════════════════════════════════════════

def is_trading_day(dt: datetime) -> bool:
    """判断是否为交易日（通过腾讯财经API，含节假日排除）"""
    from trading_utils import is_trading_day as _api_is_trading_day
    return _api_is_trading_day()


def has_recent_crash(code: str) -> bool:
    """检查近3个月是否有单日跌幅超15%的暴雷史"""
    try:
        hist = fetch_stock_history(code, days=CRASH_WINDOW_DAYS)
        if not hist.empty and "pct_change" in hist.columns:
            return (hist["pct_change"] < CRASH_THRESHOLD).any()
    except Exception as e:
        logger.debug(f"检查 {code} 暴雷史失败: {e}")
    return False


def calculate_stabilize_score(row: pd.Series, hist_df: pd.DataFrame) -> tuple:
    """
    综合企稳评分系统（满分100分，≥60分为企稳）
    
    不依赖东方财富分时接口，全部使用新浪实时行情 + 历史K线数据。
    
    评分维度：
    1. 下影线长度 (30分) — 收盘远离日内低点 = 卖压衰竭信号
    2. 缩量下跌 (25分) — 今日成交量 < 近5日均量 = 抛盘枯竭
    3. 均线支撑 (20分) — 价格接近/站上MA20/MA60 = 技术支撑位
    4. 近期趋势 (15分) — 此前非持续下跌 = 非弱势股
    5. 换手率健康 (10分) — 换手率在合理区间 = 有资金承接
    
    Returns: (score, details_dict)
    """
    score = 0
    details = {}

    # ── 维度1: 下影线长度 (30分) ──
    try:
        close_p = float(row.get("price", 0))       # 今日最新价(收盘)
        low_p = float(row.get("low", 0))            # 今日最低
        high_p = float(row.get("high", 0))          # 今日最高
        open_p = float(row.get("open_price", 0))    # 今日开盘
        
        if low_p > 0 and (high_p - low_p) > 0:
            # 下影线占比 = (收盘-最低)/(最高-最低)，越大说明尾盘越强势
            lower_shadow_ratio = (close_p - low_p) / (high_p - low_p)
            
            if lower_shadow_ratio >= 0.6:
                shadow_score = 30
            elif lower_shadow_ratio >= 0.45:
                shadow_score = 25
            elif lower_shadow_ratio >= 0.3:
                shadow_score = 18
            elif lower_shadow_ratio >= 0.2:
                shadow_score = 10
            else:
                shadow_score = 3
            
            # 额外加分：长下影线 + 跌幅收窄（收盘接近开盘）
            if open_p > 0 and abs(close_p - open_p) / open_p < 0.01:
                shadow_score += 5  # 十字星形态，多空平衡
            
            score += min(shadow_score, 30)
            details["lower_shadow"] = f"{shadow_score}/30 (下影线占比{lower_shadow_ratio:.0%})"
        else:
            details["lower_shadow"] = "0/30 (数据不足)"
    except Exception as e:
        score += 5  # 保底分
        details["lower_shadow"] = f"5/30 (计算异常: {e})"

    # ── 维度2: 缩量下跌 (25分) ──
    try:
        today_vol = float(row.get("volume", 0))
        
        if not hist_df.empty and len(hist_df) >= 5:
            recent_vols = hist_df["volume"].tail(5).values[:4]  # 前4天（不含今天）
            avg_vol_5d = recent_vols.mean() if len(recent_vols) > 0 else today_vol
            
            if avg_vol_5d > 0:
                vol_ratio = today_vol / avg_vol_5d
                
                if vol_ratio <= 0.6:
                    vol_score = 25   # 明显缩量，卖压衰竭
                elif vol_ratio <= 0.8:
                    vol_score = 20   # 温和缩量
                elif vol_ratio <= 1.0:
                    vol_score = 15   # 持平
                elif vol_ratio <= 1.3:
                    vol_score = 10   # 微放量
                else:
                    vol_score = 3    # 放量下跌，危险信号
                
                score += vol_score
                details["volume_shrink"] = f"{vol_score}/25 (量比{vol_ratio:.2f})"
            else:
                details["volume_shrink"] = "10/25 (均量为0)"
        else:
            # 无历史数据，给中等分
            score += 10
            details["volume_shrink"] = "10/25 (无历史量数据)"
    except Exception as e:
        score += 8
        details["volume_shrink"] = f"8/25 (计算异常)"

    # ── 维度3: 均线支撑 (20分) ──
    try:
        if not hist_df.empty and len(hist_df) >= 20:
            close_series = hist_df["close_p"].values
            
            ma5 = close_series[-1] if len(close_series) >= 1 else 0
            ma10 = close_series[-10:].mean() if len(close_series) >= 10 else 0
            ma20 = close_series[-20:].mean() if len(close_series) >= 20 else 0
            ma60 = close_series[-60:].mean() if len(close_series) >= 60 else 0
            
            current_price = float(row.get("price", 0))
            
            # 检查价格是否接近均线支撑（±1%范围内）
            support_score = 0
            near_supports = []
            
            for ma_name, ma_val in [("MA5", ma5), ("MA10", ma10), ("MA20", ma20), ("MA60", ma60)]:
                if ma_val > 0:
                    dist_pct = abs(current_price - ma_val) / ma_val * 100
                    if dist_pct <= 1.5:
                        support_score += 8
                        near_supports.append(ma_name)
                    elif dist_pct <= 3:
                        support_score += 4
            
            # 额外加分：价格站上MA20或MA60
            if ma20 > 0 and current_price >= ma20:
                support_score += 5
            if ma60 > 0 and current_price >= ma60:
                support_score += 3
            
            score += min(support_score, 20)
            supports_str = ",".join(near_supports) if near_supports else "无"
            details["ma_support"] = f"{min(support_score,20)}/20 (接近{supports_str})"
        else:
            score += 8
            details["ma_support"] = "8/20 (均线数据不足)"
    except Exception as e:
        score += 5
        details["ma_support"] = f"5/20 (计算异常)"

    # ── 维度4: 近期趋势 (15分) ──
    try:
        if not hist_df.empty and len(hist_df) >= 10:
            pct_changes = hist_df["pct_change"].dropna().tail(10).values
            
            # 统计近10天涨跌天数
            up_days = sum(1 for p in pct_changes if p > 0)
            down_days = sum(1 for p in pct_changes if p < 0)
            
            # 检查是否有连续暴跌（3天以上连跌）
            max_consecutive_down = 0
            current_streak = 0
            for p in pct_changes:
                if p < -2:
                    current_streak += 1
                    max_consecutive_down = max(max_consecutive_down, current_streak)
                else:
                    current_streak = 0
            
            # 评分逻辑
            trend_score = 15  # 基础分
            
            # 连跌超过3天扣分（弱势股）
            if max_consecutive_down >= 5:
                trend_score -= 12
            elif max_consecutive_down >= 3:
                trend_score -= 6
            
            # 近5天有涨有跌加分（震荡非单边下跌）
            recent_5 = pct_changes[-5:] if len(pct_changes) >= 5 else pct_changes
            recent_up = sum(1 for p in recent_5 if p > 0)
            if 2 <= recent_up <= 3:
                trend_score += 3
            
            score += max(trend_score, 0)
            details["recent_trend"] = f"{max(trend_score,0)}/15 (近10天{up_days}涨{down_days}跌,最大连跌{max_consecutive_down}天)"
        else:
            score += 8
            details["recent_trend"] = "8/15 (趋势数据不足)"
    except Exception as e:
        score += 5
        details["recent_trend"] = f"5/15 (计算异常)"

    # ── 维度5: 换手率健康 (10分) ──
    try:
        turnover = float(row.get("turnover_rate", 0))
        
        if 2 <= turnover <= 15:
            tr_score = 10   # 正常活跃区间
        elif 1 <= turnover < 2 or 15 < turnover <= 25:
            tr_score = 6    # 偏低或偏高
        elif turnover > 25:
            tr_score = 2    # 异常高换手，可能是出货
        else:
            tr_score = 4    # 过低换手
        
        score += tr_score
        details["turnover_health"] = f"{tr_score}/10 (换手率{turnover:.1f}%)"
    except Exception as e:
        score += 5
        details["turnover_health"] = "5/10 (计算异常)"

    return score, details


def is_st_stock(name: str, code: str) -> bool:
    """判断是否为ST/*ST/退市风险股票"""
    name_lower = name.lower()
    return "st" in name_lower or "*st" in name_lower or "退" in name


# ─── 选股主流程 ────────────────────────────────────────

def screen_stocks() -> list[dict]:
    """执行选股策略，返回候选股票列表"""
    now = datetime.now()

    if not is_trading_day(now):
        logger.info("今日非交易日，跳过选股")
        return [{"error": "今日非交易日"}]

    # ── Step 0: 获取全市场数据 ──
    logger.info("[1/6] 获取实时行情...")
    spot_df = api_call(fetch_spot_data)

    if spot_df.empty:
        return [{"recommendation": "今日不推荐", "reason": "无法获取行情数据"}]

    # ── Step 1: 大盘环境检查 ──
    logger.info("[2/6] 检查大盘环境...")
    try:
        indices = fetch_market_index()
    except Exception as e:
        logger.warning(f"指数获取失败 ({e})，跳过大盘环境检查")
        indices = {}
    logger.info(f"      指数涨跌: {indices}")

    market_bad = any(pct < MARKET_DROP_LIMIT for pct in indices.values()) if indices else False
    if market_bad:
        has_stabilize = any(pct > -1 for pct in indices.values())
        if not has_stabilize:
            reason = f"大盘环境较差，{', '.join(f'{k}{v}%' for k,v in indices.items())}，建议观望"
            logger.warning(reason)
            return [{"recommendation": "今日不推荐", "reason": reason}]

    # ── Step 2: 跌幅初筛 ──
    logger.info("[3/6] 筛选跌幅6%-8%的个股...")
    candidates = spot_df[
        (spot_df["pct_change"] <= DROP_MAX) &   # ≤ -6%
        (spot_df["pct_change"] >= DROP_MIN)      # ≥ -8%
    ].copy()
    logger.info(f"      初筛 {len(candidates)} 只")

    if candidates.empty:
        return [{"recommendation": "今日不推荐", "reason": "无跌幅6%-8%的个股"}]

    # ── Step 3: ST/跌停过滤 ──
    before = len(candidates)
    candidates = candidates[~candidates.apply(
        lambda r: is_st_stock(r["name"], r["code"]), axis=1)]
    logger.info(f"[4/6] ST过滤: {before} → {len(candidates)} 只")

    # 排除跌幅≤-10%（跌停板）
    before = len(candidates)
    candidates = candidates[candidates["pct_change"] > -10]
    logger.info(f"      跌停过滤: {before} → {len(candidates)} 只")

    # ── Step 4: 流通市值过滤 ──
    before = len(candidates)
    candidates = candidates[
        (candidates["circ_market_cap"] >= MIN_CIRC_CAP) &
        (candidates["circ_market_cap"] <= MAX_CIRC_CAP)
    ]
    logger.info(f"[5/6] 市值过滤({MIN_CIRC_CAP/1e8}-{MAX_CIRC_CAP/1e8}亿): {before} → {len(candidates)} 只")

    if candidates.empty:
        return [{"recommendation": "今日不推荐", "reason": "跌幅区间内无符合市值条件的个股"}]

    # ── Step 5: 深度筛选（暴雷史 + 尾盘企稳 + 板块分散）──
    logger.info("[6/6] 深度筛选候选股票...")
    final_pool = []
    sector_count = {}
    deep_check_limit = min(30, len(candidates))

    for i, (idx, row) in enumerate(candidates.iterrows()):
        if len(final_pool) >= MAX_STOCKS:
            break
        if i >= deep_check_limit:
            logger.info(f"      已达深度检查上限({deep_check_limit})，停止筛选")
            break

        code = str(row.get("code", ""))
        name = str(row.get("name", ""))
        price = round(float(row.get("price", 0)), 2)
        pct = round(float(row["pct_change"]), 2)

        logger.info(f"      [{i+1}/{deep_check_limit}] 检查 {code} {name} (跌幅{pct}%)...")

        # 暴雷史检查
        crashed = has_recent_crash(code)
        if crashed:
            logger.info(f"         ✗ 近3个月有暴雷史，排除")
            continue

        # 尾盘企稳检查
        stabilized = check_tail_stabilize(code)
        logger.info(f"         {'✓' if stabilized else '○'} 尾盘{'已' if stabilized else '未'}企稳")

        # 板块分散
        sector = fetch_sector_for_stock(code, spot_df)
        current_sector_count = sector_count.get(sector, 0)
        if current_sector_count >= MAX_SECTOR_COUNT:
            logger.info(f"         ✗ 板块{sector}已达上限，排除")
            continue

        # 构建推荐理由
        reasons = [f"跌幅{pct}%处于超跌区间"]
        if stabilized:
            reasons.append("尾盘出现企稳信号")
        else:
            reasons.append("需关注尾盘走势确认企稳")

        final_pool.append({
            "code": code,
            "name": name,
            "price": price,
            "pct_change": pct,
            "sector": sector,
            "stabilized": stabilized,
            "logic": "；".join(reasons),
        })
        sector_count[sector] = current_sector_count + 1

    logger.info(f"最终选出 {len(final_pool)} 只")
    return final_pool


# ═══════════════════════════════════════════════════════
#  输出格式化 & 持久化
# ═══════════════════════════════════════════════════════

def format_stock_pool(pool: list[dict]) -> str:
    """格式化为选股池推送文本"""
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")

    if not pool or "error" in (pool[0] if pool else {}) or "recommendation" in (pool[0] if pool else {}):
        reason = ""
        if pool:
            reason = pool[0].get("reason", pool[0].get("error", "数据异常"))
        return f"""【{date_str} 隔日超跌反弹大概率高开股票池】

今日不推荐
原因：{reason or '无符合条件标的'}

⚠️ 本策略仅供参考，不构成投资建议。股市有风险，入市需谨慎。"""

    lines = [f"【{date_str} 隔日超跌反弹大概率高开股票池】\n"]
    for i, stock in enumerate(pool, 1):
        stabilize_tag = "✓企稳" if stock.get("stabilized") else "○待确认"
        lines.append(
            f"{i}. 代码：{stock['code']} | "
            f"名称：{stock['name']} | "
            f"当前价格：{stock['price']}元 | "
            f"跌幅：{stock['pct_change']}% | "
            f"板块：{stock['sector']} | "
            f"尾盘信号：{stabilize_tag} | "
            f"简要逻辑：{stock['logic']}"
        )

    lines.append(f"\n共 {len(pool)} 只候选股票")
    lines.append("\n⚠️ 明日9:45将推送平仓提醒，请及时操作。")
    lines.append("⚠️ 本策略仅供参考，不构成投资建议。股市有风险，入市需谨慎。")

    return "\n".join(lines)


def format_close_reminder(pool_data: list[dict]) -> str:
    """格式化为平仓提醒文本"""
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")

    if not pool_data:
        return f"【{date_str} 09:45 平仓提示】\n\n无持仓需要平仓。"

    lines = [f"【{date_str} 09:45 平仓提示】\n"]

    total_pnl_pct = 0
    count = 0
    for i, stock in enumerate(pool_data, 1):
        buy_price = stock["buy_price"]
        current_price = stock.get("current_price", buy_price)
        pnl_pct = round((current_price - buy_price) / buy_price * 100, 2)
        pnl_amt = round(current_price - buy_price, 2)

        pnl_str = f"+{pnl_pct}%（+{pnl_amt}元/股）" if pnl_pct >= 0 else f"{pnl_pct}%（{pnl_amt}元/股）"

        lines.append(
            f"{i}. 代码：{stock['code']} | "
            f"名称：{stock['name']} | "
            f"买入价：{buy_price}元 | "
            f"当前价：{current_price}元 | "
            f"盈亏：{pnl_str} | "
            f"建议：平仓"
        )

        total_pnl_pct += pnl_pct
        count += 1

    if count > 0:
        avg_pnl = round(total_pnl_pct / count, 2)
        lines.append(f"\n综合盈亏均值：{'+' if avg_pnl >= 0 else ''}{avg_pnl}%")

    lines.append("\n⚠️ 请及时执行平仓操作，避免隔夜风险。")
    return "\n".join(lines)


def save_pool(pool: list[dict]):
    """保存选股池到本地JSON"""
    data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M:%S"),
        "stocks": pool,
    }
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"选股池已保存至 {POOL_FILE}")


def load_pool() -> list[dict]:
    """加载上次选股池"""
    if not POOL_FILE.exists():
        return []
    with open(POOL_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("stocks", [])


def close_holdings(pool_file: Optional[str] = None):
    """获取当前价格并生成平仓提醒"""
    if pool_file:
        pf = Path(pool_file)
        with open(pf, "r", encoding="utf-8") as f:
            pool_data = json.load(f).get("stocks", [])
    else:
        pool_data = load_pool()

    if not pool_data:
        logger.info("无持仓数据，跳过平仓提醒。")
        return format_close_reminder([])

    logger.info("获取实时行情更新当前价...")
    spot_df = fetch_spot_data()

    updated = []
    for stock in pool_data:
        code = str(stock["code"])
        row = spot_df[spot_df["code"] == code] if "code" in spot_df.columns else pd.DataFrame()

        if not row.empty and "price" in row.columns:
            current_price = round(float(row.iloc[0]["price"]), 2)
        else:
            current_price = stock.get("price", 0)
            logger.warning(f"{code} ({stock['name']}) 未获取到实时价格，使用买入价")

        updated.append({
            "code": code,
            "name": stock["name"],
            "buy_price": stock["price"],
            "current_price": current_price,
        })

    return format_close_reminder(updated)


# ═══════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1]

    try:
        if command == "screen":
            pool = screen_stocks()
            output = format_stock_pool(pool)
            save_pool(pool)
            print("\n" + "=" * 60)
            print(output)
            print("=" * 60)

        elif command == "closehold":
            pf = None
            if len(sys.argv) >= 3 and sys.argv[2].startswith("--file="):
                pf = sys.argv[2].split("=", 1)[1]
            output = close_holdings(pf)
            print("\n" + "=" * 60)
            print(output)
            print("=" * 60)

        elif command == "test":
            logger.info("=== 数据接口连通性测试 ===")
            
            # 1. 实时行情
            try:
                df = fetch_spot_data()
                print(f"  ✓ 实时行情: {len(df)} 只股票")
                sample = df.head(3)[["code", "name", "price", "pct_change"]]
                print(f"    示例:\n{sample.to_string(index=False)}")
            except Exception as e:
                print(f"  ✗ 实时行情失败: {e}")

            # 2. 指数数据
            try:
                idx = fetch_market_index()
                if idx:
                    print(f"  ✓ 指数数据: {idx}")
                else:
                    print(f"  ○ 指数数据为空（可能非交易时段）")
            except Exception as e:
                print(f"  ✗ 指数数据失败: {e}")

            # 3. 交易日判断
            try:
                td = is_trading_day(datetime.now())
                print(f"  {'✓' if td else '○'} 今日{'是' if td else '不是'}交易日")
            except Exception as e:
                print(f"  ✗ 交易日判断失败: {e}")

        else:
            print(f"[ERROR] 未知命令: {command}")
            print(__doc__)
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"执行失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
