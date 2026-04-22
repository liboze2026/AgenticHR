import pytest
from app.modules.im_intake.slot_filler import regex_extract

ARRIVAL_CASES = [
    ("我下周一可以入职", "下周一"),
    ("立刻就能到岗", "立刻"),
    ("4月28号开始", "4月28号"),
    ("随时", "随时"),
    ("明天就行", "明天"),
    ("周一", "周一"),
    ("下周三入职", "下周三"),
    ("5月1日", "5月1日"),
    ("后天到岗", "后天"),
    ("马上就可以", "马上"),
    ("4月30日开始上班", "4月30日"),
    ("下下周也可以", None),
    ("还要一段时间", None),
    ("看公司安排", None),
    ("现在就行", None),
]

INTERN_CASES = [
    ("可以实习6个月", "6个月"),
    ("3个月没问题", "3个月"),
    ("半年", "半年"),
    ("一年", "一年"),
    ("长期", "长期"),
    ("实习12个月", "12个月"),
    ("4 个月", "4个月"),
    ("两个月", None),
    ("看情况", None),
    ("不确定", None),
]

FREE_CASES = [
    ("周二下午、周四上午", ["周二下午", "周四上午"]),
    ("周一上午", ["周一上午"]),
    ("周三晚上有空", ["周三晚上"]),
    ("周一周二都行", ["周一", "周二"]),
    ("下午都可以", []),
    ("没空", []),
]

@pytest.mark.parametrize("text,expected", ARRIVAL_CASES)
def test_arrival_date(text, expected):
    assert regex_extract("arrival_date", text) == expected

@pytest.mark.parametrize("text,expected", INTERN_CASES)
def test_intern_duration(text, expected):
    assert regex_extract("intern_duration", text) == expected

@pytest.mark.parametrize("text,expected", FREE_CASES)
def test_free_slots(text, expected):
    assert regex_extract("free_slots", text) == expected
