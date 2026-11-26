"""缓存层单元测试 - 不需要 Redis"""
import os
import sys
import time

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-test-only-12345678")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_sqlite_cache_get_set_roundtrip():
    """_SqliteCache: setex 后 get 应返回原值"""
    from app.core.cache import _SqliteCache
    cache = _SqliteCache()
    cache.setex("k1", 60, '{"a": 1, "b": [1, 2]}')
    assert cache.get("k1") == '{"a": 1, "b": [1, 2]}'
    cache.delete("k1")


def test_sqlite_cache_ttl_expiry():
    """_SqliteCache: ttl 过期后应返回 None"""
    from app.core.cache import _SqliteCache
    cache = _SqliteCache()
    cache.setex("k2", 1, "v")
    assert cache.get("k2") == "v"
    time.sleep(1.2)
    assert cache.get("k2") is None


def test_sqlite_cache_delete():
    """_SqliteCache: delete 后 get 应返回 None"""
    from app.core.cache import _SqliteCache
    cache = _SqliteCache()
    cache.setex("k3", 60, "v")
    assert cache.get("k3") == "v"
    n = cache.delete("k3")
    assert n == 1
    assert cache.get("k3") is None


def test_sqlite_cache_get_stale():
    """_SqliteCache: get_stale 不应检查 TTL"""
    from app.core.cache import _SqliteCache
    cache = _SqliteCache()
    cache.setex("k4", 1, "v")
    time.sleep(1.2)
    assert cache.get("k4") is None
    assert cache.get_stale("k4") == "v"
    cache.delete("k4")


def test_sqlite_cache_keys():
    """_SqliteCache: keys 应支持通配符匹配"""
    from app.core.cache import _SqliteCache
    cache = _SqliteCache()
    cache.setex("ns:a", 60, "1")
    cache.setex("ns:b", 60, "2")
    cache.setex("other:c", 60, "3")
    keys = cache.keys("ns:*")
    assert "ns:a" in keys
    assert "ns:b" in keys
    assert "other:c" not in keys
    cache.delete("ns:a", "ns:b", "other:c")


def test_cache_set_get_via_public_api():
    """公开 API cache_set/cache_get 在 SQLite 回退场景下应保持原值"""
    from app.core.cache import cache_set, cache_get, _backend
    original = _backend._redis
    _backend._redis = None
    try:
        test_data = {"name": "测试", "values": [1, 2, 3]}
        cache_set("test_key", test_data, ttl=60)
        assert cache_get("test_key") == test_data
        cache_set("test_key", None, ttl=60)
        assert cache_get("test_key") is None
    finally:
        _backend._redis = original
