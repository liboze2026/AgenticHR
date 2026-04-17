"""飞书 API 适配器"""
import json
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class FeishuAdapter:
    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self):
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self._token = ""

    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
                    json={"app_id": self.app_id, "app_secret": self.app_secret},
                )
                self._token = resp.json().get("tenant_access_token", "")
                return self._token
        except Exception as e:
            logger.error(f"获取飞书 token 失败: {e}")
            return ""

    async def send_message(self, user_id: str, content: str, msg_type: str = "text") -> bool:
        if not self.is_configured():
            logger.warning("飞书未配置")
            return False
        token = await self._get_token()
        if not token:
            logger.error("获取飞书 token 失败")
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/im/v1/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"receive_id_type": "open_id"},
                    json={"receive_id": user_id, "msg_type": msg_type,
                          "content": json.dumps({"text": content}) if msg_type == "text" else content},
                )
                data = resp.json()
                if data.get("code") == 0:
                    return True
                logger.error(f"飞书发送失败: code={data.get('code')}, msg={data.get('msg')}")
                return False
        except Exception as e:
            logger.error(f"飞书消息发送失败: {e}")
            return False

    async def upload_file(self, file_path: str, file_name: str = "") -> str:
        """上传文件到飞书，返回 file_key。失败返回空字符串。"""
        import os
        if not self.is_configured():
            return ""
        token = await self._get_token()
        if not token:
            return ""
        if not file_name:
            file_name = os.path.basename(file_path)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                with open(file_path, "rb") as f:
                    resp = await client.post(
                        f"{self.BASE_URL}/im/v1/files",
                        headers={"Authorization": f"Bearer {token}"},
                        data={"file_type": "pdf", "file_name": file_name},
                        files={"file": (file_name, f, "application/pdf")},
                    )
                data = resp.json()
                if data.get("code") == 0:
                    file_key = data.get("data", {}).get("file_key", "")
                    logger.info(f"飞书文件上传成功: {file_name} -> {file_key}")
                    return file_key
                logger.error(f"飞书文件上传失败: {data.get('msg')}")
                return ""
        except Exception as e:
            logger.error(f"飞书文件上传异常: {e}")
            return ""

    async def send_file(self, user_id: str, file_key: str) -> bool:
        """发送文件消息给用户"""
        if not file_key:
            return False
        return await self.send_message(
            user_id,
            json.dumps({"file_key": file_key}),
            msg_type="file",
        )

    async def create_calendar_event(
        self, summary: str, description: str,
        start_timestamp: int, end_timestamp: int,
        attendee_open_id: str = "",
    ) -> str:
        """在飞书日历上创建日程。返回 event_id，失败返回空字符串。"""
        if not self.is_configured():
            return ""
        token = await self._get_token()
        if not token:
            return ""
        try:
            body = {
                "summary": summary,
                "description": description,
                "start_time": {"timestamp": str(start_timestamp)},
                "end_time": {"timestamp": str(end_timestamp)},
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                # 创建日程
                resp = await client.post(
                    f"{self.BASE_URL}/calendar/v4/calendars/primary/events",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"user_id_type": "open_id"},
                    json=body,
                )
                data = resp.json()
                if data.get("code") != 0:
                    logger.error(f"创建日程失败: {data.get('msg')}")
                    return ""

                event_id = data.get("data", {}).get("event", {}).get("event_id", "")
                logger.info(f"飞书日程已创建: {summary} (event_id={event_id})")
                self._last_event_id = event_id  # 保存供调用者获取

                # 添加参会人
                if attendee_open_id and event_id:
                    resp2 = await client.post(
                        f"{self.BASE_URL}/calendar/v4/calendars/primary/events/{event_id}/attendees",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"user_id_type": "open_id"},
                        json={
                            "attendees": [{"type": "user", "user_id": attendee_open_id}],
                        },
                    )
                    data2 = resp2.json()
                    if data2.get("code") == 0:
                        logger.info(f"参会人已添加: {attendee_open_id}")
                    else:
                        logger.warning(f"添加参会人失败: {data2.get('msg')}")

                return event_id or ""
        except Exception as e:
            logger.error(f"创建飞书日程失败: {e}")
            return ""

    async def delete_calendar_event(self, event_id: str) -> bool:
        """删除飞书日历上的日程"""
        if not self.is_configured() or not event_id:
            return False
        token = await self._get_token()
        if not token:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.delete(
                    f"{self.BASE_URL}/calendar/v4/calendars/primary/events/{event_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                data = resp.json()
                if data.get("code") == 0:
                    logger.info(f"飞书日程已删除: {event_id}")
                    return True
                logger.warning(f"删除日程失败: {data.get('msg')}")
                return False
        except Exception as e:
            logger.error(f"删除飞书日程失败: {e}")
            return False

    async def lookup_user_id(self, phone: str = "", email: str = "") -> str:
        """按手机号或邮箱从飞书通讯录反查 open_id。找不到或报错返回空字符串。

        调用 POST /contact/v3/users/batch_get_id?user_id_type=open_id
        至少需要通讯录权限 contact:user.employee_id:readonly 或等效权限。
        """
        if not self.is_configured():
            return ""
        if not phone and not email:
            return ""
        token = await self._get_token()
        if not token:
            return ""
        body = {}
        if phone:
            body["mobiles"] = [phone]
        if email:
            body["emails"] = [email]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/contact/v3/users/batch_get_id",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"user_id_type": "open_id"},
                    json=body,
                )
                data = resp.json()
                if data.get("code") != 0:
                    logger.warning(f"飞书反查失败: code={data.get('code')}, msg={data.get('msg')}")
                    return ""
                for item in data.get("data", {}).get("user_list", []):
                    uid = item.get("user_id", "")
                    if uid:
                        return uid
                return ""
        except Exception as e:
            logger.error(f"飞书反查异常: {e}")
            return ""

    async def get_freebusy(self, user_id: str, start_time: str, end_time: str) -> list[dict]:
        if not self.is_configured():
            return []
        token = await self._get_token()
        if not token:
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/calendar/v4/freebusy/list",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"time_min": start_time, "time_max": end_time, "user_id": user_id},
                )
                return resp.json().get("data", {}).get("freebusy_list", [])
        except Exception as e:
            logger.error(f"查询飞书日历失败: {e}")
            return []
