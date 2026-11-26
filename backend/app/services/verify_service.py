"""选股前向验证服务

核心功能：
1. 记录每日选股结果到 PickVerification 表
2. 每个交易日收盘后自动回填 T+1/T+3/T+5/T+10 涨跌幅
3. 统计各策略的真实命中率数据
4. 提供 API 查询验证统计数据

使用方式：
- 定时任务：每个交易日 15:30 运行 verify_past_picks()
- 手动触发：调用 record_today_picks() + verify_past_picks()
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.pytdx_source import pytdx_data
from app.models.pick_verification import PickVerification

logger = logging.getLogger(__name__)


class VerifyService:
    """前向验证服务"""

    def record_today_picks(self, picks: List[Dict[str, Any]], strategy_type: str,
                           pick_date: Optional[date] = None) -> int:
        """记录当日选股结果到验证表

        Args:
            picks: 选股结果列表，每项包含 code, name, score, price 等字段
            strategy_type: 策略类型（multi_factor/low_absorption/capital_flow/ml_prediction）
            pick_date: 选股日期，默认为今天

        Returns:
            插入的记录数
        """
        if not picks:
            return 0

        if pick_date is None:
            pick_date = date.today()

        records = []
        for pick in picks:
            code = pick.get('code') or pick.get('stock_code')
            if not code:
                continue

            record = PickVerification(
                pick_date=pick_date,
                strategy_type=strategy_type,
                stock_code=code,
                stock_name=pick.get('name') or pick.get('stock_name', ''),
                pick_score=pick.get('score') or pick.get('pick_score'),
                entry_price=pick.get('price') or pick.get('entry_price'),
            )
            records.append(record)

        if not records:
            return 0

        try:
            db = next(get_db())
            db.bulk_save_objects(records)
            db.commit()
            logger.info(f"记录 {len(records)} 只 {strategy_type} 选股结果 ({pick_date})")
            return len(records)
        except Exception as e:
            logger.error(f"记录选股结果失败: {e}")
            return 0

    def verify_past_picks(self, days_to_check: List[int] = None) -> Dict[str, Any]:
        """回填过去选股的 T+N 日涨跌幅

        Args:
            days_to_check: 需要检查的持有天数列表，默认 [1, 3, 5, 10]

        Returns:
            验证统计信息
        """
        if days_to_check is None:
            days_to_check = [1, 3, 5, 10]

        today_str = datetime.now().strftime('%Y-%m-%d')
        verified_count = 0

        try:
            db = next(get_db())

            for check_days in days_to_check:
                field_name = f'return_{check_days}d'
                pick_date_limit = (datetime.now() - timedelta(days=check_days)).date()

                pending = db.query(PickVerification).filter(
                    PickVerification.pick_date <= pick_date_limit,
                    getattr(PickVerification, field_name) == None
                ).limit(500).all()

                for pv in pending:
                    try:
                        return_pct = self._calculate_forward_return(
                            pv.stock_code, pv.pick_date, check_days, today_str
                        )
                        if return_pct is not None:
                            setattr(pv, field_name, round(return_pct, 2))
                            pv.verified_at = datetime.now()
                            verified_count += 1
                    except Exception as e:
                        logger.debug(f"验证 {pv.stock_code} T+{check_days} 失败: {e}")

            if verified_count > 0:
                db.commit()
                logger.info(f"完成 {verified_count} 条选股验证记录")

        except Exception as e:
            logger.error(f"批量验证失败: {e}")

        return {
            'verified_count': verified_count,
            'check_periods': days_to_check,
            'stats': self.get_strategy_stats()
        }

    def _calculate_forward_return(self, stock_code: str, pick_date: date,
                                  hold_days: int, today_str: str) -> Optional[float]:
        """计算从选股日起 N 日后的涨跌幅

        Args:
            stock_code: 股票代码
            pick_date: 选股日期
            hold_days: 持有天数（交易日）
            today_str: 今天的日期字符串 YYYY-MM-DD

        Returns:
            涨跌幅百分比，失败返回 None
        """
        try:
            klines = pytdx_data.get_kline(stock_code, period=4, count=hold_days + 30)
            if not klines:
                return None

            pick_date_str = pick_date.strftime('%Y-%m-%d')
            entry_price = None
            exit_idx = None

            for i, k in enumerate(klines):
                dt_str = str(k.get('date', ''))
                if len(dt_str) >= 10:
                    dt_str = dt_str[:10]

                if entry_price is None and dt_str == pick_date_str:
                    entry_price = float(k.get('close', 0))

                if entry_price is not None and exit_idx is None:
                    if dt_str >= pick_date_str:
                        trading_days_passed = sum(
                            1 for _k in klines[:i + 1]
                            if str(_k.get('date', ''))[:10] >= pick_date_str
                        )
                        if trading_days_passed >= hold_days:
                            exit_idx = i
                            break

            if entry_price is None or exit_idx is None or entry_price <= 0:
                return None

            exit_price = float(klines[exit_idx].get('close', 0))
            return (exit_price - entry_price) / entry_price * 100

        except Exception as e:
            logger.debug(f"计算 {stock_code} T+{hold_days} 收益失败: {e}")
            return None

    def get_strategy_stats(self, strategy_type: Optional[str] = None,
                          days: int = 30) -> List[Dict[str, Any]]:
        """获取策略验证统计

        Args:
            strategy_type: 指定策略类型，None=所有策略
            days: 统计最近N天的数据

        Returns:
            各策略的统计数据列表
        """
        try:
            db = next(get_db())
            since_date = (datetime.now() - timedelta(days=days)).date()

            query = db.query(PickVerification).filter(
                PickVerification.pick_date >= since_date
            )

            if strategy_type:
                query = query.filter(PickVerification.strategy_type == strategy_type)

            records = query.all()

            stats_by_strategy = {}
            for r in records:
                st = r.strategy_type
                if st not in stats_by_strategy:
                    stats_by_strategy[st] = {
                        'strategy': st,
                        'total_picks': 0,
                        'win_1d': 0, 'verified_1d': 0,
                        'win_3d': 0, 'verified_3d': 0,
                        'win_5d': 0, 'verified_5d': 0,
                        'win_10d': 0, 'verified_10d': 0,
                        'avg_return_1d': 0.0, 'sum_return_1d': 0.0,
                        'avg_return_3d': 0.0, 'sum_return_3d': 0.0,
                        'avg_return_5d': 0.0, 'sum_return_5d': 0.0,
                        'avg_return_10d': 0.0, 'sum_return_10d': 0.0,
                    }

                stats = stats_by_strategy[st]
                stats['total_picks'] += 1

                for period in ['1d', '3d', '5d', '10d']:
                    ret_val = getattr(r, f'return_{period}', None)
                    if ret_val is not None:
                        stats[f'verified_{period}'] += 1
                        stats[f'sum_return_{period}'] += ret_val
                        if ret_val > 0:
                            stats[f'win_{period}'] += 1

            result = []
            for st, stats in stats_by_strategy.items():
                final = {
                    'strategy': stats['strategy'],
                    'total_picks': stats['total_picks'],
                }

                for period in ['1d', '3d', '5d', '10d']:
                    verified = stats[f'verified_{period}']
                    wins = stats[f'win_{period}']
                    sum_ret = stats[f'sum_return_{period}']

                    final.update({
                        f'verified_{period}': verified,
                        f'win_rate_{period}': round(wins / verified * 100, 1) if verified > 0 else None,
                        f'avg_return_{period}': round(sum_ret / verified, 2) if verified > 0 else None,
                    })

                result.append(final)

            return result

        except Exception as e:
            logger.error(f"获取策略统计失败: {e}")
            return []

    def get_pick_detail(self, stock_code: str, strategy_type: str,
                       pick_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
        """查询单只股票的验证详情

        Args:
            stock_code: 股票代码
            strategy_type: 策略类型
            pick_date: 选股日期，None=最近一次

        Returns:
            验证记录字典
        """
        try:
            db = next(get_db())
            query = db.query(PickVerification).filter(
                PickVerification.stock_code == stock_code,
                PickVerification.strategy_type == strategy_type
            )

            if pick_date:
                query = query.filter(PickVerification.pick_date == pick_date)
            else:
                query = query.order_by(PickVerification.pick_date.desc())

            record = query.first()
            if not record:
                return None

            return {
                'stock_code': record.stock_code,
                'stock_name': record.stock_name,
                'pick_date': str(record.pick_date),
                'strategy_type': record.strategy_type,
                'pick_score': record.pick_score,
                'entry_price': record.entry_price,
                'return_1d': record.return_1d,
                'return_3d': record.return_3d,
                'return_5d': record.return_5d,
                'return_10d': record.return_10d,
                'verified_at': str(record.verified_at) if record.verified_at else None,
            }

        except Exception as e:
            logger.error(f"查询验证详情失败: {e}")
            return None


# Global instance
verify_service = VerifyService()
