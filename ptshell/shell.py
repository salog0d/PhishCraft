"""PhishCraft — the interactive harness shell: a styled, visual REPL over the generator.

    python -m ptshell

A Claude-Code-style terminal UI: a colored prompt (model + adapter inline),
tab-completion with descriptions, persistent command history, and rich
rendering of every command — panels, tables, spinners, and pass/fail badges.

All commands work with or without the leading slash (``/generate`` or
``generate``). Settings persist to ``~/.pt-shell/config.json`` (override with
the ``PTSHELL_CONFIG`` env var) and can be changed in-session; model switches
take effect on the next generation.

Capabilities live as ``cmd_*`` methods on :class:`PtShell`; adding a new
capability = add a method + a ``COMMANDS`` row.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ptshell import config as cfg_mod
from ptshell.config import KNOWN_MODELS

REPO_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------- #
# PhishCraft look & feel: a purple + white palette (dim greys allowed).
# --------------------------------------------------------------------- #
PURPLE = "#a855f7"        # vivid purple — borders, accents
PURPLE_BRIGHT = "#c084fc"  # light purple — headings, prompt, highlights
PURPLE_SOFT = "#a78bfa"   # soft violet — secondary accents
PURPLE_DEEP = "#6d28d9"   # deep purple — selection backgrounds

# The startup drawing: a FIGlet "PHISHCRAFT" logo and a little fish scene.
_LOGO = [
    " mmmmm  m    m mmmmm   mmmm  m    m   mmm  mmmmm    mm   mmmmmmmmmmmmm",
    ' #   "# #    #   #    #"   " #    # m"   " #   "#   ##   #        #',
    ' #mmm#" #mmmm#   #    "#mmm  #mmmm# #      #mmmm"  #  #  #mmmmm   #',
    ' #      #    #   #        "# #    # #      #   "m  #mm#  #        #',
    ' #      #    # mm#mm  "mmm#" #    #  "mmm" #    " #    # #        #',
]

_FISH = [
    "          ><((((°>               ><((((°>",
    "      ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
]

COMMANDS: dict[str, str] = {
    "help": "show this command list (/help [command])",
    "config": "view or set settings (/config, /config <key> [value], /config reset)",
    "model": "set the generation model (/model <id>)",
    "models": "list known model ids",
    "recipients": "list the target catalog (12 internal + 3 external personas)",
    "recipient": "set the default recipient (/recipient <id>)",
    "generate": "run the ADK pipeline once; save campaign + report",
    "validate": "run the 5 coherence checks on a campaign file",
    "measure": "run the 10-spec reliability suite (writes summary.md)",
    "reproduce": "run the same spec twice and compare (default: S1)",
    "replay": "re-run the last execution (from the run manifest) and show it again",
    "replay-logs": "show the manifest entry + provenance log of the last replay",
    "send": "deliver the last generated campaign to MailHog",
    "status": "show current settings and the last run summary",
    "quit": "exit the shell (also /exit or Ctrl-D)",
}

_PROMPT_STYLE = {
    "prompt": "#c084fc bold",
    "prompt.dim": "ansibrightblack",
    "bottom-toolbar": "bg:#2e1065 #e9d5ff",
    "completion-menu.completion": "bg:#1e1b4b #d8b4fe",
    "completion-menu.completion.current": "bg:#6d28d9 #ffffff",
    "completion-menu.meta.completion": "bg:#312e81 #a78bfa",
    "completion-menu.meta.completion.current": "bg:#6d28d9 #e9d5ff",
}


class PtShell:
    def __init__(self, stdout=None, cfg_path: Path | None = None):
        if cfg_path is not None:
            os.environ["PTSHELL_CONFIG"] = str(cfg_path)
        self.console = Console(file=stdout) if stdout is not None else Console()
        self.cfg: dict = cfg_mod.load()
        self._active_model: str | None = None
        self.last_campaign = None
        self.last_report = None
        self.last_paths: dict[str, Path] = {}
        self.last_recipient: dict | None = None
        self.last_run: dict | None = None  # manifest entry of the last execution

    # ------------------------------------------------------------------ #
    # small rendering helpers
    # ------------------------------------------------------------------ #

    def _err(self, message: str) -> None:
        self.console.print(Panel(Text(message, style="red"), border_style="red",
                                 title="error", title_align="left", padding=(0, 1)))

    def _dim(self, message: str) -> None:
        self.console.print(Text(message, style="dim"))

    def _panel(self, content, title: str, border: str = PURPLE) -> None:
        self.console.print(Panel(content, title=title, title_align="left",
                                 border_style=border, padding=(1, 2)))

    def _banner(self) -> None:
        recipient = self.cfg["recipient_id"] or "first non-executive"
        self.console.print(Text("\n".join(_LOGO), style=f"{PURPLE_BRIGHT} bold"))
        self.console.print(
            Text(_FISH[0] + "\n", style="white")
            + Text(_FISH[1], style=f"{PURPLE_SOFT} dim")
        )
        body = Text()
        body.append("interactive harness for the phishing-campaign generator\n",
                    style="dim")
        body.append("settings  ", style="bold")
        body.append(str(cfg_mod.config_path()) + "\n")
        body.append("model     ", style="bold")
        body.append(f"{self.cfg['model']}  (adapter: {self.cfg['adapter']})\n")
        body.append("recipient ", style="bold")
        body.append(f"{recipient}  ·  pretext: {self.cfg['pretext']}  ·  "
                    f"tone: {self.cfg['tone']}  ·  seed: {self.cfg['seed']}\n")
        body.append("type /help for commands · /quit to exit", style="dim")
        self._panel(body, "PhishCraft", border=PURPLE)

    # ------------------------------------------------------------------ #
    # plumbing
    # ------------------------------------------------------------------ #

    def _save_cfg(self) -> None:
        cfg_mod.save(self.cfg)

    def _apply_model(self) -> None:
        """Point the ADK pipeline at the configured model (env-driven)."""
        model = self.cfg["model"]
        os.environ["ADK_MODEL"] = model
        if self._active_model != model:
            # agent.pipeline resolves the model at import time; force a
            # re-resolve after a mid-session switch.
            for name in ("agent.pipeline", "agent.config", "agent.driver"):
                sys.modules.pop(name, None)
            self._active_model = model

    def _default_recipient_id(self) -> str:
        from generator_agent.catalog import load_catalog

        internal = [p for p in load_catalog() if p["class"] == "internal"]
        return str(next(p for p in internal if p["level"] != 1)["id"])

    def _mission(self) -> dict:
        path = Path(self.cfg["mission"])
        return json.loads(path.read_text(encoding="utf-8"))

    def _build_spec(self, mission: dict) -> dict:
        recipient_id = self.cfg["recipient_id"] or self._default_recipient_id()
        return {
            "spec_id": "shell",
            "campaign_id": mission["campaign_id"],
            "pretext": self.cfg["pretext"],
            "tone": self.cfg["tone"],
            "difficulty": self.cfg["difficulty"],
            "language": self.cfg["language"],
            "seed": self.cfg["seed"],
            "model": mission["model_policy"]["models"][0],
            "recipient_id": recipient_id,
            "start_at": self.cfg["start_at"],
            "followup_minutes": self.cfg["followup_minutes"],
        }

    def _render_campaign(self, campaign, report) -> None:
        body = Text()
        body.append("persona  ", style="bold")
        body.append(f"{campaign.persona.display_name} "
                    f"<{campaign.persona.email}>\n")
        body.append(f"campaign  {campaign.campaign_id} · "
                    f"{len(campaign.messages)} messages\n\n", style="dim")

        channel_style = {"email": "white", "sms": PURPLE}
        for m in campaign.messages:
            badge = m.channel.value.upper()
            body.append(f"  {badge:<5} ", style=channel_style[m.channel.value])
            body.append(m.message_id, style="bold")
            body.append(f"  @ {m.scheduled_at}\n", style="dim")
            if m.subject:
                body.append(f"    subject  {m.subject}\n")
            body.append(f"    body     ", style="dim")
            body.append(f"{m.body[:130]}\n")
            body.append(f"    cta      {m.call_to_action.landing_url}\n\n",
                        style="dim")
        self._panel(body, f"campaign · {campaign.campaign_id}")

        table = Table(title="validator report", box=box.SIMPLE_HEAVY,
                      header_style="bold", expand=False)
        table.add_column("check", style="bold")
        table.add_column("result")
        table.add_column("detail", style="dim", max_width=90)
        for r in report.results:
            if r.passed:
                table.add_row(r.check.value, Text("✓ PASS", style="green"), r.detail)
            else:
                table.add_row(r.check.value, Text("✗ FAIL", style="bold red"), r.detail)
        self.console.print(table)

        verdict = ("✓ ALL PASSED", "green") if report.all_passed else \
            ("✗ VIOLATIONS FOUND", "bold red")
        self.console.print(Text(f"all_passed: {verdict[0]}", style=verdict[1]))
        self.console.print()

    def _render_config(self) -> None:
        table = Table(title=f"settings ({cfg_mod.config_path()})",
                      box=box.SIMPLE_HEAVY, expand=False)
        table.add_column("key", style=f"bold {PURPLE_BRIGHT}")
        table.add_column("value")
        table.add_column("valid options", style="dim")
        for key in sorted(self.cfg):
            value = str(self.cfg[key]) or "(default)"
            options = ", ".join(cfg_mod.VALID_VALUES.get(key, ())) or "—"
            table.add_row(key, value, options)
        self.console.print(table)

    # ------------------------------------------------------------------ #
    # dispatch (kept test-friendly: onecmd == dispatch)
    # ------------------------------------------------------------------ #

    def dispatch(self, line: str) -> bool:
        line = line.strip().lstrip("/")
        if not line:
            return False
        parts = shlex.split(line)
        command, arg = parts[0], " ".join(parts[1:])
        # multi-word commands are written with dashes (/replay-logs) and map
        # to cmd_* methods with underscores (cmd_replay_logs).
        handler = getattr(self, f"cmd_{command.replace('-', '_')}", None)
        if handler is None:
            self.console.print(
                f"[red]unknown command[/red] '{command}' — "
                f"type [bold]/help[/bold] for the list"
            )
            return False
        try:
            return bool(handler(arg))
        except Exception as exc:  # provider, parse, validation failures
            self._err(f"{type(exc).__name__}: {exc}")
            return False

    onecmd = dispatch  # compatibility with cmd.Cmd-style callers/tests

    # ------------------------------------------------------------------ #
    # commands
    # ------------------------------------------------------------------ #

    def cmd_help(self, arg: str) -> None:
        name = arg.strip()
        if name and name in COMMANDS:
            self.console.print(f"[bold]/{name}[/bold] — {COMMANDS[name]}")
            return
        table = Table(title="commands", box=box.SIMPLE_HEAVY, expand=False,
                      header_style=f"bold {PURPLE_BRIGHT}")
        table.add_column("command", style="bold")
        table.add_column("description")
        for key, desc in COMMANDS.items():
            table.add_row(f"/{key}", desc)
        self.console.print(table)
        self._dim("tip: everything also works without the leading slash")

    def cmd_config(self, arg: str) -> None:
        tokens = shlex.split(arg)
        if not tokens:
            self._render_config()
            return
        if tokens[0] == "reset":
            cfg_mod.reset()
            self.cfg = cfg_mod.load()
            self.console.print(Text("settings reset to defaults", style="green"))
            return
        if len(tokens) == 1:
            key = tokens[0]
            if key not in self.cfg:
                self._err(f"unknown key '{key}'")
                return
            self.console.print(f"[bold]{key}[/bold] = {self.cfg[key]}")
            return
        if len(tokens) == 2:
            key, value = tokens
            error = cfg_mod.validate(key, value)
            if error:
                self._err(error)
                return
            self.cfg[key] = cfg_mod.coerce(key, value)
            self._save_cfg()
            self.console.print(
                Text(f"{key} = {self.cfg[key]}", style="green") +
                Text("  (saved)", style="dim")
            )
            return
        self._dim("usage: /config [key [value]] | /config reset")

    def cmd_model(self, arg: str) -> None:
        tokens = shlex.split(arg)
        if not tokens:
            self.console.print(f"model = [bold]{self.cfg['model']}[/bold]")
            return
        model = tokens[0]
        if model in cfg_mod.ollama_models():
            # A bare Ollama name (e.g. 'qwen3:8b') selects the local instance.
            model = f"ollama/{model}"
        self.cfg["model"] = model
        self._save_cfg()
        self._active_model = None
        self.console.print(
            Text(f"model = {model}", style="green") +
            Text("  (applies to the next /generate)", style="dim")
        )

    def cmd_models(self, arg: str) -> None:
        table = Table(title="known model ids (LiteLlm format)",
                      box=box.SIMPLE_HEAVY, expand=False)
        table.add_column("model id", style="bold")
        table.add_column("note", style="dim")
        for m in KNOWN_MODELS:
            note = "current" if m == self.cfg["model"] else "needs its provider API key"
            table.add_row(m, note)
        for name in cfg_mod.ollama_models():
            model_id = f"ollama/{name}"
            note = "current" if model_id == self.cfg["model"] else "local Ollama"
            table.add_row(model_id, note)
        self.console.print(table)
        if cfg_mod.ollama_models():
            self._dim("local models discovered from `ollama list` — pull more "
                      "with `ollama pull <model>` and they appear here")
        else:
            self._dim("no local Ollama models — `ollama list` found none "
                      "(or Ollama isn't installed/running)")

    def cmd_recipients(self, arg: str) -> None:
        from generator_agent.catalog import load_catalog

        table = Table(title="target catalog (personas are derived from "
                            "pretext + recipient)",
                      box=box.SIMPLE_HEAVY, header_style="bold", expand=False)
        table.add_column("id")
        table.add_column("class")
        table.add_column("org_type")
        table.add_column("name / role", style="bold")
        table.add_column("email", style="dim")
        class_style = {"internal": "white", "external": PURPLE}
        for p in load_catalog():
            table.add_row(
                str(p["id"]),
                Text(p["class"], style=class_style.get(p["class"], "white")),
                str(p["org_type"]),
                f"{p['display_name']} ({p['role'] or '—'})",
                p["email"],
            )
        self.console.print(table)

    def cmd_recipient(self, arg: str) -> None:
        from generator_agent.catalog import load_catalog

        tokens = shlex.split(arg)
        if not tokens:
            self.console.print(
                f"recipient_id = [bold]{self.cfg['recipient_id'] or '(default)'}[/bold]"
            )
            return
        pid = tokens[0]
        catalog = load_catalog()
        match = next((p for p in catalog if str(p["id"]) == pid), None)
        if match is None:
            self._err(f"no recipient with id '{pid}' — see /recipients")
            return
        self.cfg["recipient_id"] = pid
        self._save_cfg()
        self.console.print(
            Text(f"recipient = {pid} ({match['display_name']})", style="green") +
            Text("  (saved)", style="dim")
        )

    def _execute(self, spec: dict, mission: dict, adapter: str):
        """Run the pipeline through the configured/recorded adapter.

        Returns ``(campaign, report, run_info)`` — the driver's refinement
        metadata is recorded in the run manifest alongside the artifacts.
        """
        if adapter == "stub":
            from measurement.adapters import get_adapter

            return get_adapter("stub").run_with_info(spec, mission)
        from agent.driver import run_pipeline_with_info

        return run_pipeline_with_info(spec, mission)

    def _record_run(
        self, kind: str, adapter: str, spec: dict, mission: dict, campaign,
        report, run_info: dict | None = None, parent_run_id: str | None = None,
    ) -> dict:
        """Persist the execution: artifacts, provenance log, manifest entry."""
        from ptshell import runlog

        out = Path(self.cfg["output_dir"]) / mission["campaign_id"]
        out.mkdir(parents=True, exist_ok=True)
        campaign_path = out / "generated_campaign.json"
        report_path = out / "coherence_report.json"
        campaign_path.write_text(campaign.model_dump_json(indent=2), encoding="utf-8")
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        provenance_path = runlog.write_provenance(campaign, out)

        run_id = runlog.next_run_id(self.cfg["output_dir"])
        entry = runlog.build_entry(
            run_id=run_id,
            kind=kind,
            parent_run_id=parent_run_id,
            adapter=adapter,
            model=self.cfg["model"],
            spec=spec,
            files={
                "campaign": campaign_path,
                "report": report_path,
                "provenance": provenance_path,
            },
            run_info=run_info,
            report=report,
        )
        runlog.append_manifest(self.cfg["output_dir"], entry)

        self.last_campaign = campaign
        self.last_report = report
        self.last_paths = {
            "campaign": campaign_path,
            "report": report_path,
            "provenance": provenance_path,
        }
        self.last_run = entry
        return entry

    def cmd_generate(self, arg: str) -> None:
        mission = self._mission()
        spec = self._build_spec(mission)
        self._apply_model()
        with self.console.status(
            f"[{PURPLE_BRIGHT}]generating with {self.cfg['model']} "
            f"(adapter: {self.cfg['adapter']})…[/{PURPLE_BRIGHT}]"
        ):
            campaign, report, info = self._execute(
                spec, mission, self.cfg["adapter"]
            )

        from generator_agent.catalog import profile_for

        self.last_recipient = profile_for(
            spec["recipient_id"], pretext=spec["pretext"]
        )
        entry = self._record_run(
            "generate", self.cfg["adapter"], spec, mission, campaign, report,
            run_info=info,
        )

        self._render_campaign(campaign, report)
        self._dim(f"run: {entry['run_id']}  ({entry['adapter']} · "
                  f"{entry['model']})")
        self._dim(f"saved: {self.last_paths['campaign']}")
        self._dim(f"saved: {self.last_paths['report']}")
        self._dim(f"saved: {self.last_paths['provenance']}")

    def cmd_validate(self, arg: str) -> None:
        from app.core.schemas import GeneratedCampaign
        from validator_agent.validate import validate_campaign

        tokens = shlex.split(arg)
        path = Path(tokens[0]) if tokens else self.last_paths.get("campaign")
        if path is None:
            self._dim("nothing to validate — pass a path or run /generate first")
            return
        if not Path(path).exists():
            self._err(f"no such file: {path}")
            return
        try:
            campaign = GeneratedCampaign.model_validate_json(
                Path(path).read_text(encoding="utf-8")
            )
        except Exception as exc:
            self._err(f"not a valid GeneratedCampaign: {type(exc).__name__}: {exc}")
            return
        report = validate_campaign(campaign)
        self._render_campaign(campaign, report)

    def cmd_measure(self, arg: str) -> None:
        from measurement.reliability import run as run_reliability

        runs = 1
        for tok in shlex.split(arg):
            if tok.startswith("--runs="):
                runs = int(tok.split("=", 1)[1])
        if self.cfg["adapter"] != "stub":
            self._apply_model()
        with self.console.status(
            f"[{PURPLE_BRIGHT}]running 10-spec reliability suite "
            f"(adapter: {self.cfg['adapter']}, runs: {runs})…[/{PURPLE_BRIGHT}]"
        ):
            payload = run_reliability(adapter_name=self.cfg["adapter"], runs=runs)

        n_ok = payload["n_runs"] - payload["n_generation_errors"]
        headline = Text()
        headline.append("post-assembler violations (delivery guarantee): ", style="bold")
        headline.append(f"{payload['n_campaigns_with_violation']}/{n_ok}",
                        style="bold red" if payload["n_campaigns_with_violation"]
                        else "bold green")
        headline.append(f"   (failure rate {payload['failure_rate']})\n")
        headline.append("raw LLM link violations (generator reliability): ", style="bold")
        headline.append(f"{payload['n_campaigns_with_raw_link_violation']}/{n_ok}",
                        style="bold red"
                        if payload["n_campaigns_with_raw_link_violation"]
                        else "bold green")
        headline.append(
            f"   (raw rate {payload['raw_link_violation_rate']})"
        )
        self._panel(headline, f"reliability · {payload['adapter']} · "
                              f"{payload['model']}")

        table = Table(title="violations by coherence check",
                      box=box.SIMPLE_HEAVY, expand=False)
        table.add_column("check", style="bold")
        table.add_column("violations")
        for check, count in payload["violation_counts"].items():
            style = "red" if count else "green"
            table.add_row(check, Text(str(count), style=style))
        self.console.print(table)
        self._dim(f"saved: {payload['out_dir']}")

    def cmd_reproduce(self, arg: str) -> None:
        from measurement.reproduce import run as run_reproduce

        tokens = shlex.split(arg)
        spec_id = None if "all" in tokens else "S1"
        if self.cfg["adapter"] != "stub":
            self._apply_model()
        with self.console.status(
            f"[{PURPLE_BRIGHT}]reproducibility run: adapter {self.cfg['adapter']}, "
            f"spec {'all' if spec_id is None else spec_id} × 2…[/{PURPLE_BRIGHT}]"
        ):
            results = run_reproduce(
                spec_id=spec_id, runs=2, adapter_name=self.cfg["adapter"]
            )

        table = Table(title="reproducibility", box=box.SIMPLE_HEAVY, expand=False)
        table.add_column("spec", style="bold")
        table.add_column("seed")
        table.add_column("content")
        table.add_column("deterministic layer")
        table.add_column("errors")
        for sid, res in results["specs"].items():
            content = (Text("identical", style="green") if res["identical"]
                       else Text("DIFFERENT", style="bold red"))
            layer = (Text("identical", style="green")
                     if res["deterministic_layer_identical"]
                     else Text("DIFFERENT", style="bold red"))
            errors = sum(1 for r in res["runs"] if r["status"] != "ok")
            table.add_row(sid, str(res["seed"]), content, layer, str(errors))
        self.console.print(table)
        self._dim(f"saved: {results['out_dir']}")

    def cmd_replay(self, arg: str) -> None:
        """Re-run the last execution recorded in the run manifest."""
        from ptshell import runlog

        entry = runlog.last_entry(self.cfg["output_dir"])
        if entry is None:
            self._dim("nothing to replay — the run manifest is empty; "
                      "/generate first")
            return
        spec, adapter, model = entry["spec"], entry["adapter"], entry["model"]
        mission = self._mission()
        self._dim(
            f"replaying {entry['run_id']} ({adapter} · {model}) — recorded in "
            f"{runlog.manifest_path(self.cfg['output_dir'])}"
        )

        saved_model = self.cfg["model"]
        try:
            # Point the pipeline at the *recorded* model — a replay re-runs the
            # last execution as it was, not the current settings.
            self.cfg["model"] = model
            self._apply_model()
            with self.console.status(
                f"[{PURPLE_BRIGHT}]replaying {entry['run_id']} "
                f"(adapter: {adapter})…[/{PURPLE_BRIGHT}]"
            ):
                campaign, report, info = self._execute(spec, mission, adapter)
        finally:
            self.cfg["model"] = saved_model
            self._active_model = None  # force re-resolve on the next run

        replay_entry = self._record_run(
            "replay", adapter, spec, mission, campaign, report,
            run_info=info, parent_run_id=entry["run_id"],
        )
        self._render_campaign(campaign, report)
        self._dim(f"replay run: {replay_entry['run_id']}  "
                  f"(replayed {entry['run_id']})")
        self._dim(f"saved: {self.last_paths['campaign']}")
        self._dim(f"saved: {self.last_paths['provenance']}")

    def cmd_replay_logs(self, arg: str) -> None:
        """Show the manifest entry + provenance log of the last replay.

        ``/replay-logs`` shows the most recent replay; ``/replay-logs <run_id>``
        shows any run recorded in the manifest.
        """
        from ptshell import runlog

        tokens = shlex.split(arg)
        entries = runlog.load_manifest(self.cfg["output_dir"])
        if tokens:
            entry = next((e for e in entries if e["run_id"] == tokens[0]), None)
            if entry is None:
                self._err(f"no run '{tokens[0]}' in the manifest")
                return
        else:
            replays = [e for e in entries if e["kind"] == "replay"]
            if not replays:
                self._dim("no replay recorded yet — /replay first")
                return
            entry = replays[-1]

        body = Text()
        body.append("run_id     ", style="bold")
        body.append(f"{entry['run_id']}\n")
        body.append("kind       ", style="bold")
        body.append(entry["kind"])
        if entry.get("parent_run_id"):
            body.append(f"  (replayed {entry['parent_run_id']})")
        body.append("\n")
        body.append("started_at ", style="bold")
        body.append(f"{entry['started_at']}\n")
        body.append("adapter    ", style="bold")
        body.append(f"{entry['adapter']}  ·  model: {entry['model']}\n")
        body.append("campaign   ", style="bold")
        body.append(f"{entry['campaign_id']}\n")
        body.append("refinement ", style="bold")
        body.append(f"{entry.get('refinement') or '—'}\n")
        if entry.get("report"):
            verdict = (
                "✓ all passed"
                if entry["report"]["all_passed"]
                else f"✗ failing: {', '.join(entry['report']['failing'])}"
            )
            body.append("validator  ", style="bold")
            body.append(verdict, style=(
                "green" if entry["report"]["all_passed"] else "bold red"
            ))
            body.append("\n")
        body.append("files      ", style="bold")
        for key, value in entry.get("files", {}).items():
            body.append(f"\n  {key:<11} {value}", style="dim")
        self._panel(body, f"run log · {entry['run_id']}")

        provenance_path = entry.get("files", {}).get("provenance")
        if provenance_path and Path(provenance_path).exists():
            raw = Path(provenance_path).read_text(encoding="utf-8")
            self._panel(
                Text(raw, style="dim"),
                f"provenance · {provenance_path}",
                border=PURPLE_SOFT,
            )
        else:
            self._dim("provenance log not found for this run")

    def cmd_send(self, arg: str) -> None:
        from generator_agent.send import send_campaign

        campaign_path = self.last_paths.get("campaign")
        if campaign_path is None or not Path(campaign_path).exists():
            self._dim("nothing to send — run /generate first")
            return
        if self.last_recipient is None:
            self._dim("no recipient recorded — run /generate first")
            return
        to_addr = self.last_recipient["recipient"]["email"]
        with self.console.status(
            f"[{PURPLE_BRIGHT}]sending to the MailHog sink…[/{PURPLE_BRIGHT}]"
        ):
            try:
                n = send_campaign(str(campaign_path), to_addr, "localhost", 1025)
            except ConnectionRefusedError:
                self._err("no SMTP sink — start it with: docker compose up -d")
                return
        self.console.print(
            Text(f"delivered {n} messages to {to_addr}", style="green") +
            Text("  — open http://localhost:8025", style="dim")
        )

    def cmd_status(self, arg: str) -> None:
        self._render_config()
        if self.last_campaign is None:
            self._dim("last run: none yet — /generate to create one")
            return
        body = Text()
        body.append("campaign   ", style="bold")
        body.append(self.last_campaign.campaign_id + "\n")
        if self.last_run:
            body.append("run        ", style="bold")
            run_desc = f"{self.last_run['run_id']} ({self.last_run['kind']})"
            if self.last_run.get("parent_run_id"):
                run_desc += f", replayed {self.last_run['parent_run_id']}"
            body.append(run_desc + "\n")
        failing = [r.check.value for r in self.last_report.results if not r.passed]
        body.append("all_passed ", style="bold")
        verdict = "✓ True" if self.last_report.all_passed else "✗ False"
        body.append(verdict + "\n", style="green" if self.last_report.all_passed
                    else "bold red")
        body.append("failing    ", style="bold")
        body.append(", ".join(failing) if failing else "none")
        if self.last_paths.get("campaign"):
            body.append("\nfiles      ", style="bold")
            body.append(str(self.last_paths["campaign"]) + "\n           ")
            body.append(str(self.last_paths["report"]))
        self._panel(body, "last run")

    def cmd_quit(self, arg: str) -> bool:
        self.console.print(Text("bye.", style=PURPLE_BRIGHT))
        return True

    cmd_exit = cmd_quit

    # ------------------------------------------------------------------ #
    # interactive loop (prompt_toolkit)
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        try:
            from prompt_toolkit import HTML, PromptSession
            from prompt_toolkit.completion import Completion, Completer
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.styles import Style
        except ImportError:
            print("install prompt_toolkit to run the interactive shell: "
                  "pip install prompt_toolkit rich")
            raise SystemExit(1)

        shell = self

        class ShellCompleter(Completer):
            def get_completions(self, document, complete_event):
                text = document.text_before_cursor.lstrip("/")
                parts = text.split()
                on_cmd = not text or text[-1] != " "
                if len(parts) == 0 or (len(parts) == 1 and on_cmd):
                    prefix = parts[0] if parts else ""
                    for name, desc in COMMANDS.items():
                        if name.startswith(prefix):
                            yield Completion(
                                f"/{name}", start_position=-len(prefix),
                                display_meta=desc,
                            )
                    return
                command, arg = parts[0], parts[1] if len(parts) > 1 else ""
                if command == "config" and len(parts) <= 2:
                    for key in sorted(shell.cfg) + ["reset"]:
                        if key.startswith(arg):
                            yield Completion(
                                key, start_position=-len(arg),
                                display_meta=f"{shell.cfg.get(key, 'defaults')}",
                            )
                elif command == "recipient":
                    from generator_agent.catalog import load_catalog

                    for p in load_catalog():
                        pid = str(p["id"])
                        if pid.startswith(arg):
                            yield Completion(
                                pid, start_position=-len(arg),
                                display_meta=p["display_name"],
                            )
                elif command == "model":
                    completions = list(KNOWN_MODELS) + [
                        f"ollama/{name}" for name in cfg_mod.ollama_models()
                    ]
                    for m in completions:
                        if m.startswith(arg):
                            yield Completion(m, start_position=-len(arg))

        history_path = cfg_mod.config_path().parent / "history"
        history_path.parent.mkdir(parents=True, exist_ok=True)

        self._banner()
        session = PromptSession(
            history=FileHistory(str(history_path)),
            completer=ShellCompleter(),
            style=Style.from_dict(_PROMPT_STYLE),
        )

        while True:
            model = self.cfg["model"]
            adapter = self.cfg["adapter"]
            seed = self.cfg["seed"]
            prompt_html = HTML(
                f"<prompt>phishcraft</prompt>"
                f"<prompt.dim> · {model} · {adapter} · seed {seed}</prompt.dim> &gt; "
            )
            recipient = self.cfg["recipient_id"] or "default recipient"
            toolbar = HTML(
                f"<bottom-toolbar>{self.cfg['pretext']} / "
                f"{self.cfg['tone']} / {self.cfg['difficulty']} · "
                f"{recipient} · /help</bottom-toolbar>"
            )
            try:
                line = session.prompt(prompt_html, bottom_toolbar=lambda: toolbar)
            except KeyboardInterrupt:
                continue
            except EOFError:
                self.console.print()
                break
            if self.dispatch(line):
                break


def main() -> None:
    try:
        PtShell().run()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
