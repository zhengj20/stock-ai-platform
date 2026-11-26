#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金流向选股策略 (Capital Flow Stock Selection)
================================================
基于主力资金流向、订单大小分类和量价关系进行智能选股。

核心逻辑：
  1. 主力净流入筛选（超大单+大单持续流入）
  2. 连续资金流入检测（N日持续净流入）
  3. 量价背离识别（价格上涨但资金流出=警示）
  4. 资金强度评分（综合多维度打分）

用法:
    python capital_flow.py scan --stocks "贵州茅台,宁德时代" --top_n 10
    python capital_flow.py continuous --stock 贵州茅台 --days 5
    python capital_flow.py divergence --stock 贵州茅台

依赖: pandas, numpy, requests
作者: Hermes Agent
版本: 1.0.0
"""

import sys
import json
import re
import time
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

import pandas as pd
import numpy as np
import requests


# ==================================================================
# 数据获取层：东方财富资金流向公开接口 + 腾讯K线（免费公开接口，无需任何 API Key）
# ==================================================================

_TX_KLINE_PATH = "/appstock/app/fqkline/get"
_TX_SMARTBOX_URL = "https://smartbox.gtimg.cn/s3/"
_TX_HOSTS = ["https://web.ifzq.gtimg.cn", "https://ifzq.gtimg.cn",
             "https://proxy.finance.qq.com/ifzqgtimg"]
_EM_FFLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


def _get(url: str, params: Dict[str, Any] = None, headers: Dict[str, str] = None,
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


def _safe_float(val) -> Optional[float]:
    """安全转换为float"""
    if val is None or val == "" or val == "-" or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        return float(str(val).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


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


def _norm_code(stock: str) -> Tuple[str, Optional[str]]:
    """归一化为 (6位代码, 显式symbol)；传名称时先检索代码"""
    s = str(stock).strip()
    m = re.fullmatch(r"(?i)(sh|sz|bj)?(\d{6})", s)
    if m:
        code = m.group(2)
        return code, (m.group(1).lower() + code) if m.group(1) else None
    return _resolve_code_by_name(s)


def _tx_symbol(code: str, symbol: str = None) -> str:
    """腾讯行情 symbol：6/5/9 沪，4/8 北交所，其余深市"""
    if symbol:
        return symbol
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def _secid(code: str, symbol: str = None) -> str:
    """东财 secid：1.=沪、0.=深"""
    if symbol:
        return f"{'1' if symbol[:2] == 'sh' else '0'}.{code}"
    return f"{'1' if code.startswith(('6', '5', '9')) else '0'}.{code}"


def _fetch_tx_kline(code: str, bars: int, symbol: str = None) -> List[list]:
    """腾讯K线（前复权日线）：日期,开盘,收盘,最高,最低,成交量(手)"""
    symbol = _tx_symbol(code, symbol)
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
    try:
        resp = _get(_EM_KLINE_URL, {
            "secid": _secid(code, symbol),
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


def fetch_kline(stock: str, days: int = 20) -> pd.DataFrame:
    """
    日K线（前复权，按日期升序）。

    列名沿用中文表头，便于下游按关键词取列：日期/开盘价/收盘价/最高价/最低价/成交量
    """
    code, symbol = _norm_code(stock)
    bars = max(int(days), 3)
    rows = _fetch_tx_kline(code, bars, symbol) or _fetch_em_kline(code, bars, symbol)
    if not rows:
        raise RuntimeError(f"未获取到 {stock} 的K线数据")
    df = pd.DataFrame(rows, columns=["日期", "开盘价", "收盘价", "最高价", "最低价", "成交量"])
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["收盘价"]).tail(bars).reset_index(drop=True)


def fetch_capital_flow(stock: str, days: int = 20) -> pd.DataFrame:
    """
    个股每日主力资金流向（东财资金流向历史，按日期升序，单位：元）。

    东财列序：日期,主力净流入,小单,中单,大单,超大单,主力净占比,...（后接收盘价/涨跌幅）
    """
    code, symbol = _norm_code(stock)
    resp = _get(_EM_FFLOW_URL, {
        "lmt": "0", "klt": "101",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "ut": _EM_UT, "secid": _secid(code, symbol),
    })
    klines = ((resp.json().get("data") or {}).get("klines")) or []
    rows = []
    for line in klines:
        f = line.split(",")
        if len(f) < 6:
            continue
        rows.append({
            "date": f[0],
            "main_net_inflow": _safe_float(f[1]),
            "small_order": _safe_float(f[2]),
            "medium_order": _safe_float(f[3]),
            "large_order": _safe_float(f[4]),
            "super_large_order": _safe_float(f[5]),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.dropna(subset=["main_net_inflow"]).tail(max(int(days), 1)).reset_index(drop=True)


# ==================================================================
# 资金流向分析引擎
# ==================================================================

class CapitalFlowAnalyzer:
    """资金流向分析器"""

    def get_main_force_flow(self, stock_name: str, days: int = 20) -> pd.DataFrame:
        """
        获取主力资金流向数据（东方财富资金流向历史，免费公开接口）

        Returns:
            DataFrame包含: date, main_net_inflow, super_large_order,
            large_order, medium_order, small_order（单位：元，按日期升序）
        """
        try:
            return fetch_capital_flow(stock_name, days)
        except Exception as e:
            print(f"  ⚠️ {stock_name} 资金流向获取失败: {e}")
            return pd.DataFrame()
    
    def calc_continuous_inflow(self, stock_name: str, days: int = 5) -> Dict[str, Any]:
        """
        连续资金流入检测
        
        Args:
            stock_name: 股票名称
            days: 检测连续天数
            
        Returns:
            包含连续流入天数的分析结果
        """
        flow_df = self.get_main_force_flow(stock_name, days + 5)
        
        if flow_df.empty or "main_net_inflow" not in flow_df.columns:
            return {
                "stock": stock_name,
                "continuous_days": 0,
                "total_inflow": 0,
                "signal": "无数据",
                "strength": 0
            }
        
        # 提取主力净流入列
        inflow_series = flow_df["main_net_inflow"].apply(_safe_float).dropna()
        
        if len(inflow_series) == 0:
            return {
                "stock": stock_name,
                "continuous_days": 0,
                "total_inflow": 0,
                "signal": "无有效数据",
                "strength": 0
            }
        
        # 计算连续净流入天数（从最新日期向前）
        continuous_days = 0
        total_inflow = 0.0
        
        for val in reversed(inflow_series):
            if val > 0:
                continuous_days += 1
                total_inflow += val
            else:
                break
        
        # 计算信号强度
        strength = min(100, continuous_days * 15 + (total_inflow / max(abs(total_inflow), 1)) * 20)
        
        if continuous_days >= days:
            signal = f"连续{continuous_days}日净流入（强势）"
        elif continuous_days >= 3:
            signal = f"连续{continuous_days}日净流入（偏强）"
        elif continuous_days >= 1:
            signal = f"连续{continuous_days}日净流入（一般）"
        else:
            signal = "资金净流出"
        
        return {
            "stock": stock_name,
            "continuous_days": continuous_days,
            "total_inflow": round(total_inflow, 2),
            "signal": signal,
            "strength": round(strength, 1)
        }
    
    def calc_price_flow_divergence(self, stock_name: str, days: int = 20) -> Dict[str, Any]:
        """
        量价背离检测
        
        逻辑：
          - 价格上涨 + 资金流入 = 健康上涨
          - 价格上涨 + 资金流出 = 顶背离（警示）
          - 价格下跌 + 资金流入 = 底背离（机会）
          - 价格下跌 + 资金流出 = 健康下跌
        
        Returns:
            包含背离类型和强度的分析结果
        """
        # 获取K线数据
        kline_df = self._fetch_kline(stock_name, days)
        flow_df = self.get_main_force_flow(stock_name, days)
        
        if kline_df.empty or flow_df.empty:
            return {
                "stock": stock_name,
                "divergence_type": "无数据",
                "price_trend": "未知",
                "flow_trend": "未知",
                "signal": "观望",
                "strength": 0
            }
        
        # 计算价格趋势（近5日 vs 前5日）
        close_col = self._find_column(kline_df, ["收盘", "最新价"])
        if not close_col:
            return {
                "stock": stock_name,
                "divergence_type": "无数据",
                "price_trend": "未知",
                "flow_trend": "未知",
                "signal": "观望",
                "strength": 0
            }
        
        closes = kline_df[close_col].apply(_safe_float).dropna()
        
        if len(closes) < 10:
            return {
                "stock": stock_name,
                "divergence_type": "数据不足",
                "price_trend": "未知",
                "flow_trend": "未知",
                "signal": "观望",
                "strength": 0
            }
        
        recent_5_avg = closes.tail(5).mean()
        prior_5_avg = closes.iloc[-10:-5].mean()
        price_change = (recent_5_avg - prior_5_avg) / prior_5_avg * 100
        
        # 计算资金流向趋势
        if "main_net_inflow" in flow_df.columns:
            inflows = flow_df["main_net_inflow"].apply(_safe_float).dropna()
            if len(inflows) >= 10:
                recent_flow = inflows.tail(5).sum()
                prior_flow = inflows.iloc[-10:-5].sum()
            else:
                recent_flow = inflows.tail(3).sum()
                prior_flow = inflows.head(max(3, len(inflows)//2)).sum()
        else:
            recent_flow = 0
            prior_flow = 0
        
        # 判断趋势方向
        price_up = price_change > 2  # 近5日涨幅>2%视为上涨
        flow_positive = recent_flow > 0 and recent_flow > abs(prior_flow)
        
        # 背离类型判定
        if price_up and flow_positive:
            divergence_type = "健康上涨"
            signal = "持有/买入（量价配合）"
            strength = min(100, abs(price_change) * 5 + 50)
        elif price_up and not flow_positive:
            divergence_type = "顶背离"
            signal = "减仓/观望（价格虚高）"
            strength = min(100, abs(price_change) * 3 + 40)
        elif not price_up and flow_positive:
            divergence_type = "底背离"
            signal = "关注/逢低买入（资金潜伏）"
            strength = min(100, abs(recent_flow) / max(abs(recent_flow), 1) * 50 + 40)
        else:
            divergence_type = "健康下跌"
            signal = "回避（量价齐跌）"
            strength = max(0, 30 - abs(price_change) * 2)
        
        return {
            "stock": stock_name,
            "divergence_type": divergence_type,
            "price_trend": f"{price_change:+.2f}%",
            "flow_trend": f"{'流入' if flow_positive else '流出'}",
            "recent_flow": round(recent_flow, 2),
            "signal": signal,
            "strength": round(strength, 1)
        }
    
    def calc_capital_strength_score(self, stock_name: str, days: int = 20) -> Dict[str, Any]:
        """
        资金强度综合评分
        
        评分维度：
          - 主力净流入占比 (40%)
          - 连续流入天数 (30%)
          - 超大单占比 (20%)
          - 量价配合度 (10%)
        
        Returns:
            综合评分(0-100)及分项得分
        """
        flow_df = self.get_main_force_flow(stock_name, days)
        
        if flow_df.empty:
            return {
                "stock": stock_name,
                "total_score": 0,
                "scores": {},
                "grade": "无数据"
            }
        
        scores = {}
        
        # 1. 主力净流入占比 (40%)
        if "main_net_inflow" in flow_df.columns:
            inflows = flow_df["main_net_inflow"].apply(_safe_float).dropna()
            positive_days = (inflows > 0).sum()
            total_days = len(inflows)
            inflow_ratio = positive_days / total_days if total_days > 0 else 0
            scores["主力净流入占比"] = round(inflow_ratio * 100 * 0.4, 2)
        else:
            scores["主力净流入占比"] = 0
        
        # 2. 连续流入天数 (30%)
        continuous_result = self.calc_continuous_inflow(stock_name, days=5)
        continuous_days = continuous_result.get("continuous_days", 0)
        continuous_score = min(100, continuous_days * 20) * 0.3
        scores["连续流入天数"] = round(continuous_score, 2)
        
        # 3. 超大单占比 (20%)
        if "super_large_order" in flow_df.columns:
            super_orders = flow_df["super_large_order"].apply(_safe_float).dropna()
            positive_super = (super_orders > 0).sum()
            total_super = len(super_orders)
            super_ratio = positive_super / total_super if total_super > 0 else 0
            scores["超大单占比"] = round(super_ratio * 100 * 0.2, 2)
        else:
            scores["超大单占比"] = 0
        
        # 4. 量价配合度 (10%)
        divergence_result = self.calc_price_flow_divergence(stock_name, days)
        div_type = divergence_result.get("divergence_type", "")
        if div_type == "健康上涨":
            scores["量价配合度"] = 10.0
        elif div_type == "底背离":
            scores["量价配合度"] = 7.0
        elif div_type == "顶背离":
            scores["量价配合度"] = 3.0
        else:
            scores["量价配合度"] = 5.0
        
        # 总分
        total_score = sum(scores.values())
        
        # 评级
        if total_score >= 70:
            grade = "A (强势)"
        elif total_score >= 55:
            grade = "B (偏强)"
        elif total_score >= 40:
            grade = "C (中性)"
        elif total_score >= 25:
            grade = "D (偏弱)"
        else:
            grade = "E (弱势)"
        
        return {
            "stock": stock_name,
            "total_score": round(total_score, 1),
            "scores": scores,
            "grade": grade
        }
    
    def _fetch_kline(self, stock_name: str, days: int) -> pd.DataFrame:
        """获取K线数据（腾讯行情主源、东财兜底，免费公开接口）"""
        try:
            return fetch_kline(stock_name, days)
        except Exception as e:
            print(f"  ⚠️ {stock_name} K线数据获取失败: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def _find_column(df: pd.DataFrame, keywords: List[str]) -> Optional[str]:
        """根据关键词查找列名"""
        for col in df.columns:
            c = str(col)
            for kw in keywords:
                if kw in c:
                    return col
        return None


# ==================================================================
# 选股执行器
# ==================================================================

class CapitalFlowSelector:
    """资金流向选股执行器"""

    def __init__(self):
        self.analyzer = CapitalFlowAnalyzer()
    
    def scan_stocks(self, stock_names: List[str], top_n: int = 10, 
                    min_score: float = 40.0) -> pd.DataFrame:
        """
        批量扫描股票资金流向
        
        Args:
            stock_names: 股票名称列表
            top_n: 输出前N只
            min_score: 最低评分阈值
            
        Returns:
            按资金强度排序的DataFrame
        """
        print(f"\n🔍 正在扫描 {len(stock_names)} 只股票的资金流向...")
        
        results = []
        
        for i, name in enumerate(stock_names):
            if (i + 1) % 10 == 0:
                print(f"  进度: {i+1}/{len(stock_names)}")
            
            try:
                score_result = self.analyzer.calc_capital_strength_score(name)
                
                if score_result["total_score"] >= min_score:
                    # 补充连续流入和背离信息
                    continuous = self.analyzer.calc_continuous_inflow(name, days=5)
                    divergence = self.analyzer.calc_price_flow_divergence(name, days=20)
                    
                    result_row = {
                        "stock": name,
                        "total_score": score_result["total_score"],
                        "grade": score_result["grade"],
                        "inflow_ratio": score_result["scores"].get("主力净流入占比", 0),
                        "continuous_days": continuous["continuous_days"],
                        "divergence_type": divergence["divergence_type"],
                        "signal": divergence["signal"]
                    }
                    results.append(result_row)
            
            except Exception as e:
                print(f"  ⚠️ {name} 分析失败: {e}")
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        df = df.sort_values("total_score", ascending=False).reset_index(drop=True)
        df["rank"] = range(1, len(df) + 1)
        
        return df.head(top_n)


# ==================================================================
# CLI入口
# ==================================================================

def main():
    parser = argparse.ArgumentParser(
        description="资金流向选股策略",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
用法示例:
  # 批量扫描股票池，按资金强度排序
  python capital_flow.py scan --stocks "贵州茅台,宁德时代,比亚迪" --top_n 10

  # 检测单只股票连续资金流入
  python capital_flow.py continuous --stock 贵州茅台 --days 5

  # 量价背离分析
  python capital_flow.py divergence --stock 贵州茅台

  # 综合评分
  python capital_flow.py score --stock 贵州茅台
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # scan子命令
    scan_parser = subparsers.add_parser("scan", help="批量扫描资金流向")
    scan_parser.add_argument("--stocks", type=str, required=True,
                            help="股票名称列表，逗号分隔")
    scan_parser.add_argument("--top_n", type=int, default=10,
                            help="输出前N只 (默认: 10)")
    scan_parser.add_argument("--min_score", type=float, default=40.0,
                            help="最低评分阈值 (默认: 40)")
    
    # continuous子命令
    cont_parser = subparsers.add_parser("continuous", help="连续资金流入检测")
    cont_parser.add_argument("--stock", type=str, required=True,
                            help="股票名称")
    cont_parser.add_argument("--days", type=int, default=5,
                            help="检测天数 (默认: 5)")
    
    # divergence子命令
    div_parser = subparsers.add_parser("divergence", help="量价背离分析")
    div_parser.add_argument("--stock", type=str, required=True,
                           help="股票名称")
    div_parser.add_argument("--days", type=int, default=20,
                           help="分析天数 (默认: 20)")
    
    # score子命令
    score_parser = subparsers.add_parser("score", help="资金强度综合评分")
    score_parser.add_argument("--stock", type=str, required=True,
                             help="股票名称")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        selector = CapitalFlowSelector()
        
        if args.command == "scan":
            stock_names = [s.strip() for s in args.stocks.split(",")]
            result_df = selector.scan_stocks(
                stock_names, 
                top_n=args.top_n,
                min_score=args.min_score
            )
            
            if result_df.empty:
                print("❌ 没有符合条件的股票")
                return
            
            print("\n" + "=" * 80)
            print("🏆 资金流向选股结果:")
            print("=" * 80)
            print(result_df.to_string(index=False))
            
        elif args.command == "continuous":
            result = selector.analyzer.calc_continuous_inflow(
                args.stock, days=args.days
            )
            print(f"\n📊 {args.stock} 连续资金流入分析:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
        elif args.command == "divergence":
            result = selector.analyzer.calc_price_flow_divergence(
                args.stock, days=args.days
            )
            print(f"\n📊 {args.stock} 量价背离分析:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
        elif args.command == "score":
            result = selector.analyzer.calc_capital_strength_score(args.stock)
            print(f"\n📊 {args.stock} 资金强度评分:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
    
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
