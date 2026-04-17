"""腾讯会议账号池选择器

问题背景：腾讯会议同一账号在同一时刻只能主持一场会议。当同一时段有多个
面试并行时，必须用不同账号分别主持。

方案：
- 账号列表存在 settings.tencent_meeting_accounts（逗号分隔的标签），每个标签对应
  data/meeting_browser_{label}/ 目录下的一套 Playwright 持久化 Chrome 登录态
- 创建会议前，查询当前数据库里"在 [start, end] 时段内、已创建会议、且未取消"
  的面试，收集这些面试占用的账号标签作为"忙集"
- 从配置的账号顺序里挑第一个不在忙集的，就是本次分配的账号
- 全忙则抛 409 让前端给出清晰提示
"""
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.scheduling.models import Interview


def configured_accounts() -> list[str]:
    raw = settings.tencent_meeting_accounts or ""
    return [a.strip() for a in raw.split(",") if a.strip()]


def pick_available_account(
    db: Session,
    start_time: datetime,
    end_time: datetime,
    exclude_interview_id: int | None = None,
) -> str:
    """挑一个在给定时段没有会议占用的账号标签。

    冲突检测规则：
    - Interview.status != 'cancelled'
    - Interview.meeting_link 非空（真的创建过会议）
    - Interview.meeting_account 非空（知道用的哪个账号）
    - 时段相交：existing.start < end AND existing.end > start
    - 可选排除某个 interview_id（用于"重建会议"场景，不要把自己算进去）
    """
    accounts = configured_accounts()
    if not accounts:
        raise HTTPException(
            status_code=500,
            detail="未配置腾讯会议账号。请在 .env 设置 TENCENT_MEETING_ACCOUNTS=xxx",
        )

    query = db.query(Interview.meeting_account).filter(
        Interview.status != "cancelled",
        Interview.meeting_link != "",
        Interview.meeting_account != "",
        Interview.start_time < end_time,
        Interview.end_time > start_time,
    )
    if exclude_interview_id is not None:
        query = query.filter(Interview.id != exclude_interview_id)

    busy = {row[0] for row in query.all()}

    for acc in accounts:
        if acc not in busy:
            return acc

    raise HTTPException(
        status_code=409,
        detail=(
            f"所有 {len(accounts)} 个腾讯会议账号在该时段都有占用"
            f"（已占用: {', '.join(sorted(busy))}）。"
            "请新增账号到 .env 的 TENCENT_MEETING_ACCOUNTS，或调整面试时间。"
        ),
    )
