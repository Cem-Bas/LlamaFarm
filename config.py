"""Agent configuration."""

MODEL = "devstral-small-2"
SCREEN_COLS = 120
SCREEN_ROWS = 40
SHELL = "/bin/bash"
OLLAMA_HOST = "http://localhost:11434"
MAX_HISTORY = 20
OBSERVE_TIMEOUT = 0.1
WEB_HOST = "0.0.0.0"
WEB_PORT = 8765

# Swarm settings
MAX_WORKERS = 8
SWARM_BROADCAST_INTERVAL = 0.5  # seconds between UI broadcasts
ORCHESTRATOR_MODEL = "devstral-small-2"  # model for the orchestrator
WORKER_MODEL = "devstral-small-2"  # model for worker agents
