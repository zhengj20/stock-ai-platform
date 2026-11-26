"""配额服务测试"""
import os
import sys
import pytest
from datetime import date

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-test-only-12345678")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def db_session():
    """内存 SQLite session"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base
    from app.models.user import User
    from app.models.quota import DailyQuota, QuotaUsage

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # 初始化数据
    session.add(DailyQuota(role="normal", max_daily=3))
    session.add(DailyQuota(role="admin", max_daily=9999))
    user = User(username="tester", password_hash="x", role="normal", status="active")
    session.add(user)
    session.commit()
    yield session
    session.close()


def test_check_and_consume_decrements(db_session):
    from app.services.quota_service import check_and_consume, get_quota_info
    from app.models.user import User
    user = db_session.query(User).filter_by(username="tester").first()
    assert user is not None

    allowed, info = check_and_consume(db_session, user)
    assert allowed is True
    assert info["used"] == 1
    assert info["limit"] == 3

    db_session.expire_all()
    user = db_session.query(User).filter_by(username="tester").first()
    allowed, info = check_and_consume(db_session, user)
    assert info["used"] == 2


def test_check_and_consume_exhausts(db_session):
    from app.services.quota_service import check_and_consume
    from app.models.user import User
    user = db_session.query(User).filter_by(username="tester").first()
    for _ in range(3):
        allowed, _ = check_and_consume(db_session, user)
        db_session.expire_all()
        user = db_session.query(User).filter_by(username="tester").first()
        assert allowed is True
    # 第四次应被拒
    allowed, info = check_and_consume(db_session, user)
    assert allowed is False
    assert info["used"] == 3


def test_refund_quota_decrements_used(db_session):
    from app.services.quota_service import check_and_consume, refund_quota, get_quota_info
    from app.models.user import User
    user = db_session.query(User).filter_by(username="tester").first()
    check_and_consume(db_session, user)
    check_and_consume(db_session, user)
    db_session.expire_all()
    user = db_session.query(User).filter_by(username="tester").first()

    refund_quota(db_session, user)
    db_session.expire_all()
    user = db_session.query(User).filter_by(username="tester").first()
    info = get_quota_info(db_session, user)
    assert info["used"] == 1


def test_refund_quota_does_not_go_below_zero(db_session):
    from app.services.quota_service import refund_quota, get_quota_info
    from app.models.user import User
    user = db_session.query(User).filter_by(username="tester").first()
    refund_quota(db_session, user)  # 之前没用过，不应变成负数
    info = get_quota_info(db_session, user)
    assert info["used"] == 0


def test_admin_unlimited(db_session):
    from app.services.quota_service import check_and_consume
    from app.models.user import User
    admin = User(username="admin1", password_hash="x", role="admin", status="active")
    db_session.add(admin)
    db_session.commit()
    for _ in range(100):
        allowed, _ = check_and_consume(db_session, admin)
        assert allowed is True
