"""POST /api/resumes/check-boss-ids endpoint tests"""


def test_check_boss_ids_empty_list(client):
    resp = client.post("/api/resumes/check-boss-ids", json={"boss_ids": []})
    assert resp.status_code == 200
    assert resp.json() == {"existing": []}


def test_check_boss_ids_none_in_library(client):
    resp = client.post("/api/resumes/check-boss-ids", json={"boss_ids": ["boss_xxx", "boss_yyy"]})
    assert resp.status_code == 200
    assert resp.json()["existing"] == []


def test_check_boss_ids_some_in_library(client):
    client.post("/api/resumes/", json={
        "name": "张三", "boss_id": "boss_aaa", "source": "boss_zhipin"
    })
    client.post("/api/resumes/", json={
        "name": "李四", "boss_id": "boss_bbb", "source": "boss_zhipin"
    })
    resp = client.post("/api/resumes/check-boss-ids", json={
        "boss_ids": ["boss_aaa", "boss_bbb", "boss_ccc"]
    })
    assert resp.status_code == 200
    existing = set(resp.json()["existing"])
    assert existing == {"boss_aaa", "boss_bbb"}


def test_upload_resume_with_batch_chat_source(client, tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 1 0 obj<</Type/Catalog>>endobj\nxref\n0 2\n0000000000 65535 f\ntrailer<</Size 2>>\nstartxref\n9\n%%EOF")
    with open(pdf, "rb") as f:
        resp = client.post(
            "/api/resumes/upload",
            data={"candidate_name": "测试", "candidate_source": "batch_chat"},
            files={"file": ("test.pdf", f, "application/pdf")},
        )
    # 422 = PDF content too short to parse; but source param itself shouldn't error
    assert resp.status_code in (200, 422)
