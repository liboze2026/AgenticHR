from app.modules.matching.schemas import (
    EvidenceItem, MatchingResultResponse,
    ScoreRequest, RecomputeRequest, RecomputeStatus,
)


def test_evidence_item_with_offset():
    item = EvidenceItem(text="匹配到 Python", source="skills", offset=[0, 6])
    assert item.offset == [0, 6]


def test_evidence_item_null_offset():
    item = EvidenceItem(text="工作年限 5 年", source="work_years", offset=None)
    assert item.offset is None


def test_score_request_valid():
    req = ScoreRequest(resume_id=1, job_id=2)
    assert req.resume_id == 1


def test_recompute_request_job_id():
    req = RecomputeRequest(job_id=2)
    assert req.job_id == 2
    assert req.resume_id is None


def test_recompute_request_resume_id():
    req = RecomputeRequest(resume_id=5)
    assert req.resume_id == 5
    assert req.job_id is None


def test_recompute_status_shape():
    s = RecomputeStatus(task_id="x", total=10, completed=3, failed=0, running=True, current="Job#2 × Resume#5")
    assert s.running is True
