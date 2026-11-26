"""定时任务调度配置模型"""
from sqlalchemy import Column, Integer, String, Boolean, Date
from app.core.database import Base


class SchedulerConfig(Base):
    """定时任务调度配置（全局单条记录）"""
    __tablename__ = "scheduler_config"

    id = Column(Integer, primary_key=True, index=True)

    # AI复盘报告生成时间
    report_enabled = Column(Boolean, default=True)  # 是否启用自动生成
    report_date = Column(Date, nullable=True)        # 保留兼容，已弃用（定时任务使用 datetime.now()，前端配置不生效）
    report_time = Column(String(5), default="16:30")  # 具体时间 HH:mm (龙虎榜16点后出)

    # AI股票推荐生成时间（AI选股页面每日推荐，量化筛选+LLM分析）
    pick_enabled = Column(Boolean, default=True)      # 是否启用自动生成
    pick_date = Column(Date, nullable=True)           # 保留兼容，已弃用（定时任务使用 datetime.now()，前端配置不生效）
    pick_time = Column(String(5), default="15:20")    # 具体时间 HH:mm

    # 模拟交易 T+1 解锁时间
    t1_unlock_morning_time = Column(String(5), default="09:25")    # 上午 T+1 解锁时间
    t1_unlock_afternoon_time = Column(String(5), default="13:00")  # 下午 T+1 解锁时间

    # 交易日判断时间（早盘 09:30 判断今天是否为交易日）
    trading_day_check_time = Column(String(5), default="09:30")

    # 收盘缓存时间（执行市场数据/龙虎榜/板块分析预热 + 当日PnL记录）
    closing_cache_time = Column(String(5), default="15:02")

    # 盘后大盘资金流刷新时间（拉取完整主力资金流向，覆盖盘中同花顺实时数据）
    # 注：字段名 mx_flow_refresh_time_* 为历史遗留，保留以兼容既有数据库列，不做迁移
    mx_flow_refresh_time_1 = Column(String(5), default="15:05")  # 盘后刷新一次即可（写入24h缓存）
    mx_flow_refresh_time_2 = Column(String(5), default="15:30")  # 保留兼容，实际重复，可禁用

    # 盘中监控间隔（分钟，仅交易时段）
    intraday_monitor_interval_min = Column(Integer, default=5)

    # 策略执行间隔（分钟，盘中AI策略自动执行的频率）
    strategy_exec_interval_min = Column(Integer, default=5)

    # 收盘复盘+次日策略合并生成时间（复盘当日交易 + 生成次日买卖策略，LLM调用）
    review_strategy_time = Column(String(5), default="15:08")

    # 午间策略调整时间（上午收盘后，默认11:30）
    midday_strategy_time = Column(String(5), default="11:30")

    # 盘中策略生成时间（交易时段内自动生成 intraday 模式策略，复用 generate_strategy）
    intraday_strategy_time_1 = Column(String(5), default="10:30")  # 上午盘中
    intraday_strategy_time_2 = Column(String(5), default="13:30")  # 下午盘中

    # 收盘前自动平短仓（避免短线隔夜风险）
    auto_close_short_enabled = Column(Boolean, default=True)  # 是否启用
    auto_close_short_time = Column(String(5), default="14:50")  # 平仓时间 HH:mm

    # 凌晨清理时间
    cleanup_report_time = Column(String(5), default="02:00")
    cleanup_conversation_time = Column(String(5), default="03:00")

    # P2-9 历史交易记录归档时间（凌晨，删除90/180/30天前的旧数据）
    archive_trades_time = Column(String(5), default="03:30")

    # ML模型定时训练配置（智能选股技术评分，每周自动重训一次）
    ml_train_enabled = Column(Boolean, default=False)   # 是否启用自动训练
    ml_train_day_of_week = Column(Integer, default=1)    # 星期几训练 (0=周日, 1=周一...6=周六)
    ml_train_time = Column(String(5), default="20:00")   # 训练时间（收盘后）
    ml_train_days = Column(Integer, default=250)          # 训练数据天数
    ml_train_stocks = Column(Integer, default=100)        # 股票数量
