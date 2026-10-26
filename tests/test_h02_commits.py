"""Offline installed-revision detection for H02 physical permit binding."""
from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch

from chamber_web.hil.commits import detect_gui_commit


COMMIT = "a" * 40


def _result(stdout="", returncode=0):
    return CompletedProcess([], returncode, stdout=stdout, stderr="")


def test_gui_commit_requires_a_clean_tracked_checkout():
    with patch("chamber_web.hil.commits.subprocess.run", side_effect=[
        _result(COMMIT + "\n"), _result(""),
    ]) as run:
        assert detect_gui_commit() == COMMIT
    assert run.call_args_list[1].args[0][-1] == "--untracked-files=no"

    with patch("chamber_web.hil.commits.subprocess.run", side_effect=[
        _result(COMMIT + "\n"), _result(" M chamber_web/main.py\n"),
    ]):
        assert detect_gui_commit() == ""


def test_gui_commit_fails_closed_when_git_cannot_verify_status():
    with patch("chamber_web.hil.commits.subprocess.run", side_effect=[
        _result(COMMIT + "\n"), _result(returncode=1),
    ]):
        assert detect_gui_commit() == ""
