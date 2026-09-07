"""Patch 7 - the GitHub Actions workflows are well-formed and say what we expect."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["ci.yml", "digest.yml", "keepalive.yml"])
def test_workflow_parses(name: str) -> None:
    data = _load(name)
    assert isinstance(data, dict)
    assert data["jobs"]


def test_ci_runs_the_full_check_suite() -> None:
    steps = _load("ci.yml")["jobs"]["check"]["steps"]
    runs = " ".join(step.get("run", "") for step in steps)
    assert "ruff check" in runs
    assert "ruff format --check" in runs
    assert "mypy src" in runs
    assert "pytest" in runs


def test_digest_schedule_polls_often_and_off_the_hour() -> None:
    data = _load("digest.yml")
    # PyYAML parses the bare `on:` key as boolean True
    triggers = data.get("on") or data.get(True)
    crons = [entry["cron"] for entry in triggers["schedule"]]
    assert crons == ["17,47 7-19 * * *"]
    for cron in crons:
        minute = cron.split()[0]
        assert minute != "0"  # never top of the hour

    run_step = next(
        step for step in data["jobs"]["run"]["steps"] if step.get("name") == "Run digest"
    )
    assert "workflow_dispatch" in run_step["run"]
    assert "--always-send" in run_step["run"]
    assert data["concurrency"]["group"] == "digest"

    commit_step = next(
        step for step in data["jobs"]["run"]["steps"] if step.get("name") == "Commit updated state"
    )
    assert "[skip ci]" in commit_step["run"]
    assert "state/seen_ids.json" in commit_step["run"]


def test_keepalive_uses_pat_with_token_fallback() -> None:
    data = _load("keepalive.yml")
    triggers = data.get("on") or data.get(True)
    assert any(entry["cron"] for entry in triggers["schedule"])
    checkout = data["jobs"]["ping"]["steps"][0]
    assert "KEEPALIVE_PAT" in checkout["with"]["token"]
    assert "github.token" in checkout["with"]["token"]
