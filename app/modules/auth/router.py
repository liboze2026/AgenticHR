"""认证 API 路由"""
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.modules.auth import service as auth_service

router = APIRouter()

# BUG-009: 简单的内存速率限制 — 同一 IP 连续失败 10 次后锁定 15 分钟
_LOGIN_FAILURES: dict[str, list[float]] = defaultdict(list)
_MAX_FAILURES = 10
_LOCKOUT_WINDOW = 900  # 15 分钟（秒）


def _check_login_rate_limit(ip: str) -> None:
    """检查登录速率限制，超出则抛出 429"""
    now = time.time()
    window_start = now - _LOCKOUT_WINDOW
    failures = [t for t in _LOGIN_FAILURES[ip] if t > window_start]
    _LOGIN_FAILURES[ip] = failures
    if len(failures) >= _MAX_FAILURES:
        raise HTTPException(status_code=429, detail="登录尝试过于频繁，请 15 分钟后重试")


def _record_login_failure(ip: str) -> None:
    _LOGIN_FAILURES[ip].append(time.time())


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    display_name: str = Field(default="", max_length=100)


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    """检查系统是否已有用户（前端据此决定显示注册页还是登录页）"""
    return {"has_user": auth_service.has_any_user(db)}


@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    # BUG-010: 仅当系统中尚无用户时才允许公开注册（首次初始化）；后续注册需管理员操作
    if auth_service.has_any_user(db):
        raise HTTPException(status_code=403, detail="系统已初始化，公开注册已关闭")
    from app.modules.auth.models import User
    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = auth_service.register(db, req.username, req.password, req.display_name)
    token = auth_service.create_token(user.id, user.username)
    return {
        "token": token,
        "user": {"id": user.id, "username": user.username, "display_name": user.display_name},
    }


@router.post("/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    # BUG-009: 检查速率限制
    client_ip = request.client.host if request.client else "unknown"
    _check_login_rate_limit(client_ip)

    user = auth_service.authenticate(db, req.username, req.password)
    if not user:
        _record_login_failure(client_ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    # 登录成功，清除该 IP 的失败记录
    _LOGIN_FAILURES.pop(client_ip, None)
    token = auth_service.create_token(user.id, user.username)
    return {
        "token": token,
        "user": {"id": user.id, "username": user.username, "display_name": user.display_name},
    }


@router.get("/me")
def get_me(db: Session = Depends(get_db)):
    """验证当前token是否有效（前端用来检查登录状态）"""
    # 这个端点由中间件保护，能到达这里说明token有效
    return {"status": "ok"}
