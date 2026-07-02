from __future__ import annotations

import asyncio

from core.memory.context import ContextAssembler
from core.memory.dreaming import DREAM_ARTIFACT_KIND, DreamingService
from core.memory.session_manager import SessionManager


def test_context_artifacts_are_idempotent_and_searchable(tmp_path):
    mgr = SessionManager(tmp_path / "sessions.db")
    try:
        first = mgr.upsert_context_artifact(
            session_id="s1",
            kind="compaction_summary",
            source_start_seq=0,
            source_end_seq=5,
            content="Implemented context budget policy and GLM downshift guard.",
            metadata={"trigger": "model_switch"},
        )
        second = mgr.upsert_context_artifact(
            session_id="s1",
            kind="compaction_summary",
            source_start_seq=0,
            source_end_seq=5,
            content="Implemented context budget policy and GLM downshift guard.",
            metadata={"trigger": "model_switch"},
        )
        assert first == second
        artifacts = mgr.list_context_artifacts(session_id="s1")
        assert len(artifacts) == 1
        hits = mgr.search_context_artifacts("GLM downshift", session_id="s1")
        assert len(hits) == 1
        assert hits[0]["kind"] == "compaction_summary"
    finally:
        mgr.close()


def test_dreaming_writes_fallback_artifact(tmp_path):
    mgr = SessionManager(tmp_path / "sessions.db")
    try:
        mgr.upsert_messages(
            "s1",
            [
                {"role": "user", "content": "Need durable context dreaming.", "seq": 0},
                {"role": "assistant", "content": "I will inspect SQLite context.", "seq": 1},
            ],
        )
        service = DreamingService(session_manager=mgr)
        result = asyncio.run(service.dream_session("s1", use_llm=False))
        assert result.did_dream is True
        assert result.artifact_id
        artifacts = mgr.list_context_artifacts(session_id="s1", kinds=(DREAM_ARTIFACT_KIND,))
        assert len(artifacts) == 1
        assert "Durable Facts" in artifacts[0].content
    finally:
        mgr.close()


def test_context_assembler_injects_long_context_artifacts(tmp_path):
    mgr = SessionManager(tmp_path / "sessions.db")
    try:
        mgr.upsert_context_artifact(
            session_id="s1",
            kind="dream",
            content="## Durable Facts\n- User wants Hermes-level context.",
            source_start_seq=0,
            source_end_seq=9,
        )
        assembler = ContextAssembler(session_manager=mgr)
        context = assembler.assemble("s1", "subject")
        assert "_long_context_summary" in context
        assert "Hermes-level context" in context["_long_context_summary"]
        assert "Long context:" in context["_llm_summary"]
    finally:
        mgr.close()
