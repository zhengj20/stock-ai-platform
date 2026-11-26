import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Optional, Callable

import redis
from sqlalchemy import text

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# ════════════════════════════════════════════════════════
# Stale-While-Revalidate (SWR) 后台刷新机制
# ════════════════════════════════════════════════════════
# 全局后台刷新线程池，避免每个请求都创建新线程
_swr_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="swr-refresh")
# 防止同一 key 重复刷新：key -> Lock
_swr_refresh_locks: dict[str, threading.Lock] = {}
_swr_locks_guard = threading.Lock()
_SWR_LOCKS_MAX = 200  # 锁字典上限，超出时清理未被持有的锁


def _get_swr_lock(key: str) -> threading.Lock:
    """获取或创建指定 key 的刷新锁"""
    with _swr_locks_guard:
        lock = _swr_refresh_locks.get(key)
        if lock is not None:
            return lock
        # 字典过大时先清理未被持有的锁
        if len(_swr_refresh_locks) > _SWR_LOCKS_MAX:
            stale_keys = [k for k, v in _swr_refresh_locks.items() if not v.locked()]
            for k in stale_keys:
                _swr_refresh_locks.pop(k, None)
        lock = threading.Lock()
        _swr_refresh_locks[key] = lock
        return lock


def _fire_background_refresh(
    full_key: str,
    fetch_fn: Callable[[], any],
    ttl: int,
):
    """后台异步刷新缓存（不阻塞当前请求）"""
    def _do_refresh():
        try:
            result = fetch_fn()
            if result is not None:
                serialized = json.dumps(result, ensure_ascii=False, default=str)
                _backend.setex(full_key, ttl, serialized)
                logger.debug(f"SWR 后台刷新成功: {full_key}")
        except Exception as e:
            logger.debug(f"SWR 后台刷新失败 [{full_key}]: {e}")

    _swr_executor.submit(_do_refresh)


def swr_cache(
    key: str,
    namespace: str,
    fetch_fn: Callable[[], any],
    ttl: int,
) -> any:
    """Stale-While-Revalidate 缓存模式

    行为：
    1. 缓存命中 → 直接返回（ms 级）
    2. 缓存未命中但有 stale 数据 → 立即返回旧数据，后台异步刷新
    3. 完全无缓存 → 阻塞拉取并写入缓存

    Redis 实现：
    - stale key 的 TTL 是主 key 的 2 倍
    - 当主 key 过期但 stale key 仍在时，返回 stale 数据并触发后台刷新

    Args:
        key: 缓存键名
        namespace: 命名空间
        fetch_fn: 数据拉取函数（同步，无参数）
        ttl: 缓存过期时间（秒）

    Returns:
        缓存数据或 stale 数据；完全未命中时阻塞拉取后返回
    """
    full_key = f"{namespace}:{key}"

    # 1. 检查新鲜缓存
    try:
        raw = _backend.get(full_key)
        if raw is not None:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug(f"SWR 缓存读取失败 [{full_key}]: {e}")

    # 2. 尝试获取 stale 数据（不检查 TTL）
    #    Redis 实现：读取 _stale:{full_key}，TTL 是主 key 的 2 倍
    stale_data = cache_get_stale(key, namespace)
    if stale_data is not None:
        # 有旧数据：立即返回，后台异步刷新
        # 使用锁防止同一 key 的并发刷新
        refresh_lock = _get_swr_lock(full_key)
        if refresh_lock.acquire(blocking=False):
            try:
                logger.debug(f"SWR 触发后台刷新 [{full_key}]")
                _fire_background_refresh(full_key, fetch_fn, ttl)
            finally:
                refresh_lock.release()
        return stale_data

    # 3. 完全无缓存：阻塞拉取（最后一次兜底）
    logger.debug(f"SWR 无缓存，阻塞拉取 [{full_key}]")
    result = fetch_fn()
    if result is not None:
        cache_set(key, result, ttl, namespace)
    return result


def _get_redis_client() -> Optional[redis.Redis]:
    """获取 Redis 客户端（启动时快速探测 + 运行时自动重连）
    
    注意：初始探测不使用 retry_on_timeout，避免 Redis 未启动时阻塞应用启动。
    运行时操作失败时会尝试重连（见 _CacheBackend.try_reconnect_redis）。
    
    REDIS_REQUIRED=True 时：连接失败直接抛出异常，阻止应用启动。
    """
    try:
        client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3 if settings.REDIS_REQUIRED else 1,
            socket_timeout=3 if settings.REDIS_REQUIRED else 2,
            retry_on_timeout=settings.REDIS_REQUIRED,
        )
        client.ping()
        logger.info("Redis 连接成功")
        return client
    except Exception as e:
        if settings.REDIS_REQUIRED:
            logger.critical(f"Redis 连接失败且 REDIS_REQUIRED=True，无法启动: {e}")
            raise RuntimeError(f"Redis 连接失败: {e}") from e
        logger.warning(f"Redis 不可用（{type(e).__name__}），降级为 SQLite 共享缓存: {e}")
        return None


_redis = None  # 延迟到首次使用时再连接，避免4个worker各等1秒
_redis_failed = False  # 标记是否曾经失败过，用于控制重试频率


def _get_redis_lazy():
    """懒加载 Redis 连接：支持自动重连"""
    global _redis, _redis_failed

    # 如果从未尝试过，立即尝试连接
    if _redis is None and not _redis_failed:
        client = _get_redis_client()
        if client:
            _redis = client
            return client
        else:
            _redis_failed = True
            return None

    # 如果之前失败过，每隔30秒尝试重连一次
    if _redis_failed:
        import time as _time
        current_time = _time.time()
        if not hasattr(_get_redis_lazy, '_last_retry') or (current_time - _get_redis_lazy._last_retry) > 30:
            _get_redis_lazy._last_retry = current_time
            client = _get_redis_client()
            if client:
                _redis = client
                _redis_failed = False
                logger.info("Redis 重连成功")
                return client

    return _redis


class _SqliteCache:
    """SQLite 共享缓存（多 worker 共享，替代进程内内存缓存）

    利用 app.db 已有的 WAL 模式，支持多 worker 并发读写。
    接口对齐 redis-py：setex 接收字符串，get 返回字符串。
    过期清理：读取时惰性清理 + 写入时概率触发定期清理。
    """

    _CLEANUP_PROBABILITY = 0.02  # 每次 setex 有 2% 概率触发清理
    _MAX_EXPIRED_BATCH = 500     # 单次最多清理 500 条过期记录

    def __init__(self):
        from app.core.database import engine
        self._engine = engine
        self._write_count = 0
        self._init_table()

    def _init_table(self):
        try:
            with self._engine.connect() as conn:
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS _cache_store ("
                    "  key TEXT PRIMARY KEY,"
                    "  value TEXT NOT NULL,"
                    "  expire_at REAL NOT NULL"
                    ")"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_cache_expire ON _cache_store(expire_at)"
                ))
                conn.commit()
        except Exception as e:
            logger.warning(f"SQLite 缓存表初始化失败: {e}")

    def _cleanup_expired(self):
        try:
            with self._engine.connect() as conn:
                conn.execute(
                    text("DELETE FROM _cache_store WHERE rowid IN ("
                         "  SELECT rowid FROM _cache_store WHERE expire_at <= :now LIMIT :batch"
                         ")"),
                    {"now": time.time(), "batch": self._MAX_EXPIRED_BATCH},
                )
                conn.commit()
        except Exception:
            pass

    def get(self, key: str) -> Optional[str]:
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text("SELECT value, expire_at FROM _cache_store WHERE key = :key"),
                    {"key": key},
                ).fetchone()
                if row is None:
                    return None
                value, expire_at = row
                if time.time() >= expire_at:
                    return None
                return value
        except Exception as e:
            logger.debug(f"SQLite 缓存读取失败 [{key}]: {e}")
            return None

    def get_stale(self, key: str) -> Optional[str]:
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text("SELECT value FROM _cache_store WHERE key = :key"),
                    {"key": key},
                ).fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.debug(f"SQLite 缓存读取失败 [{key}]: {e}")
            return None

    def setex(self, key: str, ttl: int, value: str):
        expire_at = time.time() + ttl
        try:
            with self._engine.connect() as conn:
                conn.execute(
                    text(
                        "INSERT OR REPLACE INTO _cache_store (key, value, expire_at) "
                        "VALUES (:key, :value, :expire_at)"
                    ),
                    {"key": key, "value": value, "expire_at": expire_at},
                )
                conn.commit()
            # 概率触发过期清理，避免 _cache_store 表无限增长
            self._write_count += 1
            if self._write_count % 50 == 0:
                import random
                if random.random() < self._CLEANUP_PROBABILITY:
                    self._cleanup_expired()
        except Exception as e:
            logger.debug(f"SQLite 缓存写入失败 [{key}]: {e}")

    def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        try:
            with self._engine.connect() as conn:
                count = 0
                for key in keys:
                    result = conn.execute(
                        text("DELETE FROM _cache_store WHERE key = :key"),
                        {"key": key},
                    )
                    count += result.rowcount
                conn.commit()
                return count
        except Exception as e:
            logger.debug(f"SQLite 缓存删除失败: {e}")
            return 0

    def keys(self, pattern: str) -> list[str]:
        import fnmatch
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(text("SELECT key FROM _cache_store")).fetchall()
                all_keys = [row[0] for row in rows]
                return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]
        except Exception as e:
            logger.debug(f"SQLite 缓存 keys 失败: {e}")
            return []


class _CacheBackend:
    """统一缓存后端 - 自动选择 Redis 或 SQLite 共享缓存

    Redis stale 机制说明：
    - Redis 的 GET 命令会自动删除过期 key，导致 SWR 的 stale 获取失效
    - 解决方案：使用单独的 `_stale:{key}` 存储可能过期的数据
    - setex 时同时写入主 key 和 stale key（stale key 的 TTL 是主 key 的 2 倍）
    - get_stale 优先读 stale key，实现 SWR 语义
    """

    def __init__(self, redis_client: Optional[redis.Redis]):
        self._redis = redis_client
        self._fallback = _SqliteCache()
        self._reconnect_lock = threading.Lock()
        self._redis_checked = False  # 是否已尝试连接过 Redis

    def try_reconnect_redis(self) -> bool:
        """尝试重新连接 Redis（在操作失败时调用）"""
        with self._reconnect_lock:
            if self._redis is not None:
                return True
            new_client = _get_redis_lazy()
            if new_client is not None:
                self._redis = new_client
                logger.info("Redis 自动重连成功")
                return True
        return False

    def _ensure_redis_checked(self):
        """首次操作时检查 Redis 可用性"""
        if not self._redis_checked:
            self._redis_checked = True
            self._redis = _get_redis_lazy()

    @property
    def is_redis(self) -> bool:
        return self._redis is not None

    def get(self, key: str) -> Optional[str]:
        """获取新鲜数据（检查 TTL）"""
        self._ensure_redis_checked()
        if self._redis:
            try:
                return self._redis.get(key)
            except Exception as e:
                logger.debug(f"Redis get 失败，尝试重连: {e}")
                if self.try_reconnect_redis():
                    try:
                        return self._redis.get(key)
                    except Exception:
                        pass
        return self._fallback.get(key)

    def get_stale(self, key: str) -> Optional[str]:
        """获取可能过期的数据（用于 SWR 语义）

        Redis 实现：读取 stale:{key}（TTL 是主 key 的 2 倍）
        SQLite 实现：直接读取，忽略 TTL
        """
        self._ensure_redis_checked()
        if self._redis:
            stale_key = f"_stale:{key}"
            try:
                return self._redis.get(stale_key)
            except Exception as e:
                logger.debug(f"Redis get_stale 失败，尝试重连: {e}")
                if self.try_reconnect_redis():
                    try:
                        return self._redis.get(stale_key)
                    except Exception:
                        pass
        return self._fallback.get_stale(key)

    def setex(self, key: str, ttl: int, value: str):
        """写入缓存（同时写入 stale key，TTL 翻倍）"""
        self._ensure_redis_checked()
        if self._redis:
            try:
                pipe = self._redis.pipeline()
                pipe.setex(key, ttl, value)
                # stale key 的 TTL 是主 key 的 2 倍，用于 SWR
                stale_ttl = max(ttl * 2, ttl + 60)  # 至少多 60 秒
                pipe.setex(f"_stale:{key}", stale_ttl, value)
                pipe.execute()
                return
            except Exception as e:
                logger.debug(f"Redis setex 失败，尝试重连: {e}")
                if self.try_reconnect_redis():
                    try:
                        pipe = self._redis.pipeline()
                        pipe.setex(key, ttl, value)
                        stale_ttl = max(ttl * 2, ttl + 60)
                        pipe.setex(f"_stale:{key}", stale_ttl, value)
                        pipe.execute()
                        return
                    except Exception:
                        pass
        self._fallback.setex(key, ttl, value)

    def delete(self, *keys: str) -> int:
        """删除缓存（同时删除对应的 stale key）"""
        self._ensure_redis_checked()
        count = 0
        if self._redis:
            try:
                # 删除主 key 和 stale key
                stale_keys = [f"_stale:{k}" for k in keys]
                all_keys = list(keys) + stale_keys
                count = self._redis.delete(*all_keys)
                return count
            except Exception as e:
                logger.debug(f"Redis delete 失败，尝试重连: {e}")
                if self.try_reconnect_redis():
                    try:
                        stale_keys = [f"_stale:{k}" for k in keys]
                        all_keys = list(keys) + stale_keys
                        count = self._redis.delete(*all_keys)
                        return count
                    except Exception:
                        pass
        return self._fallback.delete(*keys)

    def keys(self, pattern: str) -> list[str]:
        """获取匹配的 key（过滤掉 _stale: 前缀的内部 key）"""
        self._ensure_redis_checked()
        if self._redis:
            try:
                all_keys = self._redis.keys(pattern)
                # 过滤掉 _stale: 前缀的 key，只返回业务 key
                return [k for k in all_keys if not k.startswith("_stale:")]
            except Exception as e:
                logger.debug(f"Redis keys 失败，尝试重连: {e}")
                if self.try_reconnect_redis():
                    try:
                        all_keys = self._redis.keys(pattern)
                        return [k for k in all_keys if not k.startswith("_stale:")]
                    except Exception:
                        pass
        return self._fallback.keys(pattern)


_backend = _CacheBackend(None)  # Redis 延迟初始化


# ════════════════════════════════════════════════════════
# 命名空间常量
# ════════════════════════════════════════════════════════

NS_MARKET = "market"
NS_STOCK = "stock"
NS_FINANCIAL = "financial"
NS_STOCKLIST = "stocklist"
NS_CAPITAL_FLOW = "capital_flow"
NS_KLINE = "kline"
NS_DRAGON = "dragon"
NS_DAILY_REPORT = "daily_report"
NS_NEWS = "news"
NS_NLP = "nlp"
NS_STRATEGY = "strategy"


_CACHE_MISS = object()


def cache_get(key, namespace="default"):
    """从缓存获取数据"""
    full_key = f"{namespace}:{key}"
    try:
        raw = _backend.get(full_key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug(f"缓存读取失败 [{full_key}]: {e}")
        return None


def cache_get_stale(key, namespace="default"):
    """从缓存获取数据（不检查TTL，即使过期也返回）"""
    full_key = f"{namespace}:{key}"
    try:
        raw = _backend.get_stale(full_key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug(f"缓存读取失败 [{full_key}]: {e}")
        return None


def cache_set(key, value, ttl=300, namespace="default"):
    """写入缓存"""
    full_key = f"{namespace}:{key}"
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        _backend.setex(full_key, ttl, serialized)
        return True
    except (TypeError, ValueError) as e:
        logger.debug(f"缓存写入失败 [{full_key}]: {e}")
        return False


def cache_delete(key, namespace="default"):
    """删除指定缓存"""
    full_key = f"{namespace}:{key}"
    return _backend.delete(full_key)


def cache_invalidate(pattern, namespace="default"):
    """按模式清除缓存（支持通配符 *）"""
    full_pattern = f"{namespace}:{pattern}"
    keys = _backend.keys(full_pattern)
    if not keys:
        return 0
    return _backend.delete(*keys)


def cached(ttl=300, namespace="default", key_prefix=""):
    """装饰器：自动缓存函数返回值（使用哨兵区分未命中和 None）"""
    def decorator(func):
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}{func.__name__}:{_hash_args(args, kwargs)}"
            result = _cache_get_sentinel(cache_key, namespace)
            if result is not _CACHE_MISS:
                return result
            data = func(*args, **kwargs)
            _cache_set_sentinel(cache_key, data, ttl, namespace)
            return data

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}{func.__name__}:{_hash_args(args, kwargs)}"
            result = _cache_get_sentinel(cache_key, namespace)
            if result is not _CACHE_MISS:
                return result
            data = await func(*args, **kwargs)
            _cache_set_sentinel(cache_key, data, ttl, namespace)
            return data

        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def _hash_args(args, kwargs):
    """生成参数指纹"""
    import hashlib
    raw = repr((args, sorted(kwargs.items())))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


# Sentinel-based internal cache functions for the @cached decorator
def _cache_get_sentinel(key, namespace="default"):
    """返回 _CACHE_MISS 表示未命中，否则返回实际值（包括 None）"""
    full_key = f"{namespace}:{key}"
    try:
        raw = _backend.get(full_key)
        if raw is None:
            return _CACHE_MISS
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug(f"缓存读取失败 [{full_key}]: {e}")
        return _CACHE_MISS


def _cache_set_sentinel(key, value, ttl=300, namespace="default"):
    """写入缓存（支持 None 值）"""
    full_key = f"{namespace}:{key}"
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        _backend.setex(full_key, ttl, serialized)
        return True
    except (TypeError, ValueError) as e:
        logger.debug(f"缓存写入失败 [{full_key}]: {e}")
        return False


def invalidate_pattern(pattern):
    """兼容旧 API - 按模式清除缓存"""
    return _backend.delete(*_backend.keys(pattern))



