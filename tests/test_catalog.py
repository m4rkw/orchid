from datetime import datetime, timezone

import pytest
from claude_agent_sdk import SDKSessionInfo

from orchid.claude.catalog import Catalog, map_summary


def _info(**over):
    base = dict(
        session_id="sid-1",
        summary=None,
        last_modified=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
        file_size=100,
        custom_title=None,
        first_prompt=None,
        git_branch="main",
        cwd="/tmp/p",
        tag=None,
        created_at=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
    )
    base.update(over)
    return SDKSessionInfo(**base)


def test_title_fallback_order():
    assert map_summary(_info(custom_title="Custom", summary="Sum"), {}).title == "Custom"
    assert map_summary(_info(summary="Sum", first_prompt="fp"), {}).title == "Sum"
    long_prompt = "word " * 40
    s = map_summary(_info(first_prompt=long_prompt), {})
    assert s.title.endswith("…") and len(s.title) == 81
    assert map_summary(_info(), {}).title is None


def test_flags_merge():
    s = map_summary(_info(), {"pinned": True, "created_by": "orchid", "archived": True})
    assert s.pinned and s.archived and s.created_by == "orchid"
    assert map_summary(_info(), {}).created_by == "external"


def test_timestamps_iso():
    s = map_summary(_info(), {})
    assert s.updated_at == "2026-06-12T10:00:00+00:00"
    assert s.created_at == "2026-06-12T09:00:00+00:00"


@pytest.mark.asyncio
async def test_list_sessions_empty_project(homes, tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    assert await Catalog().list_sessions(root, {}) == []


def test_timestamps_epoch_millis():
    s = map_summary(_info(last_modified=1781234567890, created_at=1781234560.0), {})
    assert s.updated_at.startswith("2026-06-")
    assert s.created_at.startswith("2026-06-")
