def _bigrams(s: str) -> set[str]:
    s = s.lower().replace(" ", "")
    return {s[i:i+2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def string_similarity(a: str, b: str) -> float:
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba and not bb:
        return 1.0
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def match_job_title(boss_job: str, jobs: list[dict], threshold: float = 0.7) -> int | None:
    best_id, best_score = None, 0.0
    for j in jobs:
        s = string_similarity(boss_job, j["title"])
        if s > best_score:
            best_score = s
            best_id = j["id"]
    return best_id if best_score >= threshold else None
