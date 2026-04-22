"""Boss 直聘适配器基础接口

所有 Boss 直聘操作方案（Chrome 插件、Playwright 等）都实现此接口，
上层业务代码只依赖此接口，不依赖具体实现。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class BossCandidate:
    """Boss 直聘上的候选人信息"""
    name: str
    boss_id: str = ""
    phone: str = ""
    email: str = ""
    education: str = ""
    work_years: int = 0
    expected_salary: str = ""
    job_intention: str = ""
    skills: str = ""
    work_experience: str = ""
    project_experience: str = ""
    self_evaluation: str = ""
    has_pdf: bool = False
    pdf_url: str = ""


@dataclass
class BossMessage:
    """Boss 直聘聊天消息"""
    sender_id: str
    sender_name: str
    content: str
    is_pdf: bool = False
    pdf_url: str = ""
    timestamp: str = ""


class BossAdapter(ABC):
    """Boss 直聘操作适配器接口"""

    @abstractmethod
    async def get_new_greetings(self) -> list[BossCandidate]:
        """获取新的打招呼消息列表"""
        ...

    @abstractmethod
    async def send_greeting_reply(self, boss_id: str, message: str) -> bool:
        """回复候选人打招呼消息"""
        ...

    @abstractmethod
    async def get_candidate_info(self, boss_id: str) -> BossCandidate | None:
        """获取候选人详细信息"""
        ...

    @abstractmethod
    async def get_chat_messages(self, boss_id: str) -> list[BossMessage]:
        """获取与候选人的聊天记录"""
        ...

    @abstractmethod
    async def download_pdf(self, pdf_url: str, save_path: str) -> bool:
        """下载候选人的 PDF 简历"""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """检查适配器是否可用"""
        ...

    @abstractmethod
    async def list_chat_index(self) -> list[BossCandidate]:
        """切到 chat/index '全部' tab，扫所有对话条目"""
        ...

    @abstractmethod
    async def send_message(self, boss_id: str, text: str) -> bool:
        """对指定候选人发送普通文字消息"""
        ...

    @abstractmethod
    async def click_request_resume(self, boss_id: str) -> bool:
        """点求简历按钮"""
        ...

    @abstractmethod
    async def list_received_resumes(self) -> list[tuple[str, str]]:
        """扫已获取简历 tab → [(boss_id, pdf_url)]"""
        ...
