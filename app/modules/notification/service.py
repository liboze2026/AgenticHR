"""通知业务逻辑"""
import logging
from sqlalchemy.orm import Session
from app.adapters.email_sender import EmailSender
from app.adapters.feishu import FeishuAdapter
from app.modules.notification.models import NotificationLog
from app.modules.notification.templates import (
    interview_email_to_candidate, interview_feishu_to_interviewer, interview_template_for_copy,
)
from app.modules.scheduling.models import Interview, Interviewer
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, db: Session, email_sender: EmailSender | None = None, feishu_adapter: FeishuAdapter | None = None):
        self.db = db
        self.email = email_sender or EmailSender()
        self.feishu = feishu_adapter or FeishuAdapter()

    async def send_interview_notifications(self, interview_id: int, send_email=True, send_feishu=True, generate_template=True, user_id: int = 0) -> dict:
        interview = self.db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            return {"interview_id": interview_id, "results": []}

        resume = self.db.query(Resume).filter(Resume.id == interview.resume_id).first()
        interviewer = self.db.query(Interviewer).filter(Interviewer.id == interview.interviewer_id).first()
        job = self.db.query(Job).filter(Job.id == interview.job_id).first() if interview.job_id else None

        candidate_name = resume.name if resume else "候选人"
        interviewer_name = interviewer.name if interviewer else "面试官"
        job_title = job.title if job else (resume.job_intention if resume and resume.job_intention else "未指定岗位")
        # DB 存 UTC，转北京时间显示
        from datetime import timedelta
        beijing_time = interview.start_time + timedelta(hours=8)
        interview_time = beijing_time.strftime("%Y-%m-%d %H:%M")
        meeting_link = interview.meeting_link or "待定"
        meeting_password = interview.meeting_password or ""

        results = []

        if send_email and resume and resume.email:
            subject, body = interview_email_to_candidate(candidate_name, interviewer_name, job_title, interview_time, meeting_link, meeting_password)
            success = self.email.send(resume.email, subject, body)
            status = "sent" if success else "failed"
            self._log(interview_id, "candidate", candidate_name, "email", resume.email, subject, body, status, user_id=user_id)
            results.append({"channel": "email", "recipient": resume.email, "status": status})

        if send_feishu and interviewer and interviewer.feishu_user_id:
            # 构建更丰富的候选人简介
            summary_parts = []
            if resume:
                if resume.education: summary_parts.append(f"学历：{resume.education}")
                if resume.work_years: summary_parts.append(f"工作年限：{resume.work_years}年")
                if resume.skills: summary_parts.append(f"技能：{resume.skills}")
                if resume.job_intention: summary_parts.append(f"求职意向：{resume.job_intention}")
                if resume.phone: summary_parts.append(f"手机：{resume.phone}")
                if resume.email: summary_parts.append(f"邮箱：{resume.email}")
            resume_summary = "\n".join(summary_parts) if summary_parts else ""
            msg = interview_feishu_to_interviewer(interviewer_name, candidate_name, job_title, interview_time, meeting_link, resume_summary)
            success = await self.feishu.send_message(interviewer.feishu_user_id, msg)
            status = "sent" if success else "failed"
            self._log(interview_id, "interviewer", interviewer_name, "feishu", interviewer.feishu_user_id, "面试通知", msg, status, user_id=user_id)
            results.append({"channel": "feishu", "recipient": interviewer_name, "status": status})

            # 发送 PDF 简历附件
            if success and resume and resume.pdf_path:
                import os
                from pathlib import Path as _Path
                from app.config import settings as _svc_settings
                _pdf_path = _Path(resume.pdf_path).resolve()
                _storage_root = _Path(_svc_settings.resume_storage_path).resolve()
                _is_safe = str(_pdf_path).startswith(str(_storage_root))
                if _is_safe and os.path.exists(resume.pdf_path):
                    file_key = await self.feishu.upload_file(resume.pdf_path, f"{candidate_name}_简历.pdf")
                    if file_key:
                        pdf_sent = await self.feishu.send_file(interviewer.feishu_user_id, file_key)
                        pdf_status = "sent" if pdf_sent else "failed"
                        self._log(interview_id, "interviewer", interviewer_name, "feishu", interviewer.feishu_user_id, "简历PDF", f"文件: {candidate_name}_简历.pdf", pdf_status, user_id=user_id)
                        results.append({"channel": "feishu_pdf", "recipient": interviewer_name, "status": pdf_status})

        # 创建飞书日程（先删旧的，再建新的）
        if interviewer and interviewer.feishu_user_id:
            from datetime import timedelta

            # 删除旧日程
            if interview.feishu_event_id:
                await self.feishu.delete_calendar_event(interview.feishu_event_id)
                interview.feishu_event_id = ""

            beijing_start = interview.start_time + timedelta(hours=8)
            beijing_end = interview.end_time + timedelta(hours=8)
            start_ts = int(beijing_start.timestamp())
            end_ts = int(beijing_end.timestamp())

            cal_summary = f"面试 - {candidate_name}"
            cal_desc = f"候选人：{candidate_name}\n岗位：{job_title}\n会议链接：{meeting_link}"

            event_id = await self.feishu.create_calendar_event(
                summary=cal_summary,
                description=cal_desc,
                start_timestamp=start_ts,
                end_timestamp=end_ts,
                attendee_open_id=interviewer.feishu_user_id,
            )
            if event_id:
                interview.feishu_event_id = event_id
                self.db.commit()

            cal_status = "sent" if event_id else "failed"
            self._log(interview_id, "interviewer", interviewer_name, "calendar", "", "飞书日程", cal_summary, cal_status, user_id=user_id)
            results.append({"channel": "calendar", "recipient": interviewer_name, "status": cal_status})

        if generate_template:
            template = interview_template_for_copy(candidate_name, job_title, interview_time, meeting_link, meeting_password)
            self._log(interview_id, "candidate", candidate_name, "template", "", "消息模板", template, "generated", user_id=user_id)
            results.append({"channel": "template", "recipient": candidate_name, "status": "generated", "content": template})

        return {"interview_id": interview_id, "results": results}

    def list_logs(self, interview_id: int | None = None, user_id: int | None = None) -> dict:
        query = self.db.query(NotificationLog)
        if user_id is not None:
            query = query.filter(NotificationLog.user_id == user_id)
        if interview_id:
            query = query.filter(NotificationLog.interview_id == interview_id)
        items = query.order_by(NotificationLog.created_at.desc()).all()
        return {"total": len(items), "items": items}

    def _log(self, interview_id, recipient_type, recipient_name, channel, address, subject, content, status, user_id: int = 0):
        log = NotificationLog(interview_id=interview_id, recipient_type=recipient_type, recipient_name=recipient_name,
                              channel=channel, recipient_address=address, subject=subject, content=content, status=status,
                              user_id=user_id)
        self.db.add(log)
        self.db.commit()
