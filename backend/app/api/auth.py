"""认证API - 注册/登录/刷新Token"""
import secrets
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    get_current_user,
    is_user_expired,
)
from app.models.user import User, InviteCode
from app.core.config import get_settings

settings = get_settings()
router = APIRouter()


# ========== 请求/响应模型 ==========

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    invite_code: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    role: str
    expiry_start_date: datetime | None = None
    expiry_date: datetime | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ========== 注册 ==========

@router.post("/auth/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册（需要邀请码）"""
    # 验证用户名
    if len(req.username) < 2 or len(req.username) > 50:
        raise HTTPException(status_code=400, detail="用户名长度2-50个字符")

    # 验证密码强度
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="密码至少8个字符")
    if not any(c.isupper() for c in req.password):
        raise HTTPException(status_code=400, detail="密码需包含大写字母")
    if not any(c.islower() for c in req.password):
        raise HTTPException(status_code=400, detail="密码需包含小写字母")
    if not any(c.isdigit() for c in req.password):
        raise HTTPException(status_code=400, detail="密码需包含数字")

    # 检查用户名是否已存在
    existing = db.query(User).filter(
        (User.username == req.username) | (User.email == req.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名或邮箱已被注册")

    # 验证邀请码
    invite = db.query(InviteCode).filter(
        InviteCode.code == req.invite_code,
        InviteCode.is_active == True,
        InviteCode.used_at == None,
    ).first()
    if not invite:
        raise HTTPException(status_code=400, detail="邀请码无效或已使用")

    # 创建用户
    user = User(
        username=req.username,
        email=req.email,
        password_hash=get_password_hash(req.password),
        role="normal",
        status="active",
        invite_code=req.invite_code,
    )
    db.add(user)
    db.flush()  # 获取user.id

    # 标记邀请码已使用
    invite.used_by = user.id
    invite.used_at = datetime.now()

    db.commit()
    db.refresh(user)

    # 记录活动日志
    from app.models.activity import UserActivity
    activity = UserActivity(
        user_id=user.id,
        action="register",
        detail=f"使用邀请码 {req.invite_code} 注册",
    )
    db.add(activity)
    db.commit()

    # 返回token
    return TokenResponse(
        access_token=create_access_token({"sub": str(user.id)}),
        refresh_token=create_refresh_token({"sub": str(user.id)}),
        user_id=user.id,
        username=user.username,
        role=user.role,
        expiry_start_date=user.expiry_start_date,
        expiry_date=user.expiry_date,
    )


# ========== 登录 ==========

@router.post("/auth/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """用户登录"""
    user = db.query(User).filter(
        (User.username == form_data.username) | (User.email == form_data.username)
    ).first()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用")

    if is_user_expired(user):
        raise HTTPException(status_code=403, detail="账号已到期，请联系管理员续费")

    # 更新最后登录时间
    user.last_login = datetime.now()
    db.commit()

    # 记录登录日志
    from app.models.activity import UserActivity
    activity = UserActivity(
        user_id=user.id,
        action="login",
        detail=f"用户 {user.username} 登录成功",
    )
    db.add(activity)
    db.commit()

    return TokenResponse(
        access_token=create_access_token({"sub": str(user.id)}),
        refresh_token=create_refresh_token({"sub": str(user.id)}),
        user_id=user.id,
        username=user.username,
        role=user.role,
        expiry_start_date=user.expiry_start_date,
        expiry_date=user.expiry_date,
    )


# ========== 刷新Token ==========

class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/auth/refresh")
async def refresh_token(req: RefreshRequest, db: Session = Depends(get_db)):
    """使用 refresh token 获取新的 access token（同时续期 refresh token，实现滑动过期）

    滑动过期策略：用户活跃使用时 refresh token 自动续期；
    不活跃用户 7 天后强制重新登录。
    """
    from app.core.auth import decode_token

    payload = decode_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="刷新令牌无效")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == int(user_id), User.status == "active").first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")

    if is_user_expired(user):
        raise HTTPException(status_code=401, detail="账号已到期，请联系管理员续费")

    return {
        "access_token": create_access_token({"sub": str(user.id)}),
        "refresh_token": create_refresh_token({"sub": str(user.id)}),
        "token_type": "bearer",
    }


# ========== 获取当前用户信息 ==========

class UserInfoResponse(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    expiry_start_date: datetime | None = None
    expiry_date: datetime | None = None
    created_at: datetime
    last_login: datetime | None

    class Config:
        from_attributes = True


@router.get("/auth/me", response_model=UserInfoResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return current_user


# ========== 修改密码 ==========

@router.post("/auth/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改密码"""
    if not verify_password(req.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少8个字符，需包含大小写字母和数字")
    if not any(c.isupper() for c in req.new_password) or not any(c.islower() for c in req.new_password) or not any(c.isdigit() for c in req.new_password):
        raise HTTPException(status_code=400, detail="新密码需包含大写字母、小写字母和数字")

    current_user.password_hash = get_password_hash(req.new_password)
    db.commit()

    # 记录日志
    from app.models.activity import UserActivity
    activity = UserActivity(
        user_id=current_user.id,
        action="change_password",
        detail=f"用户 {current_user.username} 修改了密码",
    )
    db.add(activity)
    db.commit()

    return {"status": "ok", "message": "密码已修改"}


# ========== 心跳（在线状态追踪）==========

@router.post("/auth/heartbeat")
async def heartbeat(current_user: User = Depends(get_current_user)):
    """上报用户心跳，用于在线状态追踪"""
    from app.core.online import heartbeat as record_heartbeat
    record_heartbeat(current_user.id)
    return {"status": "ok"}
