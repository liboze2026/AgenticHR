"""认证依赖注入"""
from fastapi import Request, HTTPException


def get_current_user_id(request: Request) -> int:
    """从中间件设置的 request.state 中获取当前登录用户ID"""
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user_id
