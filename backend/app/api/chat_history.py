"""AI对话历史API - CRUD + 90天自动清理"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.chat import ChatSession, ChatMessage

router = APIRouter()


# ========== 对话会话列表 ==========

@router.get("/chat/sessions")
async def list_sessions(
    skip: int = 0,
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取我的对话会话列表（分页）"""
    # 用 groupby 一次性聚合 message_count，避免 N+1
    count_subq = (
        db.query(
            ChatMessage.session_id,
            func.count(ChatMessage.id).label("msg_count"),
        )
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    query = (
        db.query(ChatSession, count_subq.c.msg_count)
        .outerjoin(count_subq, ChatSession.id == count_subq.c.session_id)
        .filter(ChatSession.user_id == current_user.id)
    )
    total = query.count()
    sessions = (
        query.order_by(ChatSession.updated_at.desc())
        .offset(skip).limit(limit).all()
    )
    return {
        "total": total,
        "sessions": [
            {
                "id": s.id,
                "title": s.title or f"对话 #{s.id}",
                "message_count": mc or 0,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            } for s, mc in sessions
        ],
    }


# ========== 会话详情 ==========

@router.get("/chat/sessions/{session_id}")
async def get_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取某次对话的完整消息"""
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
    ).first()

    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at.asc()).all()

    return {
        "session": {
            "id": session.id,
            "title": session.title or f"对话 #{session.id}",
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        },
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "tools_used": m.tools_used,
                "created_at": m.created_at,
            } for m in messages
        ],
    }


# ========== 删除会话 ==========

@router.delete("/chat/sessions/{session_id}")
async def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除某次对话（级联删除消息）"""
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
    ).first()

    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="对话不存在")

    db.delete(session)
    db.commit()

    return {"status": "ok", "message": "对话已删除"}


# ========== 搜索消息 ==========

@router.get("/chat/search")
async def search_messages(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    skip: int = 0,
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """跨会话搜索消息内容"""
    messages = (
        db.query(ChatMessage)
        .join(ChatSession)
        .filter(
            ChatSession.user_id == current_user.id,
            ChatMessage.content.contains(q),
        )
        .order_by(ChatMessage.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": len(messages),
        "results": [
            {
                "message_id": m.id,
                "session_id": m.session_id,
                "role": m.role,
                "content_preview": m.content[:200] + ("..." if len(m.content) > 200 else ""),
                "created_at": m.created_at,
            } for m in messages
        ],
    }


# ========== 90天自动清理（管理员触发或定时任务） ==========

@router.post("/chat/cleanup")
async def cleanup_old_sessions(
    days: int = Query(default=30, description="保留天数"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """清理超过指定天数的对话记录（仅管理员可执行全局清理）"""
    if current_user.role != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="需要管理员权限")

    cutoff = datetime.now() - timedelta(days=days)

    # 统计将被删除的数量
    old_sessions = db.query(ChatSession).filter(
        ChatSession.created_at < cutoff
    ).all()

    deleted_count = len(old_sessions)
    for session in old_sessions:
        db.delete(session)

    db.commit()

    return {
        "status": "ok",
        "deleted_sessions": deleted_count,
        "cutoff_date": cutoff.isoformat(),
    }


# ========== 创建新会话（供 chat.py 调用） ==========

def create_session(db: Session, user_id: int, title: str = "") -> ChatSession:
    """创建新的对话会话"""
    session = ChatSession(
        user_id=user_id,
        title=title[:200] if title else "",
    )
    db.add(session)
    db.flush()
    return session


def save_message(db: Session, session_id: int, role: str, content: str, tools_used: str = None):
    """保存单条消息"""
    message = ChatMessage(
        session_id=session_id,
        role=role,
        content=content[:10000] if content else "",  # 限制长度
        tools_used=tools_used,
    )
    db.add(message)

    # 更新会话标题（取首条用户消息前20字）
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session and not session.title:
        first_user_msg = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id, ChatMessage.role == "user")
            .order_by(ChatMessage.created_at.asc())
            .first()
        )
        if first_user_msg:
            session.title = first_user_msg.content[:20]

    db.flush()


# ========== 定时清理任务（在 lifespan 中注册） ==========

def cleanup_old_data(db: Session, days: int = 30):
    """后台清理超过指定天数的数据"""
    cutoff = datetime.now() - timedelta(days=days)
    old_sessions = db.query(ChatSession).filter(
        ChatSession.created_at < cutoff
    ).all()

    deleted_count = len(old_sessions)
    if deleted_count > 0:
        for session in old_sessions:
            db.delete(session)
        db.commit()

    return deleted_count
