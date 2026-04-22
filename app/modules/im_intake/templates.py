HARD_QUESTIONS: dict[str, list[str]] = {
    "arrival_date": [
        "您好~请问您最快什么时候可以到岗呢？",
        "想再确认一下您的入职时间方便告知吗？",
        "麻烦最后确认下到岗时间哦~",
    ],
    "free_slots": [
        "方便告知您接下来五天哪些时段可以面试吗？",
        "想约下面试时间，您这周哪些时段方便？",
        "最后确认下，您这五天内可面试的具体时段~",
    ],
    "intern_duration": [
        "请问您实习能持续多久呢？",
        "想再确认下您可以实习的总时长~",
        "麻烦最后确认下实习时长哦~",
    ],
}

HARD_SLOT_KEYS = ("arrival_date", "free_slots", "intern_duration")


def get_hard_question(slot_key: str, ask_count: int) -> str:
    variants = HARD_QUESTIONS[slot_key]
    return variants[min(ask_count, len(variants) - 1)]
