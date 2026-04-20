"""/api/skills 路由."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.competency.skill_library import SkillLibrary, SkillCache, _session_factory
from app.core.competency.models import Skill

router = APIRouter(prefix="/api/skills", tags=["skills"])


class _SkillCreateBody(BaseModel):
    canonical_name: str
    category: str = "uncategorized"
    aliases: list[str] = []


class _SkillUpdateBody(BaseModel):
    canonical_name: str | None = None
    category: str | None = None
    aliases: list[str] | None = None


class _MergeBody(BaseModel):
    merge_into_id: int


@router.get("")
def list_skills(
    search: str | None = None,
    category: str | None = None,
    pending: bool = False,
    limit: int = 20,
    offset: int = 0,
):
    lib = SkillLibrary()
    if search:
        items = lib.search(search, limit=limit)
        return {"items": items, "total": len(items)}
    elif pending:
        items = lib.list_pending()
        return {"items": items, "total": len(items)}
    else:
        all_items = lib.list_all()
        if category:
            all_items = [s for s in all_items if s["category"] == category]
        total = len(all_items)
        items = all_items[offset: offset + limit]
        return {"items": items, "total": total}


@router.get("/categories")
def list_categories():
    lib = SkillLibrary()
    cats = sorted({s["category"] for s in lib.list_all()})
    return {"categories": cats}


@router.get("/{skill_id}")
def get_skill(skill_id: int):
    lib = SkillLibrary()
    s = lib.find_by_id(skill_id)
    if not s:
        raise HTTPException(status_code=404, detail="skill not found")
    return s


@router.post("")
def create_skill(body: _SkillCreateBody):
    lib = SkillLibrary()
    if lib.find_by_name(body.canonical_name):
        raise HTTPException(status_code=409, detail="skill already exists")
    new_id = lib.insert(
        canonical_name=body.canonical_name,
        source="seed_manual",
        category=body.category,
        aliases=body.aliases,
    )
    return lib.find_by_id(new_id)


@router.put("/{skill_id}")
def update_skill(skill_id: int, body: _SkillUpdateBody):
    session = _session_factory()
    try:
        s = session.query(Skill).filter(Skill.id == skill_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="not found")
        if body.canonical_name is not None:
            s.canonical_name = body.canonical_name
        if body.category is not None:
            s.category = body.category
        if body.aliases is not None:
            s.aliases = body.aliases
        session.commit()
        SkillCache.invalidate()
        return SkillLibrary().find_by_id(skill_id)
    finally:
        session.close()


@router.post("/{skill_id}/merge")
def merge_skill(skill_id: int, body: _MergeBody):
    lib = SkillLibrary()
    try:
        lib.merge(skill_id, body.merge_into_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "merged"}


@router.delete("/{skill_id}")
def delete_skill(skill_id: int):
    session = _session_factory()
    try:
        s = session.query(Skill).filter(Skill.id == skill_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="not found")
        if s.source == "seed" or (s.usage_count or 0) > 0:
            raise HTTPException(status_code=400, detail="只能删除未被使用的技能（seed 来源不可删除）")
        session.delete(s)
        session.commit()
        SkillCache.invalidate()
        return {"status": "deleted"}
    finally:
        session.close()
