"""Tests for ollama_client — sends screen state to Ollama, receives action dicts."""

import json

import pytest
from unittest.mock import patch, MagicMock

from ollama_client import OllamaAgent, SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(content: str) -> MagicMock:
    """Build a mock ollama.chat return value with the given content string."""
    resp = MagicMock()
    resp.message.content = content
    return resp


# ---------------------------------------------------------------------------
# 1. decide() returns parsed action dict from valid JSON response
# ---------------------------------------------------------------------------

class TestDecideValidJSON:
    @patch("ollama_client.chat")
    def test_type_action(self, mock_chat):
        payload = {"action": "type", "value": "ls -la"}
        mock_chat.return_value = _mock_response(json.dumps(payload))

        agent = OllamaAgent(model="test-model")
        result = agent.decide("$ ")

        assert result == payload

    @patch("ollama_client.chat")
    def test_key_action(self, mock_chat):
        payload = {"action": "key", "value": "enter"}
        mock_chat.return_value = _mock_response(json.dumps(payload))

        agent = OllamaAgent(model="test-model")
        result = agent.decide("$ ls -la")

        assert result == payload

    @patch("ollama_client.chat")
    def test_keys_action(self, mock_chat):
        payload = {"action": "keys", "value": ["ctrl+c", "up", "enter"]}
        mock_chat.return_value = _mock_response(json.dumps(payload))

        agent = OllamaAgent(model="test-model")
        result = agent.decide("running process...")

        assert result == payload

    @patch("ollama_client.chat")
    def test_wait_action(self, mock_chat):
        payload = {"action": "wait", "value": 3}
        mock_chat.return_value = _mock_response(json.dumps(payload))

        agent = OllamaAgent(model="test-model")
        result = agent.decide("compiling...")

        assert result == payload


# ---------------------------------------------------------------------------
# 2. decide() sends screen text in user message
# ---------------------------------------------------------------------------

class TestDecideSendsScreenText:
    @patch("ollama_client.chat")
    def test_screen_text_in_user_message(self, mock_chat):
        mock_chat.return_value = _mock_response('{"action": "wait", "value": 1}')

        agent = OllamaAgent(model="test-model")
        agent.decide("user@host:~$ ")

        # The last message in the messages list should be the user message
        # containing the screen text.
        call_args = mock_chat.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][0]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "user@host:~$ " in user_msgs[-1]["content"]


# ---------------------------------------------------------------------------
# 3. decide() includes system prompt as first message
# ---------------------------------------------------------------------------

class TestDecideSystemPrompt:
    @patch("ollama_client.chat")
    def test_system_prompt_is_first(self, mock_chat):
        mock_chat.return_value = _mock_response('{"action": "wait", "value": 1}')

        agent = OllamaAgent(model="test-model")
        agent.decide("$ ")

        call_args = mock_chat.call_args
        messages = call_args[1]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == SYSTEM_PROMPT

    @patch("ollama_client.chat")
    def test_correct_model_passed(self, mock_chat):
        mock_chat.return_value = _mock_response('{"action": "wait", "value": 1}')

        agent = OllamaAgent(model="my-model")
        agent.decide("$ ")

        call_args = mock_chat.call_args
        assert call_args[1]["model"] == "my-model"


# ---------------------------------------------------------------------------
# 4. History accumulates across calls
# ---------------------------------------------------------------------------

class TestHistoryAccumulation:
    @patch("ollama_client.chat")
    def test_history_grows(self, mock_chat):
        mock_chat.return_value = _mock_response('{"action": "wait", "value": 1}')

        agent = OllamaAgent(model="test-model")
        agent.decide("screen1")
        agent.decide("screen2")

        # After 2 calls, history should have 4 entries (2 user + 2 assistant)
        assert len(agent._history) == 4

    @patch("ollama_client.chat")
    def test_history_included_in_messages(self, mock_chat):
        mock_chat.return_value = _mock_response('{"action": "wait", "value": 1}')

        agent = OllamaAgent(model="test-model")
        agent.decide("screen1")

        # Second call should include history from first call
        agent.decide("screen2")

        call_args = mock_chat.call_args
        messages = call_args[1]["messages"]
        # system + 2 history (user+assistant from call 1) + 1 current user = 4
        assert len(messages) == 4
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"
        assert messages[3]["role"] == "user"


# ---------------------------------------------------------------------------
# 5. History truncates when exceeding max_history
# ---------------------------------------------------------------------------

class TestHistoryTruncation:
    @patch("ollama_client.chat")
    def test_truncates_at_max_history(self, mock_chat):
        mock_chat.return_value = _mock_response('{"action": "wait", "value": 1}')

        max_h = 3
        agent = OllamaAgent(model="test-model", max_history=max_h)

        # Make more calls than max_history
        for i in range(5):
            agent.decide(f"screen{i}")

        # History should be trimmed to max_history pairs (user+assistant each)
        assert len(agent._history) == max_h * 2

    @patch("ollama_client.chat")
    def test_oldest_history_removed(self, mock_chat):
        responses = [
            _mock_response(json.dumps({"action": "type", "value": f"cmd{i}"}))
            for i in range(5)
        ]
        mock_chat.side_effect = responses

        agent = OllamaAgent(model="test-model", max_history=2)
        for i in range(5):
            agent.decide(f"screen{i}")

        # Only last 2 pairs should remain — history should NOT contain the
        # earliest entries.
        history_contents = [m["content"] for m in agent._history]
        assert "screen0" not in str(history_contents)
        assert "screen1" not in str(history_contents)
        assert "screen2" not in str(history_contents)


# ---------------------------------------------------------------------------
# 6. Malformed JSON falls back to wait action
# ---------------------------------------------------------------------------

class TestMalformedJSONFallback:
    @patch("ollama_client.chat")
    def test_garbage_string(self, mock_chat):
        mock_chat.return_value = _mock_response("this is not json at all")

        agent = OllamaAgent(model="test-model")
        result = agent.decide("$ ")

        assert result == {"action": "wait", "value": 2}

    @patch("ollama_client.chat")
    def test_empty_response(self, mock_chat):
        mock_chat.return_value = _mock_response("")

        agent = OllamaAgent(model="test-model")
        result = agent.decide("$ ")

        assert result == {"action": "wait", "value": 2}

    @patch("ollama_client.chat")
    def test_json_in_markdown_block(self, mock_chat):
        content = '```json\n{"action": "type", "value": "hello"}\n```'
        mock_chat.return_value = _mock_response(content)

        agent = OllamaAgent(model="test-model")
        result = agent.decide("$ ")

        # Should extract JSON from markdown code block
        assert result == {"action": "type", "value": "hello"}

    @patch("ollama_client.chat")
    def test_ollama_exception_falls_back(self, mock_chat):
        mock_chat.side_effect = Exception("connection refused")

        agent = OllamaAgent(model="test-model")
        result = agent.decide("$ ")

        assert result == {"action": "wait", "value": 2}

    @patch("ollama_client.chat")
    def test_partial_json(self, mock_chat):
        mock_chat.return_value = _mock_response('{"action": "type"')

        agent = OllamaAgent(model="test-model")
        result = agent.decide("$ ")

        assert result == {"action": "wait", "value": 2}


# ---------------------------------------------------------------------------
# 7. SYSTEM_PROMPT contains required keywords
# ---------------------------------------------------------------------------

class TestSystemPromptContent:
    def test_contains_type(self):
        assert "type" in SYSTEM_PROMPT

    def test_contains_key(self):
        assert "key" in SYSTEM_PROMPT

    def test_contains_keys(self):
        assert "keys" in SYSTEM_PROMPT

    def test_contains_wait(self):
        assert "wait" in SYSTEM_PROMPT

    def test_contains_json(self):
        assert "JSON" in SYSTEM_PROMPT

    def test_mentions_autonomous_agent(self):
        # System prompt should describe the agent's role
        assert "terminal" in SYSTEM_PROMPT.lower()

    def test_mentions_enter_after_typing(self):
        # Should instruct to send enter separately after typing
        assert "enter" in SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# 8. Chat call parameters
# ---------------------------------------------------------------------------

class TestChatCallParameters:
    @patch("ollama_client.chat")
    def test_format_json_passed(self, mock_chat):
        mock_chat.return_value = _mock_response('{"action": "wait", "value": 1}')

        agent = OllamaAgent(model="test-model")
        agent.decide("$ ")

        call_args = mock_chat.call_args
        assert call_args[1]["format"] == "json"

    @patch("ollama_client.chat")
    def test_options_passed(self, mock_chat):
        mock_chat.return_value = _mock_response('{"action": "wait", "value": 1}')

        agent = OllamaAgent(model="test-model")
        agent.decide("$ ")

        call_args = mock_chat.call_args
        options = call_args[1]["options"]
        assert options["temperature"] == 0.1
        assert options["num_predict"] == 256
