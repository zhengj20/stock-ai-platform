"""pytdx数据源 - 直连通达信服务器获取实时数据（连接池+并行优化版）"""
import os
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from pytdx.hq import TdxHq_API
from app.core.cache import cache_get, cache_get_stale, cache_set, NS_KLINE
from app.core.constants import FULL_MARKET_CACHE_TTL as _DEFAULT_CACHE_TTL

logger = logging.getLogger(__name__)

# K线缓存 TTL 常量（模块级，供 get_kline 等方法直接引用）
_KLINES_TTL_DAILY = 300   # 日K盘中5分钟（最后一根在变化）
_KLINES_TTL_WEEKLY = 600  # 周/月K10分钟


SERVERS = [
    # a-stock-data-main 实测可用服务器（2026-06 验证，按延迟排序，优先）
    ('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709),
    ('123.60.73.44', 7709),  ('116.205.163.254', 7709), ('121.36.225.169', 7709),
    ('123.60.70.228', 7709), ('124.71.9.153', 7709),    ('110.41.147.114', 7709),
    ('124.71.187.122', 7709),
    # 原有服务器（保留作冗余）
    ('218.75.126.9', 7709),
    ('115.238.56.198', 7709),
    ('124.160.88.183', 7709),
    ('60.12.136.250', 7709),
    ('218.108.98.244', 7709),
    ('119.147.212.81', 7709),
    ('112.74.214.43', 7727),
]

# 市场映射: 1=沪市, 0=深市
MARKET_SH = 1
MARKET_SZ = 0

# ── pytdx 熔断：全部服务器不可用（海外/机房 IP 被风控）时，一段时间内跳过
# pytdx 连接遍历（每台 connect 默认超时 5s，17 台全试最坏 85s），直接走 HTTP 回退。
# 熔断过期后自动重试一次，pytdx 恢复则重新启用。
_PYTDX_FUSE_SECONDS = 600        # 熔断时长（本环境 pytdx 数据层被风控，探测已并行化故周期可长）
_PYTDX_CONNECT_TIMEOUT = 2.0     # 单台 connect 超时（a-stock-data-main _probe 同值）
# 全局探测锁：同一时刻只允许一个线程做全量服务器探测，避免诊断等并发场景
# 多个线程同时遍历 17 台服务器（惊群效应）。其余线程等待锁后看到熔断直接走 HTTP。
_probe_lock = threading.Lock()
_pytdx_fuse_until = 0.0
_pytdx_fuse_lock = threading.Lock()


def _pytdx_fuse_active() -> bool:
    return _pytdx_fuse_until > time.time()


def _arm_pytdx_fuse():
    """触发熔断：pytdx 全部服务器不可用，一段时间内跳过连接尝试。已熔断则不重复告警。"""
    global _pytdx_fuse_until
    with _pytdx_fuse_lock:
        if _pytdx_fuse_until > time.time():
            return
        _pytdx_fuse_until = time.time() + _PYTDX_FUSE_SECONDS
    logger.warning(f"pytdx 全部服务器不可用，触发熔断 {_PYTDX_FUSE_SECONDS}s，K线/行情将走 HTTP 回退")


def get_market(code: str) -> int:
    """根据股票代码判断市场"""
    if code.startswith(('6', '5', '9', '11', '13')):
        return MARKET_SH
    return MARKET_SZ


# ── HTTP K线回退数据源 ──────────────────────────────────────────────
# pytdx(通达信 TCP 7709) 在部分网络(海外/机房 IP)会被风控：连接通、
# security_count 通，但 get_security_bars/get_security_quotes 全部返回空。
# 参照 a-stock-data-main 数据源优先级：行情优先用不封 IP 的 HTTP 源。
# 回退链：腾讯 ifzq(前复权,主) → 百度股市通(含MA,备)。分钟K线两者均不支持。
_HTTP_KLINE_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
# pytdx period → 腾讯 type（仅 日/周/月/年 可回退）
_PERIOD_TO_TENCENT = {4: "day", 5: "week", 6: "month", 8: "year", 9: "day"}
# pytdx period → 百度 ktype（1=日 2=周 3=月 4=年）
_PERIOD_TO_BAIDU = {4: "1", 5: "2", 6: "3", 8: "4", 9: "1"}
# pytdx period → 腾讯分钟K type（m1/m5/m15/m30/m60，mootdx 挂掉时唯一 HTTP 分钟源）
_PERIOD_TO_TENCENT_MIN = {7: "m1", 0: "m5", 1: "m15", 2: "m30", 3: "m60"}
# pytdx period → 同花顺 K线 type（01日/11周/21月，全历史）
_PERIOD_TO_THS = {4: "01", 9: "01", 5: "11", 6: "21"}
# 同花顺指数代码（实测可用：上证指数=1A0001；深证系 399xxx 原样。000016/000300 等
# 沪市指数同花顺会误返 ETF/个股，不可用）
_THS_INDEX_CODE = {'000001': '1A0001', '399001': '399001', '399006': '399006',
                   '399005': '399005', '399106': '399106'}


def _tencent_code_prefix(code: str) -> str:
    """6位代码 → 腾讯市场前缀（个股用；指数需按 market 另行指定）"""
    if code.startswith(('6', '9', '5', '11', '13')):
        return 'sh'
    if code.startswith(('4', '8')):
        return 'bj'
    return 'sz'


def _http_kline_tencent(code: str, period: int, count: int, prefix: str | None = None) -> list[dict]:
    """腾讯 ifzq.gtimg.cn K线（前复权 qfq，不封IP）。
    返回格式与 pytdx 对齐：date/open/high/low/close/volume(手)/amount。
    """
    t = _PERIOD_TO_TENCENT.get(period)
    if not t:
        return []
    import requests
    full_code = f"{(prefix or _tencent_code_prefix(code))}{code}"
    params = {"param": f"{full_code},{t},,,{count},qfq"}
    r = requests.get("https://ifzq.gtimg.cn/appstock/app/fqkline/get",
                     params=params, headers={"User-Agent": _HTTP_KLINE_UA}, timeout=10)
    data = (r.json().get("data") or {}).get(full_code) or {}
    rows = data.get(f"qfq{t}") or data.get(t) or []
    bars = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        # row = [date, open, close, high, low, volume]
        bars.append({
            'date': row[0],
            'open': float(row[1]),
            'high': float(row[3]),
            'low': float(row[4]),
            'close': float(row[2]),
            'volume': float(row[5]),   # 腾讯单位=手，与 pytdx 一致
            'amount': 0,
        })
    return bars


def _http_kline_tencent_min(code: str, period: int, count: int) -> list[dict]:
    """腾讯 ifzq 分钟K线（m1/m5/m15/m30/m60，≤320根，不封IP）。
    参照 a-stock-data-main「备用源速查」K线(分钟)备胎：需头 Referer: https://gu.qq.com/。
    ⚠️ 字段坑：row=[时间, 开, 收, 高, 低, 量(手), {}, 换手率基点]——第3字段是收盘价
    不是最高价；第7字段是换手率基点不是成交额（差3个数量级），故 amount 不取。
    """
    m = _PERIOD_TO_TENCENT_MIN.get(period)
    if not m:
        return []
    import requests
    full_code = f"{_tencent_code_prefix(code)}{code}"
    n = min(count, 320)
    r = requests.get("https://ifzq.gtimg.cn/appstock/app/kline/mkline",
                     params={"param": f"{full_code},{m},,{n}"},
                     headers={"User-Agent": _HTTP_KLINE_UA, "Referer": "https://gu.qq.com/"},
                     timeout=10)
    data = (r.json().get("data") or {}).get(full_code) or {}
    rows = data.get(m) or []
    bars = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        # [时间, 开, 收, 高, 低, 量(手), {}, 换手率基点]
        bars.append({
            'date': str(row[0]),
            'open': float(row[1]),
            'high': float(row[3]),
            'low': float(row[4]),
            'close': float(row[2]),
            'volume': float(row[5]),
            'amount': 0,
        })
    return bars[-count:] if count and len(bars) > count else bars


def _http_kline_baidu(code: str, period: int, count: int, is_index: bool = False) -> list[dict]:
    """百度股市通 K线（不封IP，自带MA）。按 keys 动态定位列，避免硬编码错位。
    is_index=True 时走指数接口（isIndex=true）。⚠️ 仅 000300/399001 等部分指数
    点位正确，000001 会被当平安银行、000016/000688 会误返 ETF——指数调用方需自行过滤。
    """
    kt = _PERIOD_TO_BAIDU.get(period)
    if not kt:
        return []
    import requests
    params = {
        "all": "1", "isIndex": "true" if is_index else "false", "isBk": "false", "isBlock": "false",
        "isFutures": "false", "isStock": "true", "newFormat": "1",
        "group": "quotation_kline_ab", "finClientType": "pc",
        "code": code, "start_time": "", "ktype": kt,
    }
    headers = {
        "User-Agent": _HTTP_KLINE_UA,
        "Accept": "application/vnd.finance-web.v1+json",
        "Origin": "https://gushitong.baidu.com",
        "Referer": "https://gushitong.baidu.com/",
    }
    r = requests.get("https://finance.pae.baidu.com/selfselect/getstockquotation",
                     params=params, headers=headers, timeout=10)
    d = r.json()
    # 已知坑：ResultCode 类型不稳定（int/str），统一转 str 比较
    if str(d.get("ResultCode", "-1")) != "0":
        return []
    md = (d.get("Result") or {}).get("newMarketData", {})
    keys = md.get("keys", []) or []
    idx = {name: i for i, name in enumerate(keys)}
    if "close" not in idx:
        return []
    bars = []
    for row in (md.get("marketData", "") or "").split(";"):
        if not row:
            continue
        parts = row.split(",")
        if len(parts) < len(keys):
            continue

        def _f(name: str) -> float:
            i = idx.get(name)
            if i is None or i >= len(parts) or parts[i] in ("", "-"):
                return 0.0
            try:
                return float(parts[i])
            except (TypeError, ValueError):
                return 0.0

        date = parts[idx["time"]] if "time" in idx else (parts[0] if parts else "")
        bars.append({
            'date': date,
            'open': _f('open'),
            'high': _f('high'),
            'low': _f('low'),
            'close': _f('close'),
            'volume': _f('volume') / 100,   # 百度单位=股，/100 转手，与 pytdx 对齐
            'amount': _f('amount'),
        })
    return bars[-count:] if count and len(bars) > count else bars


def _http_kline_sina(code: str, period: int, count: int) -> list[dict]:
    """新浪K线（日K，前复权）。实测最稳定：大 count(250+)、批量请求均正常，
    且不受腾讯 WAF/百度限流影响。仅支持日K(scale=240)。
    成交量单位=股，/100 转手与 pytdx 对齐。
    """
    if period not in (4, 9):
        return []
    import json
    import urllib.request
    sym = f"{_tencent_code_prefix(code)}{code}"
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData")
    query = f"symbol={sym}&scale=240&ma=no&datalen={count}"
    req = urllib.request.Request(f"{url}?{query}")
    req.add_header("User-Agent", _HTTP_KLINE_UA)
    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            raw = json.loads(res.read().decode("utf-8"))
    except Exception as e:
        logger.debug(f"新浪K线请求失败 ({code}): {e}")
        return []
    if not isinstance(raw, list):
        return []
    bars = []
    for item in raw:
        try:
            bars.append({
                'date': item.get("day", ""),
                'open': float(item.get("open", 0)),
                'high': float(item.get("high", 0)),
                'low': float(item.get("low", 0)),
                'close': float(item.get("close", 0)),
                'volume': int(float(item.get("volume", 0))) / 100,   # 股 → 手
                'amount': 0,
            })
        except (TypeError, ValueError):
            continue
    return bars


def _http_kline_ths(code: str, period: int, count: int, ths_code: str | None = None) -> list[dict]:
    """同花顺全历史K线（01日/11周/21月，2001至今，JSONP剥壳，零鉴权）。
    参照 a-stock-data-main「备用源速查」K线(全历史)备胎。
    字段：日期,开,高,低,收,量(股),额(元),换手率,... → volume /100 转手对齐 pytdx。
    日线仅返回最近约一年（~140根），周/月为全历史。
    ths_code: 指数专用同花顺代码（如 1A0001），None 时用裸 6 位代码拼 hs_600519。
    ⚠️ 代码格式坑：个股是 hs_600519（不带市场前缀）；hs_sh600519/hs_sz000001 实测
    404/502。指数走 ths_code（1A0001/399001 等）。
    """
    t = _PERIOD_TO_THS.get(period)
    if not t:
        return []
    import json
    import urllib.request
    sym = f"hs_{ths_code}" if ths_code else f"hs_{code}"
    url = f"https://d.10jqka.com.cn/v6/line/{sym}/{t}/last.js"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _HTTP_KLINE_UA)
    req.add_header("Referer", "https://www.iwencai.com/")
    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            txt = res.read().decode("utf-8", "ignore")
    except Exception as e:
        logger.debug(f"同花顺K线请求失败 ({code}): {e}")
        return []
    start = txt.find("(")
    end = txt.rfind(")")
    if start < 0 or end <= start:
        return []
    try:
        d = json.loads(txt[start + 1:end])
    except Exception as e:
        logger.debug(f"同花顺K线解析失败 ({code}): {e}")
        return []
    bars = []
    for row in (d.get("data", "") or "").split(";"):
        if not row:
            continue
        p = row.split(",")
        if len(p) < 6:
            continue
        try:
            bars.append({
                'date': p[0],
                'open': float(p[1]),
                'high': float(p[2]),
                'low': float(p[3]),
                'close': float(p[4]),
                'volume': float(p[5]) / 100,   # 股 → 手
                'amount': float(p[6]) if len(p) > 6 else 0,
            })
        except (TypeError, ValueError):
            continue
    return bars[-count:] if count and len(bars) > count else bars


def http_kline(code: str, period: int, count: int) -> list[dict]:
    """HTTP K线回退统一入口，按周期选择数据源优先级（参照 a-stock-data-main 行情层）：
    - 分钟K(0/1/2/3/7)：腾讯 mkline（唯一 HTTP 分钟源）
    - 日K(4/9)：百度(零鉴权,稳定,支持大count) → 同花顺(全历史) → 腾讯(qfq) → 新浪(qfq)
    - 周/月(5/6)：百度 → 同花顺(全历史) → 腾讯
    - 年K(8)：百度 → 腾讯
    2026-09 实测环境：新浪被限流(456)、腾讯 ifzq 被 WAF(501)，百度/同花顺仍可用，
    故百度提前。全部失败返回 []。
    """
    if period in (0, 1, 2, 3, 7):
        fetchers = (_http_kline_tencent_min,)
    elif period in (4, 9):
        fetchers = (_http_kline_baidu, _http_kline_ths, _http_kline_tencent, _http_kline_sina)
    elif period in (5, 6):
        fetchers = (_http_kline_baidu, _http_kline_ths, _http_kline_tencent)
    else:
        fetchers = (_http_kline_baidu, _http_kline_tencent)
    for fetcher in fetchers:
        try:
            bars = fetcher(code, period, count)
            if bars:
                logger.info(f"K线HTTP回退命中 [{fetcher.__name__}]: {code} period={period} bars={len(bars)}")
                return bars
        except Exception as e:
            logger.debug(f"K线HTTP回退 {fetcher.__name__} 失败 ({code} period={period}): {e}")
    return []


class ConnectionPool:
    """pytdx连接池 - 线程安全，自动重连+心跳保活。

    关键设计：每个线程持有独立连接（threading.local），避免 pytdx 非线程安全问题。
    """

    def __init__(self, pool_size: int = 3):
        self._pool_size = pool_size
        self._connections = []
        self._lock = threading.Lock()
        self._last_heartbeat = time.time()
        self.HEARTBEAT_INTERVAL = 120  # 心跳间隔(秒)
        # 每个线程独立连接，避免 pytdx 非线程安全
        self._thread_local = threading.local()

    def _probe_server(self, host: str, port: int) -> dict | None:
        """探测单台服务器：连接 + 真实取数验活（防止假阳性）。线程独立 API 实例。"""
        api = TdxHq_API()
        try:
            if api.connect(host, port, time_out=_PYTDX_CONNECT_TIMEOUT):
                # 真实取数验活：能拉到一根K线才算可用（000001 平安银行，深市 market=0）
                if api.get_security_bars(4, 0, '000001', 0, 1):
                    return {'api': api, 'host': host, 'port': port, 'connected': True}
        except Exception:
            pass
        try:
            api.disconnect()
        except Exception:
            pass
        return None

    def _create_connection(self):
        """创建单个连接（真实取数验活，参照 a-stock-data-main §1.1 tdx_client）：
        TCP 握手成功 ≠ 能取数——坏服务器可握手通过却回空 body。候选必须能真实
        拉到一根K线才采用，避免静默空表 + 走不到 HTTP 回退（#43 同类问题）。
        全部失败触发熔断，后续调用直接走 HTTP 回退。

        优化（2026-09）：17 台服务器【并行】探测（原顺序遍历最坏 34s→并行最坏 ~2s），
        且受全局 _probe_lock 保护——并发场景（如个股诊断 5 线程）只有一个线程做全量
        探测，其余线程等锁后看到熔断立即返回 None 走 HTTP 回退，消除惊群。
        """
        if _pytdx_fuse_active():
            return None
        with _probe_lock:
            # 双重检查：等待锁期间其他线程可能已完成探测并触发熔断
            if _pytdx_fuse_active():
                return None
            executor = ThreadPoolExecutor(max_workers=min(len(SERVERS), 12))
            try:
                futures = {executor.submit(self._probe_server, h, p): (h, p) for h, p in SERVERS}
                for future in as_completed(futures):
                    conn = future.result()
                    if conn:
                        # 找到可用服务器：取消未启动的探测任务，立即返回
                        for f in futures:
                            f.cancel()
                        return conn
            finally:
                # wait=False：已启动但未完成的探测线程在后台自行结束，不阻塞调用方
                executor.shutdown(wait=False)
            _arm_pytdx_fuse()
            return None

    def get_connection(self):
        """获取当前线程的专属连接（带自动重连）。

        每个线程持有独立 pytdx API 实例，避免并发调用导致连接断开或数据错乱。
        pytdx 熔断期间直接返回 None，让调用方快速走 HTTP 回退。
        """
        if _pytdx_fuse_active():
            return None

        # 检查当前线程是否有有效连接
        if hasattr(self._thread_local, 'conn') and self._thread_local.conn:
            api = self._thread_local.conn
            try:
                # 快速检测连接是否存活
                api.get_security_quotes([(1, '000001')])
                return api
            except Exception:
                # 连接已断开，清理旧引用
                self._thread_local.conn = None

        now = time.time()
        if now - self._last_heartbeat > self.HEARTBEAT_INTERVAL:
            self._refresh_pool()

        # 创建新连接给当前线程
        conn = self._create_connection()
        if conn:
            self._thread_local.conn = conn['api']
            return conn['api']

        # 紧急：从池中借用一个（兼容旧行为）
        with self._lock:
            for c in self._connections:
                if c and c.get('connected'):
                    return c['api']

        temp = self._create_connection()
        return temp['api'] if temp else None

    def _rebuild_pool(self):
        """重建连接池（加锁防并发；熔断期间跳过）。原实现循环 pool_size=50 次
        顺序 _create_connection，pytdx 全挂时最坏 50×2s=100s+ 且无锁并发执行，已修正。
        实际每个线程通过 threading.local 持有独立连接，共享池仅作紧急借用，2 条足够。
        """
        if _pytdx_fuse_active():
            return
        with self._lock:
            if _pytdx_fuse_active():
                return
            for _ in range(min(self._pool_size, 2)):
                c = self._create_connection()
                if c:
                    self._connections.append(c)

    def _refresh_pool(self):
        """刷新连接池（熔断期间跳过）"""
        if _pytdx_fuse_active():
            return
        with self._lock:
            new_conns = []
            for _ in range(min(self._pool_size, 2)):
                c = self._create_connection()
                if c:
                    new_conns.append(c)
            # 断开旧连接
            for conn in self._connections:
                try:
                    if conn and conn.get('connected'):
                        conn['api'].disconnect()
                except Exception:
                    pass
            self._connections = new_conns
            self._last_heartbeat = time.time()

    def close_all(self):
        """关闭所有连接"""
        # 关闭线程本地连接
        if hasattr(self._thread_local, 'conn') and self._thread_local.conn:
            try:
                self._thread_local.conn.disconnect()
            except Exception:
                pass
            self._thread_local.conn = None

        with self._lock:
            for conn in self._connections:
                try:
                    if conn and conn.get('connected'):
                        conn['api'].disconnect()
                except Exception:
                    pass
            self._connections = []


# 全局连接池实例（pool_size=50，支持多人并发诊断）
_connection_pool = ConnectionPool(pool_size=50)


class PytdxData:
    """pytdx数据源 - 使用连接池，支持并行批量操作"""

    def __init__(self):
        self._pool = _connection_pool

    @staticmethod
    def get_api():
        """从连接池获取API实例"""
        return _connection_pool.get_connection()

    def disconnect(self):
        """断开所有连接（用于优雅关闭）"""
        self._pool.close_all()

    # ── 行情数据 ────────────────────────────────────────

    def get_realtime_quote(self, codes: list[str]) -> list[dict]:
        """获取实时行情（带重试）"""
        for attempt in range(2):
            api = self.get_api()
            if not api:
                return []
            params = [(get_market(c), c) for c in codes]
            try:
                result = api.get_security_quotes(params)
                if not result:
                    if attempt == 0:
                        continue  # 重试一次
                    return []
                return [self._parse_quote(q) for q in result]
            except Exception:
                # 连接断开，重建池并重试
                self._pool._rebuild_pool()
                if attempt == 1:
                    logger.warning(f"pytdx get_realtime_quote 重试失败 ({len(codes)} codes)")
                continue
        return []

    def _parse_quote(self, q: dict) -> dict:
        """解析行情数据"""
        change = q['price'] - q['last_close']
        change_pct = (change / q['last_close'] * 100) if q['last_close'] else 0
        high = q.get('high', 0)
        low = q.get('low', 0)
        last_close = q.get('last_close', 0)
        amplitude = (high - low) / last_close * 100 if last_close > 0 and (high - low) > 0 else 0
        return {
            'code': q['code'],
            'name': q.get('name', ''),
            'price': q['price'],
            'last_close': last_close,
            'open': q['open'],
            'high': high,
            'low': low,
            'volume': q['vol'],
            'amount': q['amount'],
            'change': round(change, 2),
            'change_pct': round(change_pct, 2),
            'amplitude': round(amplitude, 2),
            'bid1': q.get('bid1', 0),
            'ask1': q.get('ask1', 0),
        }

    # ── K线数据（支持并行批量获取）───────────────────────

    from collections import OrderedDict
    _kline_cache = OrderedDict()  # LRU缓存，限制最大500条防止内存泄漏
    _KLINES_MAX_SIZE = 500  # K线缓存最大条目数
    _KLINE_CACHE_LOCK = threading.Lock()  # 多线程并发保护

    @classmethod
    def _get_kline_cache(cls, code: str, period: int, count: int) -> list[dict] | None:
        """获取K线缓存（LRU：访问后移到末尾，线程安全）。

        优化：只按(code, period)建索引，按需截取count。避免同一股票不同count占用多个槽位。
        """
        key = (code, period)
        with cls._KLINE_CACHE_LOCK:
            cached = cls._kline_cache.get(key)
            if not cached:
                return None
            # 根据周期确定TTL
            ttl = _KLINES_TTL_WEEKLY if period in (5, 6, 8) else _KLINES_TTL_DAILY
            if time.time() - cached['timestamp'] < ttl:
                # LRU：访问后移到末尾（最新）
                cls._kline_cache.move_to_end(key)
                # 按需截取：如果缓存的数据量>=请求的count，返回最后count条
                data = cached['data']
                if len(data) >= count:
                    return data[-count:]
                return None
            del cls._kline_cache[key]
        return None

    _KLINE_STALE_MAX_AGE = 86400  # 过期数据最大可用时间：24小时

    @classmethod
    def _get_kline_cache_stale(cls, code: str, period: int, count: int) -> list[dict] | None:
        """获取K线缓存（忽略TTL，pytdx不可用时的回退方案）。

        收盘后K线数据已定，用过期缓存比返回空更安全。
        限制：数据不超过24小时。
        """
        key = (code, period)
        with cls._KLINE_CACHE_LOCK:
            cached = cls._kline_cache.get(key)
            if not cached:
                return None
            age = time.time() - cached['timestamp']
            if age > cls._KLINE_STALE_MAX_AGE:
                del cls._kline_cache[key]
                return None
            data = cached['data']
            if len(data) >= count:
                return data[-count:]
            return None

    @classmethod
    def _set_kline_cache(cls, code: str, period: int, count: int, data: list[dict]):
        """设置K线缓存（LRU：超出大小时淘汰最久未访问的条目，线程安全）。

        优化：只按(code, period)建索引。如果已有缓存且新数据量更大则替换，否则保留旧的。
        """
        key = (code, period)
        with cls._KLINE_CACHE_LOCK:
            # 如果已存在，只有当新数据量更大时才替换（保留最大count）
            if key in cls._kline_cache:
                existing_count = len(cls._kline_cache[key]['data'])
                if len(data) <= existing_count:
                    return  # 已有更多数据，无需更新
                cls._kline_cache.move_to_end(key)
            else:
                # 检查是否超出最大容量
                while len(cls._kline_cache) >= cls._KLINES_MAX_SIZE:
                    cls._kline_cache.popitem(last=False)  # 淘汰最久未访问的（FIFO）
            cls._kline_cache[key] = {'data': data, 'timestamp': time.time()}

    def _get_kline_fallback(self, code: str, period: int, count: int) -> list[dict]:
        """pytdx不可用时的回退：优先Redis过期缓存，其次内存过期缓存"""
        if period not in (4, 5, 6, 8):
            return []
        redis_key = f"{code}_p{period}"
        stale_redis = cache_get_stale(redis_key, NS_KLINE)
        if stale_redis and len(stale_redis) >= count:
            logger.info(f"pytdx不可用，使用Redis过期K线缓存: {code}, 条数={len(stale_redis)}")
            return stale_redis[-count:]
        stale_mem = self._get_kline_cache_stale(code, period, count)
        if stale_mem is not None:
            logger.info(f"pytdx不可用，使用内存过期K线缓存: {code}, 条数={len(stale_mem)}")
            return stale_mem
        return []

    def _resolve_kline_with_http(self, code: str, period: int, count: int) -> list[dict]:
        """pytdx 不可用时的回退编排：HTTP K线(按周期多源，含分钟K腾讯mkline) → 过期缓存。

        命中 HTTP 时写入 Redis+内存缓存，后续调用直接命中缓存，避免重复请求。
        """
        bars = http_kline(code, period, count)
        if bars:
            if period in (4, 5, 6, 8):
                ttl = _KLINES_TTL_WEEKLY if period in (5, 6, 8) else _KLINES_TTL_DAILY
                cache_set(f"{code}_p{period}", bars, ttl=ttl, namespace=NS_KLINE)
                self._set_kline_cache(code, period, count, bars)
            return bars
        return self._get_kline_fallback(code, period, count)

    def get_kline(self, code: str, period: int = 4, count: int = 100, adj: str = '') -> list[dict]:
        """获取K线数据
        
        Args:
            code: 股票代码
            period: K线周期 (0=5min, 1=15min, 2=30min, 3=60min, 4=日, 5=周, 6=月, 7=1min, 8=年)
            count: 获取数量
            adj: 复权方式（预留参数，pytdx原生不支持复权，暂忽略）
        """
        # 分时K线不缓存（变化太快），只缓存日/周/月/年K
        if period not in (4, 5, 6, 8):
            pass  # 跳过缓存
        else:
            # Redis跨worker共享缓存
            redis_key = f"{code}_p{period}"
            cached_redis = cache_get(redis_key, NS_KLINE)
            if cached_redis and len(cached_redis) >= count:
                logger.debug(f"从Redis缓存获取K线: {code}, 条数={len(cached_redis)}")
                return cached_redis[-count:]

            # 进程内存缓存（热点加速）
            cached = self._get_kline_cache(code, period, count)
            if cached is not None:
                logger.debug(f"从内存缓存获取K线: {code}, 条数={len(cached)}")
                return cached

        api = self.get_api()
        if not api:
            logger.warning(f"无法获取pytdx API连接: {code}，尝试HTTP回退")
            return self._resolve_kline_with_http(code, period, count)
        market = get_market(code)
        
        try:
            logger.debug(f"开始从pytdx获取K线: {code}, market={market}, period={period}, count={count}")
            result = api.get_security_bars(period, market, code, 0, count)
            if not result:
                logger.warning(f"pytdx返回空数据: {code}, market={market}, period={period}，尝试HTTP回退")
                return self._resolve_kline_with_http(code, period, count)
            
            logger.info(f"成功获取K线数据: {code}, 条数={len(result)}")
            bars = [{
                'date': k['datetime'],
                'open': k['open'],
                'high': k['high'],
                'low': k['low'],
                'close': k['close'],
                'volume': k['vol'],
                'amount': k.get('amount', 0),
            } for k in result]
            if period in (4, 5, 6, 8):
                # 写入Redis（多worker共享）和内存缓存
                ttl = _KLINES_TTL_WEEKLY if period in (5, 6, 8) else _KLINES_TTL_DAILY
                cache_set(redis_key, bars, ttl=ttl, namespace=NS_KLINE)
                self._set_kline_cache(code, period, count, bars)
            return bars
        except Exception as e:
            logger.error(f"pytdx获取K线异常 ({code}): {type(e).__name__}: {e}", exc_info=True)
            return self._resolve_kline_with_http(code, period, count)

    # 指数市场映射（与股票不同：000001=上证指数属于沪市，399xxx=深证）
    _INDEX_MARKET_MAP = {
        '000001': 1, '000016': 1, '000300': 1, '000688': 1,
        '000905': 1, '000852': 1,
        '399001': 0, '399006': 0, '399005': 0, '399106': 0,
    }

    def get_index_kline(self, code: str, period: int = 4, count: int = 30, adj: str = 'qfq') -> list[dict]:
        """获取指数 K 线（pytdx.get_index_bars，category: 0=深证, 1=上证）

        用于指数迷你走势展示。缓存 key 加 'idx:' 前缀以隔离个股。
        period: 4=日, 5=周, 6=月, 8=年
        adj: 复权方式 ('qfq'=前复权, ''=不复权)
        """
        prefixed = f'idx:{code}'
        if period in (4, 5, 6, 8):
            cached = self._get_kline_cache(prefixed, period, count)
            if cached is not None:
                return cached

        api = self.get_api()
        if not api:
            return self._http_index_kline(code, period, count)
        market = self._INDEX_MARKET_MAP.get(code, get_market(code))
        try:
            result = api.get_index_bars(period, market, code, 0, count)
            if not result:
                # 兜底：get_security_bars（部分版本也支持指数）
                result = api.get_security_bars(period, market, code, 0, count)
            if not result:
                return self._http_index_kline(code, period, count)
            bars = [{
                'date': k['datetime'],
                'open': k['open'],
                'high': k['high'],
                'low': k['low'],
                'close': k['close'],
                'volume': k['vol'],
                'amount': k.get('amount', 0),
            } for k in result]
            if period in (4, 5, 6, 8):
                self._set_kline_cache(prefixed, period, count, bars)
            return bars
        except Exception as e:
            logger.debug(f"pytdx index kline failed ({code}): {e}")
            return self._http_index_kline(code, period, count)

    def _http_index_kline(self, code: str, period: int, count: int) -> list[dict]:
        """指数 K线 HTTP 回退（参照 a-stock-data-main 行情层，多备胎）：
        腾讯 ifzq(全指数) → 同花顺(上证1A0001/深证399xxx) → 百度 isIndex(仅000300等)。
        前缀按 _INDEX_MARKET_MAP 指定：market=1→sh，market=0→sz。
        """
        if period not in _PERIOD_TO_TENCENT:
            return []
        market = self._INDEX_MARKET_MAP.get(code, get_market(code))
        prefix = 'sh' if market == 1 else 'sz'
        bars = []
        try:
            bars = _http_kline_tencent(code, period, count, prefix=prefix)
        except Exception as e:
            logger.debug(f"指数K线腾讯回退失败 ({code}): {e}")
        if not bars and code in _THS_INDEX_CODE:
            try:
                bars = _http_kline_ths(code, period, count, ths_code=_THS_INDEX_CODE[code])
            except Exception as e:
                logger.debug(f"指数K线同花顺回退失败 ({code}): {e}")
        if not bars and code == '000300':
            # 百度 isIndex 实测仅 000300 点位正确；000001/000016/000688/000905/000852
            # 会静默返回个股/ETF 价（差 2-3 个数量级）——宁缺毋错，禁用。
            try:
                bars = _http_kline_baidu(code, period, count, is_index=True)
            except Exception as e:
                logger.debug(f"指数K线百度回退失败 ({code}): {e}")
        if bars:
            logger.info(f"指数K线HTTP回退命中: {code} period={period} bars={len(bars)}")
            if period in (4, 5, 6, 8):
                self._set_kline_cache(f'idx:{code}', period, count, bars)
        return bars

    def get_batch_klines(self, codes: list[str], period: int = 4, count: int = 30, max_workers: int = 5) -> dict[str, list[dict]]:
        """并行批量获取K线数据 - 每个线程独立连接(pytdx非线程安全)，优先使用缓存"""
        results = {}

        # 先检查缓存，只对未缓存的股票发起网络请求
        need_fetch = []
        for code in codes:
            cached = self._get_kline_cache(code, period, count)
            if cached is not None:
                results[code] = cached
            else:
                need_fetch.append(code)

        def _fetch_one(code):
            # pytdx 熔断期间直接走 HTTP 回退
            if _pytdx_fuse_active():
                return code, self._resolve_kline_with_http(code, period, count)
            # 复用连接池的并行探测（受全局锁保护，防多线程重复遍历17台服务器）
            conn = self._pool._create_connection()
            if not conn:
                return code, self._resolve_kline_with_http(code, period, count)
            api = conn['api']
            bars = []
            try:
                r = api.get_security_bars(period, get_market(code), code, 0, count)
                if r:
                    bars = [{
                        'date': k['datetime'],
                        'open': k['open'],
                        'high': k['high'],
                        'low': k['low'],
                        'close': k['close'],
                        'volume': k['vol'],
                        'amount': k.get('amount', 0),
                    } for k in r]
                    # 写入缓存
                    if period in (4, 5, 6, 8, 9):
                        self._set_kline_cache(code, period, count, bars)
            except Exception as e:
                logger.debug(f"pytdx batch kline failed ({code}): {e}")
            finally:
                try:
                    api.disconnect()
                except Exception:
                    pass
            if not bars:
                # pytdx 返回空（被风控）→ HTTP 回退
                bars = self._resolve_kline_with_http(code, period, count)
            return code, bars

        if need_fetch:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_fetch_one, c): c for c in need_fetch}
                for future in as_completed(futures):
                    try:
                        code, bars = future.result(timeout=15)
                        if bars:
                            results[code] = bars
                    except Exception:
                        pass

            for code in need_fetch:
                if code not in results:
                    fallback = self._get_kline_fallback(code, period, count)
                    if fallback:
                        results[code] = fallback

        return results

    # ── 指数行情 ────────────────────────────────────────

    def get_index_quotes(self) -> list[dict]:
        """获取大盘指数"""
        indices = [
            (1, '000001', '上证指数'),
            (0, '399001', '深证成指'),
            (0, '399006', '创业板指'),
            (1, '000016', '上证50'),
            (1, '000300', '沪深300'),
            (0, '399005', '中小板指'),
            (1, '000688', '科创50'),
            (1, '000905', '中证500'),
            (1, '000852', '中证1000'),
        ]
        api = self.get_api()
        if not api:
            return []
        params = [(m, c) for m, c, _ in indices]
        try:
            result = api.get_security_quotes(params)
            if not result:
                return []
            name_map = {c: n for _, c, n in indices}
            return [{
                'code': q['code'],
                'name': name_map.get(q['code'], q['code']),
                'price': q['price'],
                'last_close': q['last_close'],
                'change': round(q['price'] - q['last_close'], 2),
                'change_pct': round((q['price'] - q['last_close']) / q['last_close'] * 100, 2) if q['last_close'] else 0,
                'volume': q['vol'],
                'amount': q['amount'],
            } for q in result]
        except Exception as e:
            logger.debug(f"pytdx index quotes failed: {e}")
            return []

    # ── 市场宽度 ────────────────────────────────────────

    def get_market_breadth(self) -> dict:
        """获取市场宽度(涨跌家数) - 批量获取两大市场股票统计"""
        api = self.get_api()
        if not api:
            return {'up': 0, 'down': 0, 'flat': 0, 'total': 0}
        up = down = flat = 0
        for market in [MARKET_SH, MARKET_SZ]:
            all_stocks = []
            for start in [0, 1000, 2000, 3000, 4000]:
                try:
                    stocks = api.get_security_list(market, start)
                    if stocks:
                        all_stocks.extend(stocks)
                    else:
                        break
                except Exception:
                    break
            if not all_stocks:
                continue
            a_stocks = [s for s in all_stocks if s['code'][:1] in ('6', '0', '3')]
            batch_size = 80
            for i in range(0, min(len(a_stocks), 3000), batch_size):
                batch = a_stocks[i:i + batch_size]
                params = [(market, s['code']) for s in batch]
                try:
                    quotes = api.get_security_quotes(params)
                except Exception:
                    continue
                if quotes:
                    for q in quotes:
                        if q['last_close'] == 0:
                            continue
                        if q['price'] > q['last_close']:
                            up += 1
                        elif q['price'] < q['last_close']:
                            down += 1
                        else:
                            flat += 1
        return {'up': up, 'down': down, 'flat': flat, 'total': up + down + flat}

    # ── 成交明细与资金流向 ───────────────────────────────

    def get_transaction_data(self, code: str, count: int = 1000) -> list[dict]:
        """获取成交明细数据 - 用于资金流向分析"""
        api = self.get_api()
        if not api:
            return []
        market = get_market(code)
        all_data = []
        for start in range(0, count, 2000):
            try:
                data = api.get_transaction_data(market, code, start, min(2000, count - start))
                if not data:
                    break
                all_data.extend(data)
                if len(data) < 2000:
                    break
            except Exception:
                break
        return all_data

    def get_capital_flow(self, code: str) -> dict:
        """基于成交明细计算资金流向"""
        txns = self.get_transaction_data(code, count=2000)
        if not txns:
            return {}

        big_buy = big_sell = mid_buy = mid_sell = small_buy = small_sell = 0
        for t in txns:
            vol = t.get('vol', 0)
            price = t.get('price', 0)
            amount = vol * price * 100
            buy_or_sell = t.get('buyorsell', 2)

            if amount >= 500000:
                if buy_or_sell == 0:
                    big_buy += amount
                elif buy_or_sell == 1:
                    big_sell += amount
            elif amount >= 100000:
                if buy_or_sell == 0:
                    mid_buy += amount
                elif buy_or_sell == 1:
                    mid_sell += amount
            else:
                if buy_or_sell == 0:
                    small_buy += amount
                elif buy_or_sell == 1:
                    small_sell += amount

        def to_yi(v):
            return round(v / 1e8, 2)

        return {
            'big_buy': to_yi(big_buy),
            'big_sell': to_yi(big_sell),
            'big_net': to_yi(big_buy - big_sell),
            'mid_buy': to_yi(mid_buy),
            'mid_sell': to_yi(mid_sell),
            'mid_net': to_yi(mid_buy - mid_sell),
            'small_buy': to_yi(small_buy),
            'small_sell': to_yi(small_sell),
            'small_net': to_yi(small_buy - small_sell),
            'main_net': to_yi(big_buy - big_sell + mid_buy - mid_sell),
            'sample_count': len(txns),
        }

    def get_tencent_capital_flow(self, code: str) -> dict:
        """使用腾讯API获取个股资金流向(基于内外盘真实数据，覆盖全天交易)。

        注意：腾讯API仅提供外盘(主动买入)/内盘(主动卖出)，无法区分大/中/小单。
        返回的big/mid/small字段为None，仅返回真实的内外盘数据。
        如需大/中/小单细分，请使用东财push2接口 (EastMoneySource.get_stock_capital_flow)。
        """
        import requests as req

        prefix = 'sh' if code.startswith('6') else 'sz'
        url = f"https://qt.gtimg.cn/q={prefix}{code}"

        try:
            r = req.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            for line in r.text.strip().split('\n'):
                if '=' not in line:
                    continue
                parts = line.split('=', 1)
                data_str = parts[-1].strip('"').replace('\\', '')
                fields = data_str.split('~')

                if len(fields) < 60:
                    return {}

                price = float(fields[3])
                outer_disk = int(fields[7])   # 外盘(主动买入)
                inner_disk = int(fields[8])   # 内盘(主动卖出)
                change_pct = float(fields[32])

                # 计算内外盘金额(亿)，基于真实数据
                buy_amount_yi = round(outer_disk * price * 100 / 1e8, 2)
                sell_amount_yi = round(inner_disk * price * 100 / 1e8, 2)

                return {
                    # 腾讯API无法区分大/中/小单，返回None（不虚构数据）
                    'big_buy': None,
                    'big_sell': None,
                    'big_net': None,
                    'mid_buy': None,
                    'mid_sell': None,
                    'mid_net': None,
                    'small_buy': None,
                    'small_sell': None,
                    'small_net': None,
                    # 真实数据：外盘(主动买入) - 内盘(主动卖出)
                    'outer_disk_buy': buy_amount_yi,
                    'inner_disk_sell': sell_amount_yi,
                    'main_net': round(buy_amount_yi - sell_amount_yi, 2),
                    'change_pct': change_pct,
                    'source': '腾讯API(内外盘)',
                }
        except Exception as e:
            logger.debug(f"pytdx tencent capital flow failed: {e}")
            return {}

    # ── 板块数据 ────────────────────────────────────────

    def get_sector_list(self) -> list[dict]:
        """获取行业板块列表"""
        api = self.get_api()
        if not api:
            return []
        try:
            blocks = api.get_and_parse_block_info(r'block\block.dat')
            if blocks:
                return [{'code': b.get('code', ''), 'name': b.get('name', ''), 'change_pct': b.get('change', 0)} for b in blocks]
        except Exception as e:
            logger.debug(f"pytdx sector list failed: {e}")
        return []

    # ── 全市场股票列表 ───────────────────────────────────

    def get_all_a_stock_codes(self) -> list[dict]:
        """获取全部A股代码列表(沪市+深市)
        
        关键修复: pytdx服务器屏蔽了get_security_list的沪市数据，
        改用AKShare获取全量A股代码+名称映射，再用pytdx拉行情。
        """
        # ── 优先用东财全市场获取A股列表（无限制、完整覆盖）───
        try:
            from app.core.data_sources import EastMoneySource
            market_data = EastMoneySource.get_full_market()
            if market_data and len(market_data) > 0:
                stocks = []
                for row in market_data:
                    code = str(row.get('f12', ''))
                    name = str(row.get('f14', ''))
                    if not code or len(code) != 6:
                        continue
                    # 只保留A股：沪市6开头，深市0/3开头
                    market = MARKET_SH if code.startswith('6') else MARKET_SZ
                    if market == MARKET_SZ and code[0] not in ('0', '3'):
                        continue
                    stocks.append({'market': market, 'code': code, 'name': name})
                return stocks
        except Exception as e:
            logger.debug(f"东财股票列表获取失败: {e}")

        # ── 东财失败时回退到pytdx（仅深市可用）───
        api = self.get_api()
        if not api:
            return []
        all_stocks = []
        for market in [MARKET_SH, MARKET_SZ]:
            found_any = False
            for start_offset in [0, 1, 10, 100, 500]:
                for start in range(start_offset, 10000, 1000):
                    try:
                        stocks = api.get_security_list(market, start)
                        if not stocks:
                            continue
                        found_any = True
                        for s in stocks:
                            code = s.get('code', '')
                            name = s.get('name', '')
                            if not code or len(code) != 6:
                                continue
                            if market == MARKET_SH and code.startswith('6'):
                                all_stocks.append({'market': market, 'code': code, 'name': name})
                            elif market == MARKET_SZ:
                                if code[0] in ('0', '3') and not code.startswith(('399', '880', '15', '16', '50')):
                                    all_stocks.append({'market': market, 'code': code, 'name': name})
                    except Exception:
                        continue
                if found_any:
                    break

        # 去重
        seen = set()
        unique = []
        for s in all_stocks:
            if s['code'] not in seen:
                seen.add(s['code'])
                unique.append(s)
        return unique

    # ── 批量行情（优化版）───────────────────────────────

    def get_batch_quotes(self, codes: list[str], batch_size: int = 80) -> list[dict]:
        """批量获取行情(自动分页+连接池复用+重试)"""
        results = []
        api = self.get_api()
        if not api:
            return []
        for i in range(0, len(codes), batch_size):
            batch_codes = codes[i:i + batch_size]
            params = [(get_market(c), c) for c in batch_codes]
            success = False
            for attempt in range(2):
                try:
                    quotes = api.get_security_quotes(params)
                    if quotes:
                        results.extend([self._parse_quote(q) for q in quotes])
                    success = True
                    break
                except Exception:
                    # 连接断开，重建池并重试
                    api = self.get_api()
                    if not api:
                        return results
            if not success and len(batch_codes) > 0:
                logger.debug(f"pytdx batch_quotes 批次 {i//batch_size} 获取失败")
        return results


# 全局实例
pytdx_data = PytdxData()


class FullMarketCache:
    """全市场缓存 - 避免重复获取"""
    _all_stocks: list[dict] | None = None
    _quotes_cache: dict[str, dict] | None = None
    _cache_time: float = 0

    @classmethod
    def get_all_stocks(cls) -> list[dict]:
        """获取全部A股列表(缓存5分钟)"""
        now = time.time()
        
        from app.core.constants import FULL_MARKET_CACHE_TTL
        if cls._all_stocks and (now - cls._cache_time) < FULL_MARKET_CACHE_TTL:
            return cls._all_stocks
        stocks = pytdx_data.get_all_a_stock_codes()
        if stocks:
            cls._all_stocks = stocks
            cls._cache_time = now
        return cls._all_stocks or []

    @classmethod
    def get_quote_map(cls) -> dict[str, dict]:
        """获取全部A股行情映射(缓存5分钟)"""
        now = time.time()
        
        from app.core.constants import FULL_MARKET_CACHE_TTL
        if cls._quotes_cache and (now - cls._cache_time) < FULL_MARKET_CACHE_TTL:
            return cls._quotes_cache
        stocks = cls.get_all_stocks()
        codes = [s['code'] for s in stocks]
        quotes = pytdx_data.get_batch_quotes(codes, batch_size=80)
        valid = [q for q in quotes if 0.5 < q.get('price', 0) < 10000]
        cls._quotes_cache = {q['code']: q for q in valid}
        cls._cache_time = now
        return cls._quotes_cache or {}

    @classmethod
    def get_top_by_change(cls, top_n: int = 50) -> list[dict]:
        """按涨跌幅排序获取TOP N"""
        qmap = cls.get_quote_map()
        sorted_quotes = sorted(qmap.values(), key=lambda x: abs(x.get('change_pct', 0)), reverse=True)
        return sorted_quotes[:top_n]

    @classmethod
    def get_by_amount(cls, top_n: int = 100) -> list[dict]:
        """按成交额排序获取TOP N"""
        qmap = cls.get_quote_map()
        sorted_quotes = sorted(qmap.values(), key=lambda x: x.get('amount', 0), reverse=True)
        return sorted_quotes[:top_n]


market_cache = FullMarketCache()


# ===== PytdxData 全局单例 =====

def _pytdx_singleton():
    """获取 PytdxData 全局单例，复用连接池"""
    return pytdx_data




