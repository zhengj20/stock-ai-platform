"""模拟交易启动维护 - WAL checkpoint + 重复账户清理"""
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def run_startup_maintenance() -> None:
    """应用启动时执行模拟交易数据维护：
    1. 强制 WAL checkpoint，将 WAL 中的未刷盘数据合并到主库（避免重启后"看似丢数据"）
    2. 执行数据库迁移（新增字段等）
    3. 合并重复账户：保留最早创建的同名账户，把其他账户的业务数据迁移过去，然后删除冗余账户
    """
    from app.core.database import SessionLocal
    from app.models.sim_trading import SimAccount

    db = SessionLocal()
    try:
        # 1) 强制 WAL checkpoint
        try:
            result = db.execute(text("PRAGMA wal_checkpoint(FULL)"))
            row = result.fetchone()
            if row:
                # busy, log_pages, checkpointed_pages
                logger.info(
                    f"WAL checkpoint 完成: busy={row[0]} log_pages={row[1]} "
                    f"checkpointed_pages={row[2]}"
                )
        except Exception as e:
            logger.warning(f"WAL checkpoint 失败: {e}")

        # 2) 数据库迁移
        _run_migrations(db)

        # 3) 清理重复账户
        _dedupe_accounts(db)
        db.commit()
    except Exception as e:
        logger.warning(f"启动维护失败: {e}")
        db.rollback()
    finally:
        db.close()


def _run_migrations(db) -> None:
    """执行数据库 schema 迁移"""
    # 检查 sim_orders 表是否有 position_type 列
    try:
        result = db.execute(text(
            "SELECT COUNT(*) FROM pragma_table_info('sim_orders') WHERE name='position_type'"
        ))
        has_column = result.scalar() > 0
        if not has_column:
            db.execute(text(
                "ALTER TABLE sim_orders ADD COLUMN position_type VARCHAR(20) DEFAULT 'short'"
            ))
            logger.info("数据库迁移: sim_orders 表添加 position_type 列")
    except Exception as e:
        logger.warning(f"数据库迁移检查失败: {e}")


def _dedupe_accounts(db) -> None:
    """合并同名账户：
    - 同一 account_name 保留 ID 最小的那一条
    - 把其他同名账户下的持仓/交易/委托/盈亏/策略/做T/复盘/监控列表/统计全部迁移到保留账户
    - 删除冗余账户
    """
    from app.models.sim_trading import (
        SimAccount, SimPosition, SimTrade, SimOrder, SimDailyPnl,
        SimTTrade, SimDailyReview, AIStrategyDecision,
        SimStrategyStats, SimWatchlist,
    )

    # 找出有重复的账户名
    dup_names = db.execute(text(
        "SELECT account_name, MIN(id) AS keep_id, COUNT(*) AS cnt "
        "FROM sim_accounts GROUP BY account_name HAVING cnt > 1"
    )).fetchall()

    if not dup_names:
        return

    for row in dup_names:
        account_name, keep_id, cnt = row[0], row[1], row[2]
        logger.info(f"检测到重复账户: name={account_name} count={cnt} 保留 id={keep_id}")

        # 找出要删除的账户
        dup_ids = [
            aid for (aid,) in db.execute(text(
                "SELECT id FROM sim_accounts WHERE account_name=:n AND id<>:keep"
            ), {"n": account_name, "keep": keep_id}).fetchall()
        ]

        for dup_id in dup_ids:
            for model in (
                SimPosition, SimTrade, SimOrder, SimDailyPnl, SimTTrade,
                SimDailyReview, AIStrategyDecision, SimStrategyStats, SimWatchlist,
            ):
                db.query(model).filter(model.account_id == dup_id).update(
                    {model.account_id: keep_id}, synchronize_session=False
                )
            # 同步资金状态到保留账户（取较大的可用资金，反映"累计"语义）
            dup_acc = db.query(SimAccount).filter(SimAccount.id == dup_id).first()
            keep_acc = db.query(SimAccount).filter(SimAccount.id == keep_id).first()
            if dup_acc and keep_acc:
                keep_acc.current_capital = max(
                    float(keep_acc.current_capital or 0),
                    float(dup_acc.current_capital or 0),
                )
                keep_acc.total_assets = max(
                    float(keep_acc.total_assets or 0),
                    float(dup_acc.total_assets or 0),
                )
            db.query(SimAccount).filter(SimAccount.id == dup_id).delete()
            logger.info(f"已合并并删除重复账户 id={dup_id}")
