"""Per-job effective scoring weights helper.

Priority chain:
  1. job.scoring_weights  — custom weights stored on the job row
  2. global settings      — data/scoring_weights.json via settings router
  3. hard-coded defaults  — 35/30/15/10/10
"""
from app.core.settings.router import _load as _load_global

_DEFAULT: dict = {
    "skill_match": 35,
    "experience": 30,
    "seniority": 15,
    "education": 10,
    "industry": 10,
}


def get_effective_weights(job=None) -> dict:
    """Return the 5-weight dict actually used for scoring *job*.

    job may be a Job ORM instance or None (falls back to global/default).
    """
    if job is not None and getattr(job, "scoring_weights", None):
        w = job.scoring_weights
        if isinstance(w, dict) and w.get("skill_match") is not None:
            return _normalize(w)
    try:
        return _normalize(_load_global())
    except Exception:
        return _DEFAULT.copy()


def _normalize(w: dict) -> dict:
    """Ensure all 5 keys present as ints; missing keys become 0."""
    return {k: int(w.get(k) or 0) for k in _DEFAULT}
