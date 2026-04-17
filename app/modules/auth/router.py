"""认证 API 路由"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.modules.auth import service as auth_service

router = APIRouter()


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
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = auth_service.authenticate(db, req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
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
