"""会议管理 API 路由"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.meeting.account_pool import pick_available_account

router = APIRouter()


@router.post("/auto-create")
async def auto_create_meeting(interview_id: int, db: Session = Depends(get_db)):
    """用 Playwright 自动在腾讯会议网页上创建会议，并回填到面试安排。

    多账号池调度：根据面试时段和已有面试占用情况，从 settings.tencent_meeting_accounts
    里挑一个当前时段没有冲突的账号主持本次会议。全部占满时返回 409。
    """
    from app.modules.scheduling.models import Interview, Interviewer
    from app.modules.resume.models import Resume

    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="面试不存在")

    # 挑一个可用的腾讯会议账号（全忙会直接抛 409 由前端提示）
    # exclude 当前 interview 是为了"重建会议"场景：它自己之前占用的账号应该被重新纳入候选
    account = pick_available_account(
        db, interview.start_time, interview.end_time, exclude_interview_id=interview.id
    )

    resume = db.query(Resume).filter(Resume.id == interview.resume_id).first()
    interviewer = db.query(Interviewer).filter(Interviewer.id == interview.interviewer_id).first()

    candidate_name = resume.name if resume else "候选人"
    interviewer_name = interviewer.name if interviewer else "面试官"

    # DB 存的是 UTC，转北京时间
    beijing_start = interview.start_time + timedelta(hours=8)
    beijing_end = interview.end_time + timedelta(hours=8)

    # 检测时间取整
    original_minutes = beijing_start.minute
    rounded_minutes = (original_minutes // 30) * 30
    time_rounded = original_minutes != rounded_minutes
    if time_rounded:
        rounded_start = beijing_start.replace(minute=rounded_minutes, second=0)
        start_time_str = rounded_start.strftime("%H:%M")

    start_date = beijing_start.strftime("%Y/%m/%d")
    if not time_rounded:
        start_time_str = beijing_start.strftime("%H:%M")
    end_date = beijing_end.strftime("%Y/%m/%d")
    end_time_str = beijing_end.strftime("%H:%M")

    # 优先使用面试记录里存的会议名称；为空时用默认格式兜底
    topic = (interview.meeting_topic or "").strip() \
        or f"面试-{candidate_name}-{interviewer_name}"

    from app.adapters.tencent_meeting_web import create_meeting
    result = await create_meeting(
        topic, start_date, start_time_str, end_date, end_time_str,
        account_label=account,
    )

    if result.get("success"):
        interview.meeting_link = result["link"]
        interview.meeting_password = result.get("password", "")
        interview.meeting_account = account
        interview.meeting_id = result.get("meeting_id", "")
        tz8 = timezone(timedelta(hours=8))
        now = datetime.now(tz8).strftime("%m-%d %H:%M")
        note = f"[{now}] 腾讯会议已创建 (账号: {account}, ID: {result['meeting_id']})"
        interview.notes = f"{interview.notes}\n{note}" if interview.notes else note
        db.commit()
        response = {
            "status": "ok",
            "link": result["link"],
            "meeting_id": result["meeting_id"],
            "account": account,
        }
        if time_rounded:
            response["warning"] = f"腾讯会议仅支持整点/半点，开始时间已从 {beijing_start.strftime('%H:%M')} 调整为 {start_time_str}"
        return response
    else:
        raise HTTPException(status_code=500, detail=result.get("error", "创建失败"))
