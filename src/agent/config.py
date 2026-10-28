"""Config for the ADK pipeline. No secrets here — env (or gitignored .env) only."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_env_file() -> None:
    """Load the gitignored repo .env into the environment if present."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

DEFAULT_MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")

# The self-refinement critic: a reasoning model better at turning precise
# deterministic findings into corrective instructions than the generalist
# generator. Falls back to the generator model when missing (offline).
DEFAULT_CRITIC_MODEL = "ollama/deepseek-r1:7b"


def resolve_model():
    """Model object from config/env. Never hardcode a provider at a call site."""
    if DEFAULT_MODEL.startswith("deepseek/") or DEFAULT_MODEL.startswith("ollama/"):
        # OpenAI-compatible providers via ADK's LiteLLM wrapper: the DeepSeek
        # key is read by litellm from DEEPSEEK_API_KEY; Ollama models are
        # served locally by the Ollama daemon (http://localhost:11434).
        from google.adk.models.lite_llm import LiteLlm

        if DEFAULT_MODEL.startswith("ollama/"):
            # Keep Ollama's thinking field visible to the trace (see
            # agent.model_trace). No-op unless ADK_MODEL_TRACE_FILE is set.
            from agent.model_trace import install_ollama_thinking_shim

            install_ollama_thinking_shim()
        return LiteLlm(model=DEFAULT_MODEL, temperature=0.0)
    return DEFAULT_MODEL  # Gemini model id, key from GOOGLE_API_KEY


def resolve_critic_model():
    """The model that writes the self-refinement critique.

    Defaults to ``DEFAULT_CRITIC_MODEL`` (a reasoning model better at
    structured criticism than the generalist generator); ``ADK_CRITIC_MODEL``
    overrides it. If the critic is a local ``ollama/`` model that has not been
    pulled yet, fall back to the generator model so the loop keeps working
    offline rather than failing on a missing model.
    """
    critic = os.getenv("ADK_CRITIC_MODEL", DEFAULT_CRITIC_MODEL)
    if critic.startswith("ollama/"):
        name = critic[len("ollama/"):]
        if not _ollama_has(name):
            return resolve_model()
    if critic.startswith("deepseek/") or critic.startswith("ollama/"):
        from google.adk.models.lite_llm import LiteLlm

        if critic.startswith("ollama/"):
            from agent.model_trace import install_ollama_thinking_shim

            install_ollama_thinking_shim()
        return LiteLlm(model=critic, temperature=0.0)
    return critic


def _ollama_has(name: str) -> bool:
    """True when ``name`` is in the local Ollama model list (best-effort)."""
    import subprocess

    try:
        out = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    for line in out.splitlines()[1:]:
        fields = line.split()
        if fields and fields[0] == name:
            return True
    return False
