"""skills 表 CRUD + 内存缓存 (SkillCache)."""
import json
import logging

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.core.competency.models import Skill

logger = logging.getLogger(__name__)

_session_factory = sessionmaker(bind=engine)


def _row_to_dict(s: Skill) -> dict:
    return {
        "id": s.id,
        "canonical_name": s.canonical_name,
        "aliases": s.aliases if isinstance(s.aliases, list) else (json.loads(s.aliases) if s.aliases else []),
        "category": s.category,
        "embedding": s.embedding,
        "source": s.source,
        "pending_classification": bool(s.pending_classification),
        "usage_count": s.usage_count,
    }


class SkillCache:
    """进程内 skills 全量缓存.

    **语义: 手动失效 (manual invalidate only).**

    写操作 (SkillLibrary.insert / add_alias_if_absent / increment_usage /
    update_embedding / merge) **不会**自动调用 invalidate(). 调用方必须
    在"需要最新状态"时显式调用 `SkillCache.invalidate()`.

    **为什么这么设计**: normalize_skills() 的一次调用里可能连续插入多个新
    技能, 若每次 insert 都 invalidate, 则后插入的技能会成为先插入技能的
    最近邻候选, 破坏归一化的稳定性. 所以 normalize_skills 在入口处拍一次
    snapshot (SkillCache.all()), 期间的所有 insert 都不影响本次 snapshot.

    **合约**: HTTP 请求边界或批处理边界上, 调用方应 invalidate 一次以读取
    最新状态. 参考 tests/core/test_skill_library.py::test_cache_reload_after_insert.
    """
    _cache: list[dict] | None = None

    @classmethod
    def all(cls) -> list[dict]:
        if cls._cache is None:
            cls._cache = SkillLibrary().list_all()
        return cls._cache

    @classmethod
    def invalidate(cls) -> None:
        cls._cache = None


class SkillLibrary:
    def list_all(self) -> list[dict]:
        session = _session_factory()
        try:
            rows = session.query(Skill).all()
            return [_row_to_dict(r) for r in rows]
        finally:
            session.close()

    def find_by_name(self, name: str) -> dict | None:
        session = _session_factory()
        try:
            row = session.query(Skill).filter(Skill.canonical_name == name).first()
            return _row_to_dict(row) if row else None
        finally:
            session.close()

    def find_by_id(self, skill_id: int) -> dict | None:
        session = _session_factory()
        try:
            row = session.query(Skill).filter(Skill.id == skill_id).first()
            return _row_to_dict(row) if row else None
        finally:
            session.close()

    def insert(
        self,
        canonical_name: str,
        source: str,
        *,
        aliases: list[str] | None = None,
        category: str = "uncategorized",
        embedding: bytes | None = None,
        pending_classification: bool = False,
    ) -> int:
        # Note: does NOT auto-invalidate SkillCache (see SkillCache docstring).
        # Caller must call SkillCache.invalidate() if fresh read needed.
        session = _session_factory()
        try:
            row = Skill(
                canonical_name=canonical_name,
                aliases=aliases or [],
                category=category,
                embedding=embedding,
                source=source,
                pending_classification=pending_classification,
            )
            session.add(row)
            session.commit()
            return row.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def add_alias_if_absent(self, canonical_name: str, alias: str) -> None:
        # Note: does NOT auto-invalidate SkillCache (see SkillCache docstring).
        # Caller must call SkillCache.invalidate() if fresh read needed.
        session = _session_factory()
        try:
            row = session.query(Skill).filter(Skill.canonical_name == canonical_name).first()
            if row is None:
                return
            current = row.aliases if isinstance(row.aliases, list) else (json.loads(row.aliases) if row.aliases else [])
            if alias not in current:
                new_aliases = list(current) + [alias]
                row.aliases = new_aliases
                session.add(row)
                session.commit()
        finally:
            session.close()

    def increment_usage(self, skill_id: int) -> None:
        # Note: does NOT auto-invalidate SkillCache (see SkillCache docstring).
        # Caller must call SkillCache.invalidate() if fresh read needed.
        session = _session_factory()
        try:
            session.query(Skill).filter(Skill.id == skill_id).update(
                {Skill.usage_count: Skill.usage_count + 1}
            )
            session.commit()
        finally:
            session.close()

    def search(self, q: str, limit: int = 20) -> list[dict]:
        session = _session_factory()
        try:
            like = f"%{q}%"
            rows = (
                session.query(Skill)
                .filter(sa.or_(
                    Skill.canonical_name.like(like),
                    sa.func.json_extract(Skill.aliases, "$").like(like),
                ))
                .limit(limit).all()
            )
            return [_row_to_dict(r) for r in rows]
        finally:
            session.close()

    def list_pending(self) -> list[dict]:
        session = _session_factory()
        try:
            rows = session.query(Skill).filter(Skill.pending_classification.is_(True)).all()
            return [_row_to_dict(r) for r in rows]
        finally:
            session.close()

    def update_embedding(self, skill_id: int, embedding: bytes) -> None:
        # Note: does NOT auto-invalidate SkillCache (see SkillCache docstring).
        # Caller must call SkillCache.invalidate() if fresh read needed.
        session = _session_factory()
        try:
            session.query(Skill).filter(Skill.id == skill_id).update({Skill.embedding: embedding})
            session.commit()
        finally:
            session.close()

    def merge(self, from_id: int, into_id: int) -> None:
        # Note: does NOT auto-invalidate SkillCache (see SkillCache docstring).
        # Caller must call SkillCache.invalidate() if fresh read needed.
        session = _session_factory()
        try:
            src = session.query(Skill).filter(Skill.id == from_id).first()
            dst = session.query(Skill).filter(Skill.id == into_id).first()
            if not src or not dst:
                raise ValueError("skill id not found")
            if src.source == "seed":
                raise ValueError("cannot merge seed skill")

            src_aliases = src.aliases if isinstance(src.aliases, list) else []
            dst_aliases = list(dst.aliases if isinstance(dst.aliases, list) else [])
            if src.canonical_name not in dst_aliases:
                dst_aliases.append(src.canonical_name)
            for a in src_aliases:
                if a not in dst_aliases:
                    dst_aliases.append(a)

            dst.aliases = dst_aliases
            dst.usage_count = (dst.usage_count or 0) + (src.usage_count or 0)
            session.delete(src)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
