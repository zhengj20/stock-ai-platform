"""模拟交易复盘系统 - 每日复盘、策略评估、明日计划"""
import asyncio
import json
import logging
from datetime import datetime, date
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.sim_trading import (
    SimDailyReview, SimTrade, SimPosition, SimDailyPnl, AIStrategyDecision,
)
from app.services.market_service import MarketService
from app.core.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

# 复盘缓存命名空间
NS_REVIEW = "sim_review"
# 复盘缓存TTL：24小时（复盘数据生成后当天不变）
REVIEW_CACHE_TTL = 86400


# ── LLM 同步调用辅助 ──────────────────────────────────────────────

def _call_llm_sync(system_prompt: str, user_prompt: str) -> str:
    """同步调用LLM（从同步上下文调用异步的 llm_client.chat_completion）。

    遵循 ai_strategy_generator.py 中的调用模式。
    """
    from app.core.llm_service import llm_config, llm_client

    if not llm_config.enabled:
        raise RuntimeError("LLM服务未启用，请先在设置中配置LM Studio连接")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = asyncio.run(
        llm_client.chat_completion(messages=messages, stream=False)
    )
    return result.get("content", "")


# ── 数据采集辅助 ──────────────────────────────────────────────────

def _get_daily_trades(db: Session, account_id: int, review_date: str) -> List[SimTrade]:
    """获取指定日期的交易记录"""
    return db.query(SimTrade).filter(
        and_(
            SimTrade.account_id == account_id,
            SimTrade.trade_date == review_date,
        )
    ).order_by(SimTrade.trade_time).all()


def _get_daily_pnl(db: Session, account_id: int, review_date: str) -> Optional[SimDailyPnl]:
    """获取指定日期的盈亏记录"""
    return db.query(SimDailyPnl).filter(
        and_(
            SimDailyPnl.account_id == account_id,
            SimDailyPnl.trade_date == review_date,
        )
    ).first()


def _get_positions(db: Session, account_id: int) -> List[SimPosition]:
    """获取当前所有持仓"""
    return db.query(SimPosition).filter(
        SimPosition.account_id == account_id,
        SimPosition.total_quantity > 0,
    ).all()


def _get_market_sentiment() -> Dict[str, Any]:
    """获取市场情绪数据"""
    try:
        ms = MarketService()
        return ms.get_market_sentiment(include_flow=False) or {}
    except Exception as e:
        logger.warning(f"获取市场情绪失败: {e}")
        return {}


def _get_strategy_decision(db: Session, account_id: int, review_date: str) -> Optional[AIStrategyDecision]:
    """获取当日AI策略决策"""
    return db.query(AIStrategyDecision).filter(
        and_(
            AIStrategyDecision.account_id == account_id,
            AIStrategyDecision.decision_date == review_date,
        )
    ).first()


def _positions_to_dict_list(positions: List[SimPosition]) -> List[Dict]:
    """将持仓对象列表转换为字典列表"""
    return [
        {
            "code": p.stock_code,
            "name": p.stock_name,
            "quantity": p.total_quantity,
            "available": p.available_quantity,
            "cost_price": round(p.cost_price, 3),
            "current_price": round(p.current_price, 3),
            "market_value": round(p.market_value, 2),
            "profit": round(p.profit, 2),
            "profit_ratio": round(p.profit_ratio, 2),
            "position_type": p.position_type,
            "buy_date": p.buy_date,
        }
        for p in positions
    ]


# ── 核心复盘系统 ──────────────────────────────────────────────────

def generate_daily_review(
    db: Session, account_id: int, review_date: str
) -> Dict[str, Any]:
    """生成每日复盘报告。

    流程：
    1. 采集当日交易记录、盈亏数据、持仓状态、市场情绪
    2. 调用LLM生成复盘报告
    3. 保存到 SimDailyReview

    Args:
        db: 数据库会话
        account_id: 模拟交易账户ID
        review_date: 复盘日期，格式 YYYY-MM-DD

    Returns:
        复盘结果字典，包含 success 状态和复盘数据
    """
    # 1. 采集数据
    trades = _get_daily_trades(db, account_id, review_date)
    daily_pnl = _get_daily_pnl(db, account_id, review_date)
    positions = _get_positions(db, account_id)
    sentiment = _get_market_sentiment()

    # 2. 交易统计
    buy_trades = [t for t in trades if t.trade_type == "buy"]
    sell_trades = [t for t in trades if t.trade_type == "sell"]
    win_count = sum(1 for t in sell_trades if t.profit and t.profit > 0)
    loss_count = sum(1 for t in sell_trades if t.profit and t.profit <= 0)
    total_trades_count = len(trades)
    win_rate = round(win_count / len(sell_trades) * 100, 1) if sell_trades else 0.0

    # 3. 盈亏数据
    daily_profit = daily_pnl.daily_profit if daily_pnl else 0.0
    total_profit = daily_pnl.total_assets - daily_pnl.initial_capital if daily_pnl else 0.0
    total_profit_ratio = daily_pnl.total_profit_ratio if daily_pnl else 0.0

    # 4. 构建LLM上下文
    positions_dict = _positions_to_dict_list(positions)
    position_count = len(positions_dict)

    trades_summary = ""
    if trades:
        lines = []
        for t in trades:
            direction = "买入" if t.trade_type == "buy" else "卖出"
            profit_str = ""
            if t.trade_type == "sell" and t.profit is not None:
                profit_str = f", 盈亏={t.profit:+.2f}元({t.profit_ratio:+.2f}%)"
            lines.append(
                f"  {t.trade_time or '--'} {direction} {t.stock_name}({t.stock_code}) "
                f"× {t.trade_quantity}股 @ {t.trade_price:.2f}元"
                f"{profit_str} 策略={t.strategy_name or '无'}"
            )
        trades_summary = "\n".join(lines)
    else:
        trades_summary = "  无交易"

    positions_summary = ""
    if positions_dict:
        lines = []
        for p in positions_dict:
            lines.append(
                f"  {p['name']}({p['code']}) {p['quantity']}股 成本{p['cost_price']:.3f} "
                f"现价{p['current_price']:.3f} 盈亏{p['profit']:+.2f}元({p['profit_ratio']:+.2f}%) "
                f"类型={p['position_type']}"
            )
        positions_summary = "\n".join(lines)
    else:
        positions_summary = "  无持仓"

    # 5. 市场情绪摘要
    indices = sentiment.get("indices", {})
    breadth = sentiment.get("breadth", {})
    market_summary_parts = []
    if indices:
        for code in ["000001", "399001", "399006"]:
            idx = indices.get(code)
            if idx:
                market_summary_parts.append(
                    f"{idx.get('name', code)} {idx.get('price', 0)} ({idx.get('change_pct', 0):+.2f}%)"
                )
    if breadth:
        market_summary_parts.append(
            f"涨{breadth.get('up', 0)}/跌{breadth.get('down', 0)}/平{breadth.get('flat', 0)}"
        )
        market_summary_parts.append(
            f"涨停{breadth.get('limit_up', 0)}/跌停{breadth.get('limit_down', 0)}"
        )
    market_summary = " | ".join(market_summary_parts) if market_summary_parts else "暂无市场数据"

    # 5a. 策略 vs 实际执行对比
    strategy_comparison = ""
    strategy_decision = _get_strategy_decision(db, account_id, review_date)
    if strategy_decision:
        strategy_buy_list = json.loads(strategy_decision.buy_list or "[]")
        strategy_sell_list = json.loads(strategy_decision.sell_list or "[]")

        actual_buy_codes = {t.stock_code for t in buy_trades}
        actual_sell_codes = {t.stock_code for t in sell_trades}

        lines = []
        lines.append(f"策略模式: {strategy_decision.strategy_mode or 'intraday'}, 执行状态: {strategy_decision.execution_status}")
        lines.append(f"市场情绪: {strategy_decision.market_sentiment or 'neutral'}, 建议仓位: {strategy_decision.position_ratio}%")

        if strategy_buy_list:
            planned_buy_codes = {b.get("code", "") for b in strategy_buy_list}
            executed = planned_buy_codes & actual_buy_codes
            missed = planned_buy_codes - actual_buy_codes
            lines.append(f"买入计划: {len(planned_buy_codes)}只, 已执行: {len(executed)}只, 未执行: {len(missed)}只")
            if missed:
                missed_names = [b.get("name", b.get("code", "")) for b in strategy_buy_list if b.get("code") in missed]
                lines.append(f"  未执行: {', '.join(missed_names)}")

        if strategy_sell_list:
            planned_sell_codes = {s.get("stock_code", "") for s in strategy_sell_list}
            executed = planned_sell_codes & actual_sell_codes
            missed = planned_sell_codes - actual_sell_codes
            lines.append(f"卖出计划: {len(planned_sell_codes)}只, 已执行: {len(executed)}只, 未执行: {len(missed)}只")

        lines.append(f"实际买入: {len(buy_trades)}笔, 实际卖出: {len(sell_trades)}笔")
        strategy_comparison = "\n".join(lines)

    # 6. 调用LLM生成复盘报告
    system_prompt = (
        "你是A股模拟交易复盘分析师。请基于当日交易数据、策略决策与实际执行的对比、"
        "持仓状态和市场情绪，生成专业的每日复盘报告。\n\n"
        "报告需包含以下部分：\n"
        "1. 交易总结：对当日所有交易的回顾和评价\n"
        "2. 策略执行评估：对比策略计划与实际执行，分析偏差原因\n"
        "3. 市场分析：当日市场环境对交易决策的影响\n"
        "4. 经验教训：做得好和需要改进的地方\n"
        "5. 策略建议：后续交易策略调整建议\n\n"
        "要求：语言简洁专业，分析深入客观，每部分50-150字。"
    )

    user_prompt = f"""日期: {review_date}

## 盈亏数据
- 当日盈亏: {daily_profit:+.2f}元
- 累计盈亏: {total_profit:+.2f}元 ({total_profit_ratio:+.2f}%)
- 交易次数: {total_trades_count}笔 (买入{len(buy_trades)}笔, 卖出{len(sell_trades)}笔)
- 盈利笔数: {win_count}, 亏损笔数: {loss_count}, 胜率: {win_rate}%

## 当日交易
{trades_summary}

## 当前持仓 ({position_count}只)
{positions_summary}

## 市场情绪
{market_summary}

## 策略 vs 实际执行对比
{strategy_comparison if strategy_comparison else '当日无AI策略决策'}

请生成复盘报告。"""

    ai_review = ""
    try:
        ai_review = _call_llm_sync(system_prompt, user_prompt)
        # 去除可能的markdown代码块标记
        if ai_review.startswith("```"):
            ai_review = ai_review.strip("`").strip()
            if "\n" in ai_review:
                first_newline = ai_review.index("\n")
                ai_review = ai_review[first_newline + 1:].strip()
    except Exception as e:
        logger.warning(f"LLM复盘生成失败，使用基础摘要: {e}")
        ai_review = (
            f"## {review_date} 交易复盘\n\n"
            f"当日盈亏 {daily_profit:+.2f}元，累计盈亏 {total_profit:+.2f}元。"
            f"共{total_trades_count}笔交易，胜率{win_rate}%。"
            f"当前持有{position_count}只股票。\n\n"
            f"> AI复盘生成失败（{type(e).__name__}），以上为基础数据摘要。"
        )

    # 7. 解析复盘报告中的各部分（从AI报告中提取子章节）
    trade_summary_text = _extract_section(ai_review, "交易总结")
    market_analysis_text = _extract_section(ai_review, "市场分析")
    lessons_text = _extract_section(ai_review, "经验教训")

    # 8. 获取或创建复盘记录（支持更新）
    review = db.query(SimDailyReview).filter(
        and_(
            SimDailyReview.account_id == account_id,
            SimDailyReview.review_date == review_date,
        )
    ).first()

    if review:
        # 更新已有记录
        review.daily_pnl = daily_profit
        review.total_pnl = total_profit
        review.total_pnl_ratio = total_profit_ratio
        review.total_trades = total_trades_count
        review.win_count = win_count
        review.loss_count = loss_count
        review.win_rate = win_rate
        review.position_count = position_count
        review.position_details = json.dumps(positions_dict, ensure_ascii=False)
        review.trade_summary = trade_summary_text
        review.market_analysis = market_analysis_text
        review.lessons = lessons_text
        review.ai_review = ai_review
    else:
        review = SimDailyReview(
            account_id=account_id,
            review_date=review_date,
            daily_pnl=daily_profit,
            total_pnl=total_profit,
            total_pnl_ratio=total_profit_ratio,
            total_trades=total_trades_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=win_rate,
            position_count=position_count,
            position_details=json.dumps(positions_dict, ensure_ascii=False),
            trade_summary=trade_summary_text,
            market_analysis=market_analysis_text,
            lessons=lessons_text,
            ai_review=ai_review,
        )
        db.add(review)

    db.commit()
    db.refresh(review)

    # 9. 清除相关缓存
    _cache_delete_keys(
        f"review:{account_id}:{review_date}",
        f"review_history:{account_id}",
    )

    return {
        "success": True,
        "review_id": review.id,
        "review_date": review_date,
        "daily_pnl": daily_profit,
        "total_pnl": total_profit,
        "total_pnl_ratio": total_profit_ratio,
        "total_trades": total_trades_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "position_count": position_count,
        "ai_review": ai_review,
    }


def calculate_strategy_accuracy(
    db: Session, account_id: int, review_date: str
) -> Dict[str, Any]:
    """计算当日策略准确度。

    对比 AI策略决策（AIStrategyDecision）与实际交易记录，
    评估策略建议的执行情况和准确性。

    流程：
    1. 获取当日AI策略决策（买入建议、卖出建议）
    2. 获取当日实际交易记录
    3. 逐项对比，计算准确度

    Args:
        db: 数据库会话
        account_id: 模拟交易账户ID
        review_date: 评估日期，格式 YYYY-MM-DD

    Returns:
        策略准确度结果字典
    """
    decision = _get_strategy_decision(db, account_id, review_date)
    trades = _get_daily_trades(db, account_id, review_date)

    if not decision:
        return {
            "success": True,
            "has_decision": False,
            "accuracy": None,
            "message": "当日无AI策略决策记录",
        }

    # 1. 解析策略建议的买入/卖出列表
    strategy_buy_list = json.loads(decision.buy_list or "[]")
    strategy_sell_list = json.loads(decision.sell_list or "[]")

    # 2. 获取实际交易
    actual_buys = [t for t in trades if t.trade_type == "buy"]
    actual_sells = [t for t in trades if t.trade_type == "sell"]

    # 3. 计算买入执行率：策略建议的买入中，实际执行了多少
    strategy_buy_codes = {item.get("code", "") for item in strategy_buy_list}
    actual_buy_codes = {t.stock_code for t in actual_buys}

    if strategy_buy_codes:
        buy_executed = strategy_buy_codes & actual_buy_codes
        buy_execution_rate = round(
            len(buy_executed) / len(strategy_buy_codes) * 100, 1
        )
    else:
        buy_executed = set()
        buy_execution_rate = 0.0

    # 4. 计算卖出执行率：策略建议的卖出中，实际执行了多少
    strategy_sell_codes = {item.get("stock_code", "") for item in strategy_sell_list}
    actual_sell_codes = {t.stock_code for t in actual_sells}

    if strategy_sell_codes:
        sell_executed = strategy_sell_codes & actual_sell_codes
        sell_execution_rate = round(
            len(sell_executed) / len(strategy_sell_codes) * 100, 1
        )
    else:
        sell_executed = set()
        sell_execution_rate = 0.0

    # 5. 计算买入建议准确率：策略建议买入的股票，实际是否盈利
    buy_accuracy_items = []
    for code in strategy_buy_codes:
        # 查找该股票的卖出记录
        sell_for_code = [t for t in actual_sells if t.stock_code == code]
        if sell_for_code:
            latest_sell = sell_for_code[-1]
            if latest_sell.profit is not None:
                buy_accuracy_items.append({
                    "code": code,
                    "executed": code in actual_buy_codes,
                    "profit": latest_sell.profit,
                    "profit_ratio": latest_sell.profit_ratio,
                    "is_win": latest_sell.profit > 0,
                })
        else:
            # 尚未卖出，标记为持仓中
            buy_accuracy_items.append({
                "code": code,
                "executed": code in actual_buy_codes,
                "profit": None,
                "profit_ratio": None,
                "is_win": None,
                "status": "holding",
            })

    # 计算已平仓建议的胜率
    closed_items = [i for i in buy_accuracy_items if i.get("profit") is not None]
    strategy_win_count = sum(1 for i in closed_items if i["is_win"])
    strategy_win_rate = (
        round(strategy_win_count / len(closed_items) * 100, 1)
        if closed_items else None
    )

    # 6. 计算实际交易胜率（全部卖出交易）
    actual_win_count = sum(1 for t in actual_sells if t.profit and t.profit > 0)
    actual_win_rate = (
        round(actual_win_count / len(actual_sells) * 100, 1)
        if actual_sells else None
    )

    # 7. 综合准确度评分
    # 买入执行率20%，卖出执行率10%，策略胜率40%，盈利因子30%
    accuracy_components = []
    accuracy_score = 0.0

    # 买入执行率权重 20%
    accuracy_components.append({
        "name": "买入执行率",
        "value": buy_execution_rate,
        "weight": 0.2,
        "detail": f"{len(buy_executed)}/{len(strategy_buy_codes)}",
    })
    accuracy_score += buy_execution_rate * 0.2

    # 卖出执行率权重 10%
    accuracy_components.append({
        "name": "卖出执行率",
        "value": sell_execution_rate,
        "weight": 0.1,
        "detail": f"{len(sell_executed)}/{len(strategy_sell_codes)}",
    })
    accuracy_score += sell_execution_rate * 0.1

    # 策略建议胜率权重 40%
    strategy_wr = strategy_win_rate if strategy_win_rate is not None else actual_win_rate
    accuracy_components.append({
        "name": "策略胜率",
        "value": strategy_wr,
        "weight": 0.4,
        "detail": f"{strategy_win_count}/{len(closed_items)}" if closed_items else "无已平仓数据",
    })
    accuracy_score += (strategy_wr or 0) * 0.4

    # 盈利因子权重 30%（盈亏比映射到 0-100，1:1=50分，3:1=100分）
    total_profit = sum(t.profit for t in actual_sells if t.profit and t.profit > 0)
    total_loss = abs(sum(t.profit for t in actual_sells if t.profit and t.profit < 0))
    if total_loss > 0:
        profit_factor = min(100, max(0, 50 + (total_profit / total_loss - 1) * 25))
    elif total_profit > 0:
        profit_factor = 100.0
    else:
        profit_factor = 50.0
    accuracy_components.append({
        "name": "盈利因子",
        "value": round(profit_factor, 1),
        "weight": 0.3,
        "detail": f"盈{total_profit:.0f}/亏{total_loss:.0f}",
    })
    accuracy_score += profit_factor * 0.3

    accuracy_score = round(accuracy_score, 1)

    # 8. 更新复盘记录中的策略准确度
    review = db.query(SimDailyReview).filter(
        and_(
            SimDailyReview.account_id == account_id,
            SimDailyReview.review_date == review_date,
        )
    ).first()

    if review:
        review.strategy_accuracy = accuracy_score
        review.strategy_name = "AI策略"
        db.commit()

    return {
        "success": True,
        "has_decision": True,
        "accuracy": accuracy_score,
        "components": accuracy_components,
        "buy_analysis": {
            "strategy_count": len(strategy_buy_codes),
            "executed_count": len(buy_executed),
            "execution_rate": buy_execution_rate,
            "details": buy_accuracy_items,
        },
        "sell_analysis": {
            "strategy_count": len(strategy_sell_codes),
            "executed_count": len(sell_executed),
            "execution_rate": sell_execution_rate,
        },
        "actual_trades": {
            "total": len(trades),
            "buy_count": len(actual_buys),
            "sell_count": len(actual_sells),
            "win_count": actual_win_count,
            "win_rate": actual_win_rate,
        },
    }


def get_daily_review(
    db: Session, account_id: int, review_date: str
) -> Optional[Dict[str, Any]]:
    """获取指定日期的复盘报告。

    优先从缓存读取，缓存未命中时查询数据库。

    Args:
        db: 数据库会话
        account_id: 模拟交易账户ID
        review_date: 复盘日期，格式 YYYY-MM-DD

    Returns:
        复盘报告字典，不存在时返回 None
    """
    # 1. 尝试缓存
    cache_key = f"review:{account_id}:{review_date}"
    cached = cache_get(cache_key, NS_REVIEW)
    if cached:
        return cached

    # 2. 查询数据库
    review = db.query(SimDailyReview).filter(
        and_(
            SimDailyReview.account_id == account_id,
            SimDailyReview.review_date == review_date,
        )
    ).first()

    if not review:
        return None

    result = {
        "id": review.id,
        "review_date": review.review_date,
        "daily_pnl": review.daily_pnl,
        "total_pnl": review.total_pnl,
        "total_pnl_ratio": review.total_pnl_ratio,
        "total_trades": review.total_trades,
        "win_count": review.win_count,
        "loss_count": review.loss_count,
        "win_rate": review.win_rate,
        "strategy_accuracy": review.strategy_accuracy,
        "strategy_name": review.strategy_name,
        "position_count": review.position_count,
        "position_details": _safe_json_loads(review.position_details),
        "trade_summary": review.trade_summary,
        "market_analysis": review.market_analysis,
        "lessons": review.lessons,
        "tomorrow_plan": review.tomorrow_plan,
        "ai_review": review.ai_review,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }

    # 3. 写入缓存
    cache_set(cache_key, result, REVIEW_CACHE_TTL, NS_REVIEW)

    return result


def get_review_history(
    db: Session, account_id: int, limit: int = 30
) -> List[Dict[str, Any]]:
    """获取复盘历史记录（按日期倒序）。

    Args:
        db: 数据库会话
        account_id: 模拟交易账户ID
        limit: 返回的最大记录数，默认30

    Returns:
        复盘记录列表（按日期倒序）
    """
    # 1. 尝试缓存
    cache_key = f"review_history:{account_id}:{limit}"
    cached = cache_get(cache_key, NS_REVIEW)
    if cached:
        return cached

    # 2. 查询数据库
    reviews = db.query(SimDailyReview).filter(
        SimDailyReview.account_id == account_id
    ).order_by(
        SimDailyReview.review_date.desc()
    ).limit(limit).all()

    result = [
        {
            "id": r.id,
            "review_date": r.review_date,
            "daily_pnl": r.daily_pnl,
            "total_pnl": r.total_pnl,
            "total_pnl_ratio": r.total_pnl_ratio,
            "total_trades": r.total_trades,
            "win_count": r.win_count,
            "loss_count": r.loss_count,
            "win_rate": r.win_rate,
            "strategy_accuracy": r.strategy_accuracy,
            "position_count": r.position_count,
            "trade_summary": _truncate_text(r.trade_summary, 100),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reviews
    ]

    # 3. 写入缓存（短期TTL，因为列表可能频繁变动）
    cache_set(cache_key, result, 3600, NS_REVIEW)

    return result


def generate_tomorrow_plan(
    db: Session, account_id: int, review_date: str
) -> Dict[str, Any]:
    """生成明日交易计划。

    基于：
    - 当日复盘结果
    - 当前市场情绪
    - 当前持仓状态

    Args:
        db: 数据库会话
        account_id: 模拟交易账户ID
        review_date: 基准日期（今日），格式 YYYY-MM-DD

    Returns:
        明日计划结果字典
    """
    # 1. 获取当日复盘
    review = db.query(SimDailyReview).filter(
        and_(
            SimDailyReview.account_id == account_id,
            SimDailyReview.review_date == review_date,
        )
    ).first()

    # 2. 获取市场情绪
    sentiment = _get_market_sentiment()

    # 3. 获取持仓状态
    positions = _get_positions(db, account_id)
    positions_dict = _positions_to_dict_list(positions)

    # 4. 获取账户信息
    from app.models.sim_trading import SimAccount
    account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
    if not account:
        return {"success": False, "error": "账户不存在"}

    # 5. 获取最近几日的复盘记录（趋势参考）
    recent_reviews = db.query(SimDailyReview).filter(
        and_(
            SimDailyReview.account_id == account_id,
            SimDailyReview.review_date <= review_date,
        )
    ).order_by(SimDailyReview.review_date.desc()).limit(5).all()

    # 6. 构建LLM上下文
    review_text = ""
    if review and review.ai_review:
        review_text = review.ai_review
    elif review:
        review_text = (
            f"当日盈亏: {review.daily_pnl:+.2f}元, "
            f"累计盈亏: {review.total_pnl:+.2f}元({review.total_pnl_ratio:+.2f}%), "
            f"交易{review.total_trades}笔, 胜率{review.win_rate}%"
        )
    else:
        review_text = "无当日复盘数据"

    positions_summary = ""
    if positions_dict:
        lines = []
        for p in positions_dict:
            lines.append(
                f"  {p['name']}({p['code']}) {p['quantity']}股 "
                f"成本{p['cost_price']:.3f} 现价{p['current_price']:.3f} "
                f"盈亏{p['profit']:+.2f}元({p['profit_ratio']:+.2f}%) "
                f"类型={p['position_type']} 买入日期={p['buy_date'] or '未知'}"
            )
        positions_summary = "\n".join(lines)
    else:
        positions_summary = "  无持仓"

    # 市场情绪摘要
    indices = sentiment.get("indices", {})
    breadth = sentiment.get("breadth", {})
    market_parts = []
    if indices:
        for code in ["000001", "399001", "399006"]:
            idx = indices.get(code)
            if idx:
                market_parts.append(
                    f"{idx.get('name', code)} {idx.get('price', 0)} ({idx.get('change_pct', 0):+.2f}%)"
                )
    if breadth:
        market_parts.append(f"涨{breadth.get('up', 0)}/跌{breadth.get('down', 0)}")
        market_parts.append(f"涨停{breadth.get('limit_up', 0)}/跌停{breadth.get('limit_down', 0)}")
    market_summary = " | ".join(market_parts) if market_parts else "暂无市场数据"

    # 近期趋势
    recent_trend = ""
    if recent_reviews:
        trend_lines = []
        for r in recent_reviews:
            trend_lines.append(
                f"  {r.review_date}: 盈亏{r.daily_pnl:+.2f}元 "
                f"胜率{r.win_rate}% 交易{r.total_trades}笔"
            )
        recent_trend = "\n".join(trend_lines)
    else:
        recent_trend = "  无历史复盘数据"

    # 7. 调用LLM生成明日计划
    system_prompt = (
        "你是A股模拟交易策略规划师。基于当日复盘结果、市场情绪、持仓状态和近期趋势，"
        "生成明日的详细交易计划。\n\n"
        "计划需包含以下部分：\n"
        "1. 市场研判：对明日市场走势的预判\n"
        "2. 持仓操作计划：对现有持仓的处理建议（持有/减仓/加仓/清仓）\n"
        "3. 买入计划：建议买入的股票及理由\n"
        "4. 风控要点：止损止盈设置和风险提醒\n\n"
        "要求：语言简洁专业，操作建议具体明确，每部分50-150字。"
    )

    user_prompt = f"""日期: {review_date}

## 当日复盘
{review_text}

## 当前持仓 ({len(positions_dict)}只, 可用资金{account.current_capital:,.0f}元)
{positions_summary}

## 市场情绪
{market_summary}

## 近期趋势
{recent_trend}

请生成明日交易计划。"""

    tomorrow_plan = ""
    try:
        tomorrow_plan = _call_llm_sync(system_prompt, user_prompt)
        # 去除可能的markdown代码块标记
        if tomorrow_plan.startswith("```"):
            tomorrow_plan = tomorrow_plan.strip("`").strip()
            if "\n" in tomorrow_plan:
                first_newline = tomorrow_plan.index("\n")
                tomorrow_plan = tomorrow_plan[first_newline + 1:].strip()
    except Exception as e:
        logger.warning(f"LLM明日计划生成失败，使用基础模板: {e}")
        tomorrow_plan = (
            f"## {review_date} 次日交易计划\n\n"
            f"### 市场研判\n当前持仓{len(positions_dict)}只，可用资金{account.current_capital:,.0f}元。"
            f"市场{market_summary}。\n\n"
            f"### 持仓计划\n保持当前持仓，关注止损止盈位。\n\n"
            f"### 风控要点\n单只仓位不超过20%，设置8%止损线。\n\n"
            f"> AI计划生成失败（{type(e).__name__}），以上为基础模板。"
        )

    # 8. 保存到复盘记录
    if review:
        review.tomorrow_plan = tomorrow_plan
    else:
        # 无复盘记录时创建一个最小化的记录
        review = SimDailyReview(
            account_id=account_id,
            review_date=review_date,
            tomorrow_plan=tomorrow_plan,
        )
        db.add(review)

    db.commit()
    db.refresh(review)

    # 9. 清除相关缓存
    _cache_delete_keys(
        f"review:{account_id}:{review_date}",
    )

    return {
        "success": True,
        "review_id": review.id,
        "review_date": review_date,
        "tomorrow_plan": tomorrow_plan,
        "position_count": len(positions_dict),
        "available_capital": account.current_capital,
    }


# ── 工具函数 ──────────────────────────────────────────────────────

def _extract_section(text: str, section_keyword: str) -> str:
    """从AI生成的报告文本中提取指定章节内容。

    查找包含关键词的章节标题（## 或 **开头），提取到下一个章节之前的内容。
    """
    if not text:
        return ""

    lines = text.split("\n")
    capture = False
    section_lines = []

    for line in lines:
        stripped = line.strip()
        # 检测章节标题（## 开头、**开头、或数字序号开头）
        is_heading = (
            stripped.startswith("#")
            or stripped.startswith("**")
            or (len(stripped) > 0 and stripped[0].isdigit() and ("." in stripped[:4] or "、" in stripped[:4]))
        )

        if is_heading and section_keyword in stripped:
            capture = True
            continue

        if capture and is_heading:
            # 遇到新章节，停止捕获
            break

        if capture:
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def _safe_json_loads(json_str: Optional[str]) -> Any:
    """安全解析JSON字符串，失败时返回None"""
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None


def _truncate_text(text: Optional[str], max_chars: int = 100) -> Optional[str]:
    """截断文本到指定长度"""
    if not text:
        return text
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _cache_delete_keys(*keys: str):
    """删除指定的缓存键"""
    from app.core.cache import cache_delete
    for key in keys:
        try:
            cache_delete(key, NS_REVIEW)
        except Exception:
            pass


class ReviewService:
    """复盘服务类 - 包装模块级函数供API层/main.py调用"""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def get_review_history(db: Session, account_id: int, limit: int = 30):
        return get_review_history(db, account_id, limit)

    @staticmethod
    def get_daily_review(db: Session, account_id: int, review_date: str):
        return get_daily_review(db, account_id, review_date)

    @staticmethod
    def generate_daily_review(db: Session, account_id: int, review_date: str = None):
        if not review_date:
            from datetime import date
            review_date = date.today().strftime("%Y-%m-%d")
        return generate_daily_review(db, account_id, review_date)

    @staticmethod
    def generate_tomorrow_plan(db: Session, account_id: int, review_date: str):
        return generate_tomorrow_plan(db, account_id, review_date)

    # 兼容main.py实例调用方式
    def analyze_daily_trades(self, trade_date: str):
        from app.services.trade_engine import TradeEngine
        account = TradeEngine.get_or_create_account(self.db)
        return generate_daily_review(self.db, account.id, trade_date)

    def calculate_daily_pnl(self, trade_date: str):
        pass  # PnL由TradeEngine.record_daily_pnl处理

    def generate_review_report(self, trade_date: str):
        from app.services.trade_engine import TradeEngine
        account = TradeEngine.get_or_create_account(self.db)
        return generate_tomorrow_plan(self.db, account.id, trade_date)
