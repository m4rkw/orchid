from claude_agent_sdk import SessionMessage

from orchid.claude.transcript import TranscriptCache, normalize_record
from orchid.models import Block, NormalizedMessage


def rec(type_="assistant", uuid="u1", content=None, sid="sid-1"):
    return SessionMessage(
        type=type_,
        uuid=uuid,
        session_id=sid,
        message={"role": type_, "content": content if content is not None else [{"type": "text", "text": "hi"}]},
        parent_tool_use_id=None,
    )


def nm(uuid, text="x"):
    return NormalizedMessage(uuid=uuid, role="assistant", agent_id=None, blocks=[Block(type="text", text=text)])


def test_normalize_record_user_prompt_renders():
    out = normalize_record(rec(type_="user", content="do the thing"))
    assert out.role == "user"
    assert out.blocks[0].type == "text"
    assert out.blocks[0].text == "do the thing"


def test_normalize_record_block_shapes():
    content = [
        {"type": "text", "text": "t"},
        {"type": "thinking", "thinking": "deep"},
        {"type": "tool_use", "id": "tu", "name": "Bash", "input": {"command": "ls"}},
        {"type": "tool_result", "tool_use_id": "tu", "content": [{"type": "text", "text": "out"}], "is_error": False},
    ]
    out = normalize_record(rec(content=content))
    assert [b.type for b in out.blocks] == ["text", "thinking", "tool_use", "tool_result"]
    assert out.blocks[2].name == "Bash"
    assert out.blocks[3].content_preview == "out"
    assert out.uuid == "u1"


def test_normalize_record_skips_non_chat_lines():
    assert normalize_record(rec(type_="ai-title")) is None
    assert normalize_record(rec(type_="file-history-snapshot")) is None


def test_normalize_record_agent_tag():
    out = normalize_record(rec(), agent_id="agent-1")
    assert out.agent_id == "agent-1"


def test_cache_ingest_diffs():
    cache = TranscriptCache()
    fresh = cache.ingest("s", [nm("a"), nm("b")])
    assert [m.uuid for m in fresh] == ["a", "b"]
    fresh = cache.ingest("s", [nm("a"), nm("b"), nm("c")])
    assert [m.uuid for m in fresh] == ["c"]
    assert cache.message_count("s") == 3


def test_cache_append_live_dedups_with_ingest():
    cache = TranscriptCache()
    assert cache.append_live("s", nm("a")) is True
    assert cache.append_live("s", nm("a")) is False
    fresh = cache.ingest("s", [nm("a"), nm("b")])
    assert [m.uuid for m in fresh] == ["b"]


def test_cache_eviction_cap():
    cache = TranscriptCache(max_messages=3)
    cache.ingest("s", [nm(f"u{i}") for i in range(5)])
    assert [m.uuid for m in cache.get("s")] == ["u2", "u3", "u4"]
    # evicted uuids stay in the seen set: a disk re-read must not re-append them
    assert cache.ingest("s", [nm("u0")]) == []


def test_ingest_drops_stranded_live_partial_keeps_real_inflight():
    # A streamed partial with a synthetic "live-" uuid (its persisted copy lands
    # on disk under a different real uuid) must NOT be stranded at the end on
    # re-read — but a genuinely in-flight message with a real uuid is kept.
    cache = TranscriptCache()
    cache.append_live("s", nm("live-abc123", "partial answer"))   # transient stream copy
    cache.append_live("s", nm("real-inflight", "not on disk yet"))
    # disk re-read: the persisted answer has its real uuid; the partial is NOT on disk
    cache.ingest("s", [nm("u-prompt"), nm("u-answer", "full answer")])
    uuids = [m.uuid for m in cache.get("s")]
    assert "live-abc123" not in uuids            # stranded partial dropped
    assert uuids[:2] == ["u-prompt", "u-answer"]  # disk order preserved
    assert "real-inflight" in uuids              # genuine in-flight kept


def test_cache_drop():
    cache = TranscriptCache()
    cache.ingest("s", [nm("a")])
    cache.drop("s")
    assert cache.get("s") is None
