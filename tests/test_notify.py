import dataclasses

import pytest

from orchid.notify import Notifier


def test_public_base_url_default(settings):
    assert settings.public_base_url == "http://127.0.0.1:4242"


def test_url_builders(settings):
    n = Notifier(dataclasses.replace(settings, base_url="http://lan:9/"))
    assert n.session_url("p", "s") == "http://lan:9/?project=p&session=s"
    assert n.review_url("p", "r") == "http://lan:9/?project=p&review=r"
    assert n.session_url(None, None) == "http://lan:9"  # trailing slash trimmed


@pytest.mark.asyncio
async def test_pushover_disabled_is_noop(settings, monkeypatch):
    calls = []
    monkeypatch.setattr("orchid.notify.requests.post", lambda *a, **k: calls.append((a, k)))
    n = Notifier(settings)  # no token/user configured
    assert not n.pushover_enabled
    await n.push("t", "m", url="u")
    assert calls == []  # never hits the network


@pytest.mark.asyncio
async def test_pushover_sends_with_url(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "orchid.notify.requests.post",
        lambda url, data=None, timeout=None: calls.append((url, data)),
    )
    s = dataclasses.replace(settings, pushover_token="tok", pushover_user="usr",
                            base_url="http://lan:4242")
    n = Notifier(s)
    assert n.pushover_enabled
    await n.push("Title", "Body", url=n.session_url("prj", "sid"), url_title="Open")
    assert len(calls) == 1
    url, data = calls[0]
    assert "pushover.net" in url
    assert data["token"] == "tok" and data["user"] == "usr"
    assert data["title"] == "Title" and data["message"] == "Body"
    assert data["url"] == "http://lan:4242/?project=prj&session=sid"
    assert data["url_title"] == "Open"


def test_push_bg_disabled_is_noop(settings):
    n = Notifier(settings)  # disabled — returns before scheduling any task
    n.push_bg("T", "B")
    assert n._tasks == set()


@pytest.mark.asyncio
async def test_push_bg_schedules_holds_ref_and_sends(settings, monkeypatch):
    import asyncio

    calls = []
    monkeypatch.setattr(
        "orchid.notify.requests.post",
        lambda url, data=None, timeout=None: calls.append(data),
    )
    s = dataclasses.replace(settings, pushover_token="t", pushover_user="u", base_url="http://x")
    n = Notifier(s)
    n.push_bg("T", "B", url="http://x/?p=1")
    assert len(n._tasks) == 1  # strong ref held so it can't be GC'd mid-send
    await asyncio.sleep(0.02)
    assert len(calls) == 1 and calls[0]["title"] == "T"
    assert n._tasks == set()  # discarded on completion


@pytest.mark.asyncio
async def test_push_swallows_errors(settings, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr("orchid.notify.requests.post", boom)
    s = dataclasses.replace(settings, pushover_token="tok", pushover_user="usr")
    await Notifier(s).push("t", "m")  # must not raise
