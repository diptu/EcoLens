from __future__ import annotations

import subprocess

from app.service.mlops.tracking import git_sha


def test_git_sha_returns_a_real_commit_hash_inside_this_repo():
    sha = git_sha()

    assert sha is not None
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_git_sha_returns_none_when_git_is_unavailable(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert git_sha() is None
