"""SMTP 邮件发送适配器"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import settings

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self):
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.user = settings.smtp_user
        self.password = settings.smtp_password
        self.use_ssl = settings.smtp_use_ssl

    def is_configured(self) -> bool:
        return bool(self.host and self.user and self.password)

    def send(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        if not self.is_configured():
            logger.warning("SMTP 未配置，跳过发送")
            return False
        try:
            msg = MIMEMultipart()
            msg["From"] = self.user
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=30)
                server.starttls()
            server.login(self.user, self.password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            logger.error(f"邮件发送失败 [{to}]: {e}")
            return False
