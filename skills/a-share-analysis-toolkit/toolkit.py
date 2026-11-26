#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股分析统一入口工具包 (A-Share Analysis Toolkit)
==================================================
全部分析模块的总览导航和智能路由中心（数据源均为免费公开接口）。

功能：
  1. 能力矩阵总览 — 展示全部Skills的名称、描述、适用场景
  2. 智能路由引擎 — 解析自然语言指令，自动匹配Skill组合
  3. 快捷命令系统 — 预设分析模板一键执行
  4. 模块状态监控 — 健康检查所有Skills和API连通性
  5. 使用指南生成器 — 自动生成Skill调用示例

用法:
  python toolkit.py overview          # 能力矩阵总览
  python toolkit.py route "贵州茅台最新价"   # 智能路由
  python toolkit.py quick stock-diag 600519  # 快捷命令-个股诊断
  python toolkit.py health             # 健康检查
  python toolkit.py guide tech-indicators  # 使用指南

作者: Hermes Agent
版本: 2.0.0
"""

import os
import sys
import json
import re
import subprocess
import importlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# ============================================================================
# 常量定义
# ============================================================================

SKILLS_DIR = Path(__file__).parent.parent
TOOLKIT_DIR = Path(__file__).parent

# ── 15个Skills的完整元数据 ───────────────────────────────────────
SKILLS_METADATA: Dict[str, Dict[str, Any]] = {
    # ── 技术分析层 (3) ────────────────────────────────────────
    "tech-indicators": {
        "name_cn": "技术分析指标库",
        "category": "技术分析",
        "description": "10项经典技术指标计算引擎，自动输出金叉死叉、超买超卖信号",
        "scenarios": ["MACD/KDJ/RSI/BOLL等指标计算", "均线系统分析", "买卖信号识别"],
        "script": "tech_indicators.py",
        "api_depends": [],
        "keywords": ["技术指标", "MACD", "KDJ", "RSI", "BOLL", "布林带", "均线", "金叉", "死叉", "超买", "超卖", "CCI", "SAR", "WR", "OBV"]
    },
    "kline-patterns": {
        "name_cn": "K线形态识别系统",
        "category": "技术分析",
        "description": "21种经典K线形态自动识别，含单根/双根/多根形态及置信度评分",
        "scenarios": ["看涨/看跌形态扫描", "反转信号检测", "持续形态确认"],
        "script": "kline_patterns.py",
        "api_depends": [],
        "keywords": ["K线形态", "十字星", "锤子线", "吞没", "早晨之星", "黄昏之星", "形态识别"]
    },
    "nlp-analyzer": {
        "name_cn": "自然语言对话分析",
        "category": "技术分析",
        "description": "NLP意图识别+智能路由，6种意图分类自动组合多模块生成综合报告",
        "scenarios": ["自然语言个股诊断", "多轮对话上下文记忆", "综合分析报告"],
        "script": "nlp_analyzer.py",
        "api_depends": [],
        "keywords": ["对话分析", "意图识别", "智能路由", "综合分析"]
    },

    # ── 量化选股层 (5) ────────────────────────────────────────
    "multi-factor": {
        "name_cn": "多因子选股框架",
        "category": "量化选股",
        "description": "27个经典量化因子（价值/成长/质量/动量/波动/流动性），支持Z-Score标准化和IC加权合成",
        "scenarios": ["低估值高成长筛选", "自定义因子权重", "多因子综合评分"],
        "script": "multi_factor.py",
        "api_depends": [],
        "keywords": ["多因子", "因子选股", "价值因子", "成长因子", "质量因子", "动量因子", "波动因子", "流动性因子"]
    },
    "ml-stock-picker": {
        "name_cn": "机器学习选股",
        "category": "量化选股",
        "description": "LightGBM/XGBoost模型驱动的智能选股，支持特征工程、训练预测全流程",
        "scenarios": ["模型训练与评估", "批量股票打分排序", "交叉验证调参"],
        "script": "ml_stock_picker.py",
        "api_depends": [],
        "keywords": ["机器学习", "LightGBM", "XGBoost", "预测", "模型选股"]
    },
    "capital-flow": {
        "name_cn": "资金流向选股",
        "category": "量化选股",
        "description": "基于主力资金流向、订单大小分类和量价关系进行智能选股，检测连续流入和量价背离",
        "scenarios": ["主力净流入筛选", "连续资金流入检测", "量价背离识别", "资金强度评分"],
        "script": "capital_flow.py",
        "api_depends": [],
        "keywords": ["资金流向", "主力流入", "超大单", "量价背离", "连续流入"]
    },
    "multi-strategy": {
        "name_cn": "多策略库扩展",
        "category": "量化选股",
        "description": "6大类18种经典交易策略（趋势跟踪/均值回归/动量/龙头战法/低吸蓝筹/网格交易）",
        "scenarios": ["策略信号扫描", "多策略对比回测", "信号强度排名"],
        "script": "multi_strategy.py",
        "api_depends": [],
        "keywords": ["策略", "趋势跟踪", "均值回归", "动量策略", "龙头战法", "低吸蓝筹", "网格交易"]
    },

    # ── 策略融合层 (1) ────────────────────────────────────────
    "strategy-combo": {
        "name_cn": "策略组合引擎",
        "category": "策略融合",
        "description": "多策略信号融合系统，支持投票融合、加权融合和冲突检测",
        "scenarios": ["多数表决选股", "加权评分合成", "策略分歧分析"],
        "script": "strategy_combo.py",
        "api_depends": [],
        "keywords": ["策略组合", "多策略融合", "投票", "加权", "冲突检测"]
    },

    # ── 基础设施层 (1) ────────────────────────────────────────
    "data-cache": {
        "name_cn": "数据缓存层",
        "category": "基础设施",
        "description": "基于SQLite的本地数据缓存，减少API重复调用，支持K线/财务/快照分级缓存",
        "scenarios": ["K线数据缓存", "财务指标缓存", "缓存统计清理"],
        "script": "data_cache.py",
        "api_depends": [],
        "keywords": ["缓存", "SQLite", "性能优化"]
    },

    # ── 市场监控层 (2) ────────────────────────────────────────
    "market-sentiment": {
        "name_cn": "市场情绪量化指标",
        "category": "市场监控",
        "description": "17项市场情绪指标+综合评分（0-100分），冰点/低迷/温和/亢奋/过热五档分类",
        "scenarios": ["大盘情绪评估", "涨跌统计", "连板高度分析", "恐慌贪婪指数"],
        "script": "market_sentiment.py",
        "api_depends": [],
        "keywords": ["市场情绪", "情绪评分", "涨跌家数", "涨停跌停", "连板", "恐慌", "贪婪"]
    },
    "sector-rotation": {
        "name_cn": "板块轮动追踪",
        "category": "市场监控",
        "description": "行业/概念板块行情总览（新浪板块源）、RPS强度排名、热点题材追踪、四阶段周期定位",
        "scenarios": ["板块涨跌排行", "热点题材发现", "轮动信号判断"],
        "script": "sector_rotation.py",
        "api_depends": [],
        "keywords": ["板块轮动", "行业排名", "概念板块", "RPS强度", "热点题材"]
    },

    # ── 策略执行层 (1) ────────────────────────────────────────
    "dragon-list": {
        "name_cn": "龙虎榜分析",
        "category": "策略执行",
        "description": "龙虎榜数据获取+游资席位数据库(50+)、机构vs游资力量对比、4种选股策略",
        "scenarios": ["今日龙虎榜查看", "游资席位追踪", "机构动向分析", "龙虎榜选股"],
        "script": "dragon_list.py",
        "api_depends": [],
        "keywords": ["龙虎榜", "游资", "席位", "机构买入", "营业部"]
    },
}

# ── 路由表配置（JSON格式，映射指令关键词到Skill模块）───────────────
ROUTE_TABLE: Dict[str, List[Dict[str, Any]]] = {
    # 单模块精确匹配规则
    "single": [
        {"keywords": ["最新价", "收盘价", "开盘价", "股价", "行情", "财务", "净利润", "营收", "财报",
                      "新闻", "公告", "研报", "资讯"], "skill": "nlp-analyzer"},
        {"keywords": ["MACD", "KDJ", "RSI", "BOLL", "布林带", "均线", "技术指标"], "skill": "tech-indicators"},
        {"keywords": ["K线形态", "十字星", "锤子线", "吞没", "早晨之星", "黄昏之星"], "skill": "kline-patterns"},
        {"keywords": ["多因子", "因子选股", "价值因子", "成长因子"], "skill": "multi-factor"},
        {"keywords": ["机器学习", "LightGBM", "XGBoost", "模型预测"], "skill": "ml-stock-picker"},
        {"keywords": ["资金流向", "主力流入", "超大单", "量价背离"], "skill": "capital-flow"},
        {"keywords": ["策略组合", "多策略融合", "投票选股"], "skill": "strategy-combo"},
        {"keywords": ["市场情绪", "情绪评分", "涨跌家数"], "skill": "market-sentiment"},
        {"keywords": ["板块轮动", "行业排名", "资金流向", "热点题材"], "skill": "sector-rotation"},
        {"keywords": ["龙虎榜", "游资席位", "机构买入"], "skill": "dragon-list"},
        {"keywords": ["策略扫描", "趋势跟踪", "龙头战法", "网格交易"], "skill": "multi-strategy"},
    ],

    # 多模块串联规则（按优先级排序）
    "composite": [
        {
            "name": "个股诊断",
            "keywords": ["怎么样", "分析一下", "全面分析", "深度分析", "诊断", "看看"],
            "skills": ["nlp-analyzer", "tech-indicators", "kline-patterns", "multi-factor"],
            "description": "行情（腾讯源） + 技术指标 + K线形态 + 基本面评分"
        },
        {
            "name": "选股推荐",
            "keywords": ["选只股票", "推荐股票", "找什么股", "买什么", "值得买的"],
            "skills": ["multi-factor", "market-sentiment", "dragon-list"],
            "description": "多因子筛选 + 市场情绪过滤 + 龙虎榜验证"
        },
        {
            "name": "市场复盘",
            "keywords": ["今天大盘", "市场怎么样", "复盘", "今日行情", "大盘走势"],
            "skills": ["nlp-analyzer", "sector-rotation", "market-sentiment", "dragon-list"],
            "description": "大盘指数行情（腾讯源） + 板块涨跌排行 + 情绪评分 + 异动个股"
        },
        {
            "name": "策略扫描",
            "keywords": ["运行策略", "策略信号", "信号排名"],
            "skills": ["multi-strategy", "market-sentiment"],
            "description": "多策略信号扫描 + 情绪环境判断"
        },
    ],

    # 条件过滤路由规则
    "conditional": [
        {
            "keywords": ["低估值", "低估"],
            "skill": "multi-factor",
            "params": {"factors": "value", "weight": "PE:0.4,PB:0.3,PS:0.3"}
        },
        {
            "keywords": ["高成长", "成长型"],
            "skill": "multi-factor",
            "params": {"factors": "growth", "weight": "营收增速:0.4,利润增速:0.4,PEG:0.2"}
        },
        {
            "keywords": ["低估值高成长"],
            "skill": "multi-factor",
            "params": {"factors": "value,growth", "weight": "PE:0.3,PB:0.2,营收增速:0.25,利润增速:0.25"}
        },
    ],
}

# ── 快捷命令定义 ───────────────────────────────────────────────
QUICK_COMMANDS: Dict[str, Dict[str, Any]] = {
    "stock-diag": {
        "name_cn": "个股诊断",
        "description": "行情 + 技术指标 + K线形态 + 基本面评分",
        "skills": ["nlp-analyzer", "tech-indicators", "kline-patterns", "multi-factor"],
        "requires_arg": True,
        "arg_hint": "股票代码或名称（如 600519 / 贵州茅台）"
    },
    "stock-pick": {
        "name_cn": "选股推荐",
        "description": "多因子筛选 + 市场情绪过滤 + 龙虎榜验证",
        "skills": ["multi-factor", "market-sentiment", "dragon-list"],
        "requires_arg": False,
        "arg_hint": ""
    },
    "market-review": {
        "name_cn": "市场复盘",
        "description": "大盘走势 + 板块涨跌排行 + 情绪评分 + 异动个股",
        "skills": ["nlp-analyzer", "sector-rotation", "market-sentiment", "dragon-list"],
        "requires_arg": False,
        "arg_hint": ""
    },
    "strategy-scan": {
        "name_cn": "策略扫描",
        "description": "运行指定策略 + 输出信号强度排名",
        "skills": ["multi-strategy", "market-sentiment"],
        "requires_arg": False,
        "arg_hint": ""
    },
}

# ── 分类定义 ───────────────────────────────────────────────
CATEGORIES = {
    "技术分析": {"count": 3, "skills": ["tech-indicators", "kline-patterns", "nlp-analyzer"]},
    "量化选股": {"count": 3, "skills": ["multi-factor", "ml-stock-picker", "multi-strategy"]},
    "市场监控": {"count": 2, "skills": ["market-sentiment", "sector-rotation"]},
    "策略执行": {"count": 1, "skills": ["dragon-list"]},
}

# ── Python依赖清单 ───────────────────────────────────────
REQUIRED_PACKAGES = [
    "pandas", "numpy", "requests"
]
OPTIONAL_PACKAGES = [
    "lightgbm", "xgboost", "scikit-learn", "scipy"
]


# ============================================================================
# 工具函数
# ============================================================================

def print_header(title: str, char: str = "=") -> None:
    """打印标题"""
    width = len(title) + 8
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}\n")


def print_table(headers: List[str], rows: List[List[str]], col_widths: Optional[List[int]] = None) -> None:
    """打印格式化表格"""
    if not col_widths:
        col_widths = []
        for i, h in enumerate(headers):
            max_w = len(h)
            for row in rows:
                if i < len(row):
                    max_w = max(max_w, len(str(row[i])))
            col_widths.append(min(max_w + 2, 40))

    # 表头
    header_line = ""
    for h, w in zip(headers, col_widths):
        header_line += f" {h:<{w}}"
    print(header_line)
    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    print(sep)

    # 数据行
    for row in rows:
        line = ""
        for i, w in enumerate(col_widths):
            val = str(row[i]) if i < len(row) else ""
            line += f" {val:<{w}}"
        print(line)


def skill_path(skill_id: str) -> Path:
    """获取Skill目录路径"""
    return SKILLS_DIR / skill_id


def script_path(skill_id: str) -> Optional[Path]:
    """获取Skill脚本路径"""
    meta = SKILLS_METADATA.get(skill_id, {})
    script_name = meta.get("script", "")
    if not script_name:
        # 尝试从目录名推断
        name_map = {
            "tech-indicators": "tech_indicators.py",
            "kline-patterns": "kline_patterns.py",
            "multi-factor": "multi_factor.py",
            "ml-stock-picker": "ml_stock_picker.py",
            "market-sentiment": "market_sentiment.py",
            "sector-rotation": "sector_rotation.py",
            "dragon-list": "dragon_list.py",
            "nlp-analyzer": "nlp_analyzer.py",
            "multi-strategy": "multi_strategy.py",
        }
        script_name = name_map.get(skill_id, "")
    if not script_name:
        return None
    p = SKILLS_DIR / skill_id / script_name
    return p if p.exists() else None


# ============================================================================
# 1. 能力矩阵总览 (Capability Matrix)
# ============================================================================

def cmd_overview(query: Optional[str] = None) -> None:
    """展示全部Skills的能力矩阵，支持按名称/关键词过滤"""
    print_header("A股分析工具包 — 能力矩阵总览 v2.0")

    if query:
        # 快速查询某个模块
        matched = []
        for sid, meta in SKILLS_METADATA.items():
            if (query.lower() in sid.lower() or
                query in meta["name_cn"] or
                any(query in kw for kw in meta["keywords"]) or
                query in meta["description"]):
                matched.append((sid, meta))
        if not matched:
            print(f"  未找到匹配 '{query}' 的模块")
            return
        print(f"  查询结果 ({len(matched)}个匹配):\n")
        for sid, meta in matched:
            _print_skill_detail(sid, meta)
    else:
        # 按类别分组展示
        for cat_name, cat_info in CATEGORIES.items():
            print(f"\n{'─' * 50}")
            print(f"  【{cat_name}】({cat_info['count']}个模块)")
            print(f"{'─' * 50}")

            headers = ["Skill", "名称", "功能描述"]
            rows = []
            for sid in cat_info["skills"]:
                meta = SKILLS_METADATA[sid]
                rows.append([sid, meta["name_cn"], meta["description"][:60]])
            print_table(headers, rows)

        # 汇总统计
        total_skills = sum(c["count"] for c in CATEGORIES.values())
        print(f"\n  总计: {total_skills}个Skills | 5大分类")
        print(f"  提示: python toolkit.py overview <关键词> 快速查询模块\n")


def _print_skill_detail(sid: str, meta: Dict[str, Any]) -> None:
    """打印单个Skill的详细信息"""
    sp = script_path(sid)
    status = "✅" if sp else "❌"
    print(f"  {status} [{sid}] {meta['name_cn']}")
    print(f"     描述: {meta['description']}")
    print(f"     场景: {' | '.join(meta['scenarios'])}")
    script = meta.get("script", "")
    if sp:
        print(f"     脚本: {sp}")
    else:
        print(f"     脚本: {script} (未找到)")
    print()


# ============================================================================
# 2. 智能路由引擎 (Smart Router)
# ============================================================================

def cmd_route(user_input: str) -> Dict[str, Any]:
    """解析用户自然语言指令，返回匹配结果"""
    result = _smart_route(user_input)
    print_header("智能路由引擎")
    print(f"  输入: \"{user_input}\"\n")

    if result["type"] == "composite":
        print(f"  📋 路由类型: {result['name']} (多模块串联)")
        print(f"     描述: {result.get('description', '')}")
        print(f"\n  调用链 ({len(result['skills'])}个模块):\n")
        for i, sid in enumerate(result["skills"], 1):
            meta = SKILLS_METADATA[sid]
            cmd = _build_command(sid, user_input)
            print(f"     {i}. [{sid}] {meta['name_cn']}")
            print(f"        → {cmd}")
    elif result["type"] == "conditional":
        print(f"  🎯 路由类型: 条件过滤 ({result['skill']})")
        params = result.get("params", {})
        print(f"\n  调用模块: [{result['skill']}] {SKILLS_METADATA[result['skill']]['name_cn']}")
        if params:
            print(f"  参数配置:")
            for k, v in params.items():
                print(f"     {k}: {v}")
        cmd = _build_command(result["skill"], user_input)
        print(f"\n  → {cmd}\n")
    elif result["type"] == "single":
        sid = result["skill"]
        meta = SKILLS_METADATA[sid]
        print(f"  🔍 路由类型: 单模块调用")
        print(f"\n  匹配模块: [{sid}] {meta['name_cn']}")
        cmd = _build_command(sid, user_input)
        print(f"  → {cmd}\n")
    else:
        print(f"  ⚠️ 未匹配到明确路由规则")
        print(f"\n  建议尝试以下快捷命令:")
        for qid, qc in QUICK_COMMANDS.items():
            print(f"     python toolkit.py quick {qid} [参数]  # {qc['name_cn']}")

    return result


def _smart_route(user_input: str) -> Dict[str, Any]:
    """核心路由算法"""
    text = user_input.lower()

    # 1. 先检查条件过滤规则（优先级最高）
    for rule in ROUTE_TABLE["conditional"]:
        if any(kw in text for kw in rule["keywords"]):
            return {
                "type": "conditional",
                "skill": rule["skill"],
                "params": rule.get("params", {}),
                "confidence": 0.95
            }

    # 2. 检查多模块串联规则
    best_composite = None
    best_kw_count = 0
    for rule in ROUTE_TABLE["composite"]:
        kw_count = sum(1 for kw in rule["keywords"] if kw in text)
        if kw_count > best_kw_count:
            best_kw_count = kw_count
            best_composite = rule

    # 3. 检查单模块规则
    best_single = None
    best_single_score = 0
    for rule in ROUTE_TABLE["single"]:
        score = sum(1 for kw in rule["keywords"] if kw in text)
        if score > best_single_score:
            best_single_score = score
            best_single = rule

    # 决策：复合规则优先（至少匹配2个关键词），否则单模块
    if best_composite and best_kw_count >= 1:
        return {
            "type": "composite",
            "name": best_composite["name"],
            "skills": best_composite["skills"],
            "description": best_composite["description"],
            "confidence": min(0.5 + best_kw_count * 0.15, 0.95)
        }

    if best_single and best_single_score >= 1:
        return {
            "type": "single",
            "skill": best_single["skill"],
            "confidence": min(0.4 + best_single_score * 0.2, 0.9)
        }

    # 4. 兜底：全局关键词扫描所有Skills
    all_scores = {}
    for sid, meta in SKILLS_METADATA.items():
        score = sum(1 for kw in meta["keywords"] if kw in text)
        if score > 0:
            all_scores[sid] = score

    if all_scores:
        top_skill = max(all_scores, key=all_scores.get)
        return {
            "type": "single",
            "skill": top_skill,
            "confidence": min(0.3 + all_scores[top_skill] * 0.1, 0.7)
        }

    # 5. 无法匹配
    return {"type": "unknown", "confidence": 0}


def _build_command(skill_id: str, user_input: str) -> str:
    """构建Skill调用命令"""
    sp = script_path(skill_id)
    if not sp:
        return f"[脚本未找到] {skill_id}"

    # 各模块根据类型构建命令
    cmd_map = {
        "tech-indicators": f'python "{sp}" "{_extract_stock_code(user_input) or user_input}"',
        "kline-patterns": f'python "{sp}" "{_extract_stock_code(user_input) or user_input}"',
        "multi-factor": f'python "{sp}" --stocks "{user_input}"',
        "ml-stock-picker": f'python "{sp}" predict',
        "market-sentiment": f'python "{sp}" --report',
        "sector-rotation": f'python "{sp}" overview',
        "dragon-list": f'python "{sp}" today',
        "multi-strategy": f'python "{sp}" trend-following',
        "nlp-analyzer": f'python "{sp}" "{user_input}"',
    }
    return cmd_map.get(skill_id, f'python "{sp}"')


def _extract_stock_code(text: str) -> Optional[str]:
    """从文本中提取股票代码"""
    # 6位数字代码
    m = re.search(r'\b(\d{6})\b', text)
    if m:
        return m.group(1)
    return None


# ============================================================================
# 3. 快捷命令系统 (Quick Commands)
# ============================================================================

def cmd_quick(command_id: str, arg: Optional[str] = None) -> None:
    """执行预设快捷命令"""
    qc = QUICK_COMMANDS.get(command_id)
    if not qc:
        print(f"  ❌ 未知快捷命令: {command_id}")
        print(f"\n  可用命令:")
        for qid, q in QUICK_COMMANDS.items():
            arg_info = f" [{q['arg_hint']}]" if q["requires_arg"] else ""
            print(f"     {qid}: {q['name_cn']}{arg_info}")
        return

    if qc["requires_arg"] and not arg:
        print(f"  ❌ '{command_id}' 需要参数: {qc['arg_hint']}")
        return

    print_header(f"快捷命令: {qc['name_cn']}")
    print(f"  描述: {qc['description']}\n")

    if arg:
        print(f"  目标: {arg}\n")

    # 依次执行每个模块
    results = {}
    for i, sid in enumerate(qc["skills"], 1):
        sp = script_path(sid)
        cmd = _build_command(sid, arg or "")
        status_icon = "✅" if sp else "⚠️"

        print(f"  [{i}/{len(qc['skills'])}] {status_icon} [{sid}] {SKILLS_METADATA[sid]['name_cn']}")
        print(f"     命令: {cmd}")

        # 实际执行（dry-run模式，仅输出命令）
        if sp and True:  # 设置 dry_run = False 可真正执行
            try:
                env = os.environ.copy()
                proc = subprocess.run(
                    [sys.executable, str(sp)] + ([arg] if qc["requires_arg"] else []),
                    capture_output=True, text=True, timeout=120, env=env,
                    cwd=str(sp.parent)
                )
                output = proc.stdout.strip()[:500]
                if proc.returncode == 0 and output:
                    print(f"     ✓ 执行成功 ({len(output)}字符)")
                    results[sid] = {"status": "success", "output_len": len(output)}
                else:
                    err_msg = (proc.stderr.strip()[:200]) if proc.returncode != 0 else ""
                    print(f"     ✗ 执行失败: {err_msg or '无输出'}")
                    results[sid] = {"status": "error", "message": err_msg}
            except subprocess.TimeoutExpired:
                print(f"     ⏱ 超时 (120秒)")
                results[sid] = {"status": "timeout"}
            except Exception as e:
                print(f"     ✗ 异常: {e}")
                results[sid] = {"status": "error", "message": str(e)}
        else:
            print(f"     ⏭ 跳过 (脚本不存在)")
            results[sid] = {"status": "skipped"}

    # 汇总报告
    success_count = sum(1 for r in results.values() if r["status"] == "success")
    print(f"\n  ── 执行汇总 ──")
    print(f"     成功: {success_count}/{len(qc['skills'])}")
    if success_count < len(qc["skills"]):
        failed = [sid for sid, r in results.items() if r["status"] != "success"]
        print(f"     异常模块: {', '.join(failed)}")


# ============================================================================
# 4. 模块状态监控 (Module Health Check)
# ============================================================================

def cmd_health() -> Dict[str, Any]:
    """全面健康检查"""
    print_header("模块健康检查报告")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report: Dict[str, Any] = {
        "timestamp": timestamp,
        "skills": {},
        "api": {},
        "dependencies": {}
    }

    # ── 4.1 Skills安装状态检查 ────────────────────────────────
    print("  [1/3] Skills安装状态检查\n")
    headers = ["Skill", "目录", "脚本", "SKILL.md"]
    rows = []
    all_ok = True

    for sid in SKILLS_METADATA:
        dir_path = skill_path(sid)
        script_p = script_path(sid)
        skill_md = dir_path / "SKILL.md"

        dir_ok = dir_path.exists() and dir_path.is_dir()
        script_ok = script_p is not None
        md_ok = skill_md.exists()

        status = "✅" if (dir_ok and script_ok) else ("⚠️" if dir_ok else "❌")
        rows.append([
            sid,
            "✅" if dir_ok else "❌",
            f"{status} {script_p.name}" if script_ok else "❌ 未找到",
            "✅" if md_ok else "⚠️"
        ])

        report["skills"][sid] = {
            "dir": dir_ok, "script": script_ok, "skill_md": md_ok,
            "status": "ok" if (dir_ok and script_ok) else ("partial" if dir_ok else "missing")
        }

    print_table(headers, rows)

    # ── 4.2 API连通性测试 ─────────────────────────────────────
    print(f"\n\n  [2/3] API连通性测试\n")
    api_results = _test_api_connectivity()
    for name, result in api_results.items():
        icon = "✅" if result["ok"] else ("⚠️" if result.get("warn") else "❌")
        msg = result.get("message", "")
        print(f"     {icon} [{name}] {msg}")
        report["api"][name] = result

    # ── 4.3 Python依赖完整性验证 ───────────────────────────────
    print(f"\n\n  [3/3] Python依赖完整性验证\n")
    dep_results = _check_dependencies()
    for pkg, info in dep_results.items():
        icon = "✅" if info["ok"] else ("⚠️" if info.get("optional") else "❌")
        version = info.get("version", "未安装")
        print(f"     {icon} [{pkg}] v{version}")
        report["dependencies"][pkg] = info

    # ── 汇总 ───────────────────────────────────────────────────
    ok_count = sum(1 for s in report["skills"].values() if s["status"] == "ok")
    total = len(report["skills"])
    api_ok = sum(1 for a in report["api"].values() if a.get("ok"))

    print(f"\n  ── 健康报告汇总 ({timestamp}) ──")
    print(f"     Skills: {ok_count}/{total} 正常")
    print(f"     API连通性: {api_ok}/{len(report['api'])} 通过")
    dep_ok = sum(1 for d in report["dependencies"].values() if d["ok"])
    print(f"     Python依赖: {dep_ok}/{len(report['dependencies'])} 已安装")

    # 标记异常模块
    issues = []
    for sid, info in report["skills"].items():
        if info["status"] != "ok":
            issues.append(f"{sid}: {info['status']}")
    for api_name, info in report["api"].items():
        if not info.get("ok"):
            issues.append(f"API[{api_name}]: {info.get('message', '未知错误')}")

    if issues:
        print(f"\n     ⚠️ 异常项 ({len(issues)}):")
        for issue in issues:
            print(f"       - {issue}")
    else:
        print(f"\n     ✅ 所有模块运行正常！")

    # 输出JSON报告
    report_path = TOOLKIT_DIR / "health_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n     📄 详细报告已保存至: {report_path}")

    return report


def _test_api_connectivity() -> Dict[str, Any]:
    """测试免费公开数据源连通性"""
    results = {}

    # 腾讯行情（K线/实时行情/名称检索主源）
    try:
        import requests
        resp = requests.get("https://qt.gtimg.cn/q=sh000001", timeout=10,
                            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
        if resp.status_code == 200 and "~" in resp.content.decode("gbk", errors="ignore"):
            results["qt.gtimg.cn"] = {"ok": True, "message": "腾讯行情连通"}
        else:
            results["qt.gtimg.cn"] = {"ok": False, "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        results["qt.gtimg.cn"] = {"ok": False, "message": str(e)[:80]}

    # 新浪板块行情（板块轮动主源）
    try:
        import requests
        resp = requests.get("http://money.finance.sina.com.cn/q/view/newSinaHy.php",
                            timeout=10, headers={"User-Agent": "Mozilla/5.0",
                                                 "Referer": "https://finance.sina.com.cn/"})
        if resp.status_code == 200 and "bankuai" in resp.content.decode("gbk", errors="ignore"):
            results["sina.bankuai"] = {"ok": True, "message": "新浪板块行情连通"}
        else:
            results["sina.bankuai"] = {"ok": False, "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        results["sina.bankuai"] = {"ok": False, "message": str(e)[:80]}

    # 东方财富数据中心（估值/财务/龙虎榜等报表）
    try:
        import requests
        resp = requests.get("https://datacenter-web.eastmoney.com/api/data/v1/get", timeout=10, params={
            "reportName": "RPT_VALUEANALYSIS_DET", "columns": "ALL",
            "filter": '(SECURITY_CODE="600519")', "pageNumber": "1", "pageSize": "1",
            "source": "WEB", "client": "PC",
        }, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://data.eastmoney.com/",
        })
        payload = resp.json() if resp.status_code == 200 else {}
        if (payload.get("result") or {}).get("data"):
            results["eastmoney.datacenter"] = {"ok": True, "message": "东财数据中心连通"}
        else:
            results["eastmoney.datacenter"] = {"ok": False, "message": f"HTTP {resp.status_code} 或无数据"}
    except Exception as e:
        results["eastmoney.datacenter"] = {"ok": False, "message": str(e)[:80]}

    return results


def _check_dependencies() -> Dict[str, Any]:
    """检查Python依赖"""
    results = {}
    all_packages = REQUIRED_PACKAGES + OPTIONAL_PACKAGES

    for pkg in all_packages:
        try:
            mod = importlib.import_module(pkg)
            version = getattr(mod, "__version__", "unknown")
            results[pkg] = {"ok": True, "version": version, "optional": pkg in OPTIONAL_PACKAGES}
        except ImportError:
            results[pkg] = {"ok": False, "version": None, "optional": pkg in OPTIONAL_PACKAGES}

    return results


# ============================================================================
# 5. 使用指南生成器 (Usage Guide)
# ============================================================================

def cmd_guide(skill_id_or_query: str) -> None:
    """根据Skill ID或用户问题生成使用指南"""
    print_header("使用指南")

    # 尝试直接匹配Skill ID
    if skill_id_or_query in SKILLS_METADATA:
        _generate_skill_guide(skill_id_or_query)
    else:
        # 智能路由找到最相关的Skills
        route_result = _smart_route(skill_id_or_query)
        if route_result["type"] == "composite":
            print(f"  问题: \"{skill_id_or_query}\"")
            print(f"  匹配模板: {route_result['name']} ({route_result.get('description', '')})\n")
            for sid in route_result["skills"]:
                _generate_skill_guide(sid)
        elif route_result["type"] == "single":
            _generate_skill_guide(route_result["skill"])
        else:
            print(f"  ⚠️ 无法匹配到相关模块，请尝试:")
            print(f"     python toolkit.py guide <Skill名称>")
            print(f"\n  可用Skills:")
            for sid in SKILLS_METADATA:
                meta = SKILLS_METADATA[sid]
                print(f"     {sid}: {meta['name_cn']}")


def _generate_skill_guide(skill_id: str) -> None:
    """生成单个Skill的使用指南"""
    meta = SKILLS_METADATA[skill_id]
    sp = script_path(skill_id)

    print(f"\n  ── [{skill_id}] {meta['name_cn']} ──")
    print(f"  描述: {meta['description']}")
    print(f"  适用场景: {' | '.join(meta['scenarios'])}")

    if sp:
        # CLI调用方式
        cli_examples = _get_cli_examples(skill_id)
        print(f"\n  📌 命令行调用:")
        for ex in cli_examples:
            print(f"     $ {ex}")

        # Python API导入方式
        module_name = Path(sp.stem).name.replace("-", "_")
        print(f"\n  🐍 Python API导入:")
        print(f'     import sys')
        print(f'     sys.path.insert(0, "{sp.parent}")')
        print(f'     from {module_name} import *')

    # 参数说明
    params = _get_param_docs(skill_id)
    if params:
        print(f"\n  📋 主要参数:")
        for pname, pdesc in params.items():
            print(f"     --{pname}: {pdesc}")


def _get_cli_examples(skill_id: str) -> List[str]:
    """获取CLI调用示例"""
    meta = SKILLS_METADATA.get(skill_id, {})
    script_name = meta.get("script", f"{skill_id}.py")
    examples = {
        "tech-indicators": [
            'python tech_indicators.py "600519"',
            'python tech_indicators.py "贵州茅台" --period 近半年'
        ],
        "kline-patterns": [
            'python kline_patterns.py "600519"',
            'python kline_patterns.py "贵州茅台"'
        ],
        "multi-factor": [
            'python multi_factor.py --stocks "沪深300成分股" --factors value,growth',
            'python multi_factor.py --stocks "创业板" --weight custom:PE:0.4,PB:0.3,ROE:0.3'
        ],
        "ml-stock-picker": [
            'python ml_stock_picker.py train --days 250',
            'python ml_stock_picker.py predict'
        ],
        "market-sentiment": [
            'python market_sentiment.py --report',
            'python market_sentiment.py --detail'
        ],
        "sector-rotation": [
            'python sector_rotation.py overview',
            'python sector_rotation.py strength',
            'python sector_rotation.py signals'
        ],
        "dragon-list": [
            'python dragon_list.py today',
            'python dragon_list.py strategy'
        ],
        "multi-strategy": [
            'python multi_strategy.py trend-following',
            'python multi_strategy.py mean-reversion',
            'python multi_strategy.py dragon-head'
        ],
        "nlp-analyzer": [
            'python nlp_analyzer.py "帮我看看贵州茅台怎么样"',
            'python nlp_analyzer.py --chat'
        ],
    }
    return examples.get(skill_id, [f'python {script_name} <参数>'])


def _get_param_docs(skill_id: str) -> Dict[str, str]:
    """获取参数文档"""
    params = {
        "tech-indicators": {"period": "时间范围(默认近一年)", "indicators": "指定指标(MACD,KDJ,RSI等)"},
        "kline-patterns": {"period": "K线数据时间范围", "min_confidence": "最低置信度阈值"},
        "multi-factor": {"stocks": "股票池(沪深300/创业板等)", "factors": "因子类别(value/growth/quality/momentum/volatility/liquidity)", "weight": "自定义权重"},
        "ml-stock-picker": {"days": "训练数据天数", "model": "模型类型(lightgbm/xgboost)"},
        "market-sentiment": {"report": "生成完整报告", "detail": "显示详细指标"},
        "sector-rotation": {"mode": "模式(overview/flow/signals)", "top_n": "排名数量"},
    }
    return params.get(skill_id, {})


# ============================================================================
# CLI入口
# ============================================================================

def print_usage() -> None:
    """打印帮助信息"""
    print("""
╔══════════════════════════════════════════════════════════╗
║         A股分析统一入口工具包 v2.0                       ║
║         A-Share Analysis Toolkit                         ║
╚══════════════════════════════════════════════════════════╝

用法: python toolkit.py <命令> [参数]

命令:
  overview [关键词]          能力矩阵总览（可选关键词过滤）
  route "自然语言指令"       智能路由 — 自动匹配Skill组合
  quick <快捷命令> [参数]    快捷命令执行
  health                     模块健康检查
  guide <Skill/问题>         使用指南生成器

快捷命令:
  stock-diag [股票代码]      个股诊断（行情+技术+形态+基本面）
  stock-pick                 选股推荐（多因子+情绪+龙虎榜）
  market-review              市场复盘（大盘+板块+情绪+异动）
  strategy-scan              策略扫描（多策略信号排名）

示例:
  python toolkit.py overview                    # 查看所有Skills
  python toolkit.py overview MACD               # 搜索MACD相关模块
  python toolkit.py route "贵州茅台最新价"       # 智能路由-单模块
  python toolkit.py route "帮我看看宁德时代怎么样" # 智能路由-多模块串联
  python toolkit.py quick stock-diag 600519     # 个股诊断
  python toolkit.py health                      # 健康检查
  python toolkit.py guide tech-indicators       # 查看tech-indicators使用指南

已集成Skills (12个):
""")
    for cat_name, cat_info in CATEGORIES.items():
        skills_str = ", ".join(cat_info["skills"])
        print(f"  [{cat_name}] {skills_str}")


def main() -> None:
    """CLI主入口"""
    if len(sys.argv) < 2:
        print_usage()
        return

    command = sys.argv[1].lower()

    if command == "overview":
        query = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_overview(query)

    elif command == "route":
        if len(sys.argv) < 3:
            print("  ❌ 请输入自然语言指令")
            print('  示例: python toolkit.py route "贵州茅台最新价"')
            return
        user_input = " ".join(sys.argv[2:])
        cmd_route(user_input)

    elif command == "quick":
        if len(sys.argv) < 3:
            print("  ❌ 请指定快捷命令")
            for qid, qc in QUICK_COMMANDS.items():
                arg_info = f" [{qc['arg_hint']}]" if qc["requires_arg"] else ""
                print(f"     {qid}: {qc['name_cn']}{arg_info}")
            return
        cmd_id = sys.argv[2]
        arg = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_quick(cmd_id, arg)

    elif command == "health":
        cmd_health()

    elif command == "guide":
        if len(sys.argv) < 3:
            print("  ❌ 请指定Skill名称或输入问题")
            print('  示例: python toolkit.py guide tech-indicators')
            return
        query = " ".join(sys.argv[2:])
        cmd_guide(query)

    elif command in ("help", "-h", "--help"):
        print_usage()

    else:
        print(f"  ❌ 未知命令: {command}")
        print("\n  可用命令: overview, route, quick, health, guide")
        print("  输入 'python toolkit.py help' 查看完整帮助\n")


if __name__ == "__main__":
    main()
