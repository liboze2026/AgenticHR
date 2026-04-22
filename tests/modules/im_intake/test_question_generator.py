import json
from unittest.mock import AsyncMock
import pytest
from app.modules.im_intake.question_generator import QuestionGenerator


def test_pack_hard_first_round():
    qg = QuestionGenerator(llm=None)
    text = qg.pack_hard(
        candidate_name="张三", job_title="前端开发",
        missing=[("arrival_date", 0), ("free_slots", 0), ("intern_duration", 0)],
    )
    assert "张三" in text and "前端开发" in text
    assert "到岗" in text or "入职" in text
    assert "面试" in text
    assert "实习" in text
    assert text.endswith("[AI 助手]")


def test_pack_hard_repeat_uses_variant():
    qg = QuestionGenerator(llm=None)
    t0 = qg.pack_hard("张三", "前端", [("arrival_date", 0)])
    t1 = qg.pack_hard("张三", "前端", [("arrival_date", 1)])
    assert t0 != t1


@pytest.mark.asyncio
async def test_soft_questions_via_llm():
    llm = AsyncMock()
    llm.complete.return_value = json.dumps([
        {"dimension_id": "d1", "dimension_name": "系统设计", "question": "讲讲你的秒杀系统？"},
    ])
    qg = QuestionGenerator(llm=llm)
    out = await qg.generate_soft(
        dimensions=[{"id": "d1", "name": "系统设计", "description": "..."}],
        resume_summary="做过电商秒杀",
        max_n=3,
    )
    assert len(out) == 1
    assert out[0]["question"] == "讲讲你的秒杀系统？"
    assert out[0]["dimension_id"] == "d1"


def test_pack_soft_appends_label():
    qg = QuestionGenerator(llm=None)
    text = qg.pack_soft([
        {"dimension_id": "d1", "dimension_name": "系统设计", "question": "讲讲秒杀？"},
    ])
    assert "讲讲秒杀？" in text
    assert text.endswith("[AI 助手]")
