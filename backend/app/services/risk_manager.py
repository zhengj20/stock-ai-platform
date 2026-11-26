# -*- coding: utf-8 -*-
"""止损止盈风险管理系统 - 阶段2: 服务层

负责持仓的风控检查，包括固定止损、移动止损、时间止损和止盈检查。
当风控条件触发时，自动创建卖出委托单。
"""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.sim_trading import SimPosition, SimOrder
from app.services.order_service import OrderService
from app.core.data_sources import TencentSource


logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "stop_loss": 0.08,
    "trailing_stop": 0.05,
    "take_profit": 0.15,
    "max_hold_days": 10,  # 默认短线；中线/长线按 HOLD_DAYS_BY_TYPE 覆盖
}

# 按 position_type 差异化的风控参数
# 短线：5个交易日强制清仓，止损5%，止盈8-15%
# 中线：30个交易日，止损10%，止盈20-40%
# 长线：90个交易日，止损15%，止盈40-100%
HOLD_DAYS_BY_TYPE = {"short": 5, "mid": 30, "long": 90}
STOP_LOSS_BY_TYPE = {"short": 0.05, "mid": 0.10, "long": 0.15}
TAKE_PROFIT_BY_TYPE = {"short": 0.08, "mid": 0.20, "long": 0.40}
TRAILING_STOP_BY_TYPE = {"short": 0.03, "mid": 0.05, "long": 0.10}

# 分批止盈配置
# 达到止盈线 → 卖出50%；达到1.5倍止盈线 → 卖出剩余
BATCH_TAKE_PROFIT_FIRST_RATIO = 0.5     # 首次止盈卖出比例
BATCH_TAKE_PROFIT_SECOND_MULT = 1.5     # 二次止盈触发倍数

# 市场情绪动态调整系数（P1-4）
# 同样的持仓周期在不同市场情绪下应使用不同阈值：
# - 牛市（bullish）：止损放宽2%，止盈放宽2%，给趋势更多空间
# - 震荡（neutral）：保持基础阈值
# - 熊市（bearish）：止损收紧2%，止盈收紧2%，避免利润回吐
SENTIMENT_ADJUSTMENT = {
    "bullish":  {"stop_loss_delta": 0.02, "take_profit_delta": 0.02, "trailing_delta": 0.01},
    "neutral":  {"stop_loss_delta": 0.00, "take_profit_delta": 0.00, "trailing_delta": 0.00},
    "bearish":  {"stop_loss_delta": -0.02, "take_profit_delta": -0.02, "trailing_delta": -0.01},
}

# ATR 倍数按情绪调整（牛市3×ATR容忍度高，熊市1.5×ATR快速止损）
ATR_MULTIPLIER_BY_SENTIMENT = {"bullish": 3.0, "neutral": 2.0, "bearish": 1.5}


class RiskManager:
    """风控服务 - 止损止盈检查"""

    @staticmethod
    def check_stop_loss(
        db: Session,
        account_id: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """止损检查：按 position_type 差异化止损线 + 市场情绪动态调整

        - 优先 ATR 动态止损（ATR 不可用时按周期阈值兜底）
        - 短线止损 5%，中线 10%，长线 15%
        - ATR 止损线 = cost_price - N×ATR（N按情绪：牛市3，震荡2，熊市1.5）
        - 情绪调整：牛市+2%，熊市-2%
        """
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        default_stop_loss_pct = cfg["stop_loss"] * 100

        # P1-4：从 cfg 提取市场情绪
        sentiment = cfg.get("_market_sentiment", "neutral")
        sentiment_adj = SENTIMENT_ADJUSTMENT.get(sentiment, SENTIMENT_ADJUSTMENT["neutral"])
        atr_multiplier = ATR_MULTIPLIER_BY_SENTIMENT.get(sentiment, 2.0)

        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()

        triggered: List[Dict[str, Any]] = []
        for pos in positions:
            # 按 position_type 取差异化止损阈值 + 情绪调整
            pos_type = pos.position_type or "short"
            base_stop_loss = STOP_LOSS_BY_TYPE.get(pos_type, cfg["stop_loss"])
            # 牛市放宽（正delta让止损线更远），熊市收紧（负delta让止损线更近）
            stop_loss_ratio = max(0.02, base_stop_loss + sentiment_adj["stop_loss_delta"])
            stop_loss_pct = stop_loss_ratio * 100

            # 优先用 ATR 动态止损
            if pos.atr_value and pos.atr_value > 0 and pos.cost_price > 0:
                atr_stop_price = pos.cost_price - atr_multiplier * pos.atr_value
                # ATR止损最低阈值保护：止损线至少在成本价下方 stop_loss_ratio
                min_stop_price = pos.cost_price * (1 - stop_loss_ratio)
                stop_price = max(atr_stop_price, min_stop_price)
                stop_threshold_ratio = (stop_price / pos.cost_price - 1) * 100
                if pos.current_price <= stop_price:
                    triggered.append({
                        "position_id": pos.id,
                        "stock_code": pos.stock_code,
                        "stock_name": pos.stock_name,
                        "risk_type": "stop_loss",
                        "profit_ratio": pos.profit_ratio,
                        "threshold": stop_threshold_ratio,
                        "current_price": pos.current_price,
                        "stop_price": round(stop_price, 2),
                        "atr_value": pos.atr_value,
                        "position_type": pos_type,
                        "market_sentiment": sentiment,
                        "message": (
                            f"{pos.stock_name}({pos.stock_code})[{pos_type}][{sentiment}] 触发ATR止损: "
                            f"当前价 {pos.current_price:.2f} <= 止损线 {stop_price:.2f} "
                            f"(成本{pos.cost_price:.2f} - {atr_multiplier}×ATR{pos.atr_value:.4f})"
                        ),
                    })
            else:
                # 回退：固定比例止损（按周期差异化 + 情绪调整）
                if pos.profit_ratio <= -stop_loss_pct:
                    triggered.append({
                        "position_id": pos.id,
                        "stock_code": pos.stock_code,
                        "stock_name": pos.stock_name,
                        "risk_type": "stop_loss",
                        "profit_ratio": pos.profit_ratio,
                        "threshold": -stop_loss_pct,
                        "position_type": pos_type,
                        "message": (
                            f"{pos.stock_name}({pos.stock_code})[{pos_type}] 触发固定止损: "
                            f"当前亏损 {pos.profit_ratio:.2f}%, 止损线 {-stop_loss_pct:.2f}%"
                        ),
                    })

        return triggered

    @staticmethod
    def check_trailing_stop(
        db: Session,
        account_id: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """移动止损检查：按 position_type 差异化回撤阈值 + 市场情绪调整

        - 短线回撤3%，中线5%，长线10%
        - 跟踪持仓期间最高盈利比例，盈利回撤>=阈值时触发卖出
        - 情绪调整：牛市+1%（容忍度高），熊市-1%（快速锁利）
        """
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        default_trailing_pct = cfg["trailing_stop"] * 100

        # P1-4：从 cfg 提取市场情绪
        sentiment = cfg.get("_market_sentiment", "neutral")
        sentiment_adj = SENTIMENT_ADJUSTMENT.get(sentiment, SENTIMENT_ADJUSTMENT["neutral"])

        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()

        triggered: List[Dict[str, Any]] = []
        for pos in positions:
            pos_type = pos.position_type or "short"
            base_trailing = TRAILING_STOP_BY_TYPE.get(pos_type, default_trailing_pct / 100)
            # 牛市放宽（正delta），熊市收紧（负delta），保底1%
            trailing_stop_pct = max(0.01, base_trailing + sentiment_adj["trailing_delta"]) * 100

            if pos.profit_ratio > pos.max_profit_ratio:
                pos.max_profit_ratio = pos.profit_ratio

            if pos.max_profit_ratio > trailing_stop_pct:
                drawdown = pos.max_profit_ratio - pos.profit_ratio
                if drawdown >= trailing_stop_pct:
                    triggered.append({
                        "position_id": pos.id,
                        "stock_code": pos.stock_code,
                        "stock_name": pos.stock_name,
                        "risk_type": "trailing_stop",
                        "profit_ratio": pos.profit_ratio,
                        "max_profit_ratio": pos.max_profit_ratio,
                        "drawdown": drawdown,
                        "threshold": trailing_stop_pct,
                        "position_type": pos_type,
                        "market_sentiment": sentiment,
                        "message": (
                            f"{pos.stock_name}({pos.stock_code})[{pos_type}][{sentiment}] 触发移动止损: "
                            f"最高盈利 {pos.max_profit_ratio:.2f}%, 当前 {pos.profit_ratio:.2f}%, "
                            f"回撤 {drawdown:.2f}% >= 阈值 {trailing_stop_pct:.2f}%"
                        ),
                    })

        if triggered:
            db.flush()

        return triggered

    @staticmethod
    def check_time_stop(
        db: Session,
        account_id: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """时间止损检查：按 position_type 差异化最大持仓天数

        - 短线 5 个交易日，中线 30 个，长线 90 个
        - 计算交易日持仓天数（从 buy_date 开始，排除周末和节假日）
        """
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        default_max_hold = cfg["max_hold_days"]
        today = date.today()

        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()

        triggered: List[Dict[str, Any]] = []
        from app.core.trading_calendar import is_trading_day
        from datetime import timedelta as _td
        for pos in positions:
            if not pos.buy_date:
                continue

            try:
                buy_date = datetime.strptime(pos.buy_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            # 按 position_type 取差异化最大持仓天数
            pos_type = pos.position_type or "short"
            max_hold_days = HOLD_DAYS_BY_TYPE.get(pos_type, default_max_hold)

            # 计算交易日持仓天数（排除周末和节假日）
            cur = buy_date + _td(days=1)
            trading_days = 0
            while cur <= today:
                if is_trading_day(datetime.combine(cur, datetime.min.time())):
                    trading_days += 1
                cur += _td(days=1)

            if trading_days >= max_hold_days:
                triggered.append({
                    "position_id": pos.id,
                    "stock_code": pos.stock_code,
                    "stock_name": pos.stock_name,
                    "risk_type": "time_stop",
                    "hold_days": trading_days,
                    "buy_date": pos.buy_date,
                    "threshold": max_hold_days,
                    "position_type": pos_type,
                    "message": (
                        f"{pos.stock_name}({pos.stock_code})[{pos_type}] 触发时间止损: "
                        f"持仓 {trading_days} 个交易日 >= 上限 {max_hold_days} 个交易日"
                    ),
                })

        return triggered

    @staticmethod
    def check_take_profit(
        db: Session,
        account_id: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """止盈检查：分批止盈 + 按 position_type 差异化止盈线 + 市场情绪调整

        - 短线止盈 8%，中线 20%，长线 40%
        - 分批止盈：达到止盈线 → 卖出50%；达到1.5倍止盈线 → 卖出剩余
        - 通过 risk_type 区分：
            take_profit_first（首次减半）
            take_profit_full（二次清仓）
        - 调用方按 sell_quantity 字段决定卖出数量
        - 情绪调整：牛市+2%（让利润奔跑），熊市-2%（快速锁利）
        """
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        default_take_profit_pct = cfg["take_profit"] * 100

        # P1-4：从 cfg 提取市场情绪
        sentiment = cfg.get("_market_sentiment", "neutral")
        sentiment_adj = SENTIMENT_ADJUSTMENT.get(sentiment, SENTIMENT_ADJUSTMENT["neutral"])

        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()

        triggered: List[Dict[str, Any]] = []
        for pos in positions:
            pos_type = pos.position_type or "short"
            base_take_profit = TAKE_PROFIT_BY_TYPE.get(pos_type, default_take_profit_pct / 100)
            # 牛市放宽（正delta让止盈线更远），熊市收紧（负delta让止盈线更近），保底3%
            take_profit_ratio = max(0.03, base_take_profit + sentiment_adj["take_profit_delta"])
            take_profit_pct = take_profit_ratio * 100
            second_trigger_pct = take_profit_pct * BATCH_TAKE_PROFIT_SECOND_MULT

            # 二次止盈：盈利达到 1.5 倍止盈线 → 全部清仓
            if pos.profit_ratio >= second_trigger_pct:
                # 全部清仓
                sell_quantity = pos.available_quantity
                triggered.append({
                    "position_id": pos.id,
                    "stock_code": pos.stock_code,
                    "stock_name": pos.stock_name,
                    "risk_type": "take_profit_full",
                    "profit_ratio": pos.profit_ratio,
                    "threshold": second_trigger_pct,
                    "sell_quantity": sell_quantity,
                    "position_type": pos_type,
                    "market_sentiment": sentiment,
                    "message": (
                        f"{pos.stock_name}({pos.stock_code})[{pos_type}][{sentiment}] 触发二次止盈(全部清仓): "
                        f"当前盈利 {pos.profit_ratio:.2f}% >= {second_trigger_pct:.2f}%"
                    ),
                })
            # 首次止盈：达到止盈线且未触发二次 → 卖出50%
            elif pos.profit_ratio >= take_profit_pct:
                # 卖出可用持仓的50%，向下取整到100股
                raw_qty = int(pos.available_quantity * BATCH_TAKE_PROFIT_FIRST_RATIO)
                sell_quantity = (raw_qty // 100) * 100
                # 至少100股；若可用持仓不足200股则全部卖出
                if sell_quantity < 100:
                    sell_quantity = pos.available_quantity
                triggered.append({
                    "position_id": pos.id,
                    "stock_code": pos.stock_code,
                    "stock_name": pos.stock_name,
                    "risk_type": "take_profit_first",
                    "profit_ratio": pos.profit_ratio,
                    "threshold": take_profit_pct,
                    "sell_quantity": sell_quantity,
                    "position_type": pos_type,
                    "market_sentiment": sentiment,
                    "message": (
                        f"{pos.stock_name}({pos.stock_code})[{pos_type}][{sentiment}] 触发首次止盈(减半): "
                        f"当前盈利 {pos.profit_ratio:.2f}% >= {take_profit_pct:.2f}%, "
                        f"卖出 {sell_quantity} 股"
                    ),
                })

        return triggered

    @staticmethod
    def check_all_risks(
        db: Session,
        account_id: int,
        config: Optional[Dict[str, Any]] = None,
        market_sentiment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """综合风险检查

        同时检查所有风控条件，返回需要处理的风险列表。
        每只股票最多触发一种风险类型（优先级：止损 > 移动止损 > 时间止损 > 止盈）。

        Args:
            market_sentiment: 市场情绪（bullish/neutral/bearish）
                              用于按情绪动态调整止损止盈阈值（P1-4）
                              None 时自动从 MarketService 获取（兼容旧调用方）
        """
        cfg = {**DEFAULT_CONFIG, **(config or {})}

        # P1-4：自动获取市场情绪（若调用方未传入）
        if market_sentiment is None:
            try:
                from app.services.market_service import MarketService
                ms = MarketService()
                sentiment_data = ms.get_market_sentiment(include_flow=False)
                breadth = sentiment_data.get("breadth", {}) if sentiment_data else {}
                total = breadth.get("total", 1)
                up = breadth.get("up", 0)
                if total > 0:
                    ratio = up / total
                    if ratio > 0.6:
                        market_sentiment = "bullish"
                    elif ratio < 0.4:
                        market_sentiment = "bearish"
                    else:
                        market_sentiment = "neutral"
                else:
                    market_sentiment = "neutral"
            except Exception as e:
                logger.warning(f"获取市场情绪失败，使用 neutral 兜底: {e}")
                market_sentiment = "neutral"

        cfg["_market_sentiment"] = market_sentiment

        RiskManager._update_position_prices(db, account_id)

        all_risks: List[Dict[str, Any]] = []

        stop_loss_risks = RiskManager.check_stop_loss(db, account_id, cfg)
        all_risks.extend(stop_loss_risks)

        trailing_stop_risks = RiskManager.check_trailing_stop(db, account_id, cfg)
        all_risks.extend(trailing_stop_risks)

        time_stop_risks = RiskManager.check_time_stop(db, account_id, cfg)
        all_risks.extend(time_stop_risks)

        take_profit_risks = RiskManager.check_take_profit(db, account_id, cfg)
        all_risks.extend(take_profit_risks)

        priority = {
            "stop_loss": 0,
            "trailing_stop": 1,
            "time_stop": 2,
            "take_profit_full": 3,
            "take_profit_first": 4,
            "take_profit": 5,
        }
        risk_map: Dict[str, Dict[str, Any]] = {}
        for risk in all_risks:
            code = risk["stock_code"]
            if code not in risk_map:
                risk_map[code] = risk
            else:
                existing_priority = priority.get(risk_map[code]["risk_type"], 99)
                new_priority = priority.get(risk["risk_type"], 99)
                if new_priority < existing_priority:
                    risk_map[code] = risk

        deduplicated = list(risk_map.values())

        # ── 补充前端展示字段 ──
        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()
        pos_map = {p.stock_code: p for p in positions}

        risk_level_map = {
            "stop_loss": "critical",
            "trailing_stop": "high",
            "time_stop": "medium",
            "take_profit_full": "low",
            "take_profit_first": "low",
            "take_profit": "low",
            "concentration_warning": "medium",
            "concentration_critical": "high",
        }
        suggestion_map = {
            "stop_loss": "立即卖出止损",
            "trailing_stop": "按移动止损规则卖出",
            "time_stop": "考虑清仓或减仓",
            "take_profit_full": "全部清仓锁定利润",
            "take_profit_first": "首次止盈卖出50%",
            "take_profit": "可分批止盈",
            "concentration_warning": "暂不加仓该行业，等集中度回落",
            "concentration_critical": "减仓超配行业的持仓1/3",
        }

        for risk in deduplicated:
            pos = pos_map.get(risk["stock_code"])
            if pos:
                risk["current_price"] = pos.current_price
                risk["cost_price"] = pos.cost_price
                risk["profit_ratio"] = pos.profit_ratio
                risk["loss_ratio"] = pos.profit_ratio
            risk["risk_level"] = risk_level_map.get(risk["risk_type"], "medium")
            risk["risk_reason"] = risk.get("message", risk["risk_type"])
            risk["suggestion"] = suggestion_map.get(risk["risk_type"], "关注并适时处理")

        # P1-5：持仓集中度强制监控
        # 单一行业占比 > 40% 触发 warning；> 50% 触发 critical 并自动减仓
        try:
            concentration_risks = RiskManager.check_concentration(db, account_id)
            if concentration_risks:
                # 集中度风险与个股风险合并（同一股票若已有个股风险，优先保留个股风险）
                existing_codes = {r["stock_code"] for r in deduplicated}
                for cr in concentration_risks:
                    if cr["stock_code"] not in existing_codes:
                        # 补充前端展示字段（与其他风险类型一致）
                        pos = pos_map.get(cr["stock_code"])
                        if pos:
                            cr["current_price"] = pos.current_price
                            cr["cost_price"] = pos.cost_price
                            cr["profit_ratio"] = pos.profit_ratio
                            cr["loss_ratio"] = pos.profit_ratio
                        cr["risk_level"] = risk_level_map.get(cr["risk_type"], "medium")
                        cr["risk_reason"] = cr.get("message", cr["risk_type"])
                        cr["suggestion"] = suggestion_map.get(cr["risk_type"], "关注行业集中度")
                        deduplicated.append(cr)
        except Exception as e:
            logger.warning(f"持仓集中度检查失败: {e}")

        logger.info(
            f"综合风控检查完成: 账户 {account_id}, "
            f"原始风险 {len(all_risks)} 项, 去重后 {len(deduplicated)} 项"
        )

        return {
            "success": True,
            "account_id": account_id,
            "total_risks": len(deduplicated),
            "risks": deduplicated,
            "risk_positions": deduplicated,
            "summary": {
                "stop_loss": sum(1 for r in deduplicated if r["risk_type"] == "stop_loss"),
                "trailing_stop": sum(1 for r in deduplicated if r["risk_type"] == "trailing_stop"),
                "time_stop": sum(1 for r in deduplicated if r["risk_type"] == "time_stop"),
                "take_profit_first": sum(1 for r in deduplicated if r["risk_type"] == "take_profit_first"),
                "take_profit_full": sum(1 for r in deduplicated if r["risk_type"] == "take_profit_full"),
                "take_profit": sum(1 for r in deduplicated if r["risk_type"].startswith("take_profit")),
                "concentration": sum(1 for r in deduplicated if r["risk_type"].startswith("concentration")),
            },
        }

    @staticmethod
    def check_concentration(
        db: Session,
        account_id: int,
        warning_threshold: float = 0.40,
        critical_threshold: float = 0.50,
    ) -> List[Dict[str, Any]]:
        """持仓行业集中度检查（P1-5）

        - 单一行业市值占比 > warning_threshold（默认40%）→ 触发 warning
        - 单一行业市值占比 > critical_threshold（默认50%）→ 触发 critical 并标记需减仓标的
        - critical 场景下选取该行业中浮盈最高（或浮亏最小）的持仓作为减仓候选

        Returns:
            风险列表，每项含 stock_code/stock_name/risk_type/sell_quantity（如适用）
        """
        from app.models.sim_trading import SimPosition
        from app.core.data_sources import TencentSource

        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id,
            SimPosition.available_quantity > 0,
        ).all()

        if not positions:
            return []

        total_mv = sum(p.market_value or 0 for p in positions)
        if total_mv <= 0:
            return []

        # 按行业聚合市值
        sector_positions: Dict[str, List[Any]] = {}
        sector_mv: Dict[str, float] = {}
        try:
            quotes = TencentSource.get_quotes([p.stock_code for p in positions])
        except Exception as e:
            logger.warning(f"集中度检查-获取行情失败，按'其他'归类: {e}")
            quotes = {}

        for p in positions:
            q = quotes.get(p.stock_code, {}) if quotes else {}
            sector = q.get("industry") or q.get("sector") or "其他"
            sector_positions.setdefault(sector, []).append(p)
            sector_mv[sector] = sector_mv.get(sector, 0) + (p.market_value or 0)

        triggered: List[Dict[str, Any]] = []
        for sector, mv in sector_mv.items():
            ratio = mv / total_mv
            if ratio > critical_threshold:
                # critical：标记该行业中浮盈最高（优先止盈）或浮亏最小（避免割肉）的持仓减仓1/3
                sector_pos_list = sector_positions[sector]
                # 按 profit_ratio 降序：浮盈越高越优先减仓
                sector_pos_list.sort(key=lambda x: x.profit_ratio or 0, reverse=True)
                target_pos = sector_pos_list[0]
                raw_qty = int(target_pos.available_quantity / 3)
                sell_quantity = (raw_qty // 100) * 100
                if sell_quantity < 100:
                    sell_quantity = min(100, target_pos.available_quantity)
                triggered.append({
                    "position_id": target_pos.id,
                    "stock_code": target_pos.stock_code,
                    "stock_name": target_pos.stock_name,
                    "risk_type": "concentration_critical",
                    "sector": sector,
                    "sector_ratio": round(ratio * 100, 1),
                    "threshold": critical_threshold * 100,
                    "sell_quantity": sell_quantity,
                    "position_type": target_pos.position_type or "short",
                    "message": (
                        f"{target_pos.stock_name}({target_pos.stock_code})[{sector}] 行业集中度 critical: "
                        f"{sector} 占比 {ratio*100:.1f}% > {critical_threshold*100:.0f}%，"
                        f"减仓 {sell_quantity} 股降低集中度"
                    ),
                })
            elif ratio > warning_threshold:
                # warning：仅提示，不强制减仓
                sector_pos_list = sector_positions[sector]
                # 标记该行业中市值最大的持仓作为提示对象
                target_pos = max(sector_pos_list, key=lambda x: x.market_value or 0)
                triggered.append({
                    "position_id": target_pos.id,
                    "stock_code": target_pos.stock_code,
                    "stock_name": target_pos.stock_name,
                    "risk_type": "concentration_warning",
                    "sector": sector,
                    "sector_ratio": round(ratio * 100, 1),
                    "threshold": warning_threshold * 100,
                    "position_type": target_pos.position_type or "short",
                    "message": (
                        f"{target_pos.stock_name}({target_pos.stock_code})[{sector}] 行业集中度 warning: "
                        f"{sector} 占比 {ratio*100:.1f}% > {warning_threshold*100:.0f}%，"
                        f"暂不加仓该行业"
                    ),
                })

        return triggered

    @staticmethod
    def create_risk_sell_order(
        db: Session,
        position: SimPosition,
        risk_type: str,
        current_price: Optional[float] = None,
        sell_quantity_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        """风险卖出：市价单立即成交（止损/止盈必须确定性成交）

        根据风险类型创建卖出市价单，记录卖出原因。
        - 默认卖出全部可用持仓
        - sell_quantity_override：分批止盈等场景指定卖出数量
        """
        risk_type_names = {
            "stop_loss": "止损",
            "trailing_stop": "移动止损",
            "time_stop": "时间止损",
            "take_profit": "止盈",
            "take_profit_first": "首次止盈(减半)",
            "take_profit_full": "二次止盈(清仓)",
        }
        risk_name = risk_type_names.get(risk_type, risk_type)

        sell_price = current_price or position.current_price
        if sell_price <= 0:
            return {
                "success": False,
                "error": f"{position.stock_name}({position.stock_code}) 无效的卖出价格: {sell_price}",
            }

        # 默认卖出全部可用持仓；分批止盈等场景使用覆盖数量
        sell_quantity = sell_quantity_override if sell_quantity_override else position.available_quantity
        # 防超卖保护：卖出数量不超过可用持仓和总持仓
        if position.available_quantity > 0:
            sell_quantity = min(sell_quantity, position.available_quantity)
        if position.total_quantity > 0:
            sell_quantity = min(sell_quantity, position.total_quantity)
        if sell_quantity <= 0:
            return {
                "success": False,
                "error": f"{position.stock_name}({position.stock_code}) 可卖数量为 0, 可能处于 T+1 冻结期",
            }

        sell_pct = (sell_quantity / position.total_quantity * 100) if position.total_quantity > 0 else 100
        strategy_reason = (
            f"[{risk_name}] 盈亏比例 {position.profit_ratio:.2f}%, "
            f"卖出 {sell_quantity} 股 ({sell_pct:.0f}%)"
        )

        result = OrderService.execute_market_order(
            db=db,
            account_id=position.account_id,
            stock_code=position.stock_code,
            stock_name=position.stock_name,
            order_type="sell",
            quantity=sell_quantity,
            price=sell_price,
            strategy_name=f"risk_{risk_type}",
            strategy_reason=strategy_reason,
            order_source="risk_control",
            auto_commit=True,
        )

        if result.get("success"):
            logger.info(
                f"{risk_name}卖出成交: {position.stock_code} "
                f"{sell_quantity}股@{sell_price}, 理由={strategy_reason}"
            )
        else:
            err = result.get("error", "")
            logger.warning(f"{risk_name}卖出失败: {position.stock_code}, 原因={err}")

        return result

    @staticmethod
    def execute_risk_sells(
        db: Session,
        account_id: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行全部风控检查并市价卖出

        完整流程:
        1. 更新持仓实时价格
        2. 执行综合风控检查
        3. 对触发风控的持仓执行市价卖出（即时成交，无需撮合）
        """
        risk_result = RiskManager.check_all_risks(db, account_id, config)
        risks = risk_result.get("risks", [])

        if not risks:
            return {
                "success": True,
                "account_id": account_id,
                "sell_orders_created": 0,
                "risks": [],
                "message": "所有持仓风控正常, 无需处理",
            }

        stock_codes = [r["stock_code"] for r in risks]
        quotes = {}
        try:
            quotes = TencentSource.get_quotes(stock_codes)
        except Exception as e:
            logger.warning(f"获取实时行情失败, 使用持仓缓存价格: {e}")

        sell_results: List[Dict[str, Any]] = []
        for risk in risks:
            position = db.query(SimPosition).filter(
                and_(
                    SimPosition.account_id == account_id,
                    SimPosition.stock_code == risk["stock_code"],
                )
            ).first()

            if not position:
                continue

            # T+1冻结期检查：今日买入的持仓不可卖出
            from datetime import date as _date
            today_str = _date.today().strftime("%Y-%m-%d")
            if position.buy_date == today_str:
                logger.info(f"风控跳过: {position.stock_name}({position.stock_code}) 今日买入(T+1冻结)")
                continue

            # 防重复卖出：检查可用数量
            if position.available_quantity <= 0 or position.total_quantity <= 0:
                logger.info(f"风控跳过: {position.stock_name}({position.stock_code}) 无剩余持仓")
                continue

            quote = quotes.get(risk["stock_code"])
            current_price = quote["price"] if quote and quote.get("price", 0) > 0 else None

            # 分批止盈等场景：从 risk 中取出 sell_quantity 传给下单函数
            sell_qty_override = risk.get("sell_quantity")

            result = RiskManager.create_risk_sell_order(
                db=db,
                position=position,
                risk_type=risk["risk_type"],
                current_price=current_price,
                sell_quantity_override=sell_qty_override,
            )
            result["risk"] = risk
            sell_results.append(result)

        created_count = sum(1 for r in sell_results if r.get("success"))
        logger.info(
            f"风控卖出执行完成: 账户 {account_id}, "
            f"成交 {created_count} 笔"
        )

        return {
            "success": True,
            "account_id": account_id,
            "sell_orders_created": created_count,
            "sell_results": sell_results,
            "risks": risks,
        }

    @staticmethod
    def _update_position_prices(db: Session, account_id: int) -> None:
        """更新持仓实时价格"""
        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()

        if not positions:
            return

        stock_codes = [p.stock_code for p in positions]

        try:
            quotes = TencentSource.get_quotes(stock_codes)
        except Exception as e:
            logger.warning(f"获取实时行情失败: {e}")
            return

        for pos in positions:
            quote = quotes.get(pos.stock_code)
            if not quote or quote.get("price", 0) <= 0:
                continue

            pos.current_price = quote["price"]
            pos.market_value = pos.total_quantity * pos.current_price
            pos.profit = (pos.current_price - pos.cost_price) * pos.total_quantity
            pos.profit_ratio = (
                (pos.current_price / pos.cost_price - 1) * 100
                if pos.cost_price > 0
                else 0
            )

        db.flush()

    @staticmethod
    def check_circuit_breaker(db: Session, account_id: int) -> bool:
        """日内熔断：当日累计亏损 > 3% 时停止开新仓

        实时计算当日盈亏（不依赖收盘才写入的 SimDailyPnl）：
        当日盈亏比例 = (当前总资产 - 昨日总资产) / 昨日总资产 * 100

        用于阻止 AI 策略在亏损过大时继续买入。
        """
        from app.models.sim_trading import SimDailyPnl, SimAccount, SimPosition
        from datetime import date as _date

        today = _date.today().strftime("%Y-%m-%d")

        # 获取昨日总资产（最近一条非今日的 PnL 记录）
        prev_pnl = db.query(SimDailyPnl).filter(
            and_(
                SimDailyPnl.account_id == account_id,
                SimDailyPnl.trade_date < today,
            )
        ).order_by(SimDailyPnl.trade_date.desc()).first()

        if not prev_pnl or prev_pnl.total_assets <= 0:
            return False  # 无历史数据，不触发熔断

        # 实时计算当前总资产（使用统一计算函数）
        from app.services.trade_engine import TradeEngine
        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
        if not account:
            return False
        current_total_assets = TradeEngine.calculate_total_assets(db, account=account)

        # 计算当日盈亏比例
        daily_profit_ratio = (
            (current_total_assets - prev_pnl.total_assets) / prev_pnl.total_assets * 100
        )

        if daily_profit_ratio <= -3.0:
            logger.warning(
                f"日内熔断触发: 账户{account_id} 当日亏损{daily_profit_ratio:.2f}% "
                f"(当前{current_total_assets:.0f} vs 昨日{prev_pnl.total_assets:.0f})"
            )
            return True
        return False
