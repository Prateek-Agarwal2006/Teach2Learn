import uuid
import asyncio
from base64 import b64encode
import json

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

import app.main as main_module
from app.main import app, database, transcripts


def set_participant_session(client: TestClient, participant_id: str) -> None:
    session = b64encode(json.dumps({"participant_id": participant_id}).encode("utf-8"))
    client.cookies.set("session", TimestampSigner("local-development-change-me").sign(session).decode("utf-8"))


def test_complete_participant_flow():
    external_id = f"test-{uuid.uuid4().hex[:10]}"
    participant = database.get_or_create_participant(
        external_id,
        "Portal Tester",
        {
            "auth_provider": "google",
            "email": "tester@pilani.bits-pilani.ac.in",
            "hosted_domain": "pilani.bits-pilani.ac.in",
        },
    )
    with TestClient(app) as client:
        set_participant_session(client, participant["id"])

        selection = client.get("/study")
        assert selection.status_code == 200
        assert "Choose what you want to study" in selection.text

        started = client.post(
            "/study/start",
            data={
                "model": "qwen3",
                "subject": "os",
                "topic": "foundations",
                "subtopic": "Purpose and services",
            },
            follow_redirects=False,
        )
        assert started.status_code == 303
        session_id = started.headers["location"].rsplit("/", 1)[-1]

        page = client.get(f"/sessions/{session_id}")
        assert page.status_code == 200
        assert "Purpose and services" in page.text

        with client.websocket_connect(f"/ws/chat/{session_id}") as socket:
            for turn in range(1, 7):
                socket.send_json({"message": f"Teacher explanation number {turn}."})
                response = socket.receive_json()
                if response.get("status") == "evaluating":
                    assert response["content"]
                    response = socket.receive_json()
                assert response["turn"] == turn
                assert response.get("content") or turn < 3
                if response["complete"]:
                    break

        session = database.get_session(session_id)
        assert session and session["status"] == "completed"
        assert session["metadata"]["turn"] == 4
        assert session["metadata"]["study_variant"] == "hci"
        assert session["metadata"]["survey_instrument"] is None
        assert len(transcripts.read(session_id)) == 9

        complete = client.get(f"/sessions/{session_id}/complete")
        assert complete.status_code == 200
        assert "How you taught the AI learner" in complete.text
        assert "Strengths" in complete.text
        assert "Improvements" in complete.text
        assert "Summary" in complete.text
        assert "You built a useful explanation across the conversation." in complete.text
        assert "Evaluation of EquitableT2L" not in complete.text
        assert 'name="quant_q' not in complete.text
        assert 'name="qual_q' not in complete.text
        assert "EquitableT2L" in complete.text

        disabled_survey = client.post(
            f"/sessions/{session_id}/survey",
            follow_redirects=False,
        )
        assert disabled_survey.status_code == 303
        assert disabled_survey.headers["location"] == f"/sessions/{session_id}/complete"
        assert database.get_survey(session_id) is None

        history = client.get("/history")
        assert history.status_code == 200
        assert "Purpose and services" in history.text


def test_manual_login_is_not_available():
    with TestClient(app) as client:
        page = client.get("/login")
        assert page.status_code == 200
        assert "Participant ID" not in page.text
        assert "Continue with study ID" not in page.text
        assert client.post("/login", data={"participant_id": "bypass", "name": "Bypass"}).status_code == 405


def test_legacy_manual_session_is_rejected():
    participant = database.get_or_create_participant(f"legacy-{uuid.uuid4().hex[:10]}", "Legacy User")
    with TestClient(app) as client:
        set_participant_session(client, participant["id"])
        response = client.get("/study", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_other_participant_cannot_access_session_data():
    owner = database.get_or_create_participant(
        f"owner-{uuid.uuid4().hex[:10]}",
        "Owner",
        {
            "auth_provider": "google",
            "email": "owner@pilani.bits-pilani.ac.in",
            "hosted_domain": "pilani.bits-pilani.ac.in",
        },
    )
    other = database.get_or_create_participant(
        f"other-{uuid.uuid4().hex[:10]}",
        "Other",
        {
            "auth_provider": "google",
            "email": "other@pilani.bits-pilani.ac.in",
            "hosted_domain": "pilani.bits-pilani.ac.in",
        },
    )
    session_id = database.create_session(
        owner["id"],
        "os",
        "Private topic",
        {"model": "qwen3", "turn": 0},
        opening_message={"role": "assistant", "content": "Private opening question", "turn": 0},
    )

    with TestClient(app) as client:
        set_participant_session(client, other["id"])
        assert client.get(f"/sessions/{session_id}", follow_redirects=False).headers["location"] == "/login"
        assert client.get(f"/sessions/{session_id}/complete", follow_redirects=False).headers["location"] == "/login"
        assert client.get(f"/sessions/{session_id}/thanks", follow_redirects=False).headers["location"] == "/login"
        assert client.get(f"/history/{session_id}", follow_redirects=False).headers["location"] == "/history"
        survey = client.post(
            f"/sessions/{session_id}/survey",
            follow_redirects=False,
        )
        assert survey.headers["location"] == "/history"
        assert database.get_survey(session_id) is None
        with client.websocket_connect(f"/ws/chat/{session_id}") as socket:
            assert socket.receive_json() == {"error": "This session is unavailable."}


def test_health_is_minimal_and_catalog_requires_authentication():
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.json() == {"status": "ok"}
        assert health.headers["x-frame-options"] == "DENY"
        assert health.headers["x-content-type-options"] == "nosniff"
        assert health.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
        assert client.get("/api/catalog").status_code == 401

        participant = database.get_or_create_participant(
            f"catalog-{uuid.uuid4().hex[:10]}",
            "Catalog Tester",
            {
                "auth_provider": "google",
                "email": "catalog@pilani.bits-pilani.ac.in",
                "hosted_domain": "pilani.bits-pilani.ac.in",
            },
        )
        set_participant_session(client, participant["id"])
        catalog = client.get("/api/catalog").json()
        assert len(catalog["models"]) == 7
        assert set(catalog["subjects"]) == {"cp", "dsa", "oop_java", "os"}


def test_admin_can_browse_all_users_and_turns_without_losing_normal_access():
    owner = database.get_or_create_participant(
        f"admin-target-{uuid.uuid4().hex[:10]}",
        "Admin Target",
        {
            "auth_provider": "google",
            "email": "target@pilani.bits-pilani.ac.in",
            "hosted_domain": "pilani.bits-pilani.ac.in",
        },
    )
    session_id = database.create_session(
        owner["id"],
        "os",
        "Admin-only inspection",
        {"model": "qwen3", "model_name": "Qwen 3", "turn": 0},
        opening_message={
            "role": "assistant",
            "content": "What does a scheduler do?",
            "turn": 0,
            "raw_content": "hidden model output",
        },
    )
    database.record_turn(
        session_id,
        {"role": "user", "content": "It selects which ready process runs next.", "turn": 1},
        {
            "role": "assistant",
            "content": "How might priorities affect that choice?",
            "turn": 1,
            "latency_ms": 725,
            "inline_evaluation": {
                "level": "Understand",
                "score": "High",
                "strength": "Correctly identified the scheduler's main responsibility.",
                "improvement": "Explain how the scheduling policy makes the selection.",
            },
        },
        {"turn": 1},
    )
    admin = database.get_or_create_participant(
        f"admin-{uuid.uuid4().hex[:10]}",
        "Study Admin",
        {
            "auth_provider": "google",
            "email": "f20230309@pilani.bits-pilani.ac.in",
            "hosted_domain": "pilani.bits-pilani.ac.in",
        },
    )

    with TestClient(app) as client:
        set_participant_session(client, admin["id"])
        assert client.get("/study").status_code == 200
        assert client.get("/history").status_code == 200

        dashboard = client.get("/admin")
        assert dashboard.status_code == 200
        assert "Admin Target" in dashboard.text
        assert "target@pilani.bits-pilani.ac.in" in dashboard.text

        user_page = client.get(f"/admin/users/{owner['id']}")
        assert user_page.status_code == 200
        assert "Admin-only inspection" in user_page.text

        session_page = client.get(f"/admin/sessions/{session_id}")
        assert session_page.status_code == 200
        assert "What does a scheduler do?" in session_page.text
        assert "Understand" in session_page.text
        assert "High score" in session_page.text
        assert "Correctly identified the scheduler&#39;s main responsibility." in session_page.text
        assert "Explain how the scheduling policy makes the selection." in session_page.text
        assert "How might priorities affect that choice?" in session_page.text
        assert "Final evaluation" in session_page.text


def test_admin_routes_reject_non_admin_and_unauthenticated_users():
    user = database.get_or_create_participant(
        f"non-admin-{uuid.uuid4().hex[:10]}",
        "Regular Student",
        {
            "auth_provider": "google",
            "email": "regular@pilani.bits-pilani.ac.in",
            "hosted_domain": "pilani.bits-pilani.ac.in",
        },
    )
    with TestClient(app) as client:
        assert client.get("/admin", follow_redirects=False).headers["location"] == "/login"
        set_participant_session(client, user["id"])
        assert client.get("/admin").status_code == 403
        assert client.get(f"/admin/users/{user['id']}").status_code == 403
        assert "href=\"/admin\"" not in client.get("/study").text


def test_openrouter_final_feedback_uses_luna_with_high_reasoning(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": self.content}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            }

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["request"] = kwargs
            system_prompt = kwargs["json"]["messages"][0]["content"]
            if "turn evaluator" in system_prompt:
                return FakeResponse(
                    "<evaluation>\nLevel: Apply\nScore: High\nStrength: Accurate.\n"
                    "Improvement: Add an example.\n</evaluation>"
                )
            return FakeResponse("<final_feedback>\nSummary: Clear teaching.\n</final_feedback>")

    monkeypatch.setattr(main_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(main_module, "OPENROUTER_API_KEY", "test-secret")
    content, metadata = asyncio.run(main_module.generate_openrouter_feedback("AI learner: Why?"))

    assert "Clear teaching" in content
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["request"]["json"]["model"] == "openai/gpt-5.6-luna"
    assert captured["request"]["json"]["reasoning"] == {"effort": "high", "exclude": True}
    assert captured["request"]["headers"]["Authorization"] == "Bearer test-secret"
    assert metadata["provider"] == "openrouter"
    assert metadata["usage"]["total_tokens"] == 30

    evaluation, turn_metadata = asyncio.run(
        main_module.generate_openrouter_turn_evaluation(
            "Mutexes",
            [
                {"role": "assistant", "content": "Why do we need a mutex?"},
                {"role": "user", "content": "It prevents simultaneous critical-section access."},
            ],
        )
    )
    assert evaluation["level"] == "Apply"
    assert evaluation["score"] == "High"
    assert evaluation["strength"] == "Accurate."
    assert evaluation["improvement"] == "Add an example."
    assert turn_metadata["model"] == "openai/gpt-5.6-luna"
    assert "Why do we need a mutex?" in captured["request"]["json"]["messages"][1]["content"]


def test_request_size_guard_rejects_oversized_body(monkeypatch):
    monkeypatch.setattr("app.main.MAX_REQUEST_BYTES", 1024)
    with TestClient(app) as client:
        response = client.post("/logout", content=b"x" * 1025)
        assert response.status_code == 413


def test_production_post_requires_exact_public_origin(monkeypatch):
    monkeypatch.setattr("app.main.IS_PRODUCTION", True)
    monkeypatch.setattr("app.main.PUBLIC_ORIGIN", "https://learnbyteaching.sasanktumpati.com")
    client = TestClient(app)
    rejected = client.post("/logout", headers={"Origin": "https://attacker.example"})
    assert rejected.status_code == 403
    allowed = client.post(
        "/logout",
        headers={"Origin": "https://learnbyteaching.sasanktumpati.com"},
        follow_redirects=False,
    )
    assert allowed.status_code == 303
