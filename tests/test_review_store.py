"""Tests for the review store."""

from orchid.store import review_store


def test_roundtrip(tmp_path):
    review = {
        "id": "rev_aabbcc",
        "project_id": "prj_x",
        "branch": "feat/hello",
        "summary": "Added hello",
        "status": "pending",
        "reviewer_notes": None,
        "created_at": "2026-01-01T00:00:00Z",
    }
    review_store.write_review(tmp_path, review)
    loaded = review_store.read_review(tmp_path, "rev_aabbcc")
    assert loaded is not None
    assert loaded["branch"] == "feat/hello"
    assert loaded["status"] == "pending"


def test_list_and_sort(tmp_path):
    for i, ts in enumerate(["2026-01-01", "2026-01-03", "2026-01-02"]):
        review_store.write_review(tmp_path, {
            "id": f"rev_{i:06x}00",
            "project_id": "prj_x",
            "branch": f"feat/{i}",
            "summary": f"Review {i}",
            "status": "pending",
            "created_at": ts,
        })
    reviews = review_store.list_reviews(tmp_path)
    assert len(reviews) == 3
    assert reviews[0]["created_at"] == "2026-01-03"


def test_delete(tmp_path):
    review_store.write_review(tmp_path, {
        "id": "rev_deadbeef",
        "project_id": "prj_x",
        "branch": "feat/del",
        "summary": "To delete",
        "status": "pending",
    })
    assert review_store.delete_review(tmp_path, "rev_deadbeef")
    assert review_store.read_review(tmp_path, "rev_deadbeef") is None


def test_path_safety(tmp_path):
    assert review_store.read_review(tmp_path, "../../etc/passwd") is None
    assert not review_store.delete_review(tmp_path, "bad_id")
