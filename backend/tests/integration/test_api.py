import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services.application_service import ApplicationService


def test_amplify_dashboard_can_call_the_local_api():
    origin = "https://main.d1rsqjlswai0rr.amplifyapp.com"
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/applications",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
                "Access-Control-Request-Private-Network": "true",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-private-network"] == "true"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_unknown_origin_is_rejected():
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/applications",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 400


def test_health_and_openapi():
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["database"] == "ok"
        docs = client.get("/openapi.json")
        assert docs.status_code == 200
        paths = docs.json()["paths"]
        assert "/api/v1/applications/validate" in paths
        assert "/api/v1/tests/{test_id}/run" in paths
        assert "/api/v1/tests/{test_id}/report" in paths


def test_reference_upload_and_test_create_do_not_echo_a_password():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/applications",
            json={"name": "Amplify", "type": "web", "url": "https://example.amplifyapp.com", "username": "tester"},
        )
        assert created.status_code == 201
        assert "password" not in created.json()
        image = Image.new("RGB", (64, 48), (20, 20, 20))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        uploaded = client.post(
            "/api/v1/references/upload",
            files={"file": ("reference-earring-correct.png", buffer.getvalue(), "image/png")},
            data={"side": "left"},
        )
        assert uploaded.status_code == 201
        body = uploaded.json()
        assert body["filename"] == "reference-earring-correct.png"
        assert body["width"] == 64
        assert body["height"] == 48
        listed = client.get("/api/v1/references")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == body["id"]
        test = client.post(
            "/api/v1/tests",
            json={
                "name": "Left Earring Placement Test",
                "application_id": created.json()["id"],
                "reference_id": body["id"],
                "jewelry_id": "E123",
                "jewelry_type": "earring",
                "ear_side": "left",
                "capture_fps": 5,
                "minimum_confidence": 0.8,
                "pass_threshold": 0.10,
                "fail_threshold": 0.15,
                "minimum_pass_rate": 0.95,
                "maximum_consecutive_failures": 2,
            },
        )
        assert test.status_code == 201
        assert "password" not in test.json()
        rejected = client.post(
            "/api/v1/references/upload",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert rejected.status_code == 422


def test_catalog_api_rejects_a_bad_tryon_url():
    with TestClient(app) as client:
        response = client.post("/api/v1/applications/catalog", json={"url": "not a url"})
        assert response.status_code == 200
        body = response.json()
        assert body["categories"] == []
        assert "Invalid URL" in body["message"]


def test_tryon_form_starts_empty():
    with TestClient(app) as client:
        response = client.get("/api/v1/applications/form")
        assert response.status_code == 200
        assert response.json() == {"name": "", "url": "", "username": ""}


def test_try_on_url_is_validated_without_being_stored():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/applications",
            json={"name": "Amplify", "type": "web", "url": "https://one.example/try-on", "username": "tester"},
        )
        assert created.status_code == 201
        assert created.json()["url"] is None
        app_id = created.json()["id"]
        patched = client.patch(f"/api/v1/applications/{app_id}", json={"url": "https://two.example/try-on"})
        assert patched.status_code == 200
        assert patched.json()["url"] is None
        validated = client.post(
            "/api/v1/applications/validate",
            json={
                "url": "https://three.example/try-on",
                "name": "Showroom",
                "username": "tester",
                "password": "secret-value",
                "application_id": app_id,
            },
        )
        assert validated.status_code == 200
        assert validated.json()["status"] == "failed"
        stored = client.get(f"/api/v1/applications/{app_id}")
        assert stored.json()["url"] is None
        assert stored.json()["name"] == "Showroom"
        assert ApplicationService.validated_urls[app_id] == "https://three.example/try-on"


def test_passed_url_is_saved_and_a_different_pass_is_kept_too():
    from app.db.database import session_scope
    from app.schemas.application import ApplicationCreate

    service = ApplicationService()
    with session_scope() as session:
        record = service.create(
            session,
            ApplicationCreate(name="Amplify", type="web", url="https://one.example/try-on", username="tester"),
        )
        assert record.url is None
        first = service.save_passed_url(session, record, "https://one.example/try-on", "tester")
        assert first.id == record.id
        assert first.url == "https://one.example/try-on"
        second = service.save_passed_url(session, first, "https://two.example/try-on", "tester", name="Evening drop")
        assert second.id != first.id
        assert second.url == "https://two.example/try-on"
        assert second.name == "Evening drop"
        assert session.get(type(first), first.id).url == "https://one.example/try-on"


def test_finished_test_saves_the_url_with_the_given_name():
    from app.db.database import session_scope
    from app.schemas.application import ApplicationCreate

    service = ApplicationService()
    with session_scope() as session:
        record = service.create(
            session,
            ApplicationCreate(name="Draft", type="web", url="https://showroom.example/try-on", username="tester"),
        )
        record.name = "Showroom"
        session.add(record)
        session.commit()
        session.refresh(record)
        service.remember_url(record.id, "https://showroom.example/try-on")
        saved = service.save_tested_application(session, record.id)
        assert saved is not None
        assert saved.id == record.id
        assert saved.name == "Showroom"
        assert saved.url == "https://showroom.example/try-on"


def test_invalid_url_fails_without_opening_a_browser():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/applications/validate",
            json={"url": "not a url", "username": "tester", "password": "secret-value"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "failed"
        assert payload["reachable"] is False
        assert "secret-value" not in response.text
