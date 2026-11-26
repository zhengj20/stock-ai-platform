"""数据库连接和会话管理 - SQLite WAL模式支持50+并发"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool, QueuePool
from app.core.config import get_settings

settings = get_settings()

# 判断是否多worker模式（通过环境变量或worker数量）
_MULTI_WORKER = os.environ.get("WORKERS", "1") != "1" or os.environ.get("MULTI_WORKER", "").lower() in ("1", "true", "yes")

# SQLite 使用 StaticPool（单进程）或 QueuePool（多worker）
if _MULTI_WORKER:
    # 多worker模式：使用QueuePool，支持50+并发连接
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=20,
        max_overflow=40,
        pool_timeout=30,
        pool_recycle=1800,
        echo=settings.DEBUG and settings.LOG_LEVEL == "DEBUG",
    )
else:
    # 单worker模式：使用StaticPool（性能最优）
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=settings.DEBUG and settings.LOG_LEVEL == "DEBUG",
    )

# SQLite性能优化：WAL模式 + 同步设置
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    # WAL模式：支持并发读写
    cursor.execute("PRAGMA journal_mode=WAL")
    # 同步NORMAL：性能和安全的平衡
    cursor.execute("PRAGMA synchronous=NORMAL")
    # 内存缓存大小（MB）
    cursor.execute("PRAGMA cache_size=-64000")
    # 索引统计
    cursor.execute("PRAGMA automatic_index=ON")
    # 外键约束
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL 自动 checkpoint：每 200 页（约 800KB）自动合并到主库，避免重启时数据仅停留在 WAL
    cursor.execute("PRAGMA wal_autocheckpoint=200")
    cursor.close()


@event.listens_for(engine, "checkout")
def checkpoint_on_checkout(dbapi_connection, connection_record, connection_proxy):
    """每次取出连接时若 WAL 超过 1000 页则强制 checkpoint，防止数据积压在 WAL 中"""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
        cursor.close()
    except Exception:
        pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库表结构"""
    import os
    from sqlalchemy import inspect, text
    
    db_dir = os.path.dirname(settings.DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    from app.models.user import User, InviteCode  # noqa: F401
    from app.models.chat import ChatSession, ChatMessage  # noqa: F401
    from app.models.watchlist import WatchlistItem  # noqa: F401
    from app.models.activity import UserActivity  # noqa: F401
    from app.models.daily_report import DailyReport  # noqa: F401
    from app.models.ai_stock_pick import AIStockPick  # noqa: F401
    from app.models.quota import DailyQuota, QuotaUsage  # noqa: F401
    from app.models.scheduler_config import SchedulerConfig  # noqa: F401
    from app.models.sim_trading import SimAccount, SimPosition, SimTrade, SimDailyPnl, AIStrategyDecision, SimStrategyStats, SimOrder, SimTTrade, SimDailyReview, SimWatchlist  # noqa: F401
    from app.models.holding import Holding  # noqa: F401
    from app.models.watchlist_strategy import WatchlistStrategyDecision, WatchlistStrategyConfig  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # 数据库迁移：为已有表添加新字段（必须在 ORM 查询之前执行）
    with engine.connect() as conn:
        inspector = inspect(engine)

        # 为用户表添加有效期相关字段
        if 'users' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('users')]
            need_commit = False
            if 'expiry_start_date' not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN expiry_start_date DATETIME"))
                need_commit = True
            if 'expiry_date' not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN expiry_date DATETIME"))
                need_commit = True
            if need_commit:
                conn.commit()

        # sim_positions 表迁移：添加 max_profit_ratio 和 atr_value 字段
        if 'sim_positions' in inspector.get_table_names():
            pos_cols = [col['name'] for col in inspector.get_columns('sim_positions')]
            need_pos_commit = False
            if 'max_profit_ratio' not in pos_cols:
                conn.execute(text('ALTER TABLE sim_positions ADD COLUMN max_profit_ratio FLOAT NOT NULL DEFAULT 0.0'))
                need_pos_commit = True
            if 'atr_value' not in pos_cols:
                conn.execute(text('ALTER TABLE sim_positions ADD COLUMN atr_value FLOAT NOT NULL DEFAULT 0.0'))
                need_pos_commit = True
            if need_pos_commit:
                conn.commit()

            # 存量持仓 position_type 自动迁移：根据持仓时长推断周期
            # 防止中长线持仓被误按短线风控（5天清仓）处理
            # 规则：持仓>30交易日→long, 10-30→mid, <10→short
            # 仅处理 position_type 为 NULL 或空字符串的记录（不覆盖用户已设置的值）
            # 通过 scheduler_config.pos_type_migrated 标记确保只执行一次
            if 'position_type' in pos_cols and 'buy_date' in pos_cols:
                try:
                    # 检查迁移标记
                    sc_cols = [c['name'] for c in inspector.get_columns('scheduler_config')] if 'scheduler_config' in inspector.get_table_names() else []
                    need_marker = 'pos_type_migrated_at' not in sc_cols
                    if need_marker:
                        conn.execute(text("ALTER TABLE scheduler_config ADD COLUMN pos_type_migrated_at DATETIME"))
                        conn.commit()

                    marker_row = conn.execute(text("SELECT pos_type_migrated_at FROM scheduler_config LIMIT 1")).fetchone()
                    already_migrated = marker_row and marker_row[0] is not None

                    if not already_migrated:
                        from datetime import date as _migrate_date, timedelta as _td, datetime as _dt
                        from app.core.trading_calendar import is_trading_day as _is_td
                        today = _migrate_date.today()
                        # 仅查询 position_type 为 NULL/空 的持仓（不覆盖 'short'，因为可能是用户主动设置）
                        rows = conn.execute(text(
                            "SELECT id, buy_date FROM sim_positions "
                            "WHERE position_type IS NULL OR position_type = ''"
                        )).fetchall()
                        updated = 0
                        for row in rows:
                            pos_id = row[0]
                            buy_date_str = row[1]
                            if not buy_date_str:
                                continue
                            try:
                                buy_date = _migrate_date.fromisoformat(buy_date_str)
                            except (ValueError, TypeError):
                                continue
                            # 计算交易日持仓天数
                            cur = buy_date + _td(days=1)
                            trading_days = 0
                            while cur <= today:
                                try:
                                    if _is_td(_dt.combine(cur, _dt.min.time())):
                                        trading_days += 1
                                except Exception:
                                    pass
                                cur += _td(days=1)
                                if trading_days > 200:  # 安全上限
                                    break
                            # 推断 position_type
                            if trading_days > 30:
                                inferred = 'long'
                            elif trading_days > 10:
                                inferred = 'mid'
                            else:
                                inferred = 'short'
                            conn.execute(text(
                                f"UPDATE sim_positions SET position_type = '{inferred}' WHERE id = {pos_id}"
                            ))
                            updated += 1
                        # 标记迁移完成（无论是否更新都标记，避免重复扫描）
                        conn.execute(text("UPDATE scheduler_config SET pos_type_migrated_at = CURRENT_TIMESTAMP"))
                        conn.commit()
                        if updated > 0:
                            print(f"[迁移] 存量持仓 position_type 推断完成: 更新 {updated} 条 NULL/空 记录")
                except Exception as _migrate_e:
                    print(f"[迁移] position_type 推断失败（不影响启动）: {_migrate_e}")

        # ai_strategy_decisions 表迁移：添加 retry_count 字段
        if 'ai_strategy_decisions' in inspector.get_table_names():
            dec_cols = [col['name'] for col in inspector.get_columns('ai_strategy_decisions')]
            if 'retry_count' not in dec_cols:
                conn.execute(text('ALTER TABLE ai_strategy_decisions ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0'))
                conn.commit()
            if 'strategy_mode' not in dec_cols:
                conn.execute(text("ALTER TABLE ai_strategy_decisions ADD COLUMN strategy_mode VARCHAR(20) DEFAULT 'intraday'"))
                conn.commit()
            if 'pending_order_decisions' not in dec_cols:
                conn.execute(text("ALTER TABLE ai_strategy_decisions ADD COLUMN pending_order_decisions TEXT"))
                conn.commit()
            if 't_trade_list' not in dec_cols:
                conn.execute(text("ALTER TABLE ai_strategy_decisions ADD COLUMN t_trade_list TEXT"))
                conn.commit()
            if 't_trade_count' not in dec_cols:
                conn.execute(text('ALTER TABLE ai_strategy_decisions ADD COLUMN t_trade_count INTEGER NOT NULL DEFAULT 0'))
                conn.commit()

        # 调度配置表迁移：旧字段 → 新字段 (date + time)
        if 'scheduler_config' in inspector.get_table_names():
            cols = [col['name'] for col in inspector.get_columns('scheduler_config')]
            # 历史字段（已存在可跳过）
            legacy_time = {
                'report_date': ('DATE', None),
                'report_time': ("VARCHAR(5)", '15:30'),
                'pick_date': ('DATE', None),
                'pick_time': ("VARCHAR(5)", '15:15'),
            }
            # 新增字段（2026-07 集中配置化）
            new_time = {
                't1_unlock_morning_time': ("VARCHAR(5)", '09:25'),
                't1_unlock_afternoon_time': ("VARCHAR(5)", '13:00'),
                'trading_day_check_time': ("VARCHAR(5)", '09:30'),
                'closing_cache_time': ("VARCHAR(5)", '15:05'),
                # 盘后大盘资金流刷新时间（覆盖盘中同花顺实时数据）
                'mx_flow_refresh_time_1': ("VARCHAR(5)", '15:10'),
                'mx_flow_refresh_time_2': ("VARCHAR(5)", '15:30'),
                'intraday_monitor_interval_min': ('INTEGER', '5'),
                'strategy_exec_interval_min': ('INTEGER', '5'),
                'review_strategy_time': ("VARCHAR(5)", '15:06'),
                'midday_strategy_time': ("VARCHAR(5)", '11:30'),
                'intraday_strategy_time_1': ("VARCHAR(5)", '10:30'),
                'intraday_strategy_time_2': ("VARCHAR(5)", '13:30'),
                'cleanup_report_time': ("VARCHAR(5)", '02:00'),
                'cleanup_conversation_time': ("VARCHAR(5)", '03:00'),
                # P2-9 历史归档时间
                'archive_trades_time': ("VARCHAR(5)", '03:30'),
                # 收盘前自动平短仓配置
                'auto_close_short_enabled': ('BOOLEAN', '1'),
                'auto_close_short_time': ("VARCHAR(5)", '14:50'),
                # ML模型定时训练配置
                'ml_train_enabled': ('BOOLEAN', '0'),
                'ml_train_day_of_week': ('INTEGER', '1'),
                'ml_train_time': ("VARCHAR(5)", '20:00'),
                'ml_train_days': ('INTEGER', '250'),
                'ml_train_stocks': ('INTEGER', '100'),
            }
            all_fields = {**legacy_time, **new_time}
            missing = [(c, t, d) for c, (t, d) in all_fields.items() if c not in cols]
            if missing:
                for c, sql_type, default in missing:
                    if default is None:
                        conn.execute(text(f"ALTER TABLE scheduler_config ADD COLUMN {c} {sql_type}"))
                    else:
                        quoted_default = default if sql_type == 'INTEGER' else f"'{default}'"
                        conn.execute(text(f"ALTER TABLE scheduler_config ADD COLUMN {c} {sql_type} DEFAULT {quoted_default}"))
                conn.commit()

        # watchlist_strategy_config 表迁移：添加分组时间字段
        if 'watchlist_strategy_config' in inspector.get_table_names():
            wsc_cols = [col['name'] for col in inspector.get_columns('watchlist_strategy_config')]
            wsc_commit = False
            if 'intraday_times' not in wsc_cols:
                conn.execute(text('ALTER TABLE watchlist_strategy_config ADD COLUMN intraday_times TEXT DEFAULT \'["10:25","14:10"]\''))
                wsc_commit = True
            if 'midday_times' not in wsc_cols:
                conn.execute(text('ALTER TABLE watchlist_strategy_config ADD COLUMN midday_times TEXT DEFAULT \'["12:30"]\''))
                wsc_commit = True
            if 'closing_times' not in wsc_cols:
                conn.execute(text('ALTER TABLE watchlist_strategy_config ADD COLUMN closing_times TEXT DEFAULT \'["16:00"]\''))
                wsc_commit = True
            # 迁移旧 schedule_times 数据
            if wsc_commit and 'schedule_times' in wsc_cols:
                try:
                    rows = conn.execute(text("SELECT id, schedule_times FROM watchlist_strategy_config")).fetchall()
                    for row in rows:
                        old = row[1]
                        if old and 'intraday_times' not in wsc_cols:
                            conn.execute(text(f"UPDATE watchlist_strategy_config SET intraday_times = schedule_times WHERE id = {row[0]}"))
                except Exception:
                    pass
            if wsc_commit:
                conn.commit()

        # watchlist_strategy_decisions 表迁移：添加仓位/市场环境/决策依据字段
        if 'watchlist_strategy_decisions' in inspector.get_table_names():
            wsd_cols = [col['name'] for col in inspector.get_columns('watchlist_strategy_decisions')]
            wsd_commit = False
            if 'position_ratio' not in wsd_cols:
                conn.execute(text('ALTER TABLE watchlist_strategy_decisions ADD COLUMN position_ratio FLOAT'))
                wsd_commit = True
            if 'dynamic_max_position' not in wsd_cols:
                conn.execute(text('ALTER TABLE watchlist_strategy_decisions ADD COLUMN dynamic_max_position FLOAT'))
                wsd_commit = True
            if 'suggested_allocation' not in wsd_cols:
                conn.execute(text('ALTER TABLE watchlist_strategy_decisions ADD COLUMN suggested_allocation TEXT'))
                wsd_commit = True
            if 'market_stage' not in wsd_cols:
                conn.execute(text('ALTER TABLE watchlist_strategy_decisions ADD COLUMN market_stage VARCHAR(30)'))
                wsd_commit = True
            if 'market_indicators' not in wsd_cols:
                conn.execute(text('ALTER TABLE watchlist_strategy_decisions ADD COLUMN market_indicators TEXT'))
                wsd_commit = True
            if wsd_commit:
                conn.commit()

    # sim_orders 表迁移：添加 order_source 字段
    if 'sim_orders' in inspector.get_table_names():
        cols = [col['name'] for col in inspector.get_columns('sim_orders')]
        if 'order_source' not in cols:
            try:
                conn.execute(text("ALTER TABLE sim_orders ADD COLUMN order_source VARCHAR(20) DEFAULT 'manual'"))
                conn.commit()
            except Exception as _e:
                print(f"[迁移] sim_orders.order_source 添加失败（不影响启动）: {_e}")

    # sim_trades 表迁移：添加 trade_source 字段
    if 'sim_trades' in inspector.get_table_names():
        cols = [col['name'] for col in inspector.get_columns('sim_trades')]
        if 'trade_source' not in cols:
            try:
                conn.execute(text("ALTER TABLE sim_trades ADD COLUMN trade_source VARCHAR(20) DEFAULT 'manual'"))
                conn.commit()
            except Exception as _e:
                print(f"[迁移] sim_trades.trade_source 添加失败（不影响启动）: {_e}")

    # 初始化定时任务调度配置（仅首次创建）
    db = SessionLocal()
    try:
        existing_config = db.query(SchedulerConfig).first()
        if not existing_config:
            db.add(SchedulerConfig())
            db.commit()
    finally:
        db.close()

