from fastapi.testclient import TestClient

from clipawesome import config as cfg
from clipawesome.api.app import app

AUTH = ("admin", "s3cret-pass")


def test_auth_required_when_password_set(monkeypatch):
    monkeypatch.setattr(cfg, "AUTH_USER", AUTH[0])
    monkeypatch.setattr(cfg, "AUTH_PASSWORD", AUTH[1])
    with TestClient(app) as client:
        denied = client.get("/api/settings")
        assert denied.status_code == 401 and "Basic" in denied.headers["www-authenticate"]
        assert client.get("/api/settings", auth=("admin", "wrong")).status_code == 401
        assert client.get("/api/settings", headers={"Authorization": "Basic !!notbase64"}).status_code == 401
        assert client.get("/api/settings", auth=AUTH).status_code == 200
        assert client.get("/api/healthz").json() == {"status": "ok"}
        assert client.get("/api/health").status_code == 401


def test_no_auth_when_password_unset(monkeypatch):
    monkeypatch.setattr(cfg, "AUTH_PASSWORD", "")
    with TestClient(app) as client:
        assert client.get("/api/settings").status_code == 200


def test_local_path_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "AUTH_PASSWORD", "")
    monkeypatch.setattr(cfg, "ALLOW_LOCAL_PATH", False)
    media = tmp_path / "x.mp4"
    media.write_bytes(b"0")
    with TestClient(app) as client:
        r = client.post("/api/analyze/local-path", json={"path": str(media)})
        assert r.status_code == 403
        assert client.get("/api/health").json()["capabilities"]["local_path"] is False
