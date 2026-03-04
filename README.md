<p align="center">
  <img src="web/logo.png" width="200" />
  <h1 align="center">LlamaFarm</h1>
</p>
<p align="center">
  <strong>AI agent swarm with an isometric pixel-art farm.</strong><br>
  One King. Eight llamas. Infinite chaos.
</p>
<p align="center">
  <a href="https://youtu.be/upiNgGM6HI4">Demo</a> &middot;
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#how-it-works">How It Works</a> &middot;
  <a href="#supported-backends">Backends</a>
</p>
<p align="center">
  <a href="https://youtu.be/upiNgGM6HI4">
    <img src="https://img.youtube.com/vi/upiNgGM6HI4/maxresdefault.jpg" width="720" alt="LlamaFarm Demo Video" />
  </a>
</p>
<p align="center"><em>Click to watch the demo</em></p>

---

## What is this?

LlamaFarm is a multi-agent orchestration system where a **Llama King** (AI orchestrator) commands a swarm of **worker llamas** — each running a real AI agent inside its own pseudo-terminal. You watch them work on a pixel-art isometric farm, chat with the King, and control everything from a browser.

Give the King a mission. It spawns workers. Workers run commands. You watch llamas roam.

```
You: "Open x.com in the browser"

Llama King: *spawns LLAMA-01*
LLAMA-01:   *thinks* → open https://x.com → *done*
Llama King: "Successfully opened x.com using a llama agent."
```

## How It Works

```
                    ┌──────────────────┐
           ╔═══════╡   LLAMA  KING    ╞═══════╗
           ║       │   (Orchestrator)  │       ║
           ║       └──────────────────┘       ║
           ║  Reads status → Issues commands   ║
           ║    spawn / assign / kill / wait    ║
           ╠══════════╦═══════════╦════════════╣
      ┌────╨────┐┌────╨────┐┌────╨────┐
      │LLAMA-01 ││LLAMA-02 ││LLAMA-03 │  ...up to 8
      │ Ollama  ││ Claude  ││ Gemini  │
      │  PTY    ││  PTY    ││  PTY    │
      └─────────┘└─────────┘└─────────┘
       Each worker runs an AI agent in
       its own terminal, visible in the UI
```

**The loop:**

1. **King reads** swarm status (worker screens, goals, ages)
2. **King decides** — outputs a single JSON command
3. **System executes** — spawns/kills/assigns workers
4. **Workers act** — each AI agent runs autonomously in its PTY
5. **UI updates** — farm animates, consoles stream, chat flows
6. **Repeat** every tick

## Supported Backends

| Backend | How it runs | Best for |
|---------|------------|----------|
| **Ollama** (any model) | `worker_agent.py` in PTY — think/run/done loop | Local models, full visibility |
| **Claude CLI** | `claude -p` print mode, non-interactive | Fast autonomous tasks |
| **Codex CLI** | `codex exec` subprocess | Code-focused tasks |
| **Gemini CLI** | Gemini in a pseudo-terminal | Google model access |

Mix and match. The King can be Ollama while workers run Claude. Or all Gemini. Whatever you want.

## Quick Start

### Prerequisites

- **Python 3.10+**
- **Ollama** running locally — `ollama serve`
- A pulled model — `ollama pull qwen3-coder:30b`
- *(Optional)* [Claude CLI](https://docs.anthropic.com/en/docs/claude-code), [Codex CLI](https://github.com/openai/codex), or [Gemini CLI](https://github.com/google-gemini/gemini-cli)

### Install

```bash
git clone https://github.com/Cem-Bas/LlamaFarm.git
cd LlamaFarm
pip install -r requirements.txt
```

### Run

```bash
# Swarm mode — launch the farm with a mission
python swarm.py --goal "Open x.com in the browser"

# Swarm mode — idle, control everything from the UI
python swarm.py

# Single agent mode
python agent.py --model qwen3-coder:30b --goal "List all Python files"
```

Open **http://localhost:8765/swarm** and watch the llamas work.

### Options

```
python swarm.py [flags]

  --goal TEXT                Mission for the Llama King
  --orchestrator-model STR  King's brain (default: qwen3-coder:30b)
  --worker-model STR        Default worker brain (default: qwen3-coder:30b)
  --max-workers INT         Max concurrent llamas (default: 8)
  --port INT                Web UI port (default: 8765)
```

## The UI

| Feature | Description |
|---------|-------------|
| **Farm View** | Isometric pixel-art farm. Llamas roam, fences surround, the King watches from above. |
| **Console View** | Live terminal output for every agent. Toggle with the Console button. |
| **Chat Panel** | Talk to the Llama King. It replies while orchestrating workers. |
| **Quick Launch** | One-click spawn buttons for Claude, Codex, Gemini, and Ollama workers. |
| **Kill Switch** | Nuke everything. Kill all workers, reset the King. |
| **Mission Directive** | Set or change the King's mission on the fly. |
| **Model Selector** | Pick from all your Ollama models + CLI agents. |
| **Admin Panel** | Set default models, view swarm config. |

## Project Structure

```
LlamaFarm/
├── swarm.py              Swarm orchestrator — tick loop, worker lifecycle, dedup
├── agent.py              TerminalAgent — Observe-Think-Act loop + safety filters
├── worker_agent.py       Ollama worker agent — runs inside PTYs with think/run/done
├── ollama_client.py      Ollama API wrapper — conversation history, JSON parsing
├── cli_agent.py          CLI backends — Claude, Codex, Gemini subprocess/PTY adapters
├── gemini_client.py      Gemini-specific PTY client
├── pty_manager.py        Pseudo-terminal manager — spawn, read, write
├── screen.py             Virtual terminal screen buffer (pyte)
├── keystroke_engine.py   Action dict → raw PTY bytes encoder
├── config.py             Configuration constants
├── requirements.txt      Python dependencies
└── web/
    ├── server.py         FastAPI + WebSocket backend
    ├── swarm.html        Farm dashboard — the whole UI in one file
    ├── index.html        Single-agent terminal view
    ├── llama-farm.js     Isometric farm renderer + animations
    ├── logo.png          LlamaFarm logo
    ├── matrix.js         Matrix rain effect
    └── particles.js      Particle system
```

## Safety

Workers run real shell commands. LlamaFarm has multiple safety layers:

- **Command blocklist** — `rm -rf`, `sudo`, `mkfs`, `dd`, `shutdown`, fork bombs, and 16+ destructive patterns are caught and blocked before reaching the terminal
- **AI recursion guard** — workers cannot invoke `codex`, `claude`, `gemini`, or `ollama` as shell commands (no infinite agent loops)
- **Ctrl+C/Z blocked** — workers cannot interrupt or suspend processes
- **Spawn dedup** — the orchestrator cannot spam-spawn duplicate workers for the same goal
- **Localhost only** — web server binds to `127.0.0.1` by default

## Tech Stack

- **Python** — FastAPI, WebSockets, pyte (terminal emulation), ptyprocess
- **Ollama** — local LLM inference
- **Vanilla JS** — no frameworks, one HTML file, isometric renderer from scratch
- **Claude / Codex / Gemini CLIs** — pluggable AI backends

## Built By

**Cem Bas** — [@Cem-Bas](https://github.com/Cem-Bas)

Built with Ollama, Claude, Codex, Gemini, and mass of llamas.

## License

MIT
