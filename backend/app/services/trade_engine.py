"""模拟交易引擎 - 执行买卖、管理持仓、计算盈亏"""
import json
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)
from typing import Optional, Dict, List, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.sim_trading import (
    SimAccount, SimPosition, SimTrade, SimDailyPnl,
    AIStrategyDecision, SimStrategyStats
)
from app.core.cache import cache_delete


class TradeEngine:
    """模拟交易引擎"""
    
    # 交易费用（模拟）
    COMMISSION_RATE = 0.0003  # 佣金费率 0.03%（双向）
    STAMP_TAX_RATE = 0.001  # 印花税 0.1%（仅卖出）
    TRANSFER_FEE_RATE = 0.00002  # 过户费 0.002%（双向）
    MIN_COMMISSION = 5.0  # 最低佣金 5元

    @staticmethod
    def calculate_total_assets(
        db: Session,
        account: SimAccount = None,
        account_id: int = None,
    ) -> float:
        """统一计算账户总资产 = 可用资金 + 冻结资金 + 持仓市值

        所有需要计算总资产的地方都应调用此函数，避免重复实现导致不一致。

        Args:
            db: 数据库会话
            account: 账户对象（已查询时直接传入，避免重复查询）
            account_id: 账户ID（未传account时使用）

        Returns:
            总资产金额
        """
        if account is None:
            if account_id is None:
                raise ValueError("必须传入 account 或 account_id")
            account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
            if not account:
                return 0.0

        # 查询所有持仓市值
        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account.id
        ).all()
        total_market_value = sum(p.market_value or 0 for p in positions)

        # 冻结资金取绝对值，防止负值脏数据影响计算
        safe_frozen = max(0, account.frozen_capital or 0.0)

        return (account.current_capital or 0) + safe_frozen + total_market_value

    @staticmethod
    def fetch_realtime_quotes(codes: list) -> dict:
        """批量获取股票实时行情，code -> current_price。
        优先 pytdx（行情中心直连），失败则用腾讯财经兜底。
        """
        if not codes:
            return {}
        result: dict = {}

        # 1) pytdx
        try:
            from app.core.pytdx_source import pytdx_data
            quotes = pytdx_data.get_security_quotes(codes)
            for q in quotes or []:
                code = q.get("code")
                price = q.get("price") or q.get("now")
                if code and price and float(price) > 0:
                    result[code] = float(price)
        except Exception as e:
            logger.debug(f"pytdx 实时行情获取失败: {e}")

        # 2) 腾讯财经兜底
        missing = [c for c in codes if c not in result]
        if missing:
            try:
                from app.core.data_sources import TencentSource
                tq = TencentSource.get_quotes(missing) or {}
                for code, data in tq.items():
                    price = data.get("price")
                    if price and float(price) > 0:
                        result[code] = float(price)
            except Exception as e:
                logger.debug(f"tencent 实时行情兜底失败: {e}")

        return result
    
    @staticmethod
    def get_or_create_account(db: Session, account_name: str = "AI智能策略账户") -> SimAccount:
        """获取或创建模拟账户

        优先按 ID 升序取最早创建的账户（同一份业务只对应一个账户）。
        多个同名账户时取最早创建的一个；不存在则创建。
        """
        account = (
            db.query(SimAccount)
            .filter(SimAccount.account_name == account_name)
            .order_by(SimAccount.id.asc())
            .first()
        )
        if not account:
            account = SimAccount(
                account_name=account_name,
                initial_capital=100000.0,
                current_capital=100000.0,
                total_assets=100000.0
            )
            db.add(account)
            db.commit()
            db.refresh(account)
        return account
    
    @staticmethod
    def calculate_commission(amount: float, trade_type: str) -> Tuple[float, float, float]:
        """计算交易费用
        返回: (佣金, 印花税, 过户费)
        """
        # 佣金（双向）
        commission = max(amount * TradeEngine.COMMISSION_RATE, TradeEngine.MIN_COMMISSION)
        
        # 印花税（仅卖出）
        stamp_tax = amount * TradeEngine.STAMP_TAX_RATE if trade_type == "sell" else 0.0
        
        # 过户费（双向）
        transfer_fee = amount * TradeEngine.TRANSFER_FEE_RATE
        
        return round(commission, 2), round(stamp_tax, 2), round(transfer_fee, 2)
    
    @staticmethod
    def buy(
        db: Session,
        account_id: int,
        stock_code: str,
        stock_name: str,
        price: float,
        quantity: int,
        strategy_name: str = "",
        strategy_reason: str = "",
        position_type: str = "short"
    ) -> Dict[str, Any]:
        """买入股票（直接成交）

        .. deprecated::
            使用 OrderService.execute_market_order 代替。本方法保留向后兼容，
            内部代理到 execute_market_order。
        """
        from app.services.order_service import OrderService
        result = OrderService.execute_market_order(
            db=db,
            account_id=account_id,
            stock_code=stock_code,
            stock_name=stock_name,
            order_type="buy",
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
            strategy_reason=strategy_reason,
            position_type=position_type,
            auto_commit=True,
        )
        # 字段兼容：actual_total_cost -> total_cost
        if result.get("success") and "actual_total_cost" in result:
            result["total_cost"] = result.pop("actual_total_cost")
        return result
    
    @staticmethod
    def sell(
        db: Session,
        account_id: int,
        stock_code: str,
        price: float,
        quantity: int,
        strategy_name: str = "",
        strategy_reason: str = ""
    ) -> Dict[str, Any]:
        """卖出股票（直接成交）

        .. deprecated::
            使用 OrderService.execute_market_order 代替。本方法保留向后兼容，
            内部代理到 execute_market_order。
        """
        from app.services.order_service import OrderService
        return OrderService.execute_market_order(
            db=db,
            account_id=account_id,
            stock_code=stock_code,
            stock_name="",  # execute_market_order 会从持仓补全
            order_type="sell",
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
            strategy_reason=strategy_reason,
            auto_commit=True,
        )
    
    @staticmethod
    def update_t_plus_1(db: Session, account_id: int) -> Dict[str, Any]:
        """T+1更新：将上一交易日买入的股票标记为可卖

        使用交易日历（而非日历日）解决跨周末/节假日误判：
        周五买入 → 下周一调用时 yesterday=周五，正确解锁。
        """
        from app.core.trading_calendar import get_last_trade_date

        last_trade_yyyymmdd = get_last_trade_date()
        last_trade_date = f"{last_trade_yyyymmdd[:4]}-{last_trade_yyyymmdd[4:6]}-{last_trade_yyyymmdd[6:8]}"

        result = db.query(SimPosition).filter(
            and_(
                SimPosition.account_id == account_id,
                SimPosition.buy_date == last_trade_date,
                SimPosition.available_quantity == 0
            )
        ).update(
            {SimPosition.available_quantity: SimPosition.total_quantity},
            synchronize_session=False
        )

        db.commit()
        return {"unlocked": result or 0, "last_trade_date": last_trade_date}
    
    @staticmethod
    def update_position_prices(db: Session, account_id: int, price_dict: Dict[str, float]) -> None:
        """更新持仓价格
        price_dict: {stock_code: current_price}
        """
        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()
        
        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
        
        for pos in positions:
            if pos.stock_code in price_dict:
                pos.current_price = price_dict[pos.stock_code]
                pos.market_value = pos.total_quantity * pos.current_price
                pos.profit = (pos.current_price - pos.cost_price) * pos.total_quantity
                pos.profit_ratio = (pos.current_price / pos.cost_price - 1) * 100 if pos.cost_price > 0 else 0
                # 同步更新 max_profit_ratio（跟踪止损基准），避免漏掉日内新高
                if pos.profit_ratio > pos.max_profit_ratio:
                    pos.max_profit_ratio = pos.profit_ratio
        
        # 更新账户总资产（使用统一计算函数）
        if account:
            account.total_assets = TradeEngine.calculate_total_assets(db, account=account)
        
        db.commit()
    
    @staticmethod
    def record_daily_pnl(db: Session, account_id: int, trade_date: str = None) -> Dict[str, Any]:
        """记录每日盈亏

        算法：当日盈亏 = 今日总资产 - 上一交易日总资产（环比法）
        - 包含已实现 + 未实现盈亏，最贴近"今天赚/亏了多少钱"
        - 买入手续费通过 capital 减少间接反映在 total_assets 上
        - 第一天（无昨日记录）当日盈亏 = 总资产 - 初始资金
        """
        if not trade_date:
            trade_date = date.today().strftime("%Y-%m-%d")

        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
        if not account:
            return {"success": False, "error": "账户不存在"}

        # ── 查上一交易日总资产（环比基准）──
        prev_pnl = (
            db.query(SimDailyPnl)
            .filter(SimDailyPnl.account_id == account_id)
            .filter(SimDailyPnl.trade_date < trade_date)
            .order_by(SimDailyPnl.trade_date.desc())
            .first()
        )
        prev_total_assets = prev_pnl.total_assets if prev_pnl else account.initial_capital

        # ── 当日总资产 = current_capital + frozen_capital + 持仓市值 ──
        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()
        total_market_value = sum(p.market_value for p in positions)
        total_assets = TradeEngine.calculate_total_assets(db, account=account)

        # ── 当日盈亏（环比法） ──
        daily_profit = total_assets - prev_total_assets
        initial_capital = account.initial_capital
        # 累计盈亏用"已实现+未实现"算法，不依赖 current_capital 数据正确性
        realized_profit = (
            db.query(sql_func.sum(SimTrade.profit))
            .filter(SimTrade.account_id == account_id, SimTrade.trade_type == "sell")
            .scalar() or 0
        )
        unrealized_profit = sum(p.profit or 0 for p in positions)
        total_profit = realized_profit + unrealized_profit
        daily_profit_ratio = (daily_profit / prev_total_assets * 100) if prev_total_assets > 0 else 0
        total_profit_ratio = (total_profit / initial_capital * 100) if initial_capital > 0 else 0

        # ── 当日交易统计 ──
        today_trades = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_date == trade_date
            )
        ).all()
        buy_count = sum(1 for t in today_trades if t.trade_type == "buy")
        sell_count = sum(1 for t in today_trades if t.trade_type == "sell")

        # ── 累计胜率 ──
        all_sell_trades = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_type == "sell"
            )
        ).all()
        win_count = sum(1 for t in all_sell_trades if t.profit and t.profit > 0)
        loss_count = sum(1 for t in all_sell_trades if t.profit and t.profit <= 0)
        total_sell_count = win_count + loss_count
        win_rate = (win_count / total_sell_count * 100) if total_sell_count > 0 else 0

        # ── 最大回撤（基于历史每日 total_assets） ──
        daily_pnls = (
            db.query(SimDailyPnl)
            .filter(SimDailyPnl.account_id == account_id)
            .order_by(SimDailyPnl.trade_date.asc())
            .all()
        )
        max_assets = prev_total_assets
        max_drawdown = 0
        for pnl in daily_pnls:
            if pnl.total_assets > max_assets:
                max_assets = pnl.total_assets
            if max_assets > 0:
                drawdown = (max_assets - pnl.total_assets) / max_assets * 100
                max_drawdown = max(max_drawdown, drawdown)
        if max_assets > 0:
            drawdown = (max_assets - total_assets) / max_assets * 100
            max_drawdown = max(max_drawdown, drawdown)

        # ── upsert 当日记录 ──
        daily_pnl = db.query(SimDailyPnl).filter(
            and_(
                SimDailyPnl.account_id == account_id,
                SimDailyPnl.trade_date == trade_date
            )
        ).first()

        pnl_data = {
            "initial_capital": initial_capital,
            "available_capital": account.current_capital,
            "market_value": total_market_value,
            "total_assets": total_assets,
            "daily_profit": round(daily_profit, 2),
            "daily_profit_ratio": round(daily_profit_ratio, 4),
            "total_profit": round(total_profit, 2),
            "total_profit_ratio": round(total_profit_ratio, 4),
            "position_count": len(positions),
            "total_trades": buy_count + sell_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round(win_rate, 2),
            "max_drawdown": round(max_drawdown, 2),
        }

        if daily_pnl:
            for k, v in pnl_data.items():
                setattr(daily_pnl, k, v)
        else:
            daily_pnl = SimDailyPnl(trade_date=trade_date, account_id=account_id, **pnl_data)
            db.add(daily_pnl)

        db.commit()

        return {
            "success": True,
            "trade_date": trade_date,
            "daily_profit": round(daily_profit, 2),
            "daily_profit_ratio": round(daily_profit_ratio, 4),
            "total_profit": round(total_profit, 2),
            "total_profit_ratio": round(total_profit_ratio, 4),
            "win_rate": round(win_rate, 2),
            "position_count": len(positions),
        }

    @staticmethod
    def backfill_daily_pnl(db: Session, account_id: int, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
        """补录历史每日盈亏记录

        当 sim_daily_pnls 表为空（如定时任务未触发）时，根据交易记录
        自动从首笔交易日期开始逐日补录。

        算法：
        - 历史日期（非今日）: total_assets = 上日 total_assets - 买入金额 + 卖出金额 + 卖出盈亏
        - 今日: 使用实时 total_assets（current_capital + 持仓市值），最准确
        """
        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
        if not account:
            return {"success": False, "error": "账户不存在"}

        from datetime import timedelta

        # 确定起止日期
        first_trade = db.query(SimTrade).filter(
            SimTrade.account_id == account_id
        ).order_by(SimTrade.trade_date.asc()).first()
        if not first_trade:
            return {"success": False, "error": "无交易记录，无法补录"}

        if not start_date:
            start_date = first_trade.trade_date
        if not end_date:
            end_date = date.today().strftime("%Y-%m-%d")

        # 已有记录的日期集合
        existing_dates = set()
        existing_pnls = db.query(SimDailyPnl).filter(
            SimDailyPnl.account_id == account_id
        ).all()
        for p in existing_pnls:
            existing_dates.add(p.trade_date)

        # 按日期查询所有交易
        all_trades = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_date >= start_date,
                SimTrade.trade_date <= end_date
            )
        ).order_by(SimTrade.trade_date.asc()).all()

        # 按日期分组
        trades_by_date = {}
        for t in all_trades:
            if t.trade_date not in trades_by_date:
                trades_by_date[t.trade_date] = []
            trades_by_date[t.trade_date].append(t)

        today_str = date.today().strftime("%Y-%m-%d")

        # 逐日遍历
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        prev_assets = account.initial_capital
        records_created = 0

        current_dt = start_dt
        while current_dt <= end_dt:
            d = current_dt.strftime("%Y-%m-%d")

            if d in existing_dates:
                pnl = db.query(SimDailyPnl).filter(
                    and_(SimDailyPnl.account_id == account_id, SimDailyPnl.trade_date == d)
                ).first()
                if pnl:
                    prev_assets = pnl.total_assets
                current_dt += timedelta(days=1)
                continue

            day_trades = trades_by_date.get(d, [])

            if d == today_str:
                # 今日：用实时总资产（最准确）
                positions = db.query(SimPosition).filter(
                    SimPosition.account_id == account_id
                ).all()
                total_market_value = sum(p.market_value or 0 for p in positions)
                total_assets = TradeEngine.calculate_total_assets(db, account=account)
            else:
                # 历史日：现金流估算
                # total_cost 已包含 trade_amount + 手续费
                # 买入: 现金减少 total_cost; 卖出: 现金增加 trade_amount - total_cost
                day_buy_total = sum(t.total_cost for t in day_trades if t.trade_type == "buy")
                day_sell_net = sum((t.trade_amount - t.total_cost) for t in day_trades if t.trade_type == "sell")
                total_assets = prev_assets - day_buy_total + day_sell_net

            daily_profit = total_assets - prev_assets
            daily_profit_ratio = (daily_profit / prev_assets * 100) if prev_assets > 0 else 0

            # 累计盈亏
            realized = sum(
                t.profit or 0 for t in db.query(SimTrade).filter(
                    and_(SimTrade.account_id == account_id, SimTrade.trade_type == "sell",
                         SimTrade.trade_date <= d)
                ).all()
            )
            # 未实现盈亏（仅今日能准确计算）
            if d == today_str:
                positions = db.query(SimPosition).filter(
                    SimPosition.account_id == account_id
                ).all()
                unrealized = sum(p.profit or 0 for p in positions)
            else:
                unrealized = 0
            total_profit = realized + unrealized
            total_profit_ratio = (total_profit / account.initial_capital * 100) if account.initial_capital > 0 else 0

            buy_count = sum(1 for t in day_trades if t.trade_type == "buy")
            sell_count = sum(1 for t in day_trades if t.trade_type == "sell")

            # 累计胜率
            all_sells = db.query(SimTrade).filter(
                and_(SimTrade.account_id == account_id, SimTrade.trade_type == "sell",
                     SimTrade.trade_date <= d)
            ).all()
            win_count = sum(1 for t in all_sells if t.profit and t.profit > 0)
            loss_count = sum(1 for t in all_sells if t.profit and t.profit <= 0)
            total_sell_count = win_count + loss_count
            win_rate = (win_count / total_sell_count * 100) if total_sell_count > 0 else 0

            pnl_record = SimDailyPnl(
                trade_date=d,
                account_id=account_id,
                initial_capital=account.initial_capital,
                available_capital=account.current_capital if d == today_str else 0,
                market_value=total_market_value if d == today_str else 0,
                total_assets=round(total_assets, 2),
                daily_profit=round(daily_profit, 2),
                daily_profit_ratio=round(daily_profit_ratio, 4),
                total_profit=round(total_profit, 2),
                total_profit_ratio=round(total_profit_ratio, 4),
                position_count=len(positions) if d == today_str else 0,
                total_trades=buy_count + sell_count,
                win_count=win_count,
                loss_count=loss_count,
                win_rate=round(win_rate, 2),
                max_drawdown=0,
            )
            db.add(pnl_record)
            records_created += 1

            prev_assets = total_assets
            current_dt += timedelta(days=1)

        db.commit()

        return {
            "success": True,
            "start_date": start_date,
            "end_date": end_date,
            "records_created": records_created,
        }
    
    @staticmethod
    def get_account_summary(db: Session, account_id: int) -> Dict[str, Any]:
        """获取账户摘要"""
        from sqlalchemy import func as sql_func

        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
        if not account:
            return {"success": False, "error": "账户不存在"}

        # 查询持仓
        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()

        # 查询最近交易
        recent_trades = db.query(SimTrade).filter(
            SimTrade.account_id == account_id
        ).order_by(SimTrade.created_at.desc()).limit(10).all()

        # 查询最近盈亏
        recent_pnls = db.query(SimDailyPnl).filter(
            SimDailyPnl.account_id == account_id
        ).order_by(SimDailyPnl.trade_date.desc()).limit(30).all()

        # 统计
        total_market_value = sum(p.market_value or 0 for p in positions)

        # 根据交易记录重新校准 current_capital（防止数据不一致）
        # 资金守恒：current_capital + frozen_capital = initial_capital + total_deposits - buy_total + sell_proceeds
        # 旧的 expected_capital = initial - buy_total + sell_proceeds 漏算了 frozen，导致修正后 current 被错误放大
        buy_total = (
            db.query(sql_func.sum(SimTrade.total_cost))
            .filter(SimTrade.account_id == account_id, SimTrade.trade_type == "buy")
            .scalar() or 0
        )
        sell_proceeds = (
            db.query(sql_func.sum(SimTrade.trade_amount - sql_func.coalesce(SimTrade.commission, 0) - sql_func.coalesce(SimTrade.stamp_tax, 0) - sql_func.coalesce(SimTrade.transfer_fee, 0)))
            .filter(SimTrade.account_id == account_id, SimTrade.trade_type == "sell")
            .scalar() or 0
        )
        expected_total = account.initial_capital + (account.total_deposits or 0) - buy_total + sell_proceeds

        # 如果交易记录为空但有持仓，用持仓成本反推（处理数据不一致）
        if buy_total == 0 and total_market_value > 0:
            position_cost = sum((p.cost_price or 0) * (p.total_quantity or 0) for p in positions)
            expected_total = account.initial_capital + (account.total_deposits or 0) - position_cost
            logger.warning(
                f"无买入记录但存在持仓，按持仓成本反推: initial={account.initial_capital}, cost={position_cost:.2f}"
            )

        # 资金守恒修正：current + frozen 应等于 expected_total
        # 同时处理偏少和偏多的情况（偏多可能是历史bug导致的脏数据）
        safe_frozen_check = max(0, account.frozen_capital or 0.0)
        expected_current = expected_total - safe_frozen_check
        if account.current_capital < expected_current - 1.0:
            logger.warning(
                f"账户资金不足: current={account.current_capital:.2f}, frozen={safe_frozen_check:.2f}, "
                f"current+frozen={account.current_capital + safe_frozen_check:.2f}, "
                f"expected_total={expected_total:.2f}, 修正 current_capital"
            )
            account.current_capital = expected_current
            db.commit()
        elif account.current_capital > expected_current + 1.0:
            logger.warning(
                f"账户资金偏多: current={account.current_capital:.2f}, frozen={safe_frozen_check:.2f}, "
                f"current+frozen={account.current_capital + safe_frozen_check:.2f}, "
                f"expected_total={expected_total:.2f}, 修正 current_capital"
            )
            account.current_capital = expected_current
            db.commit()

        total_profit_unrealized = sum(p.profit or 0 for p in positions)
        # frozen_capital 脏数据修复：历史bug可能导致负值，检测并修正
        raw_frozen = account.frozen_capital or 0.0
        if raw_frozen < -1:
            logger.warning(f"账户{account_id} frozen_capital异常({raw_frozen})，自动修复为0")
            account.frozen_capital = 0.0
            db.commit()

        # current_capital 脏数据修复：无交易记录且 total_deposits=0 时应该等于 initial_capital
        if buy_total == 0 and sell_proceeds == 0 and len(positions) == 0:
            expected_base = account.initial_capital + (account.total_deposits or 0)
            # 只修正明显偏少的情况（可能是历史bug导致），不覆盖合法的重置操作
            if account.current_capital < expected_base - 1.0 and account.current_capital < account.initial_capital:
                logger.warning(
                    f"账户{account_id} current_capital异常({account.current_capital})，"
                    f"无交易记录应等于initial+deposits={expected_base}，自动修复"
                )
                account.current_capital = expected_base
                db.commit()

        # 实时计算 total_assets（使用统一计算函数）
        total_assets = TradeEngine.calculate_total_assets(db, account=account)

        # 计算总体胜率
        all_buy_trades = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_type == "buy"
            )
        ).all()
        all_sell_trades = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_type == "sell"
            )
        ).all()

        win_count = sum(1 for t in all_sell_trades if t.profit and t.profit > 0)
        loss_count = sum(1 for t in all_sell_trades if t.profit and t.profit <= 0)
        total_sell = win_count + loss_count
        win_rate = (win_count / total_sell * 100) if total_sell > 0 else 0

        # 盈亏比 = 平均盈利 / |平均亏损|
        win_total = sum((t.profit or 0) for t in all_sell_trades if t.profit and t.profit > 0)
        loss_total = sum((t.profit or 0) for t in all_sell_trades if t.profit and t.profit < 0)
        avg_win = win_total / win_count if win_count > 0 else 0
        avg_loss = abs(loss_total) / loss_count if loss_count > 0 else 0
        profit_loss_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0

        # 最大回撤（基于历史每日总资产）
        max_drawdown = 0
        if recent_pnls:
            all_pnls_asc = list(reversed(recent_pnls))
            max_assets = all_pnls_asc[0].total_assets if all_pnls_asc else account.initial_capital
            for pnl in all_pnls_asc:
                if pnl.total_assets > max_assets:
                    max_assets = pnl.total_assets
                if max_assets > 0:
                    drawdown = (max_assets - pnl.total_assets) / max_assets * 100
                    max_drawdown = max(max_drawdown, drawdown)
            # 加上今日的潜在回撤
            if max_assets > 0:
                drawdown = (max_assets - total_assets) / max_assets * 100
                max_drawdown = max(max_drawdown, drawdown)

        # 真实总盈亏 = 已实现盈亏（卖出 trade.profit 之和）+ 未实现盈亏（持仓 profit 之和）
        # 旧公式 total_assets - initial_capital 依赖 current_capital 数据正确性，
        # 当 current_capital 被 cancel_order/历史 bug 污染时会算出错误的盈利
        realized_profit = (
            db.query(sql_func.sum(SimTrade.profit))
            .filter(SimTrade.account_id == account_id, SimTrade.trade_type == "sell")
            .scalar() or 0
        )
        unrealized_profit = sum(p.profit or 0 for p in positions)
        actual_profit = realized_profit + unrealized_profit

        return {
            "success": True,
            "account": {
                "id": account.id,
                "name": account.account_name,
                "initial_capital": account.initial_capital,
                "current_capital": account.current_capital,
                "total_assets": total_assets,
                "frozen_capital": account.frozen_capital,
                "total_profit": round(actual_profit, 2),
                "total_profit_ratio": round(actual_profit / account.initial_capital * 100, 4) if account.initial_capital > 0 else 0,
                "max_drawdown": round(max_drawdown, 2)
            },
            "positions": [
                {
                    "stock_code": p.stock_code,
                    "stock_name": p.stock_name,
                    "total_quantity": p.total_quantity,
                    "available_quantity": p.available_quantity,
                    "cost_price": p.cost_price,
                    "current_price": p.current_price,
                    "market_value": p.market_value,
                    "profit": p.profit,
                    "profit_ratio": p.profit_ratio,
                    "position_type": p.position_type,
                    "buy_date": p.buy_date
                } for p in positions
            ],
            "recent_trades": [
                {
                    "id": t.id,
                    "stock_code": t.stock_code,
                    "stock_name": t.stock_name,
                    "trade_type": t.trade_type,
                    "trade_price": t.trade_price,
                    "trade_quantity": t.trade_quantity,
                    "trade_amount": t.trade_amount,
                    "profit": t.profit,
                    "profit_ratio": t.profit_ratio,
                    "trade_date": t.trade_date,
                    "strategy_name": t.strategy_name,
                    "position_type": t.position_type
                } for t in recent_trades
            ],
            "stats": {
                "position_count": len(positions),
                "total_trades": len(all_buy_trades) + len(all_sell_trades),
                "buy_count": len(all_buy_trades),
                "sell_count": total_sell,
                "win_count": win_count,
                "loss_count": loss_count,
                "win_rate": round(win_rate, 2),
                "profit_loss_ratio": profit_loss_ratio,
                "max_drawdown": round(max_drawdown, 2),
                "total_market_value": total_market_value,
                "position_profit": total_profit_unrealized
            }
        }