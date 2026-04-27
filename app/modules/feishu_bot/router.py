"""飞书机器人事件回调路由"""
import hashlib
import hmac
import json
import logging
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.modules.feishu_bot.schemas import FeishuEvent
from app.modules.feishu_bot.command_handler import CommandHandler
from app.adapters.feishu import FeishuAdapter

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_feishu_signature(request_timestamp: str, nonce: str, body_bytes: bytes, signature: str) -> bool:
    """验证飞书事件签名 (SHA256)"""
    app_secret = settings.feishu_app_secret
    if not app_secret:
        # 未配置飞书密钥时跳过验证（开发环境）
        return True
    content = (request_timestamp + nonce + app_secret).encode("utf-8") + body_bytes
    expected = hashlib.sha256(content).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/event")
async def handle_feishu_event(request: Request, db: Session = Depends(get_db)):
    """处理飞书事件回调"""
    # BUG-008: 验证飞书请求签名，防止伪造事件注入
    body_bytes = await request.body()
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")

    if settings.feishu_app_secret and signature:
        if not _verify_feishu_signature(timestamp, nonce, body_bytes, signature):
            raise HTTPException(status_code=401, detail="飞书签名验证失败")

    try:
        body = json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="无效 JSON")

    # URL 验证（飞书首次配置时会发送 challenge）
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    # 处理消息事件
    event = body.get("event", {})
    msg = event.get("message", {})
    content = msg.get("content", "{}")
    chat_id = msg.get("chat_id", "")

    # 提取文本内容
    try:
        text = json.loads(content).get("text", "").strip()
    except (json.JSONDecodeError, AttributeError):
        text = ""

    if not text:
        return {"status": "ok"}

    # 去掉 @机器人 的前缀
    if "@_" in text:
        text = text.split("@_")[-1].strip()

    # 执行指令
    handler = CommandHandler(db)
    reply = handler.handle(text)

    # 发送回复
    feishu = FeishuAdapter()
    sender_id = event.get("sender", {}).get("sender_id", {}).get("user_id", "")
    if sender_id:
        await feishu.send_message(sender_id, reply)

    return {"status": "ok"}


@router.get("/status")
def bot_status():
    feishu = FeishuAdapter()
    return {
        "configured": feishu.is_configured(),
    }
