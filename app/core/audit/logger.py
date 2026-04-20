"""WORM 审计日志写入. 大 payload 外置到 data/audit/{event_id}.json."""
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.core.audit.models import AuditEvent

logger = logging.getLogger(__name__)

AUDIT_DIR = os.environ.get("AGENTICHR_AUDIT_DIR", "data/audit")
RETENTION_YEARS = 3

_session_factory = sessionmaker(bind=engine)


def compute_hash(payload: Any) -> str:
    """SHA256 hex. dict 按 sorted keys 规整化, 保证幂等."""
    if payload is None:
        return ""
    if isinstance(payload, (dict, list)):
        s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    else:
        s = str(payload)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _write_payload_file(event_id: str, input_payload: Any, output_payload: Any) -> None:
    """大 payload 外置存储, 文件名 = event_id."""
    Path(AUDIT_DIR).mkdir(parents=True, exist_ok=True)
    path = Path(AUDIT_DIR) / f"{event_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            {"input": input_payload, "output": output_payload},
            f, ensure_ascii=False, indent=2, default=str,
        )


def log_event(
    f_stage: str,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    input_payload: Any = None,
    output_payload: Any = None,
    prompt_version: str = "",
    model_name: str = "",
    model_version: str = "",
    reviewer_id: int | None = None,
) -> str:
    """写一条 audit event, 返回 event_id (UUID4)."""
    event_id = str(uuid.uuid4())
    event = AuditEvent(
        event_id=event_id,
        f_stage=f_stage,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        input_hash=compute_hash(input_payload) if input_payload is not None else None,
        output_hash=compute_hash(output_payload) if output_payload is not None else None,
        prompt_version=prompt_version or None,
        model_name=model_name or None,
        model_version=model_version or None,
        reviewer_id=reviewer_id,
        retention_until=datetime.now(timezone.utc) + timedelta(days=365 * RETENTION_YEARS),
    )

    session = _session_factory()
    try:
        session.add(event)
        session.commit()
        if input_payload is not None or output_payload is not None:
            _write_payload_file(event_id, input_payload, output_payload)
    except Exception as e:
        session.rollback()
        logger.error(f"audit log_event failed: {e}")
        raise
    finally:
        session.close()

    return event_id
