"""JWT 鉴权测试"""
import os
import sys
import time
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-test-only-12345678")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_access_token_roundtrip():
    """签发的 access token 应能正确解码"""
    from app.core.auth import create_access_token, decode_token
    token = create_access_token({"sub": "42"})
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_refresh_token_roundtrip():
    from app.core.auth import create_refresh_token, decode_token
    token = create_refresh_token({"sub": "7"})
    payload = decode_token(token)
    assert payload["sub"] == "7"
    assert payload["type"] == "refresh"


def test_invalid_token_returns_none():
    from app.core.auth import decode_token
    assert decode_token("not.a.real.token") is None
    assert decode_token("") is None


def test_password_hash_verify():
    from app.core.auth import get_password_hash, verify_password
    h = get_password_hash("mypassword")
    assert verify_password("mypassword", h) is True
    assert verify_password("wrong", h) is False


def test_is_user_expired_cases():
    """is_user_expired：非管理员且已过期→True；管理员/永不过期/未过期→False"""
    from datetime import datetime, timedelta
    from app.core.auth import is_user_expired
    from app.models.user import User

    assert is_user_expired(User(role="normal", expiry_date=datetime.now() - timedelta(days=1))) is True
    assert is_user_expired(User(role="normal", expiry_date=datetime.now() + timedelta(days=1))) is False
    assert is_user_expired(User(role="normal", expiry_date=None)) is False
    assert is_user_expired(User(role="admin", expiry_date=datetime.now() - timedelta(days=1))) is False


def test_expired_user_login_refresh_and_api_rejected():
    """过期账号：登录403、刷新401、业务接口（即使持有效token）401，且均提示到期"""
    from datetime import datetime, timedelta
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.database import SessionLocal
    from app.core.auth import get_password_hash, create_refresh_token, create_access_token
    from app.models.user import User

    username = "test_expired_account"
    password = "Test1234a"
    db = SessionLocal()
    try:
        # 清理历史残留，确保测试可重复
        db.query(User).filter(User.username == username).delete()
        db.commit()

        user = User(
            username=username,
            password_hash=get_password_hash(password),
            role="normal",
            status="active",
            expiry_start_date=datetime.now() - timedelta(days=30),
            expiry_date=datetime.now() - timedelta(days=1),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        client = TestClient(app)

        # 1. 登录应被拒绝（403 + 到期提示）
        r = client.post(
            "/api/v1/auth/login",
            data={"username": username, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 403
        assert "到期" in r.json()["detail"]

        # 2. 刷新token应被拒绝（401 + 到期提示）
        refresh = create_refresh_token({"sub": str(user_id)})
        r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert r2.status_code == 401
        assert "到期" in r2.json()["detail"]

        # 3. 过期账号即使持有未过期的access token，业务接口也应拒绝（401 + 到期提示）
        access = create_access_token({"sub": str(user_id)})
        r3 = client.get("/api/v1/market/trading-date", headers={"Authorization": f"Bearer {access}"})
        assert r3.status_code == 401
        assert "到期" in r3.json()["detail"]

        # 4. 未携带token调用业务接口应401
        r4 = client.get("/api/v1/market/trading-date")
        assert r4.status_code == 401
    finally:
        db.query(User).filter(User.username == username).delete()
        db.commit()
        db.close()
