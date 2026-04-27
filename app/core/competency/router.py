"""/api/skills 路由."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.competency.skill_library import SkillLibrary, SkillCache, _session_factory
from app.core.competency.models import Skill

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _strip_embedding(d: dict | None) -> dict | None:
    if d is None:
        return None
    return {k: v for k, v in d.items() if k != "embedding"}


def _strip_many(items: list[dict]) -> list[dict]:
    return [_strip_embedding(i) for i in items]


class _SkillCreateBody(BaseModel):
    canonical_name: str
    category: str = "uncategorized"
    aliases: list[str] = []


class _SkillUpdateBody(BaseModel):
    canonical_name: str | None = None
    category: str | None = None
    aliases: list[str] | None = None
    pending_classification: bool | None = None


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
        return {"items": _strip_many(items), "total": len(items)}
    elif pending:
        items = lib.list_pending()
        return {"items": _strip_many(items), "total": len(items)}
    else:
        all_items = lib.list_all()
        if category:
            all_items = [s for s in all_items if s["category"] == category]
        total = len(all_items)
        items = all_items[offset: offset + limit]
        return {"items": _strip_many(items), "total": total}


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
    return _strip_embedding(s)


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
    return _strip_embedding(lib.find_by_id(new_id))


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
        if body.pending_classification is not None:
            s.pending_classification = body.pending_classification
        session.commit()
        SkillCache.invalidate()
        return _strip_embedding(SkillLibrary().find_by_id(skill_id))
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


_CATEGORY_KEYWORDS = {
    "language":  ["python","java","go","rust","c++","c#","typescript","javascript","kotlin","swift","ruby","php","scala","r语言","r "],
    "framework": ["django","fastapi","flask","spring","react","vue","angular","nextjs","express","laravel","rails","gin","fiber"],
    "cloud":     ["aws","azure","gcp","docker","kubernetes","k8s","terraform","ansible","ci/cd","devops","linux","nginx","redis","kafka","rabbitmq","elasticsearch"],
    "database":  ["mysql","postgresql","postgres","sqlite","mongodb","oracle","sqlserver","clickhouse","hive","hadoop","spark","flink"],
    "tool":      ["git","jira","confluence","jenkins","grafana","prometheus","postman","vscode","intellij","figma","excel","ppt"],
    "soft":      ["沟通","表达","领导","协作","团队","学习","抗压","责任","执行","创新","分析","解决问题","时间管理"],
}

def _keyword_classify(name: str) -> str:
    n = name.lower()
    for cat, kws in _CATEGORY_KEYWORDS.items():
        if any(kw in n for kw in kws):
            return cat
    return "uncategorized"


@router.post("/auto-classify")
async def auto_classify_pending():
    """用 LLM 批量归类所有 pending_classification=True 的技能，LLM 失败则关键词兜底。"""
    import json as _json
    from app.core.llm.provider import LLMProvider, LLMError
    from app.core.hitl.service import HitlService
    from app.core.hitl.models import HitlTask

    lib = SkillLibrary()
    pending = [s for s in lib.list_all() if s.get("pending_classification")]
    if not pending:
        return {"classified": 0, "message": "没有待归类的技能"}

    names = [s["canonical_name"] for s in pending]
    valid_cats = list(_CATEGORY_KEYWORDS.keys()) + ["domain", "uncategorized"]

    # 尝试 LLM 批量分类
    llm_map: dict[str, str] = {}
    try:
        llm = LLMProvider()
        prompt = (
            f"请将以下技能名称各归入一个分类，分类只能从列表中选：{valid_cats}。\n"
            f"以 JSON 对象返回，格式：{{\"技能名\": \"分类\", ...}}，不要其他内容。\n"
            f"技能列表：{names}"
        )
        raw = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            prompt_version="skill_auto_classify_v1",
            f_stage="F1_skill_classification",
            entity_type="skill",
            entity_id=0,
            temperature=0.0,
        )
        from app.core.llm.parsing import extract_json
        parsed = extract_json(raw)
        if isinstance(parsed, dict):
            for name, cat in parsed.items():
                if cat in valid_cats:
                    llm_map[name] = cat
    except (LLMError, ValueError):
        pass  # 全量降级到关键词

    # 更新每条技能
    session = _session_factory()
    classified = 0
    try:
        task_ids_to_approve = []
        for s in pending:
            cat = llm_map.get(s["canonical_name"]) or _keyword_classify(s["canonical_name"])
            skill_row = session.query(Skill).filter(Skill.id == s["id"]).first()
            if skill_row:
                skill_row.category = cat
                skill_row.pending_classification = False
            task = (
                session.query(HitlTask)
                .filter(
                    HitlTask.entity_type == "skill",
                    HitlTask.entity_id == s["id"],
                    HitlTask.f_stage == "F1_skill_classification",
                    HitlTask.status == "pending",
                )
                .first()
            )
            if task:
                task_ids_to_approve.append((task.id, cat))
            classified += 1
        session.commit()
        SkillCache.invalidate()
        # Now approve via HitlService so callbacks run
        for task_id, cat in task_ids_to_approve:
            try:
                HitlService().approve(task_id, reviewer_id=None, note=f"自动归类: {cat}")
            except Exception:
                pass  # Non-fatal: skill already classified
    finally:
        session.close()

    method = "LLM" if llm_map else "关键词"
    return {"classified": classified, "method": method}


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
