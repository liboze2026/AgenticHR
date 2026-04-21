"""简历管理 API 路由"""
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings

from app.database import get_db
from app.modules.auth.deps import get_current_user_id
from app.modules.resume.service import ResumeService
from app.modules.resume.schemas import (
    ResumeCreate,
    ResumeUpdate,
    ResumeResponse,
    ResumeListResponse,
)

router = APIRouter()


def get_resume_service(db: Session = Depends(get_db)) -> ResumeService:
    return ResumeService(db)


@router.delete("/clear-all", status_code=200)
def clear_all_resumes(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """清空当前用户的所有简历、关联的面试和通知记录、以及PDF文件"""
    import os, glob
    from app.modules.resume.models import Resume
    from app.modules.scheduling.models import Interview
    from app.modules.notification.models import NotificationLog
    # 先获取当前用户的简历ID列表，再删关联数据（外键约束）
    user_resume_ids = [r.id for r in db.query(Resume.id).filter(Resume.user_id == user_id).all()]
    interview_count = db.query(Interview).filter(Interview.resume_id.in_(user_resume_ids)).count() if user_resume_ids else 0
    if user_resume_ids:
        user_interview_ids = [i.id for i in db.query(Interview.id).filter(Interview.resume_id.in_(user_resume_ids)).all()]
        notification_count = db.query(NotificationLog).filter(NotificationLog.interview_id.in_(user_interview_ids)).count() if user_interview_ids else 0
        if user_interview_ids:
            db.query(NotificationLog).filter(NotificationLog.interview_id.in_(user_interview_ids)).delete(synchronize_session=False)
        db.query(Interview).filter(Interview.resume_id.in_(user_resume_ids)).delete(synchronize_session=False)
        # 级联清 F2 匹配结果（无 FK，需手动）
        try:
            from app.modules.matching.models import MatchingResult
            db.query(MatchingResult).filter(
                MatchingResult.resume_id.in_(user_resume_ids)
            ).delete(synchronize_session=False)
        except Exception:
            pass
    else:
        notification_count = 0
    count = db.query(Resume).filter(Resume.user_id == user_id).count()
    db.query(Resume).filter(Resume.user_id == user_id).delete(synchronize_session=False)
    db.commit()
    for f in glob.glob(os.path.join(settings.resume_storage_path, "*.pdf")):
        os.remove(f)
    return {"deleted_resumes": count, "deleted_interviews": interview_count, "deleted_notifications": notification_count}


@router.post("/", response_model=ResumeResponse, status_code=201)
def create_resume(
    data: ResumeCreate,
    service: ResumeService = Depends(get_resume_service),
    user_id: int = Depends(get_current_user_id),
):
    resume, is_new = service.create(data, user_id=user_id)
    return resume


@router.post("/batch", status_code=201)
def batch_create_resumes(
    resumes: list[ResumeCreate],
    service: ResumeService = Depends(get_resume_service),
    user_id: int = Depends(get_current_user_id),
):
    if len(resumes) > 100:
        raise HTTPException(status_code=400, detail="单次批量导入不能超过100条")
    created = 0
    duplicates = 0
    for data in resumes:
        resume, is_new = service.create(data, user_id=user_id)
        if is_new:
            created += 1
        else:
            duplicates += 1
    return {"created": created, "duplicates": duplicates, "total": len(resumes)}


@router.post("/upload", response_model=ResumeResponse, status_code=201)
def upload_pdf_resume(
    file: UploadFile = File(...),
    candidate_name: str = Form(""),
    candidate_phone: str = Form(""),
    candidate_email: str = Form(""),
    candidate_education: str = Form(""),
    candidate_work_years: int = Form(0),
    candidate_job: str = Form(""),
    service: ResumeService = Depends(get_resume_service),
    user_id: int = Depends(get_current_user_id),
):
    # 检查文件类型：文件名或 content-type 任一匹配即可
    is_pdf = (file.filename or "").lower().endswith(".pdf") or (file.content_type or "").startswith("application/pdf")
    if not is_pdf:
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    storage_dir = Path(settings.resume_storage_path)
    storage_dir.mkdir(parents=True, exist_ok=True)

    # 统一命名: 日期_姓名_职位.pdf
    from datetime import datetime
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = (candidate_name or "未知").replace("/", "_").replace("\\", "_")
    safe_job = (candidate_job or "未知职位").replace("/", "_").replace("\\", "_")
    filename = f"{date_str}_{safe_name}_{safe_job}.pdf"
    file_path = storage_dir / filename

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    resume = service.create_from_pdf(
        str(file_path),
        page_info={
            "name": candidate_name,
            "phone": candidate_phone,
            "email": candidate_email,
            "education": candidate_education,
            "work_years": candidate_work_years,
            "job_intention": candidate_job,
        },
        original_filename=file.filename or "",
        user_id=user_id,
    )
    if not resume:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="PDF 解析失败，无法提取内容")
    return resume


@router.get("/settings/storage-path")
def get_storage_path():
    """获取当前 PDF 存储路径"""
    p = Path(settings.resume_storage_path).resolve()
    return {"path": str(p)}


@router.get("/", response_model=ResumeListResponse)
def list_resumes(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: str | None = None,
    keyword: str | None = None,
    source: str | None = None,
    service: ResumeService = Depends(get_resume_service),
    user_id: int = Depends(get_current_user_id),
):
    return service.list(
        page=page, page_size=page_size, status=status, keyword=keyword, source=source, user_id=user_id
    )


@router.get("/ai-parse-status")
def ai_parse_status():
    """查询 AI 解析进度"""
    from app.modules.resume._ai_parse_worker import get_parse_status
    return get_parse_status()


@router.get("/{resume_id}", response_model=ResumeResponse)
def get_resume(
    resume_id: int,
    service: ResumeService = Depends(get_resume_service),
    user_id: int = Depends(get_current_user_id),
):
    resume = service.get_by_id(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    if resume.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该简历")
    return resume


@router.patch("/{resume_id}", response_model=ResumeResponse)
def update_resume(
    resume_id: int,
    data: ResumeUpdate,
    service: ResumeService = Depends(get_resume_service),
    user_id: int = Depends(get_current_user_id),
):
    resume = service.get_by_id(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    if resume.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权修改该简历")
    resume = service.update(resume_id, data)
    return resume


@router.delete("/{resume_id}", status_code=204)
def delete_resume(
    resume_id: int,
    service: ResumeService = Depends(get_resume_service),
    user_id: int = Depends(get_current_user_id),
):
    resume = service.get_by_id(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    if resume.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权删除该简历")
    service.delete(resume_id)


@router.post("/ai-parse-all")
async def ai_parse_all_resumes(user_id: int = Depends(get_current_user_id)):
    """启动后台线程，逐个 AI 解析当前用户所有未解析的简历"""
    from app.config import settings
    if not settings.ai_enabled:
        raise HTTPException(status_code=400, detail="AI 功能未开启，请在设置中启用")

    from app.adapters.ai_provider import AIProvider
    ai = AIProvider()
    if not ai.is_configured():
        raise HTTPException(status_code=400, detail="AI 未配置，请在 .env 中设置 API Key")

    from app.modules.resume._ai_parse_worker import start_ai_parse_worker, _status
    if _status.get("running"):
        return {"status": "already_running", "message": "AI解析任务已在运行中，请勿重复启动"}

    import threading
    thread = threading.Thread(target=start_ai_parse_worker, args=(user_id,), daemon=True)
    thread.start()

    return {"status": "started", "message": "AI 解析任务已在后台启动"}


@router.post("/{resume_id}/ai-parse", response_model=ResumeResponse)
async def ai_parse_single(
    resume_id: int,
    background_tasks: BackgroundTasks,
    service: ResumeService = Depends(get_resume_service),
    user_id: int = Depends(get_current_user_id),
):
    """AI 解析单条简历"""
    from app.config import settings as cfg
    if not cfg.ai_enabled:
        raise HTTPException(status_code=400, detail="AI 功能未开启")

    resume = service.get_by_id(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    if resume.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该简历")

    from app.adapters.ai_provider import AIProvider
    from app.modules.resume.pdf_parser import ai_parse_resume, ai_parse_resume_vision, is_image_pdf
    import os

    ai = AIProvider()
    if not ai.is_configured():
        raise HTTPException(status_code=400, detail="AI 未配置")

    # 判断用文本模式还是视觉模式
    parsed = {}
    use_vision = False
    if resume.pdf_path and os.path.exists(resume.pdf_path):
        if not resume.raw_text or len(resume.raw_text.strip()) < 50 or is_image_pdf(resume.pdf_path):
            use_vision = True

    if use_vision:
        parsed = await ai_parse_resume_vision(resume.pdf_path, ai)
        if parsed:
            resume.raw_text = f"[AI视觉解析] 姓名:{parsed.get('name','')} 技能:{parsed.get('skills','')} 经历:{parsed.get('work_experience','')}"
    elif resume.raw_text:
        parsed = await ai_parse_resume(resume.raw_text, ai)

    if not parsed:
        raise HTTPException(status_code=500, detail="AI 解析失败")

    # 更新字段（dict/list 转字符串）
    def _s(v):
        return str(v) if isinstance(v, (dict, list)) else (v or "")

    if parsed.get("name") and resume.name == "未知":
        resume.name = _s(parsed["name"])
    if parsed.get("phone") and not resume.phone:
        resume.phone = _s(parsed["phone"])
    if parsed.get("email") and not resume.email:
        resume.email = _s(parsed["email"])
    if parsed.get("education"):
        resume.education = _s(parsed["education"])
    if parsed.get("bachelor_school"):
        resume.bachelor_school = _s(parsed["bachelor_school"])
    if parsed.get("master_school"):
        resume.master_school = _s(parsed["master_school"])
    if parsed.get("phd_school"):
        resume.phd_school = _s(parsed["phd_school"])
    if parsed.get("work_years"):
        val = parsed["work_years"]
        resume.work_years = int(val) if isinstance(val, (int, float)) else 0
    if parsed.get("skills"):
        resume.skills = _s(parsed["skills"])
    if parsed.get("work_experience"):
        resume.work_experience = _s(parsed["work_experience"])
    if parsed.get("project_experience"):
        resume.project_experience = _s(parsed["project_experience"])
    if parsed.get("self_evaluation"):
        resume.self_evaluation = _s(parsed["self_evaluation"])
    if parsed.get("job_intention") and not resume.job_intention:
        resume.job_intention = _s(parsed["job_intention"])

    resume.seniority = (parsed.get("seniority") or "").strip() or ""

    resume.ai_parsed = "yes"
    service.db.commit()
    service.db.refresh(resume)

    # F2 T1 trigger: score resume against all active+approved jobs (background, non-blocking)
    try:
        async def _t1_bg():
            from app.database import SessionLocal
            from app.modules.matching.triggers import on_resume_parsed
            _db = SessionLocal()
            try:
                await on_resume_parsed(_db, resume.id)
            finally:
                _db.close()
        background_tasks.add_task(_t1_bg)
    except Exception as _t1_err:
        import logging as _log
        _log.getLogger(__name__).warning(f"F2 T1 trigger failed (non-fatal): {_t1_err}")

    return resume


@router.get("/{resume_id}/qr")
def get_resume_qr(
    resume_id: int,
    regen: int = 0,
    service: ResumeService = Depends(get_resume_service),
    user_id: int = Depends(get_current_user_id),
):
    """返回简历左上角裁剪出的二维码图片。

    自愈机制：如果磁盘上没有缓存的 QR 图（被误删、从未生成过等），
    尝试从 PDF 现场裁剪一张回来。成功则写回 DB、返回图片。

    `?regen=1`：强制忽略缓存，立即重跑算法（用于算法升级后让旧缓存重生成）。
    """
    resume = service.get_by_id(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    if resume.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该简历")

    # 先尝试用 DB 记录的路径；不存在或 regen=1 则从 PDF 即时生成
    qr_path = resume.qr_code_path
    need_regen = regen == 1 or (not qr_path) or (not Path(qr_path).exists())
    if need_regen and resume.pdf_path and Path(resume.pdf_path).exists():
        from app.modules.resume.pdf_parser import extract_boss_qr
        qr_out = Path("data/qrcodes") / f"{resume.id}.png"
        # 强制重生成时先删旧文件
        if regen == 1 and qr_out.exists():
            try:
                qr_out.unlink()
            except Exception:
                pass
        qr_path = extract_boss_qr(resume.pdf_path, str(qr_out))
        if qr_path:
            resume.qr_code_path = qr_path
            service.db.commit()

    if not qr_path or not Path(qr_path).exists():
        raise HTTPException(status_code=404, detail="二维码不存在")

    # 关键：禁掉浏览器缓存。一旦磁盘上的 QR 被重新生成（文件内容变了但 URL 没变），
    # 浏览器必须拿到最新版本，而不能从本地缓存里掏一份过期的（甚至缓存的 404）
    return FileResponse(
        str(qr_path),
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.get("/{resume_id}/pdf")
def get_resume_pdf(
    resume_id: int,
    service: ResumeService = Depends(get_resume_service),
    user_id: int = Depends(get_current_user_id),
):
    """下载/查看候选人的 PDF 简历"""
    resume = service.get_by_id(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")
    if resume.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该简历")
    if not resume.pdf_path:
        raise HTTPException(status_code=404, detail="该候选人没有 PDF 简历")

    pdf_file = Path(resume.pdf_path)
    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在")

    return FileResponse(
        str(pdf_file),
        media_type="application/pdf",
        filename=f"{resume.name}_简历.pdf",
        content_disposition_type="inline",  # 浏览器中直接打开，不下载
    )
