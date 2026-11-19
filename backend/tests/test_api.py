import time

import pytest
from fastapi.testclient import TestClient

from clipawesome.api.app import app
from clipawesome.sources import transcribe

from .test_local_media import make_media


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert {"whisper", "ai_configured", "js_runtime"} <= set(body["capabilities"])


def test_settings_secrets_are_masked_and_preserved(client):
    r = client.put("/api/settings", json={"ai": {"provider": "custom", "base_url": "https://llm.maqsoftware.net/v1", "model": "qwen-3.8-27b", "api_key": "sk-secret-123456789"}})
    assert r.status_code == 200
    ai = r.json()["ai"]
    assert ai["api_key"].startswith("••••") and "secret" not in ai["api_key"]
    assert ai["configured"] and ai["has_api_key"]

    r = client.put("/api/settings", json={"ai": {"api_key": ai["api_key"], "temperature": 0.5}})
    assert r.json()["ai"]["has_api_key"] and r.json()["ai"]["temperature"] == 0.5

    r = client.put("/api/settings", json={"ai": {"api_key": "__clear__"}})
    assert not r.json()["ai"]["has_api_key"]

    assert client.put("/api/settings", json={"default_max_clips": 999}).status_code == 422


def test_providers_listed(client):
    providers = client.get("/api/ai/providers").json()
    assert set(providers) == {"custom", "gemini", "groq", "nvidia"}


def test_ai_test_reports_unreachable(client):
    body = client.post("/api/ai/test", json={"provider": "custom", "base_url": "http://127.0.0.1:9/v1", "model": "x", "timeout_sec": 5}).json()
    assert body["ok"] is False and body["message"]


def test_rejects_bad_youtube_url(client):
    r = client.post("/api/analyze/youtube", json={"url": "https://example.com/watch?v=dQw4w9WgXcQ"})
    assert r.status_code == 400


def test_ai_mode_requires_configuration(client):
    client.put("/api/settings", json={"ai": {"provider": "groq", "api_key": "__clear__"}})
    r = client.post("/api/analyze/youtube", json={"url": "dQw4w9WgXcQ", "mode": "ai"})
    assert r.status_code == 400 and "AI" in r.json()["detail"]


def test_local_path_validation(client, tmp_path):
    assert client.post("/api/analyze/local-path", json={"path": str(tmp_path / "missing.mp4")}).status_code == 400
    txt = tmp_path / "notes.txt"
    txt.write_text("x")
    assert client.post("/api/analyze/local-path", json={"path": str(txt)}).status_code == 400


def test_local_path_end_to_end(client, tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe, "available", lambda: False)
    media = make_media(tmp_path / "clip.mkv")
    r = client.post("/api/analyze/local-path", json={"path": str(media), "preset": "shorts", "max_clips": 2})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert job["status"] == "done", job
    analysis = client.get(f"/api/analyses/{job['result_id']}").json()
    assert analysis["clips"] and analysis["sources"][0]["media_id"]

    m = client.get(f"/api/media/{analysis['sources'][0]['media_id']}", headers={"Range": "bytes=0-99"})
    assert m.status_code == 206 and len(m.content) == 100

    assert any(s["id"] == analysis["id"] for s in client.get("/api/analyses").json())
    assert client.delete(f"/api/analyses/{analysis['id']}").status_code == 204
    assert client.get(f"/api/analyses/{analysis['id']}").status_code == 404
    assert media.exists()  # path-registered media is never deleted


def test_media_id_is_validated(client):
    assert client.get("/api/media/..%2F..%2Fsettings.json").status_code == 404
    assert client.get("/api/analyses/..%2Fsettings").status_code == 404
