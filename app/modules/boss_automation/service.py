"""Boss 自动化业务逻辑"""
import random
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.adapters.boss.base import BossAdapter
from app.modules.boss_automation.schemas import (
    AutoGreetResponse,
    GreetedCandidate,
    CollectResumesResponse,
    CollectedResume,
    BossStatusResponse,
)

# 默认招呼语
DEFAULT_GREETING = "您好，我们正在招聘相关岗位，看到您的简历很匹配，方便聊一下吗？"

# 模拟的职位招呼模板 (实际项目中从数据库获取)
JOB_GREETING_TEMPLATES: dict[str, list[str]] = {}


class BossAutomationService:
    """Boss 直聘自动化业务服务"""

    def __init__(self, db: Session, adapter: BossAdapter | None = None):
        self.db = db
        self.adapter = adapter

    def _get_greeting_message(
        self,
        job_id: str = "",
        custom_message: str = "",
    ) -> str:
        """获取招呼消息

        优先级：自定义消息 > 职位模板随机选择 > 默认招呼语
        """
        if custom_message:
            return custom_message

        if job_id and job_id in JOB_GREETING_TEMPLATES:
            templates = JOB_GREETING_TEMPLATES[job_id]
            if templates:
                return random.choice(templates)

        return DEFAULT_GREETING

    async def auto_greet(
        self,
        job_id: str = "",
        message: str = "",
        max_count: int = 10,
        user_id: int | None = None,  # BUG-042: 支持用户隔离
    ) -> AutoGreetResponse:
        """自动打招呼"""
        if self.adapter is None:
            return AutoGreetResponse(
                message="Boss 适配器未配置，无法执行自动打招呼",
            )

        try:
            candidates = await self.adapter.get_new_greetings()
        except Exception as e:
            return AutoGreetResponse(message=f"获取新消息失败: {e}")

        greeting = self._get_greeting_message(job_id, message)
        greeted: list[GreetedCandidate] = []
        count = 0

        for candidate in candidates:
            if count >= max_count:
                break

            try:
                success = await self.adapter.send_greeting_reply(
                    candidate.boss_id, greeting
                )
            except RuntimeError:
                # 每日上限
                break
            except Exception:
                success = False

            greeted.append(GreetedCandidate(
                name=candidate.name,
                boss_id=candidate.boss_id,
                success=success,
            ))
            if success:
                count += 1

        return AutoGreetResponse(
            total_found=len(candidates),
            greeted_count=count,
            candidates=greeted,
            message=f"成功打招呼 {count} 人",
        )

    async def collect_resumes(self, user_id: int | None = None) -> CollectResumesResponse:  # BUG-042
        """收集简历"""
        if self.adapter is None:
            return CollectResumesResponse(message="Boss 适配器未配置")

        try:
            candidates = await self.adapter.get_new_greetings()
        except Exception as e:
            return CollectResumesResponse(message=f"获取候选人失败: {e}")

        collected: list[CollectedResume] = []
        for candidate in candidates:
            try:
                messages = await self.adapter.get_chat_messages(candidate.boss_id)
                pdf_msgs = [m for m in messages if m.is_pdf and m.pdf_url]

                has_pdf = len(pdf_msgs) > 0
                resume_id = None

                if has_pdf:
                    save_dir = Path(settings.resume_storage_path)
                    save_dir.mkdir(parents=True, exist_ok=True)
                    save_path = str(save_dir / f"{candidate.boss_id}.pdf")
                    await self.adapter.download_pdf(pdf_msgs[0].pdf_url, save_path)

                collected.append(CollectedResume(
                    name=candidate.name,
                    boss_id=candidate.boss_id,
                    has_pdf=has_pdf,
                    resume_id=resume_id,
                ))
            except Exception:
                continue

        return CollectResumesResponse(
            collected_count=len(collected),
            resumes=collected,
            message=f"收集到 {len(collected)} 份简历信息",
        )

    async def get_status(self, user_id: int | None = None) -> BossStatusResponse:  # BUG-042
        """获取 Boss 适配器状态"""
        if self.adapter is None:
            return BossStatusResponse(
                available=False,
                adapter_type="none",
                message="Boss 适配器未配置",
                max_operations_per_day=settings.boss_max_operations_per_day,
            )

        try:
            available = await self.adapter.is_available()
        except Exception:
            available = False

        adapter_type = type(self.adapter).__name__

        operations_today = 0
        if hasattr(self.adapter, "_operations_today"):
            operations_today = self.adapter._operations_today

        return BossStatusResponse(
            available=available,
            adapter_type=adapter_type,
            operations_today=operations_today,
            max_operations_per_day=settings.boss_max_operations_per_day,
            message="适配器状态正常" if available else "适配器不可用",
        )
