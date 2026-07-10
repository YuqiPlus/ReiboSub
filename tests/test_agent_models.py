from __future__ import annotations

from video_translate.agent.models import AgentSession


def test_agent_session_serializes_workflow_state():
    session = AgentSession(
        id="session-1",
        status="waiting",
        phase="review_glossary",
        payload={"source_language": "korean"},
        question={"kind": "confirm"},
    )

    assert session.to_dict() == {
        "id": "session-1",
        "status": "waiting",
        "phase": "review_glossary",
        "payload": {"source_language": "korean"},
        "result": {},
        "question": {"kind": "confirm"},
        "logs": [],
        "error": "",
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "cancellable": True,
        "retryable": False,
    }
