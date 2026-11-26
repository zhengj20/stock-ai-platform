"""市场看板服务 — 多源混合架构: 东方财富直连(核心) + 同花顺/腾讯(广度与互补)

缓存策略：所有跨请求缓存统一委托 app.core.cache，自动走 Redis/内存回退。

性能优化要点（v2）：
1. 直调东方财富 push2 API，替换慢速 akshare 包装，单次获取全市场 5000+ 股票
2. asyncio 并发拉取独立数据源（指数/涨跌统/涨跌停/资金流），总延迟从 sum 降至 max
3. 涨跌停数据从 push2 一并获取，消除乐咕乐股+akshare 串行开销
4. _get_last_trade_date 结果缓存 1h，避免每次调 stock_zt_pool_em 验证
5. 涨跌停数据复用 breadth 结果中的 limit_up/limit_down，消除重复计算
"""
from datetime import datetime, timedelta
import asyncio
import json
import logging
import concurrent.futures
import re
import time
import threading
from collections import OrderedDict
from typing import Optional

import httpx
import pandas as pd
import aiohttp
# akshare 已替换为直连API，不再使用

from app.core.pytdx_source import pytdx_data
from app.core.cache import cache_get, cache_set, swr_cache, NS_MARKET
from app.core.data_utils import is_limit_up, is_limit_down

# 新增：直连数据源（替代 akshare）
from app.core.data_sources import (
    EastMoneySource, EastMoneyDataCenter, EastMoneyZTPool,
    TencentSource, THSNorthboundSource, THSHotSource, THSCapitalFlowSource,
    THSLimitUpPoolSource, get_last_trade_date,
)

logger = logging.getLogger(__name__)

# 缓存 TTL - 从统一常量导入
from app.core.constants import (
    CACHE_TTL_BREADTH as TTL_BREADTH,
    CACHE_TTL_SECTOR_QUOTES as TTL_SECTOR_QUOTES,
    CACHE_TTL_MARKET_FLOW as TTL_MARKET_FLOW,
    CACHE_TTL_AK_CONCEPTS as TTL_AK_CONCEPTS,
    CACHE_TTL_TRADE_DATE as TTL_TRADE_DATE,
)

from app.core.trading_calendar import is_trading_hours

# ═══════════════════════════════════════════════════════════════════
# 东方财富 push2 API 常量
# ═══════════════════════════════════════════════════════════════════

_EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.eastmoney.com/',
}

# 全市场行情：获取涨跌幅/成交额/主力净流入
_EM_SPOT_FIELDS = (
    'f2,f3,f4,f5,f6,f7,f8,f10,f12,f14,f15,f16,f17,f18,f20,f21,'
    'f62,f66,f69,f72,f75,f78,f81,f84,f87,f100'
)
_EM_SPOT_FS = (
    'm:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,'
    'm:0+t:7,m:1+t:3,m:1+t:10,m:0+t:80+m:1+t:3'
)

# 涨跌停池参数
_EM_ZTFS = 'm:0+t:6+f:!2,m:0+t:13+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2'
_EM_DTFS = 'm:0+t:6+f:!2,m:0+t:13+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2'

def _get_last_trade_date() -> str:
    """获取最近一个交易日（YYYYMMDD），结果缓存 1h，使用腾讯财经验证。"""
    today = datetime.now()
    weekday = today.weekday()

    # 周末直接跳过腾讯验证（腾讯返回的是上周五收盘价，会误判）
    if weekday >= 5:
        days_back = 1 if weekday == 5 else 2
        date_str = (today - timedelta(days=days_back)).strftime('%Y%m%d')
        cache_set('last_trade_date', date_str, TTL_TRADE_DATE, NS_MARKET)
        logger.info(f"周末休市，最近交易日: {date_str}")
        return date_str

    cached = cache_get('last_trade_date', NS_MARKET)
    if cached:
        return cached

    # 方案1：腾讯财经验证（拉取上证指数，有数据说明是交易日）
    try:
        quotes = TencentSource.get_quotes(['000001'])
        if '000001' in quotes:
            data = quotes['000001']
            price = data.get('price', 0)
            if price and float(price) > 0:
                today_str = today.strftime('%Y%m%d')
                cache_set('last_trade_date', today_str, TTL_TRADE_DATE, NS_MARKET)
                logger.info(f"腾讯财经确认今日为交易日: {today_str}")
                return today_str
    except Exception as e:
        logger.warning(f"腾讯财经交易日历验证失败: {e}")

    # 方案2：datacenter 涨停池验证（push2ex）
    for i in range(0, 20):
        candidate = today - timedelta(days=i)
        if candidate.weekday() >= 5:
            continue
        date_str = candidate.strftime('%Y%m%d')
        try:
            pool = EastMoneyZTPool.get_zt_pool(date_str)
            if len(pool) > 0:
                cache_set('last_trade_date', date_str, TTL_TRADE_DATE, NS_MARKET)
                logger.info(f"datacenter验证最近交易日: {date_str}")
                return date_str
        except Exception:
            continue

    # 最终兜底：返回上周五
    days_back = 2 if weekday == 5 else 3 if weekday == 6 else 1
    date_str = (today - timedelta(days=days_back)).strftime('%Y%m%d')
    cache_set('last_trade_date', date_str, TTL_TRADE_DATE, NS_MARKET)
    return date_str

def _format_display_date(date_str: str) -> str:
    """将 YYYYMMDD 格式转换为 YYYY-MM-DD 显示格式"""
    try:
        dt = datetime.strptime(str(date_str), '%Y%m%d')
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return str(date_str)[:4] + '-' + str(date_str)[4:6] + '-' + str(date_str)[6:]

# ── 进程内缓存（仅用于不可 JSON 序列化的 DataFrame 数据）────
# 用 OrderedDict 实现简易 LRU：超过 MAX_PROCESS_CACHE 容量时淘汰最久未访问的 key
MAX_PROCESS_CACHE = 16
_process_cache: "OrderedDict[str, tuple]" = OrderedDict()
_process_cache_lock = threading.Lock()

def _cache_store(key: str, data, now: datetime, ttl: int):
    if isinstance(data, pd.DataFrame):
        with _process_cache_lock:
            _process_cache[key] = (data, now)
            while len(_process_cache) > MAX_PROCESS_CACHE:
                _process_cache.popitem(last=False)
    else:
        # 写入时间戳供_cache_fetch验证TTL
        to_cache = {**data, '_cached_at': now.isoformat()} if isinstance(data, dict) else data
        cache_set(key, to_cache, ttl, NS_MARKET)

def _cache_fetch(key: str, ttl: int) -> tuple:
    """获取缓存数据，严格检查TTL（Redis不自动删过期key时兜底）"""
    # 1. 检查进程内缓存
    with _process_cache_lock:
        if key in _process_cache:
            data, ts = _process_cache.get(key, (None, None))
            if data is not None and ts is not None and (datetime.now() - ts) < timedelta(seconds=ttl):
                _process_cache.move_to_end(key)
                return data, True
    # 2. 检查Redis缓存（手动验证时间戳，防止Redis未及时淘汰）
    raw = cache_get(key, NS_MARKET)
    if raw is not None:
        if isinstance(raw, dict) and '_cached_at' in raw:
            age = (datetime.now() - datetime.fromisoformat(raw['_cached_at'])).total_seconds()
            if age < ttl:
                return raw, True
            return None, False  # 过期了
        return raw, True  # 无时间戳，兼容旧数据
    return None, False

# ═══════════════════════════════════════════════════════════════════
# 东方财富 push2 API 统一请求
# ═══════════════════════════════════════════════════════════════════

def _em_clist_get(
    fs: str,
    fields: str,
    pn: int = 1,
    pz: int = 5000,
    fid: str = 'f3',
    po: str = '1',
    timeout: float = 15,
) -> list:
    """东财 push2 clist 统一请求（已禁用，返回空列表）。

    注意：push2.eastmoney.com 接口已长期不可用（ConnectionError），
    此函数保留代码但直接返回空，避免浪费请求时间。
    如将来东财恢复，取消下面注释即可。
    """
    # === 以下为原始 push2 代码（已禁用）===
    # from app.core.data_sources import em_get
    # url = 'https://push2.eastmoney.com/api/qt/clist/get'
    # all_rows = []
    # page = 1
    # max_pages = 80
    # try:
    #     while page <= max_pages:
    #         params = {
    #             'pn': str(page), 'pz': str(pz), 'po': po, 'np': '1',
    #             'fltt': '2', 'invt': '2',
    #             'fid': fid, 'fs': fs, 'fields': fields,
    #         }
    #         r = em_get(url, params=params, headers={'Referer': 'https://quote.eastmoney.com/'}, timeout=timeout)
    #         data = r.json().get('data') or {}
    #         diff = data.get('diff', [])
    #         if not diff:
    #             break
    #         all_rows.extend(diff)
    #         total = data.get('total', 0)
    #         if len(all_rows) >= total or len(diff) < 100:
    #             break
    #         page += 1
    #     return all_rows
    # except Exception as e:
    #     logger.warning(f"东财 clist 请求失败 ({fs}): {e}")
    #     return all_rows or []
    return []

# ═══════════════════════════════════════════════════════════════════
# AkShare板块列表缓存
# ═══════════════════════════════════════════════════════════════════

def _get_cached_boards(sector_type='concept'):
    cache_key = f'ths_{sector_type}s'
    cached, hit = _cache_fetch(cache_key, TTL_AK_CONCEPTS)
    if hit:
        return cached
    try:
        trade_date = _get_last_trade_date()
        date_str = datetime.strptime(trade_date, '%Y%m%d').strftime('%Y-%m-%d')
        # 交易时间用'即时'，非交易时间用最近交易日日期
        symbol = '即时' if is_trading_hours() else date_str

        # 使用东财 push2 板块接口（替代 akshare）
        if sector_type == 'industry':
            boards_data = EastMoneySource.get_industry_boards(page_size=100)
        else:
            boards_data = EastMoneySource.get_concept_boards(page_size=500)
        
        # 转换为 DataFrame 格式保持兼容
        df = pd.DataFrame(boards_data) if boards_data else pd.DataFrame()
        now = datetime.now()
        _cache_store(cache_key, df, now, TTL_AK_CONCEPTS)
        logger.info(f"同花顺{sector_type}板块数据已缓存，共{len(df)}个板块")
        return df
    except Exception as e:
        logger.warning(f"同花顺{sector_type}板块数据获取失败: {e}")
        return None

# ═══════════════════════════════════════════════════════════════════
# 全市场主力资金流向（东方财富直连）
# ═══════════════════════════════════════════════════════════════════

def _fetch_market_flow(force_refresh=False) -> dict:
    """获取全市场主力资金流向（东方财富公开接口，免费无配额限制）。

    主力 = 超大单 + 大单，接口直接给出各类别净额。
    缓存策略：交易时段5分钟，盘后24小时。
    """
    ttl = TTL_MARKET_FLOW if is_trading_hours() else 86400  # 盘后24小时
    if not force_refresh:
        cached, hit = _cache_fetch('market_flow', ttl)
        if hit and isinstance(cached, dict) and cached.get('net_inflow_billion') is not None:
            return {k: v for k, v in cached.items() if k != '_cached_at'}

    try:
        resp = httpx.get(
            "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
            params={
                "lmt": "0", "klt": "101",
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                "ut": "b2884a393a59ad64002292a3e90d46a5",
                "secid": "1.000001", "secid2": "0.399001",
            },
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"},
            timeout=15,
        )
        klines = (resp.json().get("data") or {}).get("klines") or []
        if not klines:
            logger.warning("东财大盘资金流返回空数据")
            return {}

        # 字段顺序：日期, 主力净流入, 小单, 中单, 大单, 超大单（单位：元）
        parts = klines[-1].split(",")
        if len(parts) < 6:
            logger.warning(f"东财大盘资金流字段异常: {parts}")
            return {}

        try:
            net_yuan, small_yuan, mid_yuan, large_yuan, super_yuan = (float(x) for x in parts[1:6])
        except ValueError:
            logger.warning(f"东财大盘资金流数值解析失败: {parts}")
            return {}

        net_billion = round(net_yuan / 1e8, 1)
        result_data = {
            'net_inflow_billion': net_billion,
            'inflow_billion': round(net_yuan / 1e8, 1) if net_yuan > 0 else 0,
            'outflow_billion': round(abs(net_yuan) / 1e8, 1) if net_yuan < 0 else 0,
            'super_large_net': round(super_yuan / 1e8, 1),
            'large_net': round(large_yuan / 1e8, 1),
            'mid_net': round(mid_yuan / 1e8, 1),
            'small_net': round(small_yuan / 1e8, 1),
            'source': 'eastmoney'
        }

        logger.info(f"东财大盘资金流({parts[0]}, 主力=超大单+大单): 净流入={result_data['net_inflow_billion']}亿, 超大单={result_data['super_large_net']}亿, 大单={result_data['large_net']}亿")
        _cache_store('market_flow', result_data, datetime.now(), ttl)
        return result_data

    except Exception as e:
        logger.error(f"东财大盘资金流查询异常: {e}")
        return {}

# ═══════════════════════════════════════════════════════════════════
# AkShare封装 — 广度数据（板块列表/全量行情）
# ═══════════════════════════════════════════════════════════════════

def _code_to_tencent(code: str) -> str:
    if code.startswith('6'):
        return f'sh{code}'
    elif code.startswith(('8', '4', '9')):
        return f'bj{code}'
    else:
        return f'sz{code}'

def parse_tencent_line(line: str) -> Optional[dict]:
    if '~' not in line:
        return None
    p = line.split('~')
    if len(p) < 53:
        return None
    try:
        code = p[2]
        name = p[1].strip()
        price = float(p[3])
        last_close = float(p[4])
        change_pct = float(p[32]) if len(p) > 32 else 0.0
        volume = int(p[6]) if p[6] else 0
        amount_wan = float(p[37]) if len(p) > 37 and p[37] else 0
        limit_up_price = float(p[47]) if len(p) > 47 and p[47] else 0.0
        limit_down_price = float(p[48]) if len(p) > 48 and p[48] else 0.0

        return {
            'code': code, 'name': name,
            'price': price, 'last_close': last_close,
            'change_pct': round(change_pct, 2),
            'volume': volume, 'amount_billion': round(amount_wan / 1e4, 2),
            'limit_up_price': limit_up_price,
            'limit_down_price': limit_down_price,
        }
    except (ValueError, IndexError):
        return None

def fetch_tencent_quotes(codes: list, batch_size: int = 80) -> list:
    all_quotes = []
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        tencent_codes = [_code_to_tencent(c) for c in batch]
        try:
            resp = httpx.get(f"http://qt.gtimg.cn/q={','.join(tencent_codes)}",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            for line in resp.text.strip().split('\n'):
                q = parse_tencent_line(line)
                if q:
                    all_quotes.append(q)
        except Exception:
            continue
    return all_quotes

def _get_all_a_stock_codes() -> list:
    try:
        # 使用东财 push2 全市场数据（替代 akshare）
        market_data = EastMoneySource.get_full_market()
        if market_data:
            codes = [str(row.get('f12', '')) for row in market_data]
            return [c for c in codes if len(c) == 6 and c[0] in ('0', '3', '6', '9')]
    except Exception as e:
        logger.warning(f"获取A股列表失败: {e}")
    return []

# ═══════════════════════════════════════════════════════════════════
# 优化1: 直调东方财富 push2 API 获取全市场涨跌统计
# 原来用 akshare.stock_zh_a_spot_em() 慢且不稳定，
# 现在直调 push2.eastmoney.com，单次请求获取全量 5000+ 股票数据
# ═══════════════════════════════════════════════════════════════════

def _fetch_em_spot_breadth(include_capital_flow: bool = False) -> Optional[dict]:
    """一次性拉取全市场数据，同时计算涨跌统计/涨跌停/资金流。

    主方案：腾讯全市场数据（有缓存时<1秒，无缓存~5秒）。
    注意：东财 push2 clist 接口已长期不可用，相关代码已注释保留。
    """
    up = down = flat = 0
    total_amount_yuan = 0.0
    limit_up = limit_down = 0

    # === 以下为原 push2 clist 代码（已禁用，保留备恢复）===
    # from app.core.data_sources_clean import _EM_SESSION, _EM_HEADERS
    # url = 'https://push2.eastmoney.com/api/qt/clist/get'
    # total_inflow_yuan = 0.0
    # total_outflow_yuan = 0.0
    # fetched_total = 0
    # try:
    #     page = 1
    #     max_pages = 80
    #     while page <= max_pages:
    #         params = {
    #             'pn': str(page), 'pz': '5000', 'po': '1', 'np': '1',
    #             'fltt': '2', 'invt': '2',
    #             'fid': 'f3', 'fs': _EM_SPOT_FS, 'fields': _EM_SPOT_FIELDS,
    #         }
    #         headers = dict(_EM_HEADERS)
    #         headers['Referer'] = 'https://quote.eastmoney.com/'
    #         r = _EM_SESSION.get(url, params=params, headers=headers, timeout=5)
    #         data = r.json().get('data') or {}
    #         diff = data.get('diff', [])
    #         total_count = data.get('total', 0)
    #         if not diff:
    #             break
    #         for row in diff:
    #             try:
    #                 f3_raw = row.get('f3', 0) or 0
    #                 f3 = 0.0 if isinstance(f3_raw, str) and f3_raw == '-' else float(f3_raw)
    #                 f2 = float(row.get('f2', 0) or 0)
    #                 f10 = float(row.get('f10', 0) or 0)
    #                 if f2 > 0:
    #                     if f3 > 0: up += 1
    #                     elif f3 < 0: down += 1
    #                     else: flat += 1
    #                 total_amount_yuan += f10
    #                 lup_raw = row.get('f78', 0) or 0
    #                 ldn_raw = row.get('f81', 0) or 0
    #                 lup = float(lup_raw) if lup_raw != '-' else 0.0
    #                 ldn = float(ldn_raw) if ldn_raw != '-' else 0.0
    #                 if lup > 0 and abs(f2 - lup) / lup < 0.005:
    #                     limit_up += 1
    #                 elif ldn > 0 and abs(f2 - ldn) / ldn < 0.005:
    #                     limit_down += 1
    #                 main_flow = float(row.get('f62', 0) or 0)
    #                 if main_flow > 0: total_inflow_yuan += main_flow
    #                 else: total_outflow_yuan += abs(main_flow)
    #             except (ValueError, TypeError):
    #                 continue
    #         fetched_total += len(diff)
    #         if fetched_total >= total_count or len(diff) < 100:
    #             break
    #         page += 1
    #         time.sleep(0.5)
    #     if fetched_total > 500:
    #         return _build_breadth_result(up, down, flat, total_amount_yuan, limit_up, limit_down,
    #                                       total_inflow_yuan, total_outflow_yuan, 'eastmoney', include_capital_flow)
    # except Exception as e:
    #     logger.debug(f"push2 clist失败: {e}")

    # === 腾讯全市场数据（主方案）===
    try:
        from app.core.data_sources_clean import TencentSource
        full_market = TencentSource.get_full_market(allow_stale=True)
        if not full_market:
            return _fetch_tencent_breadth(include_capital_flow)

        up = down = flat = 0
        limit_up = limit_down = 0
        total_amount_yuan = 0.0

        for row in full_market:
            try:
                f3 = float(row.get('f3', 0) or 0)
                f2 = float(row.get('f2', 0) or 0)
                f10 = float(row.get('f10', 0) or 0)

                if f2 > 0:
                    if f3 > 0: up += 1
                    elif f3 < 0: down += 1
                    else: flat += 1

                total_amount_yuan += f10

                code = row.get('f12', '')
                name = row.get('f14', '')
                lup = float(row.get('f78', 0) or 0)
                ldn = float(row.get('f81', 0) or 0)
                if is_limit_up(f2, lup, code, name):
                    limit_up += 1
                elif is_limit_down(f2, ldn, code, name):
                    limit_down += 1

            except (ValueError, TypeError):
                continue

        if up + down + flat > 0:
            logger.info(f"腾讯全市场({len(full_market)}条): 涨{up}/跌{down}/平{flat}, "
                        f"涨停{limit_up}/跌停{limit_down}")
            # 腾讯数据无资金流，尝试从同花顺获取
            ths_flow = _fetch_ths_market_flow() if include_capital_flow else {}
            inflow = ths_flow.get('inflow_billion', 0)
            outflow = ths_flow.get('outflow_billion', 0)
            return _build_breadth_result(up, down, flat, total_amount_yuan, limit_up, limit_down,
                                          inflow * 1e8 if inflow else 0,
                                          outflow * 1e8 if outflow else 0,
                                          'tencent_ths_flow', include_capital_flow)

    except Exception as e:
        logger.warning(f"腾讯全市场也失败: {e}")

    return None


def _build_breadth_result(up, down, flat, total_amount_yuan, limit_up, limit_down,
                          total_inflow_yuan, total_outflow_yuan, source, include_capital_flow):
    """构建 breadth 结果 dict"""
    total = up + down + flat
    inflow_billion = round(total_inflow_yuan / 1e8, 2)
    outflow_billion = round(total_outflow_yuan / 1e8, 2)
    net_billion = round(inflow_billion - outflow_billion, 2)

    has_money_flow = source in ('eastmoney', 'tencent_ths_flow') and abs(net_billion) > 0.01

    result = {
        'up': up, 'down': down, 'flat': flat, 'total': total,
        'total_amount_billion': round(total_amount_yuan / 1e8, 0),
        'limit_up': limit_up, 'limit_down': limit_down,
        'money_flow': {
            'net_inflow_billion': net_billion if has_money_flow else 0,
            'inflow_billion': inflow_billion if has_money_flow else 0,
            'outflow_billion': outflow_billion if has_money_flow else 0,
            'source': source if has_money_flow else 'none',
        },
        'source': source,
    }

    if include_capital_flow:
        try:
            from app.core.data_sources_clean import THSCapitalFlowSource
            capital_flow = THSCapitalFlowSource.get_top_capital_flows()
            if capital_flow:
                result['capital_flow_breakdown'] = capital_flow
                if not has_money_flow:
                    net_yi = capital_flow.get('main_net_inflow_yi', 0) or 0
                    total_in_yi = capital_flow.get('total_inflow_yi', 0) or 0
                    total_out_yi = capital_flow.get('total_outflow_yi', 0) or 0
                    if total_in_yi == 0 and total_out_yi == 0:
                        total_in_yi = max(net_yi, 0)
                        total_out_yi = abs(min(net_yi, 0))
                    result['money_flow'] = {
                        'net_inflow_billion': round(net_yi, 2),
                        'inflow_billion': round(total_in_yi, 2),
                        'outflow_billion': round(total_out_yi, 2),
                        'source': capital_flow.get('source', 'ths_hyzjl'),
                    }
        except Exception as e:
            logger.debug(f"同花顺资金流获取失败: {e}")

    logger.info(f"全市场广度({source}): 涨{up}/跌{down}/平{flat}(共{total}), "
                f"涨停{limit_up}/跌停{limit_down}, 成交额{round(total_amount_yuan/1e8,0)}亿")
    return result


def _fetch_tencent_breadth(include_capital_flow: bool = False) -> Optional[dict]:
    """腾讯财经逐只查询全市场（~5秒，无资金流字段）。

    每批80只，约17批完成。不封IP，数据准确。
    """
    all_codes = _get_all_a_stock_codes()
    if not all_codes:
        return None

    up = down = flat = limit_up = limit_down = 0
    total_amount_yuan = 0.0

    for i in range(0, len(all_codes), 80):
        batch = [_code_to_tencent(c) for c in all_codes[i:i+80]]
        try:
            resp = httpx.get(f"http://qt.gtimg.cn/q={','.join(batch)}",
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            for line in resp.text.strip().split('\n'):
                if '~' not in line or '=' not in line:
                    continue
                p = line.split('~')
                if len(p) < 53:
                    continue

                try:
                    price = float(p[3])
                    last_close = float(p[4])
                    change_pct = float(p[32]) if p[32] else 0.0
                    amount_wan = float(p[37]) if p[37] else 0.0
                    code = p[2] if len(p) > 2 else ''
                    name = p[1].strip() if len(p) > 1 else ''
                    lup = float(p[47]) if p[47] else 0.0
                    ldn = float(p[48]) if p[48] else 0.0

                    if price <= 0 or last_close <= 0:
                        continue

                    # 涨跌统计
                    if change_pct > 0: up += 1
                    elif change_pct < 0: down += 1
                    else: flat += 1

                    total_amount_yuan += amount_wan * 10000  # 万→元

                    # 涨跌停判断（严格口径）
                    if is_limit_up(price, lup, code, name):
                        limit_up += 1
                    elif is_limit_down(price, ldn, code, name):
                        limit_down += 1

                except (ValueError, IndexError):
                    continue
        except Exception:
            continue

    if up + down + flat == 0:
        return None

    logger.info(f"腾讯全市场: 涨{up}/跌{down}/平{flat}, 涨停{limit_up}/跌停{limit_down}")
    return _build_breadth_result(up, down, flat, total_amount_yuan, limit_up, limit_down,
                                  0, 0, 'tencent', include_capital_flow)

def _fetch_breadth_tencent_fallback() -> dict:
    """腾讯接口兜底：批量获取全市场涨跌统计（优化版，3并发）"""
    all_codes = _get_all_a_stock_codes()
    if not all_codes:
        all_codes = (
            [f'{i:06d}' for i in range(1, 5000)] +
            [f'{i:06d}' for i in range(300000, 302000)] +
            [f'{i:06d}' for i in range(600000, 602000)]
        )

    def fetch_batch(code_batch):
        up = down = flat = 0
        total_amt = 0.0
        limit_up = limit_down = 0
        tc = [_code_to_tencent(c) for c in code_batch]
        for i in range(0, len(tc), 80):
            batch = tc[i:i+80]
            try:
                resp = httpx.get(f"http://qt.gtimg.cn/q={','.join(batch)}",
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                for line in resp.text.strip().split('\n'):
                    if '~' not in line:
                        continue
                    p = line.split('~')
                    if len(p) < 53:
                        continue
                    try:
                        price = float(p[3])
                        last_close = float(p[4])
                        if price == 0 or last_close == 0:
                            continue
                        change_pct = float(p[32])
                        if change_pct > 0:
                            up += 1
                        elif change_pct < 0:
                            down += 1
                        else:
                            flat += 1

                        # 使用腾讯接口返回的涨跌停价精确判断（严格口径）
                        code = p[2] if len(p) > 2 else ''
                        name = p[1].strip() if len(p) > 1 else ''
                        limit_up_price = float(p[47]) if p[47] else 0.0
                        limit_down_price = float(p[48]) if p[48] else 0.0
                        if is_limit_up(price, limit_up_price, code, name):
                            limit_up += 1
                        elif is_limit_down(price, limit_down_price, code, name):
                            limit_down += 1

                        amount_wan = float(p[37]) if len(p) > 37 and p[37] else 0
                        total_amt += amount_wan
                    except ValueError:
                        continue
            except Exception:
                continue
        return up, down, flat, total_amt, limit_up, limit_down

    all_codes = list(set(all_codes))
    batches = [all_codes[i:i+400] for i in range(0, len(all_codes), 400)]

    # 优化：从 5 workers 提升到 8 workers，提升并发度
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_batch, b) for b in batches]
        total_up = total_down = total_flat = 0
        total_amount_wan = 0.0
        total_limit_up = total_limit_down = 0
        for f in concurrent.futures.as_completed(futures):
            try:
                u, d, fl, amt, lu, ld = f.result(timeout=120)
                total_up += u
                total_down += d
                total_flat += fl
                total_amount_wan += amt
                total_limit_up += lu
                total_limit_down += ld
            except Exception:
                continue

    return {
        'up': total_up, 'down': total_down, 'flat': total_flat,
        'total': total_up + total_down + total_flat,
        'total_amount_billion': round(total_amount_wan / 1e4, 0),
        'limit_up': total_limit_up, 'limit_down': total_limit_down,
        'source': 'tencent',
    }

def _fetch_breadth_fast(include_capital_flow: bool = False) -> dict:
    """获取全市场涨跌统计 + 成交额 + 涨跌停。

    push2 成功 → 返回真实数据；push2 失败 → 返回空 dict，由上层用板块样本估算。
    不再走腾讯全量兜底（太慢）。

    Args:
        include_capital_flow: 是否包含同花顺资金流拆分（约30s，默认不包含）
    """
    result = _fetch_em_spot_breadth(include_capital_flow)
    if result:
        logger.info(f"东方财富全市场广度数据: 涨{result['up']}/跌{result['down']}")
        return result

    logger.warning("东方财富push2不可用，返回空由上层估算")
    return {}

# ═══════════════════════════════════════════════════════════════════
# 优化2: 直调东方财富获取涨跌停数据（替代乐咕乐股+akshare 串行）
# ═══════════════════════════════════════════════════════════════════

def _fetch_em_limit_up_down(trade_date: str) -> dict:
    """使用东财 push2ex 四池快速获取涨跌停。

    ZTPool = 仍封板涨停股，DTPool = 跌停股（tc字段有准确数量）。
    不单独拉取全市场数据——breadth 已包含涨跌停统计，此处只做快速补充。
    """
    try:
        from app.core.data_sources import EastMoneyZTPool

        zt_pool = EastMoneyZTPool.get_zt_pool(trade_date)
        limit_up = len(zt_pool or [])

        dt_count = EastMoneyZTPool.get_dt_count(trade_date)
        dt_pool = EastMoneyZTPool.get_dt_pool(trade_date)
        limit_down = dt_count if dt_count > 0 else len(dt_pool or [])

        logger.info(f"东财四池涨跌停: 涨停{limit_up}家, 跌停{limit_down}家")
        return {'limit_up': limit_up, 'limit_down': limit_down, 'source': 'em_ztpool'}
    except Exception as e:
        logger.warning(f"东财涨跌停获取失败: {e}")
        return {}

# ═══════════════════════════════════════════════════════════════════
# 全市场主力资金流向：优先东方财富直连，兜底同花顺行业资金流合计
# ═══════════════════════════════════════════════════════════════════

def _fetch_ths_market_flow(force_refresh=False) -> dict:
    """使用同花顺行业资金流合计计算全市场主力资金流向（兜底方案）。

    东财 push2 不可用，改用同花顺行业资金流（hyzjl）合计。
    行业资金流无重复计算，数值接近全市场实际资金流。

    返回: {net_inflow_billion, inflow_billion, outflow_billion, signal, source, metric}
    """
    try:
        from app.core.data_sources import THSCapitalFlowSource

        flow_data = THSCapitalFlowSource.get_top_capital_flows(force_refresh=force_refresh)
        if not flow_data:
            return {}

        net_billion = round(flow_data.get('main_net_inflow_yi', 0), 2)
        sample_size = flow_data.get('sample_size', 0)

        total_in = flow_data.get('total_inflow_yi', 0) or 0
        total_out = flow_data.get('total_outflow_yi', 0) or 0
        if total_in == 0 and total_out == 0:
            total_in = max(net_billion, 0)
            total_out = abs(min(net_billion, 0))

        logger.info(f"同花顺行业资金流合计: 净额={net_billion:.1f}亿 (行业数={sample_size})")

        return {
            'net_inflow_billion': net_billion,
            'inflow_billion': round(total_in, 2),
            'outflow_billion': round(total_out, 2),
            'signal': '--',
            'source': 'ths_hyzjl',
            'metric': flow_data.get('metric', '全市场净额(行业资金流合计)'),
            'sample_size': sample_size,
        }
    except Exception as e:
        logger.warning(f"同花顺行业资金流合计获取失败: {e}")
        return {}

import threading as _threading_mod
_MODULE_SEMAPHORE = _threading_mod.Semaphore(3)

# ═══════════════════════════════════════════════════════════════════
# 兼容旧逻辑的硬编码板块
# ═══════════════════════════════════════════════════════════════════

_LEGACY_SECTORS = {
    '银行': ['601398', '601166', '600036', '601288', '600919', '000001'],
    '券商': ['601211', '600030', '601688', '600837', '601066', '002736'],
    '白酒': ['600519', '000858', '000568', '002304', '000596', '600809'],
    '光伏': ['601012', '002129', '300750', '600438', '002506', '300274'],
    '半导体': ['688981', '688008', '002371', '603986', '600584', '603501'],
    '医药': ['600276', '300760', '000661', '603259', '600196', '300122'],
    '房地产': ['600048', '000002', '001979', '600383', '600066'],
    '汽车': ['601633', '000625', '600104', '002475', '601238', '600741'],
    '煤炭': ['601088', '601898', '600997', '600547', '000983', '600123'],
    '电力': ['600900', '600011', '600027', '600025', '600795', '600995'],
    '计算机': ['603019', '002410', '688187', '300033', '600588', '002230'],
    '通信': ['600050', '000063', '603160', '688003', '600487', '002465'],
}

# ═══════════════════════════════════════════════════════════════════
# 缓存访问函数
# ═══════════════════════════════════════════════════════════════════

def get_cached_breadth(include_capital_flow: bool = False) -> dict:
    """获取全市场涨跌统计（带缓存）。

    Args:
        include_capital_flow: 是否包含同花顺资金流拆分（约30s，默认不包含）
    """
    cache_key = 'breadth_cf' if include_capital_flow else 'breadth'
    cached, hit = _cache_fetch(cache_key, TTL_BREADTH)
    if hit and (cached.get('total', 0) > 0):
        return cached

    # 尝试获取breadth数据

    result = _fetch_breadth_fast(include_capital_flow)
    if not result or result.get('total', 0) == 0:
        sq = get_cached_sector_quotes()
        up = sum(1 for q in sq.values() if q['change_pct'] > 0)
        down = sum(1 for q in sq.values() if q['change_pct'] < 0)
        flat = len(sq) - up - down
        result = {
            'up': up, 'down': down, 'flat': flat,
            'total': up + down + flat,
            'total_amount_billion': round(sum(q.get('amount_billion', 0) for q in sq.values()), 0),
            'limit_up': sum(1 for q in sq.values() if q['change_pct'] >= 9.5),
            'limit_down': sum(1 for q in sq.values() if q['change_pct'] <= -9.5),
            'source': 'sector_sample'
        }
    _cache_store(cache_key, result, datetime.now(), TTL_BREADTH)
    return result

def get_cached_sector_quotes() -> dict:
    cached, hit = _cache_fetch('sector_quotes', TTL_SECTOR_QUOTES)
    if hit:
        return cached

    boards_df = _get_cached_boards('concept')
    if boards_df is not None and len(boards_df) > 0:
        boards_df = boards_df.head(50)
        code_col = None
        for col in ['板块代码', '代码', 'code']:
            if col in boards_df.columns:
                code_col = col
                break
        if code_col:
            board_codes = boards_df[code_col].astype(str).tolist()
            quotes = fetch_tencent_quotes(board_codes, batch_size=80)
            quote_map = {q['code']: q for q in quotes}
        else:
            logger.warning(f"AkShare板块列名不匹配: {list(boards_df.columns)}")
            quote_map = {}
    else:
        logger.warning("AkShare板块列表不可用，使用硬编码回退")
        all_codes = list(set(
            code for codes in _LEGACY_SECTORS.values() for code in codes
        ))
        quotes = fetch_tencent_quotes(all_codes, batch_size=80)
        quote_map = {q['code']: q for q in quotes}

    _cache_store('sector_quotes', quote_map, datetime.now(), TTL_SECTOR_QUOTES)
    return quote_map

# ═══════════════════════════════════════════════════════════════════
# 优化4: 并行获取独立数据源
# ═══════════════════════════════════════════════════════════════════

def _fetch_index_and_breadth_parallel():
    """并行获取指数（pytdx）+ 全市场广度，减少总延迟"""
    indices = {}
    breadth = {}

    def fetch_pytdx():
        try:
            indices_raw = pytdx_data.get_index_quotes()
            result = {}
            for idx in indices_raw:
                code = idx['code']
                if idx.get('price', 0) > 0:
                    result[code] = {
                        'name': idx['name'],
                        'price': round(idx['price'], 2),
                        'change_pct': round(idx['change_pct'], 2),
                        'amount_billion': round(idx.get('amount', 0) / 1e8, 0),
                    }
            return result
        except Exception as e:
            logger.warning(f"pytdx指数获取失败: {e}")
            return {}

    def fetch_breadth():
        return _fetch_breadth_fast()

    # pytdx 不封 IP，可并发；东财必须串行（em_get 内部有锁保护）
    # 改为：先拿 pytdx（快速），再拿东财（限流）
    indices = {}
    try:
        indices = fetch_pytdx() or {}
    except Exception:
        pass

    breadth = {}
    try:
        breadth = fetch_breadth() or {}
    except Exception:
        pass

    return indices, breadth

# ═══════════════════════════════════════════════════════════════════
# MarketService — 主服务类
# ═══════════════════════════════════════════════════════════════════

class MarketService:
    """市场看板服务 — 双源混合架构（性能优化版）"""

    # ── 顶层结果缓存（参照 StrategyService 模式）────────────
    _MAX_MARKET_CACHE = 16
    _market_cache: OrderedDict = OrderedDict()
    _market_cache_lock = threading.Lock()
    _MARKET_TTL = 300  # 5 分钟
    _STALE_TTL = 86400  # 非交易时段 stale 缓存最长24小时

    @classmethod
    def _get_market_cache(cls, key: str):
        """获取缓存；非交易时段 TTL 过期也返回 stale 数据（限当日）"""
        from app.core.trading_calendar import is_trading_hours
        from app.core.trading_calendar import get_last_trade_date
        with cls._market_cache_lock:
            cached = cls._market_cache.get(key)
            if not cached:
                # 内存未命中：回查 Redis（SWR）
                try:
                    redis_data = cache_get(key, NS_MARKET)
                    if redis_data is not None:
                        return redis_data
                except Exception:
                    pass
                return None
            if time.time() - cached['timestamp'] < cls._MARKET_TTL:
                cls._market_cache.move_to_end(key)
                return cached['data']
            # 非交易时段返回stale缓存，限当日数据，最长24小时
            if not is_trading_hours() and time.time() - cached['timestamp'] < cls._STALE_TTL:
                data = cached['data']
                if not isinstance(data, dict):
                    del cls._market_cache[key]
                    return None
                # 检查数据日期是否为当日/最近交易日
                data_date = data.get('date', '') or data.get('data_date', '')
                last_trade = get_last_trade_date()  # YYYYMMDD
                if data_date and last_trade and data_date.replace('-', '') != last_trade:
                    logger.debug(f"stale缓存日期不匹配: key={key}, data_date={data_date}, last_trade={last_trade}")
                    del cls._market_cache[key]
                    return None
                # 数据质量检查：仅对 sentiment 数据检查指数成交额（其他类型数据不需要）
                if key == 'sentiment':
                    indices_data = data.get('indices', {})
                    sh_amt = indices_data.get('000001', {}).get('amount_billion', 0) or 0
                    sz_amt = indices_data.get('399001', {}).get('amount_billion', 0) or 0
                    if sh_amt > 1000 and sz_amt > 1000:
                        return data
                    del cls._market_cache[key]
                    return None
                # 其他类型数据：检查是否有有效内容
                if data.get('sectors') or data.get('minute_data') or data.get('summary') or data.get('stocks'):
                    return data
                # 没有有效内容的空数据删除
                del cls._market_cache[key]
                return None
        return None

    @classmethod
    def _set_market_cache(cls, key: str, data):
        if not data:
            return
        with cls._market_cache_lock:
            while len(cls._market_cache) >= cls._MAX_MARKET_CACHE:
                cls._market_cache.popitem(last=False)
            cls._market_cache[key] = {'data': data, 'timestamp': time.time()}

        # 同时写入 Redis，供 SWR 后台刷新使用
        try:
            cache_set(key, data, ttl=cls._MARKET_TTL, namespace=NS_MARKET)
        except Exception:
            pass  # Redis 写入失败不影响内存缓存

    @classmethod
    def _get_stale_cache(cls, key: str):
        """获取缓存但不检查 TTL，用于 preload 兜底。
        优先读进程内缓存，再读 Redis/SQLite stale 缓存。
        """
        with cls._market_cache_lock:
            cached = cls._market_cache.get(key)
            if cached:
                return cached['data']
        # 进程内没有，尝试从 Redis/SQLite 读 stale 缓存（不检查TTL）
        try:
            from app.core.cache import cache_get_stale
            redis_data = cache_get_stale(key, NS_MARKET)
            if redis_data is not None:
                return redis_data
        except Exception:
            pass
        return None

    def get_market_sentiment(self, date=None, force_refresh: bool = False, include_flow: bool = True):
        """获取市场情绪指标（并行获取，独立源并发拉取）。

        Args:
            include_flow: 是否包含同花顺资金流拆分（资本流向聚合，约 30s）
                          False 时快路径（约 3s），money_flow 使用东方财富直连/同花顺兜底
        """
        logger.info(f"=== get_market_sentiment called, force_refresh={force_refresh}, include_flow={include_flow} ===")
        if not force_refresh:
            cached = self._get_market_cache('sentiment')
            if cached:
                return cached

            # SWR fallback：内存未命中时尝试 Redis/SQLite 旧数据+后台刷新
            swr_result = swr_cache('sentiment', NS_MARKET, lambda: None, self._MARKET_TTL)
            if swr_result is not None:
                return swr_result

            # 非交易时间：有 stale 缓存直接返回（不校验日期，保证总有数据可展示）
            # 兜底：若 stale 中资金流仍是同花顺行业合计(ths_hyzjl)，跳过 stale 走东财主源刷新
            if not is_trading_hours():
                stale = self._get_stale_cache('sentiment')
                if stale and (stale.get('breadth', {}).get('total', 0) > 0):
                    mf_source = (stale.get('money_flow') or {}).get('source', '')
                    if mf_source == 'ths_hyzjl':
                        logger.info("盘后stale缓存资金流仍为同花顺(ths_hyzjl)，跳过stale走东财主源刷新")
                    else:
                        logger.info("非交易时段返回stale缓存数据")
                        return stale

        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        # 非交易时间（包括周末和非交易时段）
        is_non_trading = not is_trading_hours()

        if is_non_trading:
            logger.info("非交易时段且无缓存，尝试获取上一交易日数据")

        _CODE_MAP = {
            '000001': 'shanghai', '399001': 'shenzhen', '399006': 'chiNext',
            '000016': 'sh50', '000300': 'hs300', '399005': 'small_cap',
            '000688': 'star50', '000905': 'csi500', '000852': 'csi1000'
        }

        # === 并行拉取：指数 / breadth / 涨跌停 / 资金流 ===
        from app.core.data_sources import TencentSource as TS

        def _fetch_indices():
            """获取指数行情（腾讯 > pytdx）"""
            indices = {}
            try:
                tencent_data = TS.get_quotes(['000001', '399001', '399006', '000016', '000300',
                                              '399005', '000688', '000905', '000852'])
                logger.info(f"腾讯指数返回: {len(tencent_data) if tencent_data else 0} 个, "
                            f"SH amount_wan={tencent_data.get('000001', {}).get('amount_wan') if tencent_data else 'N/A'}")
                if tencent_data:
                    for code, data in tencent_data.items():
                        if data.get('price', 0) > 10:
                            indices[code] = {
                                'name': data['name'],
                                'price': round(data['price'], 2),
                                'change_pct': round(data['change_pct'], 2),
                                'amount_billion': round(data.get('amount_wan', 0) / 1e4, 0),
                            }
            except Exception as e:
                logger.warning(f"腾讯指数获取失败: {e}")

            for code in list(indices.keys()):
                mapped_key = _CODE_MAP.get(code)
                if mapped_key and mapped_key not in indices:
                    indices[mapped_key] = dict(indices[code])

            has_good_amounts = any(v.get('amount_billion', 0) > 1000 for v in indices.values())
            if not is_non_trading and not has_good_amounts:
                try:
                    raw = pytdx_data.get_index_quotes()
                    for idx in raw:
                        code = idx['code']
                        if idx.get('price', 0) > 0:
                            idx_data = {
                                'name': idx['name'],
                                'price': round(idx['price'], 2),
                                'change_pct': round(idx['change_pct'], 2),
                                'amount_billion': round(idx.get('amount', 0) / 1e8, 0),
                            }
                            if code not in indices:
                                indices[code] = idx_data
                            else:
                                existing_amt = indices[code].get('amount_billion', 0) or 0
                                new_amt = idx_data.get('amount_billion', 0) or 0
                                if existing_amt < 1000 and new_amt > 1000:
                                    indices[code]['amount_billion'] = new_amt
                            if code in _CODE_MAP:
                                indices[_CODE_MAP[code]] = idx_data
                except Exception as e:
                    logger.warning(f"pytdx指数获取失败: {e}")

            if not indices:
                logger.warning("指数数据获取失败，尝试从缓存恢复")
                # 非交易时段：尝试用stale缓存中的指数数据
                stale_cache = cls._get_stale_cache.__func__(cls, 'sentiment') if is_non_trading else None
                if stale_cache and stale_cache.get('indices'):
                    indices = stale_cache['indices']
                    logger.info(f"从stale缓存恢复指数数据: {len(indices)}个")
                else:
                    default_indices = {
                        '000001': {'name': '上证指数', 'price': 0, 'change_pct': 0, 'amount_billion': 0},
                        '399001': {'name': '深证成指', 'price': 0, 'change_pct': 0, 'amount_billion': 0},
                        '399006': {'name': '创业板指', 'price': 0, 'change_pct': 0, 'amount_billion': 0},
                    }
                    indices = default_indices
                    for code, mapped_key in _CODE_MAP.items():
                        if code in default_indices and mapped_key not in indices:
                            indices[mapped_key] = dict(default_indices[code])

            return indices

        # 三路并行：指数 + breadth全市场 + 涨跌停池（四池精准数据）
        indices = {}
        breadth = None
        limit_pool = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            f_indices = executor.submit(_fetch_indices)
            f_breadth = executor.submit(get_cached_breadth, include_flow)
            f_limit_pool = executor.submit(_fetch_em_limit_up_down, _get_last_trade_date())

        try:
            indices = f_indices.result(timeout=20)
        except Exception as e:
            logger.warning(f"指数获取失败: {e}")

        try:
            breadth = f_breadth.result(timeout=15)
        except Exception as e:
            logger.warning(f"breadth获取失败: {e}")

        try:
            limit_pool = f_limit_pool.result(timeout=10)
        except Exception as e:
            logger.warning(f"涨跌停池获取失败: {e}")

        # breadth必须有有效数据，否则用板块样本估算
        if not breadth or not isinstance(breadth, dict) or breadth.get('total', 0) == 0:
            sq = get_cached_sector_quotes()
            up = sum(1 for q in sq.values() if q['change_pct'] > 0)
            down = sum(1 for q in sq.values() if q['change_pct'] < 0)
            flat = len(sq) - up - down
            total = len(sq)
            breadth = {
                'up': up, 'down': down, 'flat': flat, 'total': total,
                'source': 'sector_sample',
                'limit_up': sum(1 for q in sq.values() if q['change_pct'] >= 9.5),
                'limit_down': sum(1 for q in sq.values() if q['change_pct'] <= -9.5),
            }

        up = breadth['up']
        down = breadth['down']
        flat = breadth['flat']
        total = breadth['total']

        if total == 0:
            sq = get_cached_sector_quotes()
            for q in sq.values():
                cpct = q['change_pct']
                if cpct > 0:
                    up += 1
                elif cpct < 0:
                    down += 1
                else:
                    flat += 1
            total = up + down + flat

        up_ratio = round(up / total * 100, 1) if total > 0 else 0

        # 成交额：优先使用指数成交额（上海+深圳），breadth个股累加作为兜底
        sh_amount = indices.get('000001', {}).get('amount_billion', 0) or 0
        sz_amount = indices.get('399001', {}).get('amount_billion', 0) or 0
        index_total = round(sh_amount + sz_amount, 0)
        breadth_total = breadth.get('total_amount_billion', 0) if breadth else 0

        # 指数成交额 > 2000亿说明数据可靠，否则用breadth兜底
        if index_total > 2000:
            total_amount_billion = index_total
        elif breadth_total > 1000:
            total_amount_billion = breadth_total
        else:
            total_amount_billion = max(index_total, breadth_total)

        # === 3. 涨跌停统计（腾讯全市场扫描优先，东财四池兜底）===
        if breadth and breadth.get('limit_up', 0) > 0:
            limit_up = breadth['limit_up']
            limit_down = breadth.get('limit_down', 0)
            limit_source = breadth.get('source', '?') + '_fullmarket'
        elif limit_pool and limit_pool.get('limit_up', 0) > 0:
            limit_up = limit_pool['limit_up']
            limit_down = limit_pool.get('limit_down', 0)
            limit_source = limit_pool.get('source', 'em_ztpool')
        else:
            limit_up = 0
            limit_down = 0
            limit_source = 'none'

        logger.info(f"涨跌停数据: 涨停{limit_up}家, 跌停{limit_down}家 (source={limit_source})")

        # === 4. 资金流向（优先东方财富大盘资金流，兜底同花顺行业合计）===
        def _compute_flow_signal(net_b: float) -> str:
            if net_b >= 500: return '大幅流入'
            if net_b >= 100: return '明显流入'
            if net_b >= 0:   return '小幅流入'
            if net_b >= -100: return '小幅流出'
            if net_b >= -500: return '明显流出'
            return '大幅流出'

        money_flow_default = {
            'net_inflow_billion': 0, 'inflow_billion': 0, 'outflow_billion': 0,
            'signal': '--', 'source': 'none',
        }

        money_flow = money_flow_default

        def _load_ths():
            """同花顺行业资金流合计（实时，无每日限额）"""
            try:
                ths_flow = _fetch_ths_market_flow(force_refresh=force_refresh)
                ths_net = ths_flow.get('net_inflow_billion', 0) or 0
                if abs(ths_net) > 0.01:
                    mf = {
                        **money_flow_default,
                        'net_inflow_billion': round(ths_net, 2),
                        'inflow_billion': ths_flow.get('inflow_billion', 0),
                        'outflow_billion': ths_flow.get('outflow_billion', 0),
                        'source': 'ths_hyzjl',
                    }
                    mf['signal'] = _compute_flow_signal(ths_net)
                    return mf
            except Exception as e:
                logger.debug(f"同花顺资金流获取失败: {e}")
            return None

        def _load_em():
            """东方财富大盘资金流（实时，含超大单/大单/中单/小单拆分，无每日限额）"""
            try:
                em_flow = _fetch_market_flow(force_refresh=force_refresh)
                em_net = em_flow.get('net_inflow_billion', 0) or 0
                if abs(em_net) > 0.01:
                    mf = {
                        **money_flow_default,
                        'net_inflow_billion': em_flow['net_inflow_billion'],
                        'inflow_billion': em_flow.get('inflow_billion', 0),
                        'outflow_billion': em_flow.get('outflow_billion', 0),
                        'super_large_net': em_flow.get('super_large_net', 0),
                        'large_net': em_flow.get('large_net', 0),
                        'mid_net': em_flow.get('mid_net', 0),
                        'small_net': em_flow.get('small_net', 0),
                        'source': 'eastmoney',
                    }
                    mf['signal'] = _compute_flow_signal(em_net)
                    return mf
            except Exception as e:
                logger.debug(f"东财大盘资金流获取失败: {e}")
            return None

        # 东财大盘资金流为主源（免费、无配额、含完整拆分），同花顺行业合计兜底
        money_flow = _load_em() or _load_ths() or money_flow_default
        logger.info(f"资金流最终来源: {money_flow.get('source')} 主力净流入={money_flow.get('net_inflow_billion')}亿")

        # === 5. 情绪评分（线性插值 + 多指数加权）===
        # 各维度子分数映射到 0-100，然后加权平均

        # 5a. 涨跌家数比 → breadth_score (权重 30%)
        # up_ratio 已是百分数(0-100)，直接映射: 0%→0, 50%→50, 100%→100
        breadth_score = max(0, min(100, up_ratio))

        # 5b. 多指数综合涨跌幅 → index_score (权重 25%)
        # 取上证、深证、创业板三只指数的加权平均（上证40%，深证30%，创业板30%）
        sh_chg = indices.get('000001', {}).get('change_pct', 0) or 0
        sz_chg = indices.get('399001', {}).get('change_pct', 0) or 0
        cyb_chg = indices.get('399006', {}).get('change_pct', 0) or 0

        # 计算有效指数的加权平均涨幅
        valid_indices = []
        if sh_chg != 0 or indices.get('000001'):
            valid_indices.append(('sh', sh_chg, 0.4))
        if sz_chg != 0 or indices.get('399001'):
            valid_indices.append(('sz', sz_chg, 0.3))
        if cyb_chg != 0 or indices.get('399006'):
            valid_indices.append(('cyb', cyb_chg, 0.3))

        if valid_indices:
            total_weight = sum(w for _, _, w in valid_indices)
            composite_change = sum(c * w / total_weight for _, c, w in valid_indices)
        else:
            composite_change = 0

        # 灵敏度 1%≈6分: 0%→50, ±8.3%→0/100，线性映射
        index_score = max(0, min(100, 50 + composite_change * 6))

        # 5c. 涨跌停比 → limit_score (权重 25%)
        total_limit = limit_up + limit_down
        if total_limit > 0:
            limit_ratio = limit_up / total_limit  # 涨停占比
        else:
            limit_ratio = 0.5  # 无数据时中性

        # 涨停占比映射：0%→0, 50%→50, 100%→100
        limit_score = max(0, min(100, limit_ratio * 100))

        # 5d. 成交额 → volume_score (权重 20%)
        # 成交额是"活跃度"中性指标，跟随指数方向加权：
        #   放量+指数涨=多头确认(高分)；放量+指数跌=恐慌抛售(低分)；指数平=中性(50)
        # 活跃度: 量比 0.5→0, 1.0→50, 1.5+→100（近5日均量）；无均量用绝对阈值兜底
        volume_info = self._compute_volume_signal(total_amount_billion, indices)
        avg_5d = volume_info.get('avg_5d_billion')
        if avg_5d and avg_5d > 0:
            vol_ratio = total_amount_billion / avg_5d
            activity = max(0, min(100, (vol_ratio - 0.5) * 100))
        else:
            # 兜底：绝对阈值 3000亿→0(缩量), 15000亿→100(放量)
            activity = max(0, min(100, (total_amount_billion - 3000) / (15000 - 3000) * 100))

        # 跟随指数方向加权：±3% 视为满强度，指数平(≈0%)则成交额不加权
        direction_strength = max(-1, min(1, composite_change / 3))
        volume_score = max(0, min(100, 50 + (activity - 50) * direction_strength))

        # 加权总分
        score = round(
            breadth_score * 0.30 +
            index_score * 0.25 +
            limit_score * 0.25 +
            volume_score * 0.20
        )
        score = max(0, min(100, score))

        if score >= 75:
            signal = '偏多活跃'
        elif score >= 60:
            signal = '温和偏多'
        elif score >= 45:
            signal = '中性震荡'
        elif score >= 30:
            signal = '温和偏空'
        else:
            signal = '偏空低迷'

        result = {
            'timestamp': now,
            'data_date': _format_display_date(_get_last_trade_date()),
            'score': score,
            'signal': signal,
            'indices': indices,
            'breadth': {
                'up': up, 'down': down, 'flat': flat,
                'total': total, 'up_ratio': up_ratio,
                'limit_up': limit_up, 'limit_down': limit_down,
            },
            'money_flow': money_flow,
            # 同花顺 Top 资金流拆分（大单/超大单/中单/小单）— 仅在 include_flow=True 时包含
            'capital_flow_breakdown': (breadth.get('capital_flow_breakdown', {}) if include_flow else {}),
            'volume': volume_info,
            'limit_up_down': {
                'limit_up': limit_up, 'limit_down': limit_down
            },
        }
        # 只在有有效数据时缓存（避免空数据覆盖上次成功缓存）
        if total > 0:
            self._set_market_cache('sentiment', result)
        elif not is_trading_hours():
            # 非交易时段且无新数据：直接返回 stale
            stale = self._get_stale_cache('sentiment')
            if stale and stale.get('breadth', {}).get('total', 0) > 0:
                return stale
        return result

    @staticmethod
    def _compute_volume_signal(total_amount_billion: float, indices: dict) -> dict:
        """计算成交额信号：对比近5日均量，动态判断放量/缩量
        
        返回: {'total_billion': float, 'signal': str, 'avg_5d_billion': float | None}
        """
        result = {
            'total_billion': total_amount_billion,
            'signal': '--',
            'avg_5d_billion': None,
        }

        # 尝试获取近5日K线数据来计算均量
        try:
            from app.core.pytdx_source import pytdx_data

            # 取上证和深证的K线，计算历史均量
            klines_sh = pytdx_data.get_index_kline('000001', 9, 10) or []
            klines_sz = pytdx_data.get_index_kline('399001', 9, 10) or []

            # 取最近5个交易日（排除今天）的成交额均值
            hist_sh = [k.get('amount', 0) for k in (klines_sh[:-1])[-5:]]
            hist_sz = [k.get('amount', 0) for k in (klines_sz[:-1])[-5:]]

            if hist_sh and hist_sz:
                # pytdx的amount单位是元，转换为亿
                avg_5d_sh_billion = sum(hist_sh) / len(hist_sh) / 1e8
                avg_5d_sz_billion = sum(hist_sz) / len(hist_sz) / 1e8
                avg_5d_total = round(avg_5d_sh_billion + avg_5d_sz_billion, 0)

                result['avg_5d_billion'] = avg_5d_total

                if avg_5d_total > 0:
                    vol_ratio = total_amount_billion / avg_5d_total
                    if vol_ratio >= 1.2:
                        result['signal'] = '放量'
                    elif vol_ratio <= 0.8:
                        result['signal'] = '缩量'
                    else:
                        result['signal'] = '正常'
                    return result
        except Exception as e:
            logger.debug(f"计算均量失败，使用兜底阈值: {e}")

        # 兜底：使用绝对阈值（适配当前市场量能水平）
        if total_amount_billion > 12000:
            result['signal'] = '放量'
        elif total_amount_billion < 6000:
            result['signal'] = '缩量'
        else:
            result['signal'] = '正常'

        return result

    def _fetch_legu_limit(self) -> dict:
        """从乐咕乐股获取收盘涨跌停家数（兜底）"""
        try:
            r = httpx.get('https://www.legulegu.com/stockdata/market-activity',
                          headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            text = r.text
            
            # 优先从 meta description 提取（格式：涨停XX家, 跌停YY家）
            desc_match = re.search(r'涨停(\d+)家.*?跌停(\d+)家', text)
            if desc_match:
                limit_up = int(desc_match.group(1))
                limit_down = int(desc_match.group(2))
                logger.info(f"乐咕乐股涨跌停(meta): 涨停{limit_up}家, 跌停{limit_down}家")
                return {'limit_up': limit_up, 'limit_down': limit_down, 'source': 'legu'}
            
            # 回退：从表格提取
            up_match = re.search(r'>涨停</[^>]*>.*?<td[^>]*>(\d+)</td>', text, re.DOTALL)
            down_match = re.search(r'>跌停</[^>]*>.*?<td[^>]*>(\d+)</td>', text, re.DOTALL)
            if up_match and down_match:
                return {'limit_up': int(up_match.group(1)), 'limit_down': int(down_match.group(1)), 'source': 'legu'}
            return {}
        except Exception as e:
            logger.warning(f"乐咕乐股涨跌停获取失败: {e}")
            return {}

    @staticmethod
    def _execute_with_limit(func, *args, timeout=10, **kwargs):
        """带并发限制的 API 调用包装器。"""
        with _MODULE_SEMAPHORE:
            return func(*args, **kwargs)

    def _fetch_all_sectors(self, sector_type='industry', max_retries=2):
        """获取全量板块数据（用于轮动分析）。

        Bug #2 + 优化1修复：统一使用 _em_sector_list() 作为主数据源，
        字段集与 sector_analysis_service 保持一致。
        THS/腾讯方案作为兜底。
        """
        from app.services.sector_analysis_service import _em_sector_list as unified_sector_list

        # 方案1: 统一东财 push2（走 em_get 限流，5秒内复用缓存）
        try:
            rows = unified_sector_list(sector_type)
            if rows:
                sector_list = []
                for row in rows:
                    sector_list.append({
                        'name': row['name'],
                        'code': row['code'],
                        'change_pct': row.get('change_pct', 0),
                        'turnover': round(row.get('turnover_yi', 0) or 0, 0),
                        'flow_net': row.get('flow_net', 0),
                        'stock_count': (row.get('up_count', 0) or 0) + (row.get('down_count', 0) or 0),
                        'lead_stock': row.get('lead_stock', ''),
                    })
                logger.info(f"统一东财 {sector_type}板块数据: 共{len(sector_list)}个")
                return sector_list
        except Exception as e:
            logger.warning(f"统一板块列表获取失败: {e}")

        # 方案2: THS + 腾讯兜底（保持原有逻辑）
        for attempt in range(max_retries + 1):
            try:
                if sector_type == 'industry':
                    boards_data = EastMoneySource.get_industry_boards(page_size=100)
                else:
                    boards_data = EastMoneySource.get_concept_boards(page_size=500)

                if not boards_data:
                    raise ValueError("东财返回空数据")

                sector_list = []
                for row in boards_data:
                    try:
                        name = str(row.get('f14', ''))
                        change_pct = float(row.get('f3', 0) or 0)
                        amount = float(row.get('f6', 0) or 0) / 1e8
                        flow_net = float(row.get('f62', 0) or 0) / 1e8

                        sector_list.append({
                            'name': name,
                            'code': str(row.get('f12', '')),
                            'change_pct': round(change_pct, 2),
                            'turnover': round(amount, 0),
                            'flow_net': round(flow_net, 2),
                            'stock_count': int(float(row.get('f9', 0) or 0)),
                            'lead_stock': str(row.get('f140', '')) or '',
                        })
                    except (ValueError, TypeError):
                        continue

                if sector_list:
                    logger.info(f"THS+腾讯 {sector_type}板块数据: 共{len(sector_list)}个")
                    return sector_list
            except Exception as e:
                logger.warning(f"东财{sector_type}板块获取失败(第{attempt+1}次): {e}")
                if attempt < max_retries:
                    import time
                    time.sleep(1)

        # 最终兜底: 硬编码板块
        logger.warning(f"所有{sector_type}板块接口均失败，回退到硬编码板块")
        return self._fetch_legacy_sectors(sector_type)

    def _fetch_legacy_sectors(self, sector_type='industry'):
        """硬编码板块兜底数据"""
        quote_map = get_cached_sector_quotes()
        sectors_map = _LEGACY_SECTORS
        sector_list = []
        for name, codes in sectors_map.items():
            sq = [quote_map[c] for c in codes if c in quote_map]
            if not sq:
                continue
            avg_change = round(sum(q['change_pct'] for q in sq) / len(sq), 2)
            total_amount = round(sum(q['amount_billion'] for q in sq), 0)
            up_count = sum(1 for q in sq if q['change_pct'] > 0)
            flow_net = round(sum(
                q['amount_billion'] * min(abs(q['change_pct']), 5) / 5 * (1 if q['change_pct'] > 0 else -1)
                for q in sq
            ), 0)
            sector_list.append({
                'name': name, 'code': codes[0],
                'change_pct': avg_change, 'turnover': total_amount,
                'flow_net': flow_net, 'up_count': up_count, 'stock_count': len(sq),
            })
        sector_list.sort(key=lambda x: x['change_pct'], reverse=True)
        return sector_list

    def _fetch_sectors_data(self, sector_type='industry', top=12):
        """获取板块数据核心逻辑（供SWR后台刷新和正常路径共用）"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M')

        all_sectors = self._fetch_all_sectors(sector_type)
        if all_sectors:
            sector_list = sorted(all_sectors, key=lambda x: x['change_pct'], reverse=True)[:top]
            return {'timestamp': now, 'sectors': sector_list}

        # 最终兜底: 硬编码板块
        logger.warning(f"所有{sector_type}板块API失败，回退到硬编码板块")
        sector_list = self._fetch_legacy_sectors(sector_type)
        return {'timestamp': now, 'sectors': sector_list[:top]}

    def get_sectors(self, sector_type='industry', top=12, force_refresh: bool = False):
        """获取板块行情（东财 push2 接口，含真实资金流向）"""
        cache_key = f'sectors:{sector_type}:{top}'
        if not force_refresh:
            cached = self._get_market_cache(cache_key)
            if cached:
                return cached
            # SWR fallback：内存缓存未命中时尝试 Redis/SQLite 旧数据+后台刷新
            # 有stale数据立即返回（后台异步刷新），无数据则阻塞拉取
            swr_result = swr_cache(cache_key, NS_MARKET,
                                   lambda: self._fetch_sectors_data(sector_type, top), 300)
            if swr_result is not None and isinstance(swr_result, dict) and swr_result.get('sectors'):
                return swr_result

        result = self._fetch_sectors_data(sector_type, top)
        self._set_market_cache(cache_key, result)
        logger.info(f"板块[{sector_type}]实时数据: {len(result.get('sectors', []))}个")
        return result

    def _fetch_hot_sectors_data(self, top=10):
        """获取热点题材核心逻辑（供SWR后台刷新和正常路径共用）"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        # 1. 同花顺热点题材归因（独家 reason 标签）
        ths_hot_items = THSHotSource.get_hot_reasons(page_size=200)
        ths_map = {item['code']: item for item in ths_hot_items}
        # 构建 THS 热门标签集合，用于识别热门题材关键词
        ths_tags = set()
        for item in ths_hot_items:
            if item.get('tag'):
                ths_tags.add(item['tag'])
        
        # 2. 直接获取东财概念板块原始数据（不通过 get_sectors）
        boards_data = EastMoneySource.get_concept_boards(page_size=500)
        
        if not boards_data:
            # 兜底：使用 get_sectors
            concept_data = self.get_sectors(sector_type='concept', top=top)
            concept_data['ths_hot_stocks'] = [{
                'code': item['code'],
                'name': item['name'],
                'price': item['price'],
                'pct_change': item['pct_change'],
                'reason': item.get('reason', ''),
                'tag': item.get('tag', ''),
            } for item in ths_hot_items[:top]]
            return concept_data
        
        # 解析板块数据并计算多维度热度评分
        sectors = []
        for row in boards_data:
            try:
                name = str(row.get('f14', ''))
                change_pct = float(row.get('f3', 0) or 0)
                amount = float(row.get('f6', 0) or 0) / 1e8  # 成交额(亿)
                flow_net = float(row.get('f62', 0) or 0) / 1e8  # 主力净流入(亿)
                stock_count = int(float(row.get('f9', 0) or 0))
                lead_stock = str(row.get('f140', '')) or ''
                
                # 过滤低活跃度板块（THS来源放宽条件，非THS来源保持严格）
                is_ths_source = row.get('source') == 'ths_hot_grouped'
                if is_ths_source:
                    if stock_count < 1:
                        continue
                else:
                    if amount < 5 or stock_count < 2:
                        continue
                
                # 多维度热度评分算法（与概念板块的涨跌幅排序完全不同）
                heat_score = 0.0
                
                # 维度1: 涨跌幅贡献 (权重30%) - 大幅上涨或下跌都算热门
                abs_change = abs(change_pct)
                if abs_change > 7:
                    heat_score += 30
                elif abs_change > 5:
                    heat_score += 25
                elif abs_change > 3:
                    heat_score += 18
                elif abs_change > 1:
                    heat_score += 10
                
                # 维度2: 资金流入贡献 (权重25%) - 大资金净流入是重要信号
                if flow_net > 50:
                    heat_score += 25
                elif flow_net > 20:
                    heat_score += 20
                elif flow_net > 10:
                    heat_score += 15
                elif flow_net > 5:
                    heat_score += 8
                
                # 维度3: 成交额贡献 (权重20%) - 高成交额代表高关注度
                if amount > 100:
                    heat_score += 20
                elif amount > 50:
                    heat_score += 15
                elif amount > 20:
                    heat_score += 10
                
                # 维度4: THS热点归因加分 (权重25%) - 同花顺人工运营标签
                ths_reason = ''
                ths_tag = ''
                if lead_stock in ths_map:
                    ths_item = ths_map[lead_stock]
                    heat_score += 25
                    ths_reason = ths_item.get('reason', '')
                    ths_tag = ths_item.get('tag', '')
                
                sectors.append({
                    'name': name,
                    'code': str(row.get('f12', '')),
                    'change_pct': round(change_pct, 2),
                    'turnover': round(amount, 0),
                    'flow_net': round(flow_net, 2),
                    'stock_count': stock_count,
                    'lead_stock': lead_stock,
                    'heat_score': round(heat_score, 1),
                    'ths_reason': ths_reason,
                    'ths_tag': ths_tag,
                })
            except (ValueError, TypeError):
                continue
        
        # 按热度评分降序排序（与概念板块的涨跌幅排序不同）
        sectors.sort(key=lambda x: x['heat_score'], reverse=True)
        
        result = {
            'timestamp': now,
            'sectors': sectors[:top],
            'ths_hot_stocks': [{
                'code': item['code'],
                'name': item['name'],
                'price': item['price'],
                'pct_change': item['pct_change'],
                'reason': item.get('reason', ''),
                'tag': item.get('tag', ''),
            } for item in ths_hot_items[:top]],
        }
        
        return result

    def get_hot_sectors(self, top=10, force_refresh: bool = False):
        """获取热点题材（同花顺归因 + 东财板块热度）
        
        与概念板块的区别：
        - 概念板块: 按涨跌幅排序，展示所有概念
        - 热点题材: 综合多维度热度评分(涨幅+资金流+成交额+涨停股+THS归因)，筛选真正热门题材
        """
        cache_key = f'hot_sectors:{top}'
        if not force_refresh:
            cached = self._get_market_cache(cache_key)
            if cached:
                return cached
            # SWR fallback：进程/stale 都未命中时尝试 Redis/SQLite 旧数据+后台刷新
            swr_result = swr_cache(cache_key, NS_MARKET,
                                   lambda: self._fetch_hot_sectors_data(top), 300)
            if swr_result is not None:
                return swr_result

        result = self._fetch_hot_sectors_data(top)
        self._set_market_cache(cache_key, result)
        logger.info(f"热点题材实时数据: {len(result.get('sectors', []))}个")
        return result
    
    def get_northbound_flow(self):
        """获取北向资金实时流向"""
        cached = self._get_market_cache('northbound')
        if isinstance(cached, dict) and (cached.get('summary') or cached.get('minute_data')):
            return cached

        # 非交易时段：优先返回stale缓存（盘中最后的数据）
        if not is_trading_hours():
            stale = self._get_stale_cache('northbound')
            if isinstance(stale, dict) and (stale.get('summary') or stale.get('minute_data')):
                logger.info("非交易时段返回stale北向资金缓存")
                return stale
            # SWR fallback：尝试 Redis/SQLite 旧数据
            swr_result = swr_cache('northbound', NS_MARKET, lambda: None, self._MARKET_TTL)
            if isinstance(swr_result, dict) and (swr_result.get('summary') or swr_result.get('minute_data')):
                logger.info("非交易时段返回SWR北向资金缓存")
                return swr_result
            logger.info("非交易时段北向资金缓存为空，尝试获取收盘数据")

        # SWR fallback：内存/Redis 都未命中时尝试 SQLite 旧数据+后台刷新
        swr_result = swr_cache('northbound', NS_MARKET, lambda: THSNorthboundSource.get_realtime(), self._MARKET_TTL)
        if swr_result is not None:
            # SWR 可能返回 list（旧缓存格式），兼容处理
            if isinstance(swr_result, dict):
                return swr_result
            result = {'minute_data': swr_result if isinstance(swr_result, list) else [], 'summary': {}}
            # 从 SWR 数据计算 summary
            if swr_result:
                hgt_values = [d['hgt_yi'] for d in swr_result if d.get('hgt_yi') is not None]
                sgt_values = [d['sgt_yi'] for d in swr_result if d.get('sgt_yi') is not None]
                result['summary'] = {
                    'hgt_latest': hgt_values[-1] if hgt_values else 0,
                    'sgt_latest': sgt_values[-1] if sgt_values else 0,
                    'hgt_max': max(hgt_values) if hgt_values else 0,
                    'sgt_max': max(sgt_values) if sgt_values else 0,
                }
            return result

        realtime = THSNorthboundSource.get_realtime()
        result = {
            'minute_data': realtime,
            'summary': {},
        }

        # 计算汇总统计
        if realtime:
            hgt_values = [d['hgt_yi'] for d in realtime if d.get('hgt_yi') is not None]
            sgt_values = [d['sgt_yi'] for d in realtime if d.get('sgt_yi') is not None]

            result['summary'] = {
                'hgt_latest': hgt_values[-1] if hgt_values else 0,
                'sgt_latest': sgt_values[-1] if sgt_values else 0,
                'hgt_max': max(hgt_values) if hgt_values else 0,
                'sgt_max': max(sgt_values) if sgt_values else 0,
            }
        else:
            # 非交易时段且实时数据为空：尝试从历史CSV获取最近一天的数据
            logger.info("北向资金实时数据为空，尝试从历史记录获取")
            try:
                history = THSNorthboundSource.get_history(n=1)
                if history:
                    last_day = history[-1]
                    result['summary'] = {
                        'hgt_latest': last_day.get('hgt_yi') or 0,
                        'sgt_latest': last_day.get('sgt_yi') or 0,
                        'hgt_max': last_day.get('hgt_yi') or 0,
                        'sgt_max': last_day.get('sgt_yi') or 0,
                    }
                    logger.info(f"从历史记录获取北向资金: 沪股通{result['summary']['hgt_latest']}亿, 深股通{result['summary']['sgt_latest']}亿")
            except Exception as e:
                logger.warning(f"获取北向资金历史数据失败: {e}")

        self._set_market_cache('northbound', result)
        return result

    def get_indices_with_kline(self, codes: list[str] = None, kline_count: int = 30):
        """获取指数列表 + 最近 N 日 K 线（pytdx 直连，不依赖东财）

        codes: 指数代码列表（默认 6 个核心指数）
        kline_count: K 线根数（默认 30 日）

        返回: {
            indices: [{code, name, price, change_pct, kline: [{date, close}, ...]}],
            timestamp: 'YYYY-MM-DD HH:MM',
        }
        """
        if not codes:
            codes = ['000001', '399001', '399006', '000300', '000016', '000688']

        cache_key = f'indices_kline:{",".join(codes)}:{kline_count}'
        cached = self._get_market_cache(cache_key)
        if cached:
            return cached
        if not is_trading_hours():
            stale = self._get_stale_cache(cache_key)
            if stale:
                return stale
        # SWR fallback：内存/Redis 都未命中时尝试 SQLite 旧数据+后台刷新
        swr_result = swr_cache(cache_key, NS_MARKET, lambda: None, self._MARKET_TTL)
        if swr_result is not None:
            return swr_result

        # 1. 取指数实时行情（pytdx → 腾讯财经兜底）
        try:
            from app.core.pytdx_source import pytdx_data
            quotes = pytdx_data.get_index_quotes()
            quote_map = {q['code']: q for q in quotes if q.get('code')}
        except Exception as e:
            logger.warning(f"pytdx 指数行情获取失败: {e}")
            quote_map = {}

        # 用腾讯财经补全 pytdx 缺失的指数（周末/非交易时段常见）
        missing_codes = [c for c in codes if c not in quote_map]
        if missing_codes:
            try:
                from app.core.data_sources import TencentSource as _TS
                tencent_data = _TS.get_quotes(missing_codes)
                if tencent_data:
                    for code, data in tencent_data.items():
                        if data.get('price', 0) > 10:
                            quote_map[code] = {
                                'name': data['name'],
                                'price': round(data['price'], 2),
                                'change_pct': round(data['change_pct'], 2),
                                'amount': data.get('amount_wan', 0) * 1e4,
                            }
                    logger.info(f"腾讯财经补全指数: {len(missing_codes)}个缺失 → {len(quote_map)}个完整")
            except Exception as e:
                logger.warning(f"腾讯财经指数补全失败: {e}")

        # 2. 并行取 K 线（指数必须用 get_index_kline，不能用 get_security_bars）
        kline_map = {}
        try:
            from app.core.pytdx_source import pytdx_data
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(pytdx_data.get_index_kline, c, 9, kline_count): c for c in codes}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        c = futures[future]
                        bars = future.result(timeout=15)
                        if bars:
                            kline_map[c] = bars
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"pytdx 指数 K 线获取失败: {e}")

        # 3. 整合
        result_indices = []
        for code in codes:
            quote = quote_map.get(code, {})
            klines = kline_map.get(code, [])

            result_indices.append({
                'code': code,
                'name': quote.get('name', self._CODE_NAME_MAP().get(code, code)),
                'price': round(quote.get('price', 0) or 0, 2),
                'change_pct': round(quote.get('change_pct', 0) or 0, 2),
                'kline': klines,  # [{date, open, high, low, close, volume}, ...]
            })

        result = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'kline_count': kline_count,
            'indices': result_indices,
        }
        self._set_market_cache(cache_key, result)
        return result

    @staticmethod
    def _CODE_NAME_MAP():
        return {
            '000001': '上证指数', '399001': '深证成指', '399006': '创业板指',
            '000016': '上证50', '000300': '沪深300', '000688': '科创50',
            '000905': '中证500', '000852': '中证1000', '399005': '中小板指',
        }

    @staticmethod
    def _enrich_limit_up_data(result: dict) -> dict:
        """涨停池数据补充：腾讯行情补充成交额/换手率/量比/振幅（不使用东财接口）"""
        if not result:
            result = {
                'total': 0,
                'patterns': {'一字': 0, '开板': 0, '连板': 0, '换手': 0},
                'max_continuous': 0,
                'total_sealed_yi': 0,
                'total_amount_yi': 0,
                'stocks': [],
            }

        # 汇总同花顺已有的封单数据（不调用东财接口）
        stocks = result.get('stocks', [])
        if stocks and not result.get('total_sealed_yi'):
            total_sealed = sum(float(s.get('sealed_amount_yi', 0) or 0) for s in stocks)
            result['total_sealed_yi'] = round(total_sealed, 2)

        # 用东方财富涨停池数据补充缺失的封单金额和首封时间
        if stocks:
            try:
                from app.core.data_sources_clean import EastMoneyLimitUpPoolSource
                from app.core.trading_calendar import get_last_trade_date
                trade_date_str = get_last_trade_date()
                sealed_map = EastMoneyLimitUpPoolSource.get_sealed_amount_map(trade_date_str)
                first_time_map = EastMoneyLimitUpPoolSource.get_first_time_map(trade_date_str)
                if sealed_map or first_time_map:
                    for stock in stocks:
                        code = stock.get('code', '')
                        if not code:
                            continue
                        # 补充封单金额
                        if code in sealed_map:
                            em_seal = sealed_map[code]
                            if (not stock.get('sealed_amount_yi') or stock['sealed_amount_yi'] == 0) and em_seal > 0:
                                stock['sealed_amount_yi'] = em_seal
                        # 补充首封时间
                        if code in first_time_map:
                            em_time = first_time_map[code]
                            if (not stock.get('first_time') or stock['first_time'] == '') and em_time:
                                stock['first_time'] = em_time
            except Exception as e:
                logger.debug(f"东财涨停池数据补充失败: {e}")

        # 用腾讯实时行情补充缺失字段（成交额、换手率、量比、振幅）
        if stocks:
            try:
                from app.core.data_sources_clean import TencentSource
                codes = [s['code'] for s in stocks if s.get('code')]
                quotes = TencentSource.get_quotes(codes) if codes else {}
                if quotes:
                    total_amount = 0
                    for stock in stocks:
                        code = stock.get('code', '')
                        q = quotes.get(code, {})
                        # 统一空字段处理（THS 新版 API 大量字段返回 null）
                        if stock.get('first_time') is None:
                            stock['first_time'] = ''
                        if stock.get('last_time') is None:
                            stock['last_time'] = ''
                        if not stock.get('industry'):
                            stock['industry'] = '--'
                        if not stock.get('reason') or stock.get('reason') == '':
                            stock['reason'] = '--'
                        if not q:
                            continue
                        # 补充成交额（腾讯返回万元 → 转亿）
                        if (not stock.get('amount_billion') or stock['amount_billion'] == 0) and q.get('amount_wan'):
                            stock['amount_billion'] = round(float(q['amount_wan'] or 0) / 10000, 2)
                        # 补充换手率
                        if (not stock.get('turnover_pct') or stock['turnover_pct'] == 0) and q.get('turnover_pct'):
                            stock['turnover_pct'] = round(float(q['turnover_pct'] or 0), 2)
                        # 补充量比
                        if not stock.get('vol_ratio') and q.get('vol_ratio'):
                            stock['vol_ratio'] = round(float(q['vol_ratio'] or 0), 2)
                        # 补充振幅
                        if not stock.get('amplitude_pct') and q.get('amplitude_pct'):
                            stock['amplitude_pct'] = round(float(q['amplitude_pct'] or 0), 2)
                        total_amount += stock.get('amount_billion', 0) or 0
                    result['total_amount_yi'] = round(total_amount, 1)
            except Exception as e:
                logger.debug(f"腾讯行情补充涨停池数据失败: {e}")
            # 兜底：未获取到腾讯行情时也要统一空字段
            for stock in stocks:
                if stock.get('first_time') is None:
                    stock['first_time'] = ''
                if stock.get('last_time') is None:
                    stock['last_time'] = ''
                if not stock.get('industry'):
                    stock['industry'] = '--'
                if not stock.get('reason'):
                    stock['reason'] = '--'
                # pattern 兜底：同花顺可能返回空，确保有默认值
                if not stock.get('pattern'):
                    continuous = stock.get('continuous_limit_num') or 1
                    open_count = stock.get('open_count') or 0
                    if open_count > 0:
                        stock['pattern'] = '开板'
                    elif continuous >= 2:
                        stock['pattern'] = '连板'
                    else:
                        stock['pattern'] = '换手'

        from app.core.trading_calendar import get_last_trade_date
        trade_date = get_last_trade_date()  # YYYYMMDD
        result['data_date'] = f'{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}'  # YYYY-MM-DD
        result['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M')
        return result

    def get_limit_up_pool(self, force_refresh: bool = False):
        """获取涨停板池（同花顺 data.10jqka.com.cn）

        返回:
        {
            total, patterns: {一字, 开板, 连板, 换手},
            max_continuous, total_sealed_yi, total_amount_yi,
            stocks: [{code, name, change_pct, sealed_amount_yi, pattern, ...}],
        }
        """
        cache_key = 'limit_up_pool'
        if not force_refresh:
            cached = self._get_market_cache(cache_key)
            if cached:
                return cached
            # SWR fallback：有 stale 数据立即返回，无则阻塞拉取+补充
            swr_result = swr_cache(
                cache_key, NS_MARKET,
                lambda: self._enrich_limit_up_data(THSLimitUpPoolSource.get_limit_up_summary()),
                self._MARKET_TTL,
            )
            if swr_result is not None:
                return swr_result

        result = THSLimitUpPoolSource.get_limit_up_summary()
        result = self._enrich_limit_up_data(result)
        self._set_market_cache(cache_key, result)
        return result

    def get_limit_down_pool(self, force_refresh: bool = False) -> dict:
        """获取跌停板池（腾讯全市场数据筛选 + 腾讯实时行情补充字段）

        返回格式与涨停池一致：
        {total, stocks: [{code, name, change_pct, price, amount_billion, turnover_pct, industry, ...}]}
        """
        cache_key = 'limit_down_pool'
        if not force_refresh:
            cached = self._get_market_cache(cache_key)
            if cached:
                return cached

        try:
            from app.core.data_sources_clean import EastMoneyZTPool, TencentSource

            # 仅用腾讯全市场数据筛选跌停股（不使用东财 push2）
            _, dt_raw = EastMoneyZTPool._fetch_tencent_pool()
            stocks = []

            if dt_raw:
                for it in dt_raw:
                    code = str(it.get("c", ""))
                    name = str(it.get("n", "") or "--")
                    price = float(it.get("p", 0) or 0) / 1000 if it.get("p") else 0
                    change_pct = float(it.get("zdp", 0) or 0)
                    amount_yi = round(float(it.get("jje", 0) or 0) / 1e8, 2)
                    stocks.append({
                        "code": code, "name": name, "price": price,
                        "change_pct": change_pct, "amount_billion": amount_yi,
                        "turnover_pct": 0, "industry": "--",
                        "sealed_amount_yi": 0, "open_count": 0,
                        "continuous_limit_num": 1,
                        "first_time": "", "reason": "--", "pattern": "跌停",
                    })

            # 用腾讯实时行情补充缺失字段（成交额、换手率、量比、振幅等）
            if stocks:
                try:
                    codes = [s["code"] for s in stocks]
                    quotes = TencentSource.get_quotes(codes)
                    for stock in stocks:
                        q = quotes.get(stock["code"], {})
                        if not q:
                            continue
                        if (not stock.get("amount_billion") or stock["amount_billion"] == 0) and q.get("amount_wan"):
                            stock["amount_billion"] = round(float(q["amount_wan"] or 0) / 10000, 2)
                        if (not stock.get("turnover_pct") or stock["turnover_pct"] == 0) and q.get("turnover_pct"):
                            stock["turnover_pct"] = round(float(q["turnover_pct"] or 0), 2)
                        if not stock.get("price") or stock["price"] == 0:
                            stock["price"] = float(q.get("price", 0) or 0)
                        if q.get("vol_ratio"):
                            stock["vol_ratio"] = round(float(q["vol_ratio"] or 0), 2)
                        if q.get("amplitude_pct"):
                            stock["amplitude_pct"] = round(float(q["amplitude_pct"] or 0), 2)
                except Exception as e:
                    logger.debug(f"腾讯行情补充跌停池数据失败: {e}")

            logger.info(f"腾讯跌停池: {len(stocks)}只")
            from app.core.trading_calendar import get_last_trade_date
            trade_date = get_last_trade_date()  # YYYYMMDD
            result = {
                "total": len(stocks),
                "stocks": stocks,
                "data_date": f'{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}',  # YYYY-MM-DD
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            self._set_market_cache(cache_key, result)
            return result
        except Exception as e:
            logger.warning(f"获取跌停池失败: {e}")
            from app.core.trading_calendar import get_last_trade_date
            trade_date = get_last_trade_date()  # YYYYMMDD
            return {"total": 0, "stocks": [], "data_date": f'{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}', "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")}

    def get_ths_hot_rank(self, top: int = 30, force_refresh: bool = False):
        """同花顺热门个股榜（多源融合：THS 热点归因 + 资金流加分 + 实时价格）

        排名算法:
        - THS 人工归因分（reason 非空）：+50
        - 净流入分: max(-30, min(30, net_yi * 3))
        - 涨幅分: max(-30, min(30, change_pct * 8))
        - 热度分: 基于 THS rank 倒数

        返回: list[dict]，含 code, name, pct_change, reason, tag, composite_score
        """
        cache_key = f'ths_hot_rank:{top}'
        if not force_refresh:
            cached = self._get_market_cache(cache_key)
            if cached:
                return cached
            # SWR fallback：内存/Redis 都未命中时尝试 SQLite 旧数据+后台刷新
            swr_result = swr_cache(cache_key, NS_MARKET, lambda: None, self._MARKET_TTL)
            if swr_result is not None:
                return swr_result

        # 1. THS 热点归因
        ths_items = THSHotSource.get_hot_reasons(page_size=200)

        # 2. 资金流加分（按 code 索引）
        capital_pool = {}
        try:
            capital_pool = THSCapitalFlowSource.get_top_capital_flows(pages=2)
        except Exception:
            pass

        # 3. 用腾讯财经补全实时价格
        codes = [it.get('code', '') for it in ths_items if it.get('code')]
        quotes_map = {}
        if codes:
            try:
                from app.core.data_sources import TencentSource as _TS
                quotes_map = _TS.get_quotes(codes)
            except Exception:
                pass

        # 4. 复合评分
        items = []
        for it in ths_items:
            code = it.get('code', '')
            name = it.get('name', '')
            pct = float(it.get('pct_change') or it.get('zhangfu') or 0)
            reason = it.get('reason') or ''
            tag = it.get('tag') or ''
            ths_rank = int(it.get('rank') or it.get('rd') or 0)

            # 用腾讯财经补全最新价/涨跌幅
            q = quotes_map.get(code) or {}
            if q and q.get('price', 0) > 0:
                pct = float(q.get('change_pct', pct) or pct)
                price = float(q.get('price', 0) or 0)
            else:
                price = float(it.get('price') or it.get('close') or 0)

            # 综合评分
            score = 0.0
            if reason:
                score += 50  # THS 人工归因权重最高
            if tag:
                score += 10
            score += max(-30, min(30, pct * 8))  # 涨幅 ±30
            score += max(0, (200 - ths_rank) / 4)  # 排名加分

            items.append({
                'code': code,
                'name': name,
                'pct_change': round(pct, 2),
                'price': round(price, 2),
                'reason': reason,
                'tag': tag,
                'ths_rank': ths_rank,
                'composite_score': round(score, 1),
                'source': 'ths_hot+tencent',
            })

        items.sort(key=lambda x: x['composite_score'], reverse=True)
        result = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'total': len(items),
            'stocks': items[:top],
        }
        self._set_market_cache(cache_key, result)
        return result

    def get_rotation_signals(self, force_refresh: bool = False):
        """板块轮动信号分析"""
        if not force_refresh:
            cached = self._get_market_cache('rotation')
            if cached:
                return cached
            # SWR fallback：内存/Redis 都未命中时尝试 SQLite 旧数据+后台刷新
            swr_result = swr_cache('rotation', NS_MARKET,
                                lambda: self._fetch_rotation_signals_data(),
                                self._MARKET_TTL)
            if swr_result is not None:
                return swr_result

        return self._fetch_rotation_signals_data()

    def _fetch_rotation_signals_data(self) -> dict:
        """获取板块轮动信号核心逻辑（供SWR后台刷新和正常路径共用）"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M')

        try:
            all_sectors = self._fetch_all_sectors('industry')
        except Exception as e:
            logger.warning(f"轮动信号获取失败: {e}")
            return {'timestamp': now}

        if not all_sectors:
            return {'timestamp': now}

        total_count = len(all_sectors)
        up_count = sum(1 for s in all_sectors if s['change_pct'] > 0)
        down_count = sum(1 for s in all_sectors if s['change_pct'] < 0)

        cyclical_keywords = ['煤炭', '钢铁', '石油', '化工', '有色', '建材', '房地产', '机械', '金属', '贵金属']
        growth_keywords = ['半导体', '光伏', '计算机', '软件', '通信', '电子', '军工', '电池', '电网', '汽车', '元件']
        defensive_keywords = ['银行', '电力', '白酒', '饮料', '食品', '中药', '医药', '保险', '证券', '燃气', '航运']

        cyc_sectors = [s for s in all_sectors if any(k in s['name'] for k in cyclical_keywords)]
        growth_sectors = [s for s in all_sectors if any(k in s['name'] for k in growth_keywords)]
        def_sectors = [s for s in all_sectors if any(k in s['name'] for k in defensive_keywords)]

        style_performance = {}
        style_flow = {}
        if cyc_sectors:
            style_performance['周期'] = round(sum(s['change_pct'] for s in cyc_sectors) / len(cyc_sectors), 2)
            style_flow['周期'] = round(sum(s['flow_net'] for s in cyc_sectors), 1)
        if growth_sectors:
            style_performance['成长'] = round(sum(s['change_pct'] for s in growth_sectors) / len(growth_sectors), 2)
            style_flow['成长'] = round(sum(s['flow_net'] for s in growth_sectors), 1)
        if def_sectors:
            style_performance['防御'] = round(sum(s['change_pct'] for s in def_sectors) / len(def_sectors), 2)
            style_flow['防御'] = round(sum(s['flow_net'] for s in def_sectors), 1)

        leading_style = max(style_performance, key=style_performance.get) if style_performance else '--'
        flow_leading_style = max(style_flow, key=style_flow.get) if style_flow else '--'

        # 量价背离/逆势吸筹检测（使用相对排名，不依赖绝对阈值）
        divergence_signals = []
        rising_sectors = [s for s in all_sectors if s['change_pct'] > 1.0]
        falling_sectors = [s for s in all_sectors if s['change_pct'] < -0.3]

        # 量价背离：涨得多但资金流出（按flow_net升序，取流出最多的）
        rising_by_flow = sorted(rising_sectors, key=lambda x: x['flow_net'])
        for s in rising_by_flow[:5]:
            if s['flow_net'] < 0:  # 确保确实是净流出
                divergence_signals.append({
                    'name': s['name'],
                    'type': '量价背离',
                    'signal': '上涨但主力出逃',
                    'change_pct': s['change_pct'],
                    'flow_net': s['flow_net'],
                    'risk_level': '高' if abs(s['flow_net']) > 0.2 else '中',
                })

        # 逆势吸筹：跌得多但资金流入（按flow_net降序，取流入最多的）
        falling_by_flow = sorted(falling_sectors, key=lambda x: x['flow_net'], reverse=True)
        for s in falling_by_flow[:5]:
            if s['flow_net'] > 0:  # 确保确实是净流入
                divergence_signals.append({
                    'name': s['name'],
                    'type': '逆势吸筹',
                    'signal': '下跌但主力进场',
                    'change_pct': s['change_pct'],
                    'flow_net': s['flow_net'],
                    'risk_level': '高' if abs(s['flow_net']) > 0.2 else '中',
                })

        divergence_signals.sort(key=lambda x: abs(x['flow_net']), reverse=True)
        warning_divergence = [d for d in divergence_signals if d['type'] == '量价背离'][:3]
        accumulation_divergence = [d for d in divergence_signals if d['type'] == '逆势吸筹'][:5]

        up_ratio = up_count / total_count
        avg_abs_change = sum(abs(s['change_pct']) for s in all_sectors) / total_count

        heat_score = 0
        if up_ratio > 0.7:
            heat_score += 35
        elif up_ratio > 0.6:
            heat_score += 28
        elif up_ratio > 0.5:
            heat_score += 20
        elif up_ratio > 0.4:
            heat_score += 12
        else:
            heat_score += 5

        if avg_abs_change > 3:
            heat_score += 25
        elif avg_abs_change > 2:
            heat_score += 20
        elif avg_abs_change > 1:
            heat_score += 15
        else:
            heat_score += 8

        total_inflow = sum(abs(s['flow_net']) for s in all_sectors)
        if total_inflow > 3000:
            heat_score += 20
        elif total_inflow > 1500:
            heat_score += 15
        else:
            heat_score += 8

        limit_up_count = sum(1 for s in all_sectors if s['change_pct'] >= 9.5)
        if limit_up_count > 3:
            heat_score += min(limit_up_count * 2, 10)

        heat_score = max(0, min(100, heat_score))

        inflow_sectors = [s for s in all_sectors if s['flow_net'] > 0]
        total_inflow_pos = sum(s['flow_net'] for s in inflow_sectors)
        top3_inflow = sorted(inflow_sectors, key=lambda x: x['flow_net'], reverse=True)[:3]
        concentration_ratio = round(sum(s['flow_net'] for s in top3_inflow) / max(1, total_inflow_pos) * 100, 1)

        advice_parts = []

        if leading_style == '周期':
            advice_parts.append('周期板块领涨，关注资源品和制造业')
        elif leading_style == '成长':
            advice_parts.append('科技成长占优，聚焦半导体和新能源')
        else:
            advice_parts.append('防御板块走强，建议配置消费和金融')

        if flow_leading_style != leading_style and style_flow.get(flow_leading_style, 0) > 50:
            advice_parts.append(f"资金正转向{flow_leading_style}板块，关注轮动机会")

        if heat_score > 75:
            advice_parts.append('市场过热，注意高位回调风险')
        elif heat_score < 30:
            advice_parts.append('市场偏冷，可逐步建仓优质标的')
        elif heat_score > 60:
            advice_parts.append('市场活跃，可适当加仓')

        if warning_divergence:
            names = [d['name'] for d in warning_divergence[:2]]
            advice_parts.append(f"{', '.join(names)}等板块主力出逃，谨慎追高")

        if accumulation_divergence:
            names = [d['name'] for d in accumulation_divergence[:3]]
            advice_parts.append(f"{', '.join(names)}等板块逆势吸筹，关注反弹机会")

        if concentration_ratio > 45:
            advice_parts.append('资金高度集中，跟随主力方向')
        elif concentration_ratio < 20:
            advice_parts.append('资金分散，建议均衡配置')

        if up_count > total_count * 0.7:
            advice_parts.append('市场普涨，注意高位回调风险')
        elif down_count > total_count * 0.7:
            advice_parts.append('市场普跌，关注超跌反弹机会')
        else:
            advice_parts.append('板块分化明显，聚焦资金流入方向')

        result = {
            'timestamp': now,
            'leading_style': leading_style,
            'style_performance': style_performance,
            'flow_leading_style': flow_leading_style,
            'style_flow': style_flow,
            'heat_score': heat_score,
            'warning_divergence': warning_divergence,
            'accumulation_divergence': accumulation_divergence,
            'concentration_ratio': concentration_ratio,
            'top_inflow_sectors': [{'name': s['name'], 'change_pct': s['change_pct'], 'flow_net': s['flow_net']} for s in top3_inflow],
            'advice': '；'.join(advice_parts),
        }
        self._set_market_cache('rotation', result)
        return result

    # ── 兼容旧API路由的方法别名 ───────────────────────────────
    def get_sentiment(self, date=None):
        return self.get_market_sentiment(date)

    def get_dashboard_combined(self, top: int = 30, force_refresh: bool = False) -> dict:
        """合并端点：资金流拆分 + THS热门榜，共享底层数据源。

        优化前：capitalFlow (~30s) + thsHotRank (~15s) = 2个独立请求，~45s
        优化后：一次拉取 THS 热点归因 + 资金流 + 腾讯报价，~20-25s

        Returns:
            {
                'timestamp': ...,
                'capital_flow_breakdown': {...},
                'ths_hot_rank': {'total', 'stocks'},
            }
        """
        cache_key = f'dashboard_combined:{top}'
        if not force_refresh:
            cached = self._get_market_cache(cache_key)
            if cached:
                return cached
        if not force_refresh and not is_trading_hours():
            stale = self._get_stale_cache(cache_key)
            if stale:
                return stale
        # SWR fallback：内存/Redis 都未命中时尝试 SQLite 旧数据+后台刷新
        swr_result = swr_cache(cache_key, NS_MARKET,
                            lambda: self._fetch_dashboard_combined_data(top),
                            self._MARKET_TTL)
        if swr_result is not None:
            return swr_result

        return self._fetch_dashboard_combined_data(top, force_refresh)

    def _fetch_dashboard_combined_data(self, top: int = 30, force_refresh: bool = False) -> dict:
        """获取合并看板数据核心逻辑（供SWR后台刷新和正常路径共用）"""
        cache_key = f'dashboard_combined:{top}'
        # 1. THS 热点归因（~73ms，被 hot_sectors 和 ths_hot_rank 共享）
        ths_items = THSHotSource.get_hot_reasons(page_size=200)

        # 2. 资金流数据（~30s，被 capitalFlow 和 ths_hot_rank 共享）
        capital_flow = {}
        try:
            capital_flow = THSCapitalFlowSource.get_top_capital_flows(force_refresh=force_refresh)
        except Exception as e:
            logger.debug(f"同花顺资金流获取失败: {e}")

        # 3. 腾讯财经补全实时价格（被 ths_hot_rank 使用）
        codes = [it.get('code', '') for it in ths_items if it.get('code')]
        quotes_map = {}
        if codes:
            try:
                from app.core.data_sources import TencentSource as _TS
                quotes_map = _TS.get_quotes(codes)
            except Exception:
                pass

        # 4. 构建热门榜（复用 ths_items + capital_flow + quotes_map）
        hot_items = []
        for it in ths_items:
            code = it.get('code', '')
            name = it.get('name', '')
            pct = float(it.get('pct_change') or it.get('zhangfu') or 0)
            reason = it.get('reason') or ''
            tag = it.get('tag') or ''
            ths_rank = int(it.get('rank') or it.get('rd') or 0)

            q = quotes_map.get(code) or {}
            if q and q.get('price', 0) > 0:
                pct = float(q.get('change_pct', pct) or pct)
                price = float(q.get('price', 0) or 0)
            else:
                price = float(it.get('price') or it.get('close') or 0)

            score = 0.0
            if reason:
                score += 50
            if tag:
                score += 10
            score += max(-30, min(30, pct * 8))
            score += max(0, (200 - ths_rank) / 4)

            hot_items.append({
                'code': code,
                'name': name,
                'pct_change': round(pct, 2),
                'price': round(price, 2),
                'reason': reason,
                'tag': tag,
                'ths_rank': ths_rank,
                'composite_score': round(score, 1),
                'source': 'ths_hot+tencent',
            })

        hot_items.sort(key=lambda x: x['composite_score'], reverse=True)

        result = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'capital_flow_breakdown': capital_flow,
            'ths_hot_rank': {
                'total': len(hot_items),
                'stocks': hot_items[:top],
            },
        }
        self._set_market_cache(cache_key, result)
        return result

    def _fetch_market_dashboard_data(self, force_refresh: bool = False) -> dict:
        """获取市场看板聚合数据核心逻辑（供SWR后台刷新和正常路径共用）"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 子任务失败时的空结构体 fallback，避免返回 None 导致前端判断异常
        _EMPTY = {
            'sentiment_quick': {'score': 0, 'signal': '--', 'indices': {}, 'breadth': {}, 'money_flow': {}, 'limit_up_down': {}, 'volume': {}},
            'sectors_industry': {'sectors': []},
            'sectors_concept': {'sectors': []},
            'hot_sectors': {'sectors': []},
            'rotation_signals': {'leading_style': '', 'heat_score': 50, 'advice': ''},
            'indices_kline': {'indices': []},
            'northbound_flow': {'summary': {}, 'minute_data': []},
            'limit_up_pool': {'total_stocks': 0, 'stocks': [], 'max_continuous': 0, 'total_sealed_yi': 0},
            'dashboard_combined': {'capital_flow_breakdown': {}, 'ths_hot_rank': {'total': 0, 'stocks': []}},
        }

        tasks = {
            'sentiment_quick': lambda: self.get_market_sentiment(force_refresh=force_refresh, include_flow=False),
            'sectors_industry': lambda: self.get_sectors(sector_type='industry', top=30, force_refresh=force_refresh),
            'sectors_concept': lambda: self.get_sectors(sector_type='concept', top=30, force_refresh=force_refresh),
            'hot_sectors': lambda: self.get_hot_sectors(top=10, force_refresh=force_refresh),
            'rotation_signals': lambda: self.get_rotation_signals(force_refresh=force_refresh),
            'indices_kline': lambda: self.get_indices_with_kline(
                ['000001', '399001', '399006', '000300', '000016', '000688', '000905', '399005', '000852'], 30
            ),
            'northbound_flow': lambda: self.get_northbound_flow(),
            'limit_up_pool': lambda: self.get_limit_up_pool(force_refresh=force_refresh),
            'dashboard_combined': lambda: self.get_dashboard_combined(top=30, force_refresh=force_refresh),
        }

        result = {}
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="dashboard") as executor:
            futures = {executor.submit(fn): name for name, fn in tasks.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    val = future.result()
                    result[name] = val
                    logger.info(f"看板聚合[{name}]成功: {type(val).__name__}")
                except Exception as e:
                    import traceback
                    logger.error(f"看板聚合[{name}]失败: {e}\n{traceback.format_exc()}")
                    result[name] = _EMPTY.get(name, {})

        result['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return result

    def get_market_dashboard(self, force_refresh: bool = False) -> dict:
        """市场看板完整聚合接口：一次性返回首页所有数据。

        优化前：8个独立请求（sentiment + sectors + hot + signals + indices + northbound + limitUp + combined）
        优化后：1个请求，并发拉取，总耗时 = 最慢的那个接口

        Returns:
            {
                'sentiment_quick': {...},        # 市场情绪（不含资金流）
                'sectors_industry': {...},       # 行业板块
                'sectors_concept': {...},        # 概念板块
                'hot_sectors': {...},            # 热门板块
                'rotation_signals': {...},       # 轮动信号
                'indices_kline': {...},          # 指数K线
                'northbound_flow': {...},        # 北向资金
                'limit_up_pool': {...},          # 涨停板池
                'dashboard_combined': {...},     # 资金流 + THS热门榜
                'timestamp': '...',
            }
        """
        cache_key = 'market_dashboard:v1'
        if not force_refresh:
            cached = self._get_market_cache(cache_key)
            if cached:
                return cached
        if not force_refresh and not is_trading_hours():
            stale = self._get_stale_cache(cache_key)
            if stale:
                return stale
        # SWR fallback：内存/Redis 都未命中时尝试 SQLite 旧数据+后台刷新
        swr_result = swr_cache(cache_key, NS_MARKET,
                               lambda: self._fetch_market_dashboard_data(force_refresh), self._MARKET_TTL)
        if swr_result is not None:
            return swr_result

        result = self._fetch_market_dashboard_data(force_refresh)
        self._set_market_cache(cache_key, result)
        return result

    def get_sector_overview(self, sector_type='industry', top=12, force_refresh: bool = False):
        return self.get_sectors(sector_type, top, force_refresh=force_refresh)

    def get_sector_flow(self, sector_type='industry', top=10):
        data = self.get_sectors(sector_type, top=top * 2)
        sectors = sorted(data.get('sectors', []), key=lambda x: x['flow_net'], reverse=True)
        return {'timestamp': data['timestamp'], 'sectors': sectors[:top]}

    def get_sector_strength(self, period=20):
        data = self.get_sectors(sector_type='industry', top=15)
        return {'timestamp': data['timestamp'], 'sectors': data.get('sectors', [])}

    def get_daily_report(self, style='detailed', fmt='json'):
        sentiment = self.get_market_sentiment()
        sectors = self.get_sectors(sector_type='industry', top=10)
        hot = self.get_hot_sectors(top=8)
        signals = self.get_rotation_signals()

        report = {
            'timestamp': sentiment['timestamp'],
            'style': style,
            'summary': f"市场情绪{sentiment['signal']}（评分{sentiment['score']}），"
                       f"涨{sentiment['breadth']['up']}/跌{sentiment['breadth']['down']}，"
                       f"成交额{sentiment['volume']['total_billion']:.0f}亿",
            'sentiment': sentiment,
            'sectors': sectors,
            'hot_concepts': hot,
            'signals': signals,
        }

        if fmt == 'markdown':
            s = sentiment
            b = s.get('breadth', {})
            v = s.get('volume', {})
            ld = s.get('limit_up_down', {})
            mf = s.get('money_flow', {})

            lines = []
            lines.append(f"# 市场日报 - {s['timestamp']}")
            lines.append("")
            lines.append(f"## 情绪评分: {s['score']} ({s['signal']})")
            lines.append(f"- 涨跌家数: 涨{b.get('up', 0)} / 跌{b.get('down', 0)} / 平{b.get('flat', 0)} (共{b.get('total', 0)})")
            lines.append(f"- 成交额: {v.get('total_billion', 0):.0f}亿 ({v.get('signal', '--')})")
            lines.append(f"- 涨停: {ld.get('limit_up', 0)} / 跌停: {ld.get('limit_down', 0)}")
            if mf.get('net_inflow_billion'):
                lines.append(f"- 主力资金净流入: {mf['net_inflow_billion']:.1f}亿 ({mf.get('signal', '--')})")
            lines.append("")

            lines.append("## 大盘指数")
            for key in ['shanghai', 'shenzhen', 'chiNext', 'hs300']:
                idx = s.get('indices', {}).get(key)
                if idx:
                    cpct = idx.get('change_pct', 0)
                    sign = '+' if cpct >= 0 else ''
                    lines.append(f"- **{idx['name']}**: {idx['price']} ({sign}{cpct:.2f}%)")
            lines.append("")

            sector_list = sectors.get('sectors', [])
            if sector_list:
                lines.append("## 领涨行业板块")
                for sec in sorted(sector_list, key=lambda x: x.get('change_pct', 0), reverse=True)[:5]:
                    cpct = sec.get('change_pct', 0)
                    sign = '+' if cpct >= 0 else ''
                    flow = sec.get('flow_net', 0)
                    lines.append(f"- **{sec['name']}**: {sign}{cpct:.2f}% (资金{flow:+.1f}亿)")
                lines.append("")

            hot_list = hot.get('concepts', []) if isinstance(hot, dict) else []
            if hot_list:
                lines.append("## 热点概念")
                for h in sorted(hot_list, key=lambda x: x.get('change_pct', 0), reverse=True)[:5]:
                    cpct = h.get('change_pct', 0)
                    sign = '+' if cpct >= 0 else ''
                    lines.append(f"- **{h['name']}**: {sign}{cpct:.2f}%")
                lines.append("")

            sig = signals if isinstance(signals, dict) else {}
            if sig:
                lines.append("## 板块轮动信号")
                if sig.get('style_preference'):
                    lines.append(f"- 风格偏好: {sig['style_preference']}")
                if sig.get('cycle_phase'):
                    lines.append(f"- 周期阶段: {sig['cycle_phase']}")
                lines.append("")

            return {'report': '\n'.join(lines), 'format': 'markdown'}

        return report

def pd_not_nan(val) -> bool:
    if val is None:
        return False
    try:
        import math
        return not math.isnan(float(val))
    except (ValueError, TypeError):
        return False

