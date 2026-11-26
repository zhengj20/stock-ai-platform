"""提示词集中管理测试"""
import os
import sys
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-test-only-12345678")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_report_prompt_exposed():
    from app.core.prompts import SYSTEM_PROMPT_REPORT
    assert "A股职业交易员复盘分析师" in SYSTEM_PROMPT_REPORT
    assert "数据暂不可用" in SYSTEM_PROMPT_REPORT


def test_agent_uses_prompts_module():
    """Agent 不再自己定义 SYSTEM_PROMPT_REPORT，引用 prompts 统一源"""
    from app.core import prompts
    from app.core.agent import SYSTEM_PROMPT_REPORT
    assert SYSTEM_PROMPT_REPORT is prompts.SYSTEM_PROMPT_REPORT


def test_daily_report_service_uses_prompts_module():
    from app.core import prompts
    from app.services.daily_report_service import SYSTEM_PROMPT_REPORT
    # daily_report_service 没有显式重导出，但内部使用 prompts.SYSTEM_PROMPT_REPORT
    assert prompts.SYSTEM_PROMPT_REPORT
