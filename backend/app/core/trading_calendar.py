"""A股交易时间/日历统一工具

提供以下能力：
- is_trading_day: 今天是否为交易日（含节假日排除）
- get_last_trade_date: 获取最近交易日(YYYYMMDD)
- is_weekend: 是否周末
- is_trading_hours: 是否在交易时段（交易日 9:30-11:30, 13:00-15:00）
- should_force_refresh: 是否允许强制刷新（与 is_trading_hours 同义）
- is_active_period: 是否在活跃期（含盘前盘后缓冲，6:00-17:00）
- is_past_close: 是否已收盘（当日 15:00 之后）
- is_within_minutes_after_close: 是否在收盘后 N 分钟内

交易日判断通过腾讯财经API获取真实交易日历，自动排除法定节假日。
腾讯财经HTTP接口不封IP，可放心调用。

查询频率：每天最多查 1 次 API（进程内按天缓存）。
"""
import logging
import threading
from datetime import datetime, time, timedelta

logger = logging.getLogger(__name__)

# 交易时段定义（A股：9:30-11:30, 13:00-15:00）
_MORNING_START = time(9, 30)
_MORNING_END = time(11, 30)
_AFTERNOON_START = time(13, 0)
_AFTERNOON_END = time(15, 0)

# 活跃期（含盘前盘后缓冲）
_ACTIVE_START = time(9, 30)
_ACTIVE_END = time(17, 0)


# ── 交易日判断（腾讯财经API + 按天缓存）──────────────

def _fetch_trading_info() -> dict | None:
    """通过腾讯财经API获取交易日历信息。

    返回 {'is_today': bool, 'last_trade_date': str(YYYYMMDD)} 或 None（失败时）。
    判断逻辑：解析上证指数实时行情中的时间戳，对比是否为今天。

    腾讯接口格式: v_sh000001="1~名称~代码~最新价~...~时间戳(YYYYMMDDHHmmss)~..."
    """
    import requests as req

    today = datetime.now()
    today_str = today.strftime('%Y%m%d')
    try:
        r = req.get(
            'http://qt.gtimg.cn/q=sh000001',
            timeout=5,
        )
        text = r.text.strip()
        if not text or '=' not in text:
            return None

        # 解析腾讯行情数据
        data_part = text.split('=', 1)[1].strip('"')
        fields = data_part.split('~')

        if len(fields) < 35:
            return None

        # field[30] 是时间戳 YYYYMMDDHHmmss
        timestamp = fields[30]
        if not timestamp or len(timestamp) < 8:
            return None

        trade_date = timestamp[:8]  # 提取日期部分
        is_today = (trade_date == today_str)
        return {'is_today': is_today, 'last_trade_date': trade_date}
    except Exception as e:
        logger.warning(f"腾讯财经交易日历查询失败: {e}")

    return None


# 进程内缓存：按天刷新，每天最多查1次API（9:30后才写入缓存）
_cached_info = {'result': None, 'date': None}
_CACHE_LOCK = threading.Lock()  # 多线程并发保护

# 历史交易日缓存：从pytdx获取的已确认交易日集合
_hist_trading_dates = set()
_hist_cache_loaded = False
_HIST_LOAD_LOCK = threading.Lock()  # 防止重复加载


def _load_historical_trading_dates():
    """通过pytdx获取历史K线数据来推断哪些日期是交易日。

    pytdx返回的日K线只有实际交易日的记录，非交易日（周末/节假日）不会有数据。
    因此可以通过解析最近250根日K线的日期来构建真实交易日集合。
    """
    global _hist_trading_dates, _hist_cache_loaded
    with _HIST_LOAD_LOCK:
        if _hist_cache_loaded:
            return

        try:
            from app.core.pytdx_source import pytdx_data
            # 获取上证指数最近250根日K线（覆盖约1年）
            klines = pytdx_data.get_index_kline('000001', period=4, count=250)
            if klines:
                for k in klines:
                    dt_str = str(k.get('date', ''))
                    # pytdx返回的date格式为 YYYY-MM-DD
                    if len(dt_str) >= 10:
                        _hist_trading_dates.add(dt_str[:10])  # 'YYYY-MM-DD'
                logger.info(f"加载历史交易日: {len(_hist_trading_dates)}天")
        except Exception as e:
            logger.warning(f"加载历史交易日失败: {e}")

        _hist_cache_loaded = True


def _get_trading_info() -> dict | None:
    """获取今日交易信息（带按天缓存，线程安全）。

    只在 9:30 之后查询并缓存，避免开盘前行情未更新导致误判。
    9:30 之前返回 None，由调用方走回退逻辑。
    """
    now = datetime.now()
    today_date = now.date()

    with _CACHE_LOCK:
        # 命中当天缓存（必须是9点后写入的）
        if _cached_info['date'] == today_date and _cached_info['result'] is not None:
            return _cached_info['result']

        # 9:30前不查API，开盘前行情数据仍是上一交易日
        if now.time() < time(9, 30):
            return None

    result = _fetch_trading_info()
    if result is not None:
        logger.debug(f"交易日信息: {result}")
        with _CACHE_LOCK:
            _cached_info['result'] = result
            _cached_info['date'] = today_date
    # API失败不写缓存，下次调用重试（但9:30前不会触发）
    return result


def is_trading_day(dt: datetime | None = None) -> bool:
    """判断指定日期是否为A股交易日（含节假日排除）。

    - 如果 dt 为 None 或今天：通过腾讯财经API获取实时交易日历。
    - 如果 dt 是历史日期：通过pytdx日K线数据推断（有K线的日期=交易日）。

    Args:
        dt: 待判断的日期，None 表示判断今天

    Returns:
        bool: 是否为交易日
    """
    if dt is None or dt.date() == datetime.now().date():
        # 判断今天：走API实时查询
        info = _get_trading_info()
        if info is not None:
            return info['is_today']
        # API失败时回退：仅排除周末（保守策略）
        return datetime.now().weekday() < 5

    # 历史日期：通过pytdx K线数据推断
    _load_historical_trading_dates()
    date_str = dt.strftime('%Y-%m-%d')
    if date_str in _hist_trading_dates:
        return True

    # 未命中缓存：至少排除周末
    return dt.weekday() < 5


def get_last_trade_date() -> str:
    """获取最近一个交易日，格式 YYYYMMDD。

    优先通过腾讯财经API获取上证指数最新交易日期，结果在进程内按天缓存。
    API失败时向前逐日回退验证（使用真实交易日集合）。
    """
    info = _get_trading_info()
    if info is not None and info['last_trade_date']:
        return info['last_trade_date']

    # 回退方案：先加载历史交易日，再向前查找
    _load_historical_trading_dates()
    now_ts = datetime.now()
    d = now_ts
    for _ in range(30):
        date_str = d.strftime('%Y-%m-%d')
        if date_str in _hist_trading_dates:
            result = d.strftime('%Y%m%d')
            logger.info(f"从历史交易日找到最近交易日: {result}")
            return result
        # 如果不在缓存中，至少排除周末
        if d.weekday() < 5:
            result = d.strftime('%Y%m%d')
            logger.info(f"回退方案找到最近交易日: {result}")
            return result
        d -= timedelta(days=1)

    # 最终兜底：上周五/前工作日
    weekday = now_ts.weekday()
    days_back = 2 if weekday == 5 else 3 if weekday == 6 else 1
    result = (now_ts - timedelta(days=days_back)).strftime('%Y%m%d')
    return result


# ── 原有时间窗口函数（现在使用 is_trading_day 替代 is_weekend）────────

def is_weekend(dt: datetime | None = None) -> bool:
    """是否周末（周六、周日）。注意：此函数不判断节假日，请使用 is_trading_day。"""
    return (dt or datetime.now()).weekday() >= 5


def is_trading_hours(dt: datetime | None = None) -> bool:
    """是否在 A 股交易时段（交易日 9:30-11:30, 13:00-15:00）

    Args:
        dt: 待判断的时间，None 表示当前时间

    Returns:
        bool: 是否在交易时段
    """
    now = dt or datetime.now()
    if not is_trading_day(now):
        return False
    t = now.time()
    return (_MORNING_START <= t <= _MORNING_END) or (_AFTERNOON_START <= t <= _AFTERNOON_END)


def should_force_refresh(dt: datetime | None = None) -> bool:
    """是否允许强制刷新（与 is_trading_hours 同义，便于阅读）

    用法：手动刷新接口在非交易时间应忽略 force 参数
    """
    return is_trading_hours(dt)


def is_active_period(dt: datetime | None = None) -> bool:
    """是否在活跃期（交易日 9:30-17:00，含盘后缓冲）

    用于判断是否应该执行后台预热/刷新任务。
    """
    now = dt or datetime.now()
    if not is_trading_day(now):
        return False
    t = now.time()
    return _ACTIVE_START <= t <= _ACTIVE_END


def is_past_close(dt: datetime | None = None) -> bool:
    """是否已收盘（当日 15:00 之后，且为交易日）"""
    now = dt or datetime.now()
    if not is_trading_day(now):
        return False
    t = now.time()
    return t > _AFTERNOON_END


def is_within_minutes_after_close(dt: datetime | None = None, minutes: int = 5) -> bool:
    """是否在收盘后 N 分钟内（用于收盘刷新逻辑）"""
    now = dt or datetime.now()
    if not is_trading_day(now):
        return False
    t = now.time()
    close_end = time(_AFTERNOON_END.hour, _AFTERNOON_END.minute + minutes)
    return _AFTERNOON_END <= t <= close_end
