"""Interactive harness shell — a Claude-Code-style REPL over the generator.

    python -m ptshell

All commands work with or without the leading slash (``/generate`` or
``generate``). Settings persist to ``~/.pt-shell/config.json`` (override with
the ``PTSHELL_CONFIG`` env var) and can be changed in-session; model switches
take effect on the next generation.

Capabilities (commands) live as ``do_*`` methods on :class:`PtShell`; adding a
new capability = add a method + a ``COMMANDS`` row.
"""

from __future__ import annotations

import cmd
import json
import os
import shlex
import sys
from pathlib import Path

from ptshell import config as cfg_mod
from ptshell.config import KNOWN_MODELS, VALID_VALUES

REPO_ROOT = Path(__file__).resolve().parent.parent

COMMANDS: dict[str, str] = {
    "help": "show this command list (/help [command])",
    "config": "view or set settings (/config, /config <key> [value], /config reset)",
    "model": "set the generation model (/model <id>)",
    "models": "list known model ids",
    "recipients": "list the persona catalog (12 internal + 2 external)",
    "recipient": "set the default recipient (/recipient <id>)",
    "generate": "run the ADK pipeline once; save campaign + report",
    "validate": "run the 4 coherence checks on a campaign file",
    "measure": "run the 10-spec reliability suite (writes summary.md)",
    "reproduce": "run the same spec twice and compare (default: S1)",
    "send": "deliver the last generated campaign to MailHog",
    "status": "show current settings and the last run summary",
    "quit": "exit the shell (also /exit or Ctrl-D)",
}


class PtShell(cmd.Cmd):
    prompt = "pt> "

    def __init__(self, stdout=None, cfg_path: Path | None = None):
        super().__init__(stdout=stdout)
        if cfg_path is not None:
            os.environ["PTSHELL_CONFIG"] = str(cfg_path)
        self.cfg: dict = cfg_mod.load()
        self._active_model: str | None = None
        self.last_campaign = None
        self.last_report = None
        self.last_paths: dict[str, Path] = {}
        self.last_recipient: dict | None = None
        self.intro = self._banner()

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _paint(self, code: int, text: str) -> str:
        try:
            is_tty = self.stdout.isatty()
        except AttributeError:
            is_tty = False
        if not is_tty:
            return text
        return f"\033[{code}m{text}\033[0m"

    def _ok(self, text: str) -> str:
        return self._paint(32, text)

    def _warn(self, text: str) -> str:
        return self._paint(33, text)

    def _err(self, text: str) -> str:
        return self._paint(31, text)

    def _head(self, text: str) -> str:
        return self._paint(1, text)

    def _banner(self) -> str:
        recipient = self.cfg["recipient_id"] or "first non-executive"
        return "\n".join(
            [
                "",
                self._head("PT Shell — interactive harness for the phishing-campaign generator"),
                f"settings : {cfg_mod.config_path()}",
                f"model    : {self.cfg['model']} (adapter: {self.cfg['adapter']})",
                f"recipient: {recipient} · pretext: {self.cfg['pretext']} · "
                f"tone: {self.cfg['tone']} · seed: {self.cfg['seed']}",
                self._paint(2, "type /help for commands, /quit to exit"),
                "",
            ]
        )

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

    def _print_campaign(self, campaign, report) -> None:
        print(f"campaign : {campaign.campaign_id} — persona "
              f"{campaign.persona.display_name} <{campaign.persona.email}>")
        for m in campaign.messages:
            print(f"  {m.message_id} [{m.channel.value}] @ {m.scheduled_at}")
            print(f"    subject: {m.subject or '(sms)'}")
            print(f"    body   : {m.body[:120]}")
            print(f"    cta    : {m.call_to_action.landing_url}")
        print(self._head("validator report"))
        for r in report.results:
            mark = self._ok("PASS") if r.passed else self._err("FAIL")
            print(f"  [{mark}] {r.check.value}: {r.detail[:140]}")
        print(
            f"  all_passed: {self._ok('True') if report.all_passed else self._err('False')}"
        )

    def _print_config(self) -> None:
        for key in sorted(self.cfg):
            print(f"  {key:<18} = {self.cfg[key]}")

    # ------------------------------------------------------------------ #
    # cmd.Cmd plumbing
    # ------------------------------------------------------------------ #

    def precmd(self, line: str) -> str:
        return line.lstrip("/") if line.startswith("/") else line

    def emptyline(self) -> bool:
        return False

    def default(self, line: str) -> None:
        print(self._err(f"unknown command '{line}' — type /help for the list"))

    def do_EOF(self, arg: str) -> bool:
        print()
        return True

    def do_quit(self, arg: str) -> bool:
        print(self._ok("bye."))
        return True

    def do_exit(self, arg: str) -> bool:
        return self.do_quit(arg)

    # ------------------------------------------------------------------ #
    # commands
    # ------------------------------------------------------------------ #

    def do_help(self, arg: str) -> None:
        name = arg.strip()
        if name and name in COMMANDS:
            print(f"/{name} — {COMMANDS[name]}")
            return
        print(self._head("commands"))
        for key, desc in COMMANDS.items():
            print(f"  /{key:<11} {desc}")

    def do_config(self, arg: str) -> None:
        tokens = shlex.split(arg)
        if not tokens:
            print(self._head("settings") + f" (file: {cfg_mod.config_path()})")
            self._print_config()
            return
        if tokens[0] == "reset":
            cfg_mod.reset()
            self.cfg = cfg_mod.load()
            print(self._ok("settings reset to defaults"))
            return
        if len(tokens) == 1:
            key = tokens[0]
            if key not in self.cfg:
                print(self._err(f"unknown key '{key}'"))
                return
            print(f"{key} = {self.cfg[key]}")
            return
        if len(tokens) == 2:
            key, value = tokens
            error = cfg_mod.validate(key, value)
            if error:
                print(self._err(error))
                return
            self.cfg[key] = cfg_mod.coerce(key, value)
            self._save_cfg()
            print(self._ok(f"{key} = {self.cfg[key]}"))
            return
        print(self._warn("usage: /config [key [value]] | /config reset"))

    def complete_config(self, text, line, begidx, endidx):
        keys = sorted(self.cfg) + ["reset"]
        return [k for k in keys if k.startswith(text)]

    def do_model(self, arg: str) -> None:
        tokens = shlex.split(arg)
        if not tokens:
            print(f"model = {self.cfg['model']}")
            return
        model = tokens[0]
        self.cfg["model"] = model
        self._save_cfg()
        self._active_model = None
        print(self._ok(f"model = {model}") + self._paint(2, "  (applies to the next /generate)"))

    def complete_model(self, text, line, begidx, endidx):
        return [m for m in KNOWN_MODELS if m.startswith(text)]

    def do_models(self, arg: str) -> None:
        print(self._head("known model ids (LiteLlm format)"))
        for m in KNOWN_MODELS:
            marker = "  (current)" if m == self.cfg["model"] else ""
            print(f"  {m}{marker}")

    def do_recipients(self, arg: str) -> None:
        from generator_agent.catalog import load_catalog

        print(self._head("persona catalog"))
        print(f"  {'id':<16} {'class':<9} {'org_type':<9} name / role")
        for p in load_catalog():
            role = p["role"] or "—"
            print(
                f"  {str(p['id']):<16} {p['class']:<9} {str(p['org_type']):<9} "
                f"{p['display_name']} ({role})"
            )

    def do_recipient(self, arg: str) -> None:
        from generator_agent.catalog import load_catalog

        tokens = shlex.split(arg)
        if not tokens:
            print(f"recipient_id = {self.cfg['recipient_id'] or '(default: first non-executive)'}")
            return
        pid = tokens[0]
        catalog = load_catalog()
        if not any(str(p["id"]) == pid for p in catalog):
            print(self._err(f"no persona with id '{pid}' — see /recipients"))
            return
        self.cfg["recipient_id"] = pid
        self._save_cfg()
        who = next(p for p in catalog if str(p["id"]) == pid)
        print(self._ok(f"recipient = {pid} ({who['display_name']})"))

    def complete_recipient(self, text, line, begidx, endidx):
        from generator_agent.catalog import load_catalog

        return [str(p["id"]) for p in load_catalog()
                if str(p["id"]).startswith(text)]

    def do_generate(self, arg: str) -> None:
        try:
            mission = self._mission()
            spec = self._build_spec(mission)
            print(self._paint(2, f"generating with model={self.cfg['model']} "
                                 f"adapter={self.cfg['adapter']} ..."))
            self._apply_model()
            if self.cfg["adapter"] == "stub":
                from measurement.adapters import get_adapter

                campaign, report = get_adapter("stub").run(spec, mission)
            else:
                from agent.driver import run_pipeline

                campaign, report = run_pipeline(spec, mission)
        except Exception as exc:  # provider errors, validation, parse failures
            print(self._err(f"generation failed: {type(exc).__name__}: {exc}"))
            return

        out = Path(self.cfg["output_dir"]) / mission["campaign_id"]
        out.mkdir(parents=True, exist_ok=True)
        campaign_path = out / "generated_campaign.json"
        report_path = out / "coherence_report.json"
        campaign_path.write_text(campaign.model_dump_json(indent=2), encoding="utf-8")
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        from generator_agent.catalog import profile_for

        self.last_campaign = campaign
        self.last_report = report
        self.last_paths = {"campaign": campaign_path, "report": report_path}
        self.last_recipient = profile_for(spec["recipient_id"])

        self._print_campaign(campaign, report)
        print(self._paint(2, f"saved: {campaign_path}"))
        print(self._paint(2, f"saved: {report_path}"))

    def do_validate(self, arg: str) -> None:
        from app.core.schemas import GeneratedCampaign
        from validator_agent.validate import validate_campaign

        tokens = shlex.split(arg)
        path = Path(tokens[0]) if tokens else self.last_paths.get("campaign")
        if path is None:
            print(self._warn("nothing to validate — pass a path or run /generate first"))
            return
        if not Path(path).exists():
            print(self._err(f"no such file: {path}"))
            return
        try:
            campaign = GeneratedCampaign.model_validate_json(
                Path(path).read_text(encoding="utf-8")
            )
        except Exception as exc:
            print(self._err(f"not a valid GeneratedCampaign: {type(exc).__name__}: {exc}"))
            return
        report = validate_campaign(campaign)
        self._print_campaign(campaign, report)

    def do_measure(self, arg: str) -> None:
        from measurement.reliability import run as run_reliability

        tokens = shlex.split(arg)
        runs = 1
        for tok in tokens:
            if tok.startswith("--runs="):
                runs = int(tok.split("=", 1)[1])
        if self.cfg["adapter"] != "stub":
            self._apply_model()
        print(self._paint(2, f"reliability suite: adapter={self.cfg['adapter']} "
                             f"runs={runs} (10 specs, live LLM calls if adapter=adk)"))
        try:
            payload = run_reliability(adapter_name=self.cfg["adapter"], runs=runs)
        except Exception as exc:
            print(self._err(f"measure failed: {type(exc).__name__}: {exc}"))
            return
        print(self._head("result"))
        print(
            f"  campaigns with >= 1 violation: {payload['n_campaigns_with_violation']}"
            f"/{payload['n_runs'] - payload['n_generation_errors']} "
            f"(failure rate {payload['failure_rate']})"
        )
        for check, count in payload["violation_counts"].items():
            print(f"    {check:<24} {count}")
        print(self._paint(2, f"saved: {payload['out_dir']}"))

    def do_reproduce(self, arg: str) -> None:
        from measurement.reproduce import run as run_reproduce

        tokens = shlex.split(arg)
        spec_id = "S1" if "all" not in tokens else None
        if self.cfg["adapter"] != "stub":
            self._apply_model()
        print(self._paint(2, f"reproducibility: adapter={self.cfg['adapter']} "
                             f"spec={'all' if spec_id is None else spec_id} runs=2"))
        try:
            results = run_reproduce(
                spec_id=spec_id, runs=2, adapter_name=self.cfg["adapter"]
            )
        except Exception as exc:
            print(self._err(f"reproduce failed: {type(exc).__name__}: {exc}"))
            return
        for sid, res in results["specs"].items():
            verdict = (
                self._ok("identical")
                if res["identical"]
                else self._err("DIFFERENT")
            )
            layer = (
                self._ok("deterministic layer identical")
                if res["deterministic_layer_identical"]
                else self._err("deterministic layer DIFFERENT")
            )
            errors = sum(1 for r in res["runs"] if r["status"] != "ok")
            print(f"  {sid}: {verdict} · {layer} (errors={errors})")
        print(self._paint(2, f"saved: {results['out_dir']}"))

    def do_send(self, arg: str) -> None:
        from generator_agent.send import send_campaign

        campaign_path = self.last_paths.get("campaign")
        if campaign_path is None or not Path(campaign_path).exists():
            print(self._warn("nothing to send — run /generate first"))
            return
        if self.last_recipient is None:
            print(self._warn("no recipient recorded — run /generate first"))
            return
        to_addr = self.last_recipient["recipient"]["email"]
        try:
            n = send_campaign(str(campaign_path), to_addr, "localhost", 1025)
        except ConnectionRefusedError:
            print(self._err("no SMTP sink — start it with: docker compose up -d"))
            return
        print(self._ok(f"delivered {n} messages to {to_addr} — open http://localhost:8025"))

    def do_status(self, arg: str) -> None:
        print(self._head("settings") + f" (file: {cfg_mod.config_path()})")
        self._print_config()
        print()
        print(self._head("last run"))
        if self.last_campaign is None:
            print("  none yet — /generate to create one")
            return
        print(f"  campaign : {self.last_campaign.campaign_id}")
        print(f"  all_passed: {self.last_report.all_passed}")
        failing = [r.check.value for r in self.last_report.results if not r.passed]
        print(f"  failing : {failing or 'none'}")
        if self.last_paths.get("campaign"):
            print(f"  files   : {self.last_paths['campaign']}")
            print(f"            {self.last_paths['report']}")


def main() -> None:
    try:
        PtShell().cmdloop()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
