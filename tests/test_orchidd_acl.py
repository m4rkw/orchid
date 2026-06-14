"""Tests for orchidd ACL loading, validation, and enforcement."""

import json
import pytest
from pathlib import Path

from orchidd.acl import check_exec, check_file_op, find_grant, load_acl, save_acl


@pytest.fixture
def acl_file(tmp_path):
    return tmp_path / "acl.json"


@pytest.fixture
def sample_grant():
    return {
        "id": "grant_abc123",
        "project_root": "/private/var/macos",
        "project_id": "prj_123",
        "permanent": True,
        "operations": {
            "file_read": True,
            "file_write": True,
            "file_delete": False,
            "exec": [
                "systemctl restart macos-config",
                "systemctl status *",
            ],
        },
    }


def test_load_missing_file(acl_file):
    assert load_acl(acl_file) == []


def test_load_corrupt_file(acl_file):
    acl_file.write_text("not json")
    assert load_acl(acl_file) == []


def test_save_and_load(acl_file, sample_grant):
    save_acl(acl_file, [sample_grant])
    grants = load_acl(acl_file)
    assert len(grants) == 1
    assert grants[0]["id"] == "grant_abc123"


def test_save_atomic(acl_file, sample_grant):
    save_acl(acl_file, [sample_grant])
    assert not acl_file.with_suffix(".json.tmp").exists()


def test_find_grant_exact(sample_grant):
    assert find_grant([sample_grant], "/private/var/macos") is sample_grant


def test_find_grant_alias(sample_grant):
    # /var -> /private/var on macOS
    assert find_grant([sample_grant], "/var/macos") is sample_grant


def test_find_grant_missing(sample_grant):
    assert find_grant([sample_grant], "/private/var/other") is None


def test_check_file_op_read_allowed(sample_grant):
    assert check_file_op(sample_grant, "read_file", "/private/var/macos/file.py") is None


def test_check_file_op_write_allowed(sample_grant):
    assert check_file_op(sample_grant, "write_file", "/private/var/macos/service/x.py") is None


def test_check_file_op_delete_denied(sample_grant):
    err = check_file_op(sample_grant, "delete_file", "/private/var/macos/file.py")
    assert err and "file_delete" in err


def test_check_file_op_outside_root(sample_grant):
    err = check_file_op(sample_grant, "read_file", "/private/var/www/other/file.py")
    assert err and "outside project root" in err


def test_check_file_op_path_traversal(sample_grant):
    err = check_file_op(sample_grant, "read_file", "/private/var/macos/../../etc/passwd")
    assert err and "outside project root" in err


def test_check_exec_exact_match(sample_grant):
    assert check_exec(sample_grant, ["systemctl", "restart", "macos-config"]) is None


def test_check_exec_wildcard(sample_grant):
    assert check_exec(sample_grant, ["systemctl", "status", "anything"]) is None
    assert check_exec(sample_grant, ["systemctl", "status"]) is None


def test_check_exec_denied(sample_grant):
    err = check_exec(sample_grant, ["rm", "-rf", "/"])
    assert err and "not in exec whitelist" in err


def test_check_exec_partial_match_denied(sample_grant):
    err = check_exec(sample_grant, ["systemctl", "restart", "sshd"])
    assert err and "not in exec whitelist" in err


def test_check_exec_no_list():
    grant = {"project_root": "/x", "operations": {}}
    err = check_exec(grant, ["echo", "hi"])
    assert err and "no exec commands" in err
