"""盈亏计算和胜率统计服务"""
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, extract

from app.models.sim_trading import (
    SimAccount, SimPosition, SimTrade, SimDailyPnl,
    AIStrategyDecision, SimStrategyStats
)


class PnLCalculator:
    """盈亏计算和胜率统计"""
    
    @staticmethod
    def calculate_strategy_stats(
        db: Session,
        account_id: int,
        strategy_name: str = None,
        start_date: str = None,
        end_date: str = None
    ) -> Dict[str, Any]:
        """计算策略统计数据"""
        # 查询交易记录
        query = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_type == "sell"
            )
        )
        
        if strategy_name:
            query = query.filter(SimTrade.strategy_name == strategy_name)
        
        if start_date:
            query = query.filter(SimTrade.trade_date >= start_date)
        
        if end_date:
            query = query.filter(SimTrade.trade_date <= end_date)
        
        trades = query.all()
        
        if not trades:
            return {
                "total_trades": 0,
                "win_trades": 0,
                "loss_trades": 0,
                "win_rate": 0,
                "avg_profit_ratio": 0,
                "total_profit": 0,
                "total_profit_ratio": 0,
                "max_profit_ratio": 0,
                "max_loss_ratio": 0,
                "profit_loss_ratio": 0,
                "avg_hold_days": 0
            }
        
        # 计算统计数据
        total_trades = len(trades)
        win_trades = sum(1 for t in trades if t.profit is not None and t.profit > 0)
        loss_trades = sum(1 for t in trades if t.profit is not None and t.profit <= 0)
        
        # 计算盈亏比例
        profit_ratios = [t.profit_ratio for t in trades if t.profit_ratio is not None]
        avg_profit_ratio = sum(profit_ratios) / len(profit_ratios) if profit_ratios else 0
        
        # 计算盈亏金额
        profits = [t.profit for t in trades if t.profit is not None]
        total_profit = sum(profits)

        # 计算总投入成本（对应卖出交易的买入总金额）
        buy_query = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_type == "buy"
            )
        )
        if strategy_name:
            buy_query = buy_query.filter(SimTrade.strategy_name == strategy_name)
        if end_date:
            buy_query = buy_query.filter(SimTrade.trade_date <= end_date)
        elif trades:
            max_date = max(t.trade_date for t in trades)
            buy_query = buy_query.filter(SimTrade.trade_date <= max_date)

        buy_trades = buy_query.all()
        total_cost_basis = sum(
            b.trade_amount for b in buy_trades
        ) if buy_trades else sum(t.trade_amount for t in trades)
        
        # 计算胜率
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
        
        # 计算盈亏比
        win_ratios = [t.profit_ratio for t in trades if t.profit_ratio and t.profit_ratio > 0]
        loss_ratios = [abs(t.profit_ratio) for t in trades if t.profit_ratio and t.profit_ratio < 0]
        
        avg_win_ratio = sum(win_ratios) / len(win_ratios) if win_ratios else 0
        avg_loss_ratio = sum(loss_ratios) / len(loss_ratios) if loss_ratios else 0
        profit_loss_ratio = avg_win_ratio / avg_loss_ratio if avg_loss_ratio > 0 else 0
        
        # 计算最大盈亏
        max_profit_ratio = max(profit_ratios) if profit_ratios else 0
        max_loss_ratio = min(profit_ratios) if profit_ratios else 0
        
        # 计算平均持仓天数
        # 批量查询所有买入记录，按 (stock_code, trade_date) 建立索引
        buy_query = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_type == "buy"
            )
        ).order_by(SimTrade.trade_date.desc()).all()
        
        # 按股票代码分组，每组按日期降序排列
        from collections import defaultdict
        buy_by_code = defaultdict(list)
        for b in buy_query:
            buy_by_code[b.stock_code].append(b)
        
        hold_days_list = []
        for trade in trades:
            if trade.trade_type == "sell":
                buys = buy_by_code.get(trade.stock_code, [])
                # 找到最近的、日期 <= 卖出日期的买入记录
                buy_trade = None
                for b in buys:
                    if b.trade_date <= trade.trade_date:
                        buy_trade = b
                        break
                
                if buy_trade:
                    buy_date = datetime.strptime(buy_trade.trade_date, "%Y-%m-%d").date()
                    sell_date = datetime.strptime(trade.trade_date, "%Y-%m-%d").date()
                    hold_days = (sell_date - buy_date).days
                    hold_days_list.append(hold_days)
        
        avg_hold_days = sum(hold_days_list) / len(hold_days_list) if hold_days_list else 0
        
        return {
            "total_trades": total_trades,
            "win_trades": win_trades,
            "loss_trades": loss_trades,
            "win_rate": round(win_rate, 2),
            "avg_profit_ratio": round(avg_profit_ratio, 2),
            "avg_win_ratio": round(avg_win_ratio, 2),
            "avg_loss_ratio": round(avg_loss_ratio, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "total_profit": round(total_profit, 2),
            "total_profit_ratio": round(total_profit / total_cost_basis * 100, 2) if total_cost_basis > 0 else 0,
            "max_profit_ratio": round(max_profit_ratio, 2),
            "max_loss_ratio": round(max_loss_ratio, 2),
            "avg_hold_days": round(avg_hold_days, 1),
            "max_hold_days": max(hold_days_list) if hold_days_list else 0
        }
    
    @staticmethod
    def calculate_monthly_pnl(db: Session, account_id: int, year: int = None) -> List[Dict]:
        """计算月度盈亏

        基于每日PnL快照数据（sim_daily_pnls），与顶部总盈亏保持一致。
        如果当月无快照记录，则先补录再计算。
        """
        from app.models.sim_trading import SimTrade, SimAccount
        from app.services.trade_engine import TradeEngine

        if not year:
            year = date.today().year
        
        monthly_data = []
        
        for month in range(1, 13):
            start_date = f"{year}-{month:02d}-01"
            if month == 12:
                end_date = f"{year}-12-31"
            else:
                end_date = f"{year}-{month+1:02d}-01"
            
            # 先查询当月快照
            daily_pnls = db.query(SimDailyPnl).filter(
                and_(
                    SimDailyPnl.account_id == account_id,
                    SimDailyPnl.trade_date >= start_date,
                    SimDailyPnl.trade_date < end_date
                )
            ).order_by(SimDailyPnl.trade_date).all()
            
            # 如果无快照但有交易，先补录每日PnL
            if not daily_pnls:
                trades_in_month = db.query(SimTrade).filter(
                    and_(
                        SimTrade.account_id == account_id,
                        SimTrade.trade_date >= start_date,
                        SimTrade.trade_date < end_date
                    )
                ).all()
                if trades_in_month:
                    # 补录该月每个交易日
                    trade_dates = sorted(set(t.trade_date for t in trades_in_month))
                    for td in trade_dates:
                        TradeEngine.record_daily_pnl(db, account_id, td)
                    # 重新查询
                    daily_pnls = db.query(SimDailyPnl).filter(
                        and_(
                            SimDailyPnl.account_id == account_id,
                            SimDailyPnl.trade_date >= start_date,
                            SimDailyPnl.trade_date < end_date
                        )
                    ).order_by(SimDailyPnl.trade_date).all()
            
            if not daily_pnls:
                continue
            
            # 计算月度数据：使用首尾总资产差值，与总盈亏算法保持一致
            start_assets = daily_pnls[0].total_assets - daily_pnls[0].daily_profit
            end_assets = daily_pnls[-1].total_assets
            monthly_pnl_amount = end_assets - start_assets
            monthly_return = monthly_pnl_amount / start_assets * 100 if start_assets > 0 else 0
            
            # 计算月度胜率
            win_days = sum(1 for p in daily_pnls if p.daily_profit > 0)
            total_days = len(daily_pnls)
            win_rate = (win_days / total_days * 100) if total_days > 0 else 0
            
            monthly_data.append({
                "year": year,
                "month": month,
                "total_daily_profit": round(monthly_pnl_amount, 2),
                "monthly_return": round(monthly_return, 2),
                "win_rate": round(win_rate, 2),
                "trade_days": total_days,
                "max_daily_profit": round(max(p.daily_profit for p in daily_pnls), 2),
                "max_daily_loss": round(min(p.daily_profit for p in daily_pnls), 2)
            })
        
        return monthly_data
    
    @staticmethod
    def calculate_drawdown_curve(db: Session, account_id: int) -> List[Dict]:
        """计算回撤曲线"""
        daily_pnls = db.query(SimDailyPnl).filter(
            SimDailyPnl.account_id == account_id
        ).order_by(SimDailyPnl.trade_date).all()
        
        if not daily_pnls:
            return []
        
        curve_data = []
        max_assets = daily_pnls[0].total_assets
        
        for pnl in daily_pnls:
            # 更新最大资产
            if pnl.total_assets > max_assets:
                max_assets = pnl.total_assets
            
            # 计算回撤
            drawdown = (max_assets - pnl.total_assets) / max_assets * 100 if max_assets > 0 else 0
            
            curve_data.append({
                "date": pnl.trade_date,
                "total_assets": pnl.total_assets,
                "max_assets": max_assets,
                "drawdown": round(drawdown, 2),
                "daily_profit": pnl.daily_profit,
                "daily_profit_ratio": pnl.daily_profit_ratio
            })
        
        return curve_data
    
    @staticmethod
    def calculate_win_loss_distribution(db: Session, account_id: int) -> Dict[str, Any]:
        """计算盈亏分布"""
        trades = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_type == "sell",
                SimTrade.profit_ratio.isnot(None)
            )
        ).all()
        
        if not trades:
            return {"distribution": [], "histogram": []}
        
        # 计算盈亏比例分布
        profit_ratios = [t.profit_ratio for t in trades]
        
        # 分桶统计
        bins = [
            (-20, -10), (-10, -5), (-5, 0), (0, 5), (5, 10), (10, 20), (20, 50)
        ]
        
        distribution = []
        for low, high in bins:
            count = sum(1 for r in profit_ratios if low <= r < high)
            distribution.append({
                "range": f"{low}%",
                "count": count,
                "percentage": round(count / len(profit_ratios) * 100, 2)
            })
        
        # 按股票统计胜率
        stock_stats = {}
        for trade in trades:
            if trade.stock_code not in stock_stats:
                stock_stats[trade.stock_code] = {
                    "name": trade.stock_name,
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "total_profit": 0
                }
            
            stock_stats[trade.stock_code]["trades"] += 1
            stock_stats[trade.stock_code]["total_profit"] += trade.profit or 0
            
            if trade.profit and trade.profit > 0:
                stock_stats[trade.stock_code]["wins"] += 1
            else:
                stock_stats[trade.stock_code]["losses"] += 1
        
        # 计算每只股票的胜率
        stock_win_rates = []
        for code, stats in stock_stats.items():
            win_rate = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
            stock_win_rates.append({
                "code": code,
                "name": stats["name"],
                "trades": stats["trades"],
                "win_rate": round(win_rate, 2),
                "total_profit": round(stats["total_profit"], 2)
            })
        
        # 按交易次数排序
        stock_win_rates.sort(key=lambda x: x["trades"], reverse=True)
        
        return {
            "distribution": distribution,
            "total_trades": len(trades),
            "avg_profit_ratio": round(sum(profit_ratios) / len(profit_ratios), 2),
            "stock_win_rates": stock_win_rates[:20]  # 取前20只
        }
    
    @staticmethod
    def generate_performance_report(db: Session, account_id: int) -> Dict[str, Any]:
        """生成业绩报告"""
        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
        if not account:
            return {"success": False, "error": "账户不存在"}

        # ── 自动补录/刷新每日快照 ──
        existing_pnl_count = db.query(SimDailyPnl).filter(
            SimDailyPnl.account_id == account_id
        ).count()
        has_trades = db.query(SimTrade).filter(
            SimTrade.account_id == account_id
        ).count() > 0

        from app.services.trade_engine import TradeEngine

        if existing_pnl_count == 0 and has_trades:
            try:
                TradeEngine.backfill_daily_pnl(db, account_id)
            except Exception:
                pass
        elif existing_pnl_count > 0:
            # 已有快照：删除旧数据重新补录，确保使用最新算法
            try:
                db.query(SimDailyPnl).filter(
                    SimDailyPnl.account_id == account_id
                ).delete()
                db.commit()
                TradeEngine.backfill_daily_pnl(db, account_id)
            except Exception:
                pass

        # ── 刷新今日快照：确保月度计算使用最新数据 ──
        try:
            TradeEngine.record_daily_pnl(db, account_id)
        except Exception:
            pass

        # 实时计算总资产（使用统一计算函数）
        from app.services.trade_engine import TradeEngine
        fresh_total_assets = TradeEngine.calculate_total_assets(db, account=account)

        # 查询持仓（用于后续统计）
        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()
        total_market_value = sum(p.market_value or 0 for p in positions)
        total_profit_unrealized = sum(p.profit or 0 for p in positions)

        # 计算总体统计
        overall_stats = PnLCalculator.calculate_strategy_stats(db, account_id)

        # 如果无卖出记录，用持仓盈亏补充关键字段
        if overall_stats["total_trades"] == 0 and positions:
            total_profit = total_profit_unrealized
            total_profit_ratio = (total_profit / account.initial_capital * 100) if account.initial_capital > 0 else 0
            overall_stats.update({
                "total_profit": round(total_profit, 2),
                "total_profit_ratio": round(total_profit_ratio, 2),
                "total_trades": 0,
                "win_trades": 0,
                "loss_trades": 0,
                "win_rate": 0,
                "profit_loss_ratio": 0,
                "unrealized_profit": round(total_profit_unrealized, 2),
                "note": "暂无卖出记录，盈亏为持仓浮动盈亏",
            })
        
        # 计算月度盈亏
        current_year = date.today().year
        monthly_pnl = PnLCalculator.calculate_monthly_pnl(db, account_id, current_year)
        if current_year > 2024:
            monthly_pnl_prev = PnLCalculator.calculate_monthly_pnl(db, account_id, current_year - 1)
            monthly_pnl = monthly_pnl_prev + monthly_pnl
        
        # 计算回撤曲线
        drawdown_curve = PnLCalculator.calculate_drawdown_curve(db, account_id)
        
        # 计算盈亏分布
        win_loss_dist = PnLCalculator.calculate_win_loss_distribution(db, account_id)
        
        # 持仓统计（已查询过，复用）
        position_stats = {
            "total_positions": len(positions),
            "total_market_value": total_market_value,
            "total_profit": total_profit_unrealized,
            "by_type": {
                "short": {"count": 0, "value": 0, "profit": 0},
                "mid": {"count": 0, "value": 0, "profit": 0},
                "long": {"count": 0, "value": 0, "profit": 0}
            }
        }
        
        for pos in positions:
            pos_type = pos.position_type or "short"
            if pos_type in position_stats["by_type"]:
                position_stats["by_type"][pos_type]["count"] += 1
                position_stats["by_type"][pos_type]["value"] += pos.market_value
                position_stats["by_type"][pos_type]["profit"] += pos.profit
        
        # 计算策略对比
        strategies = db.query(
            SimTrade.strategy_name,
            func.count(SimTrade.id).label("trades")
        ).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_type == "sell"
            )
        ).group_by(SimTrade.strategy_name).all()
        
        strategy_comparison = []
        for strategy_name, trades_count in strategies:
            if strategy_name:
                stats = PnLCalculator.calculate_strategy_stats(
                    db, account_id, strategy_name=strategy_name
                )
                stats["strategy_name"] = strategy_name
                strategy_comparison.append(stats)
        
        return {
            "success": True,
            "account_summary": {
                "initial_capital": account.initial_capital,
                "current_capital": account.current_capital,
                "total_assets": fresh_total_assets,
                "total_profit": fresh_total_assets - account.initial_capital - (account.total_deposits or 0),
                "total_profit_ratio": round(
                    (fresh_total_assets - account.initial_capital - (account.total_deposits or 0)) / account.initial_capital * 100, 2
                ) if account.initial_capital > 0 else 0
            },
            "overall_stats": overall_stats,
            "monthly_pnl": monthly_pnl,
            "drawdown_curve": drawdown_curve,
            "win_loss_distribution": win_loss_dist,
            "position_stats": position_stats,
            "strategy_comparison": strategy_comparison,
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    @staticmethod
    def update_strategy_stats(db: Session, account_id: int) -> Dict[str, Any]:
        """更新策略统计数据"""
        # 获取所有策略名称
        strategies = db.query(
            SimTrade.strategy_name
        ).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_type == "sell"
            )
        ).distinct().all()
        
        updated_strategies = []
        
        for (strategy_name,) in strategies:
            if not strategy_name:
                continue
            
            # 计算策略统计
            stats = PnLCalculator.calculate_strategy_stats(
                db, account_id, strategy_name=strategy_name
            )
            
            # 更新或创建统计记录
            strategy_stat = db.query(SimStrategyStats).filter(
                and_(
                    SimStrategyStats.account_id == account_id,
                    SimStrategyStats.strategy_name == strategy_name
                )
            ).first()
            
            if strategy_stat:
                # 更新现有记录
                strategy_stat.total_trades = stats["total_trades"]
                strategy_stat.win_trades = stats["win_trades"]
                strategy_stat.loss_trades = stats["loss_trades"]
                strategy_stat.win_rate = stats["win_rate"]
                strategy_stat.avg_profit_ratio = stats["avg_profit_ratio"]
                strategy_stat.avg_win_ratio = stats["avg_win_ratio"]
                strategy_stat.avg_loss_ratio = stats["avg_loss_ratio"]
                strategy_stat.profit_loss_ratio = stats["profit_loss_ratio"]
                strategy_stat.max_profit_ratio = stats["max_profit_ratio"]
                strategy_stat.max_loss_ratio = stats["max_loss_ratio"]
                strategy_stat.total_profit = stats["total_profit"]
                strategy_stat.total_profit_ratio = stats["total_profit_ratio"]
                strategy_stat.avg_hold_days = stats["avg_hold_days"]
                strategy_stat.max_hold_days = stats["max_hold_days"]
            else:
                # 创建新记录
                strategy_stat = SimStrategyStats(
                    account_id=account_id,
                    strategy_name=strategy_name,
                    total_trades=stats["total_trades"],
                    win_trades=stats["win_trades"],
                    loss_trades=stats["loss_trades"],
                    win_rate=stats["win_rate"],
                    avg_profit_ratio=stats["avg_profit_ratio"],
                    avg_win_ratio=stats["avg_win_ratio"],
                    avg_loss_ratio=stats["avg_loss_ratio"],
                    profit_loss_ratio=stats["profit_loss_ratio"],
                    max_profit_ratio=stats["max_profit_ratio"],
                    max_loss_ratio=stats["max_loss_ratio"],
                    total_profit=stats["total_profit"],
                    total_profit_ratio=stats["total_profit_ratio"],
                    avg_hold_days=stats["avg_hold_days"],
                    max_hold_days=stats["max_hold_days"]
                )
                db.add(strategy_stat)
            
            updated_strategies.append(strategy_name)
        
        db.commit()
        
        return {
            "success": True,
            "updated_strategies": updated_strategies
        }