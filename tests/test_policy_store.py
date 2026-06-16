"""Tests for the autonomy policy store."""

from orchid.store import policy_store, project_store


def test_roundtrip(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project_store.init_project(root, "prj_test", "test-project")

    assert policy_store.read_policy(root) is None

    policy_store.write_policy(root, policy_store.PRESETS["strict"])
    loaded = policy_store.read_policy(root)
    assert loaded is not None
    assert loaded["profile"] == "strict"
    assert loaded["plan_approval"] == "human"
    assert loaded["gates"]["tests_pass"]["mode"] == "required"


def test_resolve_falls_back_to_balanced(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project_store.init_project(root, "prj_test", "test-project")

    policy = policy_store.resolve_policy(root)
    assert policy["profile"] == "balanced"
    assert policy["review_strategy"] == "agent"
    assert policy["gates"]["tests_pass"]["mode"] == "required"


def test_resolve_maps_legacy_review_mode_manual(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project_store.init_project(root, "prj_test", "test-project")
    f = project_store.read_project_file(root)
    f["review_mode"] = "manual"
    project_store.write_project_file(root, f)

    policy = policy_store.resolve_policy(root)
    assert policy["review_strategy"] == "human"


def test_resolve_maps_legacy_review_mode_autonomous(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project_store.init_project(root, "prj_test", "test-project")
    f = project_store.read_project_file(root)
    f["review_mode"] = "autonomous"
    project_store.write_project_file(root, f)

    policy = policy_store.resolve_policy(root)
    assert policy["review_strategy"] == "agent"


def test_explicit_policy_overrides_legacy(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project_store.init_project(root, "prj_test", "test-project")
    f = project_store.read_project_file(root)
    f["review_mode"] = "manual"
    project_store.write_project_file(root, f)

    policy_store.write_policy(root, policy_store.PRESETS["permissive"])
    policy = policy_store.resolve_policy(root)
    assert policy["profile"] == "permissive"
    assert policy["review_strategy"] == "self"


def test_presets_have_expected_shapes():
    for name, preset in policy_store.PRESETS.items():
        assert preset["profile"] == name
        assert preset["plan_approval"] in ("auto", "human")
        assert preset["review_strategy"] in ("agent", "human", "self")
        assert preset["merge_approval"] in ("auto", "human")
        assert "tests_pass" in preset["gates"]
        for gate in preset["gates"].values():
            assert gate["mode"] in ("required", "optional", "skip")


def test_partial_policy_merges_with_defaults(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    project_store.init_project(root, "prj_test", "test-project")

    policy_store.write_policy(root, {
        "profile": "custom",
        "plan_approval": "human",
        "review_strategy": "agent",
        "merge_approval": "auto",
        "gates": {"tests_pass": {"mode": "required"}},
    })
    policy = policy_store.resolve_policy(root)
    assert policy["plan_approval"] == "human"
    assert policy["gates"]["tests_pass"]["mode"] == "required"
    assert "spec_compliance" in policy["gates"]
