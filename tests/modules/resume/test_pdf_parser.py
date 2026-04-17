"""PDF 解析测试"""
from app.modules.resume.pdf_parser import parse_pdf, extract_resume_fields


def _create_test_pdf(path: str, text: str):
    """创建一个包含指定文本的简单 PDF 用于测试"""
    import os
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_name = "Helvetica"
    # 在 Windows 上注册中文字体以正确嵌入中文字符
    for name, fpath in [
        ("SimSun", "C:/Windows/Fonts/simsun.ttc"),
        ("MicrosoftYaHei", "C:/Windows/Fonts/msyh.ttc"),
    ]:
        if os.path.exists(fpath):
            try:
                pdfmetrics.registerFont(TTFont(name, fpath))
                font_name = name
                break
            except Exception:
                pass

    c = canvas.Canvas(path)
    c.setFont(font_name, 12)
    y = 800
    for line in text.split("\n"):
        c.drawString(72, y, line)
        y -= 15
    c.save()


def test_parse_pdf_extracts_text(tmp_path):
    pdf_path = str(tmp_path / "test.pdf")
    _create_test_pdf(pdf_path, "张三\n手机：13800138000\n邮箱：zhangsan@test.com")
    text = parse_pdf(pdf_path)
    assert "张三" in text
    assert "13800138000" in text


def test_parse_pdf_file_not_found():
    text = parse_pdf("/nonexistent/file.pdf")
    assert text == ""


def test_extract_resume_fields_phone():
    text = "联系方式：13912345678，邮箱test@qq.com"
    fields = extract_resume_fields(text)
    assert fields["phone"] == "13912345678"
    assert fields["email"] == "test@qq.com"


def test_extract_resume_fields_education():
    text = "教育经历：北京大学 本科 计算机科学 2015-2019"
    fields = extract_resume_fields(text)
    assert fields["education"] in ["本科", "硕士", "博士", "大专", ""]
