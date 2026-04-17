"""飞书机器人指令处理"""
import logging
from sqlalchemy.orm import Session

from app.modules.resume.service import ResumeService
from app.modules.screening.service import ScreeningService
from app.modules.scheduling.service import SchedulingService
from app.modules.notification.service import NotificationService

logger = logging.getLogger(__name__)

# Command definitions
COMMANDS = {
    "查看概览": "dashboard",
    "查看简历": "list_resumes",
    "筛选简历": "screen_resumes",
    "安排面试": "schedule_interview",
    "管理岗位": "list_jobs",
    "帮助": "help",
}


class CommandHandler:
    def __init__(self, db: Session):
        self.db = db
        self.resume_service = ResumeService(db)
        self.screening_service = ScreeningService(db)
        self.scheduling_service = SchedulingService(db)

    def handle(self, text: str) -> str:
        """解析并执行指令，返回回复文本"""
        text = text.strip()

        if text in ("帮助", "help", "/help"):
            return self._help()

        if text.startswith("查看概览") or text == "概览":
            return self._dashboard()

        if text.startswith("查看简历"):
            return self._list_resumes()

        if text.startswith("管理岗位") or text.startswith("查看岗位"):
            return self._list_jobs()

        return self._help()

    def _help(self) -> str:
        return """招聘助手支持以下指令：

- 查看概览 — 查看今日数据概览
- 查看简历 — 查看待处理简历列表
- 管理岗位 — 查看所有岗位
- 帮助 — 显示此帮助信息

更多操作请访问 Web 管理后台"""

    def _dashboard(self) -> str:
        from app.modules.resume.models import Resume
        from app.modules.scheduling.models import Interview

        total_resumes = self.db.query(Resume).count()
        pending = self.db.query(Resume).filter(Resume.status == "pending").count()
        passed = self.db.query(Resume).filter(Resume.status == "passed").count()
        today_interviews = self.db.query(Interview).filter(Interview.status == "scheduled").count()

        return f"""📊 招聘概览

总简历数：{total_resumes}
待筛选：{pending}
已通过：{passed}
待面试：{today_interviews}"""

    def _list_resumes(self) -> str:
        result = self.resume_service.list(page=1, page_size=5, status="pending")
        if not result["items"]:
            return "暂无待处理简历"

        lines = [f"📋 待处理简历（共 {result['total']} 份，显示前5）\n"]
        for r in result["items"]:
            lines.append(f"• {r.name} | {r.education} | {r.work_years}年 | {r.skills[:30]}")
        return "\n".join(lines)

    def _list_jobs(self) -> str:
        result = self.screening_service.list_jobs(active_only=True)
        if not result["items"]:
            return "暂无活跃岗位"

        lines = [f"📌 活跃岗位（共 {result['total']} 个）\n"]
        for j in result["items"]:
            lines.append(f"• {j.title} | {j.department} | 要求：{j.education_min} {j.work_years_min}年+")
        return "\n".join(lines)
