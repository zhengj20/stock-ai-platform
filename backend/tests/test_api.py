"""后端应用测试"""
import pytest
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_root():
    """测试根路径"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "A股智能分析平台"
    assert data["status"] == "running"


def test_health_check():
    """测试健康检查"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_market_sentiment_requires_auth():
    """市场情绪接口需登录，未携带token应返回401"""
    response = client.get("/api/v1/market/sentiment")
    assert response.status_code == 401


def test_sector_overview_requires_auth():
    """板块总览接口需登录，未携带token应返回401"""
    response = client.get("/api/v1/market/sectors")
    assert response.status_code == 401


def test_dragon_list_requires_auth():
    """龙虎榜接口需登录，未携带token应返回401"""
    response = client.get("/api/v1/dragon/today")
    assert response.status_code == 401
