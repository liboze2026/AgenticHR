"""通知 service 测试"""
import pytest
from datetime import datetime, timezone, timedelta
from app.modules.notification.service import NotificationService
from app.modules.scheduling.models import Interview, Interviewer
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


class MockEmailSender:
    def __init__(self): self.sent = []
    def is_configured(self): return True
    def send(self, to, subject, body, html=False):
        self.sent.append({"to": to, "subject": subject})
        return True


class MockFeishuAdapter:
    def __init__(self): self.sent = []
    def is_configured(self): return True
    async def send_message(self, user_id, content, msg_type="text"):
        self.sent.append({"user_id": user_id, "content": content})
        return True
    async def upload_file(self, file_path, file_name=""): return "mock_file_key"
    async def send_file(self, user_id, file_key): return True
    async def create_calendar_event(self, summary="", description="", start_timestamp=0, end_timestamp=0, attendee_open_id=""): return "mock_event_id"
    async def delete_calendar_event(self, event_id): return True


@pytest.fixture
def notification_deps(db_session):
    interviewer = Interviewer(name="张面试官", feishu_user_id="feishu_123", email="zhang@company.com")
    db_session.add(interviewer)
    resume = Resume(name="李候选人", phone="13800001234", email="li@test.com", education="本科", work_years=3, skills="Python")
    db_session.add(resume)
    job = Job(title="Python开发")
    db_session.add(job)
    db_session.commit()

    interview = Interview(
        resume_id=resume.id, interviewer_id=interviewer.id, job_id=job.id,
        start_time=datetime.now(timezone.utc) + timedelta(days=1),
        end_time=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
        meeting_link="https://meeting.tencent.com/test", meeting_password="1234",
    )
    db_session.add(interview)
    db_session.commit()
    return {"interview_id": interview.id}


@pytest.mark.asyncio
async def test_send_all_notifications(db_session, notification_deps):
    email = MockEmailSender()
    feishu = MockFeishuAdapter()
    service = NotificationService(db_session, email_sender=email, feishu_adapter=feishu)

    result = await service.send_interview_notifications(notification_deps["interview_id"])
    # email + feishu + feishu_pdf + calendar + template = 5 (pdf may fail if no file)
    assert len(result["results"]) >= 3
    assert len(email.sent) == 1
    assert email.sent[0]["to"] == "li@test.com"
    assert len(feishu.sent) >= 1
    assert feishu.sent[0]["user_id"] == "feishu_123"
    template_result = [r for r in result["results"] if r["channel"] == "template"][0]
    assert "Python开发" in template_result["content"]


@pytest.mark.asyncio
async def test_notification_logs(db_session, notification_deps):
    email = MockEmailSender()
    feishu = MockFeishuAdapter()
    service = NotificationService(db_session, email_sender=email, feishu_adapter=feishu)
    await service.send_interview_notifications(notification_deps["interview_id"])
    logs = service.list_logs(notification_deps["interview_id"])
    assert logs["total"] >= 3
