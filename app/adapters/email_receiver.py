"""IMAP 邮件接收适配器

连接 IMAP 服务器，搜索未读邮件，下载 PDF 附件作为简历。
"""
import email
import imaplib
import os
from email.header import decode_header
from pathlib import Path

from app.config import settings


class EmailReceiver:
    """IMAP 邮件接收器，用于获取简历附件"""

    def __init__(
        self,
        host: str = "",
        port: int = 0,
        user: str = "",
        password: str = "",
    ):
        self.host = host or settings.imap_host
        self.port = port or settings.imap_port
        self.user = user or settings.imap_user
        self.password = password or settings.imap_password

    def is_configured(self) -> bool:
        """检查 IMAP 配置是否完整"""
        return bool(self.host and self.user and self.password)

    @staticmethod
    def _decode_header(header_value: str) -> str:
        """解码邮件头（可能含编码片段）"""
        if not header_value:
            return ""
        decoded_parts = decode_header(header_value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(part)
        return "".join(result)

    def fetch_new_resumes(self, save_dir: str = "") -> list[dict]:
        """从 IMAP 获取未读邮件中的 PDF 附件

        Returns:
            list[dict]: 每个元素包含 sender, subject, filename, filepath
        """
        if not self.is_configured():
            return []

        save_path = Path(save_dir or settings.resume_storage_path)
        save_path.mkdir(parents=True, exist_ok=True)

        results: list[dict] = []

        try:
            mail = imaplib.IMAP4_SSL(self.host, self.port)
            mail.login(self.user, self.password)
            mail.select("INBOX")

            _, message_numbers = mail.search(None, "UNSEEN")
            if not message_numbers[0]:
                mail.logout()
                return results

            for num in message_numbers[0].split():
                _, msg_data = mail.fetch(num, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]  # type: ignore
                msg = email.message_from_bytes(raw_email)

                sender = self._decode_header(msg.get("From", ""))
                subject = self._decode_header(msg.get("Subject", ""))

                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))

                    if "attachment" not in content_disposition:
                        continue

                    filename = part.get_filename()
                    if not filename:
                        continue

                    filename = self._decode_header(filename)
                    if not filename.lower().endswith(".pdf"):
                        continue

                    # 保存 PDF 附件
                    filepath = save_path / filename
                    # 避免文件名冲突
                    counter = 1
                    while filepath.exists():
                        stem = Path(filename).stem
                        filepath = save_path / f"{stem}_{counter}.pdf"
                        counter += 1

                    payload = part.get_payload(decode=True)
                    if payload:
                        with open(filepath, "wb") as f:
                            f.write(payload)

                        results.append({
                            "sender": sender,
                            "subject": subject,
                            "filename": filename,
                            "filepath": str(filepath),
                        })

            mail.logout()
        except Exception:
            pass

        return results
