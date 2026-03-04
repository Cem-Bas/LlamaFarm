"""Agent configuration."""

MODEL = "gemini-cli"
SCREEN_COLS = 120
SCREEN_ROWS = 40
SHELL = "/bin/zsh"
OLLAMA_HOST = "http://localhost:11434"
MAX_HISTORY = 20
OBSERVE_TIMEOUT = 0.1
WEB_HOST = "127.0.0.1"
WEB_PORT = 8765

# Swarm settings
MAX_WORKERS = 8
SWARM_BROADCAST_INTERVAL = 0.5  # seconds between UI broadcasts
ORCHESTRATOR_MODEL = "qwen3-coder:30b"  # default orchestrator
WORKER_MODEL = "qwen3-coder:30b"  # default worker model

# CLI agent names — use these as model names to activate CLI mode
# e.g. model="gemini-cli" or model="claude-cli" or model="codex-cli"
CLI_AGENT_NAMES = {"gemini-cli", "claude-cli", "codex-cli"}

def is_cli_agent(model: str) -> bool:
    """Check if a model name refers to a terminal CLI agent."""
    return model in CLI_AGENT_NAMES
