"""扫描并清理 IntakeCandidate / Resume 中的无效 pdf_path。

无效定义：pdf_path 既不是 http(s):// URL，也不是 settings.resume_storage_path 下
存在的文件。例如 BUG-A1 残留的 "简历.pdf"。

操作：
  - intake_candidates.pdf_path 置 NULL
  - intake_slots(slot_key='pdf').value 清空 + ask_count 重置为 0 + answered_at NULL
  - resumes.pdf_path 置空字符串
  - intake_status='complete' 但 pdf_path 失效的 candidate → 拉回 'collecting'，
    清 intake_completed_at + promoted_resume_id（解关联的 resume 也清 pdf_path）

默认 dry-run；--apply 才落库。落库前自动备份 DB。

用法：
  python scripts/cleanup_invalid_pdf_paths.py            # 报告影响范围
  python scripts/cleanup_invalid_pdf_paths.py --apply    # 真正修改
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

import app.modules.resume.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.screening.models  # noqa: F401
import app.modules.scheduling.models  # noqa: F401
import app.modules.notification.models  # noqa: F401
import app.modules.matching.models  # noqa: F401
import app.modules.im_intake.models  # noqa: F401
import app.modules.im_intake.candidate_model  # noqa: F401
import app.modules.im_intake.outbox_model  # noqa: F401
import app.modules.im_intake.settings_model  # noqa: F401
import app.core.audit.models  # noqa: F401

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.resume.models import Resume


def is_valid_pdf_url(url: str | None) -> bool:
    if not url:
        return True  # nothing to clean
    if url.startswith(("http://", "https://")):
        return True
    try:
        p = Path(url).resolve()
        storage_root = Path(settings.resume_storage_path).resolve()
        return str(p).startswith(str(storage_root)) and p.exists()
    except (OSError, ValueError):
        return False


def backup_db(db_url: str) -> Path | None:
    if not db_url.startswith("sqlite:///"):
        return None
    db_path = Path(db_url.replace("sqlite:///", "", 1))
    if not db_path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_suffix(f".db.bak.{ts}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def scan(db) -> dict:
    bad_candidates = []
    for c in db.query(IntakeCandidate).filter(IntakeCandidate.pdf_path.isnot(None)).all():
        if not c.pdf_path:
            continue
        if not is_valid_pdf_url(c.pdf_path):
            bad_candidates.append(c)

    bad_resumes = []
    for r in db.query(Resume).filter(Resume.pdf_path != "").all():
        if not is_valid_pdf_url(r.pdf_path):
            bad_resumes.append(r)

    bad_slots = []
    for s in db.query(IntakeSlot).filter_by(slot_key="pdf").all():
        if s.value and not is_valid_pdf_url(s.value):
            bad_slots.append(s)

    return {
        "candidates": bad_candidates,
        "resumes": bad_resumes,
        "slots": bad_slots,
    }


def apply_cleanup(db, scan_result: dict) -> dict:
    affected = {"candidates": 0, "resumes": 0, "slots": 0, "status_rolled_back": 0}

    for s in scan_result["slots"]:
        s.value = ""
        s.source = None
        s.answered_at = None
        s.ask_count = 0
        affected["slots"] += 1

    for c in scan_result["candidates"]:
        c.pdf_path = None
        if c.intake_status == "complete":
            c.intake_status = "collecting"
            c.intake_completed_at = None
            # Note: keep promoted_resume_id; the linked Resume row's pdf_path is
            # cleaned separately. Detaching here would cascade-orphan.
            affected["status_rolled_back"] += 1
        affected["candidates"] += 1

    for r in scan_result["resumes"]:
        r.pdf_path = ""
        affected["resumes"] += 1

    db.commit()
    return affected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="actually mutate the DB (default: dry-run)")
    args = parser.parse_args()

    db_url = settings.database_url
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        result = scan(db)

        n_c = len(result["candidates"])
        n_r = len(result["resumes"])
        n_s = len(result["slots"])

        print(f"=== Invalid pdf_path scan ===")
        print(f"intake_candidates with bad pdf_path: {n_c}")
        for c in result["candidates"][:20]:
            print(f"  id={c.id} name={c.name!r} status={c.intake_status} pdf_path={c.pdf_path!r}")
        if n_c > 20:
            print(f"  ... +{n_c - 20} more")

        print(f"resumes with bad pdf_path: {n_r}")
        for r in result["resumes"][:20]:
            print(f"  id={r.id} name={r.name!r} pdf_path={r.pdf_path!r}")
        if n_r > 20:
            print(f"  ... +{n_r - 20} more")

        print(f"intake_slots(pdf) with bad value: {n_s}")
        for s in result["slots"][:20]:
            print(f"  candidate_id={s.candidate_id} value={s.value!r}")
        if n_s > 20:
            print(f"  ... +{n_s - 20} more")

        if not args.apply:
            print("\n[dry-run] Pass --apply to execute. No changes made.")
            return 0

        if not (n_c or n_r or n_s):
            print("\nNothing to clean.")
            return 0

        bak = backup_db(db_url)
        if bak:
            print(f"\nBackup: {bak}")

        affected = apply_cleanup(db, result)
        print(f"\nApplied:")
        print(f"  candidates updated:     {affected['candidates']}")
        print(f"  status rolled back:     {affected['status_rolled_back']}")
        print(f"  resumes updated:        {affected['resumes']}")
        print(f"  slots cleared:          {affected['slots']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
