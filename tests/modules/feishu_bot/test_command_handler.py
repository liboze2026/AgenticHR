"""飞书机器人指令处理测试"""
from app.modules.feishu_bot.command_handler import CommandHandler
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def test_help_command(db_session):
    handler = CommandHandler(db_session)
    result = handler.handle("帮助")
    assert "查看概览" in result
    assert "查看简历" in result


def test_dashboard_command(db_session):
    db_session.add(Resume(name="测试", phone="13165338580", status="pending"))
    db_session.add(Resume(name="测试2", phone="13165338581", status="passed"))
    db_session.commit()

    handler = CommandHandler(db_session)
    result = handler.handle("查看概览")
    assert "待筛选：1" in result
    assert "已通过：1" in result


def test_list_resumes_command(db_session):
    db_session.add(Resume(name="候选人甲", phone="13165338582", status="pending", education="本科", work_years=3, skills="Python"))
    db_session.commit()

    handler = CommandHandler(db_session)
    result = handler.handle("查看简历")
    assert "候选人甲" in result


def test_list_resumes_empty(db_session):
    handler = CommandHandler(db_session)
    result = handler.handle("查看简历")
    assert "暂无" in result


def test_list_jobs_command(db_session):
    db_session.add(Job(title="Python开发", department="技术部", education_min="本科", work_years_min=3))
    db_session.commit()

    handler = CommandHandler(db_session)
    result = handler.handle("管理岗位")
    assert "Python开发" in result


def test_unknown_command(db_session):
    handler = CommandHandler(db_session)
    result = handler.handle("随便说什么")
    assert "帮助" in result or "指令" in result
