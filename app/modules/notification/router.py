"""通知 API 路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.modules.auth.deps import get_current_user_id
from app.modules.notification.service import NotificationService
from app.modules.notification.schemas import SendNotificationRequest, SendNotificationResponse, NotificationLogListResponse

router = APIRouter()

def get_service(db: Session = Depends(get_db)) -> NotificationService:
    return NotificationService(db)

@router.post("/send", response_model=SendNotificationResponse)
async def send_notifications(request: SendNotificationRequest, service: NotificationService = Depends(get_service), db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    from app.modules.scheduling.models import Interview, Interviewer
    from app.modules.resume.models import Resume
    from app.config import settings
    from fastapi import HTTPException

    interview = db.query(Interview).filter(Interview.id == request.interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")
    if not interview.meeting_link:
        raise HTTPException(status_code=400, detail="请先创建腾讯会议后再发送面试通知")

    warnings = []

    interviewer = db.query(Interviewer).filter(Interviewer.id == interview.interviewer_id).first()
    if request.send_feishu_to_interviewer:
        if not settings.feishu_app_id or not settings.feishu_app_secret:
            warnings.append("飞书未配置，将跳过飞书通知")
            request.send_feishu_to_interviewer = False
        elif interviewer and not interviewer.feishu_user_id:
            warnings.append(f"面试官「{interviewer.name}」无飞书ID，将跳过飞书通知")
            request.send_feishu_to_interviewer = False

    resume = db.query(Resume).filter(Resume.id == interview.resume_id).first()
    if resume and not resume.phone and not resume.email:
        warnings.append("候选人无联系方式，消息模板生成后请手动联系")

    result = await service.send_interview_notifications(
        request.interview_id, send_email=request.send_email_to_candidate,
        send_feishu=request.send_feishu_to_interviewer, generate_template=request.generate_template,
        user_id=user_id)

    if warnings:
        result["warnings"] = warnings

    return result

@router.delete("/clear-all", status_code=200)
def clear_all_logs(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    from app.modules.notification.models import NotificationLog
    count = db.query(NotificationLog).filter(NotificationLog.user_id == user_id).count()
    db.query(NotificationLog).filter(NotificationLog.user_id == user_id).delete(synchronize_session=False)
    db.commit()
    return {"deleted": count}

@router.get("/logs", response_model=NotificationLogListResponse)
def list_logs(interview_id: int | None = None, service: NotificationService = Depends(get_service), user_id: int = Depends(get_current_user_id)):
    return service.list_logs(interview_id=interview_id, user_id=user_id)
