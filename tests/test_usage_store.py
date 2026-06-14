from orchid.store import usage_store


def test_add_turn_accumulates(homes):
    root = homes.tmp / "proj"
    root.mkdir()

    u = usage_store.add_turn(root, "sid-1", cost_usd=0.10, duration_ms=1000, is_error=False)
    assert u["total_cost_usd"] == 0.10
    assert u["turns"] == 1
    assert u.get("errors") is None  # no error key until one occurs

    u = usage_store.add_turn(root, "sid-1", cost_usd=0.05, duration_ms=500, is_error=True)
    assert u["total_cost_usd"] == 0.15
    assert u["total_duration_ms"] == 1500
    assert u["turns"] == 2
    assert u["errors"] == 1

    # round-trips from disk
    again = usage_store.read_usage(root, "sid-1")
    assert again["total_cost_usd"] == 0.15
    assert again["turns"] == 2


def test_read_usage_missing(homes):
    root = homes.tmp / "proj"
    root.mkdir()
    assert usage_store.read_usage(root, "nope") == {}


def test_project_usage_rolls_up(homes):
    root = homes.tmp / "proj"
    root.mkdir()
    usage_store.add_turn(root, "sid-1", cost_usd=0.10, duration_ms=100, is_error=False)
    usage_store.add_turn(root, "sid-1", cost_usd=0.20, duration_ms=100, is_error=False)
    usage_store.add_turn(root, "sid-2", cost_usd=0.30, duration_ms=100, is_error=False)

    roll = usage_store.project_usage(root)
    assert roll["total_cost_usd"] == 0.60
    assert roll["turns"] == 3
    assert roll["sessions"] == 2


def test_project_usage_empty(homes):
    root = homes.tmp / "proj"
    root.mkdir()
    assert usage_store.project_usage(root) == {"total_cost_usd": 0.0, "turns": 0, "sessions": 0}


def test_bad_session_id_writes_nothing(homes):
    root = homes.tmp / "proj"
    root.mkdir()
    assert usage_store.add_turn(root, "../escape", cost_usd=1.0, duration_ms=1, is_error=False) == {}
    assert usage_store.add_turn(root, "", cost_usd=1.0, duration_ms=1, is_error=False) == {}
    assert not (usage_store.usage_dir(root)).exists() or not any(usage_store.usage_dir(root).iterdir())
