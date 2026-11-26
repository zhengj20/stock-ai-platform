#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股板块轮动追踪工具
基于免费公开接口（新浪板块行情 + 腾讯指数行情）实现行业/概念板块行情分析与热点切换跟踪

功能模块:
  overview  - 板块行情总览
  strength  - 板块强度排名
  hot       - 热点题材追踪
  signals   - 轮动信号检测

用法:
  python sector_rotation.py overview [--type industry|concept] [--top N]
  python sector_rotation.py strength [--period 20|60]
  python sector_rotation.py hot      [--top N]
  python sector_rotation.py signals

数据源:
  - 行业板块: 新浪 http://money.finance.sina.com.cn/q/view/newSinaHy.php (49个行业)
  - 概念板块: 新浪 http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class (170+个概念)
  - 指数行情: 腾讯 https://qt.gtimg.cn (沪深300/中证1000/创业板指/上证指数)

说明: 免费接口仅提供板块当日涨跌幅/成交额/领涨股等截面数据；
板块资金流向、5日/10日涨跌、换手率、涨跌家数、历史行情无免费数据源，相关模块已移除。

依赖: numpy, requests
"""

import sys
import json
import time
import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import numpy as np
import requests

# ============================================================================
# 免费公开数据层（新浪板块 + 腾讯指数），文件内自包含
# ============================================================================

_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
_SINA_INDUSTRY_URL = "http://money.finance.sina.com.cn/q/view/newSinaHy.php"
_SINA_CONCEPT_URL = "http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class"
_TX_QUOTE_URL = "https://qt.gtimg.cn/q="


def _get(url: str, headers: Dict = None, retries: int = 3) -> requests.Response:
    """请求公开接口，带退避重试（行情源偶发直接断连）"""
    merged = dict(_HEADERS)
    if headers:
        merged.update(headers)
    last_err = None
    for attempt in range(retries):
        try:
            return requests.get(url, headers=merged, timeout=20)
        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"接口请求失败: {url} -> {last_err}")


def _safe_float(val) -> Optional[float]:
    """安全转浮点，失败返回 None"""
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(str(val).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def _parse_sina_sectors(url: str, var_key: str) -> List[Dict[str, Any]]:
    """
    抓取并解析新浪板块全量行情（行业/概念同一格式，一次拉全量）。

    返回字段:
      code/name/stock_count/avg_price/avg_change/change_pct/
      volume(股)/amount(元)/leader_code/leader_pct/leader_price/leader_name
    """
    resp = _get(url)
    resp.encoding = "gbk"
    m = re.search(r"var\s+" + var_key + r"\s*=", resp.text)
    if not m:
        raise RuntimeError(f"新浪板块数据格式异常: {url}")
    body = resp.text[m.end():]
    body = body[body.index("{"): body.rindex("}") + 1]
    raw = json.loads(body)

    sectors = []
    for code, line in raw.items():
        parts = str(line).split(",")
        if len(parts) < 13:
            continue
        sectors.append({
            "code": code,
            "name": parts[1],
            "stock_count": int(_safe_float(parts[2]) or 0),
            "avg_price": _safe_float(parts[3]),
            "avg_change": _safe_float(parts[4]),
            "change_pct": _safe_float(parts[5]),
            "volume": _safe_float(parts[6]),
            "amount": _safe_float(parts[7]),
            "leader_code": parts[8],
            "leader_pct": _safe_float(parts[9]),
            "leader_price": _safe_float(parts[10]),
            "leader_name": parts[12],
        })
    return sectors


def _fetch_tx_indices(symbols: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """
    腾讯实时指数行情（一次请求多只，GBK编码）。

    symbols: {名称: 腾讯symbol}；返回 {名称: {name, latest_price, change_pct}}
    """
    query = ",".join(symbols.values())
    resp = _get(_TX_QUOTE_URL + query, {"Referer": "https://gu.qq.com/"})
    resp.encoding = "gbk"
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for line in resp.text.split(";"):
        line = line.strip()
        if "=" not in line or '"' not in line:
            continue
        sym = line.split("=", 1)[1].strip().strip('"')
        fields = sym.split("~")
        if len(fields) > 32:
            by_symbol[fields[2]] = {
                "name": fields[1],
                "latest_price": _safe_float(fields[3]),
                "change_pct": _safe_float(fields[32]),
            }
    out: Dict[str, Dict[str, Any]] = {}
    for name, sym in symbols.items():
        item = by_symbol.get(sym[2:]) or {}
        out[name] = {
            "name": name,
            "latest_price": item.get("latest_price"),
            "change_pct": item.get("change_pct"),
        }
    return out


# ============================================================================
# 板块与风格定义（使用新浪行业实际名称）
# ============================================================================

# 风格指数（腾讯 symbol）
STYLE_INDICES = {
    "沪深300": "sh000300",
    "中证1000": "sh000852",
    "创业板指": "sz399006",
    "上证指数": "sh000001",
}

# 防御型 vs 进攻型行业分类
DEFENSIVE_SECTORS = ["金融行业", "电力行业", "供水供气", "食品行业", "酿酒行业", "生物制药", "煤炭行业"]
OFFENSIVE_SECTORS = ["电子器件", "电子信息", "传媒娱乐", "发电设备", "机械行业", "飞机制造", "船舶制造"]

# 成长型 vs 价值型行业分类
GROWTH_SECTORS = ["电子器件", "电子信息", "发电设备", "生物制药", "医疗器械", "飞机制造"]
VALUE_SECTORS = ["金融行业", "煤炭行业", "石油行业", "钢铁行业", "建筑建材", "水泥行业", "房地产"]

# ============================================================================
# 工具函数
# ============================================================================

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


def format_pct(val: Optional[float]) -> str:
    """格式化百分比显示"""
    if val is None:
        return "-"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.2f}%"


def color_pct(val: Optional[float]) -> str:
    """带颜色的百分比(终端ANSI颜色)"""
    s = format_pct(val)
    if val is None:
        return s
    if val > 0:
        return f"\033[91m{s}\033[0m"  # 红涨（A股惯例）
    elif val < 0:
        return f"\033[92m{s}\033[0m"  # 绿跌
    return s


def print_table(headers: List[str], rows: List[List[str]], col_widths: Optional[List[int]] = None):
    """打印格式化表格"""
    if not col_widths:
        col_widths = []
        for i, h in enumerate(headers):
            max_w = len(str(h))
            for row in rows:
                if i < len(row):
                    max_w = max(max_w, len(str(row[i])))
            col_widths.append(min(max_w + 2, 30))

    header_line = ""
    for i, h in enumerate(headers):
        w = col_widths[i] if i < len(col_widths) else 15
        header_line += f" {str(h):<{w}}"
    print(header_line)
    print("-" * len(header_line.encode()))

    for row in rows:
        line = ""
        for i, cell in enumerate(row):
            w = col_widths[i] if i < len(col_widths) else 15
            line += f" {str(cell):<{w}}"
        print(line)


def save_json(data: Any, filepath: str):
    """保存JSON结果文件"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


# ============================================================================
# 数据获取模块
# ============================================================================

class SectorDataFetcher:
    """板块数据获取器（全量抓取 + 实例内缓存）"""

    def __init__(self):
        self._industry: Optional[List[Dict[str, Any]]] = None
        self._concept: Optional[List[Dict[str, Any]]] = None
        self._indices: Optional[Dict[str, Dict[str, Any]]] = None

    def get_sectors(self, is_concept: bool = False) -> List[Dict[str, Any]]:
        """获取板块全量行情（行业/概念各一次请求，缓存复用）"""
        if is_concept:
            if self._concept is None:
                self._concept = _parse_sina_sectors(_SINA_CONCEPT_URL, "S_Finance_bankuai_class")
            return self._concept
        if self._industry is None:
            self._industry = _parse_sina_sectors(_SINA_INDUSTRY_URL, "S_Finance_bankuai_sinaindustry")
        return self._industry

    def get_sector_by_name(self, name: str, is_concept: bool = False) -> Optional[Dict[str, Any]]:
        """按名称查找板块"""
        for s in self.get_sectors(is_concept=is_concept):
            if s["name"] == name:
                return s
        return None

    def get_index_quotes(self) -> Dict[str, Dict[str, Any]]:
        """获取风格指数行情（一次请求）"""
        if self._indices is None:
            self._indices = _fetch_tx_indices(STYLE_INDICES)
        return self._indices


# ============================================================================
# 功能模块实现
# ============================================================================

class SectorRotationAnalyzer:
    """板块轮动分析器"""

    def __init__(self):
        self.fetcher = SectorDataFetcher()
        self.output_dir = Path("./sector_rotation_output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ------------------------------------------------------------------
    # 1. 板块行情总览 (Overview)
    # ------------------------------------------------------------------
    def overview(self, sector_type: str = "industry", top_n: int = 30):
        """板块行情总览"""
        is_concept = (sector_type == "concept")
        print("=" * 80)
        print(f"  A股板块行情总览 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"  类型: {'概念板块' if is_concept else '行业板块'}")
        print("=" * 80)

        results = list(self.fetcher.get_sectors(is_concept=is_concept))
        print(f"\n  共获取 {len(results)} 个板块\n")

        results.sort(key=lambda x: (x["change_pct"] is None, -(x["change_pct"] or 0)))

        headers = ["排名", "板块名称", "涨跌幅%", "均价", "家数", "成交额(亿)", "领涨股", "领涨股涨幅%"]

        def make_rows(items):
            rows = []
            for i, r in enumerate(items):
                amount_yi = (r["amount"] / 1e8) if r["amount"] else None
                leader = f"{r['leader_name']}({format_pct(r['leader_pct'])})" if r["leader_name"] else "-"
                rows.append([
                    str(i + 1),
                    r["name"],
                    color_pct(r["change_pct"]),
                    f"{r['avg_price']:.2f}" if r["avg_price"] is not None else "-",
                    str(r["stock_count"]),
                    f"{amount_yi:.1f}" if amount_yi is not None else "-",
                    leader,
                ])
            return rows

        print(f"\n📈 {'概念' if is_concept else '行业'}板块涨幅TOP{min(top_n, len(results))}:\n")
        print_table(headers, make_rows(results[:top_n]))

        worst = list(results[-min(10, len(results)):])
        worst.sort(key=lambda x: (x["change_pct"] is None, x["change_pct"] or 0))
        print(f"\n📉 {'概念' if is_concept else '行业'}板块跌幅TOP{len(worst)}:\n")
        # 跌幅榜重新编排名
        print_table(headers, make_rows(worst))

        valid_changes = [r["change_pct"] for r in results if r["change_pct"] is not None]
        avg_change = max_change = min_change = None
        up_sectors = down_sectors = 0
        if valid_changes:
            avg_change = float(np.mean(valid_changes))
            max_change = max(valid_changes)
            min_change = min(valid_changes)
            up_sectors = sum(1 for c in valid_changes if c > 0)
            down_sectors = sum(1 for c in valid_changes if c < 0)

            print(f"\n📊 统计摘要:")
            print(f"  平均涨跌幅: {color_pct(avg_change)}")
            print(f"  最大涨幅:   {color_pct(max_change)}")
            print(f"  最大跌幅:   {color_pct(min_change)}")
            print(f"  上涨板块数: {up_sectors}/{len(valid_changes)}")
            print(f"  下跌板块数: {down_sectors}/{len(valid_changes)}")

        output_data = {
            "module": "overview",
            "sector_type": sector_type,
            "timestamp": datetime.now().isoformat(),
            "results": results[:top_n],
            "summary": {
                "avg_change_pct": avg_change,
                "max_change_pct": max_change,
                "min_change_pct": min_change,
                "up_count": up_sectors,
                "down_count": down_sectors,
            }
        }
        filepath = self.output_dir / f"overview_{sector_type}_{self.timestamp}.json"
        save_json(output_data, str(filepath))
        print(f"\n💾 结果已保存: {filepath}")

        return results

    # ------------------------------------------------------------------
    # 2. 板块强度排名 (Sector Strength)
    # ------------------------------------------------------------------
    def strength(self, period: int = 20):
        """
        板块强度排名 - RPS相对强度 + 动量评分

        动量评分 = 日涨跌幅×3 + 领涨股涨幅×1
        （免费源仅含当日截面数据，评分为横截面排名，非时间序列指标）
        """
        print("=" * 80)
        print(f"  A股板块强度排名 ({period}日RPS口径) - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 80)

        industry = self.fetcher.get_sectors(is_concept=False)
        concept = self.fetcher.get_sectors(is_concept=True)
        concept_codes = {s["code"] for s in concept}

        strength_data = []
        for s in industry + concept:
            change = s["change_pct"]
            if change is None:
                continue
            leader_pct = s["leader_pct"] or 0
            momentum_score = change * 3.0 + leader_pct * 1.0
            strength_data.append({
                "name": s["name"],
                "is_concept": s["code"] in concept_codes,
                "change_pct": change,
                "leader_name": s["leader_name"],
                "leader_pct": s["leader_pct"],
                "amount": s["amount"],
                "momentum_score": momentum_score,
            })

        if not strength_data:
            print("\n❌ 未获取到板块数据")
            return []

        # RPS: 百分位排名
        scores = [d["momentum_score"] for d in strength_data]
        for d in strength_data:
            rank = sum(1 for s in scores if s < d["momentum_score"])
            d["rps"] = round(rank / len(scores) * 100, 1)

        strength_data.sort(key=lambda x: -x["momentum_score"])

        print(f"\n🏆 板块动量强度排名TOP20 (共{len(strength_data)}个板块):\n")
        headers = ["排名", "板块名称", "类型", "涨跌幅%", "领涨股", "领涨股涨幅%", "成交额(亿)", "动量评分", "RPS"]
        rows = []
        for i, d in enumerate(strength_data[:20]):
            signal = ""
            if d["change_pct"] and d["change_pct"] > 3:
                signal += "🔥"
            if d["rps"] >= 90:
                signal += "⭐"
            amount_yi = (d["amount"] / 1e8) if d["amount"] else None
            rows.append([
                str(i + 1),
                d["name"],
                "概念" if d["is_concept"] else "行业",
                color_pct(d["change_pct"]),
                d["leader_name"] or "-",
                color_pct(d["leader_pct"]),
                f"{amount_yi:.1f}" if amount_yi is not None else "-",
                f"{d['momentum_score']:+.1f}",
                f"{d['rps']} {signal}",
            ])
        print_table(headers, rows)

        breakouts = [d for d in strength_data if (d["change_pct"] or 0) > 3 and d["rps"] >= 70]
        if breakouts:
            print(f"\n🚀 突破信号板块 ({len(breakouts)}个 - 涨幅>3%且RPS≥70):")
            for d in breakouts[:10]:
                print(f"  {d['name']} - 涨跌幅:{color_pct(d['change_pct'])} RPS:{d['rps']} 动量:{d['momentum_score']:+.1f}")

        output_data = {
            "module": "strength",
            "period": period,
            "timestamp": datetime.now().isoformat(),
            "formula": "动量评分 = 日涨跌幅×3 + 领涨股涨幅×1",
            "rankings": strength_data[:20],
            "breakout_signals": breakouts[:10],
        }
        filepath = self.output_dir / f"strength_{self.timestamp}.json"
        save_json(output_data, str(filepath))
        print(f"\n💾 结果已保存: {filepath}")

        return strength_data

    # ------------------------------------------------------------------
    # 3. 热点题材追踪 (Hot Themes)
    # ------------------------------------------------------------------
    def hot(self, top_n: int = 10):
        """热点题材追踪（扫描全部概念板块）"""
        print("=" * 80)
        print(f"  A股热点题材追踪 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 80)

        concept_data = list(self.fetcher.get_sectors(is_concept=True))
        print(f"\n  共扫描 {len(concept_data)} 个概念板块\n")

        concept_data.sort(key=lambda x: (x["change_pct"] is None, -(x["change_pct"] or 0)))

        print(f"\n🔥 当日最强概念TOP{min(top_n, len(concept_data))}:\n")
        headers = ["排名", "概念名称", "涨跌幅%", "家数", "成交额(亿)", "领涨股", "所属主题"]
        rows = []
        for i, d in enumerate(concept_data[:top_n]):
            amount_yi = (d["amount"] / 1e8) if d["amount"] else None
            leader = f"{d['leader_name']}({format_pct(d['leader_pct'])})" if d["leader_name"] else "-"
            rows.append([
                str(i + 1),
                d["name"],
                color_pct(d["change_pct"]),
                str(d["stock_count"]),
                f"{amount_yi:.1f}" if amount_yi is not None else "-",
                leader,
                self._categorize_concept(d["name"]),
            ])
        print_table(headers, rows)

        high_momentum = [d for d in concept_data if (d["change_pct"] or 0) > 5]
        print(f"\n🆕 高动量概念 ({len(high_momentum)}个 - 涨幅>5%):")
        for d in high_momentum[:15]:
            cat = self._categorize_concept(d["name"])
            print(f"  {d['name']} [{cat}] - {color_pct(d['change_pct'])} 领涨:{d['leader_name']} 成交额:{format_amount(d.get('amount'))}")

        # Concept correlation map (group by category)
        categories: Dict[str, List[Dict[str, Any]]] = {}
        for d in concept_data:
            cat = self._categorize_concept(d["name"])
            categories.setdefault(cat, []).append(d)

        print(f"\n🗺️ 概念关联图谱 (按主题分类):")
        for cat, concepts in sorted(categories.items()):
            concepts.sort(key=lambda x: -(x["change_pct"] or 0))
            avg_change = np.mean([c["change_pct"] or 0 for c in concepts])
            print(f"\n  [{cat}] ({len(concepts)}个概念, 平均涨跌:{format_pct(avg_change)})")
            for c in concepts[:5]:
                marker = "🔥" if (c["change_pct"] or 0) > 3 else ""
                print(f"    {marker} {c['name']}: {color_pct(c['change_pct'])}")

        output_data = {
            "module": "hot",
            "timestamp": datetime.now().isoformat(),
            "top_concepts": concept_data[:top_n],
            "high_momentum": high_momentum[:20],
            "category_map": {cat: [{"name": c["name"], "change_pct": c["change_pct"]} for c in concepts[:10]]
                             for cat, concepts in categories.items()},
        }
        filepath = self.output_dir / f"hot_{self.timestamp}.json"
        save_json(output_data, str(filepath))
        print(f"\n💾 结果已保存: {filepath}")

        return concept_data

    @staticmethod
    def _categorize_concept(name: str) -> str:
        """概念主题分类（关键词匹配）"""
        categories = [
            ("AI科技", ["华为", "鸿蒙", "小米", "百度", "苹果", "5G", "物联网", "智能",
                        "国产软件", "信息安全", "网络", "电子", "触摸屏", "无线耳机",
                        "机器人", "机器", "大数据", "云计算", "人工智能", "芯片", "半导体",
                        "算力", "穿戴", "智能家居"]),
            ("新能源/绿色", ["新能源", "光伏", "锂", "电池", "氢", "风电", "风能", "充电桩",
                            "碳", "核电", "页岩气", "可燃冰", "地热", "石墨烯", "节能",
                            "环保", "循环", "钙钛矿", "储能", "快充"]),
            ("消费/医药", ["白酒", "食品", "酿酒", "猪肉", "鸡肉", "水产", "婴童", "生物",
                          "基因", "疫苗", "抗癌", "仿制药", "创新药", "CXO", "CRO", "免疫",
                          "民营医院", "医疗器械", "奢侈", "旅游", "博彩", "体育", "电商",
                          "维生素", "草甘膦", "维生素"]),
            ("政策主题", ["改革", "自贸", "新区", "特区", "规划", "丝路", "京津冀", "雄安",
                          "海南", "振兴", "乡村", "科创", "央企", "国企", "整体上市",
                          "专精特新", "扶贫", "一体化"]),
            ("金融地产", ["金融", "银行", "保险", "券商", "证券", "地产", "土地流转",
                          "参股", "重仓", "解禁", "融资融券", "互联金融", "含H股", "含B股"]),
            ("军工航天", ["军工", "军民", "航天", "航空", "卫星", "大飞机", "船舶", "海工",
                          "国防"]),
        ]
        for cat, keywords in categories:
            for kw in keywords:
                if kw in name:
                    return cat
        return "其他"

    # ------------------------------------------------------------------
    # 4. 轮动信号检测 (Rotation Signals)
    # ------------------------------------------------------------------
    def signals(self):
        """板块轮动信号检测"""
        print("=" * 80)
        print(f"  A股板块轮动信号检测 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 80)

        print("\n📊 正在获取风格数据...")

        def pick(names):
            out = []
            for n in names:
                s = self.fetcher.get_sector_by_name(n, is_concept=False)
                if s and s["change_pct"] is not None:
                    out.append(s)
            return out

        defensive_data = pick(DEFENSIVE_SECTORS)
        offensive_data = pick(OFFENSIVE_SECTORS)
        growth_data = pick(GROWTH_SECTORS)
        value_data = pick(VALUE_SECTORS)

        indices = self.fetcher.get_index_quotes()
        print("")

        # --- 信号1: 防御型 vs 进攻型 ---
        def_avg = float(np.mean([d["change_pct"] for d in defensive_data])) if defensive_data else 0
        off_avg = float(np.mean([d["change_pct"] for d in offensive_data])) if offensive_data else 0

        print(f"\n{'='*60}")
        print("  🔄 信号1: 防御型 vs 进攻型行业轮动")
        print(f"{'='*60}")
        print(f"\n  防御型行业平均涨跌: {color_pct(def_avg)} ({len(defensive_data)}个)")
        for d in sorted(defensive_data, key=lambda x: -(x["change_pct"] or 0)):
            print(f"    {d['name']}: {color_pct(d['change_pct'])}")

        print(f"\n  进攻型行业平均涨跌: {color_pct(off_avg)} ({len(offensive_data)}个)")
        for d in sorted(offensive_data, key=lambda x: -(x["change_pct"] or 0)):
            print(f"    {d['name']}: {color_pct(d['change_pct'])}")

        rotation_dir = "进攻→防御 (避险模式)" if def_avg > off_avg else "防御→进攻 (风险偏好上升)"
        spread = off_avg - def_avg
        print(f"\n  📌 轮动方向: {rotation_dir}")
        print(f"  📌 攻守差值: {spread:+.2f}%")

        # --- 信号2: 大小盘风格 ---
        hs300_change = indices["沪深300"]["change_pct"] or 0
        zz1000_change = indices["中证1000"]["change_pct"] or 0

        print(f"\n{'='*60}")
        print("  🔄 信号2: 大小盘风格切换")
        print(f"{'='*60}")
        print(f"\n  沪深300(大盘): {color_pct(hs300_change)}")
        print(f"  中证1000(小盘): {color_pct(zz1000_change)}")

        size_signal = "大盘占优" if hs300_change > zz1000_change else "小盘占优"
        size_spread = zz1000_change - hs300_change
        print(f"\n  📌 风格信号: {size_signal}")
        print(f"  📌 大小盘差值: {size_spread:+.2f}%")

        # --- 信号3: 成长型 vs 价值型 ---
        growth_avg = float(np.mean([d["change_pct"] for d in growth_data])) if growth_data else 0
        value_avg = float(np.mean([d["change_pct"] for d in value_data])) if value_data else 0

        print(f"\n{'='*60}")
        print("  🔄 信号3: 成长型 vs 价值型风格切换")
        print(f"{'='*60}")
        print(f"\n  成长型行业平均涨跌: {color_pct(growth_avg)} ({len(growth_data)}个)")
        for d in sorted(growth_data, key=lambda x: -(x["change_pct"] or 0)):
            print(f"    {d['name']}: {color_pct(d['change_pct'])}")

        print(f"\n  价值型行业平均涨跌: {color_pct(value_avg)} ({len(value_data)}个)")
        for d in sorted(value_data, key=lambda x: -(x["change_pct"] or 0)):
            print(f"    {d['name']}: {color_pct(d['change_pct'])}")

        gv_signal = "成长占优" if growth_avg > value_avg else "价值占优"
        gv_spread = growth_avg - value_avg
        print(f"\n  📌 风格信号: {gv_signal}")
        print(f"  📌 成长-价值差值: {gv_spread:+.2f}%")

        # --- 信号4: 板块轮动周期定位 ---
        print(f"\n{'='*60}")
        print("  🔄 信号4: 板块轮动周期定位")
        print(f"{'='*60}")

        all_sectors = defensive_data + offensive_data
        changes = [d["change_pct"] or 0 for d in all_sectors]
        avg_change = float(np.mean(changes)) if changes else 0
        std_change = float(np.std(changes)) if len(changes) > 1 else 0

        strong_up = sum(1 for c in changes if c > 3)
        strong_down = sum(1 for c in changes if c < -3)
        moderate_up = sum(1 for c in changes if 0 < c <= 3)
        moderate_down = sum(1 for c in changes if -3 <= c < 0)

        if strong_up > len(all_sectors) * 0.4 and avg_change > 2:
            cycle_phase = "🔴 高潮期"
            cycle_confidence = "多数板块大幅上涨，注意追高风险"
        elif strong_up > len(all_sectors) * 0.2 and avg_change > 0:
            cycle_phase = "🟡 发酵期"
            cycle_confidence = "热点扩散中，关注持续性"
        elif moderate_up > len(all_sectors) * 0.3 and avg_change >= -1:
            cycle_phase = "🟢 萌芽期"
            cycle_confidence = "板块分化，寻找新主线"
        else:
            cycle_phase = "⚫ 衰退期"
            cycle_confidence = "市场整体偏弱，防御为主"

        print(f"\n  📊 板块涨跌分布:")
        print(f"    大幅上涨(>3%): {strong_up}个")
        print(f"    温和上涨(0~3%): {moderate_up}个")
        print(f"    温和下跌(-3~0%): {moderate_down}个")
        print(f"    大幅下跌(<-3%): {strong_down}个")

        print(f"\n  📌 轮动周期: {cycle_phase}")
        print(f"  📌 判断依据: {cycle_confidence}")
        print(f"  📌 平均涨跌: {color_pct(avg_change)} | 标准差: {std_change:.2f}%")

        # --- 综合信号摘要 ---
        print(f"\n{'='*60}")
        print("  📋 综合信号摘要")
        print(f"{'='*60}")
        print(f"""
  ┌─────────────────┬──────────────────────┐
  │   信号类型       │   判断结果            │
  ├─────────────────┼──────────────────────┤
  │ 攻守轮动         │ {rotation_dir:<20s}│
  │ 大小盘风格       │ {size_signal:<20s}│
  │ 成长vs价值       │ {gv_signal:<20s}│
  │ 轮动周期         │ {cycle_phase.strip():<20s}│
  └─────────────────┴──────────────────────┘

  📊 主要指数表现:
    上证指数: {color_pct(indices['上证指数']['change_pct'])}
    沪深300:  {color_pct(indices['沪深300']['change_pct'])}
    中证1000: {color_pct(indices['中证1000']['change_pct'])}
    创业板指: {color_pct(indices['创业板指']['change_pct'])}
""")

        output_data = {
            "module": "signals",
            "timestamp": datetime.now().isoformat(),
            "rotation_signals": {
                "defensive_vs_offensive": {
                    "direction": rotation_dir,
                    "spread": round(spread, 2),
                    "defensive_avg": round(def_avg, 2),
                    "offensive_avg": round(off_avg, 2),
                },
                "size_style": {
                    "signal": size_signal,
                    "hs300_change": round(hs300_change, 2),
                    "zz1000_change": round(zz1000_change, 2),
                    "spread": round(size_spread, 2),
                },
                "growth_vs_value": {
                    "signal": gv_signal,
                    "growth_avg": round(growth_avg, 2),
                    "value_avg": round(value_avg, 2),
                    "spread": round(gv_spread, 2),
                },
                "cycle_phase": {
                    "phase": cycle_phase.strip(),
                    "confidence": cycle_confidence,
                    "avg_change": round(avg_change, 2),
                    "std_change": round(std_change, 2),
                    "distribution": {
                        "strong_up": strong_up,
                        "moderate_up": moderate_up,
                        "moderate_down": moderate_down,
                        "strong_down": strong_down,
                    }
                },
            },
            "indices": indices,
        }
        filepath = self.output_dir / f"signals_{self.timestamp}.json"
        save_json(output_data, str(filepath))
        print(f"\n💾 结果已保存: {filepath}")

        return output_data["rotation_signals"]


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="A股板块轮动追踪工具（免费公开数据源）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python sector_rotation.py overview                    # 行业板块行情总览
  python sector_rotation.py overview --type concept     # 概念板块行情总览
  python sector_rotation.py strength                    # 板块强度排名
  python sector_rotation.py hot                         # 热点题材追踪
  python sector_rotation.py signals                     # 轮动信号检测

说明: 板块资金流向(flow)与历史回查(history)因无免费数据源已移除。
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="功能模块")

    p_overview = subparsers.add_parser("overview", help="板块行情总览")
    p_overview.add_argument("--type", choices=["industry", "concept"], default="industry",
                           help="板块类型: industry(行业) / concept(概念)")
    p_overview.add_argument("--top", type=int, default=30, help="显示前N名 (默认30)")

    p_strength = subparsers.add_parser("strength", help="板块强度排名")
    p_strength.add_argument("--period", type=int, choices=[20, 60], default=20,
                           help="RPS展示口径 (默认20，当前为当日截面计算)")

    p_hot = subparsers.add_parser("hot", help="热点题材追踪")
    p_hot.add_argument("--top", type=int, default=10, help="显示前N名 (默认10)")

    p_signals = subparsers.add_parser("signals", help="轮动信号检测")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    analyzer = SectorRotationAnalyzer()

    try:
        if args.command == "overview":
            analyzer.overview(sector_type=args.type, top_n=args.top)
        elif args.command == "strength":
            analyzer.strength(period=args.period)
        elif args.command == "hot":
            analyzer.hot(top_n=args.top)
        elif args.command == "signals":
            analyzer.signals()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
