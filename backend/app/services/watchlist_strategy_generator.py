"""自选股AI策略生成器 - 仅建议，不执行

四种模式：
1. morning: 10:25 盘中策略
2. midday: 12:30 午间策略
3. afternoon: 14:10 盘中策略
4. closing: 16:00 收盘策略

优化要点（参考 ai_strategy_generator.py）：
- 提示词专业化：持仓周期差异化 + 金字塔建仓 + 板块分散 + 避免追高杀跌 + 现金为王
- 数据维度增强：技术指标 + 板块热度 + 北向资金 + 龙虎榜 + 板块轮动 + 持仓风控 + 候选股票池 + 历史反馈
- 动态仓位配置：基于市场情绪自适应仓位上限
- 结果校验：股票代码合法性 + action/risk_level 枚举校验
- LLM 重试：错误反馈给 LLM 让其修正
- 策略覆盖：按 user_id + decision_date + strategy_mode 覆盖更新
"""
import json
import asyncio
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Set
from sqlalchemy.orm import Session
import logging

from app.models.holding import Holding
from app.models.watchlist import WatchlistItem
from app.models.watchlist_strategy import WatchlistStrategyDecision, WatchlistStrategyConfig

log = logging.getLogger(__name__)


class WatchlistAIStrategyGenerator:
    """自选股AI策略生成器（仅建议，不执行）"""

    # ── 公共基础规则 ────────────────────────────────────────
    _COMMON_RULES = """## 通用决策规则
1. **仅提供建议，不执行交易**：所有建议仅供用户参考，用户自行决定是否操作
2. **分开处理**：
   - 持仓股票：分析是否需要卖出/减仓/持有/加仓，必须为每只持仓给出建议
   - 自选股：分析是否有买入机会/关注价值
3. **风险提示**：每个建议都要给出风险等级和注意事项
4. **参考近期经验教训**（如有），避免重复犯错

## 持仓周期配置（必须严格遵守，每条建议必须标注 position_type）
账户持仓分为三个周期，建议中必须新增 "position_type" 字段（值: short/mid/long）：
- **短线（short）**：持仓 1-5 个交易日，止损 5%，止盈 8-15%，单只仓位 ≤ 10%
  适用：资金流入龙头、放量突破、龙虎榜活跃标的、热点题材
  决策要点：快进快出，不恋战；达到 8% 即可分批止盈，跌破 5% 果断止损
- **中线（mid）**：持仓 5-30 个交易日，止损 10%，止盈 20-40%，单只仓位 ≤ 15%
  适用：板块轮动、业绩预期、技术面突破回踩、北向持续流入
  决策要点：耐心持有，不因短期波动操作；浮盈 20% 后启动移动止盈
- **长线（long）**：持仓 30-90 个交易日，止损 15%，止盈 40-100%，单只仓位 ≤ 20%
  适用：基本面优秀、低估值、行业龙头、政策长期利好
  决策要点：忽略短期波动，聚焦基本面变化；只有基本面恶化或达 40% 以上盈利才考虑退出

## 投资布局建议（AI 自主决策参考，需根据下方"动态仓位配置"调整）
- **金字塔建仓**：对已持有的盈利标的可加仓，加仓数量 ≤ 底仓 1/3，且必须在浮盈时加仓（浮亏不加仓）
- **板块分散**：单一行业集中度不得超过 30%，新买入若导致某行业超限请放弃或减少数量
- **避免追高**：涨幅已超过 6% 的标的一般不追入；候选中优先选择 source=oversold/low_absorption/multi_factor 的反向机会
- **避免杀跌**：浮亏但基本面未恶化的中线/长线持仓不要急于止损，给市场修复时间
- **现金为王**：保留至少 20-40% 现金仓位（按市场情绪调整），用于应对突发机会和风险
- **技术面参考**：结合 MA/MACD/KDJ/RSI/BOLL 信号判断买卖点，金叉/超卖/突破上轨为买入信号，死叉/超买/跌破下轨为卖出信号

## 深度分析要求（每条建议必须包含以下分析维度）
每条建议的 reason 字段必须写成一段完整的分析（2-4句话），覆盖以下维度：
1. **技术面分析**：当前趋势（MA5/MA20 排列）、量价关系、MACD/KDJ 信号状态
2. **资金面/市场面**：主力资金流向、所属板块热度、北向资金态度（如可判断）
3. **操作逻辑**：为什么在这个时点操作？预期什么？核心依据是什么？
4. **关键价位**：明确指出关键支撑位和阻力位，作为设置止损止盈的参考

示例（good）：
"该股处于上升通道，MA5>MA10>MA20 多头排列，MACD 金叉持续红柱放大，量价配合良好。所属半导体板块近期受政策利好驱动，板块资金连续 3 日净流入。当前处于突破前高后的回踩确认阶段，建议在回踩 MA5 附近加仓。关键支撑 15.2 元（MA20 位置），若跌破则止损观察。"

示例（bad, too short）：
"技术面良好，建议加仓"

## 分析报告要求
- market_analysis（市场分析）：结合指数走势、板块轮动、北向资金、市场情绪，给出清晰的市场判断（200-400字）
- position_analysis（持仓分析）：结合整体盈亏分布、各周期持仓表现、风控状态，给出持仓调整方向（200-500字）"""

    # ── 输出格式 ────────────────────────────────────────
    _COMMON_OUTPUT_FORMAT = """## 输出格式（纯JSON，不要其他文字，不要markdown标记）
{
  "market_sentiment": "bullish/bearish/neutral",
  "market_analysis": "市场分析（200-400字，结合指数/板块/北向资金/情绪）",
  "position_analysis": "持仓整体分析（200-500字，结合风控/周期/盈亏分布）",
  "position_ratio": 0-100,
  "holdings_suggestions": [
    {
      "code": "6位代码",
      "name": "名称",
      "action": "sell/reduce/hold/add",
      "position_type": "short/mid/long",
      "reason": "详细分析（2-4句话，覆盖技术面+资金面+操作逻辑+关键价位）",
      "technical_summary": "技术面一句话总结（如：多头排列/MACD金叉/放量突破）（可选）",
      "target_price": "目标价（可选）",
      "stop_loss": "止损价（可选）",
      "stop_loss_pct": "止损百分比（可选，如-5）",
      "take_profit_pct": "止盈百分比（可选，如15）",
      "risk_level": "low/medium/high"
    }
  ],
  "watchlist_suggestions": [
    {
      "code": "6位代码",
      "name": "名称",
      "action": "buy/watch",
      "position_type": "short/mid/long",
      "reason": "详细分析（2-4句话，覆盖技术面+资金面+操作逻辑+关键价位）",
      "technical_summary": "技术面一句话总结（可选）",
      "entry_price": "建议入场价（可选）",
      "target_price": "目标价（可选）",
      "suggested_position_ratio": "建议仓位占比0-20（可选）",
      "risk_level": "low/medium/high"
    }
  ],
  "risk_warning": "整体风险提示（40-80字）"
}"""

    STRATEGY_SYSTEM_PROMPT = """你是A股资深投资顾问。基于用户的持仓股票、自选股列表和市场环境，提供专业投资建议。

""" + _COMMON_RULES + """

""" + _COMMON_OUTPUT_FORMAT

    # 模式标签（与 API 层映射保持一致：intraday→morning/afternoon 由调用方解析）
    MODE_LABELS = {
        "morning": "盘中策略-上午",
        "midday": "午间策略",
        "afternoon": "盘中策略-下午",
        "closing": "收盘策略",
    }

    # API 层模式 → 内部模式映射
    API_MODE_MAP = {
        "intraday": None,  # 需根据当前时间判断 morning/afternoon
        "midday": "midday",
        "closing": "closing",
    }

    # 持仓周期止损止盈阈值（与提示词保持一致）
    POS_THRESHOLDS = {
        "short": {"stop_loss": -5, "take_profit": 8, "strong_profit": 15, "max_position": 10},
        "mid":   {"stop_loss": -10, "take_profit": 20, "strong_profit": 40, "max_position": 15},
        "long":  {"stop_loss": -15, "take_profit": 40, "strong_profit": 100, "max_position": 20},
    }

    # 允许的枚举值
    VALID_HOLDINGS_ACTIONS = {"sell", "reduce", "hold", "add"}
    VALID_WATCHLIST_ACTIONS = {"buy", "watch"}
    VALID_RISK_LEVELS = {"low", "medium", "high"}
    VALID_POSITION_TYPES = {"short", "mid", "long"}

    @staticmethod
    def generate_strategy(
        db: Session,
        user_id: int,
        mode: str = None,
        source: str = "auto",
    ) -> Dict[str, Any]:
        """生成自选股AI策略

        Args:
            db: 数据库会话
            user_id: 用户ID
            mode: 策略模式（morning/midday/afternoon/closing 或 API 层 intraday/midday/closing），None则自动判断
            source: 来源（auto=定时任务, manual=手动生成）
        """
        # API 层模式映射到内部模式
        if mode in WatchlistAIStrategyGenerator.API_MODE_MAP:
            internal_mode = WatchlistAIStrategyGenerator.API_MODE_MAP[mode]
            mode = internal_mode if internal_mode else WatchlistAIStrategyGenerator._auto_detect_intraday_mode()

        # 自动判断模式
        if mode is None:
            mode = WatchlistAIStrategyGenerator._auto_detect_mode()

        # 获取用户持仓
        holdings = db.query(Holding).filter(Holding.user_id == user_id).all()
        if not holdings:
            return {"success": False, "error": "暂无持仓股票，请先添加持仓"}

        # 获取用户自选股
        watchlist = db.query(WatchlistItem).filter(WatchlistItem.user_id == user_id).all()

        # 获取持仓数据（含实时价格 + 技术指标 + 风控信息）
        holdings_data, holdings_indicators = WatchlistAIStrategyGenerator._get_holdings_data(holdings)
        position_risk_text = WatchlistAIStrategyGenerator._get_position_risk_info(holdings, holdings_indicators)

        # 获取自选股数据（含实时价格 + 技术指标）
        watchlist_data, watchlist_indicators = WatchlistAIStrategyGenerator._get_watchlist_data(watchlist)

        # 已持仓股票代码集合（用于过滤候选股票池）
        held_codes = {h.stock_code for h in holdings}
        # 用户自选股代码集合
        watchlist_codes = {w.stock_code for w in watchlist}

        # ── 并行获取市场环境数据（5个独立数据源）──
        from concurrent.futures import ThreadPoolExecutor, as_completed
        market_data = {}
        market_extra = {}
        dragon_summary = ""
        sector_rotation = ""
        hot_stocks = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(WatchlistAIStrategyGenerator._get_market_overview): "market_data",
                executor.submit(WatchlistAIStrategyGenerator._get_market_extra): "market_extra",
                executor.submit(WatchlistAIStrategyGenerator._get_dragon_list_summary): "dragon_summary",
                executor.submit(WatchlistAIStrategyGenerator._get_sector_rotation_summary): "sector_rotation",
                executor.submit(WatchlistAIStrategyGenerator._get_hot_stocks, held_codes): "hot_stocks",
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    result = future.result()
                    if key == "market_data":
                        market_data = result
                    elif key == "market_extra":
                        market_extra = result
                    elif key == "dragon_summary":
                        dragon_summary = result
                    elif key == "sector_rotation":
                        sector_rotation = result
                    elif key == "hot_stocks":
                        hot_stocks = result
                except Exception as e:
                    log.warning(f"并行获取 {key} 失败: {e}")

        # 获取历史策略表现（反馈闭环）
        recent_performance = WatchlistAIStrategyGenerator._get_recent_strategy_performance(db, user_id)

        # 动态仓位配置
        dynamic_position = WatchlistAIStrategyGenerator._calc_dynamic_position(market_data, holdings_data)

        # 构建用户提示词
        user_prompt = WatchlistAIStrategyGenerator._build_user_prompt(
            mode=mode,
            holdings_data=holdings_data,
            holdings_indicators=holdings_indicators,
            watchlist_data=watchlist_data,
            watchlist_indicators=watchlist_indicators,
            market_data=market_data,
            market_extra=market_extra,
            dragon_summary=dragon_summary,
            sector_rotation=sector_rotation,
            hot_stocks=hot_stocks,
            position_risk_text=position_risk_text,
            recent_performance=recent_performance,
            dynamic_position=dynamic_position,
        )

        # 调用LLM生成策略
        from app.core.llm_service import llm_config, llm_client
        if not llm_config.enabled:
            return {"success": False, "error": "LLM服务未启用"}

        messages = [
            {"role": "system", "content": WatchlistAIStrategyGenerator.STRATEGY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        llm_response = ""
        strategy_data = None
        for _attempt in range(2):
            try:
                result = asyncio.run(
                    llm_client.chat_completion(messages=messages, stream=False)
                )
                llm_response = result.get("content", "")

            except Exception as e:
                log.error(f"LLM调用失败: {e}")
                if _attempt == 1:
                    return {"success": False, "error": f"AI分析失败: {str(e)}"}
                continue

            # 解析LLM响应
            strategy_data = WatchlistAIStrategyGenerator._parse_llm_response(llm_response)
            if strategy_data is not None:
                break

            # 首次解析失败，反馈给 LLM 让其修正
            if _attempt == 0:
                log.warning("LLM响应JSON解析失败，尝试反馈重试")
                try:
                    retry_messages = messages + [
                        {"role": "assistant", "content": llm_response[:500]},
                        {"role": "user", "content": "你的上一条回复不是有效的JSON格式。请严格按照要求的JSON格式输出，不要添加任何额外的解释文字。直接输出JSON。"},
                    ]
                    retry_result = asyncio.run(
                        llm_client.chat_completion(messages=retry_messages, stream=False)
                    )
                    llm_response = retry_result.get("content", "")
                except Exception as retry_e:
                    log.error(f"LLM重试调用失败: {retry_e}")
                    break

        if strategy_data is None:
            return {"success": False, "error": "AI响应格式错误，请重试"}

        # ── 结果校验（防 AI 编造股票代码 + 枚举合法性 + 合理性校验）──
        candidate_codes = {s.get("code", "") for s in hot_stocks if s.get("code")}
        valid_watchlist_codes = watchlist_codes | candidate_codes

        # 构建持仓代码到数据的映射（用于价格方向性校验）
        holdings_map = {h["code"]: h for h in holdings_data}

        # 动态仓位上限（百分比）
        dynamic_max_position_pct = dynamic_position.get("dynamic_max_position_ratio", 0) * 100

        strategy_data = WatchlistAIStrategyGenerator._validate_strategy_data(
            strategy_data, held_codes, valid_watchlist_codes,
            holdings_map, dynamic_max_position_pct,
        )

        # ── 建议一致性检查：同一股票不应同时出现在持仓建议和自选股建议中 ──
        # 持仓股票已在 holdings_suggestions 中给出建议，不应再出现在 watchlist_suggestions 中
        holdings_advised_codes = {
            str(item.get("code", "")).strip()
            for item in strategy_data.get("holdings_suggestions", [])
        }
        consistent_watchlist = []
        for item in strategy_data.get("watchlist_suggestions", []):
            code = str(item.get("code", "")).strip()
            if code in holdings_advised_codes:
                log.warning(f"AI 同时在持仓建议和自选股建议中推荐 {code}，已从自选股建议中移除")
                continue
            consistent_watchlist.append(item)
        strategy_data["watchlist_suggestions"] = consistent_watchlist

        # 标记自选股建议中的"AI 推荐新增"（不在用户自选股中，来自候选池）
        for item in strategy_data.get("watchlist_suggestions", []):
            code = str(item.get("code", "")).strip()
            item["is_new_recommendation"] = code not in watchlist_codes

        # ── 保存策略记录（同 user_id + decision_date + strategy_mode 覆盖更新）──
        decision_date_str = date.today().strftime("%Y-%m-%d")
        decision = db.query(WatchlistStrategyDecision).filter(
            WatchlistStrategyDecision.user_id == user_id,
            WatchlistStrategyDecision.decision_date == decision_date_str,
            WatchlistStrategyDecision.strategy_mode == mode,
        ).first()

        # 序列化建议列表
        holdings_suggestions_json = json.dumps(strategy_data.get("holdings_suggestions", []), ensure_ascii=False)
        watchlist_suggestions_json = json.dumps(strategy_data.get("watchlist_suggestions", []), ensure_ascii=False)
        suggested_allocation = dynamic_position.get("suggested_allocation", {})
        suggested_allocation_json = json.dumps(suggested_allocation, ensure_ascii=False)
        market_indicators_data = {
            "indices": market_data.get("indices", {}),
            "sentiment": market_data.get("sentiment", "neutral"),
            "sectors": market_extra.get("sectors", []),
            "northbound": market_extra.get("northbound", ""),
            "dragon_summary": dragon_summary,
            "sector_rotation": sector_rotation,
            "hot_stocks_count": len(hot_stocks),
        }
        market_indicators_json = json.dumps(market_indicators_data, ensure_ascii=False)

        if decision:
            # 同模式策略 → 覆盖更新
            decision.decision_time = datetime.now().strftime("%H:%M:%S")
            decision.market_sentiment = strategy_data.get("market_sentiment", "neutral")
            decision.market_analysis = strategy_data.get("market_analysis", "")
            decision.position_analysis = strategy_data.get("position_analysis", "")
            decision.holdings_suggestions = holdings_suggestions_json
            decision.watchlist_suggestions = watchlist_suggestions_json
            decision.position_ratio = strategy_data.get("position_ratio")
            decision.dynamic_max_position = dynamic_position.get("dynamic_max_position_ratio", 0) * 100
            decision.suggested_allocation = suggested_allocation_json
            decision.market_stage = dynamic_position.get("market_stage", "")
            decision.market_indicators = market_indicators_json
            decision.ai_analysis = llm_response
            decision.risk_warning = strategy_data.get("risk_warning", "")
            decision.status = "active"
        else:
            decision = WatchlistStrategyDecision(
                user_id=user_id,
                decision_date=decision_date_str,
                decision_time=datetime.now().strftime("%H:%M:%S"),
                strategy_mode=mode,
                market_sentiment=strategy_data.get("market_sentiment", "neutral"),
                market_analysis=strategy_data.get("market_analysis", ""),
                position_analysis=strategy_data.get("position_analysis", ""),
                holdings_suggestions=holdings_suggestions_json,
                watchlist_suggestions=watchlist_suggestions_json,
                position_ratio=strategy_data.get("position_ratio"),
                dynamic_max_position=dynamic_position.get("dynamic_max_position_ratio", 0) * 100,
                suggested_allocation=suggested_allocation_json,
                market_stage=dynamic_position.get("market_stage", ""),
                market_indicators=market_indicators_json,
                ai_analysis=llm_response,
                risk_warning=strategy_data.get("risk_warning", ""),
                status="active",
            )
            db.add(decision)

        db.commit()
        db.refresh(decision)

        return {
            "success": True,
            "decision_id": decision.id,
            "decision_date": decision.decision_date,
            "decision_time": decision.decision_time,
            "mode": mode,
            "mode_label": WatchlistAIStrategyGenerator.MODE_LABELS.get(mode, mode),
            "market_sentiment": strategy_data.get("market_sentiment", "neutral"),
            "market_analysis": strategy_data.get("market_analysis", ""),
            "position_analysis": strategy_data.get("position_analysis", ""),
            "position_ratio": strategy_data.get("position_ratio"),
            "dynamic_max_position": dynamic_position.get("dynamic_max_position_ratio", 0) * 100,
            "suggested_allocation": suggested_allocation,
            "market_stage": dynamic_position.get("market_stage", ""),
            "market_indicators": market_indicators_data,
            "holdings_suggestions": strategy_data.get("holdings_suggestions", []),
            "watchlist_suggestions": strategy_data.get("watchlist_suggestions", []),
            "risk_warning": strategy_data.get("risk_warning", ""),
        }

    # ── 模式判断 ────────────────────────────────────────
    @staticmethod
    def _auto_detect_mode() -> str:
        """自动检测当前应使用的策略模式"""
        now = datetime.now()
        current_time = now.hour * 60 + now.minute

        if current_time < 10 * 60 + 25:
            return "morning"
        elif current_time < 12 * 60 + 30:
            return "midday"
        elif current_time < 14 * 60 + 10:
            return "afternoon"
        else:
            return "closing"

    @staticmethod
    def _auto_detect_intraday_mode() -> str:
        """盘中模式细分为 morning/afternoon"""
        now = datetime.now()
        current_time = now.hour * 60 + now.minute
        return "morning" if current_time < 12 * 60 else "afternoon"

    # ── 数据采集：持仓 + 技术指标 ────────────────────────
    @staticmethod
    def _get_holdings_data(holdings: List[Holding]) -> tuple:
        """获取持仓数据（含实时价格）+ 技术指标

        Returns:
            (holdings_data, indicators_map)
        """
        import pandas as pd
        from app.core.pytdx_source import pytdx_data
        from app.services.stock_service import StockService

        codes = [h.stock_code for h in holdings]
        quotes = {}
        if codes:
            try:
                quote_list = pytdx_data.get_realtime_quote(codes) or []
                quotes = {q["code"]: q for q in quote_list}
            except Exception as e:
                log.warning(f"获取持仓行情失败: {e}")

        # 批量获取K线并计算技术指标
        indicators_map = {}
        if codes:
            try:
                kline_data = pytdx_data.get_batch_klines(codes, period=4, count=120, max_workers=5)
                service = StockService()
                for code in codes:
                    klines = kline_data.get(code, []) or []
                    if not klines:
                        continue
                    try:
                        df = pd.DataFrame(klines)
                        for col in ['close', 'open', 'high', 'low', 'volume']:
                            df[col] = pd.to_numeric(df[col])
                        indicators_map[code] = service._calc_indicators(df)
                    except Exception as e:
                        log.warning(f"计算持仓 {code} 技术指标失败: {e}")
            except Exception as e:
                log.warning(f"批量获取持仓K线失败: {e}")

        result = []
        for h in holdings:
            q = quotes.get(h.stock_code, {})
            current_price = q.get("price", h.current_price) or h.current_price
            # 过滤异常 change_pct（pytdx 非交易时间可能返回 -100% 等脏数据）
            raw_change = q.get("change_pct") if q else None
            if raw_change is not None and -20 <= raw_change <= 20:
                change_pct = round(raw_change, 2)
            else:
                change_pct = None
            market_value = round(current_price * h.quantity, 2) if current_price and h.quantity else (h.market_value or 0)
            profit = round((current_price - h.cost_price) * h.quantity, 2) if current_price and h.cost_price and h.quantity else (h.profit or 0)
            profit_ratio = round(profit / ((h.cost_price * h.quantity) or 1) * 100, 2) if h.cost_price and h.quantity and current_price else (h.profit_ratio or 0)

            # 持仓天数
            hold_days = 0
            buy_date_str = h.buy_date or ""
            if buy_date_str:
                try:
                    bd = date.fromisoformat(buy_date_str) if isinstance(buy_date_str, str) else buy_date_str
                    hold_days = (date.today() - bd).days
                except Exception:
                    pass

            result.append({
                "code": h.stock_code,
                "name": h.stock_name,
                "quantity": h.quantity,
                "cost_price": h.cost_price,
                "current_price": current_price,
                "change_pct": change_pct,
                "market_value": market_value,
                "profit": profit,
                "profit_ratio": profit_ratio,
                "buy_date": buy_date_str or "未知",
                "position_type": h.position_type or "short",
                "hold_days": hold_days,
            })
        return result, indicators_map

    @staticmethod
    def _get_watchlist_data(watchlist: List[WatchlistItem]) -> tuple:
        """获取自选股数据（含实时价格）+ 技术指标

        Returns:
            (watchlist_data, indicators_map)
        """
        import pandas as pd
        from app.core.pytdx_source import pytdx_data
        from app.services.stock_service import StockService

        codes = [w.stock_code for w in watchlist]
        quotes = {}
        if codes:
            try:
                quote_list = pytdx_data.get_realtime_quote(codes) or []
                quotes = {q["code"]: q for q in quote_list}
            except Exception as e:
                log.warning(f"获取自选股行情失败: {e}")

        # 批量获取K线并计算技术指标
        indicators_map = {}
        if codes:
            try:
                kline_data = pytdx_data.get_batch_klines(codes, period=4, count=120, max_workers=5)
                service = StockService()
                for code in codes:
                    klines = kline_data.get(code, []) or []
                    if not klines:
                        continue
                    try:
                        df = pd.DataFrame(klines)
                        for col in ['close', 'open', 'high', 'low', 'volume']:
                            df[col] = pd.to_numeric(df[col])
                        indicators_map[code] = service._calc_indicators(df)
                    except Exception as e:
                        log.warning(f"计算自选股 {code} 技术指标失败: {e}")
            except Exception as e:
                log.warning(f"批量获取自选股K线失败: {e}")

        result = []
        for w in watchlist:
            q = quotes.get(w.stock_code, {})
            # 过滤异常 change_pct
            raw_change = q.get("change_pct") if q else None
            if raw_change is not None and -20 <= raw_change <= 20:
                change_pct = round(raw_change, 2)
            else:
                change_pct = None
            result.append({
                "code": w.stock_code,
                "name": w.stock_name or w.stock_code,
                "group": w.group,
                "current_price": q.get("price", 0),
                "change_pct": change_pct,
            })
        return result, indicators_map

    # ── 数据采集：市场概况 ────────────────────────────────
    @staticmethod
    def _get_market_overview() -> Dict:
        """获取市场概况（指数 + 涨跌家数 + 情绪）"""
        data = {"indices": {}, "sentiment": "neutral", "breadth": {}}
        try:
            from app.services.market_service import MarketService
            ms = MarketService()
            sentiment = ms.get_market_sentiment(include_flow=False)
            if sentiment:
                data["indices"] = sentiment.get("indices", {})
                breadth = sentiment.get("breadth", {})
                data["breadth"] = breadth
                total = breadth.get("total", 1)
                up = breadth.get("up", 0)
                down = breadth.get("down", 0)
                if total > 0:
                    ratio = up / total
                    if ratio > 0.6:
                        data["sentiment"] = "bullish"
                    elif ratio < 0.4:
                        data["sentiment"] = "bearish"
                    else:
                        data["sentiment"] = "neutral"
        except Exception as e:
            log.warning(f"获取市场数据失败: {e}")
        return data

    @staticmethod
    def _get_market_extra() -> Dict:
        """获取板块排名和北向资金摘要（用于 prompt 注入）"""
        result = {"sectors": [], "northbound": ""}
        try:
            from app.services.market_service import MarketService
            ms = MarketService()
            sectors_data = ms.get_sectors(sector_type='concept', top=5)
            if sectors_data and sectors_data.get('sectors'):
                result["sectors"] = sectors_data["sectors"]
        except Exception as e:
            log.warning(f"获取板块排名失败: {e}")
        try:
            from app.services.market_service import MarketService
            ms = MarketService()
            nb = ms.get_northbound_flow()
            if nb and nb.get('summary'):
                s = nb['summary']
                hgt = s.get('hgt_latest', 0) or 0
                sgt = s.get('sgt_latest', 0) or 0
                total = hgt + sgt
                direction = "流入" if total > 0 else "流出"
                result["northbound"] = f"北向资金: {direction}{abs(total):.1f}亿 (沪股通{hgt:+.1f}亿 深股通{sgt:+.1f}亿)"
        except Exception as e:
            log.warning(f"获取北向资金失败: {e}")
        return result

    @staticmethod
    def _get_dragon_list_summary() -> str:
        """获取今日龙虎榜摘要，注入策略 prompt

        龙虎榜数据每天下午16:30后才发布，盘中查询会回退到上一交易日
        """
        try:
            from app.services.strategy_service import StrategyService
            ss = StrategyService()
            dragon = ss.get_dragon_list_today()
            if not dragon:
                # 区分"非交易时段"和"当日无数据"
                from datetime import datetime as _dt
                now = _dt.now()
                if now.hour < 16 or (now.hour == 16 and now.minute < 30):
                    return "（盘中暂无龙虎榜数据，16:30后发布；如有将自动回退到上一交易日）"
                return "（当日龙虎榜数据为空）"

            lines = []
            # 数据日期提示
            dragon_date = dragon.get("dragon_data_date") or dragon.get("date", "")
            if dragon_date:
                lines.append(f"（龙虎榜数据日期: {dragon_date}）")

            gainers = dragon.get("gainers_list", [])[:8]
            if gainers:
                lines.append("龙虎榜涨幅榜:")
                for g in gainers:
                    code = g.get("code", "")
                    name = g.get("name", "")
                    change = g.get("change_pct", 0)
                    reason = g.get("reason", "")
                    lines.append(f"  {code} {name} +{change:.2f}% {reason}")

            losers = dragon.get("losers_list", [])[:5]
            if losers:
                lines.append("龙虎榜跌幅榜:")
                for l in losers:
                    code = l.get("code", "")
                    name = l.get("name", "")
                    change = l.get("change_pct", 0)
                    reason = l.get("reason", "")
                    lines.append(f"  {code} {name} {change:.2f}% {reason}")

            limit_up = dragon.get("limit_up_count", 0)
            limit_down = dragon.get("limit_down_count", 0)
            if limit_up or limit_down:
                lines.append(f"涨停{limit_up}家 / 跌停{limit_down}家")

            return "\n".join(lines) if lines else "（龙虎榜数据为空）"
        except Exception as e:
            log.warning(f"获取龙虎榜摘要失败: {e}")
            return ""

    @staticmethod
    def _get_sector_rotation_summary() -> str:
        """获取板块轮动摘要，注入策略 prompt"""
        try:
            from app.services.sector_analysis_service import sector_analysis_service
            result = sector_analysis_service.get_sector_rotation_model(
                sector_type="concept", top_n=10
            )
            if not result:
                return ""

            sectors = result.get("sectors", [])[:8]
            signal = result.get("rotation_signal", "")
            if not sectors:
                return ""

            lines = ["板块轮动(概念板块TOP8):"]
            for s in sectors:
                name = s.get("name", "")
                score = s.get("score", 0)
                change = s.get("change_pct", 0)
                lifecycle = s.get("lifecycle", "")
                lines.append(f"  {name} 评分{score:.0f} 涨跌{change:+.2f}% {lifecycle}")
            if signal:
                lines.append(f"轮动信号: {signal}")

            return "\n".join(lines)
        except Exception as e:
            log.warning(f"获取板块轮动摘要失败: {e}")
            return ""

    # ── 数据采集：候选股票池（多源热门股票） ────────────────
    @staticmethod
    def _get_hot_stocks(exclude_codes: Set[str] = None) -> List[Dict]:
        """获取多类型候选股票（避免追高偏置）

        Args:
            exclude_codes: 需要排除的股票代码集合（如用户已持有的股票）

        候选来源：
        1. capital_flow 资金流入（短线候选）
        2. gainers 涨幅榜前20（短线候选，已过滤ST/涨停）
        3. oversold 超跌反弹（-3%~-8%）（中线候选）
        4. low_absorption 低吸企稳（长线候选）
        5. multi_factor 多因子综合（中线候选）
        """
        exclude_codes = exclude_codes or set()
        candidates = []

        # 方法1：资金流入（短线候选）
        try:
            from app.services.strategy_service import StrategyService
            ss = StrategyService()
            picks = ss.get_capital_flow_picks(top_n=10)
            if picks and picks.get("stocks"):
                for s in picks["stocks"][:10]:
                    candidates.append({
                        "code": s.get("code", ""),
                        "name": s.get("name", ""),
                        "reason": "资金流入",
                        "source": "capital_flow",
                        "suggested_type": "short",
                    })
        except Exception as e:
            log.warning(f"获取资金流向选股失败: {e}")

        # 方法2：涨幅榜前20 + 方法3：超跌反弹（共用一次市场调用）
        try:
            from app.core.data_sources import TencentSource
            ts = TencentSource()
            market = ts.get_full_market()
            if market:
                sorted_stocks = sorted(
                    market,
                    key=lambda x: x.get("change_pct", 0),
                    reverse=True
                )[:20]
                for s in sorted_stocks:
                    if s.get("code") and s.get("change_pct", 0) > 0:
                        candidates.append({
                            "code": s["code"],
                            "name": s.get("name", ""),
                            "reason": f"涨幅{s.get('change_pct', 0):.2f}%",
                            "source": "gainers",
                            "suggested_type": "short",
                            "change_pct": round(s.get("change_pct", 0), 2),
                            "amount_wan": round(s.get("amount_wan", 0) or 0, 0),
                            "turnover_pct": round(s.get("turnover_pct", 0) or 0, 2),
                        })

                try:
                    oversold = [
                        s for s in market
                        if -8 <= s.get("change_pct", 0) <= -3
                        and s.get("amount_wan", 0) > 5000
                    ]
                    oversold.sort(key=lambda x: x.get("amount_wan", 0), reverse=True)
                    for s in oversold[:10]:
                        candidates.append({
                            "code": s["code"],
                            "name": s.get("name", ""),
                            "reason": f"超跌{s.get('change_pct', 0):.2f}%",
                            "source": "oversold",
                            "suggested_type": "mid",
                            "change_pct": round(s.get("change_pct", 0), 2),
                            "amount_wan": round(s.get("amount_wan", 0) or 0, 0),
                            "turnover_pct": round(s.get("turnover_pct", 0) or 0, 2),
                        })
                except Exception as e:
                    log.warning(f"获取超跌候选失败: {e}")
        except Exception as e:
            log.warning(f"获取涨幅榜失败: {e}")

        # 方法4：低吸企稳（长线候选）
        try:
            from app.services.strategy_service import StrategyService
            ss = StrategyService()
            if hasattr(ss, "get_low_absorption_picks"):
                low_picks = ss.get_low_absorption_picks(top_n=8)
                if low_picks and low_picks.get("stocks"):
                    for s in low_picks["stocks"][:8]:
                        candidates.append({
                            "code": s.get("code", ""),
                            "name": s.get("name", ""),
                            "reason": "低吸企稳",
                            "source": "low_absorption",
                            "suggested_type": "long",
                        })
        except Exception as e:
            log.warning(f"获取低吸候选失败: {e}")

        # 方法5：多因子综合（中线候选）
        try:
            from app.services.strategy_service import StrategyService
            ss = StrategyService()
            if hasattr(ss, "get_multi_factor_picks"):
                multi = ss.get_multi_factor_picks(top_n=8, exclude_st=True)
                if multi and multi.get("stocks"):
                    for s in multi["stocks"][:8]:
                        candidates.append({
                            "code": s.get("code", ""),
                            "name": s.get("name", ""),
                            "reason": "多因子综合",
                            "source": "multi_factor",
                            "suggested_type": "mid",
                        })
        except Exception as e:
            log.warning(f"获取多因子候选失败: {e}")

        # 去重：多源命中标记为高置信度
        seen: Dict[str, Dict] = {}
        for c in candidates:
            code = c.get("code", "")
            if not code:
                continue
            if code not in seen:
                seen[code] = c
            else:
                seen[code]["reason"] = f"{seen[code]['reason']}+{c['reason']}"
                seen[code]["source"] = f"{seen[code]['source']}+{c['source']}"
                seen[code]["confidence"] = seen[code].get("confidence", 1) + 1

        # 过滤掉用户已持有的股票（避免重复推荐）
        if exclude_codes:
            seen = {k: v for k, v in seen.items() if k not in exclude_codes}

        unique = sorted(
            seen.values(),
            key=lambda x: (x.get("confidence", 1), len(x.get("reason", ""))),
            reverse=True
        )

        return unique[:25]

    # ── 数据采集：持仓风控信息 ────────────────────────────
    @staticmethod
    def _get_position_risk_info(holdings: List[Holding], indicators_map: Dict) -> str:
        """获取持仓止损/止盈价位信息，注入策略 prompt"""
        if not holdings:
            return ""

        lines = ["持仓风控信息:"]
        for h in holdings:
            cost = h.cost_price or 0
            current = h.current_price or 0
            profit = h.profit_ratio or 0
            pos_type = h.position_type or "short"
            thresholds = WatchlistAIStrategyGenerator.POS_THRESHOLDS.get(pos_type, WatchlistAIStrategyGenerator.POS_THRESHOLDS["short"])

            # 计算止损位
            stop_loss_pct = thresholds["stop_loss"]
            stop_loss_price = round(cost * (1 + stop_loss_pct / 100), 2) if cost > 0 else 0
            take_profit_pct = thresholds["take_profit"]
            strong_profit_pct = thresholds["strong_profit"]
            take_profit_price = round(cost * (1 + take_profit_pct / 100), 2) if cost > 0 else 0

            # 持仓天数
            hold_days = 0
            if h.buy_date:
                try:
                    bd = date.fromisoformat(h.buy_date) if isinstance(h.buy_date, str) else h.buy_date
                    hold_days = (date.today() - bd).days
                except Exception:
                    pass

            # 触发提示
            trigger = ""
            if profit <= stop_loss_pct:
                trigger = f" ⚠触发止损线"
            elif profit >= strong_profit_pct:
                trigger = f" ⚠触发强止盈线"
            elif profit >= take_profit_pct:
                trigger = f" ⚠达止盈线"

            lines.append(
                f"  {h.stock_name}({h.stock_code})[{pos_type}]: "
                f"成本{cost:.2f} 现价{current:.2f} 盈亏{profit:+.2f}% "
                f"止损{stop_loss_price:.2f}({stop_loss_pct}%) 止盈{take_profit_price:.2f}({take_profit_pct}%) "
                f"持仓{hold_days}天{trigger}"
            )

        return "\n".join(lines)

    # ── 数据采集：历史策略表现（反馈闭环） ────────────────
    @staticmethod
    def _get_recent_strategy_performance(db: Session, user_id: int, limit: int = 5) -> str:
        """获取最近 N 条策略的表现统计，注入策略 prompt 让 AI 自我修正

        包含：
        1. 建议分布统计（加仓/卖出减仓/持有）
        2. 用户采纳率统计（基于 adopted 字段反馈）
        3. 最近3次策略的市场判断
        """
        try:
            decisions = db.query(WatchlistStrategyDecision).filter(
                WatchlistStrategyDecision.user_id == user_id,
            ).order_by(
                WatchlistStrategyDecision.decision_date.desc(),
                WatchlistStrategyDecision.decision_time.desc(),
            ).limit(limit).all()
            if not decisions:
                return ""

            lines = ["历史策略表现（近{}次）:".format(len(decisions))]

            # 统计建议分布 + 采纳率
            total_buy = total_sell = total_hold = 0
            total_adopted = total_rejected = total_feedback = 0
            for d in decisions:
                try:
                    holdings_sugg = json.loads(d.holdings_suggestions) if d.holdings_suggestions else []
                    watchlist_sugg = json.loads(d.watchlist_suggestions) if d.watchlist_suggestions else []
                    for s in holdings_sugg + watchlist_sugg:
                        action = s.get("action", "")
                        if action in ("add", "buy"):
                            total_buy += 1
                        elif action in ("sell", "reduce"):
                            total_sell += 1
                        elif action in ("hold", "watch"):
                            total_hold += 1
                        # 统计采纳反馈
                        if "adopted" in s:
                            total_feedback += 1
                            if s["adopted"]:
                                total_adopted += 1
                            else:
                                total_rejected += 1
                except Exception:
                    continue

            lines.append(f"  历史建议统计: 加仓/买入{total_buy}次 / 卖出减仓{total_sell}次 / 持有/关注{total_hold}次")

            # 采纳率统计（仅在有反馈数据时显示）
            if total_feedback > 0:
                adoption_rate = round(total_adopted / total_feedback * 100, 1)
                lines.append(f"  用户采纳率: {adoption_rate}% (采纳{total_adopted}/不采纳{total_rejected}/总反馈{total_feedback})")
                if total_rejected > total_adopted:
                    lines.append("  ⚠用户近期不采纳率较高，请反思建议质量，提升专业度和可操作性")

            # 最近3次策略的市场判断
            for d in decisions[:3]:
                try:
                    sentiment = d.market_sentiment or "neutral"
                    sentiment_cn = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}.get(sentiment, sentiment)
                    stage = d.market_stage or "未知"
                    analysis = (d.market_analysis or "")[:60]
                    lines.append(f"  [{d.decision_date} {d.decision_time}] {d.strategy_mode} 情绪={sentiment_cn} 阶段={stage} | {analysis}")
                except Exception:
                    continue

            lines.append("请参考历史判断和用户采纳反馈，避免重复犯错，对当前建议保持一致性或合理调整。")
            return "\n".join(lines)
        except Exception as e:
            log.warning(f"获取历史策略表现失败: {e}")
            return ""

    # ── 动态仓位配置 ────────────────────────────────────
    @staticmethod
    def _calc_dynamic_position(market_data: Dict, holdings_data: List[Dict]) -> Dict:
        """根据市场情绪+涨跌家数自适应调整仓位上限"""
        sentiment = market_data.get("sentiment", "neutral")
        breadth = market_data.get("breadth", {})
        up_count = breadth.get("up", 0) or 0
        down_count = breadth.get("down", 0) or 0

        if sentiment == "bullish" and up_count > down_count * 2:
            dynamic_max_position_ratio = 0.80
            suggested_allocation = {"short": 30, "mid": 30, "long": 20}
            market_stage = "牛市(强势)"
        elif sentiment == "bearish" or (down_count > up_count * 1.5 and up_count > 0):
            dynamic_max_position_ratio = 0.45
            suggested_allocation = {"short": 10, "mid": 15, "long": 20}
            market_stage = "熊市(弱势)"
        else:
            dynamic_max_position_ratio = 0.60
            suggested_allocation = {"short": 20, "mid": 25, "long": 25}
            market_stage = "震荡市"

        # 当前持仓总市值占比估算（仅用于提示）
        total_market_value = sum(h.get("market_value", 0) for h in holdings_data) if holdings_data else 0

        return {
            "dynamic_max_position_ratio": dynamic_max_position_ratio,
            "suggested_allocation": suggested_allocation,
            "market_stage": market_stage,
            "up_count": up_count,
            "down_count": down_count,
            "sentiment": sentiment,
            "total_market_value": total_market_value,
        }

    # ── 构建用户提示词 ────────────────────────────────────
    @staticmethod
    def _build_user_prompt(
        mode: str,
        holdings_data: List[Dict],
        holdings_indicators: Dict,
        watchlist_data: List[Dict],
        watchlist_indicators: Dict,
        market_data: Dict,
        market_extra: Dict,
        dragon_summary: str,
        sector_rotation: str,
        hot_stocks: List[Dict],
        position_risk_text: str,
        recent_performance: str,
        dynamic_position: Dict,
    ) -> str:
        """构建用户提示词（注入多维数据）"""
        mode_label = WatchlistAIStrategyGenerator.MODE_LABELS.get(mode, mode)

        # 持仓分析（含实时价格 + 技术指标）
        holdings_text = ""
        if holdings_data:
            lines = []
            for h in holdings_data:
                status = "盈利" if h["profit"] > 0 else "亏损"
                change_info = f", 今日{h.get('change_pct', 0):+.2f}%" if h.get('change_pct') is not None else ""
                # 技术指标摘要
                ind = holdings_indicators.get(h['code'], {})
                tech_info = ""
                if ind:
                    macd_sig = ind.get('MACD_SIGNAL', '')
                    kdj_sig = ind.get('KDJ_SIGNAL', '')
                    rsi_sig = ind.get('RSI_SIGNAL', '')
                    boll_sig = ind.get('BOLL_SIGNAL', '')
                    vol_sig = ind.get('VOL_SIGNAL', '')
                    ma5 = ind.get('MA5')
                    ma20 = ind.get('MA20')
                    ma_info = f" MA5={ma5:.2f}/MA20={ma20:.2f}" if ma5 and ma20 else ""
                    tech_info = f" | 技术: {macd_sig}/{kdj_sig}/{rsi_sig}/{boll_sig}/{vol_sig}{ma_info}"
                lines.append(
                    f"- {h['name']}({h['code']})[{h['position_type']}]: {status}{abs(h['profit_ratio']):.2f}%, "
                    f"成本{h['cost_price']:.2f}, 现价{h['current_price']:.2f}"
                    f"{change_info}, 持仓{h['quantity']}股, 买入日{h.get('buy_date', '未知')}, 持仓{h.get('hold_days', 0)}天{tech_info}"
                )
            holdings_text = "\n".join(lines)
        else:
            holdings_text = "暂无持仓"

        # 自选股列表（含实时价格 + 技术指标）
        watchlist_text = ""
        if watchlist_data:
            lines = []
            for w in watchlist_data:
                price_info = f", 现价{w['current_price']:.2f}" if w.get('current_price') and w['current_price'] > 0 else ""
                change_info = f" ({w['change_pct']:+.2f}%)" if w.get('change_pct') is not None else ""
                # 技术指标摘要
                ind = watchlist_indicators.get(w['code'], {})
                tech_info = ""
                if ind:
                    macd_sig = ind.get('MACD_SIGNAL', '')
                    kdj_sig = ind.get('KDJ_SIGNAL', '')
                    rsi_sig = ind.get('RSI_SIGNAL', '')
                    ma5 = ind.get('MA5')
                    ma20 = ind.get('MA20')
                    ma_info = f" MA5={ma5:.2f}/MA20={ma20:.2f}" if ma5 and ma20 else ""
                    tech_info = f" | {macd_sig}/{kdj_sig}/{rsi_sig}{ma_info}"
                lines.append(f"- {w['name']}({w['code']}) [{w['group']}]{price_info}{change_info}{tech_info}")
            watchlist_text = "\n".join(lines)
        else:
            watchlist_text = "暂无自选股"

        # 指数信息
        indices_raw = market_data.get("indices", {})
        indices_list = list(indices_raw.values())[:3] if isinstance(indices_raw, dict) else []
        indices_str = "、".join(
            [f"{v.get('name', '')} {v.get('change_pct', 0):.2f}%"
             for v in indices_list if isinstance(v, dict)]
        ) if indices_list else "暂无"

        # 板块排名
        sectors_str = ""
        sectors = market_extra.get("sectors", [])
        if sectors:
            sector_lines = []
            for s in sectors[:5]:
                if isinstance(s, dict):
                    sector_lines.append(
                        f"  {s.get('name', '')} 涨跌{s.get('change_pct', 0):+.2f}% 领涨股: {s.get('leader', '')}"
                    )
            sectors_str = "\n".join(sector_lines)

        # 北向资金
        northbound_str = market_extra.get("northbound", "暂无")

        # 候选股票池
        hot_stocks_text = ""
        if hot_stocks:
            hs_lines = []
            for s in hot_stocks[:15]:
                # 包含成交额/换手率信息（如可用）
                extra = ""
                amount = s.get("amount_wan")
                turnover = s.get("turnover_pct")
                if amount and amount > 0:
                    # 转换为亿元展示
                    amount_yi = amount / 10000
                    extra = f" 成交额{amount_yi:.2f}亿"
                if turnover and turnover > 0:
                    extra += f" 换手{turnover:.1f}%"
                hs_lines.append(
                    f"  {s.get('code', '')} {s.get('name', '')} [{s.get('suggested_type', '')}] "
                    f"{s.get('reason', '')} (来源:{s.get('source', '')}){extra}"
                )
            hot_stocks_text = "\n".join(hs_lines)
        else:
            hot_stocks_text = "暂无候选"

        # 动态仓位文本
        dp = dynamic_position
        dynamic_position_text = f"""## 动态仓位配置（基于市场情绪，AI 必须遵守）
当前市场判定: {dp['market_stage']}, 涨{dp['up_count']}/跌{dp['down_count']}, 情绪={dp['sentiment']}
- 总仓位上限: {dp['dynamic_max_position_ratio']*100:.0f}%
- 建议周期配置: 短线{dp['suggested_allocation']['short']}% + 中线{dp['suggested_allocation']['mid']}% + 长线{dp['suggested_allocation']['long']}%
- 现金保留: {(1-dp['dynamic_max_position_ratio'])*100:.0f}%（应对突发风险）
- 单日新建仓: 短线不超过 3 只，中长线不超过 2 只"""

        prompt = f"""当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
策略模式: {mode_label}

## 市场概况
市场情绪: {market_data.get('sentiment', 'neutral')}
主要指数: {indices_str}
市场宽度: 上涨{dp['up_count']}家 / 下跌{dp['down_count']}家

## 板块热度
{sectors_str or '暂无'}

## 北向资金
{northbound_str}

## 龙虎榜摘要
{dragon_summary or '暂无'}

## 板块轮动
{sector_rotation or '暂无'}

{dynamic_position_text}

## 持仓股票
{holdings_text}

## 持仓风控信息
{position_risk_text or '暂无'}

## 自选股列表
{watchlist_text}

## 候选股票池（多源热门，AI 可推荐用户加入自选股）
{hot_stocks_text}

## 历史策略表现
{recent_performance or '暂无历史数据'}

请综合以上数据，分别为持仓股票和自选股提供专业投资建议。
要求：
1. 每条建议必须给出 position_type（short/mid/long）和明确的止损止盈价位
2. **每条建议的 reason 必须是详细的深度分析**（2-4句话），覆盖：技术面现状（MA/量价/信号）+ 资金面/板块背景 + 操作逻辑 + 关键价位，不要空泛地说"技术面良好"
3. 严格遵守动态仓位配置上限
4. 持仓建议必须覆盖所有持仓股票
5. 自选股建议可包含候选股票池中的标的（推荐用户加入自选股）
6. 同一股票不能同时在持仓建议和自选股建议中出现
7. 板块分散：买入建议中单一行业集中度不超过 30%，如候选标的板块过度集中请主动分散
8. 优先推荐候选股票池中多源命中（confidence 高）的标的
9. market_analysis 和 position_analysis 要用完整段落写，不要只是关键词堆砌
10. 持仓建议中的 "持有" 也需要给出理由（为什么继续持有，预期什么），不能简单写"暂时持有"即可"""
        return prompt

    # ── LLM 响应解析 ────────────────────────────────────
    @staticmethod
    def _parse_llm_response(llm_response: str) -> Optional[Dict]:
        """解析LLM响应，支持代码块和{}容错提取"""
        try:
            json_str = llm_response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
            first_brace = json_str.find('{')
            last_brace = json_str.rfind('}')
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                json_str = json_str[first_brace:last_brace + 1]

            strategy_data = json.loads(json_str.strip())

            if not isinstance(strategy_data, dict):
                return None

            # 确保必要字段存在
            if "holdings_suggestions" not in strategy_data:
                strategy_data["holdings_suggestions"] = []
            if "watchlist_suggestions" not in strategy_data:
                strategy_data["watchlist_suggestions"] = []

            return strategy_data
        except json.JSONDecodeError as e:
            log.warning(f"LLM响应JSON解析失败: {e}")
            return None

    # ── 结果校验 ────────────────────────────────────────
    @staticmethod
    def _validate_strategy_data(
        strategy_data: Dict,
        held_codes: Set[str],
        valid_watchlist_codes: Set[str],
        holdings_map: Dict[str, Dict] = None,
        dynamic_max_position_pct: float = 60.0,
    ) -> Dict:
        """校验 LLM 输出：股票代码合法性 + 枚举值合法性 + 合理性校验

        Args:
            holdings_map: 持仓代码到数据的映射，用于价格方向性校验
            dynamic_max_position_pct: 动态仓位上限（百分比），position_ratio 不能超过此值
        """
        holdings_map = holdings_map or {}

        # 顶层字段默认值
        strategy_data.setdefault("market_sentiment", "neutral")
        if strategy_data["market_sentiment"] not in ("bullish", "bearish", "neutral"):
            strategy_data["market_sentiment"] = "neutral"

        strategy_data.setdefault("position_ratio", 60)
        try:
            position_ratio = float(strategy_data["position_ratio"])
            # 仓位合理性校验：不超过动态上限，不超过100，不小于0
            if position_ratio > dynamic_max_position_pct:
                log.warning(f"AI 建议仓位 {position_ratio}% 超过动态上限 {dynamic_max_position_pct}%，已截断")
                position_ratio = dynamic_max_position_pct
            if position_ratio > 100:
                position_ratio = 100
            if position_ratio < 0:
                position_ratio = 0
        except (ValueError, TypeError):
            position_ratio = min(60, dynamic_max_position_pct)
        strategy_data["position_ratio"] = position_ratio

        # 校验持仓建议
        valid_holdings = []
        for item in strategy_data.get("holdings_suggestions", []):
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip()
            if not code:
                continue
            # 股票代码必须在持仓中
            if code not in held_codes:
                log.warning(f"AI 建议的持仓 {code} 不在实际持仓中，已移除")
                continue
            # action 枚举校验
            action = item.get("action", "hold")
            if action not in WatchlistAIStrategyGenerator.VALID_HOLDINGS_ACTIONS:
                log.warning(f"AI 持仓建议 action={action} 非法，已默认 hold")
                action = "hold"
            item["action"] = action
            # risk_level 枚举校验
            risk = item.get("risk_level", "medium")
            if risk not in WatchlistAIStrategyGenerator.VALID_RISK_LEVELS:
                risk = "medium"
            item["risk_level"] = risk
            # position_type 枚举校验
            pos_type = item.get("position_type", "short")
            if pos_type not in WatchlistAIStrategyGenerator.VALID_POSITION_TYPES:
                pos_type = "short"
            item["position_type"] = pos_type

            # ── 价格方向性校验（基于持仓现价）──
            holding = holdings_map.get(code, {})
            current_price = holding.get("current_price", 0) or 0
            if current_price > 0:
                # 止损价应低于现价（卖出/减仓/持有时）
                stop_loss = WatchlistAIStrategyGenerator._safe_float(item.get("stop_loss"))
                if stop_loss is not None and stop_loss >= current_price and action in ("sell", "reduce", "hold"):
                    log.warning(f"AI 持仓 {code} 止损价 {stop_loss} ≥ 现价 {current_price}，已移除止损价")
                    item.pop("stop_loss", None)
                # 目标价应高于现价（加仓时）
                target_price = WatchlistAIStrategyGenerator._safe_float(item.get("target_price"))
                if target_price is not None and target_price <= current_price and action == "add":
                    log.warning(f"AI 持仓 {code} 目标价 {target_price} ≤ 现价 {current_price}，已移除目标价")
                    item.pop("target_price", None)

            valid_holdings.append(item)
        strategy_data["holdings_suggestions"] = valid_holdings

        # 校验自选股建议
        valid_watchlist = []
        for item in strategy_data.get("watchlist_suggestions", []):
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip()
            if not code:
                continue
            # 自选股代码必须在自选股或候选股票池中
            if code not in valid_watchlist_codes:
                log.warning(f"AI 建议的自选股 {code} 不在自选股/候选池中，已移除")
                continue
            action = item.get("action", "watch")
            if action not in WatchlistAIStrategyGenerator.VALID_WATCHLIST_ACTIONS:
                log.warning(f"AI 自选股建议 action={action} 非法，已默认 watch")
                action = "watch"
            item["action"] = action
            risk = item.get("risk_level", "medium")
            if risk not in WatchlistAIStrategyGenerator.VALID_RISK_LEVELS:
                risk = "medium"
            item["risk_level"] = risk
            pos_type = item.get("position_type", "short")
            if pos_type not in WatchlistAIStrategyGenerator.VALID_POSITION_TYPES:
                pos_type = "short"
            item["position_type"] = pos_type

            # ── 价格方向性校验（买入建议）──
            entry_price = WatchlistAIStrategyGenerator._safe_float(item.get("entry_price"))
            target_price = WatchlistAIStrategyGenerator._safe_float(item.get("target_price"))
            if entry_price is not None and target_price is not None and action == "buy":
                # 目标价应高于入场价
                if target_price <= entry_price:
                    log.warning(f"AI 自选股 {code} 目标价 {target_price} ≤ 入场价 {entry_price}，已移除目标价")
                    item.pop("target_price", None)

            valid_watchlist.append(item)

        # ── 建议数量限制（防止 AI 输出过多建议）──
        # 持仓建议最多 15 条（一般用户持仓不会超过此数）
        if len(valid_holdings) > 15:
            log.warning(f"持仓建议数量 {len(valid_holdings)} 超过上限 15，已截断")
            valid_holdings = valid_holdings[:15]
        # 自选股建议最多 20 条（避免信息过载）
        if len(valid_watchlist) > 20:
            log.warning(f"自选股建议数量 {len(valid_watchlist)} 超过上限 20，已截断")
            valid_watchlist = valid_watchlist[:20]

        # ── 建议排序（按操作重要性）──
        # 持仓建议：卖出 > 减仓 > 加仓 > 持有
        holdings_order = {"sell": 0, "reduce": 1, "add": 2, "hold": 3}
        valid_holdings.sort(key=lambda x: holdings_order.get(x.get("action", "hold"), 99))
        # 自选股建议：买入 > 关注；同操作内按风险等级升序（低风险优先）
        watchlist_order = {"buy": 0, "watch": 1}
        risk_order = {"low": 0, "medium": 1, "high": 2}
        valid_watchlist.sort(key=lambda x: (
            watchlist_order.get(x.get("action", "watch"), 99),
            risk_order.get(x.get("risk_level", "medium"), 99),
        ))

        strategy_data["holdings_suggestions"] = valid_holdings
        strategy_data["watchlist_suggestions"] = valid_watchlist

        return strategy_data

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """安全转换为 float，失败返回 None"""
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


def generate_watchlist_strategy_for_scheduler(db: Session, user_id: int, mode: str) -> Dict[str, Any]:
    """定时任务调用的策略生成函数

    Args:
        db: 数据库会话
        user_id: 用户ID
        mode: 策略模式
    """
    return WatchlistAIStrategyGenerator.generate_strategy(
        db=db,
        user_id=user_id,
        mode=mode,
        source="auto",
    )
