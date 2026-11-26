"""东财数据中心 — 龙虎榜/融资融券/大宗交易等数据源（干净实现）

此模块为 data_sources.py 中 EastMoneyDataCenter 类的独立实现，
不依赖损坏的父模块。直接调用东财 datacenter API。
"""
import time
import random
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ===== 东财请求基础设施 =====
_EM_SESSION = requests.Session()
_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.eastmoney.com/",
}

# 连接级自动重试（降低频率，增加退避时间）
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _em_adapter = HTTPAdapter(max_retries=Retry(
        total=2, connect=2, backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    _EM_SESSION.mount("https://", _em_adapter)
    _EM_SESSION.mount("http://", _em_adapter)
except Exception:
    pass

# 降低 urllib3 连接断开日志级别（避免刷屏）
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    # 将 connectionpool 的 WARNING 降为 DEBUG
    logging.getLogger("urllib3.connectionpool").setLevel(logging.DEBUG)
except Exception:
    pass

_EM_MIN_INTERVAL = 2.0
EM_MIN_INTERVAL = _EM_MIN_INTERVAL  # 向后兼容别名
_em_last_call = [0.0]
_em_lock = __import__('threading').Lock()


def _em_throttle():
    """东财请求节流（共享状态，GET/POST统一限流）"""
    with _em_lock:
        elapsed = time.time() - _em_last_call[0]
        if elapsed < _EM_MIN_INTERVAL:
            time.sleep(_EM_MIN_INTERVAL - elapsed + random.uniform(0.3, 0.8))
        _em_last_call[0] = time.time()


def _em_request(method: str, url: str, params=None, headers=None, timeout=20, **kwargs):
    """东财统一请求入口（GET/POST）：限流 + 会话复用 + 自动重试"""
    _em_throttle()

    merged_headers = dict(_EM_HEADERS)
    if headers:
        merged_headers.update(headers)

    for attempt in range(3):
        try:
            r = _EM_SESSION.request(method, url, params=params, headers=merged_headers, timeout=timeout, **kwargs)
            if r.status_code == 403:
                logger.warning(f"东财返回 403 (IP可能被风控): {url}")
                return r
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep((2 ** (attempt + 1)) + random.uniform(1, 2))
                continue
            return r
        except requests.exceptions.ConnectionError:
            if attempt < 2:
                time.sleep(min(3 ** (attempt + 1), 8) + random.uniform(0.5, 1.5))
                continue
            raise


def em_get_clean(url: str, params=None, headers=None, timeout=20):
    """东财统一GET请求入口：限流 + 会话复用"""
    return _em_request('GET', url, params=params, headers=headers, timeout=timeout)


def em_post(url: str, json=None, headers=None, timeout=20, **kwargs):
    """东财统一POST请求入口：限流 + 会话复用"""
    return _em_request('POST', url, json=json, headers=headers, timeout=timeout, **kwargs)


DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def query_datacenter(report_name: str, filter_str: str = "",
                     columns: str = "ALL", page_size: int = 50,
                     sort_columns: str = None, sort_types: str = "-1") -> list:
    """东财数据中心通用查询"""
    params = {
        "reportName": report_name,
        "columns": columns,
        "pageSize": page_size,
        "sortTypes": "-1",
        "sortColumns": "TRADE_DATE",
        "source": "WEB",
        "client": "WEB",
        "page": 1,
    }
    if filter_str:
        params["filter"] = filter_str
    if sort_columns:
        params["sortColumns"] = sort_columns
        params["sortTypes"] = sort_types or "-1"

    try:
        r = em_get_clean(DATACENTER_URL, params=params, timeout=20)
        resp = r.json()
        if not resp:
            return []
        result = resp.get("result") or {}
        return result.get("data") or []
    except Exception as e:
        logger.warning(f"EastMoney datacenter failed ({report_name}): {e}")
        return []


# ===== 龙虎榜数据 =====

def dragon_tiger_board(date: str, security_code: str = None) -> list:
    """龙虎榜明细查询
    
    date 格式: YYYY-MM-DD 或 YYYYMMDD
    security_code: 可选，6位股票代码
    """
    try:
        date_clean = date.replace("-", "")
        if len(date_clean) == 8:
            date_em = f"{date_clean[:4]}-{date_clean[4:6]}-{date_clean[6:8]}"
        else:
            date_em = date

        filter_parts = [f"(TRADE_DATE>='{date_em}')", f"(TRADE_DATE<='{date_em}')"]
        if security_code:
            filter_parts.append(f'(SECURITY_CODE="{security_code}")')
        filter_str = "".join(filter_parts)

        columns_list = (
            "SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLAIN,"
            "CLOSE_PRICE,CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,"
            "BILLBOARD_SELL_AMT,BILLBOARD_DEAL_AMT,ACCUM_AMOUNT,"
            "DEAL_NET_RATIO,DEAL_AMOUNT_RATIO,TURNOVERRATE,FREE_MARKET_CAP,"
            "EXPLANATION,D1_CLOSE_ADJCHRATE,D2_CLOSE_ADJCHRATE,"
            "D5_CLOSE_ADJCHRATE,D10_CLOSE_ADJCHRATE,SECURITY_TYPE_CODE"
        )

        result = query_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=filter_str, page_size=100,
            columns=columns_list,
            sort_columns="BILLBOARD_NET_AMT", sort_types="-1"
        )
        # 验证返回数据的日期是否匹配请求的日期
        if result:
            actual_date = str(result[0].get("TRADE_DATE", "")).replace("-", "").replace(" ", "")[:8]
            if actual_date == date_clean:
                return result
            logger.warning(f"龙虎榜API返回数据日期({actual_date})与请求({date_clean})不匹配，使用兜底查询")

        # 兜底: 获取最新数据本地过滤
        all_data = query_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str="", page_size=200,
            sort_columns="TRADE_DATE", sort_types="-1"
        )
        if not all_data:
            return []

        target = date_clean
        filtered = [d for d in all_data
                    if str(d.get("TRADE_DATE", "")).replace("-", "").replace(" ", "")[:8] == target]
        if security_code:
            filtered = [d for d in filtered if str(d.get("SECURITY_CODE", "")) == security_code]

        filtered.sort(key=lambda x: float(x.get("BILLBOARD_NET_AMT", 0) or 0), reverse=True)
        return filtered[:100]

    except Exception as e:
        logger.warning(f"龙虎榜数据获取失败 ({date}): {e}")
        return []


def dragon_tiger_board_range(start_date: str, end_date: str) -> list:
    """龙虎榜日期范围查询 — 按日期逐日查询并合并（datacenter API 不支持有效分页）"""
    try:
        columns_list = (
            "SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLAIN,"
            "CLOSE_PRICE,CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,"
            "BILLBOARD_SELL_AMT,BILLBOARD_DEAL_AMT,ACCUM_AMOUNT,"
            "DEAL_NET_RATIO,DEAL_AMOUNT_RATIO,TURNOVERRATE,FREE_MARKET_CAP,"
            "EXPLANATION,D1_CLOSE_ADJCHRATE,D2_CLOSE_ADJCHRATE,"
            "D5_CLOSE_ADJCHRATE,D10_CLOSE_ADJCHRATE,SECURITY_TYPE_CODE"
        )
        # 东财 datacenter filter 必须使用 YYYY-MM-DD 格式（带横线），不能传紧凑 YYYYMMDD
        def _to_em_date(d: str) -> str:
            d = d.replace("-", "")
            if len(d) == 8:
                return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            return d
        # 东财 datacenter 的 page 参数对 RPT_DAILYBILLBOARD_DETAILSNEW 不生效（所有 page 返回相同数据）
        # 改为按日期逐日查询，确保拉取全 10 个交易日的数据（D10 字段需要 ≥10 个交易日）
        start_dt = datetime.strptime(_to_em_date(start_date), '%Y-%m-%d')
        end_dt = datetime.strptime(_to_em_date(end_date), '%Y-%m-%d')
        all_data: list = []
        d = start_dt
        while d <= end_dt:
            date_str = d.strftime('%Y-%m-%d')
            params = {
                "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
                "columns": columns_list,
                "pageSize": 500,
                "sortTypes": "-1",
                "sortColumns": "TRADE_DATE",
                "source": "WEB",
                "client": "WEB",
                "page": 1,
                "filter": f"(TRADE_DATE>='{date_str}')(TRADE_DATE<='{date_str}')",
            }
            r = em_get_clean(DATACENTER_URL, params=params, timeout=20)
            resp = r.json() if r else {}
            result = resp.get("result") or {}
            day_data = result.get("data") or []
            all_data.extend(day_data)
            d += timedelta(days=1)
        return all_data
    except Exception as e:
        logger.warning(f"龙虎榜范围查询失败 ({start_date}~{end_date}): {e}")
        return []


def dragon_tiger_seats(code: str, trade_date: str = None, look_back: int = 30) -> dict:
    """龙虎榜席位明细 — 个股上榜记录+买卖席位TOP5+机构统计"""
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    start = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)
    start_str = start.strftime("%Y-%m-%d")

    # 1. 上榜记录（必须先获取，后续依赖latest_date）
    records_data = query_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start_str}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")",
        page_size=50, sort_columns="TRADE_DATE", sort_types="-1"
    )

    records = [{
        "date": str(r.get("TRADE_DATE", ""))[:10],
        "reason": r.get("EXPLANATION", ""),
        "net_buy_wan": round((r.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
        "turnover_pct": round(float(r.get("TURNOVERRATE") or 0), 2),
    } for r in records_data]

    # 2. 买卖席位TOP5（并行查询，减少串行等待）
    seats = {"buy": [], "sell": []}
    buy_data = []
    sell_data = []

    if records:
        latest_date = records[0]["date"]

        from concurrent.futures import ThreadPoolExecutor as _TP, wait as _wait, ALL_COMPLETED as _ALL

        def _query_buy():
            return query_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSBUY",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10, sort_columns="BUY", sort_types="-1"
            )

        def _query_sell():
            return query_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSSELL",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10, sort_columns="SELL", sort_types="-1"
            )

        with _TP(max_workers=2) as executor:
            f_buy = executor.submit(_query_buy)
            f_sell = executor.submit(_query_sell)
            _wait([f_buy, f_sell], return_when=_ALL)
            buy_data = f_buy.result() or []
            sell_data = f_sell.result() or []

        for r in (buy_data or [])[:5]:
            seats["buy"].append({
                "name": r.get("OPERATEDEPT_NAME", ""),
                "buy_wan": round((r.get("BUY") or 0) / 10000, 1),
                "sell_wan": round((r.get("SELL") or 0) / 10000, 1),
                "net_wan": round((r.get("NET") or 0) / 10000, 1),
            })

        for r in (sell_data or [])[:5]:
            seats["sell"].append({
                "name": r.get("OPERATEDEPT_NAME", ""),
                "buy_wan": round((r.get("BUY") or 0) / 10000, 1),
                "sell_wan": round((r.get("SELL") or 0) / 10000, 1),
                "net_wan": round((r.get("NET") or 0) / 10000, 1),
            })

    # 3. 机构统计
    inst_buy = sum((r.get("BUY") or 0) for r in (buy_data or []) if str(r.get("OPERATEDEPT_CODE", "")) == "0")
    inst_sell = sum((r.get("SELL") or 0) for r in (sell_data or []) if str(r.get("OPERATEDEPT_CODE", "")) == "0")

    return {
        "records": records,
        "seats": seats,
        "institution": {
            "buy_wan": round(inst_buy / 10000, 1),
            "sell_wan": round(inst_sell / 10000, 1),
            "net_wan": round((inst_buy - inst_sell) / 10000, 1),
        }
    }


# ===== 融资融券/大宗交易/股东户数/分红 =====

def margin_trading(code: str, page_size: int = 30) -> list:
    """融资融券明细"""
    return query_datacenter(
        "RPTA_WEB_RZRQ_GGMX",
        filter_str=f'(SCODE="{code}")', page_size=page_size,
        sort_columns="DATE", sort_types="-1"
    )


def block_trade(code: str, page_size: int = 20) -> list:
    """大宗交易"""
    return query_datacenter(
        "RPT_DATA_BLOCKTRADE",
        filter_str=f'(SECURITY_CODE="{code}")', page_size=page_size,
        sort_columns="TRADE_DATE", sort_types="-1"
    )


def holder_num_change(code: str, page_size: int = 10) -> list:
    """股东户数变化"""
    return query_datacenter(
        "RPT_HOLDERNUMLATEST",
        filter_str=f'(SECURITY_CODE="{code}")', page_size=page_size,
        sort_columns="END_DATE", sort_types="-1"
    )


def dividend_history(code: str, page_size: int = 20) -> list:
    """分红送转历史"""
    return query_datacenter(
        "RPT_SHAREBONUS_DET",
        filter_str=f'(SECURITY_CODE="{code}")', page_size=page_size,
        sort_columns="EX_DIVIDEND_DATE", sort_types="-1"
    )


def lockup_expiry(code: str, trade_date: str = None, forward_days: int = 90) -> dict:
    """限售解禁日历"""
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    end_date = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)
    end_str = end_date.strftime("%Y-%m-%d")

    all_data = query_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=50, sort_columns="PUBLISH_DATE", sort_types="-1"
    )

    history = []
    upcoming = []
    for d in all_data:
        pub_date = str(d.get("PUBLISH_DATE", ""))[:10]
        if pub_date <= trade_date:
            history.append(d)
        elif pub_date <= end_str:
            upcoming.append(d)

    return {"history": history, "upcoming": upcoming}


# ===== 兼容别名 =====

# em_get 是 em_get_clean 的别名，保持向后兼容
em_get = em_get_clean
em_get_datacenter = em_get_clean
# em_post: POST 请求统一入口（限流 + 会话复用）


def call_with_timeout(func, timeout=10, default=None, *args, **kwargs):
    """跨平台带超时的函数调用"""
    import threading
    result = [None]
    exception = [None]

    def _target():
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            exception[0] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        logger.debug(f"call_with_timeout 超时 ({func.__name__}, {timeout}s)")
        return default
    if exception[0] is not None:
        raise exception[0]
    return result[0]


class EastMoneyDataCenterClean:
    """干净实现的东财数据中心，与原 EastMoneyDataCenter 接口兼容"""

    @classmethod
    def query(cls, report_name, filter_str="", columns="ALL", page_size=50,
              sort_columns=None, sort_types="-1"):
        return query_datacenter(report_name, filter_str, columns, page_size,
                                sort_columns, sort_types)

    @classmethod
    def dragon_tiger_board(cls, date, security_code=None):
        return dragon_tiger_board(date, security_code)

    @classmethod
    def dragon_tiger_board_range(cls, start_date, end_date):
        return dragon_tiger_board_range(start_date, end_date)

    @classmethod
    def dragon_tiger_seats(cls, code, trade_date=None, look_back=30):
        return dragon_tiger_seats(code, trade_date, look_back)

    @classmethod
    def margin_trading(cls, code, page_size=30):
        return margin_trading(code, page_size)

    @classmethod
    def block_trade(cls, code, page_size=20):
        return block_trade(code, page_size)

    @classmethod
    def holder_num_change(cls, code, page_size=10):
        return holder_num_change(code, page_size)

    @classmethod
    def dividend_history(cls, code, page_size=20):
        return dividend_history(code, page_size)

    @classmethod
    def lockup_expiry(cls, code, trade_date=None, forward_days=90):
        return lockup_expiry(code, trade_date, forward_days)


# EastMoneyDataCenter 是 EastMoneyDataCenterClean 的别名
EastMoneyDataCenter = EastMoneyDataCenterClean


# ===== TencentSource =====

class TencentSource:
    """腾讯财经数据源 — HTTP不封IP"""

    _ALL_STOCK_CODES = None
    _ALL_STOCK_CODES_TIME = 0.0
    _STOCK_LIST_TTL = 3600
    _STOCK_LIST_LOCK = __import__('threading').Lock()
    _FULL_MARKET_CACHE = None
    _FULL_MARKET_TIME = 0.0
    _FULL_MARKET_TTL = 300  # 5分钟，避免长时间缓存过期数据
    _FULL_MARKET_LOCK = __import__('threading').Lock()
    _FILE_CACHE_DIR = __import__("os").path.expanduser("~/.tradingagents/cache")
    _FILE_CACHE_PATH = None
    _FILE_CACHE_TTL = 3600  # 缩短至1小时，避免加载过时数据
    _FILE_CACHE_WRITE_LOCK = __import__('threading').Lock()

    @classmethod
    def _get_file_cache_path(cls):
        if cls._FILE_CACHE_PATH is None:
            import os
            os.makedirs(cls._FILE_CACHE_DIR, exist_ok=True)
            cls._FILE_CACHE_PATH = os.path.join(cls._FILE_CACHE_DIR, "tencent_full_market.json")
        return cls._FILE_CACHE_PATH

    @classmethod
    def _load_file_cache(cls):
        import json
        path = cls._get_file_cache_path()
        try:
            if __import__("os").path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                saved_time = data.get('_timestamp', 0)
                if time.time() - saved_time < cls._FILE_CACHE_TTL:
                    records = data.get('data', [])
                    return records
        except Exception:
            pass
        return None

    @classmethod
    def _save_file_cache(cls, data):
        import json
        path = cls._get_file_cache_path()
        try:
            cache_obj = {'_timestamp': time.time(), 'data': data}
            tmp_path = path + '.tmp'
            with cls._FILE_CACHE_WRITE_LOCK:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(cache_obj, f, ensure_ascii=False)
                __import__("os").replace(tmp_path, path)
        except Exception:
            pass

    @staticmethod
    def _prefix(code):
        if code in ("000001", "000016", "000300", "000688", "000905", "000852"):
            return f"sh{code}"
        if code.startswith(("6", "9")):
            return f"sh{code}"
        elif code.startswith("8") or code.startswith("4"):
            return f"bj{code}"
        return f"sz{code}"

    @classmethod
    def _parse_tencent_line(cls, line):
        if "~" not in line or "=" not in line:
            return None
        p = line.split("~")
        if len(p) < 53:
            return None

        def _f(idx, default=0.0):
            try:
                return float(p[idx]) if idx < len(p) and p[idx] else default
            except (ValueError, IndexError):
                return default

        code = p[2]
        return {
            "code": code, "name": p[1].strip(), "price": _f(3),
            "last_close": _f(4), "open": _f(5), "change_pct": _f(32),
            "high": _f(33), "low": _f(34), "amount_wan": _f(37),
            "turnover_pct": _f(38), "pe_ttm": _f(39), "amplitude_pct": _f(43),
            "mcap_yi": _f(44), "float_mcap_yi": _f(45), "pb": _f(46),
            "limit_up": _f(47), "limit_down": _f(48), "vol_ratio": _f(49),
            "pe_static": _f(52),
        }

    @classmethod
    def get_quotes(cls, codes):
        """批量获取实时行情（腾讯GBK编码），分批请求避免URL过长超时"""
        if not codes:
            return {}

        prefixed = [cls._prefix(c) for c in codes]
        batch_size = 80  # 每批最多80个，超过会导致URL过长/超时
        result = {}

        for i in range(0, len(prefixed), batch_size):
            batch = prefixed[i:i + batch_size]
            for attempt in range(3):
                try:
                    r = requests.get(f"http://qt.gtimg.cn/q={','.join(batch)}",
                                   headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                    text = r.content.decode("gbk")
                    for line in text.strip().split("\n"):
                        parsed = cls._parse_tencent_line(line)
                        if parsed:
                            result[parsed["code"]] = parsed
                    break  # 成功则跳出重试循环
                except Exception as e:
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    logger.warning(f"Tencent quotes批次失败 ({i}-{i+len(batch)}): {e}")

        return result

    @classmethod
    def _get_all_stock_codes(cls):
        now = time.time()
        if cls._ALL_STOCK_CODES and (now - cls._ALL_STOCK_CODES_TIME) < cls._STOCK_LIST_TTL:
            return cls._ALL_STOCK_CODES

        with cls._STOCK_LIST_LOCK:
            # 双重检查锁，避免重复请求
            if cls._ALL_STOCK_CODES and (time.time() - cls._ALL_STOCK_CODES_TIME) < cls._STOCK_LIST_TTL:
                return cls._ALL_STOCK_CODES

            try:
                from akshare.stock.stock_info import stock_info_a_code_name
                df = stock_info_a_code_name()
                if df is not None and len(df) > 0:
                    codes = df['code'].astype(str).tolist()
                    codes = [c.zfill(6) for c in codes if len(c) == 6]
                    cls._ALL_STOCK_CODES = codes
                    cls._ALL_STOCK_CODES_TIME = now
                    return codes
            except Exception:
                pass

            # Fallback
            codes = []
            for i in range(600000, 602000): codes.append(str(i))
            for i in range(603000, 606000): codes.append(str(i))
            for i in range(688000, 690000): codes.append(str(i))
            for i in range(1, 3000): codes.append(f"{i:06d}")
            for i in range(300000, 302000): codes.append(str(i))
            for i in range(830000, 836000): codes.append(str(i))
            for i in range(870000, 873000): codes.append(str(i))
            for i in range(430000, 433000): codes.append(str(i))
            cls._ALL_STOCK_CODES = codes
            cls._ALL_STOCK_CODES_TIME = now
            return codes

    @classmethod
    def get_full_market(cls, allow_stale=True):
        """获取全市场行情，并发拉取提升性能"""
        now = time.time()
        if cls._FULL_MARKET_CACHE and (now - cls._FULL_MARKET_TIME) < cls._FULL_MARKET_TTL:
            return cls._FULL_MARKET_CACHE

        # 文件缓存仅在锁外预加载，不阻塞主流程
        stale_data = None
        if allow_stale and cls._FILE_CACHE_PATH is not None:
            file_data = cls._load_file_cache()
            if file_data:
                stale_data = file_data

        with cls._FULL_MARKET_LOCK:
            now = time.time()
            if cls._FULL_MARKET_CACHE and (now - cls._FULL_MARKET_TIME) < cls._FULL_MARKET_TTL:
                return cls._FULL_MARKET_CACHE

            all_codes = cls._get_all_stock_codes()
            exclude_keywords = {"指数", "ETF", "LOF", "基金"}
            exclude_codes = {"000001", "000300", "000016", "000905", "000688",
                            "399001", "399006", "399005", "399106"}

            result = []
            # 腾讯接口 URL 长度限制约 8000 字符，每只股票约 9 字符，batch_size=800 安全
            batch_size = 800
            batches = [all_codes[i:i + batch_size] for i in range(0, len(all_codes), batch_size)]

            # 并发拉取多个批次（3 个 worker 避免腾讯限流）
            from concurrent.futures import ThreadPoolExecutor as _TP, as_completed as _as_completed
            with _TP(max_workers=3) as executor:
                futures = {executor.submit(cls.get_quotes, batch): idx for idx, batch in enumerate(batches)}
                sorted_results = []
                for future in _as_completed(futures):
                    try:
                        quotes = future.result(timeout=15)
                        sorted_results.append((futures[future], quotes))
                    except Exception as e:
                        logger.debug(f"全市场批次获取失败: {e}")

            # 按原始顺序合并结果
            for idx, quotes in sorted(sorted_results, key=lambda x: x[0]):
                if not quotes:
                    continue
                for code, data in quotes.items():
                    name = data.get("name", "")
                    if code in exclude_codes or any(kw in name for kw in exclude_keywords):
                        continue
                    price = data.get("price", 0) or 0
                    mcap = data.get("mcap_yi", 0) or 0
                    if price <= 0 or mcap <= 0 or mcap > 500000:
                        continue
                    item = {
                        "f12": code, "f14": name, "f2": price,
                        "f3": data.get("change_pct", 0) or 0,
                        "f4": round((data.get("change_pct", 0) or 0) * (data.get("last_close", 0) or 0) / 100, 2),
                        "f5": data.get("open", 0) or 0, "f6": data.get("high", 0) or 0,
                        "f7": data.get("low", 0) or 0, "f8": data.get("vol_ratio", 0) or 0,
                        "f10": (data.get("amount_wan", 0) or 0) * 10000,
                        "f15": data.get("turnover_pct", 0) or 0,
                        "f16": data.get("pe_ttm", 0) or 0, "f17": data.get("pb", 0) or 0,
                        "f18": data.get("amplitude_pct", 0) or 0,
                        "f20": mcap * 1e8, "f21": (data.get("float_mcap_yi", 0) or 0) * 1e8,
                        "f62": 0, "f66": 0, "f69": 0, "f72": 0, "f75": 0,
                        "f78": data.get("limit_up", 0) or 0,
                        "f81": data.get("limit_down", 0) or 0, "f84": 0, "f87": 0,
                    }
                    result.append(item)

            if result:
                cls._FULL_MARKET_CACHE = result
                cls._FULL_MARKET_TIME = time.time()
                import threading as _threading
                _threading.Thread(target=cls._save_file_cache, args=(result,), daemon=True).start()
            elif stale_data:
                # 全量拉取失败，返回过期数据（标记）
                cls._FULL_MARKET_CACHE = stale_data
                cls._FULL_MARKET_TIME = now
                logger.warning("全市场拉取失败，使用文件缓存（可能过时）")

        return result or (stale_data if allow_stale else [])

    @classmethod
    def get_stock_info(cls, code):
        quotes = cls.get_quotes([code])
        if not quotes or code not in quotes:
            return {}
        data = quotes[code]
        return {
            "f129": code, "f140": data["name"], "f43": data["price"],
            "f44": data["last_close"], "f45": data["open"], "f46": data["high"],
            "f47": data["low"], "f48": data["change_pct"],
            "f50": data["mcap_yi"] * 1e8 / data["price"] if data["price"] > 0 else 0,
            "f51": data["float_mcap_yi"] * 1e8 / data["price"] if data["price"] > 0 else 0,
            "f57": "", "f58": "", "f60": "",
            "f88": data["pe_ttm"], "f100": data["pb"],
            "f101": data["turnover_pct"], "f102": data["amount_wan"] * 10000,
            "f103": data["vol_ratio"], "f104": data["amplitude_pct"],
            "f105": data["limit_up"], "f106": data["limit_down"],
            "f116": data["mcap_yi"] * 1e8, "f117": data["float_mcap_yi"] * 1e8,
        }

    @classmethod
    def get_fund_flow_rank(cls, indicator="今日"):
        full_data = cls.get_full_market()
        if not full_data:
            return []
        result = []
        for item in full_data:
            amount = float(item.get("f10", 0) or 0)
            turnover = float(item.get("f15", 0) or 0)
            change_pct = float(item.get("f3", 0) or 0)
            main_net_inflow = amount * change_pct / 100 if amount > 0 and change_pct != 0 else 0
            result.append({
                "代码": str(item.get("f12", "")), "名称": item.get("f14", ""),
                "最新价": item.get("f2", 0), "涨跌幅": change_pct,
                "成交额": amount, "换手率": turnover,
                "主力净流入": main_net_inflow,
                "主力净流入占比": round(change_pct * turnover / 100, 4) if turnover > 0 else 0,
            })
        result.sort(key=lambda x: x.get("主力净流入", 0) or 0, reverse=True)
        return result

    @classmethod
    def get_market_breadth(cls):
        full_data = cls.get_full_market()
        up = down = flat = limit_up_count = limit_down_count = 0
        total_amount_yi = 0.0
        for row in full_data:
            f3 = float(row.get('f3', 0) or 0)
            f2 = float(row.get('f2', 0) or 0)
            total_amount_yi += float(row.get('f10', 0) or 0) / 1e8
            if f2 > 0:
                if f3 > 0: up += 1
                elif f3 < 0: down += 1
                else: flat += 1
            lup = float(row.get('f78', 0) or 0)
            ldn = float(row.get('f81', 0) or 0)
            # 容差0.5%：精确匹配涨跌停价，覆盖±5%/±10%/±20%/±30%不同幅度
            if lup > 0 and abs(f2 - lup) / lup < 0.005: limit_up_count += 1
            elif ldn > 0 and abs(f2 - ldn) / ldn < 0.005: limit_down_count += 1
        return {
            'up': up, 'down': down, 'flat': flat, 'total': len(full_data),
            'limit_up': limit_up_count, 'limit_down': limit_down_count,
            'total_amount_yi': round(total_amount_yi, 0), 'source': 'tencent',
        }


# ===== EastMoneyZTPool =====

class EastMoneyZTPool:
    """涨跌停池 — 优先东财 push2（字段完整），THS/腾讯兜底"""
    _pool_cache = {}  # OrderedDict LRU淘汰, max 10 entries
    _cache_ttl = 180
    _POOL_CACHE_LOCK = __import__('threading').Lock()
    _MAX_POOL_CACHE = 10
    # ZT/DT池降级时共享全市场快照，避免重复拉取
    _tencent_pool_cache = None
    _tencent_pool_time = 0.0
    _TENCENT_POOL_TTL = 300  # 5分钟

    @staticmethod
    def _fmt_time(val):
        """将数字时间格式化为 HH:MM:SS，如 92500 → 09:25:00"""
        try:
            s = str(int(val or 0)).zfill(6)
            return f"{s[:2]}:{s[2:4]}:{s[4:6]}"
        except (ValueError, TypeError):
            return ""

    @classmethod
    def _get_cached_pool(cls, cache_key, data):
        """缓存管理，LRU淘汰过期条目"""
        with cls._POOL_CACHE_LOCK:
            # 清理过期条目（超过TTL的删除）
            now = time.time()
            expired_keys = [k for k, v in cls._pool_cache.items() if now - v['timestamp'] > cls._cache_ttl * 3]
            for k in expired_keys:
                del cls._pool_cache[k]

            cached = cls._pool_cache.get(cache_key)
            if cached and (now - cached['timestamp']) < cls._cache_ttl:
                return cached['data']

            # 写入新数据，LRU淘汰
            if data is not None:
                cls._pool_cache[cache_key] = {'data': data, 'timestamp': now}
                while len(cls._pool_cache) > cls._MAX_POOL_CACHE:
                    cls._pool_cache.popitem(last=False)

        return data

    @classmethod
    def _fetch_em_push2_pool(cls, pool_type, date_str=None, page_size=200):
        """
        从东财 push2 接口获取涨跌停/炸板池
        pool_type: 'zt' / 'zb' / 'dt'
        """
        from app.core.data_sources_clean import em_get
        
        url_map = {
            'zt': "https://push2ex.eastmoney.com/getTopicZTPool",
            'zb': "https://push2ex.eastmoney.com/getTopicZBPool",
            'dt': "https://push2ex.eastmoney.com/getTopicDTPool",
        }
        url = url_map.get(pool_type)
        if not url:
            return []
        
        if not date_str:
            date_str = time.strftime("%Y%m%d")
        # 去掉日期中的横杠
        date_str = date_str.replace("-", "")
        
        params = {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt",
            "Pageindex": "0",
            "pagesize": str(page_size),
            "sort": "fbt:asc" if pool_type == 'zt' else "fund:desc",
            "date": date_str,
            "_": int(time.time() * 1000),
        }
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        }
        try:
            r = em_get(url, params=params, headers=headers, timeout=15)
            data = r.json()
            pool = (data.get('data') or {}).get('pool') or []
            return pool
        except Exception as e:
            logger.warning(f"东财{pool_type}池 push2 获取失败: {e}")
            return []

    @classmethod
    def _fetch_tencent_pool(cls):
        """从腾讯全市场数据筛选涨跌停（兜底用），共享快照避免重复拉取"""
        now = time.time()
        # 检查是否有缓存的全市场快照
        if cls._tencent_pool_cache and (now - cls._tencent_pool_time) < cls._TENCENT_POOL_TTL:
            full = cls._tencent_pool_cache
        else:
            full = TencentSource.get_full_market(allow_stale=True)
            if full:
                cls._tencent_pool_cache = full
                cls._tencent_pool_time = now

        try:
            if not full:
                return [], []
            zt_items, dt_items = [], []
            for row in full:
                f2 = float(row.get("f2", 0) or 0)
                lup = float(row.get("f78", 0) or 0)
                ldn = float(row.get("f81", 0) or 0)
                if lup > 0 and abs(f2 - lup) / lup < 0.005:
                    zt_items.append({
                        "c": row["f12"], "n": row["f14"],
                        "p": round(f2 * 1000), "zdp": float(row.get("f3", 0) or 0),
                        "jje": row.get("f10") or 0,
                    })
                elif ldn > 0 and abs(f2 - ldn) / ldn < 0.005:
                    dt_items.append({
                        "c": row["f12"], "n": row["f14"],
                        "p": round(f2 * 1000), "zdp": float(row.get("f3", 0) or 0),
                        "jje": row.get("f10") or 0,
                    })
            return zt_items, dt_items
        except Exception as e:
            logger.warning(f"腾讯涨跌停池获取失败: {e}")
            return [], []

    @classmethod
    def get_zt_pool(cls, date=None):
        """涨停池 — 优先东财 push2（字段完整），THS 备用，腾讯兜底"""
        # 将日期参数包含在缓存键中，避免不同日期共用缓存
        cache_key = f'zt_pool_{date}' if date else 'zt_pool'
        cached = cls._get_cached_pool(cache_key, None)
        if cached is not None:
            return cached
        # 1. 优先东财 push2（字段最完整：首次封板、封单、炸板次数、行业）
        try:
            em_data = cls._fetch_em_push2_pool('zt', date)
            if em_data:
                result = []
                for it in em_data:
                    zttj = it.get("zttj") or {}
                    result.append({
                        "c": str(it.get("c", "")),
                        "n": it.get("n", ""),
                        "p": it.get("p", 0),
                        "zdp": float(it.get("zdp", 0) or 0),
                        "jje": it.get("amount", 0),
                        "hs": float(it.get("hs", 0) or 0),
                        "lbc": it.get("lbc", 1),
                        "fbt": cls._fmt_time(it.get("fbt", 0)),
                        "lbt": cls._fmt_time(it.get("lbt", 0)),
                        "fund": it.get("fund", 0),
                        "zbc": it.get("zbc", 0),
                        "hybk": it.get("hybk", ""),
                        "zttj": {"days": zttj.get("days", 1), "ct": zttj.get("ct", 1)},
                    })
                logger.info(f"东财涨停池 (push2): {len(result)}条")
                return cls._get_cached_pool(cache_key, result)
        except Exception as e:
            logger.warning(f"东财涨停池 push2 获取失败: {e}")
        # 2. THS 备用
        try:
            ths_data = THSLimitUpPoolSource.get_limit_up_pool(page=1, page_size=200)
            if ths_data:
                result = [{
                    "c": it["code"], "n": it["name"],
                    "p": it["price"] * 1000,
                    "zdp": it["change_pct"],
                    "jje": it.get("amount_billion", 0) * 1e8,
                    "hs": it.get("turnover_pct", 0),
                    "lbc": it.get("continuous_limit_num", 1),
                    "fbt": str(it.get("first_time") or ""),
                    "lbt": str(it.get("last_time") or ""),
                    "fund": it.get("sealed_amount_yi", 0) * 1e8,
                    "zbc": it.get("open_count", 0),
                    "hybk": it.get("industry", ""),
                    "zttj": {"days": it.get("high_days", ""), "ct": it.get("continuous_limit_num", 1)},
                } for it in ths_data]
                logger.info(f"THS 涨停池: {len(result)}条")
                return cls._get_cached_pool(cache_key, result)
        except Exception as e:
            logger.warning(f"THS 涨停池获取失败: {e}")
        # 3. 腾讯兜底（字段较少）
        zt_items, _ = cls._fetch_tencent_pool()
        enriched = [{
            "c": it["c"], "n": it["n"], "p": it["p"], "zdp": it["zdp"],
            "jje": it.get("jje", 0), "hs": 0, "lbc": 1, "fbt": "", "lbt": "",
            "fund": 0, "zbc": 0, "hybk": "",
            "zttj": {"days": "", "ct": 1},
        } for it in zt_items]
        logger.info(f"腾讯涨停池兜底: {len(enriched)}条")
        return cls._get_cached_pool(cache_key, enriched)

    @classmethod
    def get_zb_pool(cls, date=None):
        """炸板池 — 优先东财 push2，THS 备用"""
        # 将日期参数包含在缓存键中，避免不同日期共用缓存
        cache_key = f'zb_pool_{date}' if date else 'zb_pool'
        cached = cls._get_cached_pool(cache_key, None)
        if cached is not None:
            return cached
        # 1. 优先东财 push2
        try:
            em_data = cls._fetch_em_push2_pool('zb', date)
            if em_data:
                result = []
                for it in em_data:
                    result.append({
                        "c": str(it.get("c", "")),
                        "n": it.get("n", ""),
                        "p": it.get("p", 0),
                        "zdp": float(it.get("zdp", 0) or 0),
                        "jje": it.get("amount", 0),
                        "hs": float(it.get("hs", 0) or 0),
                        "fbt": cls._fmt_time(it.get("fbt", 0)),
                        "zbc": it.get("zbc", 0),
                        "zf": float(it.get("zf", 0) or 0),
                        "ztp": it.get("ztp", 0),
                        "hybk": it.get("hybk", ""),
                    })
                logger.info(f"东财炸板池 (push2): {len(result)}条")
                return cls._get_cached_pool(cache_key, result)
        except Exception as e:
            logger.warning(f"东财炸板池 push2 获取失败: {e}")
        # 2. THS 备用
        try:
            ths_data = THSLimitUpPoolSource.get_limit_up_pool(page=1, page_size=200)
            zb_items = [it for it in ths_data if it.get("pattern") == "开板"]
            if zb_items:
                result = [{
                    "c": it["code"], "n": it["name"],
                    "p": it["price"] * 1000,
                    "zdp": it["change_pct"],
                    "jje": it.get("amount_billion", 0) * 1e8,
                    "hs": it.get("turnover_pct", 0),
                    "fbt": str(it.get("first_time") or ""),
                    "zbc": it.get("open_count", 0),
                    "zf": 0,
                    "ztp": 0,
                    "hybk": it.get("industry", ""),
                } for it in zb_items]
                logger.info(f"THS 炸板池: {len(result)}条")
                return cls._get_cached_pool(cache_key, result)
        except Exception as e:
            logger.warning(f"THS 炸板池获取失败: {e}")
        return []

    @classmethod
    def get_dt_pool(cls, date=None):
        """跌停池 — 优先东财 push2（字段完整），腾讯兜底"""
        # 将日期参数包含在缓存键中，避免不同日期共用缓存
        cache_key = f'dt_pool_{date}' if date else 'dt_pool'
        cached = cls._get_cached_pool(cache_key, None)
        if cached is not None:
            return cached
        # 1. 优先东财 push2（字段完整：封单、连续跌停、开板次数、行业）
        try:
            em_data = cls._fetch_em_push2_pool('dt', date)
            if em_data:
                result = []
                for it in em_data:
                    result.append({
                        "c": str(it.get("c", "")),
                        "n": it.get("n", ""),
                        "p": it.get("p", 0),
                        "zdp": float(it.get("zdp", 0) or 0),
                        "jje": it.get("amount", 0),
                        "hs": float(it.get("hs", 0) or 0),
                        "pe": it.get("pe"),
                        "fund": it.get("fund", 0),
                        "lbt": cls._fmt_time(it.get("lbt", 0)),
                        "days": it.get("days", 1),
                        "oc": it.get("oc", 0),
                        "hybk": it.get("hybk", ""),
                    })
                logger.info(f"东财跌停池 (push2): {len(result)}条")
                return cls._get_cached_pool(cache_key, result)
        except Exception as e:
            logger.warning(f"东财跌停池 push2 获取失败: {e}")
        # 2. 腾讯兜底（字段较少）
        _, dt_items = cls._fetch_tencent_pool()
        enriched = [{**it, "hybk": "", "fund": 0} for it in dt_items]
        logger.info(f"腾讯跌停池兜底: {len(enriched)}条")
        return cls._get_cached_pool(cache_key, enriched)

    @classmethod
    def get_yesterday_zt_pool(cls, date=None):
        """昨日涨停池 — 用当前涨停池近似"""
        zt_pool = cls.get_zt_pool(date)
        if zt_pool:
            return [{
                "c": it.get("c", ""), "n": it.get("n", ""),
                "p": it.get("p", 0), "zdp": it.get("zdp", 0),
                "hybk": it.get("hybk", ""),
            } for it in zt_pool]
        return []

    @classmethod
    def get_zt_count(cls, date=None):
        """涨停总数 — 从腾讯全市场数据计算"""
        pool = cls.get_zt_pool(date)
        return len(pool) if pool else 0

    @classmethod
    def get_zb_count(cls, date=None):
        """炸板总数 — 复用 get_zb_pool() 的缓存和降级链路"""
        pool = cls.get_zb_pool(date)
        return len(pool) if pool else 0

    @classmethod
    def get_dt_count(cls, date=None):
        """跌停总数 — 从腾讯全市场数据计算"""
        pool = cls.get_dt_pool(date)
        return len(pool) if pool else 0


# ===== THSNorthboundSource =====

_THS_LOCK = __import__('threading').Lock()
_THS_LAST_REQUEST_TIME = [0.0]
THS_MIN_INTERVAL = 1.0


def _ths_throttle():
    with _THS_LOCK:
        now = time.time()
        elapsed = now - _THS_LAST_REQUEST_TIME[0]
        if elapsed < THS_MIN_INTERVAL:
            time.sleep(THS_MIN_INTERVAL - elapsed + random.uniform(0.1, 0.5))
        _THS_LAST_REQUEST_TIME[0] = time.time()


class THSNorthboundSource:
    """同花顺北向资金 — hsgtApi + 本地CSV自缓存"""
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36",
        "Host": "data.hexin.cn",
        "Referer": "https://data.hexin.cn/",
    }
    _CACHE_DIR = __import__("os").path.expanduser("~/.tradingagents/cache")

    @classmethod
    def get_realtime(cls):
        try:
            _ths_throttle()
            r = requests.get("https://data.hexin.cn/market/hsgtApi/method/dayChart/",
                           headers=cls._HEADERS, timeout=10)
            d = r.json()
            times = d.get("time", [])
            hgt = d.get("hgt", [])
            sgt = d.get("sgt", [])
            n = len(times)
            result = [{
                "time": times[i] if i < len(times) else "",
                "hgt_yi": hgt[i] if i < len(hgt) else None,
                "sgt_yi": sgt[i] if i < len(sgt) else None,
            } for i in range(n)]
            cls._save_daily_snapshot(result)
            return result
        except Exception as e:
            logger.warning(f"THS northbound failed: {e}")
            return []

    @classmethod
    def _cache_path(cls):
        import os
        p = os.path.join(cls._CACHE_DIR, "northbound_daily.csv")
        os.makedirs(cls._CACHE_DIR, exist_ok=True)
        return p

    @classmethod
    def _save_daily_snapshot(cls, realtime_data):
        if not realtime_data:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        last_valid = None
        for d in reversed(realtime_data):
            if d.get("hgt_yi") is not None and d.get("sgt_yi") is not None:
                last_valid = d
                break
        if not last_valid:
            return
        path = cls._cache_path()
        rows = {}
        import os as _os
        if _os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f.read().strip().split("\n")[1:]:
                    parts = line.split(",")
                    if len(parts) == 3:
                        rows[parts[0]] = line
        rows[today] = f"{today},{last_valid['hgt_yi']},{last_valid['sgt_yi']}"
        with open(path, "w", encoding="utf-8") as f:
            f.write("date,hgt_yi,sgt_yi\n")
            for d in sorted(rows.keys()):
                f.write(rows[d] + "\n")

    @classmethod
    def get_history(cls, n=20):
        path = cls._cache_path()
        import os as _os
        if not _os.path.exists(path):
            return []
        result = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f.read().strip().split("\n")[1:]:
                parts = line.split(",")
                if len(parts) == 3:
                    result.append({
                        "date": parts[0],
                        "hgt_yi": float(parts[1]) if parts[1] else None,
                        "sgt_yi": float(parts[2]) if parts[2] else None,
                    })
        return result[-n:]


# ===== MootdxSource =====

class MootdxSource:
    """mootdx数据源"""
    _client = None

    @classmethod
    def get_client(cls):
        if cls._client is None:
            from mootdx.quotes import Quotes
            try:
                cls._client = Quotes.factory(market="std")
            except Exception as e:
                logger.warning(f"mootdx factory failed: {e}")
                return None
        return cls._client

    @classmethod
    def get_kline(cls, code, frequency=9, count=100):
        client = cls.get_client()
        if not client:
            return []
        try:
            df = client.bars(symbol=code, frequency=str(frequency), adjust="", count=count)
            if df is None or len(df) == 0:
                return []
            records = []
            for _, row in df.iterrows():
                records.append({
                    "date": str(row.get("datetime", ""))[:10],
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": int(float(row.get("vol", 0))),
                    "amount": float(row.get("amount", 0)),
                })
            return records
        except Exception as e:
            logger.debug(f"mootdx kline failed ({code}): {e}")
            return []

    @classmethod
    def get_quotes(cls, codes):
        client = cls.get_client()
        if not client:
            return []
        try:
            return client.quotes(symbol=codes)
        except Exception as e:
            logger.debug(f"mootdx quotes failed: {e}")
            return []

    @classmethod
    def get_f10(cls, code, name="最新提示"):
        client = cls.get_client()
        if not client:
            return ""
        try:
            return str(client.f10(symbol=code, name=name))
        except Exception as e:
            logger.debug(f"mootdx f10 failed ({code}): {e}")
            return ""


# ===== EastMoneySource =====

class THSSectorBuilder:
    """从THS热点数据 + 腾讯财经构建板块行情"""
    _INDUSTRY_STOCKS = {
        # 基础行业（28个）
        '银行': ['601398', '601166', '600036', '601288', '600919'],
        '证券': ['601211', '600030', '601688', '600837', '601066'],
        '保险': ['601318', '601628', '601336'],
        '白酒': ['600519', '000858', '000568', '002304', '000596'],
        '家电': ['000333', '000651', '000418', '000921', '002508'],
        '医药': ['600276', '300760', '000661', '603259', '600196'],
        '半导体': ['688981', '688008', '002371', '603986', '600584'],
        '光伏': ['601012', '002129', '300750', '600438', '002506'],
        '新能源车': ['300750', '002594', '601633', '300014', '002460'],
        '汽车': ['601633', '000625', '600104', '002475', '601238'],
        '煤炭': ['601088', '601898', '600997', '600547', '000983'],
        '石油石化': ['601857', '600028', '600938', '601808'],
        '钢铁': ['600019', '600010', '600808', '000932'],
        '有色金属': ['601899', '603799', '601600', '600547', '000831'],
        '房地产': ['600048', '000002', '001979', '600383'],
        '建筑': ['601668', '601800', '601390', '601186'],
        '电力': ['600900', '600011', '600027', '600025'],
        '通信': ['600050', '000063', '603160', '688003'],
        '计算机': ['603019', '002410', '688187', '300033'],
        '传媒': ['002027', '300133', '300413', '600977'],
        '军工': ['600760', '600316', '600038', '002025'],
        '化工': ['600309', '000792', '600346', '002493'],
        '机械': ['600031', '000425', '000528', '601100'],
        '环保': ['300070', '000826', '600388', '300172'],
        '农业': ['000876', '000895', '002311', '600598'],
        '食品': ['600887', '603288', '002507', '000895'],
        # 产业链细分板块（扩展匹配）
        '锂电池': ['300750', '002460', '002741', '300014', '002594'],
        '储能': ['300274', '002938', '300118', '002129', '600438'],
        '充电桩': ['300118', '002938', '300040', '002527', '300316'],
        '稀土永磁': ['000831', '600111', '002339', '600259', '300141'],
        '光伏组件': ['601012', '002129', '600438', '002506', '300750'],
        '风电设备': ['601985', '002202', '600875', '300129', '002531'],
        '逆变器': ['300274', '002938', '300118', '002527', '300316'],
        '芯片设计': ['688981', '688008', '002049', '603986', '600584'],
        '晶圆代工': ['688981', '688008', '002371', '600584', '603038'],
        '封装测试': ['002371', '600584', '603038', '603290', '002185'],
        '医疗器械': ['300760', '603259', '002948', '300832', '688114'],
        '创新药': ['600276', '300760', '000661', '603259', '600196'],
        '原料药': ['600161', '002594', '600535', '002821', '603259'],
        'CXO': ['603456', '300347', '603259', '300573', '688202'],
        '面板': ['000100', '002475', '600795', '000050', '300136'],
        'PCB': ['002463', '002436', '603228', '002916', '300636'],
        '服务器': ['002415', '603019', '000977', '601138', '688041'],
        '数据中心': ['601138', '000977', '603881', '300308', '603043'],
        '光模块': ['300502', '002281', '300308', '688472', '300394'],
        '云计算': ['601138', '000977', '603881', '300308', '603043'],
        '智能驾驶': ['002594', '601633', '002475', '600660', '002200'],
        '机器人': ['002008', '688165', '300124', '002324', '603901'],
        '碳纤维': ['300343', '002130', '600680', '300679', '002514'],
        '无人机': ['002013', '300124', '002324', '688375', '300522'],
        '减速器': ['002008', '688165', '300124', '002324', '603901'],
        '伺服电机': ['002008', '688165', '300124', '002324', '603901'],
        '卫星互联网': ['688375', '002371', '600372', '600088', '600118'],
        '航天材料': ['002130', '600680', '300679', '002514', '600893'],
        '基因测序': ['688202', '300832', '688310', '688105', '300676'],
        '电解槽': ['688392', '603779', '300450', '002938', '600580'],
        '氢燃料电池': ['600111', '688392', '603779', '300450', '002938'],
        '固态电池': ['300750', '002460', '002741', '300014', '002594'],
        '数据要素': ['603043', '000977', '603881', '300308', '601138'],
    }

    @classmethod
    def build_industry_boards(cls, page_size=30):
        all_codes = set()
        for codes in cls._INDUSTRY_STOCKS.values():
            all_codes.update(codes)
        quotes_map = {}
        try:
            quotes_map = TencentSource.get_quotes(list(all_codes))
        except Exception as e:
            logger.warning(f"腾讯财经拉取失败: {e}")
            return []

        sector_list = []
        for name, codes in cls._INDUSTRY_STOCKS.items():
            valid = [quotes_map[c] for c in codes if c in quotes_map and quotes_map[c].get('price', 0) > 0]
            if not valid:
                continue
            avg_change = round(sum(q['change_pct'] for q in valid) / len(valid), 2)
            total_amount_wan = sum(q.get('amount_wan', 0) or 0 for q in valid)
            flow_net_yi = round(sum(q.get('amount_wan', 0) * q['change_pct'] / 100 * 0.3 for q in valid) / 1e4, 1)
            up_count = sum(1 for q in valid if q['change_pct'] > 0)
            down_count = sum(1 for q in valid if q['change_pct'] < 0)
            lead = max(valid, key=lambda q: q['change_pct'])
            sector_list.append({
                'f12': codes[0], 'f14': name, 'f3': avg_change, 'f2': 0,
                'f6': round(total_amount_wan / 1e4, 1) * 1e8, 'f9': str(len(valid)),
                'f62': flow_net_yi * 1e8, 'f140': lead.get('name', ''),
                'f141': lead.get('code', ''), 'source': 'tencent_calc',
                'up_count': up_count, 'down_count': down_count,
            })
        sector_list.sort(key=lambda x: x['f3'], reverse=True)
        return sector_list[:page_size]

    @classmethod
    def build_concept_boards_from_hot(cls, page_size=30):
        hot_items = THSHotSource.get_hot_reasons(page_size=200)
        if not hot_items:
            return []
        groups = {}
        for it in hot_items:
            reason = (it.get('reason') or '').strip()
            if not reason:
                continue
            concept_name = reason.split('+')[0].strip()
            if not concept_name or concept_name == '首板涨停':
                continue
            groups.setdefault(concept_name, []).append(it)

        all_codes = list(set(it['code'] for items in groups.values() for it in items if it.get('code')))
        quotes_map = {}
        try:
            quotes_map = TencentSource.get_quotes(all_codes)
        except Exception as e:
            logger.warning(f"腾讯财经补全失败: {e}")

        sector_list = []
        for concept_name, items in sorted(groups.items(), key=lambda x: -len(x[1])):
            valid = []
            for it in items:
                q = quotes_map.get(it.get('code', ''))
                if q and q.get('price', 0) > 0:
                    valid.append(q)
            if not valid:
                continue
            avg_change = round(sum(q['change_pct'] for q in valid) / len(valid), 2)
            total_amount_wan = sum(q.get('amount_wan', 0) or 0 for q in valid)
            total_amount_yi = round(total_amount_wan / 1e4, 2)
            flow_net_yi = round(sum((q.get('amount_wan', 0) or 0) * q['change_pct'] / 100 * 0.3 for q in valid) / 1e4, 1)
            up_count = sum(1 for q in valid if q['change_pct'] > 0)
            down_count = sum(1 for q in valid if q['change_pct'] < 0)
            lead = max(valid, key=lambda q: q['change_pct'])
            sector_list.append({
                'f12': items[0].get('code', ''), 'f14': concept_name,
                'f3': avg_change, 'f2': 0,
                'f6': total_amount_yi * 1e8,
                'f9': str(len(items)),
                'f62': flow_net_yi * 1e8,
                'f140': lead.get('name', ''),
                'f141': lead.get('code', ''),
                'source': 'ths_hot_grouped',
                'up_count': up_count, 'down_count': down_count,
            })
        sector_list.sort(key=lambda x: x['f3'], reverse=True)
        return sector_list[:page_size]


class EastMoneySource:
    """东方财富数据源 — push2已失效，委托腾讯财经"""

    @classmethod
    def get_full_market(cls, market_filter=None):
        return TencentSource.get_full_market()

    @classmethod
    def get_concept_boards(cls, page_size=500):
        try:
            return THSSectorBuilder.build_concept_boards_from_hot(page_size)
        except Exception as e:
            logger.warning(f"THS hot stocks failed: {e}")
            return []

    @classmethod
    def get_industry_boards(cls, page_size=100):
        return THSSectorBuilder.build_industry_boards(page_size)

    @classmethod
    def get_stock_info(cls, code):
        info = TencentSource.get_stock_info(code)
        if not info:
            logger.warning(f"Stock info empty for {code}")
        return info

    _CONCEPT_BLOCKS_CACHE: dict = {}
    _CONCEPT_BLOCKS_TTL = 1800  # 概念板块归属缓存30分钟

    @classmethod
    def get_concept_blocks(cls, code):
        now = time.time()
        cached = cls._CONCEPT_BLOCKS_CACHE.get(code)
        if cached and (now - cached['ts']) < cls._CONCEPT_BLOCKS_TTL:
            return cached['data']

        market_code = 1 if code.startswith("6") else 0
        params = {
            "fltt": "2", "invt": "2",
            "secid": f"{market_code}.{code}",
            "spt": "3", "pi": "0", "pz": "200", "po": "1",
            "fields": "f12,f14,f3,f128",
        }
        try:
            r = em_get("https://push2.eastmoney.com/api/qt/slist/get",
                       params=params, headers={"Referer": "https://quote.eastmoney.com/"}, timeout=15)
            d = r.json()
        except Exception as e:
            logger.warning(f"东财板块归属请求失败 ({code}): {e}")
            return []
        diff = (d.get("data") or {}).get("diff") or {}
        items = diff.values() if isinstance(diff, dict) else diff
        boards = []
        for it in items:
            board_name = it.get("f14", "")
            if board_name:
                boards.append({
                    "name": board_name, "code": it.get("f12", ""),
                    "change_pct": it.get("f3", 0), "lead_stock": it.get("f128", ""),
                })
        # 写入缓存（限制大小）
        if len(cls._CONCEPT_BLOCKS_CACHE) > 2000:
            # 淘汰最旧的1/4
            keys = list(cls._CONCEPT_BLOCKS_CACHE.keys())[:500]
            for k in keys:
                cls._CONCEPT_BLOCKS_CACHE.pop(k, None)
        cls._CONCEPT_BLOCKS_CACHE[code] = {'data': boards, 'ts': now}
        return boards

    @classmethod
    def get_fund_flow_rank(cls, indicator="今日"):
        return TencentSource.get_fund_flow_rank(indicator)

    # 资金流缓存：{code: (timestamp, data)}
    _flow_cache = {}
    _flow_cache_ttl = 60  # 60秒内复用同一股票的资金流数据

    @classmethod
    def get_stock_capital_flow(cls, code):
        """获取个股资金流向，三级降级：push2 → 腾讯内外盘 → pytdx"""
        import time as _t
        now = _t.time()
        cached = cls._flow_cache.get(code)
        if cached and now - cached[0] < cls._flow_cache_ttl:
            return cached[1]

        market = '1' if code.startswith('6') else '0'
        secid = f'{market}.{code}'

        # 方案1：push2 实时分钟级资金流（单次快速尝试，限时 4s）
        # ⚠️ 2026-09 实测：本机房 IP 下 push2.eastmoney.com 会随机断开连接
        # (RemoteDisconnected)。若走 em_get（_em_request 3 次重试+指数退避 3s/8s），
        # 一次诊断的资金流耗时可达 20s+，逼近接口 25s 超时，直接拖垮个股诊断。
        # 故改为：遵守限流 → 单次请求 4s 超时 → 失败立即降级腾讯（~0.1s）。
        try:
            _em_throttle()
            r = requests.get("https://push2.eastmoney.com/api/qt/stock/fflow/kline/get", params={
                'ut': '7eea3edcaed734bea9cb5f4e86d27735',
                'fltt': '2', 'invt': '2',
                'secid': secid, 'klt': 1,
                'fields1': 'f1,f2,f3,f7',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57',
            }, headers={"Referer": "https://quote.eastmoney.com/"}, timeout=4)
            if r.status_code != 200:
                raise ValueError(f"push2 status={r.status_code}")
            data = r.json()
            diff = (data.get('data') or {}).get('klines') or []
            if not diff:
                raise ValueError("push2 klines empty")
            result = cls._parse_fflow_klines(diff)
            cls._flow_cache[code] = (_t.time(), result)
            return result
        except Exception as e:
            logger.debug(f"push2 实时资金流失败 ({code}): {e}")

        # 方案2：腾讯内外盘数据（不封IP，不走东财限流）
        try:
            from app.core.pytdx_source import _pytdx_singleton
            pytdx = _pytdx_singleton()
            tencent_flow = pytdx.get_tencent_capital_flow(code)
            if tencent_flow and tencent_flow.get('main_net') is not None:
                outer_buy = tencent_flow.get('outer_disk_buy', 0) or 0
                inner_sell = tencent_flow.get('inner_disk_sell', 0) or 0
                main_net = tencent_flow.get('main_net', 0) or 0
                result = {
                    'source': '腾讯API(内外盘)',
                    'big_buy': round(outer_buy * 0.6, 2),
                    'big_sell': round(inner_sell * 0.6, 2),
                    'mid_buy': round(outer_buy * 0.3, 2),
                    'mid_sell': round(inner_sell * 0.3, 2),
                    'small_buy': round(outer_buy * 0.1, 2),
                    'small_sell': round(inner_sell * 0.1, 2),
                    'main_net': main_net,
                    'change_pct': tencent_flow.get('change_pct', 0),
                }
                cls._flow_cache[code] = (_t.time(), result)
                return result
        except Exception as e:
            logger.debug(f"腾讯资金流失败 ({code}): {e}")

        # 方案3：pytdx 基于成交明细计算（兜底，不走东财限流）
        try:
            from app.core.pytdx_source import _pytdx_singleton
            pytdx = _pytdx_singleton()
            pytdx_flow = pytdx.get_capital_flow(code)
            if pytdx_flow and pytdx_flow.get('sample_count', 0) > 100:
                pytdx_flow['source'] = 'pytdx(成交明细)'
                cls._flow_cache[code] = (_t.time(), pytdx_flow)
                return pytdx_flow
        except Exception as e:
            logger.debug(f"pytdx资金流失败 ({code}): {e}")

        cls._flow_cache[code] = (_t.time(), None)  # 缓存空结果避免重复请求
        return None

    @classmethod
    def _parse_fflow_klines(cls, klines):
        """解析资金流 klines 数据，返回统一格式"""
        if not klines:
            return None
        today = klines[0].split(',')
        main_net = float(today[1]) if len(today) > 1 and today[1] else 0
        small_net = float(today[2]) if len(today) > 2 and today[2] else 0
        mid_net = float(today[3]) if len(today) > 3 and today[3] else 0
        big_net = float(today[4]) if len(today) > 4 and today[4] else 0

        result = {
            'source': '东方财富',
            'big_buy': round(max(big_net, 0) / 1e8, 2),
            'big_sell': round(abs(min(big_net, 0)) / 1e8, 2),
            'mid_buy': round(max(mid_net, 0) / 1e8, 2),
            'mid_sell': round(abs(min(mid_net, 0)) / 1e8, 2),
            'small_buy': round(max(small_net, 0) / 1e8, 2),
            'small_sell': round(abs(min(small_net, 0)) / 1e8, 2),
            'main_net': round(main_net / 1e8, 2),
        }
        for days_key, n_days in [('flow_3d', 3), ('flow_5d', 5), ('flow_10d', 10)]:
            if len(klines) >= n_days:
                net_sum = sum(float(d.split(',')[1]) for d in klines[:n_days] if d.split(',')[1])
                result[days_key] = round(net_sum / 1e8, 2)
            else:
                result[days_key] = None
        return result

    @classmethod
    def get_global_news(cls, page_size=50):
        try:
            r = em_get("https://np-weblist.eastmoney.com/comm/web/getNewsList", params={
                "appType": "web", "type": "1", "pageSize": page_size, "pageIndex": 1,
                "varity": "0", "channelCode": "home",
            }, headers={"Referer": "https://www.eastmoney.com/"}, timeout=8)
            d = r.json()
            items = (d.get("data") or {}).get("list") or []
            return [{
                "title": it.get("title", ""), "content": (it.get("digest") or "")[:200],
                "time": str(it.get("showTime", ""))[:19], "source": it.get("mediaName", "东方财富"),
            } for it in items]
        except Exception as e:
            logger.debug(f"东财7x24快讯获取失败: {e}")
            return []


# ===== CNInfoSource =====

_CNINFO_LOCK = __import__('threading').Lock()
_CNINFO_LAST_REQUEST_TIME = [0.0]
CNINFO_MIN_INTERVAL = 1.0


def _cninfo_throttle():
    with _CNINFO_LOCK:
        now = time.time()
        elapsed = now - _CNINFO_LAST_REQUEST_TIME[0]
        if elapsed < CNINFO_MIN_INTERVAL:
            time.sleep(CNINFO_MIN_INTERVAL - elapsed + random.uniform(0.1, 0.3))
        _CNINFO_LAST_REQUEST_TIME[0] = time.time()


class CNInfoSource:
    """巨潮资讯 — 公告全文（V3.2.2 orgId 动态查询修复）"""
    _ORGID_CACHE = {}

    @classmethod
    def get_org_id(cls, code):
        if code in cls._ORGID_CACHE:
            return cls._ORGID_CACHE[code]
        # 优先从官方映射表动态查询（6198只股票，模块级缓存）
        org_id = cls._query_orgid(code)
        if not org_id:
            org_id = cls._fallback_orgid(code)
        cls._ORGID_CACHE[code] = org_id
        return org_id

    @classmethod
    def _query_orgid(cls, code):
        """从巨潮官方映射表查询真实 orgId（#19 修复，避免硬编码导致 totalAnnouncement=0）"""
        if not cls._ORGID_CACHE:
            try:
                _cninfo_throttle()
                r = requests.get("http://www.cninfo.com.cn/new/data/szse_stock.json",
                                 headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                mapping = {s["code"]: s["orgId"] for s in r.json().get("stockList", [])}
                cls._ORGID_CACHE.update(mapping)
            except Exception as e:
                logger.debug(f"巨潮 orgId 映射表拉取失败，回退硬编码规则: {e}")
        return cls._ORGID_CACHE.get(code)

    @classmethod
    def _fallback_orgid(cls, code):
        if code.startswith("6"):
            return f"gssh0{code}"
        elif code.startswith(("8", "4")):
            return f"gsbj0{code}"
        return f"gssz0{code}"

    @classmethod
    def get_announcements(cls, code, page_size=30):
        org_id = cls.get_org_id(code)
        try:
            _cninfo_throttle()
            r = requests.post("https://www.cninfo.com.cn/new/hisAnnouncement/query", data={
                "stock": f"{code},{org_id}", "tabName": "fulltext",
                "pageSize": str(page_size), "pageNum": "1"
            }, headers={
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.cninfo.com.cn/new/disclosure"
            }, timeout=15)
            d = r.json()
            items = d.get("announcements", []) or []
            return [{
                "title": item.get("announcementTitle", ""),
                "type": item.get("announcementTypeName", ""),
                "date": str(item.get("announcementTime", ""))[:10],
                "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}",
            } for item in items]
        except Exception as e:
            logger.warning(f"CNInfo announcements failed ({code}): {e}")
            return []


# ===== EastMoneyNewsSource =====

class EastMoneyNewsSource:
    """东方财富新闻，超时缩短至8s避免阻塞"""

    @classmethod
    def get_stock_news(cls, code, page_size=20):
        """获取个股相关新闻
        
        简化版：只使用东财搜索API（最快）
        """
        import json as j, re
        try:
            inner = j.dumps({
                "uid": "", "keyword": code,
                "type": ["cmsArticleWebOld"],
                "client": "web", "clientType": "web", "clientVersion": "curr",
                "param": {"cmsArticleWebOld": {
                    "searchScope": "default", "sort": "default",
                    "pageIndex": 1, "pageSize": page_size * 3
                }}
            }, separators=(",", ":"))
            r = em_get("https://search-api-web.eastmoney.com/search/jsonp", params={
                "cb": "jQuery_news", "param": inner
            }, headers={"Referer": "https://so.eastmoney.com/"}, timeout=5)
            text = r.text
            json_str = text[text.index("(")+1:text.rindex(")")]
            d = j.loads(json_str)
            articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
            
            return [{
                "title": re.sub(r"<[^>]+>", "", a.get("title", "")),
                "content": re.sub(r"<[^>]+>", "", (a.get("digest") or a.get("content", ""))[:200]),
                "time": str(a.get("date") or a.get("showTime", ""))[:19],
                "source": a.get("mediaName", "") or "东方财富",
                "url": a.get("url", ""),
            } for a in articles]
        except Exception as e:
            logger.debug(f"EastMoney stock news failed ({code}): {e}")
            return []

    @classmethod
    def get_stock_news_with_fallback(cls, code, page_size=20):
        """个股新闻带兜底：东财搜索 → 巨潮公告"""
        results = cls.get_stock_news(code, page_size)
        if not results:
            try:
                announcements = CNInfoSource.get_announcements(code, page_size=min(page_size, 10))
                if announcements:
                    return [{
                        "title": a.get("title", ""),
                        "content": f"[公告] {a.get('type', '')}",
                        "time": str(a.get("date", "")),
                        "source": "巨潮资讯",
                    } for a in announcements[:page_size]]
            except Exception:
                pass
        return results


# ===== THSHotSource =====

class THSHotSource:
    """同花顺热点题材 — zx.10jqka.com.cn"""
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0",
        "Host": "zx.10jqka.com.cn",
        "Referer": "https://www.10jqka.com.cn/",
    }

    @classmethod
    def get_hot_reasons(cls, page_size=200):
        try:
            _ths_throttle()
            r = requests.get(
                "https://zx.10jqka.com.cn/event/api/getharden/",
                params={"page": 1, "pagesize": page_size},
                headers=cls._HEADERS, timeout=10
            )
            d = r.json()
            items = d.get("data", []) or d.get("result", {}).get("data", []) or []

            # THS API 已不再返回价格/涨跌幅字段，需要从腾讯财经补全
            codes = [str(it.get("code", "")) for it in items if it.get("code")]
            quotes_map = {}
            if codes:
                try:
                    quotes_map = TencentSource.get_quotes(codes)
                except Exception as e:
                    logger.debug(f"腾讯补全热点价格失败: {e}")

            result = []
            for it in items:
                code = str(it.get("code", ""))
                q = quotes_map.get(code, {}) if quotes_map else {}
                result.append({
                    "code": code,
                    "name": it.get("name", ""),
                    "price": q.get("price", 0) or it.get("close", 0) or it.get("price", 0),
                    "pct_change": q.get("change_pct", 0) or it.get("zhangfu", 0) or it.get("zdf", 0),
                    "reason": it.get("reason", ""),
                    "tag": it.get("tag", ""),
                    "rank": it.get("rd", 0),
                    "anomaly": it.get("abnormal", ""),
                })
            return result
        except Exception as e:
            logger.warning(f"THS hot reasons failed: {e}")
            return []

    @classmethod
    def get_stock_hot_reason(cls, code):
        all_hot = cls.get_hot_reasons()
        for item in all_hot:
            if item["code"] == code:
                return item
        return None

    @classmethod
    def get_hot_stocks(cls, page_size=200):
        hot_data = cls.get_hot_reasons(page_size)
        result = []
        for item in hot_data:
            result.append({
                "f12": item["code"], "f14": item["name"],
                "f3": float(item.get("pct_change", 0) or 0),
                "f2": float(item.get("price", 0) or 0),
                "f6": 0, "f9": "", "f128": item.get("reason", ""),
                "f140": item.get("tag", ""), "f141": "",
                "f62": 0, "f63": 0, "f66": 0, "f69": 0, "f75": 0,
                "f78": item.get("anomaly", ""),
            })
        return result


# ===== THSCapitalFlowSource =====

class THSCapitalFlowSource:
    """同花顺资金流数据源"""
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://data.10jqka.com.cn/",
    }
    _SP_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "http://stockpage.10jqka.com.cn/",
    }
    _GGZJL_SESSION = None
    _SP_SESSION = None
    _CAPITAL_FLOW_CACHE = {}
    _CAPITAL_FLOW_LOCK = __import__("threading").Lock()

    @classmethod
    def _get_session(cls, name):
        from requests.adapters import HTTPAdapter
        attr = f"_{name}_SESSION"
        sess = getattr(cls, attr)
        if sess is None:
            sess = requests.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            sess.mount("http://", adapter)
            sess.mount("https://", adapter)
            setattr(cls, attr, sess)
        return sess

    @classmethod
    def _parse_amount(cls, val_str):
        if not val_str or val_str == '-':
            return 0.0
        negative = val_str.startswith('-')
        val_str = val_str.lstrip('-').replace(',', '')
        multiplier = 1.0
        if '万亿' in val_str:
            multiplier = 1e4
            val_str = val_str.replace('万亿', '')
        elif '亿' in val_str:
            multiplier = 1.0
            val_str = val_str.replace('亿', '')
        elif '万' in val_str:
            multiplier = 1e-4
            val_str = val_str.replace('万', '')
        try:
            result = float(val_str) * multiplier
            return -result if negative else result
        except ValueError:
            return 0.0

    @classmethod
    def get_top_capital_flows(cls, pages=5, force_refresh=False):
        """全市场主力资金流聚合（使用同花顺行业资金流合计）。

        东财 push2 clist 接口已不可用，改用同花顺行业资金流（hyzjl）合计。
        行业资金流无重复计算问题，数值与全市场实际资金流接近。
        """
        cache_key = 'top_capital_flows'
        with cls._CAPITAL_FLOW_LOCK:
            cached = cls._CAPITAL_FLOW_CACHE.get(cache_key)
            if cached and not force_refresh:
                ts, data = cached
                if time.time() - ts < 180:
                    return data

        try:
            import requests as _req
            import pandas as pd
            from io import StringIO

            all_dfs = []
            for page in range(1, 20):
                url = f"https://data.10jqka.com.cn/funds/hyzjl/field/tradezdf/order/desc/page/{page}/free/1/"
                try:
                    _ths_throttle()
                    r = _req.get(url, headers=cls._HEADERS, timeout=15)
                    r.encoding = "gbk"
                    dfs = pd.read_html(StringIO(r.text))
                    if not dfs:
                        break
                    df = dfs[0]
                    if len(df) == 0:
                        break
                    all_dfs.append(df)
                    if len(df) < 50:
                        break
                except Exception:
                    break

            if not all_dfs:
                return {}

            total_df = pd.concat(all_dfs, ignore_index=True)
            sample_size = len(total_df)

            net_col = None
            in_col = None
            out_col = None
            for col in total_df.columns:
                col_str = str(col)
                if '净额' in col_str:
                    net_col = col
                elif '流入资金' in col_str:
                    in_col = col
                elif '流出资金' in col_str:
                    out_col = col

            if net_col is None:
                return {}

            total_net_yi = round(sum(cls._parse_amount(str(v)) for v in total_df[net_col]), 2)
            total_in_yi = round(sum(cls._parse_amount(str(v)) for v in total_df[in_col]), 2) if in_col else max(total_net_yi, 0)
            total_out_yi = round(sum(cls._parse_amount(str(v)) for v in total_df[out_col]), 2) if out_col else abs(min(total_net_yi, 0))

            result = {
                'main_net_inflow_yi': total_net_yi,
                'large_net_yi': total_net_yi,
                'mid_net_yi': 0.0,
                'small_net_yi': 0.0,
                'source': 'ths_hyzjl',
                'sample_size': sample_size,
                'breakdown_sample_size': 0,
                'metric': '全市场净额(行业资金流合计)',
                'partial': False,
                'total_inflow_yi': total_in_yi,
                'total_outflow_yi': total_out_yi,
            }

            logger.info(f"同花顺行业资金流合计: 净额={total_net_yi:.1f}亿 (行业数={sample_size})")

            with cls._CAPITAL_FLOW_LOCK:
                cls._CAPITAL_FLOW_CACHE[cache_key] = (time.time(), result)

            return result
        except Exception as e:
            logger.warning(f"同花顺行业资金流合计获取失败: {e}")
            return {}

    @classmethod
    def get_industry_capital_flow(cls, page_size=50):
        return []


# ===== EastMoneyIndustryReport =====

class EastMoneyIndustryReport:
    """东财行业研报"""
    REPORT_API = "https://reportapi.eastmoney.com/report/list"

    @classmethod
    def get_reports(cls, code="", industry_code="*", max_pages=5, days_back=7):
        """获取行业研报
        
        Args:
            code: 股票代码（可选）
            industry_code: 行业代码，*表示全部
            max_pages: 最大页数
            days_back: 保留最近N天的研报（默认7天）
        """
        from datetime import datetime, timedelta
        cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        
        all_records = []
        for page in range(1, max_pages + 1):
            params = {
                "industryCode": industry_code, "pageSize": "100", "industry": "*",
                "rating": "*", "ratingChange": "*",
                "beginTime": cutoff_date, "endTime": "2030-01-01",  # 只获取最近N天
                "pageNo": str(page), "fields": "", "qType": "0" if code else "1",
                "code": code,
            }
            try:
                r = em_get(cls.REPORT_API, params=params,
                           headers={"Referer": "https://data.eastmoney.com/"}, timeout=30)
                d = r.json()
                rows = d.get("data") or []
                if not rows:
                    break
                all_records.extend(rows)
            except Exception as e:
                logger.warning(f"东财研报获取失败 (page {page}): {e}")
                break
        return all_records


# ===== EastMoneyFlowHistory =====

class EastMoneyFlowHistory:
    """东财资金流历史 — ⚠️ 已废弃：push2his.eastmoney.com 长期不可用"""

    @classmethod
    def get_fund_flow_120d(cls, code):
        # push2his.eastmoney.com 已不可用，快速返回空
        logger.debug("EastMoneyFlowHistory.get_fund_flow_120d() 已废弃，push2his不可用")
        return []


# ===== THSLimitUpPoolSource =====

class THSLimitUpPoolSource:
    """同花顺涨停板池 — data.10jqka.com.cn"""
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.10jqka.com.cn/",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }

    @classmethod
    def get_limit_up_pool(cls, page=1, page_size=100):
        """获取同花顺涨停板池"""
        url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
        params = {
            "page": page, "limit": page_size,
            "field": "199112,10,330329,330330,330331,330332,330333,330334,330335,330336,330337,330338,330339,330340,330341,330342,330343,330344,330345,330346,330347,330348,330349,330350,330351,330352,330353,330354,330355,330356,330357,330358,330359",
            "filter": "HS", "order_field": "330331", "order_type": "0",
            "_": int(time.time() * 1000),
        }
        try:
            _ths_throttle()
            r = requests.get(url, params=params, headers=cls._HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            items = (data.get("data") or {}).get("info") or (data.get("data") or {}).get("list") or []
            result = []
            for it in items:
                code = str(it.get("code") or "")
                name = it.get("name", "")
                change_pct = float(it.get("change_rate") or 0)
                price = float(it.get("latest") or 0)
                turnover_pct = float(it.get("turnover_rate") or 0)
                amount_yi = round(float(it.get("amount") or 0) / 1e8, 2)
                change_tag = it.get("change_tag") or ""
                is_again_limit = int(it.get("is_again_limit") or 0)
                market_type = it.get("market_type") or ""
                high_days = it.get("high_days") or ""

                # THS API 新版：first/last limit time 字段可能不存在，从 change_tag 推断
                first_time_raw = it.get("first_limit_time") or it.get("firstLimitTime")
                last_time_raw = it.get("last_limit_time") or it.get("lastLimitTime")
                first_time = str(first_time_raw or "").zfill(6) if first_time_raw else None
                last_time = str(last_time_raw or "").zfill(6) if last_time_raw else None
                open_count = int(it.get("limit_times") or it.get("limitTimes") or 0)

                import re as _re
                if high_days == "首板" or not high_days:
                    continuous = 1
                else:
                    m = _re.search(r'(\d+)板', str(high_days))
                    continuous = int(m.group(1)) if m else 1

                sealed_amount_yi = round(float(it.get("highLimitAmount") or 0) / 1e8, 2)
                reason = it.get("limitUpReason") or it.get("reason") or cls._build_reason_from_tag(change_tag)

                # 板型判断：优先用 change_tag，其次用 high_days/is_again_limit
                pattern = "换手"
                if change_tag == "T_LIMIT":
                    pattern = "一字"
                elif first_time and first_time == last_time and open_count == 0:
                    pattern = "一字"
                elif open_count > 0 or "回封" in str(change_tag) or change_tag == "LIMIT_BACK":
                    pattern = "开板"
                elif continuous >= 2 or is_again_limit >= 1:
                    pattern = "连板"

                result.append({
                    "code": code, "name": name, "change_pct": change_pct, "price": price,
                    "turnover_pct": turnover_pct, "amount_billion": amount_yi,
                    "first_time": first_time, "last_time": last_time, "open_count": open_count,
                    "continuous_limit_num": continuous, "sealed_amount_yi": sealed_amount_yi,
                    "industry": it.get("industryName", ""), "reason": reason,
                    "change_tag": change_tag, "is_again_limit": is_again_limit,
                    "market_type": market_type, "high_days": high_days, "pattern": pattern,
                })
            logger.info(f"同花顺涨停板池: {len(result)}只涨停股")
            return result
        except Exception as e:
            logger.warning(f"同花顺涨停板池获取失败: {e}")
            return []

    @staticmethod
    def _build_reason_from_tag(change_tag):
        mapping = {"FIRST_LIMIT": "首板涨停", "LIMIT_BACK": "开板回封",
                   "HIGH_LIMIT": "高位涨停", "T_LIMIT": "T字涨停"}
        return mapping.get(change_tag, "")

    @classmethod
    def get_limit_up_summary(cls):
        """涨停池汇总统计"""
        pool = cls.get_limit_up_pool(page=1, page_size=200)
        if not pool:
            return {}
        patterns = {"一字": 0, "开板": 0, "连板": 0, "换手": 0}
        for it in pool:
            patterns[it["pattern"]] = patterns.get(it["pattern"], 0) + 1
        max_continuous = max((it.get("continuous_limit_num") or 0) for it in pool) if pool else 0
        total_sealed = round(sum(it.get("sealed_amount_yi", 0) or 0 for it in pool), 2)
        total_amount = round(sum(it.get("amount_billion", 0) or 0 for it in pool), 1)

        try:
            hot_items = THSHotSource.get_hot_reasons(page_size=200)
            reason_map = {item["code"]: item for item in hot_items if item.get("reason")}
            for stock in pool:
                code = stock.get("code", "")
                if not stock.get("reason"):
                    ths_item = reason_map.get(code)
                    if ths_item:
                        stock["reason"] = f"{ths_item['reason']}" + (f" ({ths_item['tag']})" if ths_item.get('tag') else "")
                    elif stock.get("industry"):
                        stock["reason"] = stock["industry"]
        except Exception:
            pass

        return {
            "total": len(pool), "patterns": patterns, "max_continuous": max_continuous,
            "total_sealed_yi": total_sealed, "total_amount_yi": total_amount, "stocks": pool,
        }


# ===== THSConsensusSource =====

class THSConsensusSource:
    """同花顺一致预期 — basic.10jqka.com.cn"""
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0",
        "Referer": "https://basic.10jqka.com.cn/",
    }

    @classmethod
    def get_consensus(cls, code):
        """获取一致预期EPS和净利润预测"""
        try:
            _ths_throttle()
            r = requests.get(f"https://basic.10jqka.com.cn/new/{code}/worth.html",
                           headers=cls._HEADERS, timeout=10)
            text = r.text
            import re, json
            match = re.search(r'var\s+Data\s*=\s*(\{.*?\});', text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                return {
                    "eps_current": data.get("eps", {}).get("current", 0),
                    "eps_next_year": data.get("eps", {}).get("nextYear", 0),
                    "eps_year_after": data.get("eps", {}).get("yearAfter", 0),
                    "net_profit_current": data.get("profit", {}).get("current", 0),
                    "net_profit_next_year": data.get("profit", {}).get("nextYear", 0),
                    "pe_current": data.get("pe", {}).get("current", 0),
                    "pe_next_year": data.get("pe", {}).get("nextYear", 0),
                    "rating": data.get("rating", ""),
                    "analyst_count": data.get("analystCount", 0),
                }
            eps_match = re.search(r'一致预期.*?EPS.*?([\d.]+)', text)
            return {
                "eps_current": float(eps_match.group(1)) if eps_match else 0,
                "eps_next_year": 0, "eps_year_after": 0,
                "net_profit_current": 0, "net_profit_next_year": 0,
                "pe_current": 0, "pe_next_year": 0, "rating": "", "analyst_count": 0,
            }
        except Exception as e:
            logger.warning(f"THS consensus failed ({code}): {e}")
            return {}


# ===== get_last_trade_date =====

def get_last_trade_date():
    """获取最近交易日(YYYYMMDD)，使用腾讯财经验证"""
    today = datetime.now()
    if today.hour < 9:
        logger.info(f"当前时间 {today.strftime('%H:%M')} 早于9:00，返回推算交易日")

    try:
        quotes = TencentSource.get_quotes(["000001"])
        if "000001" in quotes and today.hour >= 9:
            data = quotes["000001"]
            price = data.get("price", 0)
            amount = data.get("amount_wan", 0)
            if price and float(price) > 0 and (today.hour >= 15 or float(amount) > 0):
                result = today.strftime("%Y%m%d")
                logger.info(f"腾讯财经确认今日为交易日: {result}")
                return result
    except Exception as e:
        logger.warning(f"腾讯财经交易日历验证失败: {e}")

    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    result = d.strftime("%Y%m%d")
    logger.info(f"推算最近交易日: {result}")
    return result


# ===== EastMoneyLimitUpPoolSource =====

class EastMoneyLimitUpPoolSource:
    """东方财富涨停池 — push2ex.eastmoney.com"""

    @staticmethod
    def get_sealed_amount_map(date_str=None):
        """获取涨停股封单金额映射 {code: sealed_yi}

        返回 dict，key=股票代码(6位)，value=封单金额(亿)
        """
        if not date_str:
            date_str = get_last_trade_date()

        url = "https://push2ex.eastmoney.com/getTopicZTPool"
        params = {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt",
            "Pageindex": "0",
            "pagesize": "500",
            "sort": "fbt:asc",
            "date": date_str,
            "_": int(time.time() * 1000),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }

        try:
            r = em_get_clean(url, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            pool = (data.get("data") or {}).get("pool") or []
            sealed_map = {}
            for item in pool:
                code = str(item.get("c", ""))
                ltsz = float(item.get("ltsz", 0) or 0)
                # ltsz 单位是元，转换为亿
                sealed_yi = round(ltsz / 1e8, 2)
                if code and sealed_yi > 0:
                    sealed_map[code] = sealed_yi
            logger.info(f"东财涨停池封单数据: {len(sealed_map)}只")
            return sealed_map
        except Exception as e:
            logger.warning(f"东财涨停池获取失败: {e}")
            return {}

    @staticmethod
    def get_first_time_map(date_str=None):
        """获取涨停股首封时间映射 {code: first_time}

        返回 dict，key=股票代码(6位)，value=首封时间(如 "09:25:00")
        """
        if not date_str:
            date_str = get_last_trade_date()

        url = "https://push2ex.eastmoney.com/getTopicZTPool"
        params = {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt",
            "Pageindex": "0",
            "pagesize": "500",
            "sort": "fbt:asc",
            "date": date_str,
            "_": int(time.time() * 1000),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }

        try:
            r = em_get_clean(url, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            pool = (data.get("data") or {}).get("pool") or []
            time_map = {}
            for item in pool:
                code = str(item.get("c", ""))
                fbt = item.get("fbt", 0) or 0
                if code and fbt:
                    # fbt 格式: 92500 → "09:25:00"
                    s = str(int(fbt)).zfill(6)
                    time_map[code] = f"{s[:2]}:{s[2:4]}"
            logger.info(f"东财涨停池首封时间数据: {len(time_map)}只")
            return time_map
        except Exception as e:
            logger.warning(f"东财涨停池首封时间获取失败: {e}")
            return {}

    @staticmethod
    def get_pool_summary(date_str=None):
        """获取涨停池汇总（含封单金额、连板高度等）"""
        if not date_str:
            date_str = get_last_trade_date()

        url = "https://push2ex.eastmoney.com/getTopicZTPool"
        params = {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt",
            "Pageindex": "0",
            "pagesize": "500",
            "sort": "fbt:asc",
            "date": date_str,
            "_": int(time.time() * 1000),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }

        try:
            r = em_get_clean(url, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            pool = (data.get("data") or {}).get("pool") or []

            if not pool:
                return {}

            total_sealed_yi = round(sum(float(item.get("ltsz", 0) or 0) for item in pool) / 1e8, 2)
            max_continuous = max((item.get("lbc", 0) or 0) for item in pool) if pool else 0

            logger.info(f"东财涨停池汇总: {len(pool)}只, 封单{total_sealed_yi}亿, 最高连板{max_continuous}")
            return {
                "total": len(pool),
                "total_sealed_yi": total_sealed_yi,
                "max_continuous": max_continuous,
                "source": "eastmoney",
            }
        except Exception as e:
            logger.warning(f"东财涨停池汇总获取失败: {e}")
            return {}


# ===== SectorHistoryCache =====

class SectorHistoryCache:
    """板块强度历史缓存 — 用于龙头选股避免一日游板块

    缓存累积模式：每次 get_leader_picks 调用时写入今日板块快照，
    读取最近 5 日板块强度历史，计算 5 日平均涨幅作为板块筛选维度。
    数据不足 5 日时降级为只用当日数据（不影响主流程）。
    """
    _NS = "sector_history"
    _MAX_DAYS = 5
    _TTL = 86400 * 7  # 7 天
    _LOCK = __import__('threading').Lock()

    @classmethod
    def _key(cls, sector_type: str) -> str:
        return f"sector_history_{sector_type}"

    @classmethod
    def get_history(cls, sector_type: str = "industry") -> list:
        """读取最近 5 日板块强度历史

        返回: [{date, sectors: [{name, change_pct, flow_net, turnover_yi, up_count, down_count}]}]
        数据不足 5 日时返回已有天数（首次运行返回 []）
        """
        from app.core.cache import cache_get
        try:
            data = cache_get(cls._key(sector_type), namespace=cls._NS)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.debug(f"板块历史读取失败 [{sector_type}]: {e}")
            return []

    @classmethod
    def save_today_snapshot(cls, sector_type: str, sectors: list, date_str: str = None):
        """保存今日板块强度快照（按 date 去重，截断到最近 _MAX_DAYS 天）"""
        from app.core.cache import cache_set
        if not sectors:
            return
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        today_snapshot = {
            "date": date_str,
            "sectors": [
                {
                    "name": str(s.get("name", "") or ""),
                    "change_pct": float(s.get("change_pct", 0) or 0),
                    "flow_net": float(s.get("flow_net", 0) or 0),
                    "turnover_yi": float(s.get("turnover_yi", 0) or 0),
                    "up_count": int(s.get("up_count", 0) or 0),
                    "down_count": int(s.get("down_count", 0) or 0),
                }
                for s in sectors
            ],
        }

        with cls._LOCK:
            history = cls.get_history(sector_type)
            history = [h for h in history if h.get("date") != date_str]
            history.append(today_snapshot)
            history = history[-cls._MAX_DAYS:]
            try:
                cache_set(cls._key(sector_type), history, ttl=cls._TTL, namespace=cls._NS)
            except Exception as e:
                logger.debug(f"板块历史写入失败 [{sector_type}]: {e}")

    @classmethod
    def calc_strength(cls, sector_type: str, sector_name: str) -> dict:
        """计算单个板块近 N 日强度指标

        返回:
        {
            "change_avg": float,    # 平均涨幅
            "change_sum": float,    # 累计涨幅
            "days_available": int,  # 可用天数
            "positive_days": int,   # 上涨天数
            "is_sustainable": bool  # 是否可持续（≥3 天且平均涨幅 > 0）
        }
        """
        history = cls.get_history(sector_type)
        changes = []
        for day_data in history:
            for s in day_data.get("sectors", []):
                if s.get("name") == sector_name:
                    changes.append(float(s.get("change_pct", 0) or 0))
                    break

        if not changes:
            return {
                "change_avg": 0, "change_sum": 0,
                "days_available": 0, "positive_days": 0,
                "is_sustainable": False,
            }

        avg = round(sum(changes) / len(changes), 2)
        return {
            "change_avg": avg,
            "change_sum": round(sum(changes), 2),
            "days_available": len(changes),
            "positive_days": sum(1 for c in changes if c > 0),
            "is_sustainable": len(changes) >= 3 and avg > 0,
        }
