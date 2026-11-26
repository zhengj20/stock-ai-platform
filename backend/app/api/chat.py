"""对话API - Agent模式：LLM自主调用Skills工具 + 对话历史持久化"""
import asyncio
import json
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from typing import Optional
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from app.core.llm_service import llm_config, llm_client
from app.core.agent import agent
from app.core.database import get_db, SessionLocal
from app.core.auth import get_current_user, get_current_admin
from app.models.user import User
from app.api.chat_history import create_session, save_message
from app.main import limiter
from app.services.quota_service import check_and_consume, refund_quota


router = APIRouter()
log = logging.getLogger(__name__)

# 配置更新锁，防止并发竞态
_config_lock = asyncio.Lock()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    stream: bool = False
    session_id: Optional[int] = None  # 指定会话ID（续聊）或None创建新会话


class ConfigUpdate(BaseModel):
    base_url: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    enabled: Optional[bool] = None
    provider: Optional[str] = None


@router.get("/chat/config")
async def get_config(current_user: User = Depends(get_current_user)):
    """获取当前LLM配置（所有登录用户可读）"""
    return llm_config.to_dict()


@router.post("/chat/config")
async def update_config(
    cfg: ConfigUpdate,
    current_user: User = Depends(get_current_admin),
):
    """更新LLM配置（仅管理员）"""
    async with _config_lock:
        if cfg.base_url is not None:
            llm_config.base_url = cfg.base_url
        if cfg.model is not None:
            llm_config.model = cfg.model
        if cfg.temperature is not None:
            llm_config.temperature = cfg.temperature
        if cfg.max_tokens is not None:
            llm_config.max_tokens = cfg.max_tokens
        if cfg.enabled is not None:
            llm_config.enabled = cfg.enabled
        if cfg.provider is not None:
            llm_config.provider = cfg.provider
        try:
            llm_config.save()  # 持久化到文件
        except RuntimeError as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
        return {"status": "ok", "config": llm_config.to_dict()}


@router.post("/chat/config/test")
async def test_connection(current_user: User = Depends(get_current_admin)):
    """测试LM Studio连接（仅管理员）"""
    result = await llm_client.check_connection()
    if result["connected"]:
        default_model = result.get("default_model", "")
        if default_model and not llm_config.model:
            result["suggested_model"] = default_model
    return result


@router.get("/chat/quota")
async def get_quota(current_user: User = Depends(get_current_user)):
    """获取当前用户AI对话配额信息"""
    from app.services.quota_service import get_quota_info
    db = SessionLocal()
    try:
        info = get_quota_info(db, current_user)
    finally:
        db.close()
    return info


@router.post("/chat/completions")
@limiter.limit("20/minute")  # LLM 调用限流：单 IP 每分钟最多 20 次
async def chat_completions(
    request: Request,
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """Agent聊天 - 支持多轮工具调用 + 自动保存对话历史"""
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    user_id = current_user.id
    log.info(f"[Chat] 用户 {user_id} 发送消息, session_id={req.session_id}, llm_enabled={llm_config.enabled}")

    # 创建或复用会话（无论LLM是否启用都保存）
    db = SessionLocal()
    session_id = req.session_id
    try:
        if session_id:
            from app.models.chat import ChatSession
            existing = db.query(ChatSession).filter(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            ).first()
            if not existing:
                session_id = None

        if not session_id:
            # 创建新会话，取首条用户消息前20字作为标题
            title = ""
            for msg in reversed(messages):
                if msg["role"] == "user":
                    title = msg["content"][:20]
                    break
            new_session = create_session(db, user_id, title)
            session_id = new_session.id
            db.commit()
            log.info(f"[Chat] 创建新会话 id={session_id}, title='{title}'")

        # 仅保存本次请求中最后一条用户消息，避免重复保存历史消息
        if session_id:
            last_user_msg = None
            for msg in messages:
                if msg["role"] == "user":
                    last_user_msg = msg["content"]
            if last_user_msg is not None:
                # 检查该条消息是否已存在（防重复）
                from app.models.chat import ChatMessage as CM
                existing = db.query(CM).filter(
                    CM.session_id == session_id,
                    CM.role == "user",
                    CM.content == last_user_msg,
                ).first()
                if not existing:
                    save_message(db, session_id, "user", last_user_msg)
                    db.commit()
                    log.info(f"[Chat] 保存用户消息到会话 {session_id}")

    except Exception as e:
        log.error(f"[Chat] 保存对话历史失败: {e}", exc_info=True)
    finally:
        db.close()

    if not llm_config.enabled:
        return JSONResponse(
            status_code=503,
            content={"error": "LLM服务未启用", "config": llm_config.to_dict(), "enabled": False}
        )

    # 配额检查
    quota_db = SessionLocal()
    try:
        allowed, quota_info = check_and_consume(quota_db, current_user)
    finally:
        quota_db.close()

    if not allowed:
        return JSONResponse(
            status_code=429,
            content={
                "error": "今日AI对话次数已用完",
                "code": "QUOTA_EXCEEDED",
                "limit": quota_info["limit"],
                "used": quota_info["used"],
                "remaining": 0,
                "role": quota_info["role"],
                "date": quota_info["date"],
            }
        )

    if req.stream:
        # 流式Agent模式 - SSE输出思考过程和最终回答
        async def safe_stream():
            full_response = ""
            tools_used_list = []
            stream_failed = False
            try:
                async for event in agent.run_stream(messages, session_id=session_id):
                    yield event
                    # 累积完整响应内容
                    try:
                        data = json.loads(event) if isinstance(event, str) else event
                        if data.get("type") in ("content", "final_chunk"):
                            full_response += data.get("content", "")
                        elif data.get("type") == "tool_result":
                            tools_used_list.append(data.get("tool_name", ""))
                    except (json.JSONDecodeError, KeyError, AttributeError):
                        pass
            except Exception as e:
                stream_failed = True
                log.error(f"[Chat] 流式响应失败, user_id={user_id}, session_id={session_id}: {e}", exc_info=True)
                yield json.dumps({"type": "error", "content": f"流式响应出错: {str(e)}"})

            # 流结束后：失败则回滚配额
            if stream_failed:
                refund_db = SessionLocal()
                try:
                    refund_quota(refund_db, current_user)
                    log.info(f"[Chat] 流式失败已退还配额, user_id={user_id}")
                finally:
                    refund_db.close()
                return

            # 成功路径：保存AI回复到数据库
            if session_id and full_response:
                db2 = SessionLocal()
                try:
                    tools_json = json.dumps(tools_used_list, ensure_ascii=False) if tools_used_list else None
                    save_message(db2, session_id, "assistant", full_response, tools_json)
                    db2.commit()
                except Exception as e:
                    log.warning(f"保存AI回复失败: {e}")
                finally:
                    db2.close()

            # 发送会话ID给前端
            yield json.dumps({"type": "session_info", "session_id": session_id})

        return EventSourceResponse(
            safe_stream(),
            media_type="text/event-stream"
        )

    # 非流式Agent模式 - 等待所有工具调用完成后再返回
    try:
        result = await agent.run(messages, session_id=session_id)
    except Exception as e:
        # LLM 调用异常 → 退还配额
        log.error(f"[Chat] LLM 调用失败, user_id={user_id}: {e}", exc_info=True)
        refund_db = SessionLocal()
        try:
            refund_quota(refund_db, current_user)
        finally:
            refund_db.close()
        return JSONResponse(
            status_code=503,
            content={"error": f"AI服务暂时不可用: {str(e)}", "code": "LLM_UNAVAILABLE"}
        )

    if "error" in result:
        # Agent 业务错误（仍计费，因为可能已完成大部分工作）
        log.warning(f"[Chat] Agent 返回业务错误, user_id={user_id}: {result.get('error')}")
        return JSONResponse(status_code=503, content=result)

    # 保存AI回复到数据库
    if session_id:
        db2 = SessionLocal()
        try:
            tools_json = json.dumps(result.get("tools_used", []), ensure_ascii=False) if result.get("tools_used") else None
            save_message(db2, session_id, "assistant", result["content"], tools_json)
            db2.commit()
        except Exception as e:
            log.warning(f"保存AI回复失败: {e}")
        finally:
            db2.close()

    return {
        "content": result["content"],
        "tools_used": result.get("tools_used", []),
        "reasoning_steps": result.get("reasoning_steps", []),
        "session_id": session_id,  # 返回会话ID供前端使用
    }
