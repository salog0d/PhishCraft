"""Config for the ADK pipeline. No secrets here — env (or gitignored .env) only."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


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
