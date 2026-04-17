"""IMAP 邮件接收器测试"""
from app.adapters.email_receiver import EmailReceiver


def test_email_receiver_not_configured():
    """未配置 IMAP 时 is_configured 返回 False"""
    receiver = EmailReceiver(host="", user="", password="")
    assert receiver.is_configured() is False
    # fetch 也应安全返回空列表
    assert receiver.fetch_new_resumes() == []


def test_decode_header():
    """测试邮件头解码"""
    # 纯 ASCII
    assert EmailReceiver._decode_header("hello") == "hello"
    # 空字符串
    assert EmailReceiver._decode_header("") == ""
    # RFC 2047 编码
    encoded = "=?utf-8?B?5L2g5aW9?="  # "你好" in base64
    assert EmailReceiver._decode_header(encoded) == "你好"
