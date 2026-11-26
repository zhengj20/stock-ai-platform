"""模拟交易系统数据模型"""
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class SimAccount(Base):
    """模拟交易账户"""
    __tablename__ = "sim_accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_name = Column(String(50), nullable=False, default="AI智能策略账户")
    initial_capital = Column(Float, nullable=False, default=100000.0)  # 初始资金（默认10万）
    current_capital = Column(Float, nullable=False, default=100000.0)  # 当前可用资金
    total_assets = Column(Float, nullable=False, default=100000.0)  # 总资产（资金+持仓市值）
    frozen_capital = Column(Float, nullable=False, default=0.0)  # 冻结资金
    total_deposits = Column(Float, nullable=False, default=0.0)  # 累计入金
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关联
    positions = relationship("SimPosition", back_populates="account", lazy="dynamic")
    trades = relationship("SimTrade", back_populates="account", lazy="dynamic")
    daily_pnls = relationship("SimDailyPnl", back_populates="account", lazy="dynamic")


class SimPosition(Base):
    """持仓记录"""
    __tablename__ = "sim_positions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sim_accounts.id"), nullable=False, index=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(50), default="")
    
    # 持仓信息
    total_quantity = Column(Integer, nullable=False, default=0)  # 总持仓数量
    available_quantity = Column(Integer, nullable=False, default=0)  # 可卖数量（A股T+1）
    cost_price = Column(Float, nullable=False, default=0.0)  # 成本价
    current_price = Column(Float, nullable=False, default=0.0)  # 当前价格
    market_value = Column(Float, nullable=False, default=0.0)  # 市值
    profit = Column(Float, nullable=False, default=0.0)  # 浮动盈亏
    profit_ratio = Column(Float, nullable=False, default=0.0)  # 盈亏比例(%)
    max_profit_ratio = Column(Float, nullable=False, default=0.0)  # 持仓期间最高盈利比例(%)
    atr_value = Column(Float, nullable=False, default=0.0)  # ATR(14)值，用于动态止损

    # 持仓类型
    position_type = Column(String(20), default="short")  # short=短线, mid=中线, long=长线
    
    # 买入信息
    buy_date = Column(String(10), nullable=True)  # 首次买入日期
    buy_reason = Column(Text, nullable=True)  # 买入理由
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    account = relationship("SimAccount", back_populates="positions")
    
    __table_args__ = (
        Index("idx_position_account_stock", "account_id", "stock_code", unique=True),
    )


class SimTrade(Base):
    """交易记录"""
    __tablename__ = "sim_trades"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sim_accounts.id"), nullable=False, index=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(50), default="")
    
    # 交易信息
    trade_type = Column(String(10), nullable=False)  # buy=买入, sell=卖出
    trade_price = Column(Float, nullable=False)  # 成交价格
    trade_quantity = Column(Integer, nullable=False)  # 成交数量
    trade_amount = Column(Float, nullable=False)  # 成交金额
    commission = Column(Float, nullable=False, default=0.0)  # 佣金
    stamp_tax = Column(Float, nullable=False, default=0.0)  # 印花税
    transfer_fee = Column(Float, nullable=False, default=0.0)  # 过户费
    total_cost = Column(Float, nullable=False, default=0.0)  # 总费用
    
    # 盈亏（仅卖出时有效）
    profit = Column(Float, nullable=True)  # 本次盈亏
    profit_ratio = Column(Float, nullable=True)  # 盈亏比例(%)
    
    # 交易信息
    trade_date = Column(String(10), nullable=False, index=True)  # 交易日期
    trade_time = Column(String(8), nullable=True)  # 交易时间
    strategy_name = Column(String(50), nullable=True)  # 策略名称
    strategy_reason = Column(Text, nullable=True)  # 交易理由

    # 交易来源：ai_strategy=AI策略, manual=手动交易/委托, risk_control=风控卖出, auto_close_short=自动平短仓, t_trade=做T
    trade_source = Column(String(20), default="manual")

    # 持仓类型
    position_type = Column(String(20), default="short")  # short=短线, mid=中线, long=长线

    created_at = Column(DateTime, default=datetime.now)

    # 关联
    account = relationship("SimAccount", back_populates="trades")
    
    __table_args__ = (
        Index("idx_trade_account_date", "account_id", "trade_date"),
        Index("idx_trade_stock", "account_id", "stock_code"),
    )


class SimDailyPnl(Base):
    """每日盈亏记录"""
    __tablename__ = "sim_daily_pnls"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sim_accounts.id"), nullable=False, index=True)
    trade_date = Column(String(10), nullable=False, index=True)  # 日期
    
    # 资金信息
    initial_capital = Column(Float, nullable=False)  # 初始资金
    available_capital = Column(Float, nullable=False)  # 可用资金
    market_value = Column(Float, nullable=False, default=0.0)  # 持仓市值
    total_assets = Column(Float, nullable=False)  # 总资产
    
    # 盈亏信息
    daily_profit = Column(Float, nullable=False, default=0.0)  # 当日盈亏
    daily_profit_ratio = Column(Float, nullable=False, default=0.0)  # 当日收益率(%)
    total_profit = Column(Float, nullable=False, default=0.0)  # 累计盈亏
    total_profit_ratio = Column(Float, nullable=False, default=0.0)  # 累计收益率(%)
    
    # 持仓统计
    position_count = Column(Integer, nullable=False, default=0)  # 持仓股票数量
    total_trades = Column(Integer, nullable=False, default=0)  # 当日交易次数
    
    # 胜率统计
    win_count = Column(Integer, nullable=False, default=0)  # 盈利交易次数
    loss_count = Column(Integer, nullable=False, default=0)  # 亏损交易次数
    win_rate = Column(Float, nullable=False, default=0.0)  # 胜率(%)
    
    # 最大回撤
    max_drawdown = Column(Float, nullable=False, default=0.0)  # 最大回撤(%)
    
    created_at = Column(DateTime, default=datetime.now)

    # 关联
    account = relationship("SimAccount", back_populates="daily_pnls")
    
    __table_args__ = (
        Index("idx_daily_pnl_account_date", "account_id", "trade_date", unique=True),
    )


class AIStrategyDecision(Base):
    """AI策略决策记录"""
    __tablename__ = "ai_strategy_decisions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sim_accounts.id"), nullable=False, index=True)
    decision_date = Column(String(10), nullable=False, index=True)  # 决策日期
    strategy_mode = Column(String(20), default="intraday")  # intraday/intraday_afternoon/midday/next_day

    # AI决策参数
    market_sentiment = Column(String(20), nullable=True)  # 市场情绪：bullish/bearish/neutral
    position_ratio = Column(Float, nullable=True)  # 建议仓位比例(%)
    short_term_ratio = Column(Float, nullable=True)  # 短线仓位比例
    mid_term_ratio = Column(Float, nullable=True)  # 中线仓位比例
    long_term_ratio = Column(Float, nullable=True)  # 长线仓位比例
    
    # 买入决策
    buy_list = Column(Text, nullable=True)  # JSON: 买入股票列表
    buy_count = Column(Integer, nullable=False, default=0)  # 买入股票数量
    
    # 卖出决策
    sell_list = Column(Text, nullable=True)  # JSON: 卖出股票列表
    sell_count = Column(Integer, nullable=False, default=0)  # 卖出股票数量

    # 做T决策
    t_trade_list = Column(Text, nullable=True)  # JSON: 做T股票列表
    t_trade_count = Column(Integer, nullable=False, default=0)  # 做T股票数量

    # 待成交限价单决策
    pending_order_decisions = Column(Text, nullable=True)  # JSON: AI对旧限价单的决策（cancel/modify/keep）

    # AI报告
    ai_analysis = Column(Text, nullable=True)  # AI分析报告
    strategy_summary = Column(Text, nullable=True)  # 策略摘要
    
    # 执行状态
    execution_status = Column(String(20), default="pending")  # pending/executed/completed/failed/manual
    executed_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)  # 执行重试次数（上限3次后置failed）
    source = Column(String(10), default="auto")  # auto=定时任务自动生成, manual=手动生成

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_strategy_decision_account_date_mode", "account_id", "decision_date", "strategy_mode", unique=True),
    )


class SimStrategyStats(Base):
    """模拟交易策略统计"""
    __tablename__ = "sim_strategy_stats"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sim_accounts.id"), nullable=False, index=True)
    strategy_name = Column(String(50), nullable=False)  # 策略名称
    
    # 统计数据
    total_trades = Column(Integer, nullable=False, default=0)  # 总交易次数
    win_trades = Column(Integer, nullable=False, default=0)  # 盈利次数
    loss_trades = Column(Integer, nullable=False, default=0)  # 亏损次数
    win_rate = Column(Float, nullable=False, default=0.0)  # 胜率(%)
    
    avg_profit_ratio = Column(Float, nullable=False, default=0.0)  # 平均盈亏比例(%)
    avg_win_ratio = Column(Float, nullable=False, default=0.0)  # 平均盈利比例(%)
    avg_loss_ratio = Column(Float, nullable=False, default=0.0)  # 平均亏损比例(%)
    profit_loss_ratio = Column(Float, nullable=False, default=0.0)  # 盈亏比
    
    max_profit_ratio = Column(Float, nullable=False, default=0.0)  # 最大单笔盈利(%)
    max_loss_ratio = Column(Float, nullable=False, default=0.0)  # 最大单笔亏损(%)
    
    total_profit = Column(Float, nullable=False, default=0.0)  # 累计盈亏金额
    total_profit_ratio = Column(Float, nullable=False, default=0.0)  # 累计收益率(%)
    
    # 持仓统计
    avg_hold_days = Column(Float, nullable=False, default=0.0)  # 平均持仓天数
    max_hold_days = Column(Integer, nullable=False, default=0)  # 最长持仓天数
    
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_strategy_stats_account_name", "account_id", "strategy_name", unique=True),
    )


class SimOrder(Base):
    """委托单"""
    __tablename__ = "sim_orders"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sim_accounts.id"), nullable=False, index=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(50), default="")

    # 委托信息
    order_type = Column(String(10), nullable=False)  # buy=买入, sell=卖出, cancel=撤单
    order_quantity = Column(Integer, nullable=False)  # 委托数量
    limit_price = Column(Float, nullable=True)  # 限价（None 表示市价单）
    order_price = Column(Float, nullable=False)  # 委托价格（市价单时为当前价快照）

    # 委托状态
    status = Column(String(20), nullable=False, default="pending")
    # pending=待成交, partial=部分成交, filled=已成交, cancelled=已撤销, expired=已过期

    # 成交信息
    filled_quantity = Column(Integer, nullable=False, default=0)  # 已成交数量
    filled_price = Column(Float, nullable=True)  # 成交均价
    filled_amount = Column(Float, nullable=False, default=0.0)  # 成交金额
    commission = Column(Float, nullable=False, default=0.0)  # 佣金

    # 过期时间（限价单有效期）
    expire_date = Column(String(10), nullable=True)  # 过期日期
    expire_time = Column(String(8), nullable=True)  # 过期时间（默认15:00:00）

    # 持仓类型
    position_type = Column(String(20), default="short")  # short=短线, mid=中线, long=长线

    # 策略关联
    strategy_name = Column(String(50), nullable=True)  # 策略名称
    strategy_reason = Column(Text, nullable=True)  # 下单理由

    # 委托来源：ai_strategy=AI策略, manual=手动交易/委托, risk_control=风控卖出, auto_close_short=自动平短仓, t_trade=做T
    order_source = Column(String(20), default="manual")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    account = relationship("SimAccount", backref="orders")

    __table_args__ = (
        Index("idx_order_account_stock", "account_id", "stock_code"),
        Index("idx_order_account_status", "account_id", "status"),
    )


class SimTTrade(Base):
    """做T记录"""
    __tablename__ = "sim_t_trades"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sim_accounts.id"), nullable=False, index=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(50), default="")

    # 买入信息
    buy_price = Column(Float, nullable=False)  # 买入价格
    buy_quantity = Column(Integer, nullable=False)  # 买入数量
    buy_date = Column(String(10), nullable=False)  # 买入日期
    buy_time = Column(String(8), nullable=True)  # 买入时间
    buy_amount = Column(Float, nullable=False, default=0.0)  # 买入金额
    buy_commission = Column(Float, nullable=False, default=0.0)  # 买入佣金

    # 卖出信息（底仓不动，仅记录T操作部分）
    sell_price = Column(Float, nullable=True)  # 卖出价格
    sell_quantity = Column(Integer, nullable=True)  # 卖出数量
    sell_date = Column(String(10), nullable=True)  # 卖出日期
    sell_time = Column(String(8), nullable=True)  # 卖出时间
    sell_amount = Column(Float, nullable=True)  # 卖出金额
    sell_commission = Column(Float, nullable=False, default=0.0)  # 卖出佣金
    stamp_tax = Column(Float, nullable=False, default=0.0)  # 印花税

    # 持仓时间
    quantity = Column(Integer, nullable=False)  # 做T数量
    hold_minutes = Column(Integer, nullable=True)  # 持仓分钟数（日内T）
    hold_days = Column(Integer, nullable=False, default=0)  # 持仓天数（跨日T）

    # 盈亏
    profit = Column(Float, nullable=True)  # 本次做T盈亏
    profit_ratio = Column(Float, nullable=True)  # 盈亏比例(%)

    # 状态与策略
    status = Column(String(20), nullable=False, default="open")  # open=待卖出, closed=已完成
    strategy_name = Column(String(50), nullable=True)  # 策略名称
    strategy_reason = Column(Text, nullable=True)  # 做T理由

    created_at = Column(DateTime, default=datetime.now)

    # 关联
    account = relationship("SimAccount", backref="t_trades")

    __table_args__ = (
        Index("idx_ttrade_account_stock", "account_id", "stock_code"),
        Index("idx_ttrade_account_status", "account_id", "status"),
    )


class SimDailyReview(Base):
    """每日复盘"""
    __tablename__ = "sim_daily_reviews"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sim_accounts.id"), nullable=False, index=True)
    review_date = Column(String(10), nullable=False, index=True)  # 复盘日期

    # 盈亏汇总
    daily_pnl = Column(Float, nullable=False, default=0.0)  # 当日盈亏
    total_pnl = Column(Float, nullable=False, default=0.0)  # 累计盈亏
    total_pnl_ratio = Column(Float, nullable=False, default=0.0)  # 累计收益率(%)

    # 交易统计
    total_trades = Column(Integer, nullable=False, default=0)  # 交易次数
    win_count = Column(Integer, nullable=False, default=0)  # 盈利笔数
    loss_count = Column(Integer, nullable=False, default=0)  # 亏损笔数
    win_rate = Column(Float, nullable=False, default=0.0)  # 当日胜率(%)

    # 策略评估
    strategy_accuracy = Column(Float, nullable=True)  # 策略准确率(%)
    strategy_name = Column(String(50), nullable=True)  # 主要策略名称

    # 持仓概览
    position_count = Column(Integer, nullable=False, default=0)  # 持仓股票数量
    position_details = Column(Text, nullable=True)  # JSON: 持仓明细

    # 复盘内容
    trade_summary = Column(Text, nullable=True)  # 交易总结
    market_analysis = Column(Text, nullable=True)  # 市场分析
    lessons = Column(Text, nullable=True)  # 经验教训
    tomorrow_plan = Column(Text, nullable=True)  # 明日计划

    # AI辅助
    ai_review = Column(Text, nullable=True)  # AI生成的复盘报告

    created_at = Column(DateTime, default=datetime.now)

    # 关联
    account = relationship("SimAccount", backref="daily_reviews")

    __table_args__ = (
        Index("idx_review_account_date", "account_id", "review_date", unique=True),
    )


class SimWatchlist(Base):
    """模拟交易监控列表"""
    __tablename__ = "sim_watchlist"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sim_accounts.id"), nullable=False, index=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(50), default="")

    # 监控条件
    alert_price = Column(Float, nullable=True)  # 预警价格
    alert_type = Column(String(20), nullable=False, default="price_above")
    # price_above=突破价格, price_below=跌破价格, percent_change=涨跌幅预警
    alert_percent = Column(Float, nullable=True)  # 涨跌幅阈值(%)
    is_active = Column(Boolean, nullable=False, default=True)  # 是否启用

    # 监控来源
    source = Column(String(50), nullable=True)  # 来源：ai_strategy/manual/strategy_alert
    strategy_name = Column(String(50), nullable=True)  # 关联策略名称
    buy_reason = Column(Text, nullable=True)  # 关注理由

    # 触发记录
    last_triggered_at = Column(DateTime, nullable=True)  # 最后触发时间
    trigger_count = Column(Integer, nullable=False, default=0)  # 触发次数

    # 备注
    notes = Column(Text, nullable=True)  # 个人备注
    target_price = Column(Float, nullable=True)  # 目标价
    stop_loss_price = Column(Float, nullable=True)  # 止损价

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    account = relationship("SimAccount", backref="watchlist_items")

    __table_args__ = (
        Index("idx_watchlist_account_stock", "account_id", "stock_code", unique=True),
    )


class SimFailurePattern(Base):
    """失败交易案例记录（P2-7）

    在 execute_sell_order 中当一笔卖出为亏损时自动写入，
    用于 AI 策略生成时注入"近30天失败模式 Top3"提示，避免重复犯错。
    """
    __tablename__ = "sim_failure_patterns"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sim_accounts.id"), nullable=False, index=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(50), default="")

    # 失败上下文（用于模式识别）
    source = Column(String(50), nullable=True)        # 候选来源：capital_flow/gainers/oversold/low_absorption/multi_factor/manual
    entry_change_pct = Column(Float, nullable=True)   # 买入时当日涨幅（>5% 视为追高）
    position_type = Column(String(10), nullable=True) # short/mid/long

    # 持仓周期与结果
    hold_days = Column(Integer, nullable=True)        # 实际持仓天数
    profit_ratio = Column(Float, nullable=False)      # 卖出时盈亏率(%)
    failure_reason = Column(String(100), nullable=True)  # 失败原因分类：stop_loss/time_stop/manual/chase_high/sector_decline

    # 时间
    buy_date = Column(String(10), nullable=True)
    sell_date = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index("idx_failure_account_sell_date", "account_id", "sell_date"),
        Index("idx_failure_account_source", "account_id", "source"),
    )


