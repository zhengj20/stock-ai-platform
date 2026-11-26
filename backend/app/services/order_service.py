"""委托单撮合服务 - 阶段2: 服务层

负责委托单的创建、撮合、成交、撤销和过期处理。
"""
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Any

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.sim_trading import (
    SimAccount, SimPosition, SimTrade, SimOrder
)
from app.services.trade_engine import TradeEngine
from app.core.data_sources import TencentSource
from app.core.cache import cache_get, cache_set, cache_delete

logger = logging.getLogger(__name__)


class OrderService:
    """委托单撮合服务"""

    @staticmethod
    def _calc_buy_frozen_amount(order_price: float, quantity: int) -> float:
        """计算买入委托冻结的总资金（含手续费），确保冻结/解冻金额一致"""
        trade_amount = order_price * quantity
        commission, _, transfer_fee = TradeEngine.calculate_commission(trade_amount, "buy")
        return trade_amount + commission + transfer_fee

    # ═══════════════════════════════════════════════════════
    # 创建委托单
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def create_order(
        db: Session,
        account_id: int,
        stock_code: str,
        stock_name: str,
        order_type: str,           # "buy" | "sell"
        order_price: float,
        order_quantity: int,
        expire_type: str = "day",  # "day" | "gtc" | "3day"
        position_type: str = "short",  # short=短线, mid=中线, long=长线
        strategy_name: str = "",
        strategy_reason: str = "",
        order_source: str = "manual",  # ai_strategy/manual/risk_control/auto_close_short/t_trade
    ) -> Dict[str, Any]:
        """创建委托单

        流程:
        1. 校验参数合法性
        2. 校验资金/持仓是否充足
        3. 计算委托金额，冻结资金或持仓
        4. 写入 SimOrder 记录（status=pending）
        """
        # ── 参数校验 ──
        if order_type not in ("buy", "sell"):
            return {"success": False, "error": f"无效的委托类型: {order_type}"}

        if order_price <= 0:
            return {"success": False, "error": "委托价格必须大于 0"}

        if order_quantity <= 0:
            return {"success": False, "error": "委托数量必须大于 0"}

        # A股最小交易单位：买入必须为 100 的整数倍（科创板/创业板可 1 股起）
        if order_type == "buy" and order_quantity % 100 != 0:
            return {"success": False, "error": "买入数量必须是 100 的整数倍"}

        # ── 查询账户 ──
        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
        if not account:
            return {"success": False, "error": "账户不存在"}

        # ── 计算委托金额 ──
        order_amount = order_price * order_quantity
        commission, stamp_tax, transfer_fee = TradeEngine.calculate_commission(
            order_amount, order_type
        )
        total_cost = order_amount + commission + transfer_fee

        # ── 资金 / 持仓校验 & 冻结 ──
        now = datetime.now()

        if order_type == "buy":
            if total_cost > (account.current_capital or 0):
                return {
                    "success": False,
                    "error": f"资金不足，需要 {total_cost:.2f}，可用 {account.current_capital:.2f}",
                }
            # 冻结资金：可用资金减少，冻结资金增加
            account.current_capital = (account.current_capital or 0) - total_cost
            account.frozen_capital = (account.frozen_capital or 0) + total_cost

        elif order_type == "sell":
            position = db.query(SimPosition).filter(
                and_(
                    SimPosition.account_id == account_id,
                    SimPosition.stock_code == stock_code,
                )
            ).first()

            if not position:
                return {"success": False, "error": f"未持有 {stock_code}"}

            if order_quantity > (position.available_quantity or 0):
                return {
                    "success": False,
                    "error": f"可卖数量不足，可卖 {position.available_quantity}，"
                             f"请求卖出 {order_quantity}",
                }

            # 冻结持仓：可卖数量减少（总持仓不变）
            position.available_quantity = (position.available_quantity or 0) - order_quantity

        # ── 计算过期时间 ──
        expire_date, expire_time = OrderService._calc_expire(now, expire_type)

        # ── 创建委托单 ──
        order = SimOrder(
            account_id=account_id,
            stock_code=stock_code,
            stock_name=stock_name,
            order_type=order_type,
            order_quantity=order_quantity,
            limit_price=order_price,       # 限价单价格
            order_price=order_price,       # 委托价格快照
            status="pending",
            filled_quantity=0,
            filled_price=None,
            filled_amount=0.0,
            commission=0.0,
            expire_date=expire_date,
            expire_time=expire_time,
            position_type=position_type,
            strategy_name=strategy_name,
            strategy_reason=strategy_reason,
            order_source=order_source,
        )
        db.add(order)

        # 更新账户总资产
        OrderService._refresh_account_assets(db, account)

        db.commit()
        db.refresh(order)

        logger.info(
            f"委托单创建成功: id={order.id}, {order_type} {stock_code} "
            f"{order_quantity}股@{order_price}, 总费用={total_cost:.2f}"
        )

        return {
            "success": True,
            "order_id": order.id,
            "order_type": order_type,
            "stock_code": stock_code,
            "stock_name": stock_name,
            "order_price": order_price,
            "order_quantity": order_quantity,
            "order_amount": order_amount,
            "total_cost": round(total_cost, 2),
            "commission": commission,
            "stamp_tax": stamp_tax,
            "transfer_fee": transfer_fee,
            "expire_date": expire_date,
            "expire_time": expire_time,
            "status": "pending",
        }

    # ═══════════════════════════════════════════════════════
    # 撮合委托单（盘中调用）
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def match_orders(db: Session, account_id: int, force: bool = False) -> Dict[str, Any]:
        """撮合指定账户的所有待成交委托单

        撮合规则：
        - 买单：当前价 <= 委托价 → 成交
        - 卖单：当前价 >= 委托价 → 成交

        非交易时段（午间休市/盘后/节假日）默认不撮合，A股 T+1 规则要求订单必须在交易时段内才能成交。
        force=True 时跳过交易时段检查，供用户手动触发撮合（模拟系统允许非交易时段撮合）。

        Returns:
            成交结果摘要
        """
        from app.core.trading_calendar import is_trading_hours

        if not force and not is_trading_hours():
            return {
                "success": True,
                "matched_count": 0,
                "details": [],
                "skipped": "非交易时段不撮合（可传 force=true 手动触发）",
            }

        # 获取所有待成交委托单
        pending_orders = db.query(SimOrder).filter(
            and_(
                SimOrder.account_id == account_id,
                SimOrder.status.in_(["pending", "partial"]),
            )
        ).all()

        if not pending_orders:
            return {"success": True, "matched_count": 0, "details": []}

        # 收集需要查询行情的股票代码
        stock_codes = list(set(o.stock_code for o in pending_orders))

        # 获取实时行情（优先从缓存读取）
        quotes = OrderService._get_realtime_quotes(stock_codes)

        matched_details = []
        matched_count = 0

        for order in pending_orders:
            quote = quotes.get(order.stock_code)
            if not quote or quote.get("price", 0) <= 0:
                # 行情不可用，跳过
                continue

            current_price = quote["price"]

            # 撮合判断
            can_match = False
            if order.order_type == "buy" and current_price <= order.order_price:
                can_match = True
            elif order.order_type == "sell" and current_price >= order.order_price:
                can_match = True

            if can_match:
                if order.order_type == "buy":
                    result = OrderService.execute_buy_order(db, order, current_price)
                else:
                    result = OrderService.execute_sell_order(db, order, current_price)

                matched_count += 1
                matched_details.append({
                    "order_id": order.id,
                    "stock_code": order.stock_code,
                    "order_type": order.order_type,
                    "order_price": order.order_price,
                    "matched_price": current_price,
                    "quantity": order.order_quantity,
                    **result,
                })

        if matched_count > 0:
            db.commit()
            # 清除账户缓存
            cache_delete(f"sim_account:{account_id}", namespace="sim")
            logger.info(f"撮合完成: 账户 {account_id} 共成交 {matched_count} 笔")

        return {
            "success": True,
            "matched_count": matched_count,
            "total_pending": len(pending_orders),
            "details": matched_details,
        }

    # ═══════════════════════════════════════════════════════
    # 执行买入成交
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def execute_buy_order(db: Session, order: SimOrder, price: float, from_market_order: bool = False) -> Dict[str, Any]:
        """执行买入成交

        1. 释放委托时冻结的资金（限价单路径；市价单跳过）
        2. 按成交价计算实际费用
        3. 扣减可用资金
        4. 创建交易记录
        5. 更新/创建持仓（加仓时锁定T+1新份额）
        6. 更新委托单状态

        Args:
            from_market_order: True=市价单直接成交，跳过冻结释放步骤
        """
        account = db.query(SimAccount).filter(SimAccount.id == order.account_id).first()
        if not account:
            return {"success": False, "error": "账户不存在"}

        quantity = order.order_quantity

        # ── 步骤1: 释放委托时冻结的资金（仅限价单路径）──
        if not from_market_order:
            frozen_amount = OrderService._calc_buy_frozen_amount(order.order_price, quantity)
            release = frozen_amount
            if (account.frozen_capital or 0) + 0.01 < release:
                logger.warning(
                    f"成交订单 {order.id}: 账户冻结资金 {account.frozen_capital:.2f} < 应释放 {release:.2f}，"
                    f"可能存在历史数据不一致，按订单金额释放"
                )
            account.frozen_capital = (account.frozen_capital or 0) - release
            account.current_capital = (account.current_capital or 0) + release

        # ── 步骤2: 按成交价计算实际费用 ──
        trade_amount = price * quantity
        commission, stamp_tax, transfer_fee = TradeEngine.calculate_commission(
            trade_amount, "buy"
        )
        actual_total_cost = trade_amount + commission + transfer_fee

        # ── 步骤3: 扣减可用资金 ──
        account.current_capital = (account.current_capital or 0) - actual_total_cost

        # ── 步骤4: 创建交易记录 ──
        now = datetime.now()
        trade = SimTrade(
            account_id=order.account_id,
            stock_code=order.stock_code,
            stock_name=order.stock_name,
            trade_type="buy",
            trade_price=price,
            trade_quantity=quantity,
            trade_amount=trade_amount,
            commission=commission,
            stamp_tax=stamp_tax,
            transfer_fee=transfer_fee,
            total_cost=actual_total_cost,
            trade_date=now.strftime("%Y-%m-%d"),
            trade_time=now.strftime("%H:%M:%S"),
            strategy_name=order.strategy_name,
            strategy_reason=order.strategy_reason,
            position_type=order.position_type,
            trade_source=getattr(order, 'order_source', None) or "manual",
        )
        db.add(trade)

        # ── 步骤5: 更新 / 创建持仓 ──
        position = db.query(SimPosition).filter(
            and_(
                SimPosition.account_id == order.account_id,
                SimPosition.stock_code == order.stock_code,
            )
        ).first()

        if position:
            # 加仓：计算新的平均成本价，新份额自动T+1锁定（不增加available_quantity）
            total_cost_basis = (position.cost_price or 0) * (position.total_quantity or 0) + trade_amount
            position.total_quantity = (position.total_quantity or 0) + quantity
            # 新买入的份额不增加 available_quantity，自然实现 T+1 锁定
            # 原有可卖份额不受影响
            position.cost_price = total_cost_basis / position.total_quantity if position.total_quantity else price
            position.current_price = price
            position.market_value = position.total_quantity * price
            position.profit = (price - position.cost_price) * position.total_quantity
            position.profit_ratio = (
                (price / position.cost_price - 1) * 100 if position.cost_price > 0 else 0
            )
        else:
            # 新建持仓
            position = SimPosition(
                account_id=order.account_id,
                stock_code=order.stock_code,
                stock_name=order.stock_name,
                total_quantity=quantity,
                available_quantity=0,          # T+1: 当天买入不可卖出
                cost_price=price,
                current_price=price,
                market_value=trade_amount,
                profit=0,
                profit_ratio=0,
                position_type=order.position_type,
                buy_date=now.strftime("%Y-%m-%d"),
                buy_reason=order.strategy_reason,
                atr_value=0.0,  # 默认0，下方同步计算
            )
            db.add(position)
            # 同步计算 ATR(14)，用于动态止损（计算失败不影响成交）
            try:
                from app.core.pytdx_source import pytdx_data
                klines = pytdx_data.get_kline(order.stock_code, period=6, count=20)
                if klines and len(klines) >= 14:
                    trs = [
                        max(
                            klines[i]["high"] - klines[i]["low"],
                            abs(klines[i]["high"] - klines[i - 1]["close"]),
                            abs(klines[i]["low"] - klines[i - 1]["close"]),
                        )
                        for i in range(1, len(klines))
                    ]
                    position.atr_value = round(sum(trs[-14:]) / min(14, len(trs)), 4)
            except Exception as e:
                logger.debug(f"新建持仓ATR计算失败 {order.stock_code}: {e}")

        # ── 步骤6: 更新委托单状态 ──
        order.status = "filled"
        order.filled_quantity = quantity
        order.filled_price = price
        order.filled_amount = trade_amount
        order.commission = commission

        # ── 刷新账户总资产 ──
        OrderService._refresh_account_assets(db, account)

        logger.info(
            f"买入成交: {order.stock_code} {quantity}股@{price}, "
            f"金额={trade_amount:.2f}, 佣金={commission:.2f}"
        )

        return {
            "success": True,
            "trade_id": trade.id,
            "trade_amount": round(trade_amount, 2),
            "commission": commission,
            "stamp_tax": stamp_tax,
            "transfer_fee": transfer_fee,
            "actual_total_cost": round(actual_total_cost, 2),
            "remaining_capital": round(account.current_capital, 2),
        }

    # ═══════════════════════════════════════════════════════
    # 执行卖出成交
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def execute_sell_order(db: Session, order: SimOrder, price: float, from_market_order: bool = False) -> Dict[str, Any]:
        """执行卖出成交

        1. 释放创建委托时冻结的持仓（限价单路径；市价单跳过）
        2. 按成交价计算实际费用和盈亏
        3. 增加可用资金
        4. 创建交易记录
        5. 更新/删除持仓
        6. 更新委托单状态

        Args:
            from_market_order: True=市价单直接成交，跳过持仓冻结释放步骤
        """
        account = db.query(SimAccount).filter(SimAccount.id == order.account_id).first()
        if not account:
            return {"success": False, "error": "账户不存在"}

        quantity = order.order_quantity

        # ── 查询持仓 ──
        position = db.query(SimPosition).filter(
            and_(
                SimPosition.account_id == order.account_id,
                SimPosition.stock_code == order.stock_code,
            )
        ).first()

        if not position:
            return {"success": False, "error": f"未持有 {order.stock_code}"}

        # ── 步骤1: 释放冻结的持仓（仅限价单路径）──
        if not from_market_order:
            position.available_quantity = (position.available_quantity or 0) + quantity

        # ── 步骤2: 按成交价计算实际费用和盈亏 ──
        trade_amount = price * quantity
        commission, stamp_tax, transfer_fee = TradeEngine.calculate_commission(
            trade_amount, "sell"
        )
        total_cost = commission + stamp_tax + transfer_fee

        profit = (price - position.cost_price) * quantity - total_cost
        profit_ratio = (
            (price / position.cost_price - 1) * 100 if position.cost_price > 0 else 0
        )

        # ── 步骤3: 增加可用资金（净收入） ──
        net_proceeds = trade_amount - total_cost
        account.current_capital = (account.current_capital or 0) + net_proceeds

        # ── 步骤4: 创建交易记录 ──
        now = datetime.now()
        trade = SimTrade(
            account_id=order.account_id,
            stock_code=order.stock_code,
            stock_name=order.stock_name,
            trade_type="sell",
            trade_price=price,
            trade_quantity=quantity,
            trade_amount=trade_amount,
            commission=commission,
            stamp_tax=stamp_tax,
            transfer_fee=transfer_fee,
            total_cost=total_cost,
            profit=profit,
            profit_ratio=profit_ratio,
            trade_date=now.strftime("%Y-%m-%d"),
            trade_time=now.strftime("%H:%M:%S"),
            strategy_name=order.strategy_name,
            strategy_reason=order.strategy_reason,
            position_type=position.position_type,
            trade_source=getattr(order, 'order_source', None) or "manual",
        )
        db.add(trade)

        # ── 步骤5: 更新 / 删除持仓 ──
        position.total_quantity = (position.total_quantity or 0) - quantity
        position.available_quantity = (position.available_quantity or 0) - quantity

        if position.total_quantity <= 0:
            # 清仓
            db.delete(position)
        else:
            # 部分卖出
            position.current_price = price
            position.market_value = position.total_quantity * price
            position.profit = (price - position.cost_price) * position.total_quantity
            position.profit_ratio = (
                (price / position.cost_price - 1) * 100 if position.cost_price > 0 else 0
            )

        # ── 步骤6: 更新委托单状态 ──
        order.status = "filled"
        order.filled_quantity = quantity
        order.filled_price = price
        order.filled_amount = trade_amount
        order.commission = commission

        # ── 刷新账户总资产 ──
        OrderService._refresh_account_assets(db, account)

        # ── 更新策略统计 ──
        OrderService._update_strategy_stats(db, order.account_id, order.strategy_name, profit, profit_ratio)

        # ── P2-7：失败案例自动记录（亏损卖出时写入 SimFailurePattern）──
        if profit < 0:
            try:
                from app.models.sim_trading import SimFailurePattern
                from datetime import date as _date
                # 推断失败原因分类
                strat = (order.strategy_name or "").lower()
                if "stop_loss" in strat or "stop" in strat:
                    failure_reason = "stop_loss"
                elif "time_stop" in strat:
                    failure_reason = "time_stop"
                elif "trailing" in strat:
                    failure_reason = "trailing_stop"
                elif "auto_close_short" in strat:
                    failure_reason = "auto_close_short"
                else:
                    failure_reason = "manual"
                # 估算持仓天数
                hold_days = None
                if position.buy_date:
                    try:
                        buy_d = _date.fromisoformat(position.buy_date)
                        sell_d = _date.today()
                        hold_days = (sell_d - buy_d).days
                    except Exception:
                        pass
                # 从 buy_reason 中尝试提取 source（AI策略生成时写入）
                source = None
                buy_reason = (position.buy_reason or "").lower()
                for src in ("capital_flow", "gainers", "oversold", "low_absorption", "multi_factor"):
                    if src in buy_reason:
                        source = src
                        break
                if not source:
                    source = "manual"

                failure = SimFailurePattern(
                    account_id=order.account_id,
                    stock_code=order.stock_code,
                    stock_name=order.stock_name or "",
                    source=source,
                    entry_change_pct=None,  # 买入时未记录，留空
                    position_type=position.position_type,
                    hold_days=hold_days,
                    profit_ratio=round(profit_ratio, 2),
                    failure_reason=failure_reason,
                    buy_date=position.buy_date,
                    sell_date=_date.today().strftime("%Y-%m-%d"),
                )
                db.add(failure)
            except Exception as _e:
                logger.warning(f"失败案例记录写入失败: {_e}")

        logger.info(
            f"卖出成交: {order.stock_code} {quantity}股@{price}, "
            f"金额={trade_amount:.2f}, 盈亏={profit:.2f}"
        )

        return {
            "success": True,
            "trade_id": trade.id,
            "trade_amount": round(trade_amount, 2),
            "commission": commission,
            "stamp_tax": stamp_tax,
            "transfer_fee": transfer_fee,
            "total_cost": round(total_cost, 2),
            "profit": round(profit, 2),
            "profit_ratio": round(profit_ratio, 2),
            "remaining_capital": round(account.current_capital, 2),
        }

    # ═══════════════════════════════════════════════════════
    # 市价单立即成交（用于做T和风控止损）
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def execute_market_order(
        db: Session,
        account_id: int,
        stock_code: str,
        stock_name: str,
        order_type: str,           # "buy" | "sell"
        quantity: int,
        price: Optional[float] = None,  # None=自动获取当前价
        strategy_name: str = "",
        strategy_reason: str = "",
        position_type: str = "short",
        order_source: str = "manual",  # ai_strategy/manual/risk_control/auto_close_short/t_trade
        auto_commit: bool = True,  # False时由调用方控制事务（做T原子化）
    ) -> Dict[str, Any]:
        """市价单立即成交

        跳过 create_order 的冻结阶段，直接调用 execute_buy_order/execute_sell_order
        以指定价格或当前实时价立即成交。用于做T和风控止损（必须确定性成交）。

        Args:
            price: 成交价。None时自动获取实时价。
            auto_commit: True时内部commit；False时由调用方控制事务（做T场景）
        """
        # ── 获取价格 ──
        if price is None or price <= 0:
            quotes = OrderService._get_realtime_quotes([stock_code])
            quote = quotes.get(stock_code)
            if not quote or quote.get("price", 0) <= 0:
                return {"success": False, "error": f"无法获取 {stock_code} 实时价格"}
            price = float(quote["price"])

        # ── 参数校验 ──
        if order_type not in ("buy", "sell"):
            return {"success": False, "error": f"无效的委托类型: {order_type}"}
        if quantity <= 0:
            return {"success": False, "error": "数量必须大于0"}
        if order_type == "buy" and quantity % 100 != 0:
            return {"success": False, "error": "买入数量必须是100的整数倍"}

        # ── 查询账户 ──
        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
        if not account:
            return {"success": False, "error": "账户不存在"}

        # ── 卖出时检查持仓 ──
        if order_type == "sell":
            position = db.query(SimPosition).filter(
                and_(
                    SimPosition.account_id == account_id,
                    SimPosition.stock_code == stock_code,
                )
            ).first()
            if not position:
                return {"success": False, "error": f"未持有 {stock_code}"}
            if quantity > (position.available_quantity or 0):
                return {
                    "success": False,
                    "error": f"可卖数量不足，可卖 {position.available_quantity}，请求卖出 {quantity}",
                }
            if not stock_name:
                stock_name = position.stock_name or stock_code

        # ── 买入时检查资金 ──
        if order_type == "buy":
            trade_amount = price * quantity
            commission, _, transfer_fee = TradeEngine.calculate_commission(trade_amount, "buy")
            total_cost = trade_amount + commission + transfer_fee
            if total_cost > (account.current_capital or 0):
                return {
                    "success": False,
                    "error": f"资金不足，需要 {total_cost:.2f}，可用 {account.current_capital:.2f}",
                }

        # ── 创建委托单记录（状态直接为 filled，作为成交快照）──
        now = datetime.now()
        order = SimOrder(
            account_id=account_id,
            stock_code=stock_code,
            stock_name=stock_name,
            order_type=order_type,
            order_quantity=quantity,
            limit_price=None,       # 市价单
            order_price=price,
            status="pending",       # execute_*_order 会改为 filled
            filled_quantity=0,
            filled_price=None,
            filled_amount=0.0,
            commission=0.0,
            expire_date=now.strftime("%Y-%m-%d"),
            expire_time=None,
            position_type=position_type,
            strategy_name=strategy_name,
            strategy_reason=strategy_reason,
            order_source=order_source,
        )
        db.add(order)
        db.flush()  # 获取 order.id，但不 commit

        # ── 执行成交（不commit，由调用方控制）──
        if order_type == "buy":
            result = OrderService.execute_buy_order(db, order, price, from_market_order=True)
        else:
            result = OrderService.execute_sell_order(db, order, price, from_market_order=True)

        if not result.get("success"):
            if auto_commit:
                db.rollback()
            return result

        # ── 提交事务 ──
        if auto_commit:
            db.commit()
            cache_delete(f"sim_account:{account_id}", namespace="sim")
            logger.info(
                f"市价单成交: id={order.id}, {order_type} {stock_code} "
                f"{quantity}股@{price}"
            )

        result["order_id"] = order.id
        result["order_type"] = order_type
        result["price"] = price
        result["quantity"] = quantity
        return result

    # ═══════════════════════════════════════════════════════
    # 撤销委托单
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def cancel_order(db: Session, order_id: int) -> Dict[str, Any]:
        """撤销委托单

        仅允许撤销状态为 pending 或 partial 的委托单。
        释放冻结的资金或持仓。
        """
        order = db.query(SimOrder).filter(SimOrder.id == order_id).first()
        if not order:
            return {"success": False, "error": "委托单不存在"}

        if order.status not in ("pending", "partial"):
            return {
                "success": False,
                "error": f"委托单状态为 {order.status}，无法撤销",
            }

        account = db.query(SimAccount).filter(SimAccount.id == order.account_id).first()
        if not account:
            return {"success": False, "error": "账户不存在"}

        remaining_qty = order.order_quantity - order.filled_quantity

        if order.order_type == "buy":
            # 释放冻结资金（按订单金额释放，不再用 min 截断）
            # 旧的 min(frozen_amount, current_frozen) 在多订单并发场景下会导致部分订单取消时
            # 冻结资金释放不足（min 会优先满足先取消的订单），最终 current_capital 数据被污染
            frozen_amount = OrderService._calc_buy_frozen_amount(order.order_price, remaining_qty)
            release = frozen_amount
            if (account.frozen_capital or 0) + 0.01 < release:
                # 数据不一致告警（不阻断释放，按订单金额释放避免数据进一步错乱）
                logger.warning(
                    f"取消订单 {order_id}: 账户冻结资金 {account.frozen_capital:.2f} < 应释放 {release:.2f}，"
                    f"可能存在历史数据不一致，按订单金额释放"
                )
            account.frozen_capital = (account.frozen_capital or 0) - release
            account.current_capital = (account.current_capital or 0) + release

        elif order.order_type == "sell":
            # 释放冻结持仓
            position = db.query(SimPosition).filter(
                and_(
                    SimPosition.account_id == order.account_id,
                    SimPosition.stock_code == order.stock_code,
                )
            ).first()

            if position:
                position.available_quantity = (position.available_quantity or 0) + remaining_qty
        order.status = "cancelled"

        # 刷新账户总资产
        OrderService._refresh_account_assets(db, account)

        db.commit()

        logger.info(f"委托单撤销: id={order_id}, 剩余数量={remaining_qty}")

        return {
            "success": True,
            "order_id": order_id,
            "status": "cancelled",
            "released_quantity": remaining_qty,
        }

    # ═══════════════════════════════════════════════════════
    # 委托改价（P2-8）
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def reprice_order(db: Session, order_id: int, new_price: float) -> Dict[str, Any]:
        """轻量改价：仅更新委托价格，不释放/重新冻结资金

        适用场景：限价单偏离市价 0.5-3% 长期不成交时，调用此方法微调价格。
        资金/持仓仍按原价冻结，改价后撮合时按新价成交，差额在成交时结算。

        约束：
        - 仅 pending/partial 状态可改价
        - 新价偏离原价不得超过 ±10%（防误操作）
        - 新价必须 > 0

        Args:
            new_price: 新委托价格
        """
        if new_price <= 0:
            return {"success": False, "error": "新价格必须大于0"}

        order = db.query(SimOrder).filter(SimOrder.id == order_id).first()
        if not order:
            return {"success": False, "error": "委托单不存在"}

        if order.status not in ("pending", "partial"):
            return {
                "success": False,
                "error": f"委托单状态为 {order.status}，无法改价",
            }

        old_price = order.order_price or 0
        if old_price <= 0:
            return {"success": False, "error": "原委托价无效"}

        # 偏离校验：新价不得偏离原价 ±10%
        deviation = abs(new_price - old_price) / old_price
        if deviation > 0.10:
            return {
                "success": False,
                "error": f"新价 {new_price:.2f} 偏离原价 {old_price:.2f} 超过 10%（{deviation*100:.1f}%），请撤单重挂",
            }

        # 买卖双方冻结资金调整：
        # - buy：原冻结 = old_price × remaining_qty × (1+费率)
        #        新冻结 = new_price × remaining_qty × (1+费率)
        #        差额 = 新 - 旧，正值需补冻结（从 current_capital 扣），负值释放冻结
        # - sell：改价不影响持仓冻结（数量不变），无需调整
        remaining_qty = order.order_quantity - (order.filled_quantity or 0)

        if order.order_type == "buy" and remaining_qty > 0:
            account = db.query(SimAccount).filter(SimAccount.id == order.account_id).first()
            if not account:
                return {"success": False, "error": "账户不存在"}

            old_frozen = OrderService._calc_buy_frozen_amount(old_price, remaining_qty)
            new_frozen = OrderService._calc_buy_frozen_amount(new_price, remaining_qty)
            delta = new_frozen - old_frozen

            if delta > 0:
                # 需补冻结：检查可用资金是否足够
                if (account.current_capital or 0) < delta:
                    return {
                        "success": False,
                        "error": f"可用资金不足，改价需补冻结 {delta:.2f} 元，当前可用 {account.current_capital:.2f}",
                    }
                account.current_capital = (account.current_capital or 0) - delta
                account.frozen_capital = (account.frozen_capital or 0) + delta
            elif delta < 0:
                # 释放冻结
                account.frozen_capital = max(0, (account.frozen_capital or 0) + delta)
                account.current_capital = (account.current_capital or 0) + abs(delta)

        # 更新委托价
        order.order_price = new_price
        # 刷新账户总资产（current_capital 变化后）
        if order.order_type == "buy":
            account = db.query(SimAccount).filter(SimAccount.id == order.account_id).first()
            if account:
                OrderService._refresh_account_assets(db, account)

        db.commit()

        logger.info(
            f"委托改价: id={order_id}, {old_price:.2f} → {new_price:.2f} "
            f"(偏离 {deviation*100:.2f}%, 剩余数量 {remaining_qty})"
        )

        return {
            "success": True,
            "order_id": order_id,
            "old_price": old_price,
            "new_price": new_price,
            "deviation_pct": round(deviation * 100, 2),
            "remaining_quantity": remaining_qty,
        }

    # ═══════════════════════════════════════════════════════
    # 过期委托单处理
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def expire_orders(db: Session, account_id: int) -> Dict[str, Any]:
        """处理过期委托单

        检查所有 pending/partial 委托单的过期日期，
        若已过期则标记为 expired 并释放冻结资源。
        """
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M:%S")

        pending_orders = db.query(SimOrder).filter(
            and_(
                SimOrder.account_id == account_id,
                SimOrder.status.in_(["pending", "partial"]),
                SimOrder.expire_date.isnot(None),
            )
        ).all()

        expired_count = 0
        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()

        for order in pending_orders:
            # 判断是否过期
            is_expired = False

            if order.expire_date < today:
                # 已过日期
                is_expired = True
            elif order.expire_date == today and order.expire_time:
                # 当天，检查时间
                expire_time = order.expire_time or "15:00:00"
                if current_time >= expire_time:
                    is_expired = True

            if is_expired:
                remaining_qty = order.order_quantity - order.filled_quantity

                if order.order_type == "buy" and account:
                    # 释放冻结资金（按订单金额释放，与 cancel_order 一致）
                    frozen_amount = OrderService._calc_buy_frozen_amount(order.order_price, remaining_qty)
                    release = frozen_amount
                    if (account.frozen_capital or 0) + 0.01 < release:
                        logger.warning(
                            f"过期订单 {order.id}: 账户冻结资金 {account.frozen_capital:.2f} < 应释放 {release:.2f}，"
                            f"可能存在历史数据不一致，按订单金额释放"
                        )
                    account.frozen_capital = (account.frozen_capital or 0) - release
                    account.current_capital = (account.current_capital or 0) + release

                elif order.order_type == "sell":
                    # 释放冻结持仓
                    position = db.query(SimPosition).filter(
                        and_(
                            SimPosition.account_id == account_id,
                            SimPosition.stock_code == order.stock_code,
                        )
                    ).first()
                    if position:
                        position.available_quantity = (position.available_quantity or 0) + remaining_qty

                order.status = "expired"
                expired_count += 1

        if expired_count > 0 and account:
            OrderService._refresh_account_assets(db, account)
            db.commit()
            cache_delete(f"sim_account:{account_id}", namespace="sim")
            logger.info(f"过期处理完成: 账户 {account_id} 共 {expired_count} 笔委托单过期")

        return {
            "success": True,
            "expired_count": expired_count,
        }

    @staticmethod
    def cleanup_today_orders(db: Session, account_id: int, today: str) -> Dict[str, int]:
        """收盘后清理当日 filled/expired 委托单

        - 删除已成交（filled）的当日委托：成交信息已写入 SimTrade，无需在委托管理保留
        - 删除已过期（expired）的委托：expire_date <= today，覆盖跨日遗留（如周五过期周一才清理）
        - 保留 cancelled（用户操作历史）和 pending/partial（理论上不会，但保险起见）
        """
        deleted_filled = db.query(SimOrder).filter(
            and_(
                SimOrder.account_id == account_id,
                SimOrder.status == "filled",
                SimOrder.created_at >= f"{today} 00:00:00",
            )
        ).delete(synchronize_session=False)

        deleted_expired = db.query(SimOrder).filter(
            and_(
                SimOrder.account_id == account_id,
                SimOrder.status == "expired",
                SimOrder.expire_date <= today,
            )
        ).delete(synchronize_session=False)

        db.commit()
        return {"filled": deleted_filled, "expired": deleted_expired}

    @staticmethod
    def cleanup_old_cancelled(db: Session, account_id: int, days: int = 30) -> int:
        """清理 N 天前的 cancelled 委托（保留最近用户操作历史）"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        deleted = db.query(SimOrder).filter(
            and_(
                SimOrder.account_id == account_id,
                SimOrder.status == "cancelled",
                SimOrder.created_at < f"{cutoff} 00:00:00",
            )
        ).delete(synchronize_session=False)
        db.commit()
        return deleted

    # ═══════════════════════════════════════════════════════
    # 查询委托单
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def get_orders(
        db: Session,
        account_id: int,
        status: Optional[str] = None,
        order_type: Optional[str] = None,
        stock_code: Optional[str] = None,
        order_source: Optional[str] = None,
        limit: int = 50,
        today_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """查询委托单列表"""
        query = db.query(SimOrder).filter(SimOrder.account_id == account_id)

        if status:
            query = query.filter(SimOrder.status == status)
        if order_type:
            query = query.filter(SimOrder.order_type == order_type)
        if stock_code:
            query = query.filter(SimOrder.stock_code == stock_code)
        if order_source:
            query = query.filter(SimOrder.order_source == order_source)
        if today_only:
            today = datetime.now().strftime("%Y-%m-%d")
            query = query.filter(SimOrder.created_at >= f"{today} 00:00:00")

        orders = query.order_by(SimOrder.created_at.desc()).limit(limit).all()

        # 批量取实时行情，补全 current_price
        codes = list({o.stock_code for o in orders})
        price_map: dict = {}
        if codes:
            try:
                from app.services.trade_engine import TradeEngine
                price_map = TradeEngine.fetch_realtime_quotes(codes) or {}
            except Exception:
                price_map = {}

        return [
            {
                "order_id": o.id,
                "stock_code": o.stock_code,
                "stock_name": o.stock_name,
                "order_type": o.order_type,
                "order_price": o.order_price,
                "order_quantity": o.order_quantity,
                "order_amount": o.order_price * o.order_quantity,
                "order_status": o.status,
                "filled_quantity": o.filled_quantity,
                "filled_price": o.filled_price,
                "filled_amount": o.filled_amount,
                "commission": o.commission,
                "expire_date": o.expire_date,
                "expire_time": o.expire_time,
                "strategy_name": o.strategy_name,
                "strategy_reason": o.strategy_reason,
                "order_source": getattr(o, 'order_source', None) or "manual",
                "current_price": price_map.get(o.stock_code),
                "create_time": o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else None,
            }
            for o in orders
        ]

    @staticmethod
    def get_order_detail(db: Session, order_id: int) -> Optional[Dict[str, Any]]:
        """获取委托单详情"""
        order = db.query(SimOrder).filter(SimOrder.id == order_id).first()
        if not order:
            return None

        return {
            "id": order.id,
            "account_id": order.account_id,
            "stock_code": order.stock_code,
            "stock_name": order.stock_name,
            "order_type": order.order_type,
            "order_price": order.order_price,
            "order_quantity": order.order_quantity,
            "order_amount": order.order_price * order.order_quantity,
            "status": order.status,
            "filled_quantity": order.filled_quantity,
            "filled_price": order.filled_price,
            "filled_amount": order.filled_amount,
            "commission": order.commission,
            "limit_price": order.limit_price,
            "expire_date": order.expire_date,
            "expire_time": order.expire_time,
            "strategy_name": order.strategy_name,
            "strategy_reason": order.strategy_reason,
            "order_source": getattr(order, 'order_source', None) or "manual",
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        }

    # ═══════════════════════════════════════════════════════
    # 内部工具方法
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _calc_expire(now: datetime, expire_type: str) -> tuple:
        """根据过期类型计算过期日期和时间

        Args:
            now: 当前时间
            expire_type: "day" (当日有效) | "gtc" (撤销前有效) | "3day" (3日有效)

        Returns:
            (expire_date, expire_time)
        """
        if expire_type == "day":
            return now.strftime("%Y-%m-%d"), "15:00:00"
        elif expire_type == "3day":
            expire_dt = now + timedelta(days=3)
            return expire_dt.strftime("%Y-%m-%d"), "15:00:00"
        elif expire_type == "gtc":
            # 撤销前有效：不设过期日期
            return None, None
        else:
            # 默认当日有效
            return now.strftime("%Y-%m-%d"), "15:00:00"

    @staticmethod
    def _get_realtime_quotes(stock_codes: List[str]) -> Dict[str, Any]:
        """获取实时行情，优先从缓存读取

        Args:
            stock_codes: 股票代码列表

        Returns:
            {stock_code: quote_dict}
        """
        if not stock_codes:
            return {}

        # 先从缓存中查找
        quotes = {}
        uncached_codes = []

        for code in stock_codes:
            cached = cache_get(f"quote:{code}", namespace="sim")
            if cached:
                quotes[code] = cached
            else:
                uncached_codes.append(code)

        # 批量获取未缓存的行情
        if uncached_codes:
            try:
                fresh_quotes = TencentSource.get_quotes(uncached_codes)
                for code, quote in fresh_quotes.items():
                    quotes[code] = quote
                    # 缓存行情数据（5秒过期，盘中频繁更新）
                    cache_set(f"quote:{code}", quote, ttl=5, namespace="sim")
            except Exception as e:
                logger.warning(f"获取实时行情失败: {e}")

        return quotes

    @staticmethod
    def _refresh_account_assets(db: Session, account: SimAccount) -> None:
        """刷新账户总资产（使用统一计算函数）"""
        from app.services.trade_engine import TradeEngine
        account.total_assets = TradeEngine.calculate_total_assets(db, account=account)

    @staticmethod
    def _update_strategy_stats(
        db: Session, account_id: int, strategy_name: str,
        profit: float, profit_ratio: float,
    ) -> None:
        """更新策略统计（按 strategy_name 维度聚合）

        在每次卖出成交后调用，累计交易次数、胜率、盈亏等。
        """
        from app.models.sim_trading import SimStrategyStats
        if not strategy_name:
            return

        stats = db.query(SimStrategyStats).filter(
            and_(
                SimStrategyStats.account_id == account_id,
                SimStrategyStats.strategy_name == strategy_name,
            )
        ).first()

        if not stats:
            stats = SimStrategyStats(
                account_id=account_id,
                strategy_name=strategy_name,
            )
            db.add(stats)

        stats.total_trades = (stats.total_trades or 0) + 1
        if profit > 0:
            stats.win_trades = (stats.win_trades or 0) + 1
        else:
            stats.loss_trades = (stats.loss_trades or 0) + 1
        stats.win_rate = round(
            stats.win_trades / stats.total_trades * 100, 2
        ) if stats.total_trades > 0 else 0

        # 平均盈亏比例
        if profit > 0:
            stats.avg_win_ratio = round(
                ((stats.avg_win_ratio or 0) * (stats.win_trades - 1) + profit_ratio) / stats.win_trades, 4
            ) if stats.win_trades > 0 else round(profit_ratio, 4)
        else:
            stats.avg_loss_ratio = round(
                ((stats.avg_loss_ratio or 0) * (stats.loss_trades - 1) + profit_ratio) / stats.loss_trades, 4
            ) if stats.loss_trades > 0 else round(profit_ratio, 4)

        # 盈亏比 = 平均盈利 / |平均亏损|
        if (stats.avg_loss_ratio or 0) != 0:
            stats.profit_loss_ratio = round(
                abs((stats.avg_win_ratio or 0) / stats.avg_loss_ratio), 4
            )

        stats.avg_profit_ratio = round(
            ((stats.avg_profit_ratio or 0) * (stats.total_trades - 1) + profit_ratio) / stats.total_trades, 4
        ) if stats.total_trades > 0 else round(profit_ratio, 4)

        # 最大单笔盈亏
        if profit_ratio > (stats.max_profit_ratio or 0):
            stats.max_profit_ratio = round(profit_ratio, 4)
        if profit_ratio < (stats.max_loss_ratio or 0):
            stats.max_loss_ratio = round(profit_ratio, 4)

        stats.total_profit = round((stats.total_profit or 0) + profit, 2)
