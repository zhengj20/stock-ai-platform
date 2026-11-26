#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股自然语言对话分析引擎 (NLP Analyzer)
======================================
解析用户自然语言问题，自动组合多个分析模块给出综合推荐。

支持的意图类型：
  - stock_diagnosis   个股诊断（"帮我看看贵州茅台怎么样"）
  - stock_selection    选股推荐（"找一只适合低吸的股票"）
  - market_query       行情查询（"今天大盘走势如何"）
  - sector_analysis    板块分析（"新能源板块最近怎么样"）
  - news_search        资讯搜索（"比亚迪有什么最新消息"）
  - strategy_run       策略执行（"超跌反弹选股结果出来了吗"）

用法:
    python nlp_analyzer.py "帮我看看贵州茅台怎么样"     # 单次查询
    python nlp_analyzer.py --chat                       # 对话模式
    python nlp_analyzer.py --batch file.txt             # 批量处理

依赖: requests
"""

import os
import sys
import re
import json
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import requests


# ============================================================================
# 1. 意图识别引擎 — 基于关键词规则 + 简单NLP
# ============================================================================

class IntentClassifier:
    """
    意图分类器：基于关键词、正则表达式和上下文模式匹配。
    不依赖外部LLM API，纯本地规则引擎。
    """

    # ── 个股诊断关键词 ────────────────────────────────
    STOCK_DIAGNOSIS_PATTERNS = [
        r"帮我看看\s*(.{1,20})\s*怎么样",
        r"(分析|评估|诊断|评价)\s*(.{1,20})",
        r"(.{1,20})\s*(怎么样|如何|好不好|值不值得买|能买吗|前景)",
        r"看看\s*(.{1,20})\s*的?\s*(基本面|技术面|走势|指标|形态)",
        r"(.{1,20})\s*(的基本面|的技术面|的行情|的最新价|的股价)",
    ]

    # ── 选股推荐关键词 ────────────────────────────────
    STOCK_SELECTION_PATTERNS = [
        r"找\s*(一)?只?\s*(适合|符合)\s*.{0,30}",
        r"(推荐|筛选|选出|挑选)\s*(.{0,20})\s*股票",
        r"(低估值|高成长|超跌|低吸|蓝筹|白马|小盘|大盘)\s*(股票|股)",
        r"什么\s*股票\s*(值得|适合|可以)\s*(买|关注|投资)",
        r"(多因子|因子选股|量化选股)",
    ]

    # ── 行情查询关键词 ────────────────────────────────
    MARKET_QUERY_PATTERNS = [
        r"今天?\s*大盘\s*(走势|怎么样|如何|情况)",
        r"(上证指数|沪深300|创业板指|科创50)\s*(最新|今天|走势|行情)",
        r"市场\s*(情绪|热度|氛围|状况)",
        r"(A股|股市)\s*(今天|最近|近期)\s*怎么样",
        r"大盘\s*(涨|跌|红|绿)了吗?",
    ]

    # ── 板块分析关键词 ────────────────────────────────
    SECTOR_ANALYSIS_PATTERNS = [
        r"(.{1,20})\s*板块\s*(怎么样|如何|走势|表现|最近)",
        r"新能源|半导体|芯片|医药|消费|金融|科技|军工|光伏|锂电|AI|人工智能",  # 常见板块名（需配合上下文）
        r"(.{1,20})\s*(行业|概念)\s*(怎么样|分析|前景)",
        r"哪个\s*板块\s*(好|强|弱|涨|跌)",
    ]

    # ── 资讯搜索关键词 ────────────────────────────────
    NEWS_SEARCH_PATTERNS = [
        r"(.{1,20})\s*(最新消息|新闻|公告|动态|消息)",
        r"搜\s*索?\s*(.{1,20})",
        r"(.{1,20})\s*(发生了什么|出了什么事|有什么新闻)",
        r"关于\s*(.{1,20})\s*(的)?\s*(资讯|信息|报道)",
    ]

    # ── 策略执行关键词 ────────────────────────────────
    STRATEGY_RUN_PATTERNS = [
        r"(超跌反弹|隔日短线)\s*选股\s*(结果|出来了吗|运行)",
        r"运行?\s*(.{0,20})\s*策略",
        r"(执行|跑一下)\s*策略",
        r"今天?\s*选股\s*(结果|推荐|列表)",
    ]

    # ── 股票名称/代码提取正则 ─────────────────────────
    STOCK_CODE_RE = re.compile(r'(?:^|\s)(\d{6})(?:\s|$)')
    STOCK_NAME_RE = re.compile(
        r'(贵州茅台|五粮液|宁德时代|比亚迪|东方财富|招商银行|中国平安|'
        r'腾讯控股|阿里巴巴|美团|中芯国际|海康威视|万华化学|隆基绿能|'
        r'药明康德|恒瑞医药|迈瑞医疗|格力电器|美的集团|海尔智家|'
        r'贵州茅台|长江电力|中国神华|紫金矿业|中信证券|华泰柏瑞)'
    )

    # ── 选股条件关键词映射 ────────────────────────────
    SELECTION_CONDITIONS = {
        "低估值": {"value_weight": 0.7, "growth_weight": 0.3},
        "高成长": {"value_weight": 0.3, "growth_weight": 0.7},
        "低吸":   {"momentum_weight": 0.5, "oversold_filter": True},
        "蓝筹":   {"large_cap_filter": True, "quality_weight": 0.8},
        "白马":   {"quality_weight": 0.9, "stability_weight": 0.7},
        "小盘":   {"small_cap_filter": True},
        "大盘":   {"large_cap_filter": True},
    }

    def classify(self, query: str) -> Dict[str, Any]:
        """
        对查询语句进行意图分类。

        Returns:
            {
                "intent": str,           # 意图类型
                "confidence": float,     # 置信度 (0-1)
                "entities": dict,        # 提取的实体（股票名、板块名等）
                "conditions": dict,      # 筛选条件
            }
        """
        query_clean = self._normalize(query)

        # 多意图评分
        scores: Dict[str, float] = {}
        entities: Dict[str, Any] = {}
        conditions: Dict[str, Any] = {}

        # ── 个股诊断 ────────────────────────────────
        score, stock_name = self._match_patterns(
            query_clean, self.STOCK_DIAGNOSIS_PATTERNS, extract_entity=True
        )
        if score > 0:
            scores["stock_diagnosis"] = max(scores.get("stock_diagnosis", 0), score)
            entities["stock"] = stock_name or self._extract_stock(query)

        # ── 选股推荐 ────────────────────────────────
        score, _ = self._match_patterns(
            query_clean, self.STOCK_SELECTION_PATTERNS
        )
        if score > 0:
            scores["stock_selection"] = max(scores.get("stock_selection", 0), score)
            conditions.update(self._extract_conditions(query_clean))

        # ── 行情查询 ────────────────────────────────
        score, _ = self._match_patterns(
            query_clean, self.MARKET_QUERY_PATTERNS
        )
        if score > 0:
            scores["market_query"] = max(scores.get("market_query", 0), score)

        # ── 板块分析 ────────────────────────────────
        score, sector = self._match_patterns(
            query_clean, self.SECTOR_ANALYSIS_PATTERNS, extract_entity=True
        )
        if score > 0:
            scores["sector_analysis"] = max(scores.get("sector_analysis", 0), score)
            entities["sector"] = sector or self._extract_sector(query)

        # ── 资讯搜索 ────────────────────────────────
        score, topic = self._match_patterns(
            query_clean, self.NEWS_SEARCH_PATTERNS, extract_entity=True
        )
        if score > 0:
            scores["news_search"] = max(scores.get("news_search", 0), score)
            entities["topic"] = topic or self._extract_stock(query)

        # ── 策略执行 ────────────────────────────────
        score, _ = self._match_patterns(
            query_clean, self.STRATEGY_RUN_PATTERNS
        )
        if score > 0:
            scores["strategy_run"] = max(scores.get("strategy_run", 0), score)

        # ── 优先级修正：有明确实体/关键词的意图优先于模糊匹配 ──
        # 板块分析 > 个股诊断（当识别到板块名时）
        if entities.get("sector") and scores.get("sector_analysis", 0) > 0:
            scores["sector_analysis"] = max(scores["sector_analysis"], 0.85)

        # 行情查询 > 个股诊断（当包含大盘/指数关键词时）
        market_keywords = ["大盘", "上证指数", "深证成指", "创业板指", "沪深300", "科创50", "a股"]
        if any(kw in query_clean for kw in market_keywords) and scores.get("market_query", 0) > 0:
            scores["market_query"] = max(scores["market_query"], 0.85)

        # ── 默认回退：如果包含股票代码/名称，优先个股诊断 ──
        stock = self._extract_stock(query)
        if not scores and stock:
            scores["stock_diagnosis"] = 0.5
            entities["stock"] = stock

        # ── 取最高分意图 ────────────────────────────────
        if scores:
            intent = max(scores, key=scores.get)
            confidence = scores[intent]
        else:
            intent = "unknown"
            confidence = 0.0

        return {
            "intent": intent,
            "confidence": round(confidence, 2),
            "entities": entities,
            "conditions": conditions,
            "all_scores": scores,
        }

    def _normalize(self, text: str) -> str:
        """文本标准化：去标点、转小写"""
        text = re.sub(r'[，。！？、；：""''（）\[\]{}《》]', ' ', text)
        return text.strip().lower()

    def _match_patterns(
        self, text: str, patterns: List[str], extract_entity: bool = False
    ) -> Tuple[float, Optional[str]]:
        """匹配一组正则模式，返回最高置信度和提取的实体"""
        best_score = 0.0
        entity = None

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                # 根据匹配长度计算置信度（越长越精确）
                matched_len = len(match.group(0))
                score = min(1.0, 0.5 + matched_len * 0.02)

                if score > best_score:
                    best_score = score
                    if extract_entity and match.lastindex and match.lastindex >= 1:
                        # 尝试提取第一个捕获组作为实体
                        for i in range(1, match.lastindex + 1):
                            g = match.group(i)
                            if g and len(g.strip()) > 0:
                                entity = g.strip()
                                break

        return best_score, entity

    def _extract_stock(self, query: str) -> Optional[str]:
        """从查询中提取股票名称或代码"""
        # 先尝试提取6位股票代码
        code_match = self.STOCK_CODE_RE.search(query)
        if code_match:
            return code_match.group(1)

        # 再尝试匹配已知股票名
        name_match = self.STOCK_NAME_RE.search(query)
        if name_match:
            return name_match.group(1)

        # 通用模式：提取"看看/分析/诊断"后面的名词短语
        generic_patterns = [
            r'(?:帮我)?(?:看看|分析|评估|诊断)\s*(.+?)(?:怎么样|如何|好不好|$)',
            r'(.{2,8})\s*(怎么样|如何|好不好|的最新价|的行情|的基本面|的技术面)',
        ]
        for pat in generic_patterns:
            m = re.search(pat, query)
            if m:
                return m.group(1).strip()

        return None

    def _extract_sector(self, query: str) -> Optional[str]:
        """从查询中提取板块名称"""
        sector_keywords = [
            "新能源", "半导体", "芯片", "医药", "消费", "金融", "科技",
            "军工", "光伏", "锂电", "AI", "人工智能", "汽车", "地产",
            "银行", "保险", "券商", "钢铁", "煤炭", "石油", "化工",
            "电子", "通信", "传媒", "游戏", "教育", "农业", "食品",
        ]
        for kw in sector_keywords:
            if kw in query:
                return kw

        # 通用模式：提取"XX板块"中的XX
        m = re.search(r'(.{2,10})\s*板块', query)
        if m:
            return m.group(1).strip()

        return None

    def _extract_conditions(self, query: str) -> Dict[str, Any]:
        """从查询中提取选股条件"""
        conditions = {}
        for kw, cond in self.SELECTION_CONDITIONS.items():
            if kw in query:
                conditions.update(cond)
        return conditions


# ============================================================================
# 2. 对话记忆 — 多轮上下文理解
# ============================================================================

class ConversationMemory:
    """
    对话记忆管理器：维护多轮对话的上下文状态。
    支持指代消解（"它"→上一只股票）、对比分析等。
    """

    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.history: List[Dict[str, Any]] = []
        self.last_stock: Optional[str] = None
        self.last_sector: Optional[str] = None
        self.last_intent: Optional[str] = None
        self.context_stocks: List[str] = []  # 最近讨论过的股票列表

    def resolve(self, query: str) -> Tuple[str, Dict[str, Any]]:
        """
        解析查询中的指代，返回消歧后的查询和补充实体。

        Returns:
            (resolved_query, resolved_entities)
        """
        entities = {}
        q = query.strip()

        # ── "再看看它的基本面" / "它的基本面" → 上一只股票 ────────
        m = re.search(r'(?:再\s*看\s*看?\s*)?(?:它|这个|这只|该股)\s*(?:的)?\s*(基本面|技术面|K线|指标|形态|行情)', q)
        if m and self.last_stock:
            aspect = m.group(1)
            entities["stock"] = self.last_stock
            return f"{self.last_stock}的{aspect}", entities

        # ── "那这只呢？" / "再看看呢" → 对比分析同一只股票 ────────
        if re.search(r'(?:那|再)\s*(?:看\s*看?\s*)?(?:这)?\s*(?:只|个)?\s*呢[？?]?', q):
            if self.last_stock:
                entities["stock"] = self.last_stock
                return f"帮我看看{self.last_stock}怎么样", entities

        # ── "它怎么样" / "这个怎么样" → 上一只股票 ────────────────
        m2 = re.search(r'(?:它|这个|这只)\s*(?:怎么样|如何)', q)
        if m2 and self.last_stock:
            entities["stock"] = self.last_stock
            return f"帮我看看{self.last_stock}怎么样", entities

        # ── "对比一下" / "和XX比" ─────────────────────
        compare_match = re.search(r'(?:和|跟|与)\s*(.{2,10})\s*比较', q)
        if compare_match and self.last_stock:
            entities["stock"] = self.last_stock
            entities["compare_with"] = compare_match.group(1).strip()

        return query, entities

    def update(self, intent_result: Dict[str, Any]):
        """更新对话记忆"""
        entities = intent_result.get("entities", {})
        stock = entities.get("stock")
        sector = entities.get("sector")

        if stock:
            self.last_stock = stock
            if stock not in self.context_stocks:
                self.context_stocks.append(stock)
            # 保持最近N只股票
            if len(self.context_stocks) > self.max_history:
                self.context_stocks = self.context_stocks[-self.max_history:]

        if sector:
            self.last_sector = sector

        self.last_intent = intent_result["intent"]

        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "intent": intent_result["intent"],
            "entities": entities,
        })

        # 保持历史长度
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]


# ============================================================================
# 3. 免费公开数据层（腾讯行情/新浪板块，文件内自包含）
# ============================================================================

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TX_QUOTE_URL = "https://qt.gtimg.cn/q="
_TX_SMARTBOX_URL = "https://smartbox.gtimg.cn/s3/"
_SINA_INDUSTRY_URL = "http://money.finance.sina.com.cn/q/view/newSinaHy.php"
_SINA_CONCEPT_URL = "http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class"


def _get(url: str, params: Dict = None, headers: Dict = None, retries: int = 3) -> requests.Response:
    """请求公开接口，带退避重试（行情源偶发直接断连）"""
    merged = dict(_HEADERS)
    if headers:
        merged.update(headers)
    last_err = None
    for attempt in range(retries):
        try:
            return requests.get(url, params=params, headers=merged, timeout=20)
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


def _fmt(val: Optional[float], digits: int = 2, suffix: str = "") -> str:
    return f"{val:.{digits}f}{suffix}" if val is not None else "-"


def _resolve_symbol(name: str) -> str:
    """股票名称/代码 → 腾讯symbol（smartbox检索，仅A股）"""
    if re.fullmatch(r"(sh|sz|bj)\d{6}", name.lower()):
        return name.lower()
    if re.fullmatch(r"\d{6}", name):
        code = name
        prefix = "sh" if code.startswith(("6", "5", "9")) else \
            "bj" if code.startswith(("4", "8")) else "sz"
        return prefix + code
    resp = _get(_TX_SMARTBOX_URL, {"v": "3", "q": name, "t": "all"},
                {"Referer": "https://gu.qq.com/"})
    resp.encoding = "gbk"
    hint = resp.text.partition('"')[2].rstrip('"')
    for item in hint.split("^"):
        parts = item.split("~")
        if len(parts) >= 5 and parts[4] == "GP-A":
            code = parts[1]
            prefix = "sh" if code.startswith(("6", "5", "9")) else \
                "bj" if code.startswith(("4", "8")) else "sz"
            return prefix + code
    raise RuntimeError(f"未找到股票：{name}")


def fetch_quote_text(target: str) -> str:
    """
    腾讯实时行情文本（免费公开接口）。

    target: 股票名称/代码，或 "指数" 时返回上证/深证/创业板三大指数。
    字段：现价/涨跌/涨跌幅/今开/最高/最低/成交量/成交额/换手率/PE/PB/总市值。
    """
    if target == "指数":
        symbols = ["sh000001", "sz399001", "sz399006"]
    else:
        symbols = [_resolve_symbol(target)]
    resp = _get(_TX_QUOTE_URL + ",".join(symbols), {"Referer": "https://gu.qq.com/"})
    resp.encoding = "gbk"
    lines = []
    for line in resp.text.split(";"):
        line = line.strip()
        if "=" not in line or '"' not in line:
            continue
        fields = line.split("=", 1)[1].strip().strip('"').split("~")
        if len(fields) < 47:
            continue
        price = _safe_float(fields[3])
        chg_pct = _safe_float(fields[32])
        arrow = "↑" if (chg_pct or 0) > 0 else ("↓" if (chg_pct or 0) < 0 else "—")
        lines.append(
            f"{fields[1]}({fields[2]})  最新价: {_fmt(price)}  "
            f"{arrow} 涨跌: {_fmt(_safe_float(fields[31]))} ({_fmt(chg_pct, suffix='%')})  "
            f"今开: {_fmt(_safe_float(fields[5]))}  最高: {_fmt(_safe_float(fields[33]))}  "
            f"最低: {_fmt(_safe_float(fields[34]))}"
        )
        lines.append(
            f"  成交额: {_fmt(_safe_float(fields[37]))}万  换手率: {_fmt(_safe_float(fields[38]), suffix='%')}  "
            f"PE(TTM): {_fmt(_safe_float(fields[39]))}  PB: {_fmt(_safe_float(fields[46]))}  "
            f"总市值: {_fmt(_safe_float(fields[45]))}亿"
        )
    if not lines:
        raise RuntimeError(f"未获取到行情：{target}")
    return "\n".join(lines)


def _fetch_sina_sectors() -> List[Dict[str, Any]]:
    """抓取新浪行业+概念板块全量行情（同一格式）"""
    sectors: List[Dict[str, Any]] = []
    for url, key in ((_SINA_INDUSTRY_URL, "S_Finance_bankuai_sinaindustry"),
                     (_SINA_CONCEPT_URL, "S_Finance_bankuai_class")):
        resp = _get(url, {"Referer": "https://finance.sina.com.cn/"})
        resp.encoding = "gbk"
        m = re.search(r"var\s+" + key + r"\s*=", resp.text)
        if not m:
            continue
        body = resp.text[m.end():]
        body = body[body.index("{"): body.rindex("}") + 1]
        for code, row in json.loads(body).items():
            parts = str(row).split(",")
            if len(parts) < 13:
                continue
            sectors.append({
                "code": code,
                "name": parts[1],
                "stock_count": int(_safe_float(parts[2]) or 0),
                "avg_price": _safe_float(parts[3]),
                "change_pct": _safe_float(parts[5]),
                "amount": _safe_float(parts[7]),
                "leader_name": parts[12],
                "leader_pct": _safe_float(parts[9]),
            })
    return sectors


def fetch_sector_text(sector: str) -> str:
    """
    新浪板块行情文本（免费公开接口）。行业/概念一次全量拉取后按名称匹配。

    注意：免费源不含板块成分股明细与资金流向数据。
    """
    sectors = _fetch_sina_sectors()
    if not sectors:
        raise RuntimeError("未获取到板块数据")

    matches = [s for s in sectors if s["name"] == sector]
    if not matches:
        matches = [s for s in sectors if sector in s["name"] or s["name"] in sector]
    if not matches:
        return f"未找到「{sector}」板块（新浪行业/概念分类）。请尝试标准板块名称，如：银行、煤炭行业、生物制药、锂电池、人工智能等。"

    matches.sort(key=lambda s: -(s["change_pct"] or 0))
    lines = []
    for s in matches[:8]:
        amount_yi = (s["amount"] / 1e8) if s["amount"] else None
        lines.append(
            f"{s['name']}  涨跌幅: {_fmt(s['change_pct'], suffix='%')}  "
            f"家数: {s['stock_count']}  均价: {_fmt(s['avg_price'])}  "
            f"成交额: {_fmt(amount_yi, 1)}亿  "
            f"领涨股: {s['leader_name']}({_fmt(s['leader_pct'], suffix='%')})"
        )
    lines.append("（注：免费数据源不含板块成分股明细与资金流向；成分股查询请通过平台 AI 助手）")
    return "\n".join(lines)


# ============================================================================
# 4. Skill路由调度器 — 调用其他模块
# ============================================================================

class SkillRouter:
    """
    技能路由器：根据意图自动选择并组合多个Skill模块。
    支持单模块调用、多模块串联、条件过滤。
    """

    def __init__(self, skills_dir: Optional[str] = None):
        self.skills_dir = Path(skills_dir) if skills_dir else self._find_skills_dir()

    @staticmethod
    def _find_skills_dir() -> Path:
        """自动查找skills目录"""
        candidates = [
            Path(__file__).parent.parent,  # 当前skill的父目录（即skills/）
            Path(os.getenv("HERMES_SKILLS_DIR", "")),
            Path.home() / ".hermes" / "profiles" / "fenxi" / "skills",
        ]
        for p in candidates:
            if (p / "tech-indicators").exists():
                return p
        # 回退到当前目录的父级
        return Path(__file__).parent.parent

    def route(self, intent_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        根据意图生成执行计划（模块调用列表）。

        Returns:
            [{"module": str, "params": dict, "description": str}, ...]
        """
        intent = intent_result["intent"]
        entities = intent_result.get("entities", {})
        conditions = intent_result.get("conditions", {})

        plans: List[Dict[str, Any]] = []

        if intent == "stock_diagnosis":
            stock = entities.get("stock", "")
            if not stock:
                return [{"module": "error", "params": {"message": "未识别到股票名称，请指定股票代码或名称"}}]
            plans.extend([
                {
                    "module": "quote",
                    "params": {"target": stock},
                    "description": "获取行情数据",
                },
                {
                    "module": "tech-indicators",
                    "params": {"stock_code": stock, "period": "近一年"},
                    "description": "计算技术指标",
                },
                {
                    "module": "kline-patterns",
                    "params": {"stock_code": stock, "periods": 200},
                    "description": "识别K线形态",
                },
                {
                    "module": "multi-factor",
                    "params": {"stock_name": stock},
                    "description": "基本面多因子分析",
                },
            ])

        elif intent == "stock_selection":
            plans.extend([
                {
                    "module": "multi-factor",
                    "params": {"conditions": conditions, "mode": "screen"},
                    "description": f"多因子选股（条件: {conditions or '默认'}）",
                },
                {
                    "module": "market-sentiment",
                    "params": {},
                    "description": "市场情绪过滤",
                },
            ])

        elif intent == "market_query":
            plans.extend([
                {
                    "module": "quote",
                    "params": {"target": "指数"},
                    "description": "获取大盘指数行情",
                },
                {
                    "module": "market-sentiment",
                    "params": {},
                    "description": "市场情绪分析",
                },
            ])

        elif intent == "sector_analysis":
            sector = entities.get("sector", "")
            if not sector:
                return [{"module": "error", "params": {"message": "未识别到板块名称"}}]
            plans.extend([
                {
                    "module": "sector",
                    "params": {"sector": sector},
                    "description": f"获取{sector}板块行情（含领涨股）",
                },
            ])

        elif intent == "news_search":
            topic = entities.get("topic") or entities.get("stock", "")
            if not topic:
                return [{"module": "error", "params": {"message": "未识别到搜索主题"}}]
            plans.append({
                "module": "news",
                "params": {"topic": topic},
                "description": f"{topic}资讯检索",
            })

        elif intent == "strategy_run":
            plans.append({
                "module": "a-share-oversold-rebound-strategy",
                "params": {"command": "screen"},
                "description": "执行超跌反弹选股策略",
            })

        else:  # unknown
            plans.append({
                "module": "error",
                "params": {
                    "message": f"无法识别意图，请尝试更具体的描述。支持的类型：个股诊断、选股推荐、行情查询、板块分析、资讯搜索、策略执行"
                },
            })

        return plans

    def execute(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单个模块调用，返回结果。

        Returns:
            {"module": str, "status": "success"/"error", "output": str, "data": any}
        """
        module = plan["module"]
        params = plan.get("params", {})
        description = plan.get("description", "")

        try:
            if module == "quote":
                return self._run_quote(params)
            elif module == "sector":
                return self._run_sector(params)
            elif module == "news":
                return self._run_news(params)
            elif module == "tech-indicators":
                return self._run_tech_indicators(params)
            elif module == "kline-patterns":
                return self._run_kline_patterns(params)
            elif module == "multi-factor":
                return self._run_multi_factor(params)
            elif module == "market-sentiment":
                return self._run_market_sentiment(params)
            elif module == "a-share-oversold-rebound-strategy":
                return self._run_strategy(params)
            else:
                return {
                    "module": module,
                    "status": "error",
                    "output": f"未知模块: {module}",
                    "data": None,
                }
        except Exception as e:
            return {
                "module": module,
                "status": "error",
                "output": f"{description} 执行失败: {str(e)}",
                "data": None,
            }

    def _run_quote(self, params: Dict) -> Dict[str, Any]:
        """腾讯实时行情（免费公开接口，内置实现）"""
        try:
            output = fetch_quote_text(params.get("target", "指数"))
            return {"module": "quote", "status": "success", "output": output, "data": None}
        except Exception as e:
            return {"module": "quote", "status": "error", "output": f"行情获取失败: {e}", "data": None}

    def _run_sector(self, params: Dict) -> Dict[str, Any]:
        """新浪板块行情（免费公开接口，内置实现）"""
        try:
            output = fetch_sector_text(params.get("sector", ""))
            return {"module": "sector", "status": "success", "output": output, "data": None}
        except Exception as e:
            return {"module": "sector", "status": "error", "output": f"板块数据获取失败: {e}", "data": None}

    def _run_news(self, params: Dict) -> Dict[str, Any]:
        """资讯检索：无免费数据源，仅返回指引（禁止伪造新闻）"""
        topic = params.get("topic", "")
        output = (f"本地技能已不再内置资讯检索（无稳定的免费资讯数据源）。\n"
                  f"「{topic}」相关资讯请通过平台 AI 助手获取。")
        return {"module": "news", "status": "success", "output": output, "data": None}

    def _run_tech_indicators(self, params: Dict) -> Dict[str, Any]:
        """调用 tech-indicators 模块"""
        script = self.skills_dir / "tech-indicators" / "tech_indicators.py"
        stock_code = params.get("stock_code", "")
        period = params.get("period", "近一年")

        cmd = [sys.executable, str(script), stock_code, period]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace"
        )
        output = result.stdout.strip() or result.stderr.strip()
        status = "success" if result.returncode == 0 else "error"

        return {"module": "tech-indicators", "status": status, "output": output, "data": None}

    def _run_kline_patterns(self, params: Dict) -> Dict[str, Any]:
        """调用 kline-patterns 模块"""
        script = self.skills_dir / "kline-patterns" / "kline_patterns.py"
        stock_code = params.get("stock_code", "")
        periods = params.get("periods", 200)

        cmd = [sys.executable, str(script), stock_code, str(periods)]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace"
        )
        output = result.stdout.strip() or result.stderr.strip()
        status = "success" if result.returncode == 0 else "error"

        return {"module": "kline-patterns", "status": status, "output": output, "data": None}

    def _run_multi_factor(self, params: Dict) -> Dict[str, Any]:
        """调用 multi-factor 模块"""
        script = self.skills_dir / "multi-factor" / "multi_factor.py"
        stock_name = params.get("stock_name", "")
        mode = params.get("mode", "analyze")

        if mode == "screen":
            conditions = params.get("conditions", {})
            cmd_args = [sys.executable, str(script), "--mode", "screen"]
            if conditions:
                # 传递条件参数
                if conditions.get("value_weight"):
                    cmd_args.extend(["--value-weight", str(conditions["value_weight"])])
                if conditions.get("growth_weight"):
                    cmd_args.extend(["--growth-weight", str(conditions["growth_weight"])])
        else:
            cmd_args = [sys.executable, str(script), "--stock", stock_name]

        result = subprocess.run(
            cmd_args, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace"
        )
        output = result.stdout.strip() or result.stderr.strip()
        status = "success" if result.returncode == 0 else "error"

        return {"module": "multi-factor", "status": status, "output": output, "data": None}

    def _run_market_sentiment(self, params: Dict) -> Dict[str, Any]:
        """调用 market-sentiment 模块"""
        script = self.skills_dir / "market-sentiment" / "market_sentiment.py"
        cmd = [sys.executable, str(script), "--report"]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace"
        )
        output = result.stdout.strip() or result.stderr.strip()
        status = "success" if result.returncode == 0 else "error"

        return {"module": "market-sentiment", "status": status, "output": output, "data": None}

    def _run_strategy(self, params: Dict) -> Dict[str, Any]:
        """调用 a-share-oversold-rebound-strategy 模块"""
        script = self.skills_dir / "a-share-oversold-rebound-strategy" / "a_share_overshot.py"
        command = params.get("command", "screen")

        cmd = [sys.executable, str(script), command]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace"
        )
        output = result.stdout.strip() or result.stderr.strip()
        status = "success" if result.returncode == 0 else "error"

        return {"module": "a-share-oversold-rebound-strategy", "status": status, "output": output, "data": None}


# ============================================================================
# 4. 综合报告生成 — 模板引擎
# ============================================================================

class ReportGenerator:
    """
    报告模板引擎：将多个模块的输出整合为结构化中文报告。
    不同意图类型对应不同的报告格式。
    """

    def generate(self, intent: str, results: List[Dict[str, Any]], entities: Dict) -> str:
        """根据意图类型生成综合报告"""
        if intent == "stock_diagnosis":
            return self._stock_diagnosis_report(results, entities)
        elif intent == "stock_selection":
            return self._stock_selection_report(results, entities)
        elif intent == "market_query":
            return self._market_analysis_report(results, entities)
        elif intent == "sector_analysis":
            return self._sector_analysis_report(results, entities)
        elif intent == "news_search":
            return self._news_report(results, entities)
        elif intent == "strategy_run":
            return self._strategy_report(results, entities)
        else:
            return self._unknown_report(intent, results)

    def _stock_diagnosis_report(self, results: List[Dict], entities: Dict) -> str:
        """个股诊断报告"""
        stock = entities.get("stock", "未知")
        lines = []
        sep = "=" * 60

        lines.append(sep)
        lines.append(f"📊 {stock} — 个股综合诊断报告")
        lines.append(f"   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(sep)

        # ── 行情概览 ────────────────────────────────
        quote_result = self._find_result(results, "quote")
        if quote_result and quote_result["status"] == "success":
            lines.append("")
            lines.append("━" * 40)
            lines.append("📈 一、行情概览")
            lines.append("━" * 40)
            # 提取前15行作为概览
            output_lines = quote_result["output"].split("\n")[:20]
            for line in output_lines:
                if line.strip():
                    lines.append(f"   {line}")

        # ── 技术指标信号 ────────────────────────────
        tech_result = self._find_result(results, "tech-indicators")
        if tech_result and tech_result["status"] == "success":
            lines.append("")
            lines.append("━" * 40)
            lines.append("📈 二、技术指标信号")
            lines.append("━" * 40)
            output_lines = tech_result["output"].split("\n")
            # 提取关键信号行（包含金叉/死叉/超买/超卖等关键词）
            signal_lines = [l for l in output_lines if any(
                kw in l for kw in ["金叉", "死叉", "多头", "空头", "超买", "超卖", "排列", "信号"]
            )]
            if signal_lines:
                for line in signal_lines[:15]:
                    lines.append(f"   {line}")
            else:
                # 回退：显示最后20行（通常包含总结）
                for line in output_lines[-20:]:
                    if line.strip():
                        lines.append(f"   {line}")

        # ── K线形态 ────────────────────────────────
        kline_result = self._find_result(results, "kline-patterns")
        if kline_result and kline_result["status"] == "success":
            lines.append("")
            lines.append("━" * 40)
            lines.append("📈 三、K线形态识别")
            lines.append("━" * 40)
            output_lines = kline_result["output"].split("\n")
            # 提取形态信号
            pattern_lines = [l for l in output_lines if any(
                kw in l for kw in ["形态", "bullish", "bearish", "十字星", "锤子", "射击", "大阳", "大阴"]
            )]
            if pattern_lines:
                for line in pattern_lines[:10]:
                    lines.append(f"   {line}")
            else:
                for line in output_lines[-15:]:
                    if line.strip():
                        lines.append(f"   {line}")

        # ── 基本面评分 ────────────────────────────────
        mf_result = self._find_result(results, "multi-factor")
        if mf_result and mf_result["status"] == "success":
            lines.append("")
            lines.append("━" * 40)
            lines.append("📈 四、基本面多因子分析")
            lines.append("━" * 40)
            output_lines = mf_result["output"].split("\n")[-25:]
            for line in output_lines:
                if line.strip():
                    lines.append(f"   {line}")

        # ── 综合建议 ────────────────────────────────
        lines.append("")
        lines.append("━" * 40)
        lines.append("💡 五、综合评估")
        lines.append("━" * 40)
        lines.extend(self._generate_summary_advice(results, stock))

        lines.append("")
        lines.append(sep)
        lines.append("⚠️ 免责声明：以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。")
        lines.append(sep)

        return "\n".join(lines)

    def _stock_selection_report(self, results: List[Dict], entities: Dict) -> str:
        """选股推荐报告"""
        conditions = entities.get("conditions", {}) or {}
        lines = []
        sep = "=" * 60

        lines.append(sep)
        lines.append("📊 A股多因子选股推荐报告")
        lines.append(f"   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        if conditions:
            cond_str = ", ".join(f"{k}={v}" for k, v in conditions.items())
            lines.append(f"   筛选条件: {cond_str}")
        else:
            lines.append("   筛选条件: 默认多因子综合评分")
        lines.append(sep)

        # ── 选股结果 ────────────────────────────────
        mf_result = self._find_result(results, "multi-factor")
        if mf_result and mf_result["status"] == "success":
            lines.append("")
            lines.append("━" * 40)
            lines.append("📋 一、候选股票列表")
            lines.append("━" * 40)
            output_lines = mf_result["output"].split("\n")[-30:]
            for line in output_lines:
                if line.strip():
                    lines.append(f"   {line}")

        # ── 市场情绪过滤 ────────────────────────────
        sentiment_result = self._find_result(results, "market-sentiment")
        if sentiment_result and sentiment_result["status"] == "success":
            lines.append("")
            lines.append("━" * 40)
            lines.append("📊 二、市场情绪环境")
            lines.append("━" * 40)
            output_lines = sentiment_result["output"].split("\n")[-15:]
            for line in output_lines:
                if line.strip():
                    lines.append(f"   {line}")

        # ── 风险提示 ────────────────────────────────
        lines.append("")
        lines.append("━" * 40)
        lines.append("⚠️ 三、风险提示")
        lines.append("━" * 40)
        lines.append("   • 选股结果基于历史数据和量化模型，不保证未来表现")
        lines.append("   • 建议结合基本面研究和市场情绪综合判断")
        lines.append("   • 分散投资，控制仓位，设置止损")

        lines.append("")
        lines.append(sep)
        lines.append("⚠️ 免责声明：以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。")
        lines.append(sep)

        return "\n".join(lines)

    def _market_analysis_report(self, results: List[Dict], entities: Dict) -> str:
        """市场分析报告"""
        lines = []
        sep = "=" * 60

        lines.append(sep)
        lines.append("📊 A股市场综合分析报告")
        lines.append(f"   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(sep)

        # ── 大盘走势 ────────────────────────────────
        quote_result = self._find_result(results, "quote")
        if quote_result and quote_result["status"] == "success":
            lines.append("")
            lines.append("━" * 40)
            lines.append("📈 一、大盘指数走势")
            lines.append("━" * 40)
            output_lines = quote_result["output"].split("\n")[:25]
            for line in output_lines:
                if line.strip():
                    lines.append(f"   {line}")

        # ── 情绪评分 ────────────────────────────────
        sentiment_result = self._find_result(results, "market-sentiment")
        if sentiment_result and sentiment_result["status"] == "success":
            lines.append("")
            lines.append("━" * 40)
            lines.append("📊 二、市场情绪评分")
            lines.append("━" * 40)
            output_lines = sentiment_result["output"].split("\n")[-20:]
            for line in output_lines:
                if line.strip():
                    lines.append(f"   {line}")

        # ── 板块强弱 ────────────────────────────────
        lines.append("")
        lines.append("━" * 40)
        lines.append("📊 三、板块强弱分析")
        lines.append("━" * 40)
        if sentiment_result and "sector" in str(sentiment_result.get("output", "")):
            sector_lines = [l for l in sentiment_result["output"].split("\n")
                          if any(kw in l for kw in ["板块", "行业", "领涨", "领跌"])]
            for line in sector_lines[:10]:
                lines.append(f"   {line}")
        else:
            lines.append("   （板块数据来自市场情绪模块，详见上方情绪报告）")

        # ── 异动个股 ────────────────────────────────
        lines.append("")
        lines.append("━" * 40)
        lines.append("📊 四、异动提示")
        lines.append("━" * 40)
        if sentiment_result:
            anomaly_lines = [l for l in sentiment_result["output"].split("\n")
                           if any(kw in l for kw in ["涨停", "跌停", "异动", "放量"])]
            if anomaly_lines:
                for line in anomaly_lines[:10]:
                    lines.append(f"   {line}")
            else:
                lines.append("   （暂无显著异动信号）")

        lines.append("")
        lines.append(sep)
        lines.append("⚠️ 免责声明：以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。")
        lines.append(sep)

        return "\n".join(lines)

    def _sector_analysis_report(self, results: List[Dict], entities: Dict) -> str:
        """板块分析报告"""
        sector = entities.get("sector", "未知板块")
        lines = []
        sep = "=" * 60

        lines.append(sep)
        lines.append(f"📊 {sector}板块 — 综合分析报告")
        lines.append(f"   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(sep)

        for i, result in enumerate(results):
            if result["status"] == "success":
                lines.append("")
                lines.append("━" * 40)
                desc = result.get("description", f"模块 {i+1}")
                lines.append(f"📋 {desc}")
                lines.append("━" * 40)
                output_lines = result["output"].split("\n")[-25:]
                for line in output_lines:
                    if line.strip():
                        lines.append(f"   {line}")

        # ── 个股表现 ────────────────────────────────
        lines.append("")
        lines.append("━" * 40)
        lines.append("💡 板块投资建议")
        lines.append("━" * 40)
        lines.append(f"   • {sector}板块近期表现需结合大盘环境综合判断")
        lines.append(f"   • 建议关注板块内龙头股和资金流入明显的个股")
        lines.append(f"   • 注意板块轮动节奏，避免追高")

        lines.append("")
        lines.append(sep)
        lines.append("⚠️ 免责声明：以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。")
        lines.append(sep)

        return "\n".join(lines)

    def _news_report(self, results: List[Dict], entities: Dict) -> str:
        """资讯搜索报告"""
        topic = entities.get("topic") or entities.get("stock", "未知主题")
        lines = []
        sep = "=" * 60

        lines.append(sep)
        lines.append(f"📰 {topic} — 最新资讯汇总")
        lines.append(f"   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(sep)

        news_result = self._find_result(results, "news")
        if news_result and news_result["status"] == "success":
            output_lines = news_result["output"].split("\n")[-40:]
            for line in output_lines:
                if line.strip():
                    lines.append(f"   {line}")
        else:
            lines.append("")
            lines.append("⚠️ 未获取到相关资讯，请检查网络连接或尝试其他关键词。")

        lines.append("")
        lines.append(sep)
        return "\n".join(lines)

    def _strategy_report(self, results: List[Dict], entities: Dict) -> str:
        """策略执行报告"""
        lines = []
        sep = "=" * 60

        lines.append(sep)
        lines.append("📊 超跌反弹选股策略 — 执行结果")
        lines.append(f"   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(sep)

        strategy_result = self._find_result(results, "a-share-oversold-rebound-strategy")
        if strategy_result and strategy_result["status"] == "success":
            output_lines = strategy_result["output"].split("\n")[-40:]
            for line in output_lines:
                if line.strip():
                    lines.append(f"   {line}")
        else:
            lines.append("")
            lines.append("⚠️ 策略执行失败或无结果。可能原因：")
            lines.append("   • 非交易时间（策略在交易日14:30后运行）")
            lines.append("   • 市场跌幅未触发选股条件")

        lines.append("")
        lines.append(sep)
        lines.append("⚠️ 免责声明：以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。")
        lines.append(sep)

        return "\n".join(lines)

    def _unknown_report(self, intent: str, results: List[Dict]) -> str:
        """未知意图报告"""
        error_result = self._find_result(results, "error")
        msg = error_result["output"] if error_result else f"无法识别意图类型: {intent}"

        lines = [
            "=" * 60,
            "❓ 未能识别您的查询意图",
            "-" * 60,
            f"   {msg}",
            "",
            "💡 支持的查询类型及示例：",
            "   • 个股诊断: '帮我看看贵州茅台怎么样'",
            "   • 选股推荐: '找一只适合低吸的股票'",
            "   • 行情查询: '今天大盘走势如何'",
            "   • 板块分析: '新能源板块最近怎么样'",
            "   • 资讯搜索: '比亚迪有什么最新消息'",
            "   • 策略执行: '超跌反弹选股结果出来了吗'",
            "=" * 60,
        ]
        return "\n".join(lines)

    def _generate_summary_advice(self, results: List[Dict], stock: str) -> List[str]:
        """根据各模块结果生成综合建议"""
        advice = []
        buy_signals = 0
        sell_signals = 0
        neutral_signals = 0

        # 分析技术指标信号
        tech_result = self._find_result(results, "tech-indicators")
        if tech_result and tech_result["status"] == "success":
            output = tech_result["output"]
            buy_signals += output.count("金叉") + output.count("超卖") + output.count("多头")
            sell_signals += output.count("死叉") + output.count("超买") + output.count("空头")

        # 分析K线形态信号
        kline_result = self._find_result(results, "kline-patterns")
        if kline_result and kline_result["status"] == "success":
            output = kline_result["output"]
            buy_signals += output.count("bullish")
            sell_signals += output.count("bearish")

        # 综合判断
        total = buy_signals + sell_signals + neutral_signals
        if total == 0:
            advice.append(f"   • {stock}：各模块信号不明确，建议观望或进一步研究")
        elif buy_signals > sell_signals:
            strength = "较强" if buy_signals >= 3 else "一般"
            advice.append(f"   • {stock}：技术面偏多（买入信号{buy_signals} vs 卖出信号{sell_signals}），趋势{strength}")
            advice.append("     → 建议关注，但需设置止损位")
        elif sell_signals > buy_signals:
            strength = "较强" if sell_signals >= 3 else "一般"
            advice.append(f"   • {stock}：技术面偏空（卖出信号{sell_signals} vs 买入信号{buy_signals}），下行风险{strength}")
            advice.append("     → 建议谨慎，等待企稳信号")
        else:
            advice.append(f"   • {stock}：多空信号均衡，市场处于震荡状态")
            advice.append("     → 建议观望，等待方向明确")

        return advice

    @staticmethod
    def _find_result(results: List[Dict], module_name: str) -> Optional[Dict]:
        """从结果列表中查找指定模块的结果"""
        for r in results:
            if r.get("module") == module_name:
                return r
        return None


# ============================================================================
# 5. NLP分析器 — 主控制器
# ============================================================================

class NLPAnalyzer:
    """
    A股自然语言对话分析引擎 — 主控制器。
    整合意图识别、Skill路由、报告生成和对话记忆。
    """

    def __init__(self, skills_dir: Optional[str] = None):
        self.classifier = IntentClassifier()
        self.router = SkillRouter(skills_dir)
        self.reporter = ReportGenerator()
        self.memory = ConversationMemory()

    def analyze(self, query: str) -> str:
        """
        单次查询分析入口。

        Args:
            query: 用户自然语言查询

        Returns:
            综合分析报告（字符串）
        """
        # ── Step 1: 对话记忆消歧 ────────────────────────
        resolved_query, resolved_entities = self.memory.resolve(query)

        # ── Step 2: 意图识别 ────────────────────────────
        intent_result = self.classifier.classify(resolved_query)

        # 合并消歧后的实体
        if resolved_entities:
            intent_result["entities"].update(resolved_entities)

        # ── Step 3: 更新对话记忆 ────────────────────────
        self.memory.update(intent_result)

        # ── Step 4: 生成执行计划 ────────────────────────
        plans = self.router.route(intent_result)

        # ── Step 5: 执行模块调用（串行） ────────────────
        results: List[Dict[str, Any]] = []
        for plan in plans:
            result = self.router.execute(plan)
            results.append({**plan, **result})

        # ── Step 6: 生成综合报告 ────────────────────────
        report = self.reporter.generate(
            intent_result["intent"], results, intent_result["entities"]
        )

        return report

    def chat(self):
        """对话模式入口"""
        print("=" * 60)
        print("🤖 A股自然语言对话分析引擎")
        print("=" * 60)
        print("💡 支持的查询类型：")
        print("   • 个股诊断: '帮我看看贵州茅台怎么样'")
        print("   • 选股推荐: '找一只适合低吸的股票'")
        print("   • 行情查询: '今天大盘走势如何'")
        print("   • 板块分析: '新能源板块最近怎么样'")
        print("   • 资讯搜索: '比亚迪有什么最新消息'")
        print("   • 策略执行: '超跌反弹选股结果出来了吗'")
        print("-" * 60)
        print("输入 'quit' / 'exit' / 'q' 退出对话\n")

        while True:
            try:
                query = input("👤 你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break

            if not query:
                continue
            if query.lower() in ("quit", "exit", "q"):
                print("再见！")
                break

            # 显示意图识别结果
            resolved_query, _ = self.memory.resolve(query)
            intent_result = self.classifier.classify(resolved_query)
            intent_label_map = {
                "stock_diagnosis": "🔍 个股诊断",
                "stock_selection": "📊 选股推荐",
                "market_query": "📈 行情查询",
                "sector_analysis": "🏭 板块分析",
                "news_search": "📰 资讯搜索",
                "strategy_run": "⚙️ 策略执行",
                "unknown": "❓ 未知意图",
            }
            intent_label = intent_label_map.get(intent_result["intent"], f"❓ {intent_result['intent']}")
            print(f"\n🤖 [{intent_label}] (置信度: {intent_result['confidence']})\n")

            # 执行分析并输出报告
            report = self.analyze(query)
            print(report)
            print()


# ============================================================================
# CLI入口
# ============================================================================

def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="A股自然语言对话分析引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python nlp_analyzer.py "帮我看看贵州茅台怎么样"     # 单次查询
  python nlp_analyzer.py --chat                       # 对话模式
  python nlp_analyzer.py --batch queries.txt          # 批量处理
  python nlp_analyzer.py --intent-only "大盘走势如何"  # 仅显示意图识别结果
        """,
    )
    parser.add_argument("query", nargs="?", default=None, help="查询语句（单次模式）")
    parser.add_argument("--chat", action="store_true", help="进入对话模式")
    parser.add_argument("--batch", type=str, help="批量处理文件路径（每行一个查询）")
    parser.add_argument("--intent-only", action="store_true", help="仅显示意图识别结果，不执行分析")
    parser.add_argument("--skills-dir", type=str, default=None, help="Skills目录路径")

    args = parser.parse_args()

    analyzer = NLPAnalyzer(skills_dir=args.skills_dir)

    if args.chat:
        analyzer.chat()
    elif args.batch:
        # 批量处理模式
        try:
            with open(args.batch, "r", encoding="utf-8") as f:
                queries = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            print(f"❌ 文件不存在: {args.batch}")
            sys.exit(1)

        for i, query in enumerate(queries, 1):
            print(f"\n{'='*60}")
            print(f"[{i}/{len(queries)}] 查询: {query}")
            print("=" * 60)

            if args.intent_only:
                resolved_query, _ = analyzer.memory.resolve(query)
                result = analyzer.classifier.classify(resolved_query)
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                report = analyzer.analyze(query)
                print(report)

    elif args.query:
        # 单次查询模式
        if args.intent_only:
            resolved_query, _ = analyzer.memory.resolve(args.query)
            result = analyzer.classifier.classify(resolved_query)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            report = analyzer.analyze(args.query)
            print(report)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
