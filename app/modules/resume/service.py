"""简历业务逻辑"""
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.modules.resume.models import Resume
from app.modules.resume.schemas import ResumeCreate, ResumeUpdate


class ResumeService:
    def __init__(self, db: Session):
        self.db = db

    def _find_duplicate(self, name: str, phone: str = "", email: str = "", user_id: int = 0) -> Resume | None:
        """组合特征去重，匹配优先级：手机号 > 邮箱 > 同名无联系方式"""
        if not name:
            return None

        # 1. 手机号匹配（最可靠，同手机号一定是同一个人）
        if phone:
            existing = self.db.query(Resume).filter(Resume.phone == phone, Resume.user_id == user_id).first()
            if existing:
                return existing

        # 2. 邮箱匹配
        if email:
            existing = self.db.query(Resume).filter(Resume.email == email, Resume.user_id == user_id).first()
            if existing:
                return existing

        # 3. 同名 + 同来源 + 对方也没有手机和邮箱（重复采集同一个人）
        if not phone and not email:
            existing = (
                self.db.query(Resume)
                .filter(Resume.name == name, Resume.phone == "", Resume.email == "", Resume.user_id == user_id)
                .first()
            )
            if existing:
                return existing

        return None

    def _update_fields(self, existing: Resume, new_data: dict):
        """用新数据刷新已有记录，非空字段覆盖旧值"""
        for key, val in new_data.items():
            if val is None or val == "" or val == 0:
                continue
            # raw_text 只在更长时覆盖
            if key == "raw_text":
                if len(str(val)) > len(existing.raw_text or ""):
                    existing.raw_text = str(val)
                continue
            if not hasattr(existing, key):
                continue
            # dict/list 转字符串（AI 模型可能返回结构化对象）
            if isinstance(val, (dict, list)):
                val = str(val)
            setattr(existing, key, val)

    def create(self, data: ResumeCreate, user_id: int = 0) -> tuple[Resume, bool]:
        """创建或更新简历。重复则刷新信息。返回 (resume, is_new)"""
        existing = self._find_duplicate(data.name, data.phone, data.email, user_id=user_id)
        if existing:
            self._update_fields(existing, data.model_dump())
            self.db.commit()
            self.db.refresh(existing)
            return existing, False

        resume = Resume(**data.model_dump())
        resume.user_id = user_id
        self.db.add(resume)
        self.db.commit()
        self.db.refresh(resume)
        # 新简历入库后，自动触发后台 AI 解析（幂等，worker 已在跑则跳过）
        try:
            from app.modules.resume._ai_parse_worker import maybe_start_worker_thread
            maybe_start_worker_thread()
        except Exception:
            pass
        return resume, True

    def get_by_id(self, resume_id: int) -> Resume | None:
        return self.db.query(Resume).filter(Resume.id == resume_id).first()

    def list(
        self,
        page: int = 1,
        page_size: int = 10,
        status: str | None = None,
        keyword: str | None = None,
        source: str | None = None,
        intake_status: str | None = None,
        user_id: int = 0,
    ) -> dict:
        query = self.db.query(Resume)

        query = query.filter(Resume.user_id == user_id)

        if status:
            query = query.filter(Resume.status == status)
        if intake_status:
            query = query.filter(Resume.intake_status == intake_status)
        if source:
            query = query.filter(Resume.source == source)
        if keyword:
            pattern = f"%{keyword}%"
            query = query.filter(
                or_(
                    Resume.name.like(pattern),
                    Resume.skills.like(pattern),
                    Resume.job_intention.like(pattern),
                    Resume.work_experience.like(pattern),
                    Resume.raw_text.like(pattern),
                )
            )

        total = query.count()
        items = (
            query.order_by(Resume.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }

    def update(self, resume_id: int, data: ResumeUpdate) -> Resume | None:
        resume = self.get_by_id(resume_id)
        if not resume:
            return None

        update_data = data.model_dump(exclude_none=True)
        for key, value in update_data.items():
            setattr(resume, key, value)

        self.db.commit()
        self.db.refresh(resume)
        return resume

    def delete(self, resume_id: int) -> bool:
        resume = self.get_by_id(resume_id)
        if not resume:
            return False
        # 级联清理：matching_results 没有 FK，需要手动清，否则会留孤儿行
        try:
            from app.modules.matching.models import MatchingResult
            self.db.query(MatchingResult).filter(
                MatchingResult.resume_id == resume_id
            ).delete(synchronize_session=False)
        except Exception:
            pass
        self.db.delete(resume)
        self.db.commit()
        return True

    def create_from_pdf(self, file_path: str, page_info: dict | None = None, original_filename: str = "", user_id: int = 0, boss_id: str = "") -> Resume | None:
        """从 PDF 文件创建简历，合并三个信息源：页面抓取 > 文件名解析 > PDF文本正则

        Args:
            file_path: PDF 文件路径
            page_info: 从 Boss 直聘页面抓取的候选人信息
            original_filename: Boss 直聘原始 PDF 文件名（含手机号邮箱等）
            boss_id: Boss 直聘候选人 ID（最高优先级去重键）
        """
        from app.modules.resume.pdf_parser import parse_pdf, extract_resume_fields, parse_boss_filename, extract_boss_qr
        from pathlib import Path as _Path

        raw_text = parse_pdf(file_path)
        if not raw_text:
            return None

        pdf_fields = extract_resume_fields(raw_text)
        filename_fields = parse_boss_filename(original_filename)
        page = page_info or {}

        # 合并策略（优先级）: 页面信息 > 文件名解析 > PDF文本正则
        name = page.get("name") or filename_fields.get("name") or "未知"
        phone = page.get("phone") or filename_fields.get("phone") or pdf_fields.get("phone") or ""
        email = page.get("email") or filename_fields.get("email") or pdf_fields.get("email") or ""
        education = page.get("education") or pdf_fields.get("education") or ""
        work_years = page.get("work_years") or 0
        job_intention = page.get("job_intention") or ""
        skills = pdf_fields.get("skills") or ""
        work_experience = pdf_fields.get("work_experience") or ""

        merge_fields = {
            "name": name, "phone": phone, "email": email,
            "education": education, "work_years": work_years,
            "job_intention": job_intention, "skills": skills,
            "work_experience": work_experience,
        }

        # boss_id 去重：优先级最高（精确身份匹配，避免 PDF 上传重复创建）
        if boss_id:
            existing_by_boss = self.db.query(Resume).filter(
                Resume.boss_id == boss_id, Resume.user_id == user_id
            ).first()
            if existing_by_boss:
                self._update_fields(existing_by_boss, merge_fields)
                existing_by_boss.raw_text = raw_text
                existing_by_boss.pdf_path = file_path
                qr_out = _Path("data/qrcodes") / f"{existing_by_boss.id}.png"
                qr_path = extract_boss_qr(file_path, str(qr_out))
                if qr_path:
                    existing_by_boss.qr_code_path = qr_path
                self.db.commit()
                self.db.refresh(existing_by_boss)
                return existing_by_boss

        # 组合特征去重
        existing = self._find_duplicate(name, phone, email, user_id=user_id)
        if existing:
            self._update_fields(existing, {
                "name": name, "phone": phone, "email": email,
                "education": education, "work_years": work_years,
                "job_intention": job_intention, "skills": skills,
                "work_experience": work_experience,
            })
            existing.raw_text = raw_text
            existing.pdf_path = file_path
            # 提取二维码（覆盖旧的）
            qr_out = _Path("data/qrcodes") / f"{existing.id}.png"
            qr_path = extract_boss_qr(file_path, str(qr_out))
            if qr_path:
                existing.qr_code_path = qr_path
            self.db.commit()
            self.db.refresh(existing)
            return existing

        resume = Resume(
            name=name,
            phone=phone,
            email=email,
            education=education,
            work_years=work_years,
            job_intention=job_intention,
            skills=skills,
            work_experience=work_experience,
            source="boss_zhipin",
            raw_text=raw_text,
            pdf_path=file_path,
            user_id=user_id,
        )
        self.db.add(resume)
        self.db.commit()
        self.db.refresh(resume)
        # 创建后再提取 QR（需要 resume.id）
        qr_out = _Path("data/qrcodes") / f"{resume.id}.png"
        qr_path = extract_boss_qr(file_path, str(qr_out))
        if qr_path:
            resume.qr_code_path = qr_path
            self.db.commit()
            self.db.refresh(resume)
        # 新简历入库后，自动触发后台 AI 解析
        try:
            from app.modules.resume._ai_parse_worker import maybe_start_worker_thread
            maybe_start_worker_thread()
        except Exception:
            pass
        return resume
