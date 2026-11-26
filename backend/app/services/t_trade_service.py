"""做T策略服务 - 利用日内波动进行T+0交易

做T策略核心逻辑：
1. 检测日内波动幅度，波动大于3%时存在做T机会
2. 利用已有持仓（available_quantity），当日低买高卖赚取差价
3. 做T必须是当日买入当日卖出，利用昨日持仓做T

注意：做T是利用底仓的日内波动套利，底仓总数量不变，
但通过低买高卖降低持仓成本。
"""
import logging
from datetime import datetime, date
from typing import Optional, Dict, List, Any

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.sim_trading import SimTTrade, SimPosition, SimOrder
from app.core.data_sources import TencentSource
from app.services.trade_engine import TradeEngine
from app.services.order_service import OrderService
from app.core.pytdx_source import pytdx_data

logger = logging.getLogger(__name__)


class TTradeService:
    """做T策略服务"""

    # 做T相关常量
    MIN_AMPLITUDE_PCT = 2.0       # 最低日内振幅阈值(%)，从3%放宽到2%以增加做T机会
    DEFAULT_T_QUANTITY = 100       # 默认做T数量（股）
    COMMISSION_RATE = 0.0003      # 佣金费率 0.03%
    STAMP_TAX_RATE = 0.001        # 印花税 0.1%（仅卖出）
    TRANSFER_FEE_RATE = 0.00002   # 过户费 0.002%
    MIN_COMMISSION = 5.0          # 最低佣金 5元
    # 网格做T：基于持仓成本偏离的触发阈值(%)
    GRID_T_DEVIATION_PCT = 2.0    # 现价偏离成本价>=2%触发网格做T
    GRID_T_PRICE_STEP = 0.01      # 网格做T价差比例(1%)

    # ═══════════════════════════════════════════════════════
    # 检测做T机会
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def detect_t_opportunity(db: Session, stock_code: str) -> Dict[str, Any]:
        """检测做T机会

        流程:
        1. 使用pytdx获取当日分钟级K线（1分钟K线）
        2. 计算日内波动幅度 = (最高价 - 最低价) / 最低价 * 100
        3. 波动 > 3% 时判定有做T机会
        4. 返回建议的买入价和卖出价

        Args:
            db: 数据库会话
            stock_code: 股票代码

        Returns:
            {
                "success": True,
                "has_opportunity": True/False,
                "stock_code": str,
                "amplitude_pct": float,         # 日内振幅(%)
                "suggested_buy_price": float,   # 建议买入价
                "suggested_sell_price": float,  # 建议卖出价
                "high": float,                  # 当日最高价
                "low": float,                   # 当日最低价
                "current_price": float,         # 当前价格
                "kline_count": int,             # 分钟K线数量
                "message": str,
            }
        """
        try:
            # ── 步骤1: 获取当日分钟级K线（1分钟，240根覆盖全天4小时交易） ──
            klines = pytdx_data.get_kline(stock_code, period=7, count=240)

            if not klines:
                # 回退到腾讯实时行情
                return TTradeService._detect_from_realtime_quote(db, stock_code)

            # ── 步骤2: 筛选今日的K线 ──
            today_str = date.today().strftime("%Y-%m-%d")
            today_bars = [
                k for k in klines
                if k.get("date", "").startswith(today_str)
            ]

            if not today_bars:
                # 分时K线可能全部是昨日数据（非交易时段），回退到实时行情
                return TTradeService._detect_from_realtime_quote(db, stock_code)

            # ── 步骤3: 计算日内波动幅度 ──
            day_high = max(bar["high"] for bar in today_bars)
            day_low = min(bar["low"] for bar in today_bars if bar["low"] > 0)
            day_open = today_bars[0]["open"]
            day_close = today_bars[-1]["close"]

            if day_low <= 0:
                return {
                    "success": True,
                    "has_opportunity": False,
                    "stock_code": stock_code,
                    "amplitude_pct": 0,
                    "suggested_buy_price": 0,
                    "suggested_sell_price": 0,
                    "high": day_high,
                    "low": day_low,
                    "current_price": day_close,
                    "kline_count": len(today_bars),
                    "message": "无效的K线数据",
                }

            amplitude_pct = (day_high - day_low) / day_low * 100

            # ── 步骤4: 判断是否有做T机会 ──
            has_opportunity = amplitude_pct >= TTradeService.MIN_AMPLITUDE_PCT

            # ── 步骤5: 计算建议买卖价格 ──
            if has_opportunity:
                # 在振幅区间内取合理价位
                # 买入价：靠近低点（支撑位）
                # 卖出价：靠近高点（压力位）
                price_range = day_high - day_low
                suggested_buy = round(day_low + price_range * 0.1, 2)
                suggested_sell = round(day_high - price_range * 0.1, 2)
            else:
                suggested_buy = 0
                suggested_sell = 0

            # 获取当前实时价格
            current_price = day_close
            try:
                quotes = TencentSource.get_quotes([stock_code])
                if quotes and stock_code in quotes:
                    current_price = quotes[stock_code].get("price", day_close)
            except Exception:
                pass

            msg = (
                f"日内振幅 {amplitude_pct:.2f}%，{'存在' if has_opportunity else '不存在'}做T机会"
                if has_opportunity
                else f"日内振幅 {amplitude_pct:.2f}%，未达到{TTradeService.MIN_AMPLITUDE_PCT}%阈值"
            )

            return {
                "success": True,
                "has_opportunity": has_opportunity,
                "stock_code": stock_code,
                "amplitude_pct": round(amplitude_pct, 2),
                "suggested_buy_price": suggested_buy,
                "suggested_sell_price": suggested_sell,
                "high": round(day_high, 2),
                "low": round(day_low, 2),
                "current_price": round(current_price, 2),
                "kline_count": len(today_bars),
                "message": msg,
            }

        except Exception as e:
            logger.error(f"检测做T机会异常 ({stock_code}): {e}")
            return {
                "success": False,
                "has_opportunity": False,
                "stock_code": stock_code,
                "error": str(e),
                "message": f"检测失败: {e}",
            }

    @staticmethod
    def _detect_from_realtime_quote(db: Session, stock_code: str) -> Dict[str, Any]:
        """从实时行情回退检测做T机会（当分钟K线不可用时）"""
        try:
            quotes = TencentSource.get_quotes([stock_code])
            if not quotes or stock_code not in quotes:
                return {
                    "success": True,
                    "has_opportunity": False,
                    "stock_code": stock_code,
                    "amplitude_pct": 0,
                    "suggested_buy_price": 0,
                    "suggested_sell_price": 0,
                    "high": 0,
                    "low": 0,
                    "current_price": 0,
                    "kline_count": 0,
                    "message": "无法获取行情数据",
                }

            quote = quotes[stock_code]
            day_high = quote.get("high", 0)
            day_low = quote.get("low", 0)
            current_price = quote.get("price", 0)

            if day_low <= 0:
                return {
                    "success": True,
                    "has_opportunity": False,
                    "stock_code": stock_code,
                    "amplitude_pct": 0,
                    "suggested_buy_price": 0,
                    "suggested_sell_price": 0,
                    "high": day_high,
                    "low": day_low,
                    "current_price": current_price,
                    "kline_count": 0,
                    "message": "无效的行情数据",
                }

            amplitude_pct = (day_high - day_low) / day_low * 100
            has_opportunity = amplitude_pct >= TTradeService.MIN_AMPLITUDE_PCT

            if has_opportunity:
                price_range = day_high - day_low
                suggested_buy = round(day_low + price_range * 0.1, 2)
                suggested_sell = round(day_high - price_range * 0.1, 2)
            else:
                suggested_buy = 0
                suggested_sell = 0

            msg = (
                f"日内振幅 {amplitude_pct:.2f}%（实时行情），{'存在' if has_opportunity else '不存在'}做T机会"
            )

            return {
                "success": True,
                "has_opportunity": has_opportunity,
                "stock_code": stock_code,
                "amplitude_pct": round(amplitude_pct, 2),
                "suggested_buy_price": suggested_buy,
                "suggested_sell_price": suggested_sell,
                "high": round(day_high, 2),
                "low": round(day_low, 2),
                "current_price": round(current_price, 2),
                "kline_count": 0,
                "message": msg,
            }
        except Exception as e:
            return {
                "success": False,
                "has_opportunity": False,
                "stock_code": stock_code,
                "error": str(e),
                "message": f"实时行情获取失败: {e}",
            }

    # ═══════════════════════════════════════════════════════
    # 执行做T交易
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def execute_t_trade(
        db: Session,
        account_id: int,
        stock_code: str,
        buy_price: float,
        sell_price: float,
        quantity: int,
        strategy_reason: str = "",
    ) -> Dict[str, Any]:
        """执行做T交易（事务化：卖→买原子操作，任一失败回滚）

        做T流程（先卖后买）：
        1. 冷却期检查：当日是否已做T
        2. 检查可用持仓
        3. 卖出（市价单，auto_commit=False）
        4. 买入（市价单，auto_commit=False）
        5. 任一失败 db.rollback()，持仓/资金完全不变
        6. 创建做T记录并 commit

        Args:
            db: 数据库会话
            account_id: 账户ID
            stock_code: 股票代码
            buy_price: 买入价格
            sell_price: 卖出价格
            quantity: 做T数量（股）
            strategy_reason: 做T理由

        Returns:
            执行结果字典
        """
        from app.services.order_service import OrderService

        # ── 参数校验 ──
        if buy_price <= 0 or sell_price <= 0:
            return {"success": False, "error": "买入价和卖出价必须大于0"}
        if quantity <= 0 or quantity % 100 != 0:
            return {"success": False, "error": "做T数量必须是100的正整数倍"}
        if sell_price <= buy_price:
            return {"success": False, "error": "卖出价必须大于买入价"}

        # ── 实时价格校验：基于当日波动率判断做T可行性 ──
        # 修复说明（P0-1）：
        # 原逻辑将 sell_price 强制≥current_price 且 buy_price 强制≤current_price*0.994，
        # 保证至少 0.6% 价差，做T几乎不可能亏损——这是"必赢模式"。
        # 真实做T应基于当日分钟K线判断：
        #   - 卖出价 ≤ 当日最高价（卖得掉）
        #   - 买入价 ≥ 当日最低价（买得回）
        #   - 两者价差 = 真实可获取的做T利润（可能为负，反映做T失败）
        try:
            quotes = TencentSource.get_quotes([stock_code])
            q = quotes.get(stock_code, {})
            current_price = q.get("price", 0)
            # 当日最高/最低价（来自实时行情）
            day_high = q.get("high", 0) or current_price
            day_low = q.get("low", 0) or current_price
            if current_price > 0:
                # 卖出价校验：必须 ≤ 当日最高价（否则不可能成交）
                if sell_price > day_high:
                    sell_price = day_high
                # 买入价校验：必须 ≥ 当日最低价（否则不可能成交）
                if buy_price < day_low:
                    buy_price = day_low
                # 真实价差校验：若卖出价 ≤ 买入价，做T必然亏损
                # 不再强制放大价差，让做T有真实失败概率
                if sell_price <= buy_price:
                    # 价差倒挂：按现价平价成交，承担费用损失（模拟"做T失败但勉强平仓"）
                    sell_price = current_price
                    buy_price = current_price
                    logger.info(
                        f"做T价差倒挂({stock_code}) 采用平价成交 sell=buy={current_price:.2f}"
                    )
        except Exception as e:
            logger.warning(f"做T实时价格校验失败，使用原始价格: {e}")

        # ── 冷却期检查：当日是否已做T（包括已平仓和未平仓） ──
        today_str = date.today().strftime("%Y-%m-%d")
        existing = db.query(SimTTrade).filter(
            and_(
                SimTTrade.account_id == account_id,
                SimTTrade.stock_code == stock_code,
                SimTTrade.buy_date == today_str,
            )
        ).first()
        if existing:
            return {"success": False, "error": f"{stock_code} 当日已做T，冷却期内"}

        # ── 风控检查：是否有 pending 止损/止盈委托单 ──
        pending_risk_order = db.query(SimOrder).filter(
            and_(
                SimOrder.account_id == account_id,
                SimOrder.stock_code == stock_code,
                SimOrder.order_type == "sell",
                SimOrder.status.in_(["pending", "partial"]),
                SimOrder.strategy_name.in_(["stop_loss", "take_profit", "trailing_stop", "time_stop"]),
            )
        ).first()
        if pending_risk_order:
            return {
                "success": False,
                "error": f"{stock_code} 已有 pending 风控委托单(#{pending_risk_order.id})，跳过做T避免冲突",
            }

        # ── 查询持仓，检查可用数量 ──
        position = db.query(SimPosition).filter(
            and_(
                SimPosition.account_id == account_id,
                SimPosition.stock_code == stock_code,
            )
        ).first()

        if not position:
            return {
                "success": False,
                "error": f"未持有 {stock_code}，做T需要先有底仓",
            }

        # T+1 显式校验：当日新买入的持仓不可做T（避免 available_quantity 异常时绕过）
        today_str_check = date.today().strftime("%Y-%m-%d")
        if position.buy_date == today_str_check:
            return {
                "success": False,
                "error": f"{stock_code} 当日新买入，T+1 规则不可做T（需待下一交易日）",
            }

        if position.available_quantity < quantity:
            return {
                "success": False,
                "error": (
                    f"可用持仓不足，当前可用 {position.available_quantity} 股，"
                    f"需要 {quantity} 股"
                ),
            }

        stock_name = position.stock_name or stock_code
        now = datetime.now()
        now_time = now.strftime("%H:%M:%S")

        # ── 事务化执行：先卖后买 ──
        try:
            # 保存原始买入日期（做T清仓回补后需保留）
            original_buy_date = position.buy_date

            # 1. 卖出（使用校验后的 sell_price）
            sell_result = OrderService.execute_market_order(
                db=db,
                account_id=account_id,
                stock_code=stock_code,
                stock_name=stock_name,
                order_type="sell",
                quantity=quantity,
                price=sell_price,
                strategy_name="t_trade",
                strategy_reason=f"做T卖出 - {strategy_reason}" if strategy_reason else "做T卖出",
                order_source="t_trade",
                auto_commit=False,
            )
            if not sell_result.get("success"):
                db.rollback()
                return {"success": False, "error": f"做T卖出失败: {sell_result.get('error')}"}

            # 获取执行时的实时成交价
            actual_sell_price = sell_result.get("price", sell_price)

            # 2. 买入（使用校验后的 buy_price）
            buy_result = OrderService.execute_market_order(
                db=db,
                account_id=account_id,
                stock_code=stock_code,
                stock_name=stock_name,
                order_type="buy",
                quantity=quantity,
                price=buy_price,
                strategy_name="t_trade",
                strategy_reason=f"做T买入 - {strategy_reason}" if strategy_reason else "做T买入",
                position_type=position.position_type,
                order_source="t_trade",
                auto_commit=False,
            )
            if not buy_result.get("success"):
                # 买入失败——回滚整个事务（卖出也被撤销，持仓/资金完全不变）
                db.rollback()
                logger.error(f"做T买入失败，回滚整个事务: {buy_result.get('error')}")
                return {"success": False, "error": f"做T买入失败: {buy_result.get('error')}"}

            # 做T清仓回补：如果卖出导致持仓被删除并新建，恢复原始 buy_date
            new_position = db.query(SimPosition).filter(
                and_(
                    SimPosition.account_id == account_id,
                    SimPosition.stock_code == stock_code,
                )
            ).first()
            if new_position and new_position.buy_date != original_buy_date:
                new_position.buy_date = original_buy_date

            # 3. 计算做T费用和收益（使用实际成交价）
            actual_buy_price = buy_result.get("price", buy_price)
            actual_sell_price = sell_result.get("filled_price", sell_price)
            buy_amount = actual_buy_price * quantity
            sell_amount = actual_sell_price * quantity

            buy_commission = max(buy_amount * TTradeService.COMMISSION_RATE, TTradeService.MIN_COMMISSION)
            buy_transfer_fee = buy_amount * TTradeService.TRANSFER_FEE_RATE

            sell_commission = max(sell_amount * TTradeService.COMMISSION_RATE, TTradeService.MIN_COMMISSION)
            sell_stamp_tax = sell_amount * TTradeService.STAMP_TAX_RATE
            sell_transfer_fee = sell_amount * TTradeService.TRANSFER_FEE_RATE

            total_fees = buy_commission + buy_transfer_fee + sell_commission + sell_stamp_tax + sell_transfer_fee

            profit = sell_amount - buy_amount - total_fees
            profit_ratio = (profit / buy_amount * 100) if buy_amount > 0 else 0

            # 4. 创建做T记录
            t_trade = SimTTrade(
                account_id=account_id,
                stock_code=stock_code,
                stock_name=stock_name,
                buy_price=round(actual_buy_price, 3),
                buy_quantity=quantity,
                buy_date=today_str,
                buy_time=now_time,
                buy_amount=round(buy_amount, 2),
                buy_commission=round(buy_commission + buy_transfer_fee, 2),
                sell_price=round(actual_sell_price, 3),
                sell_quantity=quantity,
                sell_date=today_str,
                sell_time=now_time,
                sell_amount=round(sell_amount, 2),
                sell_commission=round(sell_commission + sell_transfer_fee, 2),
                stamp_tax=round(sell_stamp_tax, 2),
                quantity=quantity,
                hold_minutes=0,
                hold_days=0,
                profit=round(profit, 2),
                profit_ratio=round(profit_ratio, 4),
                status="closed",
                strategy_name="t_trade",
                strategy_reason=strategy_reason,
            )
            db.add(t_trade)
            db.commit()
            db.refresh(t_trade)

            logger.info(
                f"做T完成: {stock_code} 买{buy_price}x{quantity} "
                f"卖{sell_price}x{quantity} 收益={profit:.2f}({profit_ratio:.2f}%)"
            )

            return {
                "success": True,
                "t_trade_id": t_trade.id,
                "stock_code": stock_code,
                "stock_name": stock_name,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "quantity": quantity,
                "buy_amount": round(buy_amount, 2),
                "sell_amount": round(sell_amount, 2),
                "total_fees": round(total_fees, 2),
                "profit": round(profit, 2),
                "profit_ratio": round(profit_ratio, 4),
                "trade_date": today_str,
                "trade_time": now_time,
                "message": (
                    f"做T{'盈利' if profit >= 0 else '亏损'} "
                    f"{abs(profit):.2f}元 ({abs(profit_ratio):.2f}%)"
                ),
            }
        except Exception as e:
            db.rollback()
            logger.error(f"做T事务异常 ({stock_code}): {e}")
            return {"success": False, "error": f"做T事务异常: {str(e)}"}

    # ═══════════════════════════════════════════════════════
    # 获取做T历史
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def get_t_trade_history(
        db: Session,
        account_id: int,
        trade_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取做T历史记录

        Args:
            db: 数据库会话
            account_id: 账户ID
            trade_date: 交易日期（可选，格式 YYYY-MM-DD）

        Returns:
            {
                "success": True,
                "trades": [...],
                "summary": {
                    "total_count": int,
                    "profit_count": int,
                    "loss_count": int,
                    "total_profit": float,
                    "avg_profit": float,
                }
            }
        """
        query = db.query(SimTTrade).filter(
            SimTTrade.account_id == account_id
        )

        if trade_date:
            query = query.filter(
                and_(
                    SimTTrade.buy_date == trade_date,
                    SimTTrade.status == "closed",
                )
            )
        else:
            query = query.filter(SimTTrade.status == "closed")

        trades = query.order_by(SimTTrade.created_at.desc()).all()

        trade_list = []
        for t in trades:
            trade_list.append({
                "id": t.id,
                "trade_id": t.id,
                "stock_code": t.stock_code,
                "stock_name": t.stock_name,
                "buy_price": t.buy_price,
                "buy_quantity": t.buy_quantity,
                "buy_date": t.buy_date,
                "buy_time": t.buy_time,
                "buy_amount": t.buy_amount,
                "buy_commission": t.buy_commission,
                "sell_price": t.sell_price,
                "sell_quantity": t.sell_quantity,
                "sell_date": t.sell_date,
                "sell_time": t.sell_time,
                "sell_amount": t.sell_amount,
                "sell_commission": t.sell_commission,
                "stamp_tax": t.stamp_tax,
                "quantity": t.quantity,
                "hold_minutes": t.hold_minutes,
                "hold_days": t.hold_days,
                "profit": t.profit,
                "profit_ratio": t.profit_ratio,
                "status": t.status,
                "trade_status": t.status,
                "strategy_name": t.strategy_name,
                "strategy_reason": t.strategy_reason,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "create_time": t.created_at.isoformat() if t.created_at else None,
            })

        # ── 计算统计信息 ──
        profit_count = sum(1 for t in trades if t.profit is not None and t.profit > 0)
        loss_count = sum(1 for t in trades if t.profit is not None and t.profit <= 0)
        total_profit = sum(t.profit or 0 for t in trades)
        avg_profit = total_profit / len(trades) if trades else 0

        summary = {
            "total_count": len(trades),
            "profit_count": profit_count,
            "loss_count": loss_count,
            "win_rate": round(profit_count / len(trades) * 100, 2) if trades else 0,
            "total_profit": round(total_profit, 2),
            "avg_profit": round(avg_profit, 2),
        }

        return {
            "success": True,
            "trades": trade_list,
            "summary": summary,
        }

    # ═══════════════════════════════════════════════════════
    # 批量检测做T机会（盘中监控调用）
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def detect_opportunities(db: Session, account_id: int) -> Dict[str, Any]:
        """扫描账户所有持仓，自动检测并执行做T机会

        流程：
        1. 获取账户所有有可用底仓的持仓
        2. 对每只股票检测日内振幅
        3. 振幅达标且价差可覆盖费用时，自动执行做T

        Args:
            db: 数据库会话
            account_id: 账户ID

        Returns:
            检测结果摘要
        """
        positions = db.query(SimPosition).filter(
            and_(
                SimPosition.account_id == account_id,
                SimPosition.available_quantity >= TTradeService.DEFAULT_T_QUANTITY,
            )
        ).all()

        if not positions:
            return {"success": True, "scanned": 0, "opportunities": 0, "executed": 0}

        # 查询当日已做T的股票集合，排除重复做T
        today_str = date.today().strftime("%Y-%m-%d")
        traded_codes = set(
            r[0] for r in db.query(SimTTrade.stock_code).filter(
                and_(
                    SimTTrade.account_id == account_id,
                    SimTTrade.buy_date == today_str,
                    SimTTrade.status == "closed",
                )
            ).all()
        )

        # T+1 显式过滤：当日新买入的持仓不可做T（双保险，避免 available_quantity 异常时绕过）
        positions = [p for p in positions if p.buy_date != today_str]

        scanned = 0
        executed = 0
        details = []

        for pos in positions:
            scanned += 1
            if pos.stock_code in traded_codes:
                continue
            try:
                # 趋势判断：用5日均线斜率判断，仅在强烈下跌趋势时跳过（原来过于严格）
                klines = pytdx_data.get_kline(pos.stock_code, period=6, count=5)
                strong_downtrend = False
                if klines and len(klines) >= 3:
                    closes = [k["close"] for k in klines]
                    mid = len(closes) // 2
                    avg_first = sum(closes[:mid]) / mid if mid > 0 else closes[0]
                    avg_second = sum(closes[mid:]) / (len(closes) - mid) if len(closes) > mid else closes[-1]
                    # 仅当后半段比前半段低 2% 以上才判定为强下跌趋势（原代码任何下跌都跳过）
                    if avg_first > 0 and (avg_second / avg_first - 1) * 100 < -2:
                        strong_downtrend = True

                if strong_downtrend:
                    continue

                # 获取现价用于网格做T判断
                current_price = 0.0
                try:
                    quotes = TencentSource.get_quotes([pos.stock_code])
                    if quotes and pos.stock_code in quotes:
                        current_price = float(quotes[pos.stock_code].get("price", 0))
                except Exception:
                    pass

                # ── 优先尝试网格做T（基于持仓成本偏离）──
                # 网格做T：现价偏离成本价 >= 动态阈值时触发
                # P1-6：阈值按个股波动率自适应：
                #   - 高波动股（创业板/科技股，ATR% > 3%）：阈值放大到 3-4%（避免误触发）
                #   - 低波动股（银行/白马，ATR% < 1%）：阈值缩小到 1-1.5%（不错过机会）
                #   - 计算：deviation_threshold = max(1.0, min(4.0, atr_pct * 0.8))
                grid_executed = False
                if (current_price > 0
                    and pos.cost_price and pos.cost_price > 0
                    and pos.available_quantity >= 100):
                    deviation_pct = (current_price / pos.cost_price - 1) * 100

                    # P1-6：基于 ATR 计算动态偏离阈值
                    atr_value = getattr(pos, "atr_value", None) or 0
                    if atr_value > 0 and pos.cost_price > 0:
                        # ATR% = ATR / 成本价 * 100
                        atr_pct = atr_value / pos.cost_price * 100
                        # 阈值 = ATR% × 0.8，限制在 [1.0, 4.0] 区间
                        dynamic_threshold = max(1.0, min(4.0, atr_pct * 0.8))
                    else:
                        # 无 ATR 时回退到默认常量
                        dynamic_threshold = TTradeService.GRID_T_DEVIATION_PCT

                    if abs(deviation_pct) >= dynamic_threshold:
                        # 做T数量：取可用持仓的1/4，最少100股，最多1000股
                        t_qty = min(1000, max(100, pos.available_quantity // 4))
                        t_qty = (t_qty // 100) * 100

                        if t_qty >= 100:
                            # P1-6：网格价差也按 ATR 自适应（高波动股扩大价差，低波动股缩小价差）
                            if atr_value > 0 and pos.cost_price > 0:
                                atr_pct = atr_value / pos.cost_price * 100
                                # 价差 = ATR% × 0.5，限制在 [0.5%, 3%]
                                dynamic_step = max(0.005, min(0.03, atr_pct * 0.005))
                            else:
                                dynamic_step = TTradeService.GRID_T_PRICE_STEP

                            # 正T（浮盈时）：先卖后买，卖高价买低价
                            # 反T（浮亏时）：先卖后买（卖低位等更低位接回），
                            #   由于execute_t_trade是先卖后买，反T需要更谨慎
                            # 这里两种情况都用先卖后买，价差由 dynamic_step 控制
                            if deviation_pct > 0:
                                # 浮盈：卖出价=现价，买回价=现价×(1-step)
                                g_sell = current_price
                                g_buy = round(current_price * (1 - dynamic_step), 2)
                                reason = f"网格T(浮盈{deviation_pct:.2f}% 阈值{dynamic_threshold:.2f}%)"
                            else:
                                # 浮亏：卖出价=现价，买回价=现价×(1-step)更低
                                # 风险：浮亏时做T若买不回会扩大亏损，但execute_t_trade原子化保证回补
                                g_sell = current_price
                                g_buy = round(current_price * (1 - dynamic_step), 2)
                                reason = f"网格T(浮亏{deviation_pct:.2f}% 阈值{dynamic_threshold:.2f}%)降本"

                            exec_result = TTradeService.execute_t_trade(
                                db=db,
                                account_id=account_id,
                                stock_code=pos.stock_code,
                                buy_price=g_buy,
                                sell_price=g_sell,
                                quantity=t_qty,
                                strategy_reason=reason,
                            )
                            details.append({
                                "stock_code": pos.stock_code,
                                "stock_name": pos.stock_name,
                                "amplitude_pct": 0,
                                "mode": "grid",
                                **exec_result,
                            })
                            if exec_result.get("success"):
                                executed += 1
                                grid_executed = True

                # ── 网格做T未触发，回退到振幅检测 ──
                if not grid_executed:
                    result = TTradeService.detect_t_opportunity(db, pos.stock_code)
                    if not result.get("success") or not result.get("has_opportunity"):
                        continue

                    buy_price = result.get("suggested_buy_price", 0)
                    sell_price = result.get("suggested_sell_price", 0)
                    if buy_price <= 0 or sell_price <= 0:
                        continue

                    price_diff_pct = (sell_price - buy_price) / buy_price * 100
                    if price_diff_pct < 0.6:
                        continue

                    actual_buy = result.get("suggested_buy_price", buy_price)
                    actual_sell = result.get("suggested_sell_price", sell_price)

                    # 做T数量：取可用持仓的1/3，最少100股，最多1000股
                    quantity = min(1000, max(100, pos.available_quantity // 3))
                    quantity = (quantity // 100) * 100

                    if quantity < 100:
                        continue

                    exec_result = TTradeService.execute_t_trade(
                        db=db,
                        account_id=account_id,
                        stock_code=pos.stock_code,
                        buy_price=actual_buy,
                        sell_price=actual_sell,
                        quantity=quantity,
                        strategy_reason=f"振幅T(日内{result.get('amplitude_pct', 0):.2f}%)",
                    )

                    details.append({
                        "stock_code": pos.stock_code,
                        "stock_name": pos.stock_name,
                        "amplitude_pct": result.get("amplitude_pct", 0),
                        "mode": "amplitude",
                        **exec_result,
                    })

                    if exec_result.get("success"):
                        executed += 1
            except Exception as e:
                logger.warning(f"做T检测异常 ({pos.stock_code}): {e}")

        return {
            "success": True,
            "scanned": scanned,
            "opportunities": len(details),
            "executed": executed,
            "details": details,
        }

    # ═══════════════════════════════════════════════════════
    # 做T统计
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def get_t_trade_stats(db: Session, account_id: int) -> Dict[str, Any]:
        """做T统计信息

        Args:
            db: 数据库会话
            account_id: 账户ID

        Returns:
            {
                "success": True,
                "total_count": int,           # 总做T次数
                "profit_count": int,          # 成功次数（盈利）
                "loss_count": int,            # 失败次数（亏损）
                "win_rate": float,            # 胜率(%)
                "total_profit": float,        # 累计收益（元）
                "total_profit_ratio": float,  # 累计收益率(%)
                "avg_profit_ratio": float,    # 平均收益率(%)
                "max_profit": float,          # 最大单笔盈利
                "min_profit": float,          # 最大单笔亏损
                "avg_hold_minutes": float,    # 平均持仓时间（分钟）
            }
        """
        trades = db.query(SimTTrade).filter(
            and_(
                SimTTrade.account_id == account_id,
                SimTTrade.status == "closed",
            )
        ).all()

        if not trades:
            return {
                "success": True,
                "total_count": 0,
                "profit_count": 0,
                "loss_count": 0,
                "win_rate": 0,
                "total_profit": 0,
                "total_profit_ratio": 0,
                "avg_profit_ratio": 0,
                "max_profit": 0,
                "min_profit": 0,
                "avg_hold_minutes": 0,
            }

        total_count = len(trades)
        profit_count = sum(1 for t in trades if t.profit is not None and t.profit > 0)
        loss_count = sum(1 for t in trades if t.profit is not None and t.profit <= 0)
        win_rate = round(profit_count / total_count * 100, 2)

        total_profit = sum(t.profit or 0 for t in trades)
        total_buy_amount = sum(t.buy_amount or 0 for t in trades)
        total_profit_ratio = (
            round(total_profit / total_buy_amount * 100, 4)
            if total_buy_amount > 0
            else 0
        )

        # 平均收益率
        valid_ratios = [t.profit_ratio for t in trades if t.profit_ratio is not None]
        avg_profit_ratio = (
            round(sum(valid_ratios) / len(valid_ratios), 4)
            if valid_ratios
            else 0
        )

        # 最大单笔盈亏
        profits = [t.profit for t in trades if t.profit is not None]
        max_profit = max(profits) if profits else 0
        min_profit = min(profits) if profits else 0

        # 平均持仓时间
        hold_minutes_list = [
            t.hold_minutes for t in trades
            if t.hold_minutes is not None and t.hold_minutes > 0
        ]
        avg_hold_minutes = (
            round(sum(hold_minutes_list) / len(hold_minutes_list), 1)
            if hold_minutes_list
            else 0
        )

        return {
            "success": True,
            "total_count": total_count,
            "profit_count": profit_count,
            "loss_count": loss_count,
            "win_rate": win_rate,
            "total_profit": round(total_profit, 2),
            "total_profit_ratio": total_profit_ratio,
            "avg_profit_ratio": avg_profit_ratio,
            "max_profit": round(max_profit, 2),
            "min_profit": round(min_profit, 2),
            "avg_hold_minutes": avg_hold_minutes,
        }
