"""通知消息模板"""


def interview_email_to_candidate(candidate_name, interviewer_name, job_title, interview_time, meeting_link, meeting_password=""):
    subject = f"面试邀请 - {job_title}"
    body = f"""尊敬的 {candidate_name}：

您好！感谢您对我们公司的关注。

我们诚挚地邀请您参加以下面试：

- 岗位：{job_title}
- 面试时间：{interview_time}
- 面试官：{interviewer_name}
- 面试方式：线上视频面试
- 会议链接：{meeting_link}
{"- 会议密码：" + meeting_password if meeting_password else ""}

请提前5分钟进入会议室，确保网络通畅、环境安静。

祝顺利！"""
    return subject, body


def interview_feishu_to_interviewer(interviewer_name, candidate_name, job_title, interview_time, meeting_link, candidate_resume_summary=""):
    msg = f"""面试安排通知

候选人：{candidate_name}
岗位：{job_title}
时间：{interview_time}
会议链接：{meeting_link}"""
    if candidate_resume_summary:
        msg += f"\n\n候选人信息：\n{candidate_resume_summary}"
    return msg


def interview_template_for_copy(candidate_name, job_title, interview_time, meeting_link, meeting_password=""):
    return f"""您好 {candidate_name}，我们安排了面试：

岗位：{job_title}
时间：{interview_time}
方式：线上视频面试
会议链接：{meeting_link}
{"会议密码：" + meeting_password if meeting_password else ""}

请提前5分钟入会，祝面试顺利！"""
