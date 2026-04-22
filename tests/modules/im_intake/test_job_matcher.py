from app.modules.im_intake.job_matcher import match_job_title

JOBS = [
    {"id": 1, "title": "前端开发工程师"},
    {"id": 2, "title": "Java 后端开发"},
    {"id": 3, "title": "数据分析师"},
]


def test_exact_match():
    assert match_job_title("前端开发工程师", JOBS, threshold=0.7) == 1


def test_fuzzy_match():
    # bigram Jaccard("前端工程师", "前端开发工程师") = 3/7 ≈ 0.43
    assert match_job_title("前端工程师", JOBS, threshold=0.4) == 1


def test_below_threshold_returns_none():
    assert match_job_title("产品经理", JOBS, threshold=0.7) is None


def test_empty_jobs_returns_none():
    assert match_job_title("前端", [], threshold=0.7) is None
