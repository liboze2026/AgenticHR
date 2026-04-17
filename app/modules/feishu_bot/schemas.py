"""飞书机器人事件与消息结构"""
from pydantic import BaseModel, Field


class FeishuEvent(BaseModel):
    """飞书事件回调"""
    schema_version: str = Field(default="", alias="schema")
    header: dict = {}
    event: dict = {}


class FeishuChallenge(BaseModel):
    """飞书 URL 验证"""
    challenge: str
    token: str = ""
    type: str = ""
