import asyncio
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
# 资金流数据源：仅使用腾讯API（稳定可靠）
import logging

# 新增：直连数据源
from app.core.data_sources import (
    TencentSource, EastMoneySource, EastMoneyDataCenter
)
from app.core.pytdx_source import pytdx_data
from app.core.cache import cache_get, cache_set, swr_cache, NS_FINANCIAL, NS_STOCKLIST, NS_CAPITAL_FLOW

logger = logging.getLogger(__name__)

STOCK_NAMES = {
    "600519": "贵州茅台", "000001": "平安银行", "300750": "宁德时代",
    "002594": "比亚迪", "601318": "中国平安", "000858": "五粮液",
    "600036": "招商银行", "601012": "隆基绿能", "002475": "立讯精密",
    "300059": "东方财富", "002415": "海康威视", "600900": "长江电力",
}

# ═══════════════════════════════════════════════════════════
# 诊断评分统一常量 — 前后端共享口径，避免分档/阈值漂移
# ═══════════════════════════════════════════════════════════

# 综合评分 5 档分级（前后端必须一致）
SCORE_THRESHOLDS = [
    {'min': 75, 'level': 'strong_bullish', 'title': '强势偏多', 'type': 'danger'},
    {'min': 60, 'level': 'bullish',       'title': '偏多',     'type': 'danger'},
    {'min': 45, 'level': 'neutral',       'title': '中性',     'type': 'info'},
    {'min': 30, 'level': 'bearish',       'title': '偏空',     'type': 'success'},
    {'min': 0,  'level': 'strong_bearish', 'title': '弱势偏空', 'type': 'success'},
]

def get_score_level(score):
    """根据综合评分返回分档信息（前后端口径统一）"""
    if score is None:
        return {'level': 'no_data', 'title': '数据不足', 'type': 'info'}
    for t in SCORE_THRESHOLDS:
        if score >= t['min']:
            return t
    return SCORE_THRESHOLDS[-1]

# 行业 PE 阈值表（用于基本面评分，避免一刀切）
# 键：股票代码前缀；值：(industry_name, pe_low, pe_high)
INDUSTRY_PE_MAP = {
    '600': ('沪市主板', 15, 30),
    '601': ('金融/地产', 8, 15),
    '603': ('制造业', 15, 30),
    '605': ('消费/医药', 20, 35),
    '000': ('深市主板', 15, 30),
    '001': ('金融/地产', 8, 15),
    '002': ('中小板制造', 18, 35),
    '300': ('创业板科技', 25, 50),
    '688': ('科创板硬科技', 30, 60),
}

# 按股票名称关键词判断行业（优先级高于代码前缀）
INDUSTRY_NAME_MAP = [
    (['银行'], '银行', 5, 10),
    (['证券', '保险', '金融'], '金融', 10, 18),
    (['地产', '置业', '控股'], '房地产', 8, 15),
    (['药业', '制药', '生物', '医疗', '医药'], '医药', 25, 40),
    (['酒', '食品', '乳', '味'], '消费', 20, 35),
    (['科技', '电子', '软件', '信息', '智能', '芯'], '科技', 30, 55),
    (['能源', '电力', '煤炭', '石油', '燃气', '光'], '能源', 12, 22),
    (['钢铁', '有色', '矿', '铝', '铜'], '资源', 15, 25),
    (['汽车', '机械', '重工', '设备'], '制造', 15, 30),
    (['建', '材', '水泥'], '建材', 12, 25),
    (['传媒', '影视', '游戏', '文'], '传媒', 20, 35),
    (['交', '运', '航空', '港', '路'], '交运', 12, 25),
]

def get_industry_info(stock_code, stock_name=''):
    """返回 (industry_name, pe_low, pe_high)"""
    if stock_name:
        for keys, name, lo, hi in INDUSTRY_NAME_MAP:
            if any(k in stock_name for k in keys):
                return name, lo, hi
    if stock_code and len(stock_code) >= 3:
        info = INDUSTRY_PE_MAP.get(stock_code[:3])
        if info:
            return info
    return '综合', 15, 30


def Number_or_0(v):
    """安全转 float，失败返回 0"""
    try:
        if v is None:
            return 0.0
        n = float(v)
        return n if not np.isnan(n) else 0.0
    except (TypeError, ValueError):
        return 0.0

# 统一 TTL - 从常量模块导入
from app.core.constants import (
    CACHE_TTL_FINANCIAL as TTL_FINANCIAL,
    CACHE_TTL_STOCK_LIST as TTL_STOCK_LIST,
    CACHE_TTL_CAPITAL_FLOW as TTL_CAPITAL_FLOW,
)

# 全局内存缓存（仅用于热点键加速 Redis 访问，进程级）
from collections import OrderedDict as _OrderedDict

_MAX_FIN_CACHE = 500
_financial_cache = _OrderedDict()
_CAPITAL_FLOW_CACHE: dict = _OrderedDict()
_STOCK_NAME_CACHE: _OrderedDict = _OrderedDict()
_MAX_NAME_CACHE = 3000  # A股共5000+，缓存3000覆盖热门股
_STOCK_NAME_TTL = 86400 * 7  # 7天（股票名称几乎不变）


def _get_lru(cache, key):
    """LRU 缓存获取：命中时移到末尾"""
    cached = cache.get(key)
    if not cached:
        return None
    # 命中：移到队尾（最近使用）
    cache.move_to_end(key)
    return cached


def _set_lru(cache, key, value, max_size):
    """LRU 缓存设置：超容量时淘汰最久未使用"""
    while len(cache) >= max_size:
        cache.popitem(last=False)
    cache[key] = value


def _get_financial_cache(stock_code):
    """进程内热点缓存 - 避免每次都走 Redis"""
    cached = _get_lru(_financial_cache, stock_code)
    if not cached:
        return None
    if time.time() - cached['timestamp'] < TTL_FINANCIAL:
        return cached['data']
    del _financial_cache[stock_code]
    return None


def _set_financial_cache(stock_code, data):
    _set_lru(_financial_cache, stock_code, {'data': data, 'timestamp': time.time()}, _MAX_FIN_CACHE)


def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        v = float(val)
        if np.isnan(v):
            return default
        return round(v, 2)
    except (ValueError, TypeError):
        return default


def _fetch_real_financial_raw(stock_code):
    """实际拉取财务数据（无缓存，仅供 SWR 和首次加载调用）"""
    result = {}

    def _fetch_tencent():
        try:
            tencent_data = TencentSource.get_quotes([stock_code])
            if stock_code in tencent_data:
                q = tencent_data[stock_code]
                return {
                    'pe_ttm': q.get('pe_ttm', 0),
                    'roe': q.get('roe', 0),
                    'mcap_yi': q.get('mcap_yi', 0),
                    'turnover_pct': q.get('turnover_pct', 0),
                }
        except Exception as e:
            logger.debug(f"Financial source 1 failed ({stock_code}): {e}")
        return {}

    def _fetch_em_push2():
        try:
            stock_info = EastMoneySource.get_stock_info(stock_code)
            if stock_info:
                total_mv = float(stock_info.get('f116', 0) or 0) / 1e8
                float_mv = float(stock_info.get('f117', 0) or 0) / 1e8
                data = {}
                if total_mv > 0:
                    data['总市值'] = round(total_mv, 2)
                if float_mv > 0:
                    data['流通市值'] = round(float_mv, 2)
                ts = float(stock_info.get('f50', 0) or 0)
                if ts > 0:
                    data['total_share'] = ts
                fs = float(stock_info.get('f51', 0) or 0)
                if fs > 0:
                    data['float_share'] = fs
                return data
        except Exception as e:
            logger.debug(f"Financial source 2 failed ({stock_code}): {e}")
        return {}

    def _fetch_em_datacenter():
        try:
            from app.core.data_sources import EastMoneyDataCenter
            fin_data = EastMoneyDataCenter.query(
                "RPT_F10_FINANCE_MAINFINADATA",
                filter_str=f'(SECURITY_CODE="{stock_code}")',
                page_size=5,
                sort_columns="REPORT_DATE",
                sort_types="-1"
            )
            if fin_data:
                latest = fin_data[0]
                data = {}
                gm = latest.get('XSMLL')
                if gm is not None and gm != '':
                    data['gross_margin'] = round(float(gm), 2)
                dr = latest.get('ZCFZL')
                if dr is not None and dr != '':
                    data['debt_ratio'] = round(float(dr), 2)
                rev = latest.get('TOTALOPERATEREVETZ')
                if rev is not None and rev != '':
                    data['revenue_yoy'] = round(float(rev), 2)
                profit = latest.get('PARENTNETPROFITTZ')
                if profit is not None and profit != '':
                    data['profit_yoy'] = round(float(profit), 2)
                eps = latest.get('EPSJB')
                if eps is not None and eps != '':
                    data['eps'] = round(float(eps), 4)
                nav = latest.get('BPS')
                if nav is not None and nav != '':
                    data['nav'] = round(float(nav), 4)
                roe = latest.get('ROEJQ')
                if roe is not None and roe != '':
                    data['roe'] = round(float(roe), 2)
                return data
        except Exception as e:
            logger.debug(f"Financial source 3 failed ({stock_code}): {e}")
        return {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_tencent = executor.submit(_fetch_tencent)
        f_push2 = executor.submit(_fetch_em_push2)
        f_dc = executor.submit(_fetch_em_datacenter)

        for future in as_completed([f_tencent, f_push2, f_dc]):
            try:
                part = future.result(timeout=15)
                result.update(part)
            except Exception as e:
                logger.debug(f"Financial fetch part failed: {e}")

    if not result.get('pb') and result.get('nav'):
        try:
            tencent_data2 = TencentSource.get_quotes([stock_code])
            if stock_code in tencent_data2:
                price2 = tencent_data2[stock_code].get('price', 0)
                if price2 > 0 and result['nav'] > 0:
                    result['pb'] = round(price2 / result['nav'], 2)
        except Exception:
            pass

    return result


def _fetch_real_financial(stock_code):
    """获取真实财务数据 - 多源并行 + Redis/内存缓存 + SWR

    三级缓存策略：
    1. 进程内 LRU 缓存（毫秒级）
    2. Redis/SQLite SWR 缓存（支持 stale 读取 + 后台刷新）
    3. 实时拉取（多源并行，超时兜底）
    """
    # 1. 检查进程内缓存
    cached = _get_financial_cache(stock_code)
    if cached:
        logger.debug(f"财务数据命中进程内缓存: {stock_code}")
        return cached

    # 2. 检查 Redis 缓存（新鲜数据）
    redis_data = cache_get(stock_code, NS_FINANCIAL)
    if redis_data:
        logger.debug(f"财务数据命中 Redis 缓存: {stock_code}")
        _set_financial_cache(stock_code, redis_data)
        return redis_data

    # 3. SWR 模式：尝试 stale 数据 + 后台刷新
    #    Redis 实现：stale key TTL 是主 key 的 2 倍
    swr_result = swr_cache(stock_code, NS_FINANCIAL,
                           lambda: _fetch_real_financial_raw(stock_code), TTL_FINANCIAL)
    if swr_result is not None:
        logger.debug(f"财务数据命中 SWR 缓存: {stock_code}")
        _set_financial_cache(stock_code, swr_result)
        return swr_result

    # 4. 完全无缓存：阻塞拉取（最后一次兜底）
    logger.debug(f"财务数据无缓存，阻塞拉取: {stock_code}")
    result = _fetch_real_financial_raw(stock_code)
    if result:
        _set_financial_cache(stock_code, result)
        cache_set(stock_code, result, ttl=TTL_FINANCIAL, namespace=NS_FINANCIAL)

    return result


def _get_all_stock_list():
    """获取全市场股票列表 - 进程内热点缓存 + Redis 兜底"""
    now = time.time()
    # 进程内热点缓存（避免频繁打 Redis）
    cached_list = _financial_cache.get('_all_stock_list')
    if cached_list and (now - cached_list['timestamp']) < TTL_STOCK_LIST:
        return cached_list['data']

    # Redis 缓存
    redis_data = cache_get("all", NS_STOCKLIST)
    if redis_data:
        _financial_cache['_all_stock_list'] = {'data': redis_data, 'timestamp': now}
        return redis_data

    try:
        raw = EastMoneySource.get_full_market()
        if raw:
            stocks = []
            for item in raw:
                code = str(item.get("f12", ""))
                name = item.get("f14", "")
                if code and len(code) == 6:
                    stocks.append({'code': code, 'name': name})
            _financial_cache['_all_stock_list'] = {'data': stocks, 'timestamp': now}
            cache_set("all", stocks, ttl=TTL_STOCK_LIST, namespace=NS_STOCKLIST)
            return stocks
    except Exception as e:
        logger.warning(f"获取全市场股票列表失败: {e}")

    return []


class StockService:
    """个股诊断服务 - 内部方法同步，对外提供 async/sync 双接口"""

    # K线短期缓存：避免同一只股票短时间内重复拉取（30秒TTL）
    _kline_cache: dict = {}
    _kline_cache_ttl: float = 30.0

    def _get_kline_df(self, stock_code: str, count: int = 120) -> pd.DataFrame:
        # 检查短期缓存（30秒内不重复拉取）
        cache_key = f"{stock_code}_{count}"
        cached = self._kline_cache.get(cache_key)
        if cached is not None:
            ts, df = cached
            if time.time() - ts < self._kline_cache_ttl:
                logger.debug(f"K线缓存命中: {stock_code}")
                return df.copy()

        # Retry logic for pytdx connection pool contention（3次重试，避免长时间阻塞）
        for attempt in range(3):
            try:
                bars = pytdx_data.get_kline(stock_code, period=4, count=count)
                if not bars:
                    continue
                df = pd.DataFrame(bars)
                df['close'] = pd.to_numeric(df['close'])
                df['open'] = pd.to_numeric(df['open'])
                df['high'] = pd.to_numeric(df['high'])
                df['low'] = pd.to_numeric(df['low'])
                df['volume'] = pd.to_numeric(df['volume'])
                self._kline_cache[cache_key] = (time.time(), df)
                return df
            except Exception as e:
                logger.debug(f"K线获取失败 (尝试{attempt+1}/3): {e}")
                if attempt < 2:
                    import time as _time
                    _time.sleep(0.3 * (attempt + 1))
        return pd.DataFrame()

    @staticmethod
    def _fetch_flow_history(stock_code: str) -> dict:
        """历史资金流 - 东财push2his"""
        return {'flow_3d': None, 'flow_5d': None, 'flow_10d': None}

    @staticmethod
    def _fetch_capital_flow(stock_code: str) -> dict:
        """获取个股资金流向（带缓存 + SWR）

        数据源：EastMoneySource.get_stock_capital_flow() 三级降级
        push2 → 腾讯内外盘 → pytdx成交明细

        三级缓存策略：
        1. 进程内 LRU 缓存（毫秒级）
        2. Redis/SQLite SWR 缓存（支持 stale 读取 + 后台刷新）
        3. 实时拉取（多源降级）
        """
        now = time.time()

        # 1. 检查进程内缓存
        cached = _get_lru(_CAPITAL_FLOW_CACHE, stock_code)
        if cached and (now - cached['timestamp']) < TTL_CAPITAL_FLOW:
            logger.debug(f"资金流命中进程内缓存: {stock_code}")
            return cached['data']

        # 2. 检查 Redis 缓存（新鲜数据）
        redis_data = cache_get(stock_code, NS_CAPITAL_FLOW)
        if redis_data:
            logger.debug(f"资金流命中 Redis 缓存: {stock_code}")
            _set_lru(_CAPITAL_FLOW_CACHE, stock_code, {'data': redis_data, 'timestamp': now}, _MAX_FIN_CACHE)
            return redis_data

        # 3. SWR 模式：尝试 stale 数据 + 后台刷新
        def _do_fetch_flow():
            try:
                from app.core.data_sources import EastMoneySource
                flow = EastMoneySource.get_stock_capital_flow(stock_code)
                if not flow:
                    return {}
                return {
                    'source': flow.get('source', '东方财富'),
                    'main_net': round(flow.get('main_net', 0) or 0, 2),
                    'big_buy': round(flow.get('big_buy', 0) or 0, 2),
                    'big_sell': round(flow.get('big_sell', 0) or 0, 2),
                    'mid_buy': round(flow.get('mid_buy', 0) or 0, 2),
                    'mid_sell': round(flow.get('mid_sell', 0) or 0, 2),
                    'small_buy': round(flow.get('small_buy', 0) or 0, 2),
                    'small_sell': round(flow.get('small_sell', 0) or 0, 2),
                    'flow_3d': flow.get('flow_3d'),
                    'flow_5d': flow.get('flow_5d'),
                    'flow_10d': flow.get('flow_10d'),
                }
            except Exception as e:
                logger.debug(f"资金流({stock_code})获取失败: {e}")
                return {}

        swr_result = swr_cache(stock_code, NS_CAPITAL_FLOW, _do_fetch_flow, TTL_CAPITAL_FLOW)
        if swr_result:
            logger.debug(f"资金流命中 SWR 缓存: {stock_code}")
            _set_lru(_CAPITAL_FLOW_CACHE, stock_code, {'data': swr_result, 'timestamp': now}, _MAX_FIN_CACHE)
            return swr_result

        # 4. 完全无缓存：阻塞拉取（最后一次兜底）
        logger.debug(f"资金流无缓存，阻塞拉取: {stock_code}")
        try:
            from app.core.data_sources import EastMoneySource
            flow = EastMoneySource.get_stock_capital_flow(stock_code)
            if not flow:
                return {}

            result = {
                'source': flow.get('source', '东方财富'),
                'main_net': round(flow.get('main_net', 0) or 0, 2),
                'big_buy': round(flow.get('big_buy', 0) or 0, 2),
                'big_sell': round(flow.get('big_sell', 0) or 0, 2),
                'mid_buy': round(flow.get('mid_buy', 0) or 0, 2),
                'mid_sell': round(flow.get('mid_sell', 0) or 0, 2),
                'small_buy': round(flow.get('small_buy', 0) or 0, 2),
                'small_sell': round(flow.get('small_sell', 0) or 0, 2),
                'flow_3d': flow.get('flow_3d'),
                'flow_5d': flow.get('flow_5d'),
                'flow_10d': flow.get('flow_10d'),
            }

            _set_lru(_CAPITAL_FLOW_CACHE, stock_code, {'data': result, 'timestamp': now}, _MAX_FIN_CACHE)
            cache_set(stock_code, result, ttl=TTL_CAPITAL_FLOW, namespace=NS_CAPITAL_FLOW)
            return result
        except Exception as e:
            logger.debug(f"资金流({stock_code})获取失败: {e}")
            return {}

    def _estimate_capital_flow_from_kline(self, kline_df: pd.DataFrame) -> dict | None:
        """资金流兜底方案：当东财API失败时返回None，不估算虚构数据。

        注意：K线数据无法推算真实的主力/大单/中单/小单流向，
        任何基于量价关系的"估算"都是虚构的，会误导用户决策。
        """
        return None

    def _calc_indicators(self, df: pd.DataFrame) -> dict:
        """计算技术指标"""
        if df.empty or len(df) < 5:
            return {}
        close = df['close']
        high = df['high']
        low = df['low']
        result = {}

        for p in [5, 10, 20, 60]:
            ma = close.rolling(p).mean()
            result[f'MA{p}'] = round(ma.iloc[-1], 2) if len(ma.dropna()) else None

        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9).mean()
        macd_bar = (dif - dea) * 2
        result['MACD_DIF'] = round(dif.iloc[-1], 4)
        result['MACD_DEA'] = round(dea.iloc[-1], 4)
        result['MACD_BAR'] = round(macd_bar.iloc[-1], 4)
        result['MACD_SIGNAL'] = '金叉买入' if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2] else \
                                '死叉卖出' if dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2] else \
                                '多头' if dif.iloc[-1] > dea.iloc[-1] else '空头'

        low_min = low.rolling(9).min()
        high_max = high.rolling(9).max()
        rsv = (close - low_min) / (high_max - low_min) * 100
        rsv = rsv.fillna(50)
        k = rsv.ewm(com=2).mean()
        d = k.ewm(com=2).mean()
        j = 3 * k - 2 * d
        result['KDJ_K'] = round(k.iloc[-1], 2)
        result['KDJ_D'] = round(d.iloc[-1], 2)
        result['KDJ_J'] = round(j.iloc[-1], 2)
        result['KDJ_SIGNAL'] = '超买' if j.iloc[-1] > 100 else '超卖' if j.iloc[-1] < 0 else '偏强' if k.iloc[-1] > d.iloc[-1] else '偏弱'

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        for period, name in [(6, 'RSI6'), (12, 'RSI12'), (24, 'RSI24')]:
            avg_gain = gain.rolling(period).mean()
            avg_loss = loss.rolling(period).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = 100 - 100 / (1 + rs)
            result[name] = round(rsi.iloc[-1], 2) if not np.isnan(rsi.iloc[-1]) else 50
        rsi6 = result.get('RSI6', 50)
        result['RSI_SIGNAL'] = '超买' if rsi6 > 80 else '超卖' if rsi6 < 20 else '偏强' if rsi6 > 60 else '偏弱' if rsi6 < 40 else '中性'

        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        result['BOLL_UP'] = round((ma20 + 2 * std20).iloc[-1], 2) if len(ma20.dropna()) else None
        result['BOLL_MID'] = round(ma20.iloc[-1], 2) if len(ma20.dropna()) else None
        result['BOLL_DN'] = round((ma20 - 2 * std20).iloc[-1], 2) if len(ma20.dropna()) else None
        if result['BOLL_UP'] and result['BOLL_DN']:
            boll_pos = (close.iloc[-1] - result['BOLL_DN']) / (result['BOLL_UP'] - result['BOLL_DN'])
            result['BOLL_SIGNAL'] = '突破上轨' if close.iloc[-1] > result['BOLL_UP'] else '跌破下轨' if close.iloc[-1] < result['BOLL_DN'] else '中轨上方' if boll_pos > 0.5 else '中轨下方'

        vol = df['volume']
        avg_vol5 = vol.rolling(5).mean()
        if avg_vol5.iloc[-1] > 0:
            result['VOL_RATIO'] = round(vol.iloc[-1] / avg_vol5.iloc[-1], 2)
            result['VOL_SIGNAL'] = '放量' if result['VOL_RATIO'] > 1.5 else '缩量' if result['VOL_RATIO'] < 0.7 else '温和'

        if len(close) >= 2:
            pct = (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100
            result['DAY_CHANGE'] = round(pct, 2)
            result['DAY_SIGNAL'] = '上涨' if pct > 0 else '下跌' if pct < 0 else '平盘'

        # ── 加权综合评分 ──
        # 明确权重：技术面 65%(趋势20+量能15+MACD10+KDJ10+RSI10+BOLL5) + 基本面 25% + 资金面 10%
        # 每个维度独立计算 0-100 分，加权平均得到总分
        # 量价配合细分：放量滞涨/缩量上涨背离/顶背离等关键形态纳入量能维度
        score_trend = 50.0
        score_volume = 50.0
        score_macd = 50.0
        score_kdj = 50.0
        score_rsi = 50.0
        score_boll = 50.0

        # 趋势 20 分（MA 多头排列=90, 短期多头=70, 短期空头=30, 空头排列=10）
        ma5, ma10, ma20, ma60 = result.get('MA5'), result.get('MA10'), result.get('MA20'), result.get('MA60')
        if ma5 and ma20 and ma60:
            if ma5 > ma20 > ma60:
                score_trend = 90
            elif ma5 < ma20 < ma60:
                score_trend = 10
            elif ma5 > ma20:
                score_trend = 70
            else:
                score_trend = 30
        result['_SCORE_TREND'] = score_trend

        # 量能 15 分（细分：放量滞涨/缩量上涨背离/温和放量+上涨/极度放量/平稳/缩量）
        vol_ratio = result.get('VOL_RATIO', 1)
        day_change = result.get('DAY_CHANGE', 0)
        if vol_ratio > 1.5 and day_change < 1:
            # 放量滞涨（量比>1.5 但涨幅<1%）：抛压沉重，扣分
            score_volume = 30
        elif vol_ratio < 0.7 and day_change > 1:
            # 缩量上涨（量比<0.7 但涨幅>1%）：背离，加分但提示风险
            score_volume = 70
        elif vol_ratio > 1.5 and day_change > 0:
            # 温和放量+上涨：量价配合良好
            score_volume = 85
        elif vol_ratio > 3:
            score_volume = 60  # 异常放量不一定是好事
        elif vol_ratio < 0.5:
            score_volume = 20
        elif vol_ratio < 0.7:
            score_volume = 35
        else:
            score_volume = 50
        result['_SCORE_VOLUME'] = score_volume

        # MACD 10 分（金叉=90, 多头=65, 死叉=10, 空头=35；柱状连续信号叠加 ±5）
        macd_bar = result.get('MACD_BAR', 0)
        # 判断 MACD 柱是否连续放大/缩小（需要至少 2 根）
        macd_bar_prev = None
        if len(close) >= 3 and macd_bar is not None:
            # 重算前一根 MACD_BAR
            try:
                ema12_series = close.ewm(span=12).mean()
                ema26_series = close.ewm(span=26).mean()
                dif_series = ema12_series - ema26_series
                dea_series = dif_series.ewm(span=9).mean()
                macd_bar_series = (dif_series - dea_series) * 2
                if len(macd_bar_series) >= 2:
                    macd_bar_prev = round(macd_bar_series.iloc[-2], 4)
            except Exception:
                pass

        if result.get('MACD_SIGNAL') == '金叉买入':
            score_macd = 90
        elif result.get('MACD_SIGNAL') == '死叉卖出':
            score_macd = 10
        elif result.get('MACD_SIGNAL') == '多头':
            score_macd = 65
        elif result.get('MACD_SIGNAL') == '空头':
            score_macd = 35

        # MACD 柱连续信号：红柱放大 +5，红柱缩小 -3，绿柱放大 -5，绿柱缩小 +3
        if macd_bar is not None and macd_bar_prev is not None:
            if macd_bar > 0 and macd_bar > macd_bar_prev:
                score_macd = min(100, score_macd + 5)  # 红柱放大
            elif macd_bar > 0 and macd_bar < macd_bar_prev:
                score_macd = max(0, score_macd - 3)  # 红柱缩小
            elif macd_bar < 0 and macd_bar < macd_bar_prev:
                score_macd = max(0, score_macd - 5)  # 绿柱放大
            elif macd_bar < 0 and macd_bar > macd_bar_prev:
                score_macd = min(100, score_macd + 3)  # 绿柱缩小
        result['_SCORE_MACD'] = score_macd

        # KDJ 10 分（极端值给大权重，超卖>超买）
        kdj_j = result.get('KDJ_J', 50)
        if kdj_j < 0:
            score_kdj = 90  # 极度超卖，强烈反弹预期
        elif kdj_j < 20:
            score_kdj = 80
        elif kdj_j > 100:
            score_kdj = 20  # 极度超买
        elif kdj_j > 80:
            score_kdj = 30
        elif kdj_j < 50:
            score_kdj = 60
        else:
            score_kdj = 50
        result['_SCORE_KDJ'] = score_kdj

        # RSI 10 分
        rsi6 = result.get('RSI6', 50)
        if rsi6 < 20:
            score_rsi = 85
        elif rsi6 > 80:
            score_rsi = 15
        elif rsi6 > 60:
            score_rsi = 65
        elif rsi6 < 40:
            score_rsi = 35
        result['_SCORE_RSI'] = score_rsi

        # BOLL 5 分（新增）：突破上轨=85, 中上区域=70, 中轨附近=50, 中下区域=30, 跌破下轨=15
        boll_signal = result.get('BOLL_SIGNAL', '')
        if boll_signal == '突破上轨':
            score_boll = 85
        elif boll_signal == '跌破下轨':
            score_boll = 15
        elif boll_signal == '中轨上方':
            score_boll = 70
        elif boll_signal == '中轨下方':
            score_boll = 30
        else:
            score_boll = 50
        result['_SCORE_BOLL'] = score_boll

        # 技术面综合（65% 权重；权重和=0.65，归一化系数=0.65）
        technical_score = (
            score_trend * 0.20 +
            score_volume * 0.15 +
            score_macd * 0.10 +
            score_kdj * 0.10 +
            score_rsi * 0.10 +
            score_boll * 0.05
        ) / 0.65  # 归一化到 0-100

        result['_TECHNICAL_SCORE'] = round(technical_score, 1)
        result['_FIN_SCORE_PENDING'] = True
        result['_FUND_SCORE_PENDING'] = True
        result['WEIGHTED_SCORE'] = round(technical_score, 1)

        return result

    def _calc_fundamental_score(self, indicators: dict, fin_display: dict, stock_code: str = '', stock_name: str = '') -> float:
        """基本面评分（0-100 分），与新加权体系对齐（25% 权重）

        优化点：
        1. PE 阈值按行业区分（银行 5-10 vs 科技 30-55），避免一刀切
        2. PE 负值（亏损股）扣分加重至 -25
        3. 新增经营现金流维度（防造假）— 由 fin_display.operating_cash_flow_ratio 提供
        4. 业绩同比基数效应：去年同期为负导致 +500% 失真时不加分
        """
        if not fin_display:
            return 50  # 无数据时给中性分
        score = 50.0  # 中性基准
        pe = fin_display.get('pe', 0)
        roe = fin_display.get('roe', 0)
        profit_yoy = fin_display.get('profit_yoy', 0)
        revenue_yoy = fin_display.get('revenue_yoy', 0)
        debt_ratio = fin_display.get('debt_ratio', 0)
        gross_margin = fin_display.get('gross_margin', 0)
        # 经营现金流净额/净利润（>0.8 视为健康，<0.3 视为风险）
        ocf_ratio = fin_display.get('operating_cash_flow_ratio', None)

        # PE 25 分（按行业阈值评分）
        industry_name, pe_low, pe_high = get_industry_info(stock_code, stock_name)
        if pe < 0:
            score -= 25  # 亏损股扣分加重
        elif pe < pe_low:
            score += 20  # 行业低估
        elif pe < pe_high:
            score += 10  # 行业合理
        elif pe < pe_high * 1.5:
            score -= 5   # 略偏贵
        else:
            score -= 15  # 严重高估

        # ROE 25 分：分级更细
        if roe > 20:
            score += 25
        elif roe > 15:
            score += 20
        elif roe > 10:
            score += 10
        elif roe > 5:
            score += 0
        elif roe > 0:
            score -= 10
        else:
            score -= 20

        # 业绩增速 15 分（同比基数效应过滤）
        # 若 profit_yoy > 100 但同期基数小，可能是低基数效应，降级加分
        if profit_yoy > 50 and revenue_yoy > 30:
            if profit_yoy > 200:
                score += 8  # 可能是低基数效应，加分减半
            else:
                score += 15
        elif profit_yoy > 20 and revenue_yoy > 15:
            score += 10
        elif profit_yoy > 0:
            score += 3
        elif profit_yoy > -15:
            score -= 8  # 0~-15% 持续走下坡也要扣分
        else:
            score -= 15

        # 负债率 10 分
        if debt_ratio > 0:
            if debt_ratio > 80:
                score -= 10
            elif debt_ratio > 60:
                score -= 4
            elif debt_ratio < 40:
                score += 6

        # 毛利率 10 分
        if gross_margin > 50:
            score += 10
        elif gross_margin > 30:
            score += 6
        elif gross_margin > 15:
            score += 3
        elif 0 < gross_margin < 10:
            score -= 4

        # 经营现金流质量 15 分（新增维度，防造假）
        if ocf_ratio is not None:
            if ocf_ratio > 1.0:
                score += 15  # 现金流充裕
            elif ocf_ratio > 0.8:
                score += 10
            elif ocf_ratio > 0.5:
                score += 5
            elif ocf_ratio > 0:
                score -= 5   # 现金流偏弱
            else:
                score -= 15  # 经营现金流为负，利润质量存疑

        return max(0, min(100, score))

    def _calc_capital_flow_score(self, capital_flow: dict) -> float:
        """资金面评分（0-100 分），与新加权体系对齐（10% 权重，提升自 5%）

        优化点：
        1. 利用大/中/小单结构化数据评估"机构建仓 vs 散户接盘"
           - 大单流入 + 小单流出 = 机构吸筹（加分）
           - 大单流出 + 小单流入 = 机构派发（扣分）
        2. 数据缺失兜底：返回 50 但附带 data_missing 标记（前端可识别）

        数据缺失策略：当 3/5/10 日累计资金流为 None 时，
        把多日累计维度权重转移到 main_net，避免区分度收窄。
        """
        if not capital_flow:
            return 50
        score = 50.0  # 中性基准
        main_net = capital_flow.get('main_net', 0) or 0
        flow_3d = capital_flow.get('flow_3d')
        flow_5d = capital_flow.get('flow_5d')
        flow_10d = capital_flow.get('flow_10d')

        # 大/中/小单结构（机构 vs 散户博弈）
        big_buy = Number_or_0(capital_flow.get('big_buy'))
        big_sell = Number_or_0(capital_flow.get('big_sell'))
        small_buy = Number_or_0(capital_flow.get('small_buy'))
        small_sell = Number_or_0(capital_flow.get('small_sell'))
        big_net = big_buy - big_sell
        small_net = small_buy - small_sell
        has_struct_data = (big_buy > 0 or big_sell > 0 or small_buy > 0 or small_sell > 0)

        history_available = any(v is not None for v in [flow_3d, flow_5d, flow_10d])
        flow_3d = flow_3d or 0
        flow_5d = flow_5d or 0
        flow_10d = flow_10d or 0

        if history_available:
            # 今日主力净流入（30 分）
            if main_net > 3:
                score += 25
            elif main_net > 1:
                score += 15
            elif main_net > 0.3:
                score += 6
            elif main_net < -3:
                score -= 25
            elif main_net < -1:
                score -= 15
            elif main_net < -0.3:
                score -= 6

            # 多日累计资金流（40 分）：3/5/10日方向一致
            if flow_3d > 0 and flow_5d > 0 and flow_10d > 0:
                score += 20
            elif flow_3d < 0 and flow_5d < 0 and flow_10d < 0:
                score -= 20
            elif flow_3d > 0 and flow_10d > 0:
                score += 8
            elif flow_3d < 0 and flow_10d < 0:
                score -= 8

            # 10日累计规模（10 分）
            if flow_10d > 5:
                score += 10
            elif flow_10d > 2:
                score += 5
            elif flow_10d < -5:
                score -= 10
            elif flow_10d < -2:
                score -= 5
        else:
            # 多日数据缺失：main_net 权重提升至覆盖全范围（40 分）
            if main_net > 3:
                score += 35
            elif main_net > 1:
                score += 22
            elif main_net > 0.3:
                score += 12
            elif main_net > 0:
                score += 6
            elif main_net < -3:
                score -= 35
            elif main_net < -1:
                score -= 22
            elif main_net < -0.3:
                score -= 12
            elif main_net < 0:
                score -= 6

        # 大/小单结构博弈（20 分，新增维度）
        # 机构建仓（大单流入+小单流出）vs 机构派发（大单流出+小单流入）
        if has_struct_data:
            if big_net > 0 and small_net < 0:
                # 机构吸筹：散户割肉离场，机构接盘
                score += 20
            elif big_net < 0 and small_net > 0:
                # 机构派发：散户追高接盘，机构出货
                score -= 20
            elif big_net > 0 and small_net > 0:
                # 双方一致看多
                score += 8
            elif big_net < 0 and small_net < 0:
                # 双方一致看空
                score -= 8

        return max(0, min(100, score))

    def _calc_risk_level(self, indicators: dict, fin_display: dict, weighted_score: float = None, stock_code: str = '', stock_name: str = '') -> dict:
        """风险等级 1-5 星（数字越大风险越高）
        评估维度（新增）：
          - MA20/MA60 乖离率（>15% 偏离度视为高风险）
          - 振幅（基于5日均振幅比，单日极端不扣分）
          - RSI/KDJ 极值（超买超卖越深风险越高）
          - PE 估值（>100 或负 PE 视为高风险）
          - 流动性风险（成交额 < 5000万）
          - ST/退市风险（股票名称含 ST/*）
          - 商誉占净资产比 > 30%
          - 应收账款激增 > 30%
          - 综合得分与风险等级冲突警示
        """
        score = 0
        reasons = []
        price_now = indicators.get('_PRICE_NOW_', 0) or 0

        # 1. MA 乖离率（权重最大）
        ma20 = indicators.get('MA20') or 0
        ma60 = indicators.get('MA60') or 0
        if ma20 > 0 and price_now > 0:
            bias20 = (price_now - ma20) / ma20 * 100
            if abs(bias20) > 20:
                score += 2
                reasons.append(f'偏离MA20 {bias20:+.1f}%，超买风险大')
            elif abs(bias20) > 12:
                score += 1
                reasons.append(f'偏离MA20 {bias20:+.1f}%')
        if ma60 > 0 and price_now > 0:
            bias60 = (price_now - ma60) / ma60 * 100
            if abs(bias60) > 30:
                score += 2
                reasons.append(f'偏离MA60 {bias60:+.1f}%，严重超买/超卖')
            elif abs(bias60) > 20:
                score += 1
                reasons.append(f'偏离MA60 {bias60:+.1f}%')

        # 2. 振幅（要求传入5日均振幅，单日极值不直接扣分）
        amp_now = indicators.get('_AMP_', 0) or 0
        amp_5d_avg = indicators.get('_AMP_5D_', 0) or 0
        if amp_5d_avg > 0:
            amp_ratio = amp_now / amp_5d_avg
            if amp_ratio > 2.5:
                score += 2
                reasons.append(f'今日振幅是5日均{amp_ratio:.1f}倍，异动')
            elif amp_ratio > 1.8:
                score += 1
                reasons.append(f'今日振幅是5日均{amp_ratio:.1f}倍')
        elif amp_now > 8:
            score += 2
            reasons.append(f'今日振幅{amp_now:.1f}%较大')

        # 3. KDJ/RSI 极值
        kdj_j = indicators.get('KDJ_J', 50)
        if kdj_j > 100:
            score += 1
            reasons.append('KDJ极度超买')
        elif kdj_j < 0:
            score += 1
            reasons.append('KDJ极度超卖')
        rsi6 = indicators.get('RSI6', 50)
        if rsi6 > 85 or rsi6 < 15:
            score += 1
            reasons.append(f'RSI6={rsi6} 极端区域')

        # 4. 估值风险
        pe = fin_display.get('pe', 0) if fin_display else 0
        if pe < 0:
            score += 2
            reasons.append(f'PE={pe} 亏损股')
        elif pe > 100:
            score += 2
            reasons.append(f'PE={pe} 估值严重偏高')
        elif pe > 50:
            score += 1
            reasons.append(f'PE={pe} 估值偏高')

        # 5. 流动性风险（成交额 < 5000万）
        rt_amount = indicators.get('_AMOUNT_', 0) or 0
        if 0 < rt_amount < 5000:
            score += 1
            reasons.append(f'成交额{rt_amount:.0f}万流动性不足')

        # 6. ST/退市风险
        if stock_name and ('ST' in stock_name or '*' in stock_name):
            score += 2
            reasons.append(f'{stock_name} ST/退市风险股')

        # 7. 商誉占净资产比 > 30%（需财务数据提供 goodwill_ratio）
        if fin_display:
            goodwill_ratio = fin_display.get('goodwill_ratio', 0) or 0
            if goodwill_ratio > 0.3:
                score += 1
                reasons.append(f'商誉占净资产{goodwill_ratio*100:.0f}%，减值风险')

        # 8. 应收账款激增（需财务数据提供 receivables_yoy）
        if fin_display:
            receivables_yoy = fin_display.get('receivables_yoy', 0) or 0
            if receivables_yoy > 30 and receivables_yoy > (fin_display.get('revenue_yoy', 0) or 0):
                score += 1
                reasons.append(f'应收账款同比+{receivables_yoy:.0f}%超营收增速')

        # 9. 综合得分与风险等级冲突警示（高分但高风险）
        score_conflict = False
        if weighted_score is not None and score >= 4 and weighted_score >= 70:
            score_conflict = True
            reasons.append(f'注意：综合评分{weighted_score}分偏高但存在多个风险因素，需谨慎')

        # 10. 风险评级映射：1-5星
        if score == 0:
            level, label = 1, '极低'
        elif score <= 2:
            level, label = 2, '低'
        elif score <= 4:
            level, label = 3, '中'
        elif score <= 6:
            level, label = 4, '中高'
        else:
            level, label = 5, '高'
        return {
            'level': level, 'label': label, 'score': score,
            'reasons': reasons, 'score_conflict': score_conflict,
        }

    def _calc_recent_performance(self, df: pd.DataFrame) -> dict:
        """1周/1月/3月/1年涨跌幅（基于 K 线）
        1周=5根日K, 1月=20根, 3月=60根, 1年=250根
        """
        if df.empty or len(df) < 2:
            return {}
        result = {}
        last = df['close'].iloc[-1]
        for label, n in [('1w', 5), ('1m', 20), ('3m', 60), ('1y', 250)]:
            if len(df) >= n:
                ref = df['close'].iloc[-n]
                if ref > 0:
                    result[f'PCT_{label.upper()}'] = round((last - ref) / ref * 100, 2)
        return result

    def _get_stock_name(self, stock_code: str) -> str:
        """获取股票中文名称（进程内LRU缓存7天）"""
        if stock_code in STOCK_NAMES:
            return STOCK_NAMES[stock_code]
        # 检查进程内缓存
        cached = _get_lru(_STOCK_NAME_CACHE, stock_code)
        if cached and (time.time() - cached['ts']) < _STOCK_NAME_TTL:
            return cached['name']
        try:
            import requests as req
            prefix = 'sh' if stock_code.startswith('6') else 'sz'
            r = req.get(f"https://qt.gtimg.cn/q={prefix}{stock_code}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            text = r.content.decode('gbk')
            for line in text.strip().split('\n'):
                if '=' not in line:
                    continue
                data_str = line.split('=', 1)[-1].strip('"').replace('\\', '')
                fields = data_str.split('~')
                if len(fields) > 7 and fields[1]:
                    name = fields[1]
                    _set_lru(_STOCK_NAME_CACHE, stock_code, {'name': name, 'ts': time.time()}, _MAX_NAME_CACHE)
                    return name
        except Exception as e:
            logger.warning(f"获取{stock_code}名称失败: {e}")
        return stock_code

    # ════════════════════════════════════════════════════
    # 内部同步方法（skill_orchestrator 直接调用）
    # ════════════════════════════════════════════════════

    def _get_technical_indicators_sync(self, stock_code: str, period: str = '近一年') -> dict:
        """技术指标分析 - 同步内部实现
        返回: 行情+技术指标+财务+资金流+加权评分+风险等级+近期表现

        并行优化：K线/实时行情/资金流/财务 4个独立数据源并发拉取。
        """
        name = self._get_stock_name(stock_code)

        # ── 并行拉取 4 个独立数据源 ──────────────────────
        kline_df, quotes_result, em_flow, fin = None, {}, {}, {}

        def _fetch_kline():
            period_kline_map = {"近一月": 60, "近3月": 120, "近三月": 120, "近半年": 200, "近一年": 250}
            count = period_kline_map.get(period, 250)
            return self._get_kline_df(stock_code, count)

        def _fetch_quotes():
            q = {}
            quotes = pytdx_data.get_realtime_quote([stock_code])
            if quotes:
                q = quotes[0]
            if not q or 'price' not in q:
                try:
                    from app.core.data_sources import TencentSource
                    tencent_data = TencentSource.get_quotes([stock_code])
                    if stock_code in tencent_data:
                        q = tencent_data[stock_code]
                except Exception as e:
                    logger.debug(f"Tencent quote fallback failed for {stock_code}: {e}")
            return q

        def _fetch_em_flow():
            return self._fetch_capital_flow(stock_code)

        def _fetch_financial():
            return _fetch_real_financial(stock_code)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_fetch_kline): 'kline',
                executor.submit(_fetch_quotes): 'quotes',
                executor.submit(_fetch_em_flow): 'em_flow',
                executor.submit(_fetch_financial): 'fin',
            }
            for future in as_completed(futures):
                tag = futures[future]
                try:
                    val = future.result(timeout=30)
                    if tag == 'kline':
                        kline_df = val
                    elif tag == 'quotes':
                        quotes_result = val
                    elif tag == 'em_flow':
                        em_flow = val
                    elif tag == 'fin':
                        fin = val
                except Exception as e:
                    logger.debug(f"并行数据拉取[{tag}]失败: {e}")

        # ── K线校验 + 技术指标计算 ──────────────────────
        if kline_df is None or kline_df.empty:
            return {'status': 'error', 'raw_output': f'无法获取{stock_code}的K线数据'}

        indicators = self._calc_indicators(kline_df)
        price = kline_df['close'].iloc[-1]
        date = kline_df['date'].iloc[-1] if 'date' in kline_df.columns else '--'

        # ── 解析实时行情 ────────────────────────────────
        q = quotes_result

        rt_price = q.get('price', price)
        rt_open = q.get('open', 0) or (kline_df['open'].iloc[-1] if not kline_df.empty else 0)
        rt_high = q.get('high', 0) or (kline_df['high'].iloc[-1] if not kline_df.empty else 0)
        rt_low = q.get('low', 0) or (kline_df['low'].iloc[-1] if not kline_df.empty else 0)
        rt_last_close = q.get('last_close', 0) or (kline_df['close'].iloc[-2] if len(kline_df) >= 2 else price)
        rt_change_pct = q.get('change_pct', 0)
        rt_volume = q.get('volume', 0)
        rt_amount = q.get('amount', 0)
        rt_bid1 = q.get('bid1', 0)
        rt_ask1 = q.get('ask1', 0)
        rt_turnover_pct = q.get('turnover_pct', 0) or 0

        amplitude = round((rt_high - rt_low) / rt_last_close * 100, 2) if rt_last_close > 0 else 0
        # 均价(元/股) = 成交额(元) / 成交量(手) / 100
        avg_price = round(rt_amount / rt_volume / 100, 2) if rt_volume > 0 else rt_price

        # ── 资金流合并（已在并行阶段拉取）──────────────────
        capital_flow = None
        if em_flow:
            capital_flow = em_flow
            if not capital_flow.get('source'):
                capital_flow['source'] = '东方财富'

        # 只有真实资金流数据才计算signal
        if capital_flow:
            main_net_val = capital_flow.get('main_net', 0) or 0
            capital_flow['signal'] = '主力流入' if main_net_val > 1 else '小幅流入' if main_net_val > 0 else '小幅流出' if main_net_val > -1 else '主力流出'

        lines = [
            "=" * 60,
            f"{name}({stock_code}) 综合诊断分析",
            f"数据日期: {date}  最新价: ¥{price:.2f}",
            "=" * 60, "",
        ]

        lines.append("【实时行情】")
        lines.append(f"  最新价: ¥{rt_price}  涨跌幅: {rt_change_pct:+.2f}%")
        lines.append(f"  今开: ¥{rt_open}  昨收: ¥{rt_last_close}")
        lines.append(f"  最高: ¥{rt_high}  最低: ¥{rt_low}")
        lines.append(f"  振幅: {amplitude:.2f}%  均价: ¥{avg_price}")
        lines.append(f"  成交量: {rt_volume}手  成交额: ¥{round(rt_amount/1e4, 0)}万")
        lines.append(f"  买卖盘: 买一¥{rt_bid1} 卖一¥{rt_ask1}")

        lines.append("")
        if capital_flow:
            lines.append(f"【资金流向】({capital_flow.get('source', '成交明细')})")
            main_net = capital_flow.get('main_net', 0) or 0
            lines.append(f"  主力净流入: {main_net:+.2f}亿")
            net_signal = capital_flow.get('signal', '--')
            lines.append(f"  信号: {net_signal}")
        else:
            logger.info(f"资金流为空 ({stock_code})，无可靠数据")
            lines.append("【资金流向】暂无数据")

        if len(kline_df) >= 5:
            vol_5 = kline_df['volume'].iloc[-5:].mean()
            vol_now = kline_df['volume'].iloc[-1]
            vol_trend = '放量' if vol_now > vol_5 * 1.3 else '缩量' if vol_now < vol_5 * 0.7 else '平稳'
            price_5 = kline_df['close'].iloc[-5:]
            pct_5d = round((price_5.iloc[-1] - price_5.iloc[0]) / price_5.iloc[0] * 100, 2)
            lines.append(f"  5日量能: {vol_trend}(量比{round(vol_now/vol_5, 2) if vol_5 > 0 else 0})")
            lines.append(f"  5日涨跌: {pct_5d:+.2f}%")

        lines.append("")
        lines.append("【均线系统】")
        for p in [5, 10, 20, 60]:
            v = indicators.get(f'MA{p}')
            if v:
                pos = '上方' if price > v else '下方'
                diff_pct = round((price - v) / v * 100, 2)
                lines.append(f"  MA{p}: ¥{v:.2f} (价格在{pos} {abs(diff_pct):.2f}%)")
        ma5 = indicators.get('MA5')
        ma20 = indicators.get('MA20')
        ma60 = indicators.get('MA60')
        if ma5 and ma20:
            if ma5 > ma20 > (ma60 or 0):
                trend = '多头排列(MA5>MA20>MA60)'
            elif ma5 < ma20 < (ma60 or float('inf')):
                trend = '空头排列(MA5<MA20<MA60)'
            elif ma5 > ma20:
                trend = '短期多头(MA5>MA20)'
            else:
                trend = '短期空头(MA5<MA20)'
            lines.append(f"  均线趋势: {trend}")

        lines.append("")
        lines.append("【MACD】")
        lines.append(f"  DIF: {indicators.get('MACD_DIF', '--')}  DEA: {indicators.get('MACD_DEA', '--')}")
        lines.append(f"  MACD柱: {indicators.get('MACD_BAR', '--')}")
        macd_signal = indicators.get('MACD_SIGNAL', '--')
        lines.append(f"  信号: {macd_signal}")
        dif_val = indicators.get('MACD_DIF', 0)
        dea_val = indicators.get('MACD_DEA', 0)
        if dif_val and dea_val:
            if dif_val > 0 and dea_val > 0:
                lines.append(f"  位置: 零轴上方(多头区域)")
            elif dif_val < 0 and dea_val < 0:
                lines.append(f"  位置: 零轴下方(空头区域)")
            else:
                lines.append(f"  位置: 零轴附近(转折区域)")

        lines.append("")
        lines.append("【KDJ】")
        k_val = indicators.get('KDJ_K', '--')
        d_val = indicators.get('KDJ_D', '--')
        j_val = indicators.get('KDJ_J', '--')
        lines.append(f"  K: {k_val}  D: {d_val}  J: {j_val}")
        lines.append(f"  信号: {indicators.get('KDJ_SIGNAL', '--')}")
        if isinstance(j_val, (int, float)):
            if j_val > 80:
                lines.append(f"  位置: 超买区域(J>80)，注意回调风险")
            elif j_val < 20:
                lines.append(f"  位置: 超卖区域(J<20)，关注反弹机会")
            elif j_val > 50:
                lines.append(f"  位置: 偏强区域(50<J<80)")
            else:
                lines.append(f"  位置: 偏弱区域(20<J<50)")

        lines.append("")
        lines.append("【RSI】")
        rsi6 = indicators.get('RSI6', 50)
        rsi12 = indicators.get('RSI12', 50)
        rsi24 = indicators.get('RSI24', 50)
        lines.append(f"  RSI6: {rsi6}  RSI12: {rsi12}  RSI24: {rsi24}")
        lines.append(f"  信号: {indicators.get('RSI_SIGNAL', '--')}")
        if rsi6 > 80:
            lines.append(f"  强度: 极度超买(RSI6>80)，短期见顶风险大")
        elif rsi6 > 60:
            lines.append(f"  强度: 偏强(RSI6>60)，多头占优")
        elif rsi6 > 40:
            lines.append(f"  强度: 中性(40<RSI6<60)")
        elif rsi6 > 20:
            lines.append(f"  强度: 偏弱(RSI6<40)，空头占优")
        else:
            lines.append(f"  强度: 极度超卖(RSI6<20)，短期超跌反弹概率大")

        lines.append("")
        lines.append("【布林带】")
        boll_up = indicators.get('BOLL_UP', '--')
        boll_mid = indicators.get('BOLL_MID', '--')
        boll_dn = indicators.get('BOLL_DN', '--')
        lines.append(f"  上轨: {boll_up}  中轨: {boll_mid}  下轨: {boll_dn}")
        lines.append(f"  信号: {indicators.get('BOLL_SIGNAL', '--')}")
        if isinstance(boll_up, (int, float)) and isinstance(boll_dn, (int, float)) and boll_mid:
            boll_width = round((boll_up - boll_dn) / boll_mid * 100, 2)
            lines.append(f"  带宽: {boll_width}% {'(收窄，关注变盘)' if boll_width < 10 else '(扩张)' if boll_width > 20 else ''}")

        lines.append("")
        lines.append("【量能分析】")
        vol_ratio = indicators.get('VOL_RATIO', '--')
        lines.append(f"  量比: {vol_ratio}")
        lines.append(f"  信号: {indicators.get('VOL_SIGNAL', '--')}")
        if isinstance(vol_ratio, (int, float)):
            if vol_ratio > 3:
                lines.append(f"  说明: 极度放量(量比>3)，关注异动")
            elif vol_ratio > 1.5:
                lines.append(f"  说明: 温和放量(量比>1.5)，活跃度提升")
            elif vol_ratio < 0.5:
                lines.append(f"  说明: 极度缩量(量比<0.5)，交投清淡")
            else:
                lines.append(f"  说明: 量能平稳")

        lines.append("")
        lines.append(f"【今日涨跌】{indicators.get('DAY_CHANGE', '--')}%  {indicators.get('DAY_SIGNAL', '')}")

        lines.append("")
        lines.append("【综合评估】")
        buy_count = sum(1 for sig in [indicators.get('MACD_SIGNAL'), indicators.get('KDJ_SIGNAL'), indicators.get('RSI_SIGNAL'), indicators.get('BOLL_SIGNAL')] if sig and any(kw in str(sig) for kw in ['买入', '金叉', '多头', '看涨', '超卖']))
        sell_count = sum(1 for sig in [indicators.get('MACD_SIGNAL'), indicators.get('KDJ_SIGNAL'), indicators.get('RSI_SIGNAL'), indicators.get('BOLL_SIGNAL')] if sig and any(kw in str(sig) for kw in ['卖出', '死叉', '空头', '看跌', '超买']))
        if buy_count > sell_count:
            overall = f'偏多({buy_count}买 vs {sell_count}卖)'
        elif sell_count > buy_count:
            overall = f'偏空({sell_count}卖 vs {buy_count}买)'
        else:
            overall = f'中性({buy_count}买 vs {sell_count}卖)'
        lines.append(f"  多空信号: {overall}")
        boll_up_v = indicators.get('BOLL_UP') or '--'
        boll_dn_v = indicators.get('BOLL_DN') or '--'
        lines.append(f"  关键位: 压力位¥{boll_up_v} 支撑位¥{boll_dn_v}")

        # fin 已在并行阶段拉取，直接使用（内部有缓存，重复调用也会秒返回）
        if fin:
            pe_ttm = fin.get('pe_ttm', 0)
            pb = fin.get('pb', 0)
            roe = fin.get('roe', 0)
            eps = fin.get('eps', 0)
            turnover_pct = fin.get('turnover_pct', 0)

            fin_display = {
                'pe': pe_ttm,
                'pb': pb,
                'roe': roe,
                'eps': eps,
                'gross_margin': fin.get('gross_margin', 0),
                'debt_ratio': fin.get('debt_ratio', 0),
                'revenue_yoy': fin.get('revenue_yoy', 0),
                'profit_yoy': fin.get('profit_yoy', 0),
                'turnover_pct': turnover_pct,
                'mcap_yi': fin.get('mcap_yi', 0),
            }
        else:
            fin_display = {}

        lines.append("")
        lines.append("【财务数据】(最新季报)")
        if fin_display:
            lines.append(f"  PE(动): {fin_display['pe']}  PB: {fin_display['pb']}  ROE: {fin_display['roe']}%")
            lines.append(f"  EPS: ¥{fin_display['eps']}  毛利率: {fin_display.get('gross_margin', '--')}%")
            lines.append(f"  资产负债率: {fin_display.get('debt_ratio', '--')}%")
            lines.append(f"  营收同比: {fin_display.get('revenue_yoy', '--'):+.1f}%  净利润同比: {fin_display.get('profit_yoy', '--'):+.1f}%")
        else:
            lines.append(f"  （暂无财务数据）")

        lines.append("")
        lines.append("=" * 60)

        # ── 加权总分：技术面 65% + 基本面 25% + 资金面 10% ──
        tech = indicators.get('_TECHNICAL_SCORE', 50) or 50
        if fin_display:
            fin_score = self._calc_fundamental_score(indicators, fin_display, stock_code, name)
        else:
            fin_score = 50  # 无数据时给中性分
        fund_score = self._calc_capital_flow_score(capital_flow)
        weighted = tech * 0.65 + fin_score * 0.25 + fund_score * 0.10
        indicators['WEIGHTED_SCORE'] = round(max(0, min(100, weighted)), 1)
        indicators['SCORE_BREAKDOWN'] = {
            'technical': round(tech, 1),
            'fundamental': round(fin_score, 1),
            'capital_flow': round(fund_score, 1),
            'weights': {'technical': 0.65, 'fundamental': 0.25, 'capital_flow': 0.10},
            'sub_scores': {
                'trend': indicators.get('_SCORE_TREND', 50),
                'volume': indicators.get('_SCORE_VOLUME', 50),
                'macd': indicators.get('_SCORE_MACD', 50),
                'kdj': indicators.get('_SCORE_KDJ', 50),
                'rsi': indicators.get('_SCORE_RSI', 50),
                'boll': indicators.get('_SCORE_BOLL', 50),
            },
            'industry': get_industry_info(stock_code, name)[0],
        }
        indicators.pop('_FIN_SCORE_PENDING', None)
        indicators.pop('_FUND_SCORE_PENDING', None)
        indicators.pop('_TECHNICAL_SCORE', None)
        indicators.pop('_SCORE_TREND', None)
        indicators.pop('_SCORE_VOLUME', None)
        indicators.pop('_SCORE_MACD', None)
        indicators.pop('_SCORE_KDJ', None)
        indicators.pop('_SCORE_RSI', None)
        indicators.pop('_SCORE_BOLL', None)

        # ── 风险等级 ──
        indicators['_AMP_'] = amplitude
        indicators['_PRICE_NOW_'] = price
        indicators['_AMOUNT_'] = round(rt_amount / 1e4, 0) if rt_amount else 0
        # 5日均振幅
        if len(kline_df) >= 6:
            amp_5d_values = []
            for i in range(-5, 0):
                h = kline_df['high'].iloc[i]
                l = kline_df['low'].iloc[i]
                c = kline_df['close'].iloc[i - 1] if i - 1 >= -len(kline_df) else kline_df['open'].iloc[i]
                if c > 0:
                    amp_5d_values.append((h - l) / c * 100)
            indicators['_AMP_5D_'] = round(sum(amp_5d_values) / len(amp_5d_values), 2) if amp_5d_values else 0
        else:
            indicators['_AMP_5D_'] = 0
        risk = self._calc_risk_level(
            indicators, fin_display,
            weighted_score=indicators.get('WEIGHTED_SCORE'),
            stock_code=stock_code, stock_name=name,
        )
        indicators.pop('_AMP_', None)
        indicators.pop('_PRICE_NOW_', None)
        indicators.pop('_AMOUNT_', None)
        indicators.pop('_AMP_5D_', None)

        # ── 近期表现 ──
        recent_perf = self._calc_recent_performance(kline_df)

        return {
            'status': 'success',
            'name': name,
            'raw_output': '\n'.join(lines),
            'realtime': {
                'price': rt_price, 'open': rt_open, 'high': rt_high, 'low': rt_low,
                'last_close': rt_last_close, 'change_pct': rt_change_pct,
                'volume': rt_volume, 'amount': round(rt_amount / 1e4, 0),
                'amplitude': amplitude, 'avg_price': avg_price,
                'turnover_rate': rt_turnover_pct, 'bid1': rt_bid1, 'ask1': rt_ask1,
            },
            'capital_flow': capital_flow,
            'financial': fin_display,
            'indicators': indicators,
            'weighted_score': indicators.get('WEIGHTED_SCORE'),
            'score_breakdown': indicators.get('SCORE_BREAKDOWN'),
            'score_level': get_score_level(indicators.get('WEIGHTED_SCORE')),
            'risk_level': risk,
            'recent_performance': recent_perf,
            'diagnose_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def _get_kline_patterns_sync(self, stock_code: str, periods: int = 200, direction: str = 'all') -> dict:
        """K线形态识别 - 同步内部实现"""
        name = STOCK_NAMES.get(stock_code, stock_code)
        # 拉够足量 K 线，覆盖至少一个完整波段周期
        df = self._get_kline_df(stock_code, min(periods, 250))
        if df.empty or len(df) < 5:
            return {'status': 'success', 'raw_output': f'{stock_code} K线数据不足', 'patterns': []}

        patterns = []
        for i in range(2, len(df)):
            o, h, l, c = df['open'].iloc[i], df['high'].iloc[i], df['low'].iloc[i], df['close'].iloc[i]
            o1, h1, l1, c1 = df['open'].iloc[i-1], df['high'].iloc[i-1], df['low'].iloc[i-1], df['close'].iloc[i-1]
            body = abs(c - o)
            range_hl = h - l
            upper = h - max(o, c)
            lower = min(o, c) - l
            date = str(df['date'].iloc[i])[:10] if 'date' in df.columns else f'bar_{i}'

            # ── 单K 反转形态 ──
            if range_hl > 0 and lower > body * 2 and upper < body * 0.3 and c > o:
                patterns.append(('bullish', '锤子线', date, 0.72))
            if range_hl > 0 and upper > body * 2 and lower < body * 0.3 and c < o:
                patterns.append(('bearish', '上吊线', date, 0.70))
            if range_hl > 0 and lower > body * 2 and upper < body * 0.3 and c < o:
                patterns.append(('bullish', '倒锤子线', date, 0.62))

            # ── 双K 组合 ──
            if c > o and c1 < o1 and c > o1 and o < c1:
                patterns.append(('bullish', '看涨吞没', date, 0.78))
            if c < o and c1 > o1 and c < o1 and o > c1:
                patterns.append(('bearish', '看跌吞没', date, 0.78))
            if range_hl > 0 and body < range_hl * 0.1 and abs(c - o) < range_hl * 0.1:
                patterns.append(('neutral', '十字星', date, 0.65))

            # ── 三K 组合 ──
            if i >= 2:
                o2, c2 = df['open'].iloc[i-2], df['close'].iloc[i-2]
                # 黄昏之星：三K先涨后星后跌
                if c2 > o2 and abs(c1 - o1) < (h1 - l1) * 0.2 and c < o and c < o2:
                    patterns.append(('bearish', '黄昏之星', date, 0.75))
                # 启明星：先跌后星后涨
                if c2 < o2 and abs(c1 - o1) < (h1 - l1) * 0.2 and c > o and c > o2:
                    patterns.append(('bullish', '启明星', date, 0.75))
                # 红三兵：连续三根阳线且收盘价递增
                if c2 > o2 and c1 > o1 and c > o and c > c1 > c2:
                    patterns.append(('bullish', '红三兵', date, 0.70))
                # 三只乌鸦：连续三根阴线且收盘价递减
                if c2 < o2 and c1 < o1 and c < o and c < c1 < c2:
                    patterns.append(('bearish', '三只乌鸦', date, 0.70))

        lines = [
            "=" * 60,
            f"{name}({stock_code}) K线形态识别 (近{len(df)}根K线)",
            "=" * 60,
        ]
        if patterns:
            for direction_type, name_p, date_p, conf in patterns[-10:]:
                dir_label = 'bullish' if direction_type == 'bullish' else 'bearish' if direction_type == 'bearish' else 'neutral'
                lines.append(f"{dir_label:<10} {name_p:<12} {date_p}  {conf}")
        else:
            lines.append("  暂未检测到明显形态")

        bull = sum(1 for d, _, _, _ in patterns if d == 'bullish')
        bear = sum(1 for d, _, _, _ in patterns if d == 'bearish')
        lines.append(f"\n检测到 {len(patterns)} 个形态: 看涨 {bull} 个, 看跌 {bear} 个")
        lines.append("=" * 60)

        # 结构化 patterns 列表（前端表格渲染依赖此字段）
        dir_label_map = {'bullish': '看涨', 'bearish': '看跌', 'neutral': '中性'}
        patterns_json = [
            {
                'direction': d,
                'direction_label': dir_label_map.get(d, d),
                'name': n,
                'date': dt,
                'confidence': conf,
            }
            for d, n, dt, conf in patterns
        ]

        return {
            'status': 'success',
            'raw_output': '\n'.join(lines),
            'patterns': patterns_json,
        }

    def _get_multi_factor_score_sync(self, stock_codes: list, factors=None, weight='equal_weight', top_n=10) -> dict:
        """多因子评分 - 同步内部实现"""
        lines = [
            "=" * 60,
            "多因子评分结果",
            "=" * 60,
            f"{'代码':<8}{'名称':<10}{'最新价':>8}{'涨跌幅':>8}{'量比':>6}{'PE':>8}{'PB':>8}{'换手率':>8}",
            "-" * 60,
        ]
        for code in stock_codes[:top_n]:
            name = STOCK_NAMES.get(code, code)
            quotes = pytdx_data.get_realtime_quote([code])
            if not quotes:
                lines.append(f"{code:<8}{name:<10}{'--':>8}{'--':>8}{'--':>6}{'--':>8}{'--':>8}{'--':>8}")
                continue
            q = quotes[0]
            price = q.get('price', 0)
            change = q.get('change_pct', 0)
            fin = _fetch_real_financial(code)
            eps = fin.get('eps', 0) if fin else 0
            nav = (fin.get('nav', 0) or fin.get('pb', 0)) if fin else 0
            pe = round(price / eps, 2) if eps and eps > 0 else 0
            pb = round(price / nav, 2) if nav and nav > 0 else 0
            lines.append(f"{code:<8}{name:<10}{price:>8.2f}{change:>+7.2f}%  --  {pe:>8.2f}{pb:>8.2f}{'--':>8}")
        lines.extend(["-" * 60, "数据来源: pytdx + akShare财务分析指标", "=" * 60])
        return {'status': 'success', 'raw_output': '\n'.join(lines)}

    def _search_stocks_sync(self, query: str) -> dict:
        """搜索股票 - 同步内部实现"""
        import re
        original_query = query.strip()
        if not original_query:
            return {'status': 'success', 'raw_output': '请输入搜索关键词'}

        digits_only = re.sub(r'[^0-9]', '', original_query)

        if len(digits_only) == 6:
            name = STOCK_NAMES.get(digits_only, '')
            quotes = pytdx_data.get_realtime_quote([digits_only])
            if quotes:
                q = quotes[0]
                return {'status': 'success', 'raw_output': f"{digits_only} {name or digits_only} ¥{q['price']:.2f} ({q['change_pct']:+.2f}%)"}
            else:
                return {'status': 'success', 'raw_output': f"{digits_only} {name or digits_only}"}

        all_stocks = _get_all_stock_list()

        def _normalize(s):
            """去空格 + 全角转半角，用于模糊匹配"""
            import unicodedata
            return unicodedata.normalize('NFKC', s).replace(' ', '')

        query_norm = _normalize(original_query)
        matched = [s for s in all_stocks if query_norm in _normalize(s['name'])][:10]

        if matched:
            lines = []
            for s in matched:
                cv, nv = s['code'], s['name']
                quotes = pytdx_data.get_realtime_quote([cv])
                price_info = ""
                if quotes:
                    q = quotes[0]
                    price_info = f" ¥{q['price']:.2f} ({q['change_pct']:+.2f}%)"
                lines.append(f"{cv} {nv}{price_info}")
            return {'status': 'success', 'raw_output': '\n'.join(lines)}

        for code, name in STOCK_NAMES.items():
            if query_norm in _normalize(name) or _normalize(name).startswith(query_norm):
                quotes = pytdx_data.get_realtime_quote([code])
                price_info = ""
                if quotes:
                    q = quotes[0]
                    price_info = f" ¥{q['price']:.2f} ({q['change_pct']:+.2f}%)"
                return {'status': 'success', 'raw_output': f"{code} {name}{price_info}"}

        if digits_only and len(digits_only) < 6:
            for code, name in STOCK_NAMES.items():
                if code.startswith(digits_only):
                    quotes = pytdx_data.get_realtime_quote([code])
                    price_info = ""
                    if quotes:
                        q = quotes[0]
                        price_info = f" ¥{q['price']:.2f} ({q['change_pct']:+.2f}%)"
                    return {'status': 'success', 'raw_output': f"{code} {name}{price_info}"}

        return {'status': 'success', 'raw_output': f'未找到匹配"{original_query}"的股票'}

    # ════════════════════════════════════════════════════
    # 对外 async 接口（FastAPI 路由调用，并行加速）
    # ════════════════════════════════════════════════════

    async def get_technical_indicators(self, stock_code: str, period: str = '近一年') -> dict:
        """获取技术指标分析 (async)"""
        return await asyncio.to_thread(self._get_technical_indicators_sync, stock_code, period)

    async def get_kline_patterns(self, stock_code: str, periods: int = 200, direction: str = 'all') -> dict:
        """获取K线形态识别 (async)"""
        return await asyncio.to_thread(self._get_kline_patterns_sync, stock_code, periods, direction)

    async def get_multi_factor_score(self, stock_codes: list, factors=None, weight='equal_weight', top_n=10) -> dict:
        """获取多因子评分 (async)"""
        return await asyncio.to_thread(self._get_multi_factor_score_sync, stock_codes, factors, weight, top_n)

    async def get_stock_diagnosis(self, stock_code: str, period: str = "近半年") -> dict:
        """获取个股综合诊断 (async, 预取+分发模式，每个数据源只拉一次)

        Args:
            stock_code: 6位股票代码
            period: 分析周期，支持"近一月"/"近三月"/"近半年"/"近一年"
        """
        import asyncio
        import time as _time

        # 根据period调整K线获取数量
        period_map = {
            "近一月": 21, "近3月": 63, "近三月": 63,
            "近半年": 126, "近一年": 250,
        }
        kline_count = period_map.get(period, 126)

        # 最大重试次数
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                return await self._fetch_diagnosis_data(stock_code, kline_count, period, attempt)
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"诊断数据拉取失败 (尝试{attempt+1}/{max_retries+1}): {e}，重试中...")
                    await asyncio.sleep(0.5 * (attempt + 1))  # 指数退避
                else:
                    logger.error(f"诊断数据拉取最终失败 ({stock_code}): {e}", exc_info=True)
                    # 返回部分数据而不是完全失败
                    return {
                        'stock_code': stock_code,
                        'analysis_time': str(datetime.now()),
                        'period': period,
                        'raw_output': f'诊断服务暂时不可用: {str(e)}',
                        'technical_indicators': {'status': 'error', 'raw_output': str(e)},
                        'kline_patterns': {'status': 'success', 'patterns': []},
                        'multi_factor': {'status': 'success', 'raw_output': ''},
                        'error': True,
                        'error_msg': str(e),
                    }

    async def _fetch_diagnosis_data(self, stock_code: str, kline_count: int, period: str, attempt: int) -> dict:
        """内部方法：拉取诊断数据"""
        import asyncio

        t0 = time.time()

        # ── 阶段1: 预取所有基础数据（5个源并行拉取）───────────────
        def _fetch_name():
            return self._get_stock_name(stock_code)

        def _fetch_kline():
            return self._get_kline_df(stock_code, kline_count)

        def _fetch_quotes():
            q = {}
            quotes = pytdx_data.get_realtime_quote([stock_code])
            if quotes:
                q = quotes[0]
            if not q or 'price' not in q:
                try:
                    from app.core.data_sources import TencentSource
                    tencent_data = TencentSource.get_quotes([stock_code])
                    if stock_code in tencent_data:
                        q = tencent_data[stock_code]
                except Exception as e:
                    logger.debug(f"Tencent quote fallback failed for {stock_code}: {e}")
            return q

        def _fetch_em_flow():
            return self._fetch_capital_flow(stock_code)

        def _fetch_financial():
            return _fetch_real_financial(stock_code)

        # 各数据源独立超时（秒）- 根据重试次数适当缩短
        timeout_factor = 1.0 if attempt == 0 else 0.7  # 重试时缩短超时
        _timeouts = {
            'name': int(5 * timeout_factor),
            'kline': int(15 * timeout_factor),
            'quotes': int(8 * timeout_factor),
            'em_flow': int(10 * timeout_factor),
            'fin': int(15 * timeout_factor),
        }

        # 5个数据源并行拉取（只拉一次）
        name = stock_code  # 兜底值，名称拉取失败时用代码
        kline_df, quotes_result, em_flow, fin = None, {}, {}, {}
        timings = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(_fetch_name): 'name',
                executor.submit(_fetch_kline): 'kline',
                executor.submit(_fetch_quotes): 'quotes',
                executor.submit(_fetch_em_flow): 'em_flow',
                executor.submit(_fetch_financial): 'fin',
            }
            for future in as_completed(futures):
                tag = futures[future]
                t_start = time.time()
                try:
                    val = future.result(timeout=_timeouts.get(tag, 30))
                    elapsed = round(time.time() - t_start, 2)
                    timings[tag] = f"{elapsed}s"
                    if tag == 'name':
                        name = val
                    elif tag == 'kline':
                        kline_df = val
                    elif tag == 'quotes':
                        quotes_result = val
                    elif tag == 'em_flow':
                        em_flow = val
                    elif tag == 'fin':
                        fin = val
                except Exception as e:
                    timings[tag] = f"FAIL({e})"
                    logger.debug(f"并行数据拉取[{tag}]失败 (尝试{attempt+1}): {e}")

        phase1_time = round(time.time() - t0, 2)
        logger.info(f"[DIAG] {stock_code} 阶段1-预取: {phase1_time}s | name={timings.get('name','?')} kline={timings.get('kline','?')} quotes={timings.get('quotes','?')} em_flow={timings.get('em_flow','?')} fin={timings.get('fin','?')}")

        # K线是必须的，如果获取失败则抛出异常
        if kline_df is None or (hasattr(kline_df, 'empty') and kline_df.empty):
            raise ValueError(f"无法获取{stock_code}的K线数据，请检查股票代码是否正确")

        # ── 阶段2: 用预取数据计算技术指标（不重复拉取）────────
        t2 = time.time()
        tech_result = self._build_tech_from_data(stock_code, name, kline_df, quotes_result, em_flow, fin)
        logger.info(f"[DIAG] {stock_code} 阶段2-技术指标: {round(time.time()-t2,2)}s")

        # ── 阶段3: K线形态识别（复用已获取的K线数据）───────────
        t3 = time.time()
        patterns_result = self._build_patterns_from_data(name, stock_code, kline_df)
        logger.info(f"[DIAG] {stock_code} 阶段3-K线形态: {round(time.time()-t3,2)}s")

        # ── 阶段4: 多因子评分（复用行情+财务数据）──────────────
        t4 = time.time()
        multi_result = self._build_multi_factor_from_data(stock_code, name, quotes_result, fin)
        logger.info(f"[DIAG] {stock_code} 阶段4-多因子: {round(time.time()-t4,2)}s | 总计: {round(time.time()-t0,2)}s")

        combined_raw = (
            tech_result.get('raw_output', '') + '\n\n' +
            patterns_result.get('raw_output', '') + '\n\n' +
            multi_result.get('raw_output', '')
        ).strip()

        return {
            'stock_code': stock_code,
            'analysis_time': str(datetime.now()),
            'period': period,
            'raw_output': combined_raw,
            'technical_indicators': tech_result,
            'kline_patterns': patterns_result,
            'multi_factor': multi_result,
        }

    def _build_tech_from_data(self, stock_code, name, kline_df, quotes_result, em_flow, fin):
        """用预取数据构建技术指标结果（复用 _get_technical_indicators_sync 的核心逻辑）

        必须计算：WEIGHTED_SCORE / SCORE_BREAKDOWN / 风险等级 / 近期表现
        否则前端综合诊断会显示"数据不足"。
        """
        if not isinstance(kline_df, pd.DataFrame) or kline_df.empty:
            return {'status': 'error', 'raw_output': f'无法获取{stock_code}的K线数据'}

        indicators = self._calc_indicators(kline_df)
        price = kline_df['close'].iloc[-1]
        date = kline_df['date'].iloc[-1] if 'date' in kline_df.columns else '--'

        q = quotes_result or {}
        # 实时行情兜底：所有字段都从 K 线最后一根兜底
        rt_price = q.get('price', 0) or price
        rt_open = q.get('open', 0) or kline_df['open'].iloc[-1]
        rt_high = q.get('high', 0) or kline_df['high'].iloc[-1]
        rt_low = q.get('low', 0) or kline_df['low'].iloc[-1]
        rt_last_close = q.get('last_close', 0) or (kline_df['close'].iloc[-2] if len(kline_df) >= 2 else price)
        rt_change_pct = q.get('change_pct', 0)
        rt_volume = q.get('volume', 0)
        rt_amount = q.get('amount', 0)
        rt_bid1 = q.get('bid1', 0)
        rt_ask1 = q.get('ask1', 0)
        rt_turnover_pct = q.get('turnover_pct', 0) or 0

        amplitude = round((rt_high - rt_low) / rt_last_close * 100, 2) if rt_last_close > 0 else 0
        # 均价(元/股) = 成交额(元) / 成交量(手) / 100
        avg_price = round(rt_amount / rt_volume / 100, 2) if rt_volume > 0 else rt_price

        capital_flow = None
        if em_flow:
            capital_flow = em_flow
            if not capital_flow.get('source'):
                capital_flow['source'] = '东方财富'

        if capital_flow:
            main_net_val = capital_flow.get('main_net', 0) or 0
            capital_flow['signal'] = '主力流入' if main_net_val > 1 else '小幅流入' if main_net_val > 0 else '小幅流出' if main_net_val > -1 else '主力流出'

        # ── 构建财务展示数据（与 _get_technical_indicators_sync 一致）──
        fin_display = {}
        if fin:
            fin_display = {
                'pe': fin.get('pe_ttm', 0),
                'pb': fin.get('pb', 0),
                'roe': fin.get('roe', 0),
                'eps': fin.get('eps', 0),
                'gross_margin': fin.get('gross_margin', 0),
                'debt_ratio': fin.get('debt_ratio', 0),
                'revenue_yoy': fin.get('revenue_yoy', 0),
                'profit_yoy': fin.get('profit_yoy', 0),
                'turnover_pct': rt_turnover_pct,
                'mcap_yi': fin.get('mcap_yi', 0),
            }

        # ── 加权总分：技术面 65% + 基本面 25% + 资金面 10% ──
        tech = indicators.get('_TECHNICAL_SCORE', 50) or 50
        fin_score = self._calc_fundamental_score(indicators, fin_display, stock_code, name) if fin_display else 50
        fund_score = self._calc_capital_flow_score(capital_flow)
        weighted = tech * 0.65 + fin_score * 0.25 + fund_score * 0.10
        indicators['WEIGHTED_SCORE'] = round(max(0, min(100, weighted)), 1)
        indicators['SCORE_BREAKDOWN'] = {
            'technical': round(tech, 1),
            'fundamental': round(fin_score, 1),
            'capital_flow': round(fund_score, 1),
            'weights': {'technical': 0.65, 'fundamental': 0.25, 'capital_flow': 0.10},
            'sub_scores': {
                'trend': indicators.get('_SCORE_TREND', 50),
                'volume': indicators.get('_SCORE_VOLUME', 50),
                'macd': indicators.get('_SCORE_MACD', 50),
                'kdj': indicators.get('_SCORE_KDJ', 50),
                'rsi': indicators.get('_SCORE_RSI', 50),
                'boll': indicators.get('_SCORE_BOLL', 50),
            },
            'industry': get_industry_info(stock_code, name)[0],
        }
        # 清理内部计算中间字段
        for k in ['_FIN_SCORE_PENDING', '_FUND_SCORE_PENDING', '_TECHNICAL_SCORE',
                  '_SCORE_TREND', '_SCORE_VOLUME', '_SCORE_MACD', '_SCORE_KDJ', '_SCORE_RSI', '_SCORE_BOLL']:
            indicators.pop(k, None)

        # ── 风险等级 ──
        indicators['_AMP_'] = amplitude
        indicators['_PRICE_NOW_'] = price
        indicators['_AMOUNT_'] = round(rt_amount / 1e4, 0) if rt_amount else 0
        if len(kline_df) >= 6:
            amp_5d_values = []
            for i in range(-5, 0):
                h = kline_df['high'].iloc[i]
                l = kline_df['low'].iloc[i]
                c = kline_df['close'].iloc[i - 1] if i - 1 >= -len(kline_df) else kline_df['open'].iloc[i]
                if c > 0:
                    amp_5d_values.append((h - l) / c * 100)
            indicators['_AMP_5D_'] = round(sum(amp_5d_values) / len(amp_5d_values), 2) if amp_5d_values else 0
        else:
            indicators['_AMP_5D_'] = 0
        risk = self._calc_risk_level(
            indicators, fin_display,
            weighted_score=indicators.get('WEIGHTED_SCORE'),
            stock_code=stock_code, stock_name=name,
        )
        for k in ['_AMP_', '_PRICE_NOW_', '_AMOUNT_', '_AMP_5D_']:
            indicators.pop(k, None)

        # ── 近期表现 ──
        recent_perf = self._calc_recent_performance(kline_df)

        realtime = {
            'price': rt_price, 'open': rt_open, 'high': rt_high, 'low': rt_low,
            'last_close': rt_last_close, 'change_pct': rt_change_pct,
            'volume': rt_volume, 'amount': round(rt_amount / 1e4, 0),
            'bid1': rt_bid1, 'ask1': rt_ask1,
            'turnover_rate': rt_turnover_pct, 'amplitude': amplitude, 'avg_price': avg_price,
        }

        return {
            'status': 'success',
            'name': name,
            'raw_output': f'{name}({stock_code}) 技术指标分析完成',
            'indicators': indicators,
            'realtime': realtime,
            'financial': fin_display,
            'capital_flow': capital_flow,
            'weighted_score': indicators.get('WEIGHTED_SCORE'),
            'score_breakdown': indicators.get('SCORE_BREAKDOWN'),
            'score_level': get_score_level(indicators.get('WEIGHTED_SCORE')),
            'risk_level': risk,
            'recent_performance': recent_perf,
            'diagnose_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def _build_patterns_from_data(self, name, stock_code, kline_df):
        """用预取K线数据构建形态识别结果"""
        if not isinstance(kline_df, pd.DataFrame) or kline_df.empty or len(kline_df) < 5:
            return {'status': 'success', 'raw_output': f'{stock_code} K线数据不足', 'patterns': []}

        patterns = []
        for i in range(2, len(kline_df)):
            o, h, l, c = kline_df['open'].iloc[i], kline_df['high'].iloc[i], kline_df['low'].iloc[i], kline_df['close'].iloc[i]
            o1, h1, l1, c1 = kline_df['open'].iloc[i-1], kline_df['high'].iloc[i-1], kline_df['low'].iloc[i-1], kline_df['close'].iloc[i-1]
            body = abs(c - o)
            range_hl = h - l
            upper = h - max(o, c)
            lower = min(o, c) - l
            date = str(kline_df['date'].iloc[i])[:10] if 'date' in kline_df.columns else f'bar_{i}'

            if range_hl > 0 and lower > body * 2 and upper < body * 0.3 and c > o:
                patterns.append(('bullish', '锤子线', date, 0.72))
            if range_hl > 0 and upper > body * 2 and lower < body * 0.3 and c < o:
                patterns.append(('bearish', '上吊线', date, 0.70))
            if range_hl > 0 and lower > body * 2 and upper < body * 0.3 and c < o:
                patterns.append(('bullish', '倒锤子线', date, 0.62))

            if c > o and c1 < o1 and c > o1 and o < c1:
                patterns.append(('bullish', '看涨吞没', date, 0.78))
            if c < o and c1 > o1 and c < o1 and o > c1:
                patterns.append(('bearish', '看跌吞没', date, 0.78))
            if range_hl > 0 and body < range_hl * 0.1 and abs(c - o) < range_hl * 0.1:
                patterns.append(('neutral', '十字星', date, 0.65))

            if i >= 2:
                o2, c2 = kline_df['open'].iloc[i-2], kline_df['close'].iloc[i-2]
                if c2 > o2 and abs(c1 - o1) < (h1 - l1) * 0.2 and c < o and c < o2:
                    patterns.append(('bearish', '黄昏之星', date, 0.75))
                if c2 < o2 and abs(c1 - o1) < (h1 - l1) * 0.2 and c > o and c > o2:
                    patterns.append(('bullish', '启明星', date, 0.75))
                if c2 > o2 and c1 > o1 and c > o and c > c1 > c2:
                    patterns.append(('bullish', '红三兵', date, 0.70))
                if c2 < o2 and c1 < o1 and c < o and c < c1 < c2:
                    patterns.append(('bearish', '三只乌鸦', date, 0.70))

        lines = [
            "=" * 60,
            f"{name}({stock_code}) K线形态识别 (近{len(kline_df)}根K线)",
            "=" * 60,
        ]
        if patterns:
            for direction_type, name_p, date_p, conf in patterns[-10:]:
                dir_label = 'bullish' if direction_type == 'bullish' else 'bearish' if direction_type == 'bearish' else 'neutral'
                lines.append(f"{dir_label:<10} {name_p:<12} {date_p}  {conf}")
        else:
            lines.append("  暂未检测到明显形态")

        bull = sum(1 for d, _, _, _ in patterns if d == 'bullish')
        bear = sum(1 for d, _, _, _ in patterns if d == 'bearish')
        lines.append(f"\n检测到 {len(patterns)} 个形态: 看涨 {bull} 个, 看跌 {bear} 个")
        lines.append("=" * 60)

        dir_label_map = {'bullish': '看涨', 'bearish': '看跌', 'neutral': '中性'}
        patterns_json = [
            {
                'direction': d,
                'direction_label': dir_label_map.get(d, d),
                'name': n,
                'date': dt,
                'confidence': conf,
            }
            for d, n, dt, conf in patterns
        ]

        return {
            'status': 'success',
            'raw_output': '\n'.join(lines),
            'patterns': patterns_json,
        }

    def _build_multi_factor_from_data(self, stock_code, name, quotes_result, fin):
        """用预取数据构建多因子评分结果"""
        lines = [
            "=" * 60,
            "多因子评分结果",
            "=" * 60,
            f"{'代码':<8}{'名称':<10}{'最新价':>8}{'涨跌幅':>8}{'量比':>6}{'PE':>8}{'PB':>8}{'换手率':>8}",
            "-" * 60,
        ]

        q = quotes_result
        if not q or 'price' not in q:
            lines.append(f"{stock_code:<8}{name:<10}{'--':>8}{'--':>8}{'--':>6}{'--':>8}{'--':>8}{'--':>8}")
        else:
            price = q.get('price', 0)
            change = q.get('change_pct', 0)
            eps = fin.get('eps', 0) if fin else 0
            nav = (fin.get('nav', 0) or fin.get('pb', 0)) if fin else 0
            pe = round(price / eps, 2) if eps and eps > 0 else 0
            pb = round(price / nav, 2) if nav and nav > 0 else 0
            lines.append(f"{stock_code:<8}{name:<10}{price:>8.2f}{change:>+7.2f}%  --  {pe:>8.2f}{pb:>8.2f}{'--':>8}")

        lines.extend(["-" * 60, "数据来源: pytdx + akShare财务分析指标", "=" * 60])
        return {'status': 'success', 'raw_output': '\n'.join(lines)}

    async def search_stocks(self, query: str) -> dict:
        """搜索股票 (async)"""
        return await asyncio.to_thread(self._search_stocks_sync, query)

