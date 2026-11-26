"""Agent核心 - LLM驱动的多轮工具调用引擎"""
import asyncio
import json
import re
import uuid
import traceback
import logging
from typing import Optional, AsyncGenerator
from app.core.llm_service import llm_config, llm_client
from app.core.skill_orchestrator import orchestrator
from app.core.prompts import SYSTEM_PROMPT_REPORT

log = logging.getLogger(__name__)

# Agent系统提示词（工具选择阶段：决定是否需要调用工具）
SYSTEM_PROMPT_TOOL = """你是一个专业的A股市场分析Agent,拥有实时数据获取能力。

## 核心原则(最高优先级)
- **凡是涉及市场数据的查询，必须调用工具获取真实数据**，不要凭记忆回答！
- 只有纯闲聊、打招呼、感谢等不需要数据的对话才直接回复。

## 工具调用规则
1. **大盘/指数问题** -> 只调用 `get_market_sentiment`(包含上证/深证/创业板等所有指数点位、涨跌幅、成交额)。不要对"上证指数""沪深300"等指数调用个股诊断工具!
2. **个股问题** -> 调用 `get_stock_diagnosis(code="6位代码")`,参数必须是6位数字股票代码。如果用户只说了股票名称(如"贵州茅台"),你需要知道其代码(600519)再调用。
3. **板块/行业问题** -> 调用 `get_sector_analysis(sector_type="industry"/"concept")`
4. **选股需求** -> 调用 `smart_stock_pick` 或 `ml_stock_prediction`
5. **资金流向** -> 个股用 `get_stock_fund_flow(code)`,板块用 `get_sector_fund_flow()`,全市场用 `get_main_fund_flow()`
6. **新闻/资讯** -> 个股用 `get_stock_news(code)`,宏观用 `get_cls_news()`
7. **复盘总结** -> 调用 `get_daily_report(style="detailed")`
8. **板块轮动/切换** -> 调用 `get_sector_rotation_signals`
9. **龙虎榜/游资** -> 调用 `get_dragon_list(date=可选)`
10. **低吸蓝筹** -> 调用 `get_low_absorption_picks(top_n=可选)`
11. **热门股票排行** -> 调用 `get_hot_rank(top_n=可选)`
12. **盘中异动** -> 调用 `get_stock_changes()`
13. **热门关键词/概念** -> 调用 `get_hot_keywords()`

## 常见错误避免
- 不要对"上证指数""大盘"等指数问题调用 `get_stock_diagnosis`(该工具只支持个股6位代码)
- 不要编造股票代码或数据
- 复杂问题可以组合多个工具,如"贵州茅台怎么样"-> `get_stock_diagnosis("600519")` + `get_stock_fund_flow("600519")`
- 问"今天哪些股票异动了" -> `get_stock_changes()`,不要调用 `get_stock_diagnosis`
- 问"龙虎榜数据" -> `get_dragon_list()`,不要调用 `get_stock_diagnosis`

## 语言要求(最高优先级)
- **回答以中文为主**，专业术语可使用通用英文缩写（如MACD、RSI、PE等），股票代码保持数字格式"""


# Agent系统提示词（普通对话：不需要调用工具时的回复风格）
SYSTEM_PROMPT_CHAT = """你是一个专业的A股市场分析助手,语气自然亲切,像朋友一样交流。

## 回复原则
- **简洁自然**: 不要每次都输出固定模板。根据问题灵活调整回答长度和格式。
- **打招呼/闲聊**: 简短友好地回应，介绍自己能做什么即可，不需要"核心结论""风险提示"等正式结构。
- **知识问答**: 直接给出答案，用 Markdown 加粗、列表让内容清晰易读。
- **需要数据的问题**: 引导用户输入具体股票代码或说明查询方向。
- **适当使用 Emoji** 增加亲和力,但不要过度堆砌。

## 语言要求(最高优先级)
- **回答以中文为主**，专业术语可使用通用英文缩写（如MACD、RSI、PE等），股票代码保持数字格式"""


# Agent系统提示词（通用分析报告：调用工具后根据场景自适应生成报告）
SYSTEM_PROMPT_ANALYSIS = """你是一个专业的A股市场分析师，请根据用户问题和已获取的数据，撰写针对性的分析报告。

## 输出规则(最高优先级)
- **禁止输出任何思考过程**,直接输出最终结果
- **回答以中文为主**，专业术语可使用通用英文缩写（如MACD、RSI、PE等），股票代码保持数字格式
- **所有数值必须使用阿拉伯数字**:涨跌幅用"-3.03%",金额用"3575.5亿元",评分用"30分"
- 数据精度:百分比保留两位小数,金额保留一位小数

## 格式要求
- **使用Markdown表格**展示关键数据对比
- **使用emoji图标**增强可读性：📈📉🔥💧🎯⚠️💰📊🔍✅❌🚀🛡️📰🔥💡等
- **关键数据加粗**，重要结论用引用块(>)包裹
- **使用分隔线(---)分隔章节**

## 重要：数据真实性原则
- **绝对不能编造任何数据**
- 如果数据不存在，直接说明"数据暂不可用"

## 报告结构（根据用户问题类型自适应）

### 场景A：个股分析（用户问某只股票）
适用工具：`get_stock_diagnosis`, `get_stock_fund_flow`, `get_stock_news`, `get_stock_changes`
标题格式：`## 🔍 {股票名称}({代码}) 个股诊断报告`

| 指标 | 数值 | 信号 |
|------|------|------|
| 最新价 | XX.XX元 | 📈/📉 |
| 涨跌幅 | ±X.XX% | 🔥/💀 |
| 成交额 | XX亿元 | 💰 |
| 换手率 | X.XX% | 📊 |
| 市盈率 | XX倍 | ⚠️ |

**核心结论**：[1-2句话总结]
**操作建议**：[买入/持有/观望/减仓]

---

### 场景B：板块分析（用户问某个行业/板块）
适用工具：`get_sector_analysis`, `get_sector_fund_flow`, `get_sector_rotation_signals`
标题格式：`## 🏭 {板块名称} 板块分析报告`

| 指标 | 数值 | 排名 |
|------|------|------|
| 板块涨跌幅 | ±X.XX% | TOP X |
| 资金净流入 | XX亿 | 📊 |
| 领涨个股 | XXX | 🚀 |

---

### 场景C：市场情绪（用户问大盘/市场）
适用工具：`get_market_sentiment`, `get_main_fund_flow`
标题格式：`## 📊 A股市场情绪分析`

| 指标 | 数值 | 信号 |
|------|------|------|
| 上证指数 | XXXX.XX | 📈/📉 |
| 涨跌家数 | XXX/XXX | 📉/📈 |
| 涨停/跌停 | XX/XX | 🔥/💀 |
| 情绪评分 | XX分 | ⚠️ |

---

### 场景D：选股/推荐（用户问买什么）
适用工具：`smart_stock_pick`, `ml_stock_prediction`, `get_low_absorption_picks`
标题格式：`## ⭐ 智能选股分析`

| 排名 | 代码 | 名称 | 涨跌幅 | 评分 | 理由 |
|------|------|------|--------|------|------|

---

### 场景E：复盘总结（用户问今日行情）
适用工具：`get_daily_report`
标题格式：`## 📋 {日期} 市场复盘`

（使用完整的复盘报告模板：市场概览→情绪周期→板块题材→个股辨识→资金面→外盘→策略）

---

### 场景F：龙虎榜/资金流（用户问资金动向）
适用工具：`get_dragon_list`, `get_stock_fund_flow`, `get_sector_fund_flow`, `get_main_fund_flow`
标题格式：`## 💰 资金流向分析`

| 个股 | 代码 | 净买额 | 方向 | 信号 |
|------|------|--------|------|------|

---

### 场景G：新闻资讯（用户问新闻/消息）
适用工具：`get_stock_news`, `get_cls_news`
标题格式：`## 📰 资讯速递`

| 时间 | 标题 | 来源 | 影响 |
|------|------|------|------|
| HH:MM | XXXXX | XX | 📈/📉/➡️ |

**核心摘要**：[1-2句话总结重要新闻]
**影响分析**：[对相关板块/个股的影响]

---

### 场景H：热度排名（用户问热门/人气）
适用工具：`get_hot_rank`, `get_hot_keywords`
标题格式：`## 🔥 热度排行`

| 排名 | 名称 | 热度值 | 涨跌幅 | 讨论焦点 |
|------|------|--------|--------|----------|

**热度解读**：[市场关注焦点分析]

---

### 场景I：板块轮动（用户问轮动/切换）
适用工具：`get_sector_rotation_signals`
标题格式：`## 🔄 板块轮动信号`

| 信号类型 | 板块 | 强度 | 方向 |
|----------|------|------|------|
| 轮动启动 | XXX | ⭐⭐⭐ | 📈 |
| 资金切入 | XXX | ⭐⭐ | 📈 |

**轮动解读**：[资金切换逻辑分析]

---

### 场景J：个股异动（用户问异动/异动）
适用工具：`get_stock_changes`
标题格式：`## ⚡ 个股异动监控`

| 时间 | 代码 | 名称 | 异动类型 | 涨跌幅 |
|------|------|------|----------|--------|
| HH:MM | XXXXXX | XXX | 🚀火箭发射/💀闪崩 | ±X.XX% |

**异动解读**：[异动原因分析]

---

> ⚠️ **风险提示**：以上分析仅供参考，不构成投资建议。市场有风险，投资需谨慎。"""


# Agent系统提示词（数据分析报告：调用工具后生成正式报告）
# SYSTEM_PROMPT_REPORT 已抽离到 app.core.prompts 统一管理，避免与 daily_report_service 重复


class Agent:
    """多轮工具调用的Agent引擎"""

    def __init__(self, max_tool_rounds: int = 3):
        self.max_tool_rounds = max_tool_rounds
        # 多轮上下文：从数据库 ChatMessage 表读取（按 session_id 隔离），重启不丢
        # 最多读取最近 N 轮
        self._max_context_rounds = 6

    def _load_context(self, session_id: int | None) -> list[dict]:
        """从数据库加载历史上下文（按 session_id 隔离，重启不丢）"""
        if session_id is None:
            return []
        try:
            from app.core.database import SessionLocal
            from app.models.chat import ChatMessage
            db = SessionLocal()
            try:
                msgs = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(self._max_context_rounds * 2)
                    .all()
                )
                # 按时间正序组合 user/assistant 对
                context = []
                for m in reversed(msgs):
                    if m.role == "user":
                        context.append({
                            "query": m.content[:200],
                            "summary": "",
                            "tools": [],
                        })
                    elif m.role == "assistant" and context and not context[-1]["summary"]:
                        # 关联到最近一条 user 消息
                        try:
                            tools = json.loads(m.tools_used) if m.tools_used else []
                        except (json.JSONDecodeError, TypeError):
                            tools = []
                        context[-1]["summary"] = m.content[:200] + ("..." if len(m.content) > 200 else "")
                        context[-1]["tools"] = tools
                return context[-self._max_context_rounds:]
            finally:
                db.close()
        except Exception as e:
            log.warning("[Agent] Failed to load context from DB: %s", e)
            return []

    def _build_context_prompt(self, session_id: int | None = None) -> str:
        """构建历史上下文提示（从 DB 读取，重启不丢）"""
        if session_id is None:
            return ""
        ctx_list = self._load_context(session_id)
        if not ctx_list:
            return ""

        lines = ["## 前几轮对话记录（供参考，保持分析连贯性）"]
        for i, ctx in enumerate(ctx_list, 1):
            if not ctx.get("summary"):
                continue
            lines.append(f"\n### 第{i}轮")
            lines.append(f"- 用户问题：{ctx['query']}")
            if ctx.get("tools"):
                lines.append(f"- 调用工具：{', '.join(ctx['tools'])}")
            lines.append(f"- 分析摘要：{ctx['summary']}")

        return "\n".join(lines) if len(lines) > 1 else ""

    @staticmethod
    def _select_report_prompt(tools_used: list[str], user_query: str = "") -> str:
        """根据调用的工具类型选择合适的报告模板"""
        tools_set = set(tools_used)
        
        # 复盘报告 → 专属模板
        if "get_daily_report" in tools_set:
            return SYSTEM_PROMPT_REPORT
        
        # 以下所有工具 → 通用分析模板（场景A-J自适应）
        # 个股类：get_stock_diagnosis, get_stock_fund_flow, get_stock_news, get_stock_changes
        # 板块类：get_sector_analysis, get_sector_fund_flow, get_sector_rotation_signals
        # 选股类：smart_stock_pick, ml_stock_prediction, get_low_absorption_picks
        # 资金类：get_dragon_list, get_main_fund_flow
        # 情绪类：get_market_sentiment
        # 热度类：get_hot_rank, get_hot_keywords
        # 新闻类：get_cls_news
        
        return SYSTEM_PROMPT_ANALYSIS

    async def run(self, messages: list[dict], session_id: int | None = None) -> dict:
        """
        执行Agent对话，支持多轮工具调用。
        
        Returns: {content, tools_used, reasoning_steps}
        """
        if not llm_config.enabled:
            return {
                "error": "LLM服务未启用",
                "config": llm_config.to_dict()
            }

        try:
            # 构建完整对话历史(注入工具选择阶段的system prompt)
            full_messages = [{"role": "system", "content": SYSTEM_PROMPT_TOOL}] + messages.copy()
            
            tools = orchestrator.get_tools()
            all_tools_used = []
            reasoning_steps = []
            tool_data_collected = {}

            # 多轮工具调用循环 - 只负责收集数据
            for round_num in range(self.max_tool_rounds):
                log.info("[Agent] Round %d: calling LLM with tools...", round_num + 1)
                response = await llm_client.chat_completion(full_messages, tools=tools)
                log.info("[Agent] Response: tool_calls=%s, content_len=%d",
                         bool(response.get('tool_calls')), len(response.get('content', '')))

                if not response.get("tool_calls"):
                    # 如果已经收集了工具数据,基于数据生成报告;否则用对话风格回复
                    if tool_data_collected:
                        content = await self._generate_final_report(
                            messages, all_tools_used, tool_data_collected
                        )
                        return {
                            "content": content,
                            "tools_used": all_tools_used,
                            "reasoning_steps": reasoning_steps
                        }

                    chat_messages = [{"role": "system", "content": SYSTEM_PROMPT_CHAT}] + messages.copy()
                    final_resp = await llm_client.chat_completion(chat_messages, tools=None)
                    content = self._clean_xml_tags(final_resp.get("content", ""))
                    return {
                        "content": content,
                        "tools_used": all_tools_used,
                        "reasoning_steps": reasoning_steps
                    }

                # 有工具调用,记录并执行
                tool_call_names = [tc["function"]["name"] for tc in response["tool_calls"]]
                all_tools_used.extend(tool_call_names)
                
                reasoning_steps.append({
                    "round": round_num + 1,
                    "tools_called": tool_call_names,
                    "model_thought": response.get("content", "")[:200] or "准备调用工具获取数据"
                })

                # 构建assistant消息(包含tool_calls)
                assistant_msg = {
                    "role": "assistant",
                    "content": response.get("content", ""),
                    "tool_calls": response["tool_calls"]
                }
                full_messages.append(assistant_msg)

                # 执行所有工具调用,收集数据
                for tc in response["tool_calls"]:
                    func_name = tc["function"]["name"]
                    log.info("[Agent] Executing tool: %s", func_name)
                    try:
                        func_args = json.loads(tc["function"].get("arguments", "{}"))
                    except json.JSONDecodeError:
                        func_args = {}

                    result_text = await orchestrator.execute_tool_async(
                        func_name, timeout=45, **func_args
                    )

                    # 保存工具数据用于最终报告生成
                    tool_data_collected[func_name] = {
                        "args": func_args,
                        "result": self._truncate(result_text, max_len=5000)
                    }

                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                        "content": tool_data_collected[func_name]["result"]
                    })

            # 工具调用阶段结束,基于收集的数据生成最终分析报告
            log.info("[Agent] Generating final report with %d tools data...", len(tool_data_collected))
            content = await self._generate_final_report(
                messages, all_tools_used, tool_data_collected
            )

            return {
                "content": content,
                "tools_used": all_tools_used,
                "reasoning_steps": reasoning_steps
            }
        except Exception as e:
            log.error("[Agent] Error: %s", e, exc_info=True)
            return {
                "error": f"分析出错: {str(e)}",
                "content": f"分析过程中出现错误:{str(e)}\n\n请检查 LM Studio 是否正常运行,或稍后重试。"
            }

    def _build_report_messages(
        self, user_query: str, tools_used: list[str], tool_data: dict, session_id: int | None = None
    ) -> list[dict]:
        """构建报告生成 prompt messages（run 和 run_stream 共用）"""
        data_summary_parts = []
        for tool_name, data in tool_data.items():
            args_str = ", ".join(f"{k}={v}" for k, v in data["args"].items()) if data["args"] else ""
            result_preview = data["result"][:2000]
            data_summary_parts.append(
                f"【{tool_name}({args_str})】\n{result_preview}"
            )
        data_context = "\n\n".join(data_summary_parts)

        context_prompt = self._build_context_prompt(session_id)
        context_section = f"\n\n{context_prompt}\n" if context_prompt else ""

        report_prompt = {
            "role": "user",
            "content": f"""我已获取以下市场数据,请基于这些数据撰写专业分析报告:
{context_section}
## 用户问题
{user_query}

## 已获取的数据
{data_context}

## 要求
1. **必须100%使用中文**,不允许出现任何英文单词（股票代码除外）
2. **所有数值必须使用阿拉伯数字**:涨跌幅用"-3.03%"而非"跌三点零三",金额用"3575.5亿元",评分用"95分",家数用"790只"
3. 采用机构研报风格,数据精确到小数点后两位(百分比)或一位(金额)
4. 先给出核心结论(1-2句话),用 Markdown 表格展示关键数据,然后分析与建议
5. **如果是追问（有历史记录），请在分析中体现与前几轮的关联和对比**"""
        }
        report_system_prompt = self._select_report_prompt(tools_used, user_query)
        return [
            {"role": "system", "content": report_system_prompt},
            report_prompt,
        ]

    async def _generate_final_report(self, original_messages, tools_used, tool_data):
        """基于工具数据生成最终分析报告"""
        # 防御性获取用户查询，处理越界和缺失content字段的情况
        user_query = ""
        if original_messages:
            last_msg = original_messages[-1]
            if isinstance(last_msg, dict):
                user_query = last_msg.get("content", "") or ""
        
        # 构造一个明确的报告生成请求,将工具数据作为上下文传入
        data_summary_parts = []
        for tool_name, data in tool_data.items():
            args_str = ", ".join(f"{k}={v}" for k, v in data["args"].items()) if data["args"] else ""
            result_preview = data["result"][:3000]  # 增加预览长度,保留更多数据
            data_summary_parts.append(
                f"【{tool_name}({args_str})】\n{result_preview}"
            )
        
        data_context = "\n\n".join(data_summary_parts)

        report_prompt = {
            "role": "user",
            "content": f"""我已获取以下市场数据,请基于这些数据撰写专业分析报告:
## 用户问题
{user_query}

## 已获取的数据
{data_context}

## 要求
1. **必须100%使用中文**,不允许出现任何英文单词（股票代码除外）
2. **所有数值必须使用阿拉伯数字**:涨跌幅用"-3.03%"而非"跌三点零三",金额用"3575.5亿元"而非"三千五百七十五点五亿",评分用"95分",家数用"790只"
3. 所有金融术语翻译成中文：bullish→看涨,bearish→看跌,support→支撑位,resistance→阻力位,volume→成交量,breakout→突破,rebound→反弹,correction→回调,momentum→动能,trend→趋势
4. 采用机构研报风格,数据描述精确到小数点后两位(百分比)或一位(金额)
5. 先给出核心结论(1-2句话),用 Markdown 表格展示关键数据,然后分析与建议
6. 不要使用任何XML标签或代码块,直接输出纯文本分析
7. **如果是追问（有历史记录），请在分析中体现与前几轮的关联和对比**"""
        }

        # 用独立的对话让LLM基于数据写报告(不传tools)
        report_system_prompt = self._select_report_prompt(tools_used, user_query)
        report_messages = [
            {"role": "system", "content": report_system_prompt},
            report_prompt
        ]

        try:
            final_resp = await llm_client.chat_completion(report_messages, tools=None)
            content = self._clean_xml_tags(final_resp.get("content", ""))
            
            # 如果仍然返回空或纯XML,使用工具数据直接构造结构化摘要
            if not content.strip() or len(content.strip()) < 20:
                content = self._build_structured_summary(user_query, tools_used, tool_data)
        except Exception as e:
            content = self._build_structured_summary(user_query, tools_used, tool_data)

        # 上下文持久化由 chat.py 在保存消息到 ChatMessage 时自动处理，无需额外保存
        return content

    def _build_structured_summary(self, user_query, tools_used, tool_data):
        """基于工具数据直接构造结构化摘要(LLM失败时的回退方案)"""
        lines = []
        lines.append(f"## {user_query} 分析报告\n")
        
        for tool_name in set(tools_used):
            if tool_name not in tool_data:
                continue
            data = tool_data[tool_name]
            args_str = ", ".join(f"{k}={v}" for k, v in data["args"].items()) if data["args"] else ""
            
            # 提取关键数据行(取前10行有意义的)
            result_lines = [l.strip() for l in data["result"].split("\n") 
                          if l.strip() and not l.startswith("+") and not l.startswith("|")]
            
            lines.append(f"\n### {self._tool_display_name(tool_name)}({args_str})")
            for line in result_lines[:12]:
                lines.append(f"- {line}")

        lines.append("\n> 以上分析基于实时市场数据,仅供参考,不构成投资建议。")
        
        return "\n".join(lines)

    @staticmethod
    def _tool_display_name(name):
        """工具名称的中文显示"""
        names = {
            "get_market_sentiment": "📊 市场情绪",
            "get_stock_diagnosis": "🔍 个股诊断",
            "get_sector_analysis": "🏭 板块分析",
            "get_sector_rotation_signals": "🔄 板块轮动信号",
            "smart_stock_pick": "⭐ 智能选股",
            "ml_stock_prediction": "🤖 ML预测",
            "get_dragon_list": "🐉 龙虎榜",
            "get_low_absorption_picks": "💎 低吸蓝筹",
            "get_daily_report": "📋 每日复盘",
            "get_stock_fund_flow": "💰 个股资金流",
            "get_hot_rank": "🔥 热门排行",
            "get_sector_fund_flow": "💰 板块资金流",
            "get_main_fund_flow": "💰 全市场资金流",
            "get_stock_news": "📰 个股资讯",
            "get_cls_news": "📰 宏观资讯",
            "get_stock_changes": "⚡ 盘中异动",
            "get_hot_keywords": "🔑 热门关键词",
        }
        return names.get(name, name)

    async def run_stream(self, messages: list[dict], session_id: int | None = None) -> AsyncGenerator[str, None]:
        """流式执行Agent(先输出工具调用过程,再流式输出最终回答)
        Yields JSON strings for sse-starlette EventSourceResponse compatibility.
        """
        def _ev(event_type: str, **kwargs) -> str:
            """构造SSE事件JSON字符串"""
            return json.dumps({"type": event_type, **kwargs}, ensure_ascii=False)

        if not llm_config.enabled:
            yield _ev("error", content="LLM服务未启用")
            return

        try:
            full_messages = [{"role": "system", "content": SYSTEM_PROMPT_TOOL}] + messages.copy()
            tools = orchestrator.get_tools()
            all_tools_used = []
            tool_data_collected = {}

            for round_num in range(self.max_tool_rounds):
                log.info("[Agent-Stream] Round %d: calling LLM...", round_num + 1)
                response = await llm_client.chat_completion(full_messages, tools=tools)
                log.info("[Agent-Stream] Response: tool_calls=%s", bool(response.get('tool_calls')))

                if not response.get("tool_calls"):
                    # 如果已经收集了工具数据,基于数据生成报告;否则用对话风格回复
                    if tool_data_collected:
                        user_query = ""
                        if messages:
                            last_msg = messages[-1]
                            if isinstance(last_msg, dict):
                                user_query = last_msg.get("content", "") or ""

                        data_summary_parts = []
                        for tn, td in tool_data_collected.items():
                            args_str = ", ".join(f"{k}={v}" for k, v in td["args"].items()) if td["args"] else ""
                            data_summary_parts.append(f"【{tn}({args_str})】\n{td['result'][:2000]}")
                        data_context = "\n\n".join(data_summary_parts)

                        # 获取历史上下文
                        context_prompt = self._build_context_prompt(session_id)
                        context_section = f"\n\n{context_prompt}\n" if context_prompt else ""

                        report_prompt = {
                            "role": "user",
                            "content": f"""我已获取以下市场数据,请基于这些数据撰写专业分析报告:
{context_section}
## 用户问题
{user_query}

## 已获取的数据
{data_context}

## 要求
1. **必须100%使用中文**,不允许出现任何英文单词（股票代码除外）
2. **所有数值必须使用阿拉伯数字**:涨跌幅用"-3.03%"而非"跌三点零三",金额用"3575.5亿元",评分用"95分",家数用"790只"
3. 采用机构研报风格,数据精确到小数点后两位(百分比)或一位(金额)
4. 先给出核心结论(1-2句话),用 Markdown 表格展示关键数据,然后分析与建议
5. **如果是追问（有历史记录），请在分析中体现与前几轮的关联和对比**"""
                        }

                        report_system_prompt = self._select_report_prompt(all_tools_used, user_query)
                        report_messages = [
                            {"role": "system", "content": report_system_prompt},
                            report_prompt
                        ]

                        yield _ev("final_start")
                        raw_buffer = ""
                        try:
                            async for chunk in llm_client.stream_chat_completion(report_messages):
                                if chunk.startswith('{'):
                                    continue
                                raw_buffer += chunk
                                yield _ev("final_chunk", content=chunk)
                        except Exception as err:
                            log.error("[Agent-Stream] Report streaming failed: %s", err)

                        full_content = self._clean_xml_tags(raw_buffer) if raw_buffer else ""
                        if not full_content.strip() or len(full_content.strip()) < 20:
                            full_content = self._build_structured_summary(user_query, all_tools_used, tool_data_collected)
                            yield _ev("final_chunk", content=full_content)

                        # 上下文由 chat.py 在保存消息时自动持久化
                        yield _ev("final_end")
                        return

                    chat_messages = [{"role": "system", "content": SYSTEM_PROMPT_CHAT}] + messages.copy()
                    yield _ev("final_start")
                    try:
                        raw_buffer = ""

                        async for chunk in llm_client.stream_chat_completion(chat_messages):
                            if chunk.startswith('{'):
                                continue
                            raw_buffer += chunk
                            yield _ev("final_chunk", content=chunk)

                        full_content = self._clean_xml_tags(raw_buffer) if raw_buffer else ""
                        if not full_content.strip() or len(full_content.strip()) < 20:
                            fallback = self._clean_xml_tags(response.get("content", "")) or "分析完成。"
                            yield _ev("final_chunk", content=fallback)
                    except Exception as err:
                        log.error("[Agent-Stream] Streaming failed, fallback: %s", err)
                        content = self._clean_xml_tags(response.get("content", "")) or "分析完成。"
                        yield _ev("final_chunk", content=content)
                    finally:
                        yield _ev("final_end")
                    return

                # 有工具调用,输出思考过程
                tool_call_names = [tc["function"]["name"] for tc in response["tool_calls"]]
                all_tools_used.extend(tool_call_names)

                thought_text = response.get("content", "") or ""
                yield _ev("thinking", round=round_num + 1, tools=tool_call_names, thought=thought_text[:200])

                # 构建assistant消息
                assistant_msg = {
                    "role": "assistant",
                    "content": response.get("content", ""),
                    "tool_calls": response["tool_calls"]
                }
                full_messages.append(assistant_msg)

                # 执行工具调用,输出进度
                for tc in response["tool_calls"]:
                    func_name = tc["function"]["name"]
                    yield _ev("tool_running", tool=func_name)
                    log.info("[Agent-Stream] Executing tool: %s", func_name)

                    try:
                        func_args = json.loads(tc["function"].get("arguments", "{}"))
                    except json.JSONDecodeError:
                        func_args = {}

                    result_text = await orchestrator.execute_tool_async(
                        func_name, timeout=45, **func_args
                    )

                    tool_data_collected[func_name] = {
                        "args": func_args,
                        "result": self._truncate(result_text, max_len=5000)
                    }

                    yield _ev("tool_result", tool=func_name, content=self._truncate(result_text, max_len=2000))

                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                        "content": tool_data_collected[func_name]["result"]
                    })

            # 最终流式输出 - 基于收集的数据生成报告
            user_query = ""
            if messages:
                last_msg = messages[-1]
                if isinstance(last_msg, dict):
                    user_query = last_msg.get("content", "") or ""

            data_summary_parts = []
            for tool_name, data in tool_data_collected.items():
                args_str = ", ".join(f"{k}={v}" for k, v in data["args"].items()) if data["args"] else ""
                result_preview = data["result"][:2000]
                data_summary_parts.append(
                    f"【{tool_name}({args_str})】\n{result_preview}"
                )

            data_context = "\n\n".join(data_summary_parts)

            # 获取历史上下文
            context_prompt = self._build_context_prompt(session_id)
            context_section = f"\n\n{context_prompt}\n" if context_prompt else ""

            report_prompt = {
                "role": "user",
                "content": f"""我已获取以下市场数据,请基于这些数据撰写专业分析报告:
{context_section}
## 用户问题
{user_query}

## 已获取的数据
{data_context}

## 要求
1. **必须100%使用中文**,不允许出现任何英文单词（股票代码除外）
2. **所有数值必须使用阿拉伯数字**:涨跌幅用"-3.03%"而非"跌三点零三",金额用"3575.5亿元",评分用"95分",家数用"790只"
3. 采用机构研报风格,数据精确到小数点后两位(百分比)或一位(金额)
4. 先给出核心结论(1-2句话),用 Markdown 表格展示关键数据,然后分析与建议
5. **如果是追问（有历史记录），请在分析中体现与前几轮的关联和对比**"""
            }

            report_system_prompt = self._select_report_prompt(all_tools_used, user_query)
            report_messages = [
                {"role": "system", "content": report_system_prompt},
                report_prompt
            ]

            log.info("[Agent-Stream] Generating final report (streaming)... data_context_len=%d", len(data_context))
            yield _ev("final_start")

            # 真流式：每个 LLM chunk 立即 yield 给前端（前端负责清理思维链）
            full_content = ""
            try:
                raw_buffer = ""
                chunk_count = 0
                async for chunk in llm_client.stream_chat_completion(report_messages):
                    if chunk.startswith('{'):
                        continue
                    raw_buffer += chunk
                    chunk_count += 1
                    # 立即 yield 原始 chunk 给前端（不等攒完）
                    yield _ev("final_chunk", content=chunk)

                # 收尾时统一清理一次（用于 chat.py 保存到数据库的最终内容）
                full_content = self._clean_xml_tags(raw_buffer) if raw_buffer else ""
                log.info("[Agent-Stream] Final report done, chunks=%d, raw_len=%d, clean_len=%d",
                         chunk_count, len(raw_buffer), len(full_content))

            except Exception as fb_err:
                log.error("[Agent-Stream] Streaming report failed: %s", fb_err)
                full_content = ""

            # 如果流式输出为空或过短,使用结构化摘要回退
            if not full_content.strip() or len(full_content.strip()) < 20:
                try:
                    fallback = self._build_structured_summary(user_query, all_tools_used, tool_data_collected)
                    log.info("[Agent-Stream] Using structured summary fallback, len=%d", len(fallback))
                    yield _ev("final_chunk", content=fallback)
                except Exception as last_err:
                    log.error("[Agent-Stream] Structured summary also failed: %s", last_err)
                    yield _ev("error", content="报告生成失败,请重试。")

            yield _ev("final_end")

        except Exception as e:
            log.error("[Agent-Stream] Error: %s", e, exc_info=True)
            yield _ev("error", content=f"分析出错: {str(e)}\n请检查 LM Studio 是否正常运行。")

    @staticmethod
    def _truncate(text: str, max_len: int = 3000) -> str:
        """截断过长文本"""
        if len(text) <= max_len:
            return text
        return text[:max_len] + f"\n\n... [内容已截断,共{len(text)}字符]"

    @staticmethod
    def _clean_xml_tags(text: str) -> str:
        """清理XML-style function calling残留标签和思维链内容，只保留最终回答"""
        if not text:
            return ""

        cleaned = text

        # 移除 XML/特殊标签块
        cleaned = re.sub(
            r'\s*<\|function=[^>]*>\s*\n.*?\n\s*</\|function[^>]*>\s*',
            '', cleaned, flags=re.DOTALL
        )
        cleaned = re.sub(r'\s*<function=[^>]*>.*?</function=[^>]*>', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'<\|parameter=[^>]*>[^<]*</\|parameter[^>]*>', '', cleaned)

        # 思维链标签（贪婪匹配，确保跨行完整移除）
        for tag in ['thinking', 'thought', 'reasoning', 'analysis']:
            cleaned = re.sub(
                rf'\s*<{tag}>.*?</{tag}>\s*', '', cleaned, flags=re.DOTALL | re.IGNORECASE
            )

        # 英文思维链块（Thinking Process: ... Final Output / Here's a thinking process: ...）
        cleaned = re.sub(
            r'(?:^|\r?\n)\s*(?:Thinking\s*Process|Thought\s*Process|Here\'?s?\s+(?:a|the)\s+thinking\s+process)[:\s]*\r?\n[\s\S]*?(?=\r?\n(?:##|# |\*\*|📊|🔥|📈|📋|⚠️|---|\d+\.\s)|$)',
            '\n', cleaned, flags=re.IGNORECASE
        )

        # 移除内联 JSON 代码块（LLM 思考时输出的工具调用）
        cleaned = re.sub(r'```(?:json)?\s*\n\[.*?\]\s*\n```\s*', '', cleaned, flags=re.DOTALL)

        # 找到最后一个思维链标记行，只保留其后的内容
        thought_keywords = [
            '识别意图', '设定角色', '确定回复', '遵守约束', '草拟',
            '最终输出', '思考过程', '分析步骤', '不需要调用', '直接生成',
            '检查约束', '输出构建', '草拟回复', '回复结构',
            '决定行动', '选择工具', '构建回复', '修正', 'plan:', 'tool selection',
            'let us proceed', 'call `get_', 'steps:', '步骤:',
            'thinking process', 'thought process', 'analyze the user',
            'determine the intent', 'formulate the response', 'adhere to constraints',
            'drafting the content', 'refining the output', 'final polish',
            'self-correction', 'call to action', "here's a thinking process",
            'understand user role', 'analyze constraints', 'process candidate data',
            'calculate strategy parameters', 'draft content', 'output generation',
            '数据分析：', '回答结构规划', '约束检查', '草稿内容构建',
            '开始生成回复', '现在需要根据返回的数据进行分析',
            '我已经调用了该工具并获取了数据',
        ]

        lines = cleaned.split('\n')
        last_thought_idx = -1
        for i, line in enumerate(lines):
            lower_line = line.lower()
            if any(kw in lower_line for kw in thought_keywords):
                last_thought_idx = i

        if last_thought_idx >= 0:
            remaining = lines[last_thought_idx + 1:]
            cleaned = '\n'.join(remaining).strip()

        # 清理格式
        cleaned = re.sub(r'(#{1,3})\s+(#+)\s+', r'\1 ', cleaned)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        return cleaned


# 全局Agent实例(最多5轮工具调用)
agent = Agent(max_tool_rounds=5)
