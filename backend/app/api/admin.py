"""管理员API - 用户管理 + 邀请码管理 + 日志查看"""
import os
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.models.user import User, InviteCode
from app.models.activity import UserActivity
from app.models.chat import ChatSession, ChatMessage
from app.models.quota import QuotaUsage
from app.core.config import get_settings
from app.core.online import is_online as check_online

settings = get_settings()
router = APIRouter()

# 日志目录（项目根/logs）
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")

# 日志分类映射：文件名 → 类别
_LOG_CATEGORIES = {
    "app": "应用日志",
    "error": "错误日志",
    "uvicorn": "服务器日志",
}


def _get_log_category(name: str) -> str:
    """根据文件名判断日志类别"""
    lower = name.lower()
    for key, label in _LOG_CATEGORIES.items():
        if key in lower:
            return label
    return "其他"


def _get_log_files() -> list[dict]:
    """扫描 logs/ 目录，返回分类后的日志文件信息"""
    if not os.path.isdir(_LOG_DIR):
        return []

    log_files = []
    for name in os.listdir(_LOG_DIR):
        if not name.lower().endswith(('.log', '.txt')):
            continue
        full_path = os.path.join(_LOG_DIR, name)
        if not os.path.isfile(full_path):
            continue
        try:
            stat = os.stat(full_path)
            size_mb = stat.st_size / (1024 * 1024)
            log_files.append({
                "name": name,
                "category": _get_log_category(name),
                "size_bytes": stat.st_size,
                "size_mb": round(size_mb, 2),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "path_key": f"logs/{name}",
            })
        except OSError:
            continue

    # 按修改时间倒序
    log_files.sort(key=lambda x: x["modified_at"], reverse=True)
    return log_files


def _read_log_tail(path_key: str, lines: int = 200) -> list[str]:
    """读取日志文件末尾N行"""
    if not path_key.startswith("logs/"):
        raise HTTPException(status_code=400, detail="无效的日志路径")

    name = path_key[5:]
    full_path = os.path.join(_LOG_DIR, name)

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="日志文件不存在")

    real_path = os.path.realpath(full_path)
    allowed_base = os.path.realpath(_LOG_DIR)
    if not real_path.startswith(allowed_base):
        raise HTTPException(status_code=403, detail="禁止访问该文件")

    try:
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
        tail = [line.rstrip('\n\r') for line in all_lines[-lines:]]
        return tail
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"读取日志失败: {e}")


def _read_log_by_date(path_key: str, date_str: str, lines: int = 200) -> list[str]:
    """按日期筛选日志行，返回匹配日期的末尾N行"""
    if not path_key.startswith("logs/"):
        raise HTTPException(status_code=400, detail="无效的日志路径")

    name = path_key[5:]
    full_path = os.path.join(_LOG_DIR, name)

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="日志文件不存在")

    real_path = os.path.realpath(full_path)
    allowed_base = os.path.realpath(_LOG_DIR)
    if not real_path.startswith(allowed_base):
        raise HTTPException(status_code=403, detail="禁止访问该文件")

    try:
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
        # 日志格式: YYYY-MM-DD HH:MM:SS | ...
        matched = [line.rstrip('\n\r') for line in all_lines if line.startswith(date_str)]
        return matched[-lines:]
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"读取日志失败: {e}")


def _get_log_dates(path_key: str) -> list[str]:
    """获取日志文件中所有可用日期"""
    if not path_key.startswith("logs/"):
        return []

    name = path_key[5:]
    full_path = os.path.join(_LOG_DIR, name)

    if not os.path.isfile(full_path):
        return []

    try:
        dates = set()
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                # 日志格式: YYYY-MM-DD HH:MM:SS | ...
                if len(line) >= 10 and line[4] == '-' and line[7] == '-':
                    dates.add(line[:10])
        return sorted(dates, reverse=True)
    except OSError:
        return []


@router.get("/admin/logs/dates")
async def get_log_dates(
    file: str = Query(..., description="path_key"),
    current_user: User = Depends(get_current_admin),
):
    """获取日志文件中所有可用日期"""
    dates = _get_log_dates(file)
    return {"dates": dates}


@router.get("/admin/logs/by-date")
async def get_log_by_date(
    file: str = Query(..., description="path_key"),
    date: str = Query(..., description="日期 YYYY-MM-DD"),
    lines: int = Query(default=200, ge=1, le=5000, description="读取末尾行数"),
    current_user: User = Depends(get_current_admin),
):
    """按日期获取日志内容"""
    content = _read_log_by_date(file, date, lines)
    return {"file": file, "date": date, "lines_count": len(content), "content": content}


# ========== 日志查看API ==========

@router.get("/admin/logs/list")
async def list_log_files(current_user: User = Depends(get_current_admin)):
    """获取所有日志文件列表"""
    return _get_log_files()


@router.get("/admin/logs/content")
async def get_log_content(
    file: str = Query(..., description="path_key，如 项目根目录/_backend.log"),
    lines: int = Query(default=200, ge=1, le=5000, description="读取末尾行数"),
    current_user: User = Depends(get_current_admin),
):
    """获取日志文件内容（末尾N行）"""
    content = _read_log_tail(file, lines)
    return {"file": file, "lines_count": len(content), "content": content}


# ========== 用户管理 ==========

class UserListItem(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    status: str
    invite_code: str | None
    remark: str | None
    expiry_start_date: datetime | None
    expiry_date: datetime | None
    created_at: datetime
    last_login: datetime | None
    is_online: bool = False

    class Config:
        from_attributes = True


@router.get("/admin/users")
async def list_users(
    skip: int = 0,
    limit: int = Query(default=50, le=200),
    search: str = "",
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """获取用户列表（分页+搜索）"""
    query = db.query(User)
    if search:
        query = query.filter(
            User.username.contains(search) | User.email.contains(search)
        )

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "users": [
            UserListItem(
                id=u.id, username=u.username, email=u.email,
                role=u.role, status=u.status,
                invite_code=u.invite_code, remark=u.remark,
                expiry_start_date=u.expiry_start_date,
                expiry_date=u.expiry_date,
                created_at=u.created_at, last_login=u.last_login,
                is_online=check_online(u.id),
            ) for u in users
        ],
    }


class UpdateUserRequest(BaseModel):
    role: str | None = None
    status: str | None = None
    username: str | None = None
    email: str | None = None
    remark: str | None = None
    expiry_days: int | None = None  # 设置剩余天数，None表示清除过期时间
    expiry_start_date: str | None = None  # 有效期开始日期 YYYY-MM-DD，不传则默认今天


@router.put("/admin/users/{user_id}")
async def update_user(
    user_id: int,
    req: UpdateUserRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """更新用户信息（角色/状态/用户名/邮箱）"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 不允许修改自己的管理员身份
    if target.id == current_user.id and req.role is not None and req.role != "admin":
        raise HTTPException(status_code=400, detail="不能降级自己的管理员权限")

    if req.role:
        if req.role not in ("normal", "vip", "admin"):
            raise HTTPException(status_code=400, detail="角色只能是 normal/vip/admin")
        target.role = req.role

    if req.status:
        if req.status not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="状态只能是 active 或 disabled")
        target.status = req.status

    if req.username:
        if len(req.username) < 2 or len(req.username) > 50:
            raise HTTPException(status_code=400, detail="用户名长度2-50个字符")
        existing = db.query(User).filter(User.username == req.username, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已被占用")
        target.username = req.username

    if req.email:
        existing = db.query(User).filter(User.email == req.email, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="邮箱已被占用")
        target.email = req.email

    if req.remark is not None:
        target.remark = req.remark

    if req.expiry_days is not None:
        if req.expiry_days == 0:
            # 0表示清除过期时间（永不过期）
            target.expiry_start_date = None
            target.expiry_date = None
        else:
            from datetime import timedelta
            start_dt = datetime.now()
            if req.expiry_start_date:
                try:
                    start_dt = datetime.strptime(req.expiry_start_date, "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail="开始日期格式必须为 YYYY-MM-DD")
            target.expiry_start_date = start_dt
            target.expiry_date = start_dt + timedelta(days=req.expiry_days)

    db.commit()

    # 记录日志
    activity = UserActivity(
        user_id=current_user.id,
        action="admin_action",
        detail=f"修改用户 {target.username}(ID:{user_id}): role={req.role}, status={req.status}",
    )
    db.add(activity)
    db.commit()

    return {"status": "ok", "message": f"用户 {target.username} 已更新"}


class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    role: str = "normal"
    remark: str | None = None


@router.post("/admin/users")
async def create_user(
    req: CreateUserRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员创建用户"""
    from app.core.auth import get_password_hash

    if len(req.username) < 2 or len(req.username) > 50:
        raise HTTPException(status_code=400, detail="用户名长度2-50个字符")

    existing = db.query(User).filter(
        (User.username == req.username) | ((User.email == req.email) & (req.email is not None))
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名或邮箱已被占用")

    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6个字符")

    if req.role not in ("normal", "vip", "admin"):
        raise HTTPException(status_code=400, detail="角色只能是 normal/vip/admin")

    user = User(
        username=req.username,
        email=req.email,
        password_hash=get_password_hash(req.password),
        role=req.role,
        status="active",
        remark=req.remark,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    activity = UserActivity(
        user_id=current_user.id,
        action="admin_action",
        detail=f"创建用户 {user.username}(ID:{user.id})",
    )
    db.add(activity)
    db.commit()

    return {"status": "ok", "message": f"用户 {user.username} 已创建", "user_id": user.id}


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.post("/admin/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    req: ResetPasswordRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员重置用户密码"""
    from app.core.auth import get_password_hash

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6个字符")

    target.password_hash = get_password_hash(req.new_password)
    db.commit()

    activity = UserActivity(
        user_id=current_user.id,
        action="admin_action",
        detail=f"重置用户 {target.username}(ID:{user_id}) 的密码",
    )
    db.add(activity)
    db.commit()

    return {"status": "ok", "message": f"用户 {target.username} 的密码已重置"}


@router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """删除用户（硬删除：清空所有关联数据后删除用户记录）"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")

    username = target.username

    # 1. 删除配额用量记录
    db.query(QuotaUsage).filter(QuotaUsage.user_id == user_id).delete()

    # 2. 清空邀请码引用（used_by / created_by 置空，保留邀请码本身）
    db.query(InviteCode).filter(InviteCode.used_by == user_id).update({"used_by": None})
    db.query(InviteCode).filter(InviteCode.created_by == user_id).update({"created_by": None})

    # 3. 删除用户（级联删除 chat_sessions、watchlist_items、activities）
    db.delete(target)
    db.commit()

    return {"status": "ok", "message": f"用户 {username} 及其所有数据已删除"}


# ========== 邀请码管理 ==========

@router.get("/admin/invite-codes")
async def list_invite_codes(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """获取所有邀请码"""
    codes = db.query(InviteCode).order_by(InviteCode.created_at.desc()).all()

    return {
        "codes": [
            {
                "id": c.id,
                "code": c.code,
                "created_by": c.created_by,
                "used_by": c.used_by,
                "used_at": c.used_at,
                "is_active": c.is_active,
                "created_at": c.created_at,
            } for c in codes
        ],
    }


@router.post("/admin/invite-codes/generate")
async def generate_invite_codes(
    count: int = Query(default=5, le=50),
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """生成邀请码"""
    generated = []
    for _ in range(count):
        code = secrets.token_hex(8)  # 16位十六进制
        invite = InviteCode(
            code=code,
            created_by=current_user.id,
        )
        db.add(invite)
        generated.append(code)

    db.commit()

    activity = UserActivity(
        user_id=current_user.id,
        action="admin_action",
        detail=f"生成 {count} 个邀请码",
    )
    db.add(activity)
    db.commit()

    return {"status": "ok", "codes": generated, "count": count}


@router.delete("/admin/invite-codes/{code_id}")
async def delete_invite_code(
    code_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """删除邀请码"""
    invite = db.query(InviteCode).filter(InviteCode.id == code_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="邀请码不存在")

    if invite.used_at:
        raise HTTPException(status_code=400, detail="已使用的邀请码不能删除")

    db.delete(invite)
    db.commit()

    return {"status": "ok", "message": "邀请码已删除"}


# ========== 系统统计 ==========

@router.get("/admin/stats")
async def get_system_stats(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """获取系统统计数据"""
    total_users = db.query(func.count(User.id)).filter(User.status == "active").scalar() or 0
    total_sessions = db.query(func.count(ChatSession.id)).scalar() or 0
    total_messages = db.query(func.count(ChatMessage.id)).scalar() or 0
    total_invite_codes = db.query(func.count(InviteCode.id)).scalar() or 0
    unused_invites = db.query(func.count(InviteCode.id)).filter(
        InviteCode.used_at == None, InviteCode.is_active == True
    ).scalar() or 0

    # 今日活跃用户（24小时内有登录或活动）
    today_start = datetime.now() - timedelta(days=1)
    active_today = db.query(func.count(UserActivity.user_id)).filter(
        UserActivity.created_at >= today_start,
        UserActivity.action == "login",
    ).scalar() or 0

    return {
        "total_users": total_users,
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "total_invite_codes": total_invite_codes,
        "unused_invites": unused_invites,
        "active_today": active_today,
    }


# ========== 聊天记录管理（管理员查看所有） ==========

@router.get("/admin/chat-sessions")
async def admin_list_sessions(
    skip: int = 0,
    limit: int = Query(default=50, le=200),
    user_id: int | None = None,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员查看所有对话会话"""
    query = db.query(ChatSession)
    if user_id:
        query = query.filter(ChatSession.user_id == user_id)

    total = query.count()
    sessions = query.order_by(ChatSession.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "sessions": [
            {
                "id": s.id,
                "user_id": s.user_id,
                "username": s.user.username if s.user else None,
                "title": s.title,
                "message_count": len(s.messages),
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            } for s in sessions
        ],
    }


# ========== 配额管理 ==========

class QuotaUpdate(BaseModel):
    role: str
    max_daily: int


@router.get("/admin/quotas")
async def list_quotas(current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """查看各角色配额配置"""
    from app.services.quota_service import get_all_quotas
    return get_all_quotas(db)


@router.put("/admin/quotas")
async def update_quota(
    req: QuotaUpdate,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """修改某角色每日配额"""
    if req.role not in ("normal", "vip", "admin"):
        raise HTTPException(status_code=400, detail="角色只能是 normal/vip/admin")
    if req.max_daily < 1 or req.max_daily > 99999:
        raise HTTPException(status_code=400, detail="配额范围: 1-99999")
    from app.services.quota_service import update_quota_limit
    update_quota_limit(db, req.role, req.max_daily)
    return {"status": "ok", "role": req.role, "max_daily": req.max_daily}


@router.get("/admin/quotas/usage")
async def list_usage(current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """查看所有用户今日用量"""
    from app.services.quota_service import get_all_users_usage_today
    return get_all_users_usage_today(db)


@router.put("/admin/quotas/usage/{user_id}")
async def reset_usage(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """重置某用户今日用量"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    from app.services.quota_service import reset_user_today
    reset_user_today(db, user_id)
    return {"status": "ok", "user_id": user_id, "username": target.username}


# ========== LLM配置管理 ==========

from app.core.llm_service import llm_config, LMStudioClient
from app.api.chat import _config_lock


class LLMConfigRequest(BaseModel):
    base_url: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    enabled: bool | None = None
    provider: str | None = None


@router.get("/admin/llm-config")
async def get_llm_config(current_user: User = Depends(get_current_admin)):
    """获取LLM配置"""
    return llm_config.to_dict()


@router.put("/admin/llm-config")
async def update_llm_config(
    req: LLMConfigRequest,
    current_user: User = Depends(get_current_admin),
):
    """更新LLM配置"""
    async with _config_lock:
        if req.base_url is not None:
            llm_config.base_url = req.base_url
        if req.model is not None:
            llm_config.model = req.model
        if req.temperature is not None:
            if not (0.0 <= req.temperature <= 2.0):
                raise HTTPException(status_code=400, detail="temperature必须在0-2之间")
            llm_config.temperature = req.temperature
        if req.max_tokens is not None:
            if not (1 <= req.max_tokens <= 65536):
                raise HTTPException(status_code=400, detail="max_tokens必须在1-65536之间")
            llm_config.max_tokens = req.max_tokens
        if req.enabled is not None:
            llm_config.enabled = req.enabled
        if req.provider is not None:
            llm_config.provider = req.provider

        llm_config.save()

    activity = UserActivity(
        user_id=current_user.id,
        action="admin_action",
        detail=f"修改LLM配置: base_url={llm_config.base_url}, model={llm_config.model}",
    )
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        db.add(activity)
        db.commit()
    finally:
        db.close()

    return {"status": "ok", "message": "LLM配置已更新", **llm_config.to_dict()}


@router.post("/admin/llm-config/test")
async def test_llm_connection(current_user: User = Depends(get_current_admin)):
    """测试LM Studio连接"""
    client = LMStudioClient(llm_config)
    result = await client.check_connection()
    return result


# ========== 定时任务调度配置 ==========

import re as _re
from datetime import date as _date
from app.models.scheduler_config import SchedulerConfig


def _parse_and_validate_time(time_str: str) -> tuple[int, int]:
    """解析并校验时间字符串，返回 (hour, minute)。

    校验：格式 HH:mm，小时 0-23，分钟 0-59。
    """
    if not _re.match(r'^\d{2}:\d{2}$', time_str):
        raise ValueError(f"格式必须为 HH:mm，如 15:30（收到: {time_str!r})")
    parts = time_str.split(":")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"小时必须在 0-23，分钟必须在 0-59（收到: {time_str})")
    return hour, minute


def _validate_time_format(time_str: str) -> bool:
    """仅校验格式（向后兼容），新逻辑请使用 _parse_and_validate_time"""
    return bool(_re.match(r'^\d{2}:\d{2}$', time_str))


class SchedulerConfigRequest(BaseModel):
    report_enabled: bool | None = None
    report_date: str | None = None  # 保留兼容，已弃用（定时任务使用 datetime.now()，配置不生效）
    report_time: str | None = None
    pick_enabled: bool | None = None
    pick_date: str | None = None  # 保留兼容，已弃用（定时任务使用 datetime.now()，配置不生效）
    pick_time: str | None = None
    # 模拟交易 T+1 解锁（仅上午，A 股 T+1 规则）
    t1_unlock_morning_time: str | None = None
    t1_unlock_afternoon_time: str | None = None  # 保留兼容，已弃用
    # 交易日判断
    trading_day_check_time: str | None = None
    # 收盘缓存
    closing_cache_time: str | None = None
    next_day_strategy_time: str | None = None  # 保留兼容，已弃用
    # 复盘+次日策略合并生成时间
    review_strategy_time: str | None = None
    # 午间策略调整时间
    midday_strategy_time: str | None = None
    # 盘中策略生成时间（交易时段内自动生成 intraday 模式策略）
    intraday_strategy_time_1: str | None = None
    intraday_strategy_time_2: str | None = None
    # 收盘前自动平短仓配置
    auto_close_short_enabled: bool | None = None
    auto_close_short_time: str | None = None
    # 策略执行间隔（分钟，盘中AI策略自动执行频率）
    strategy_exec_interval_min: int | None = None
    # 凌晨清理
    cleanup_report_time: str | None = None
    cleanup_conversation_time: str | None = None
    # ML模型定时训练配置（智能选股技术评分）
    ml_train_enabled: bool | None = None
    ml_train_day_of_week: int | None = None
    ml_train_time: str | None = None
    ml_train_days: int | None = None
    ml_train_stocks: int | None = None


@router.get("/admin/scheduler-config")
async def get_scheduler_config(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """获取定时任务调度配置"""
    config = db.query(SchedulerConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="调度配置不存在")

    return {
        "report_enabled": config.report_enabled,
        "report_time": config.report_time or "16:30",
        "pick_enabled": config.pick_enabled,
        "pick_time": config.pick_time or "15:15",
        "t1_unlock_morning_time": config.t1_unlock_morning_time or "09:25",
        "t1_unlock_afternoon_time": config.t1_unlock_afternoon_time or "13:00",
        "trading_day_check_time": config.trading_day_check_time or "09:30",
        "closing_cache_time": config.closing_cache_time or "15:05",
        "review_strategy_time": config.review_strategy_time or "15:08",
        "midday_strategy_time": config.midday_strategy_time or "11:30",
        "intraday_strategy_time_1": config.intraday_strategy_time_1 or "10:30",
        "intraday_strategy_time_2": config.intraday_strategy_time_2 or "13:30",
        # 收盘前自动平短仓配置
        "auto_close_short_enabled": config.auto_close_short_enabled if hasattr(config, 'auto_close_short_enabled') else True,
        "auto_close_short_time": config.auto_close_short_time if hasattr(config, 'auto_close_short_time') else "14:50",
        "strategy_exec_interval_min": config.strategy_exec_interval_min or 5,
        "cleanup_report_time": config.cleanup_report_time or "02:00",
        "cleanup_conversation_time": config.cleanup_conversation_time or "03:00",
        # ML模型定时训练配置
        "ml_train_enabled": config.ml_train_enabled if hasattr(config, 'ml_train_enabled') else False,
        "ml_train_day_of_week": config.ml_train_day_of_week if hasattr(config, 'ml_train_day_of_week') else 1,
        "ml_train_time": config.ml_train_time if hasattr(config, 'ml_train_time') else "20:00",
        "ml_train_days": config.ml_train_days if hasattr(config, 'ml_train_days') else 250,
        "ml_train_stocks": config.ml_train_stocks if hasattr(config, 'ml_train_stocks') else 100,
    }


@router.put("/admin/scheduler-config")
async def update_scheduler_config(
    req: SchedulerConfigRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """更新定时任务调度配置"""
    config = db.query(SchedulerConfig).first()
    if not config:
        raise HTTPException(status_code=500, detail="调度配置不存在")

    # 校验所有时间字段格式和范围（HH:mm，小时 0-23，分钟 0-59）
    time_fields = (
        "report_time", "pick_time",
        "t1_unlock_morning_time", "t1_unlock_afternoon_time",
        "trading_day_check_time", "closing_cache_time",
        "review_strategy_time",
        "midday_strategy_time",
        "intraday_strategy_time_1", "intraday_strategy_time_2",
        "cleanup_report_time", "cleanup_conversation_time",
        "ml_v2_train_time",
    )
    for field in time_fields:
        val = getattr(req, field, None)
        if val is not None:
            try:
                _parse_and_validate_time(val)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"{field}: {e}")

    # 业务逻辑校验：复盘+次日策略合并时间必须在收盘后
    _strategy_constraints = {
        "review_strategy_time": (15, 20),  # 复盘+次日策略：15:00-20:00（收盘后）
    }
    for field, (min_h, max_h) in _strategy_constraints.items():
        val = getattr(req, field, None)
        if val is not None:
            hour, minute = _parse_and_validate_time(val)
            total_min = hour * 60 + minute
            min_total = min_h * 60
            max_total = max_h * 60
            if total_min < min_total or total_min > max_total:
                raise HTTPException(
                    status_code=400,
                    detail=f"{field} 必须在 {min_h:02d}:00-{max_h:02d}:00 之间（收到: {val})"
                )

    # T+1 上午解锁时间校验：应在开盘前
    if req.t1_unlock_morning_time is not None:
        h, m = _parse_and_validate_time(req.t1_unlock_morning_time)
        t = h * 60 + m
        if t < 8 * 60 or t > 9 * 60 + 30:
            raise HTTPException(
                status_code=400,
                detail=f"t1_unlock_morning_time 必须在 08:00-09:30 之间（收到: {req.t1_unlock_morning_time})"
            )

    # 盘中策略时间校验：必须在交易时段（9:30-11:30 或 13:00-15:00）
    for _field in ("intraday_strategy_time_1", "intraday_strategy_time_2"):
        _val = getattr(req, _field, None)
        if _val is not None:
            _h, _m = _parse_and_validate_time(_val)
            _t = _h * 60 + _m
            in_morning = 9 * 60 + 30 <= _t <= 11 * 60 + 30
            in_afternoon = 13 * 60 <= _t <= 15 * 60
            if not (in_morning or in_afternoon):
                raise HTTPException(
                    status_code=400,
                    detail=f"{_field} 必须在交易时段内（09:30-11:30 或 13:00-15:00，收到: {_val})"
                )

    # 收盘前平短仓时间校验：必须在 13:30-14:55 之间（收盘前但留出撮合时间）
    if req.auto_close_short_time is not None:
        _h, _m = _parse_and_validate_time(req.auto_close_short_time)
        _t = _h * 60 + _m
        if not (13 * 60 + 30 <= _t <= 14 * 60 + 55):
            raise HTTPException(
                status_code=400,
                detail=f"auto_close_short_time 必须在 13:30-14:55 之间（收到: {req.auto_close_short_time}）"
            )

    # 校验日期格式 YYYY-MM-DD
    for prefix in ("report", "pick"):
        date_val = getattr(req, f"{prefix}_date")
        if date_val is not None:
            try:
                _date.fromisoformat(date_val)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"日期格式必须为 YYYY-MM-DD")

    # 校验策略执行间隔范围
    if req.strategy_exec_interval_min is not None:
        if not (1 <= req.strategy_exec_interval_min <= 60):
            raise HTTPException(status_code=400, detail="strategy_exec_interval_min 必须在 1-60 分钟之间")

    # 更新字段
    if req.report_enabled is not None:
        config.report_enabled = req.report_enabled
    if req.report_date is not None:
        # 已弃用：定时任务使用 datetime.now()，此字段不再生效，保留写入仅向后兼容
        config.report_date = _date.fromisoformat(req.report_date) if req.report_date else None
    if req.report_time is not None:
        config.report_time = req.report_time
    if req.pick_enabled is not None:
        config.pick_enabled = req.pick_enabled
    if req.pick_date is not None:
        # 已弃用：定时任务使用 datetime.now()，此字段不再生效，保留写入仅向后兼容
        config.pick_date = _date.fromisoformat(req.pick_date) if req.pick_date else None
    if req.pick_time is not None:
        config.pick_time = req.pick_time
    if req.t1_unlock_morning_time is not None:
        config.t1_unlock_morning_time = req.t1_unlock_morning_time
    if req.t1_unlock_afternoon_time is not None:
        config.t1_unlock_afternoon_time = req.t1_unlock_afternoon_time
    if req.trading_day_check_time is not None:
        config.trading_day_check_time = req.trading_day_check_time
    if req.closing_cache_time is not None:
        config.closing_cache_time = req.closing_cache_time
    if req.review_strategy_time is not None:
        config.review_strategy_time = req.review_strategy_time
    if req.midday_strategy_time is not None:
        config.midday_strategy_time = req.midday_strategy_time
    if req.intraday_strategy_time_1 is not None:
        config.intraday_strategy_time_1 = req.intraday_strategy_time_1
    if req.intraday_strategy_time_2 is not None:
        config.intraday_strategy_time_2 = req.intraday_strategy_time_2
    # 收盘前自动平短仓配置
    if req.auto_close_short_enabled is not None:
        config.auto_close_short_enabled = req.auto_close_short_enabled
    if req.auto_close_short_time is not None:
        config.auto_close_short_time = req.auto_close_short_time
    if req.strategy_exec_interval_min is not None:
        config.strategy_exec_interval_min = req.strategy_exec_interval_min
    if req.cleanup_report_time is not None:
        config.cleanup_report_time = req.cleanup_report_time
    if req.cleanup_conversation_time is not None:
        config.cleanup_conversation_time = req.cleanup_conversation_time

    # ML模型定时训练配置（智能选股技术评分）
    if req.ml_train_enabled is not None:
        config.ml_train_enabled = req.ml_train_enabled
    if req.ml_train_day_of_week is not None:
        if not (0 <= req.ml_train_day_of_week <= 6):
            raise HTTPException(status_code=400, detail="ml_train_day_of_week 必须在 0-6 之间（0=周日...6=周六）")
        config.ml_train_day_of_week = req.ml_train_day_of_week
    if req.ml_train_time is not None:
        _parse_and_validate_time(req.ml_train_time)
        config.ml_train_time = req.ml_train_time
    if req.ml_train_days is not None:
        if not (50 <= req.ml_train_days <= 1000):
            raise HTTPException(status_code=400, detail="ml_train_days 必须在 50-1000 之间")
        config.ml_train_days = req.ml_train_days
    if req.ml_train_stocks is not None:
        if not (10 <= req.ml_train_stocks <= 200):
            raise HTTPException(status_code=400, detail="ml_train_stocks 必须在 10-200 之间")
        config.ml_train_stocks = req.ml_train_stocks

    db.commit()
    db.refresh(config)
    return {"status": "ok"}


# ============================================================================
# ML模型训练管理 API
# ============================================================================

class TrainMLRequest(BaseModel):
    days: int | None = None
    stocks: int | None = None
    model: str | None = None


@router.post("/admin/train-ml-model")
async def admin_train_ml_model(
    req: TrainMLRequest,
    current_user: User = Depends(get_current_admin),
):
    """管理员手动触发ML模型训练（智能选股技术评分）"""
    import subprocess

    try:
        script_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "skills", "ml-stock-picker")
        script_path = os.path.join(script_dir, "ml_stock_picker.py")
        days = req.days or 250
        stocks = req.stocks or 100
        model = req.model or "lightgbm"

        if not os.path.exists(script_path):
            raise HTTPException(status_code=500, detail=f"训练脚本不存在: {script_path}")

        result = subprocess.run(
            ["python", script_path, "train", "--days", str(days), "--stock-count", str(stocks), "--model", model],
            capture_output=True, timeout=600, cwd=script_dir,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")[-500:] if result.stderr else "训练失败"
            return {"status": "error", "message": stderr}
        stdout = result.stdout.decode("utf-8", errors="replace")[-1000:] if result.stdout else ""

        return {
            "status": "success",
            "message": f"ML模型训练完成 (days={days}, stocks={stocks}, model={model})",
            "stdout": stdout,
        }

    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "训练超时（超过10分钟）"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/admin/ml-model-status")
async def admin_get_ml_model_status(
    current_user: User = Depends(get_current_admin),
):
    """获取ML模型状态"""
    import json as _json
    from pathlib import Path

    skills_dir = Path(__file__).parent.parent.parent.parent / "skills" / "ml-stock-picker"

    # 模型状态 (智能选股技术评分)
    model_dir = skills_dir / "ml_output"
    model_status = {
        "classifier_exists": (model_dir / "model_classifier.pkl").exists(),
        "regressor_exists": (model_dir / "model_regressor.pkl").exists(),
        "feature_names_exists": (model_dir / "feature_names.json").exists(),
    }
    report = model_dir / "train_report.json"
    if report.exists():
        try:
            with open(report, 'r', encoding='utf-8') as f:
                report_data = _json.load(f)
            model_status["last_train_time"] = report_data.get("timestamp", None)
            model_status["stock_count"] = report_data.get("stock_count", 0)
            model_status["sample_count"] = report_data.get("sample_count", 0)
            model_status["feature_count"] = report_data.get("feature_count", 0)
        except Exception:
            pass

    return {"status": "success", "data": model_status}
