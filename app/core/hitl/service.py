"""HITL 任务服务."""
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.core.hitl.models import HitlTask
from app.core.audit.logger import log_event

logger = logging.getLogger(__name__)

_session_factory = sessionmaker(bind=engine)
_approve_callbacks: dict[str, list[Callable]] = {}


class InvalidHitlStateError(RuntimeError):
    """试图对已终态 (approved/rejected/edited) 的任务再次操作."""


class HitlCallbackError(RuntimeError):
    """approve/edit callback 执行失败. 任务已回退到 pending, 需 HR 重试或手工修复."""


def register_approve_callback(f_stage: str, callback: Callable) -> None:
    """注册 stage-specific 的 approve 后 callback. 参数是 task dict."""
    _approve_callbacks.setdefault(f_stage, []).append(callback)


def _row_to_dict(t: HitlTask) -> dict:
    return {
        "id": t.id,
        "f_stage": t.f_stage,
        "entity_type": t.entity_type,
        "entity_id": t.entity_id,
        "payload": t.payload,
        "status": t.status,
        "edited_payload": t.edited_payload,
        "reviewer_id": t.reviewer_id,
        "reviewed_at": t.reviewed_at.isoformat() if t.reviewed_at else None,
        "note": t.note,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


class HitlService:
    def create(
        self,
        f_stage: str,
        entity_type: str,
        entity_id: int,
        payload: Any,
    ) -> int:
        session = _session_factory()
        try:
            task = HitlTask(
                f_stage=f_stage,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
                status="pending",
            )
            session.add(task)
            session.commit()
            tid = task.id
            log_event(
                f_stage=f_stage, action="hitl_create",
                entity_type=entity_type, entity_id=entity_id,
                input_payload=payload,
            )
            return tid
        finally:
            session.close()

    def get(self, task_id: int) -> dict | None:
        session = _session_factory()
        try:
            t = session.query(HitlTask).filter(HitlTask.id == task_id).first()
            return _row_to_dict(t) if t else None
        finally:
            session.close()

    def list(
        self,
        stage: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        session = _session_factory()
        try:
            q = session.query(HitlTask)
            if stage:
                q = q.filter(HitlTask.f_stage == stage)
            if status:
                q = q.filter(HitlTask.status == status)
            q = q.order_by(HitlTask.created_at.desc()).limit(limit).offset(offset)
            return [_row_to_dict(t) for t in q.all()]
        finally:
            session.close()

    def count_pending(self, stage: str | None = None) -> int:
        session = _session_factory()
        try:
            q = session.query(HitlTask).filter(HitlTask.status == "pending")
            if stage:
                q = q.filter(HitlTask.f_stage == stage)
            return q.count()
        finally:
            session.close()

    def approve(self, task_id: int, reviewer_id: int | None = None, note: str = "") -> None:
        self._transition(task_id, "approved", reviewer_id, note, "hitl_approve")

    def reject(self, task_id: int, reviewer_id: int | None = None, note: str = "") -> None:
        if not note:
            raise ValueError("reject requires a non-empty note")
        self._transition(task_id, "rejected", reviewer_id, note, "hitl_reject")

    def edit(
        self,
        task_id: int,
        *,
        reviewer_id: int | None = None,
        edited_payload: Any,
        note: str = "",
    ) -> None:
        session = _session_factory()
        try:
            t = session.query(HitlTask).filter(HitlTask.id == task_id).first()
            if t is None:
                raise ValueError(f"task {task_id} not found")
            if t.status != "pending":
                raise InvalidHitlStateError(
                    f"cannot edit task {task_id} in status={t.status}"
                )
            t.status = "edited"
            t.edited_payload = edited_payload
            t.reviewer_id = reviewer_id
            t.reviewed_at = datetime.now(timezone.utc)
            t.note = note
            session.commit()
            log_event(
                f_stage=t.f_stage, action="hitl_edit",
                entity_type=t.entity_type, entity_id=t.entity_id,
                input_payload=t.payload, output_payload=edited_payload,
                reviewer_id=reviewer_id,
            )
            row_snapshot = _row_to_dict(t)
            f_stage_snapshot = t.f_stage
            entity_type_snapshot = t.entity_type
            entity_id_snapshot = t.entity_id
        finally:
            session.close()

        self._run_callbacks(
            task_id=task_id,
            row_snapshot=row_snapshot,
            f_stage=f_stage_snapshot,
            entity_type=entity_type_snapshot,
            entity_id=entity_id_snapshot,
            reviewer_id=reviewer_id,
            action="hitl_edit_callback_failed",
        )

    def _transition(self, task_id: int, new_status: str,
                     reviewer_id: int | None, note: str, action: str) -> None:
        session = _session_factory()
        try:
            t = session.query(HitlTask).filter(HitlTask.id == task_id).first()
            if t is None:
                raise ValueError(f"task {task_id} not found")
            if t.status != "pending":
                raise InvalidHitlStateError(
                    f"cannot {new_status} task {task_id} in status={t.status}"
                )
            t.status = new_status
            t.reviewer_id = reviewer_id
            t.reviewed_at = datetime.now(timezone.utc)
            t.note = note
            session.commit()
            log_event(
                f_stage=t.f_stage, action=action,
                entity_type=t.entity_type, entity_id=t.entity_id,
                input_payload=t.payload, reviewer_id=reviewer_id,
            )
            row_snapshot = _row_to_dict(t)
            f_stage_snapshot = t.f_stage
            entity_type_snapshot = t.entity_type
            entity_id_snapshot = t.entity_id
        finally:
            session.close()

        if new_status == "approved":
            self._run_callbacks(
                task_id=task_id,
                row_snapshot=row_snapshot,
                f_stage=f_stage_snapshot,
                entity_type=entity_type_snapshot,
                entity_id=entity_id_snapshot,
                reviewer_id=reviewer_id,
                action="hitl_approve_callback_failed",
            )

    def _run_callbacks(
        self,
        *,
        task_id: int,
        row_snapshot: dict,
        f_stage: str,
        entity_type: str,
        entity_id: int,
        reviewer_id: int | None,
        action: str,
    ) -> None:
        """按注册顺序跑 callbacks. 任一失败: 回退 task → pending, 记 audit, 抛 HitlCallbackError.

        Callbacks 必须原子 (自带事务). 若 callback 部分写库后抛异常, 那部分写入不会因本方法
        回退而被撤销 - 所以 callback 实现方有责任用 try/rollback 自愈.
        """
        errors: list[str] = []
        for cb in _approve_callbacks.get(f_stage, []):
            try:
                cb(row_snapshot)
            except Exception as e:
                errors.append(f"{cb.__name__ if hasattr(cb, '__name__') else 'cb'}: {e}")
                logger.error(f"{action}: task={task_id} cb={cb} err={e}")
                break  # 一失败即止, 不继续跑后续 callbacks

        if not errors:
            return

        err_msg = "; ".join(errors)
        # 回退 task 到 pending, 清 reviewer 痕迹, 写 note
        session = _session_factory()
        try:
            t = session.query(HitlTask).filter(HitlTask.id == task_id).first()
            if t is not None:
                t.status = "pending"
                t.reviewer_id = None
                t.reviewed_at = None
                t.note = f"callback failed: {err_msg}"
                session.commit()
        finally:
            session.close()

        log_event(
            f_stage=f_stage, action=action,
            entity_type=entity_type, entity_id=entity_id,
            input_payload={"error": err_msg}, reviewer_id=reviewer_id,
        )

        raise HitlCallbackError(err_msg)
