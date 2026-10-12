"""Offline tests for the interactive harness shell (no LLM, no network)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ptshell import config as cfg_mod
from ptshell.shell import PtShell

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def shell(tmp_path, monkeypatch):
    monkeypatch.setenv("PTSHELL_CONFIG", str(tmp_path / "config.json"))
    return PtShell(stdout=io.StringIO())


def _run(shell, line: str) -> str:
    # onecmd() bypasses precmd-style handling, so strip the slash here. The
    # shell renders through its rich Console, wired to the fixture's buffer.
    shell.onecmd(line.lstrip("/"))
    return shell.console.file.getvalue()


# --------------------------------------------------------------------------- #
# Config layer
# --------------------------------------------------------------------------- #


def test_config_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("PTSHELL_CONFIG", str(tmp_path / "config.json"))
    cfg = cfg_mod.load()
    assert cfg["seed"] == 42
    assert cfg["model"] == "deepseek/deepseek-chat"
    assert cfg["output_dir"] == "data/shell"


def test_config_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("PTSHELL_CONFIG", str(tmp_path / "config.json"))
    cfg = cfg_mod.load()
    cfg["seed"] = 7
    cfg_mod.save(cfg)
    reloaded = cfg_mod.load()
    assert reloaded["seed"] == 7
    assert reloaded["pretext"] == "executive_request"  # default still merged


def test_config_reset_drops_the_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setenv("PTSHELL_CONFIG", str(path))
    cfg_mod.save({"seed": 99})
    assert path.exists()
    cfg_mod.reset()
    assert not path.exists()
    assert cfg_mod.load()["seed"] == 42


def test_config_empty_file_falls_back_to_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setenv("PTSHELL_CONFIG", str(path))
    path.write_text("", encoding="utf-8")  # e.g. a crashed save / touch
    cfg = cfg_mod.load()
    assert cfg["seed"] == 42
    assert cfg["model"] == "deepseek/deepseek-chat"
    # the empty file is repaired into valid JSON defaults
    assert json.loads(path.read_text(encoding="utf-8"))["seed"] == 42


def test_config_corrupt_file_is_backed_up(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setenv("PTSHELL_CONFIG", str(path))
    path.write_text("{ this is not json", encoding="utf-8")
    cfg = cfg_mod.load()
    assert cfg["seed"] == 42
    # the corrupt file is moved aside, not deleted, and replaced by defaults
    backups = list(tmp_path.glob("config.json.corrupt-*"))
    assert len(backups) == 1
    assert "{ this is not json" in backups[0].read_text(encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["seed"] == 42


def test_config_validation():
    assert cfg_mod.validate("nope", "x") is not None
    assert cfg_mod.validate("seed", "abc") is not None
    assert cfg_mod.validate("pretext", "voice") is not None
    assert cfg_mod.validate("pretext", "it_support") is None
    assert cfg_mod.validate("adapter", "stub") is None
    assert cfg_mod.validate("seed", "42") is None


def test_config_coerces_integers(tmp_path, monkeypatch):
    monkeypatch.setenv("PTSHELL_CONFIG", str(tmp_path / "config.json"))
    cfg = cfg_mod.load()
    cfg["followup_minutes"] = cfg_mod.coerce("followup_minutes", "90")
    assert cfg["followup_minutes"] == 90


# --------------------------------------------------------------------------- #
# Shell commands
# --------------------------------------------------------------------------- #


def test_help_lists_commands(shell):
    out = _run(shell, "/help")
    for cmd in ("generate", "validate", "measure", "reproduce", "config",
                "replay", "replay-logs"):
        assert f"/{cmd}" in out


def test_status_before_any_run(shell):
    out = _run(shell, "/status")
    assert "settings" in out
    assert "none yet" in out


def test_set_config_via_shell_persists(shell):
    _run(shell, "/config seed 7")
    assert shell.cfg["seed"] == 7
    assert cfg_mod.load()["seed"] == 7


def test_config_rejects_bad_value(shell):
    out = _run(shell, "/config pretext voice")
    assert "must be one of" in out
    assert shell.cfg["pretext"] == "executive_request"


def test_config_reset_command(shell):
    _run(shell, "/config seed 99")
    _run(shell, "/config reset")
    assert shell.cfg["seed"] == 42


def test_model_and_models(shell):
    out = _run(shell, "/models")
    assert "deepseek/deepseek-chat" in out
    _run(shell, "/model deepseek/deepseek-reasoner")
    assert shell.cfg["model"] == "deepseek/deepseek-reasoner"


def test_recipients_lists_catalog(shell):
    out = _run(shell, "/recipients")
    assert "ext-supplier-01" in out
    assert "Rebecca Stern" in out


def test_recipient_sets_and_rejects(shell):
    out = _run(shell, "/recipient 40")
    assert shell.cfg["recipient_id"] == "40"
    out = _run(shell, "/recipient nope")
    assert "no recipient" in out


def test_validate_known_case_catches_the_link_failure(shell):
    fixture = REPO_ROOT / "data" / "measurements" / "known-case" / \
        "generated_campaign.json"
    out = _run(shell, f"/validate {fixture}")
    assert "link_consistency" in out
    assert "FAIL" in out
    assert "abc123" in out or "d6db8064874a" in out


def test_validate_missing_file(shell):
    out = _run(shell, "/validate does/not/exist.json")
    assert "no such file" in out


def test_unknown_command_hint(shell):
    out = _run(shell, "/frobnicate")
    assert "unknown command" in out


def test_generate_with_stub_adapter_is_offline(shell, tmp_path):
    _run(shell, "/config adapter stub")
    _run(shell, f"/config output_dir {tmp_path / 'out'}")
    out = _run(shell, "/generate")
    assert "validator report" in out
    assert shell.last_campaign is not None
    assert shell.last_report is not None
    saved = shell.last_paths["campaign"]
    assert saved.exists() and str(tmp_path) in str(saved)


# --------------------------------------------------------------------------- #
# Run manifest + provenance logging + replay
# --------------------------------------------------------------------------- #


def _runs(tmp_path):
    return json.loads((tmp_path / "out" / "runs.json").read_text(encoding="utf-8"))


def _provenance(tmp_path):
    return json.loads(
        (tmp_path / "out" / "q3-awareness-2026" / "provenance.json")
        .read_text(encoding="utf-8")
    )


def _setup_stub(shell, tmp_path):
    _run(shell, "/config adapter stub")
    _run(shell, f"/config output_dir {tmp_path / 'out'}")


def test_generate_writes_the_run_manifest_and_provenance(shell, tmp_path):
    _setup_stub(shell, tmp_path)
    _run(shell, "/generate")
    runs = _runs(tmp_path)
    assert len(runs) == 1
    entry = runs[0]
    assert entry["kind"] == "generate"
    assert entry["adapter"] == "stub"
    assert entry["model"] == shell.cfg["model"]
    assert entry["report"]["all_passed"] is True
    assert entry["spec"]["seed"] == shell.cfg["seed"]
    prov = _provenance(tmp_path)
    assert prov["campaign_id"] == "q3-awareness-2026"
    assert len(prov["messages"]) == 2
    assert prov["messages"][0]["provenance"]["prompt_hash"]
    assert prov["messages"][0]["link_fixes"] == []


def test_replay_reruns_the_last_execution_and_links_it(shell, tmp_path):
    _setup_stub(shell, tmp_path)
    _run(shell, "/generate")
    first_id = _runs(tmp_path)[0]["run_id"]
    out = _run(shell, "/replay")
    runs = _runs(tmp_path)
    assert len(runs) == 2
    assert runs[1]["kind"] == "replay"
    assert runs[1]["parent_run_id"] == first_id
    assert runs[1]["adapter"] == "stub"
    assert shell.last_campaign is not None
    assert shell.last_run["run_id"] == runs[1]["run_id"]
    assert "validator report" in out
    assert first_id in out  # the replay names what it re-ran


def test_replay_before_any_generate_is_graceful(shell, tmp_path):
    _run(shell, f"/config output_dir {tmp_path / 'out'}")
    out = _run(shell, "/replay")
    assert "nothing to replay" in out


def test_replay_uses_the_recorded_adapter_not_the_current_one(shell, tmp_path):
    _setup_stub(shell, tmp_path)
    _run(shell, "/generate")
    _run(shell, "/config adapter adk")  # would need an API key...
    out = _run(shell, "/replay")        # ...but the replay stays offline (stub)
    assert "validator report" in out
    assert _runs(tmp_path)[-1]["adapter"] == "stub"


def test_replay_logs_shows_the_last_replay(shell, tmp_path):
    _setup_stub(shell, tmp_path)
    _run(shell, "/generate")
    _run(shell, "/replay")
    out = _run(shell, "/replay-logs")
    replay_id = _runs(tmp_path)[-1]["run_id"]
    assert replay_id in out
    assert "prompt_hash" in out  # the provenance log is rendered


def test_replay_logs_before_any_replay_is_graceful(shell, tmp_path):
    _setup_stub(shell, tmp_path)
    _run(shell, "/generate")
    out = _run(shell, "/replay-logs")
    assert "no replay recorded" in out


def test_replay_logs_accepts_a_run_id(shell, tmp_path):
    _setup_stub(shell, tmp_path)
    _run(shell, "/generate")
    first = _runs(tmp_path)[0]
    out = _run(shell, f"/replay-logs {first['run_id']}")
    assert first["run_id"] in out
    assert "generate" in out


def test_replay_logs_rejects_an_unknown_run_id(shell, tmp_path):
    _setup_stub(shell, tmp_path)
    _run(shell, "/generate")
    out = _run(shell, "/replay-logs run-999-000000")
    assert "no run" in out


def test_manifest_self_heals_on_corrupt_file(tmp_path):
    from ptshell import runlog

    out = tmp_path / "out"
    out.mkdir()
    (out / "runs.json").write_text("{ not json", encoding="utf-8")
    assert runlog.load_manifest(out) == []
    runlog.append_manifest(out, {"run_id": "run-001-test"})
    assert runlog.last_entry(out)["run_id"] == "run-001-test"
    assert runlog.next_run_id(out).startswith("run-002-")


def test_quit_returns_true(shell):
    assert shell.onecmd("quit") is True
