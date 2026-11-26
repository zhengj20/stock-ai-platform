"""A股交易日判断工具（腾讯财经API）

通过腾讯财经接口获取真实交易日历，自动排除法定节假日。
腾讯财经HTTP接口不封IP，可放心调用。

用法:
    from trading_utils import is_trading_day, get_last_trade_date
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _fetch_trading_info() -> dict | None:
    """通过腾讯财经API获取交易日历信息。

    返回 {'is_today': bool, 'last_trade_date': str(YYYYMMDD)} 或 None（失败时）。
    腾讯接口格式: v_sh000001="1~名称~代码~最新价~...~时间戳(YYYYMMDDHHmmss)~..."
    """
    import requests as req

    today = datetime.now()
    today_str = today.strftime('%Y%m%d')
    try:
        r = req.get('http://qt.gtimg.cn/q=sh000001', timeout=5)
        text = r.text.strip()
        if not text or '=' not in text:
            return None

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


# 进程内缓存：按天刷新
_cached_info = {'result': None, 'date': None}


def _get_trading_info() -> dict | None:
    """获取交易日信息（带按天缓存）。

    只在 9:00 之后查询并缓存，避免开盘前行情未更新导致误判。
    """
    now = datetime.now()
    today_date = now.date()

    # 命中当天缓存
    if _cached_info['date'] == today_date and _cached_info['result'] is not None:
        return _cached_info['result']

    # 9点前不查API
    if now.hour < 9:
        return None

    result = _fetch_trading_info()
    if result is not None:
        _cached_info['result'] = result
        _cached_info['date'] = today_date
    return result


def is_trading_day(dt: datetime | None = None) -> bool:
    """判断今天是否为A股交易日（含节假日排除）。

    通过腾讯财经API获取真实交易日历，结果在进程内按天缓存。
    API失败时回退：仅排除周末。

    Args:
        dt: 仅用于兼容旧接口签名，实际只判断"今天"

    Returns:
        bool: 今天是否为交易日
    """
    info = _get_trading_info()
    if info is not None:
        return info['is_today']
    # API失败回退：仅排除周末（保守策略）
    return datetime.now().weekday() < 5


def get_last_trade_date() -> str:
    """获取最近一个交易日，格式 YYYYMMDD。

    通过腾讯财经API获取上证指数最新交易日期。
    API失败时向前逐日回退验证。
    """
    info = _get_trading_info()
    if info is not None:
        return info['last_trade_date']

    # 回退策略：向前逐日查找
    dt = datetime.now()
    for _ in range(30):
        if dt.weekday() < 5:
            return dt.strftime('%Y%m%d')
        dt -= __import__('datetime').timedelta(days=1)

    return datetime.now().strftime('%Y%m%d')
