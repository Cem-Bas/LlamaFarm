#!/usr/bin/env python3
"""Ollama Worker Agent — runs inside a PTY, uses Ollama to think and execute commands.

This is the equivalent of 'codex' but powered by Ollama models.
It runs inside each worker's terminal so the user can see:
- The model's thinking
- Commands being executed
- Results and output

Usage:
    python worker_agent.py --model qwen3-coder:30b --goal "Your goal here"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import re

from ollama import chat

# Safety — block destructive commands
_DANGEROUS_PATTERNS = [
    re.compile(r'\brm\s+-(r|f|rf|fr)', re.IGNORECASE),
    re.compile(r'\brm\b.*\*'),
    re.compile(r'\bmkfs\b'),
    re.compile(r'\bdd\b\s+if='),
    re.compile(r'>\s*/dev/sd'),
    re.compile(r'\bsudo\b'),
    re.compile(r'\bchmod\s+777'),
    re.compile(r'\bcurl\b.*\|\s*(ba)?sh'),
    re.compile(r'\bwget\b.*\|\s*(ba)?sh'),
    re.compile(r'\b:()\s*\{'),
    re.compile(r'/etc/passwd'),
    re.compile(r'/etc/shadow'),
    re.compile(r'\bshutdown\b'),
    re.compile(r'\breboot\b'),
    re.compile(r'\bkill\s+-9\b'),
    re.compile(r'\bkillall\b'),
    re.compile(r'\bxargs\b.*\brm\b'),
]

_BLOCKED_CMDS = {"codex", "gemini", "claude", "ollama", "chatgpt", "gpt"}


def _is_safe_command(cmd: str) -> bool:
    """Return False if the command is dangerous or runs an AI tool."""
    first_word = cmd.strip().split()[0].lower() if cmd.strip() else ""
    if first_word in _BLOCKED_CMDS:
        return False
    for pat in _DANGEROUS_PATTERNS:
        if pat.search(cmd):
            return False
    return True


AGENT_PROMPT = """\
You are an autonomous terminal agent on macOS with zsh.
You receive a goal and execute shell commands to accomplish it.
Respond with ONLY a JSON object. No markdown, no explanation.

Actions:
{"action": "run", "value": "<shell command>"}  — run a shell command
{"action": "done", "value": "<summary>"}       — goal accomplished
{"action": "think", "value": "<reasoning>"}    — think out loud, then act

Rules:
- Run real shell commands to accomplish the goal
- NEVER use rm, sudo, kill, shutdown, or destructive commands
- When done, use the "done" action
- Output ONLY JSON
"""


def run_agent(model: str, goal: str, max_steps: int = 20) -> None:
    print(f"\033[1;33m{'='*60}\033[0m")
    print(f"\033[1;33m  Ollama Agent — {model}\033[0m")
    print(f"\033[1;33m  Goal: {goal}\033[0m")
    print(f"\033[1;33m{'='*60}\033[0m")
    print()

    history: list[dict] = []
    system_prompt = AGENT_PROMPT + f"\nYour GOAL: {goal}\n"

    for step in range(1, max_steps + 1):
        print(f"\033[1;36m--- Step {step} ---\033[0m")

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        if not history:
            messages.append({"role": "user", "content": f"Goal: {goal}\nDecide your first action."})

        # Think
        print("\033[0;90mThinking...\033[0m")
        try:
            response = chat(
                model=model,
                messages=messages,
                format="json",
                options={"temperature": 0.1, "num_predict": 256, "num_ctx": 8192},
            )
            content = response.message.content
        except Exception as e:
            print(f"\033[1;31mOllama error: {e}\033[0m")
            break

        # Parse
        try:
            action = json.loads(content)
        except json.JSONDecodeError:
            print(f"\033[1;31mBad JSON: {content[:200]}\033[0m")
            action = {"action": "done", "value": "Failed to parse response"}

        act = action.get("action", "")
        val = action.get("value", "")

        if act == "think":
            print(f"\033[0;35m💭 {val}\033[0m")
            history.append({"role": "assistant", "content": content})
            history.append({"role": "user", "content": "Now execute an action."})
            continue

        elif act == "run":
            if not _is_safe_command(val):
                print(f"\033[1;31mBLOCKED: {val}\033[0m")
                history.append({"role": "assistant", "content": content})
                history.append({"role": "user", "content": "That command is blocked for safety. Try a different approach."})
                continue
            print(f"\033[1;32m$ {val}\033[0m")
            try:
                result = subprocess.run(
                    val, shell=True, capture_output=True, text=True, timeout=30,
                )
                output = result.stdout + result.stderr
                if output.strip():
                    print(output.rstrip())
                else:
                    print("\033[0;90m(no output)\033[0m")
                history.append({"role": "assistant", "content": content})
                history.append({"role": "user", "content": f"Command output:\n{output[:2000]}\nDecide next action."})
            except subprocess.TimeoutExpired:
                print("\033[1;31mCommand timed out\033[0m")
                history.append({"role": "assistant", "content": content})
                history.append({"role": "user", "content": "Command timed out. Decide next action."})

        elif act == "done":
            print(f"\033[1;33m✅ Done: {val}\033[0m")
            print()
            print(f"\033[1;33m{'='*60}\033[0m")
            print(f"\033[1;33m  Mission complete in {step} steps\033[0m")
            print(f"\033[1;33m{'='*60}\033[0m")
            break

        else:
            print(f"\033[0;90mUnknown action: {act}\033[0m")
            history.append({"role": "assistant", "content": content})
            history.append({"role": "user", "content": "Use run, think, or done actions. Decide next action."})

        print()

    else:
        print(f"\033[1;31mMax steps reached ({max_steps})\033[0m")

    # Keep the process alive so the PTY doesn't close
    print("\n\033[0;90mAgent finished. Idle.\033[0m")
    while True:
        try:
            import time
            time.sleep(60)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3-coder:30b")
    parser.add_argument("--goal", default="Await instructions")
    args = parser.parse_args()
    run_agent(args.model, args.goal)
