"""飞书机器人事件回调路由"""
import json
import logging
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.feishu_bot.schemas import FeishuEvent
from app.modules.feishu_bot.command_handler import CommandHandler
from app.adapters.feishu import FeishuAdapter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/event")
async def handle_feishu_event(request: Request, db: Session = Depends(get_db)):
    """处理飞书事件回调"""
    body = await request.json()

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
