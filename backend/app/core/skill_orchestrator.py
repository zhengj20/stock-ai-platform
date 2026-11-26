"""技能编排器 - LLM通过工具调用触发项目分析服务"""
import asyncio
import math
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
# akshare 已替换为直连API，不再使用

from app.core.data_sources import (
    EastMoneySource, EastMoneyDataCenter, EastMoneyZTPool,
    TencentSource, THSNorthboundSource, EastMoneyNewsSource, CNInfoSource
)
import pandas as pd
from app.services.market_service import MarketService
from app.services.stock_service import StockService
from app.services.strategy_service import StrategyService
from app.core.data_utils import sanitize_number

log = logging.getLogger(__name__)


class ToolError(Exception):
    """工具调用结构化错误（向上抛给 Agent 终止流程，避免 LLM 编造数据）"""
    pass


def _row_value(row, df: "pd.DataFrame", *keywords: str, fallback_idx: int = 0):
    """按列名（关键字，模糊匹配中文/英文）取值；都匹配不上时回退到 iloc[fallback_idx]"""
    for kw in keywords:
        for col in df.columns:
            if kw in col or kw.lower() in col.lower():
                return row[col]
    if fallback_idx < len(row):
        return row.iloc[fallback_idx]
    return ""


# 线程池用于执行阻塞的同步技能调用
_executor = ThreadPoolExecutor(max_workers=8)  # 扩容至8，支持更多并发工具调用


class SkillOrchestrator:
    """将项目分析能力封装为LLM可调用的tools"""

    def __init__(self):
        self.market = MarketService()
        self.stock = StockService()
        self.strategy = StrategyService()

    def get_tools(self) -> list[dict]:
        """返回OpenAI格式的工具定义"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_market_sentiment",
                    "description": "获取大盘指数行情和市场情绪数据。包含：上证/深证/创业板/沪深300等指数点位和涨跌幅、涨跌家数统计、涨停跌停数量、全市场成交额、主力资金流向。\n【使用场景】用户询问大盘或指数相关问题，如'今天大盘怎么样''上证指数多少点''市场情绪如何''沪深300走势'\n【注意】这是获取大盘/指数数据的唯一工具，不要对指数调用个股诊断工具！",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "日期 YYYY-MM-DD，不传则为今天"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_stock_diagnosis",
                    "description": "个股全面诊断：实时行情、技术指标（MA/MACD/KDJ/RSI/BOLL）、K线形态识别、资金流向分析、财务数据（PE/PB/ROE/EPS）。\n【使用场景】用户询问具体某只股票，如'贵州茅台怎么样''600519分析''比亚迪走势如何'\n【参数要求】code 必须是6位数字股票代码（如 600519），不支持指数代码！",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "6位数字股票代码，如 600519。必须是具体个股代码，不能是指数！"},
                            "period": {"type": "string", "description": "分析周期：近一月/近三月/近半年/近一年"}
                        },
                        "required": ["code"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_sector_analysis",
                    "description": "板块行情分析：行业/概念板块涨幅排行、资金流向。\n【使用场景】用户询问板块相关问题，如'今天哪个板块涨得好''热门板块有哪些'\n【参数说明】sector_type: industry=行业板块, concept=概念板块",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sector_type": {"type": "string", "enum": ["industry", "concept"], "description": "板块类型：industry=行业板块, concept=概念板块"},
                            "top": {"type": "integer", "description": "显示前N名，默认15"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_sector_rotation_signals",
                    "description": "板块轮动信号：风格方向（大盘/小盘偏好）、周期阶段判断、领涨领跌板块。\n【使用场景】用户询问策略分析问题，如'现在该买什么板块''市场风格如何''板块轮动情况'",
                    "parameters": {"type": "object", "properties": {}, "required": []}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "smart_stock_pick",
                    "description": "多因子智能选股：从全市场5000+只A股中筛选综合评分最高的股票，支持市值、成交额、涨跌幅等条件过滤。\n【使用场景】用户有选股需求，如'推荐几只好股票''帮我选选股''有什么值得买的股票'\n【参数说明】market_cap: large=大盘, mid=中盘, small=小盘；min_amount: 最小成交额(元)；change_range: 涨跌幅区间，如'-0.05~0.05'；exclude_st: 排除ST股",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "top_n": {"type": "integer", "description": "返回前N只，默认10"},
                            "market_cap": {"type": "string", "enum": ["large", "mid", "small"], "description": "市值筛选：large=大盘, mid=中盘, small=小盘"},
                            "min_amount": {"type": "number", "description": "最小成交额（元），过滤低流动性股票"},
                            "change_range": {"type": "string", "description": "涨跌幅区间，如 '-0.05~0.05' 表示 -5%~+5%"},
                            "exclude_st": {"type": "boolean", "description": "排除ST股，默认false"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "ml_stock_prediction",
                    "description": "ML智能选股预测：基于技术指标、量价因子等多维度特征的全市场扫描评分。\n【使用场景】用户询问量化选股，如'AI推荐股票''机器学习选股''模型预测哪些股票会涨'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "top_n": {"type": "integer", "description": "返回前N只，默认10"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_dragon_list",
                    "description": "龙虎榜数据：今日上榜股票、异常波动分析、机构净买入/游资席位。\n【使用场景】用户询问龙虎榜，如'今天龙虎榜''哪些股票上龙虎榜了''机构买了什么股'\n【参数说明】strategy_type: all=全部, institution_buy=机构净买入, hot_money=游资活跃",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "日期 YYYY-MM-DD，不传则为今天"},
                            "strategy_type": {"type": "string", "enum": ["all", "institution_buy", "hot_money"], "description": "策略类型：all=全部, institution_buy=机构净买入, hot_money=游资活跃"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_low_absorption_picks",
                    "description": "低吸蓝筹选股：识别近期超跌、RSI/KDJ处于低位、具备反弹潜力的股票。\n【使用场景】用户询问抄底机会，如'有什么超跌股可以抄底''推荐低吸机会''哪些股票跌多了可能反弹'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "top_n": {"type": "integer", "description": "返回前N只，默认10"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_daily_report",
                    "description": "每日复盘报告：汇总大盘表现、市场情绪评分、涨跌统计、板块分析、资金流向等，生成结构化Markdown日报。\n【使用场景】用户需要全面回顾，如'今天复盘''写个今日总结''市场日报'\n【参数说明】style: concise=简洁, detailed=详细（默认）, professional=专业",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "style": {"type": "string", "enum": ["concise", "detailed", "professional"], "description": "报告风格：concise=简洁, detailed=详细（默认）, professional=专业"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_stock_fund_flow",
                    "description": "个股资金流向：查询指定股票近期主力/大单/中单/小单资金流入流出明细。\n【使用场景】用户询问个股资金面，如'贵州茅台资金流向''600519主力资金'\n【参数要求】code 必须是6位数字股票代码",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "6位数字股票代码，如 600519"},
                            "market": {"type": "string", "enum": ["sh", "sz"], "description": "市场：sh=沪市, sz=深市。不传则自动判断"}
                        },
                        "required": ["code"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_hot_rank",
                    "description": "热门股票排行：东方财富人气榜，反映市场关注度最高的股票。\n【使用场景】用户询问热度分析，如'今天什么股票最热门''市场关注度最高的股''人气股排行'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "top_n": {"type": "integer", "description": "返回前N只，默认15"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_sector_fund_flow",
                    "description": "板块资金流向：行业/概念板块的资金流入流出排名，识别资金聚集方向。\n【使用场景】用户询问板块资金面，如'资金在流入哪些板块''哪个行业资金最多'\n【参数说明】sector_type: industry=行业板块, concept=概念板块",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sector_type": {"type": "string", "enum": ["industry", "concept"], "description": "板块类型：industry=行业板块, concept=概念板块，默认industry"},
                            "top": {"type": "integer", "description": "显示前N名，默认15"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_main_fund_flow",
                    "description": "主力资金排名：全市场个股主力资金净流入/流出排行榜，识别主力动向。\n【使用场景】用户询问主力动向，如'主力资金流入最多的股票''今天主力在买什么''主力资金排行榜'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "top_n": {"type": "integer", "description": "返回前N只，默认15"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_stock_news",
                    "description": "个股新闻：查询指定股票的最新新闻公告，了解公司动态和市场消息。\n【使用场景】用户询问个股资讯，如'贵州茅台最近有什么消息''600519新闻'\n【参数要求】code 必须是6位数字股票代码",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "6位数字股票代码，如 600519"},
                            "top_n": {"type": "integer", "description": "返回前N条，默认10"}
                        },
                        "required": ["code"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_cls_news",
                    "description": "财联社快讯：实时财经要闻、政策动态、市场热点。\n【使用场景】用户询问宏观资讯，如'今天有什么财经新闻''最新消息''市场有什么重要政策'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "top_n": {"type": "integer", "description": "返回前N条，默认15"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_stock_changes",
                    "description": "盘中异动：实时监控大幅波动、涨停跌停、大单异动等盘中信号。\n【使用场景】用户询问实时盯盘，如'现在有什么异动''盘中有哪些大单''哪些股票突然拉升'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "top_n": {"type": "integer", "description": "返回前N条，默认15"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_hot_keywords",
                    "description": "热门关键词/概念：当前市场最热门的题材概念和关联股票，反映短线资金炒作方向。\n【使用场景】用户询问热点追踪，如'今天热门概念是什么''市场在炒什么题材''哪些概念最火'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "top_n": {"type": "integer", "description": "返回前N个关键词，默认15"}
                        },
                        "required": []
                    }
                }
            },
        ]

    def execute_tool(self, tool_name: str, **kwargs) -> str:
        """执行工具调用并返回结果文本（同步，应在线程池中运行）

        关键错误（如数据源完全不可用）会抛出 ToolError，让 Agent 停止基于错误编造数据。
        兜底错误（数据缺失）走 _format_* 的"暂无数据"分支。
        """
        try:
            if tool_name == "get_market_sentiment":
                result = self.market.get_sentiment(kwargs.get("date"))
                return self._format_sentiment(result)

            elif tool_name == "get_stock_diagnosis":
                code = kwargs["code"]
                period = kwargs.get("period", "近一年")
                # 同步上下文，通过 asyncio.run 运行异步方法
                import asyncio as _asyncio
                try:
                    loop = _asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is None:
                    diagnosis = _asyncio.run(self.stock.get_stock_diagnosis(code, period))
                else:
                    # 已在事件循环中，使用 run_in_executor
                    import concurrent.futures as cf
                    with cf.ThreadPoolExecutor(max_workers=1) as ex:
                        future = ex.submit(lambda: _asyncio.new_event_loop().run_until_complete(
                            self.stock.get_stock_diagnosis(code, period)
                        ))
                        diagnosis = future.result()
                raw = diagnosis.get('raw_output', '')
                if not raw:
                    return f"无法获取 {code} 的数据"
                return raw

            elif tool_name == "get_sector_analysis":
                sector_type = kwargs.get("sector_type", "industry")
                top = kwargs.get("top", 15)
                result = self.market.get_sector_overview(sector_type, top)
                return self._format_sector_result(result)

            elif tool_name == "get_sector_rotation_signals":
                result = self.market.get_rotation_signals()
                return self._format_rotation_result(result)

            elif tool_name == "smart_stock_pick":
                top_n = kwargs.get("top_n", 10)
                # 工具声明的参数对齐 StrategyService.get_multi_factor_picks 实际签名
                result = self.strategy.get_multi_factor_picks(
                    top_n=top_n,
                    market_cap=kwargs.get("market_cap"),
                    min_amount=kwargs.get("min_amount"),
                    change_range=kwargs.get("change_range"),
                    exclude_st=kwargs.get("exclude_st", False),
                )
                return self._format_pick_result(result)

            elif tool_name == "ml_stock_prediction":
                top_n = kwargs.get("top_n", 10)
                result = self.strategy.predict_ml_stocks(top_n=top_n)
                return self._format_pick_result(result)

            elif tool_name == "get_dragon_list":
                date = kwargs.get("date")
                strategy_type = kwargs.get("strategy_type", "all")
                if date:
                    result = self.strategy.get_dragon_list_history(date)
                else:
                    result = self.strategy.get_dragon_list_today()
                return self._format_dict_result(result, "龙虎榜数据")

            elif tool_name == "get_low_absorption_picks":
                top_n = kwargs.get("top_n", 10)
                result = self.strategy.get_low_absorption_picks(top_n=top_n)
                return self._format_pick_result(result)

            elif tool_name == "get_daily_report":
                style = kwargs.get("style", "detailed")
                report = self.market.get_daily_report(style=style, fmt='markdown')
                if isinstance(report, dict) and 'report' in report:
                    return report['report']
                return str(report)

            elif tool_name == "get_stock_fund_flow":
                code = kwargs["code"]
                market = kwargs.get("market", "")
                if not market:
                    market = "sh" if code.startswith("6") else "sz"
                return self._get_stock_fund_flow(code, market)

            elif tool_name == "get_hot_rank":
                top_n = kwargs.get("top_n", 15)
                return self._get_hot_rank(top_n)

            elif tool_name == "get_sector_fund_flow":
                sector_type = kwargs.get("sector_type", "industry")
                top = kwargs.get("top", 15)
                return self._get_sector_fund_flow(sector_type, top)

            elif tool_name == "get_main_fund_flow":
                top_n = kwargs.get("top_n", 15)
                return self._get_main_fund_flow(top_n)

            elif tool_name == "get_stock_news":
                code = kwargs["code"]
                top_n = kwargs.get("top_n", 10)
                return self._get_stock_news(code, top_n)

            elif tool_name == "get_cls_news":
                top_n = kwargs.get("top_n", 15)
                return self._get_cls_news(top_n)

            elif tool_name == "get_stock_changes":
                top_n = kwargs.get("top_n", 15)
                return self._get_stock_changes(top_n)

            elif tool_name == "get_hot_keywords":
                top_n = kwargs.get("top_n", 15)
                return self._get_hot_keywords(top_n)

            else:
                raise ToolError(f"未知工具: {tool_name}")

        except ToolError:
            # 已结构化的工具错误，直接向上抛（让 Agent 停止编数据）
            raise
        except KeyError as e:
            # 缺少必需参数
            raise ToolError(f"工具 {tool_name} 缺少必需参数: {e}") from e
        except Exception as e:
            # 兜底：返回明确失败标识，不让 LLM 继续基于模糊错误编造
            log.error("[Skill] %s failed: %s", tool_name, e)
            return f"⚠️ {tool_name} 数据获取失败：{e}\n请基于已有信息回答或建议用户稍后重试。"

    async def execute_tool_async(self, tool_name: str, timeout: int = 45, **kwargs) -> str:
        """异步执行工具调用，带超时保护（捕获 ToolError 以避免 LLM 基于错误编造数据）"""
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(_executor, lambda: self.execute_tool(tool_name, **kwargs)),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return f"⏱️ {tool_name} 执行超时（>{timeout}s），请尝试更具体的查询条件"
        except ToolError as e:
            # 工具结构性错误（未知工具/缺参数/关键数据源失败）—— 让 LLM 知道不能继续
            return f"⚠️ {tool_name} 调用失败：{e}\n请基于已有信息回答或建议用户调整查询。"

    def _get_stock_fund_flow(self, code: str, market: str) -> str:
        """获取个股资金流向 — 三级降级：东财push2 → 腾讯内外盘 → pytdx"""
        try:
            flow_data = EastMoneySource.get_stock_capital_flow(code)
            if not flow_data:
                return f"无法获取 {code} 的资金流向数据（可能非交易日或数据暂不可用）"

            def yi(v):
                if v is None:
                    return "暂无"
                return f"{v:+.2f}亿" if abs(v) >= 1 else f"{v * 1e4:+.0f}万"

            source = flow_data.get('source', '东财实时')
            main_net = flow_data.get('main_net', 0) or 0
            big_buy = flow_data.get('big_buy', 0)
            big_sell = flow_data.get('big_sell', 0)
            mid_buy = flow_data.get('mid_buy', 0)
            mid_sell = flow_data.get('mid_sell', 0)
            small_buy = flow_data.get('small_buy', 0)
            small_sell = flow_data.get('small_sell', 0)

            lines = [f"=== {code} 资金流向（{source}） ==="]
            if big_buy is not None and big_sell is not None:
                lines.append(f"  主力净流入: {yi(big_buy - big_sell)}")
                lines.append(f"  大单买入: {yi(big_buy)}   大单卖出: {yi(big_sell)}")
                lines.append(f"  中单净额: {yi((mid_buy or 0) - (mid_sell or 0))}")
                lines.append(f"  小单净额: {yi((small_buy or 0) - (small_sell or 0))}")
            else:
                # 腾讯内外盘模式，无大/中/小单细分
                outer = flow_data.get('outer_disk_buy', 0) or 0
                inner = flow_data.get('inner_disk_sell', 0) or 0
                lines.append(f"  主动买入(外盘): {yi(outer)}")
                lines.append(f"  主动卖出(内盘): {yi(inner)}")
                lines.append(f"  净流入: {yi(main_net)}")

            return "\n".join(lines)
        except Exception as e:
            return f"获取 {code} 资金流向失败: {e}"

    def _get_hot_rank(self, top_n: int) -> str:
        """获取热门股票排行"""
        try:
            market_data = EastMoneySource.get_full_market()
            if not market_data:
                return "无法获取热门股票数据"
            # 按成交额排序取热门
            sorted_data = sorted(market_data, key=lambda x: float(x.get("f10", 0) or 0), reverse=True)[:top_n]
            lines = [f"=== 东方财富人气榜 TOP{top_n} ==="]
            lines.append(f"{'排名':<6} {'代码':<10} {'名称':<10} {'最新价':>8} {'涨跌幅':>8}")
            lines.append("-" * 50)
            for i, item in enumerate(sorted_data, 1):
                code = str(item.get("f12", ""))
                name = str(item.get("f14", ""))[:10]
                price = float(item.get("f2", 0) or 0)
                change = float(item.get("f3", 0) or 0)
                lines.append(f"{i:<6} {code:<10} {name:<10} {price:>8.2f} {change:>+7.2f}%")
            return "\n".join(lines)
        except Exception as e:
            return f"获取热门股票排行失败: {e}"

    def _get_sector_fund_flow(self, sector_type: str, top: int) -> str:
        """获取板块资金流向"""
        try:
            if sector_type == "concept":
                boards_data = EastMoneySource.get_concept_boards(page_size=500)
                title = "概念板块资金流向"
            else:
                boards_data = EastMoneySource.get_industry_boards(page_size=100)
                title = "行业板块资金流向"
            if not boards_data:
                return "无法获取板块资金流向数据"
            lines = [f"=== {title} TOP{top} ==="]
            lines.append(f"{'排名':<6} {'板块':<14} {'涨跌幅':>8}")
            lines.append("-" * 32)
            for i, item in enumerate(boards_data[:top], 1):
                name = str(item.get("f14", ""))[:14]
                change = float(item.get("f3", 0) or 0)
                main_net_yi = float(item.get("f62", 0) or 0) / 1e8
                net_str = f"{main_net_yi:+.2f}亿"
                lines.append(f"{i:<6} {name:<14} {change:>+7.2f}% {net_str:>10}")
            return "\n".join(lines)
        except Exception as e:
            return f"获取板块资金流向失败: {e}"

    def _get_main_fund_flow(self, top_n: int) -> str:
        """获取主力资金排名 — 数据源：腾讯财经代理指标（成交额×涨跌幅估算）"""
        try:
            fund_rank = TencentSource.get_fund_flow_rank()
            if not fund_rank:
                return "无法获取主力资金排名数据"
            sorted_data = fund_rank[:top_n]
            lines = [f"=== 主力资金净流入排行 TOP{top_n}（估算） ==="]
            lines.append(f"{'排名':<4} {'代码':<8} {'名称':<10} {'最新价':>8} {'涨跌幅':>8} {'主力净流入(估)':>14}")
            lines.append("-" * 62)
            for i, item in enumerate(sorted_data, 1):
                code = str(item.get("代码", ""))
                name = str(item.get("名称", ""))[:10]
                price = float(item.get("最新价", 0) or 0)
                chg = float(item.get("涨跌幅", 0) or 0)
                net = float(item.get("主力净流入", 0) or 0)
                net_yi = net / 1e8
                net_str = f"{net_yi:+.2f}亿" if abs(net_yi) >= 1 else f"{net_yi * 1e4:+.0f}万"
                lines.append(f"{i:<4} {code:<8} {name:<10} {price:>8.2f} {chg:>+7.2f}% {net_str:>14}")
            return "\n".join(lines)
        except Exception as e:
            return f"获取主力资金排名失败: {e}"

    def _get_stock_news(self, code: str, top_n: int) -> str:
        """获取个股新闻 - 多数据源聚合：东财搜索 → 巨潮公告兜底"""
        results = []

        try:
            news_items = EastMoneyNewsSource.get_stock_news_with_fallback(code, page_size=20)
            if news_items:
                for item in news_items[:top_n]:
                    title = str(item.get("title", ""))
                    pub_time = str(item.get("time", ""))[:16]
                    source = str(item.get("source", "东方财富"))
                    results.append(f"[{pub_time}] {source}: {title}")
        except Exception:
            pass

        return f"=== {code} 最新新闻 ===\n\n" + "\n".join(results) if results else f"暂无 {code} 的新闻数据"

    def _get_cls_news(self, top_n: int) -> str:
        """获取财经快讯 - 多数据源聚合：东财7x24 → 新浪快讯兜底"""
        all_items = []

        # 方案1：东财7x24全球快讯（timeout已缩短至8s）
        try:
            news_items = EastMoneySource.get_global_news(page_size=top_n * 2)
            if news_items:
                for item in news_items[:top_n]:
                    title = str(item.get("title", ""))
                    pub_time = str(item.get("time", ""))[:16]
                    source = str(item.get("source", "东财快讯"))
                    all_items.append(f"[{pub_time}] {source}: {title}")
        except Exception:
            pass

        # 方案2：如果无结果，尝试新浪财经快讯（语义匹配）
        if not all_items:
            try:
                from app.services.news_service import get_sina_finance_news
                sina_items = get_sina_finance_news(top_n=top_n)
                for item in sina_items[:top_n]:
                    title = str(item.get("title", ""))
                    pub_time = str(item.get("time", ""))[:16]
                    source = str(item.get("org", "新浪财经"))
                    all_items.append(f"[{pub_time}] {source}: {title}")
            except Exception:
                pass

        return "=== 今日财经快讯 ===\n\n" + "\n".join(all_items[:top_n]) if all_items else "暂无最新快讯数据"

    def _get_stock_changes(self, top_n: int) -> str:
        """获取盘中异动 — 按涨跌幅排序取异常波动股票"""
        try:
            market_data = EastMoneySource.get_full_market()
            if not market_data:
                return "暂无盘中异动数据"
            # 按涨跌幅绝对值排序，取前 top_n
            sorted_data = sorted(market_data, key=lambda x: abs(float(x.get("f3", 0) or 0)), reverse=True)[:top_n]
            lines = ["=== 盘中异动监控 ==="]
            lines.append(f"{'代码':<8} {'名称':<10} {'最新价':>8} {'涨跌幅':>8} {'成交额':>12}")
            lines.append("-" * 50)
            for item in sorted_data:
                code = str(item.get("f12", ""))
                name = str(item.get("f14", ""))[:10]
                price = float(item.get("f2", 0) or 0)
                chg = float(item.get("f3", 0) or 0)
                amt_yi = float(item.get("f10", 0) or 0) / 1e8
                lines.append(f"{code:<8} {name:<10} {price:>8.2f} {chg:>+7.2f}% {amt_yi:>10.2f}亿")
            return "\n".join(lines)
        except Exception as e:
            return f"获取盘中异动失败: {e}"

    def _get_hot_keywords(self, top_n: int) -> str:
        """获取热门概念板块排行"""
        try:
            boards_data = EastMoneySource.get_concept_boards(page_size=500)
            if not boards_data:
                return "无法获取热门概念数据"
            lines = ["=== 热门概念板块排行 ==="]
            lines.append(f"{'排名':<4} {'概念名称':<14} {'涨跌幅':>8}")
            lines.append("-" * 30)
            for i, item in enumerate(boards_data[:top_n], 1):
                name = str(item.get("f14", ""))[:14]
                chg = float(item.get("f3", 0) or 0)
                lines.append(f"{i:<4} {name:<14} {chg:>+7.2f}%")
            return "\n".join(lines)
        except Exception as e:
            return f"获取热门概念失败: {e}"

    def _format_sentiment(self, data: dict) -> str:
        """格式化情绪数据为可读文本"""
        if not isinstance(data, dict):
            return str(data)

        lines = [
            "=== 市场情绪分析 ===",
            f"综合评分: {data.get('score', '--')}/100 ({data.get('signal', '--')})",
            "",
        ]

        # 大盘指数
        indices = data.get("indices", {})
        if indices:
            lines.append("--- 大盘指数 ---")
            for code, idx in indices.items():
                name = idx.get('name', code)
                price = idx.get('price', '--')
                change = idx.get('change_pct', 0.0)
                amount = idx.get('amount_billion', '')
                # 处理NaN值
                try:
                    if math.isnan(float(change)):
                        change = 0.0
                    lines.append(f"  {name}: {price} ({change:+.2f}%) 成交额{amount}亿")
                except (ValueError, TypeError):
                    lines.append(f"  {name}: {price} (--%) 成交额{amount}亿")

        # 涨跌统计
        breadth = data.get("breadth", {})
        if breadth:
            lines.append("")
            lines.append("--- 涨跌统计 ---")
            lines.append(f"  涨{breadth.get('up', '--')} / 跌{breadth.get('down', '--')} / 平{breadth.get('flat', '--')} (共{breadth.get('total', '--')}只)")

        # 涨停跌停
        limit = data.get("limit_up_down", {})
        if limit:
            lines.append(f"  涨停: {limit.get('limit_up', '--')} / 跌停: {limit.get('limit_down', '--')}")

        # 成交额
        volume = data.get("volume", {})
        if volume:
            lines.append("")
            lines.append("--- 成交情况 ---")
            lines.append(f"  总成交额: {volume.get('total_billion', '--'):.0f}亿 ({volume.get('signal', '--')})")

        # 资金流向
        flow = data.get("money_flow", {})
        if flow:
            lines.append("")
            lines.append("--- 资金流向 ---")
            net = flow.get('net_inflow_billion', 0) or 0.0
            inflow = flow.get('inflow_billion', 0) or 0.0
            outflow = flow.get('outflow_billion', 0) or 0.0
            # 处理NaN和inf值
            net = sanitize_number(net)
            inflow = sanitize_number(inflow)
            outflow = sanitize_number(outflow)
            lines.append(f"  主力净流入: {net:+.1f}亿 (流入{inflow:.1f}亿 / 流出{outflow:.1f}亿)")

        return "\n".join(lines)

    def _format_sector_result(self, data: dict) -> str:
        """格式化板块分析结果"""
        if not isinstance(data, dict):
            return str(data)
        sectors = data.get('sectors', [])
        if not sectors:
            return "暂无板块数据"
        lines = ["=== 板块行情 ==="]
        for s in sectors[:15]:
            change = s.get('change_pct', 0)
            flow_net = s.get('flow_net', 0)
            arrow = '↑' if change > 0 else '↓'
            lines.append(f"- {s.get('name', '')}: {arrow} {abs(change):.2f}% (资金净额: {int(flow_net)}万)")
        return '\n'.join(lines)

    def _format_rotation_result(self, data: dict) -> str:
        """格式化板块轮动信号"""
        if not isinstance(data, dict):
            return str(data)
        lines = ["=== 板块轮动信号 ==="]

        leading = data.get('leading_style', '--')
        perf = data.get('style_performance', {})
        perf_str = ', '.join(f"{k}: {v:+.2f}%" for k, v in perf.items()) if perf else '--'
        lines.append(f"风格偏好: {leading} ({perf_str})")

        flow_leading = data.get('flow_leading_style', '--')
        flow = data.get('style_flow', {})
        flow_str = ', '.join(f"{k}: {v:+.1f}亿" for k, v in flow.items()) if flow else '--'
        lines.append(f"资金偏好: {flow_leading} ({flow_str})")

        heat = data.get('heat_score', '--')
        lines.append(f"板块热度: {heat}/100")

        concentration = data.get('concentration_ratio', '--')
        lines.append(f"资金集中度: {concentration}%")

        top_inflow = data.get('top_inflow_sectors', [])
        if top_inflow:
            names = ', '.join(f"{s['name']}(+{s['flow_net']:.1f}亿)" for s in top_inflow[:3])
            lines.append(f"资金流入前列: {names}")

        accum = data.get('accumulation_divergence', [])
        if accum:
            names = ', '.join(f"{s['name']}({s['signal']})" for s in accum[:3])
            lines.append(f"逆势吸筹信号: {names}")

        warning = data.get('warning_divergence', [])
        if warning:
            names = ', '.join(f"{s['name']}({s['signal']})" for s in warning[:3])
            lines.append(f"⚠ 出货信号: {names}")

        advice = data.get('advice', '')
        if advice:
            lines.append(f"操作建议: {advice}")

        return '\n'.join(lines)

    def _format_pick_result(self, data: dict) -> str:
        """格式化选股结果"""
        if not isinstance(data, dict):
            return str(data)
        stocks = data.get('stocks', []) or data.get('picks', [])
        if not stocks:
            raw = data.get('raw_output', '')
            if raw:
                return raw
            return "暂无选股数据"
        lines = ["=== 选股结果 ==="]
        for s in stocks[:15]:
            code = s.get('code', '')
            name = s.get('name', '')
            score = s.get('score', s.get('prediction_score', '--'))
            price = s.get('price', '--')
            change = s.get('change_pct', s.get('pct_change', ''))
            lines.append(f"- {code} {name}: 评分{score}, 价格{price}, 涨跌{change}")
        return '\n'.join(lines)

    def _format_dict_result(self, data: dict, title: str = "数据") -> str:
        """通用字典格式化"""
        if not isinstance(data, dict):
            return str(data)
        raw = data.get('raw_output', '')
        if raw:
            return raw
        lines = [f"=== {title} ==="]
        for k, v in data.items():
            if k in ('raw_output', 'stocks', 'picks', 'sectors'):
                continue
            if isinstance(v, dict):
                lines.append(f"{k}:")
                for sk, sv in v.items():
                    lines.append(f"  {sk}: {sv}")
            elif isinstance(v, list) and len(v) > 0:
                lines.append(f"{k} ({len(v)}条)")
            else:
                lines.append(f"- {k}: {v}")
        return '\n'.join(lines)


# 全局编排器实例
orchestrator = SkillOrchestrator()
