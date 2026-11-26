"""配置模块测试 - 验证 SECRET_KEY 必填校验"""
import os
import sys
import pytest


def test_secret_key_required():
    """未设置 SECRET_KEY 时应抛出 ValueError"""
    # 清除缓存
    from app.core import config as cfg_mod
    cfg_mod.get_settings.cache_clear()

    old = os.environ.pop("SECRET_KEY", None)
    os.environ["SECRET_KEY"] = ""
    try:
        with pytest.raises(Exception) as exc:
            cfg_mod.Settings()
        assert "SECRET_KEY" in str(exc.value)
    finally:
        if old is not None:
            os.environ["SECRET_KEY"] = old
        else:
            os.environ.pop("SECRET_KEY", None)
        cfg_mod.get_settings.cache_clear()


def test_secret_key_present():
    """设置 SECRET_KEY 后应能正常初始化"""
    from app.core import config as cfg_mod
    cfg_mod.get_settings.cache_clear()
    os.environ["SECRET_KEY"] = "a" * 48
    try:
        s = cfg_mod.Settings()
        assert s.SECRET_KEY == "a" * 48
        assert s.DATABASE_URL.startswith("sqlite:///")
    finally:
        cfg_mod.get_settings.cache_clear()
