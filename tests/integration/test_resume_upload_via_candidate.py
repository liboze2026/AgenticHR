"""spec 0429 阶段 B — POST /api/resumes/upload 必须先建 IntakeCandidate

入口收敛后，手动上传 PDF 不再绕过 candidate；走 ensure_candidate（boss_id 空时
用 surrogate_key = sha256(file)[:16]）→ 写 candidate 字段 → promote 出 Resume。
"""
import io
import hashlib
import pytest
from unittest.mock import patch

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.resume.models import Resume


def _fake_pdf_bytes() -> bytes:
    # 最小可被 PyPDF2 read 的 PDF 字节
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<<>>>>endobj\n"
        b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 100 700 Td (test) Tj ET\nendstream endobj\n"
        b"xref\n0 5\n0000000000 65535 f\n"
        b"trailer<</Size 5/Root 1 0 R>>\nstartxref\n300\n%%EOF\n"
    )


def _upload_call(client, content=b"", filename="resume.pdf",
                 candidate_name="", candidate_phone="", candidate_boss_id=""):
    files = {"file": (filename, io.BytesIO(content or _fake_pdf_bytes()), "application/pdf")}
    data = {
        "candidate_name": candidate_name,
        "candidate_phone": candidate_phone,
        "candidate_boss_id": candidate_boss_id,
    }
    return client.post("/api/resumes/upload", files=files, data=data)


@patch("app.modules.resume.pdf_parser.parse_pdf", return_value="模拟 PDF 文本 内容 张三 13800001111")
class TestUploadCreatesCandidate:
    def test_upload_creates_intake_candidate(self, _mock, client, db_session):
        """阶段 B: 上传后 IntakeCandidate 表必须有对应行"""
        resp = _upload_call(client, candidate_name="张三",
                            candidate_phone="13800001111",
                            candidate_boss_id="b_manual_1")
        assert resp.status_code == 201, resp.text
        c = (db_session.query(IntakeCandidate)
             .filter_by(user_id=1, boss_id="b_manual_1").first())
        assert c is not None, "上传应创建 IntakeCandidate"
        assert c.name == "张三"

    def test_upload_promotes_to_resume(self, _mock, client, db_session):
        """阶段 B: 上传后三槽兜底 + PDF 到位 → promote 出 Resume"""
        resp = _upload_call(client, candidate_name="李四",
                            candidate_boss_id="b_manual_2")
        assert resp.status_code == 201
        c = db_session.query(IntakeCandidate).filter_by(boss_id="b_manual_2").first()
        assert c.promoted_resume_id is not None
        r = db_session.query(Resume).get(c.promoted_resume_id)
        assert r is not None

    def test_upload_no_boss_id_uses_surrogate(self, _mock, client, db_session):
        """阶段 B: 无 boss_id 上传 → surrogate_key = sha256(file)[:16] 入 boss_id"""
        body = _fake_pdf_bytes()
        expected_surrogate = "manual_" + hashlib.sha256(body).hexdigest()[:16]
        resp = _upload_call(client, content=body, candidate_name="王五")
        assert resp.status_code == 201
        c = (db_session.query(IntakeCandidate)
             .filter_by(user_id=1, boss_id=expected_surrogate).first())
        assert c is not None, f"应以 surrogate {expected_surrogate} 建 candidate"

    def test_repeat_upload_same_file_dedups(self, _mock, client, db_session):
        """阶段 B: 同文件重复上传 → 同一 surrogate → 不重复建 candidate"""
        body = _fake_pdf_bytes()
        _upload_call(client, content=body, candidate_name="张三")
        _upload_call(client, content=body, candidate_name="张三")
        cnt = (db_session.query(IntakeCandidate)
               .filter(IntakeCandidate.boss_id.like("manual_%")).count())
        assert cnt == 1


class TestSimpleLibraryShowsManualUploads:
    @patch("app.modules.resume.pdf_parser.parse_pdf", return_value="模拟 PDF 文本")
    def test_manual_upload_appears_in_resume_library(self, _mock, client, db_session):
        """阶段 B 验收：手动上传的简历必须出现在简历库列表（不再孤儿）"""
        resp = _upload_call(client, candidate_name="孤儿测试",
                            candidate_boss_id="b_manual_lib")
        assert resp.status_code == 201
        list_resp = client.get("/api/resumes/")
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        assert any(i["name"] == "孤儿测试" for i in items), \
            f"手动上传应出现在简历库，实际 items: {[i.get('name') for i in items]}"
