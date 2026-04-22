import re
from typing import Any

ARRIVAL_PATTERNS = [
    re.compile(r"(下周[一二三四五六日天])"),
    re.compile(r"(明天|后天|立刻|马上|随时)"),
    re.compile(r"(\d+月\d+[号日])"),
    re.compile(r"^(周[一二三四五六日天])$"),
]

INTERN_PATTERN = re.compile(r"(\d+\s*个?\s*月|半年|一年|长期)")
INTERN_NORMALIZE = re.compile(r"(\d+)\s*个?\s*月")

FREE_PATTERN = re.compile(r"(周[一二三四五六日天])\s*(上午|下午|晚上)?")


def _arrival(text: str) -> str | None:
    for pat in ARRIVAL_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def _intern(text: str) -> str | None:
    m = INTERN_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(1)
    nm = INTERN_NORMALIZE.match(raw)
    if nm:
        return f"{nm.group(1)}个月"
    return raw


def _free(text: str) -> list[str]:
    out: list[str] = []
    for m in FREE_PATTERN.finditer(text):
        day, period = m.group(1), m.group(2) or ""
        out.append(f"{day}{period}")
    return out


def regex_extract(slot_key: str, text: str) -> Any:
    if slot_key == "arrival_date":
        return _arrival(text)
    if slot_key == "intern_duration":
        return _intern(text)
    if slot_key == "free_slots":
        return _free(text)
    return None
