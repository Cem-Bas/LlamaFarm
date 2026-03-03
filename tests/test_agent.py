"""Tests for TerminalAgent — the observe-think-act agent loop."""

import time

import pytest
from unittest.mock import patch, MagicMock

from agent import TerminalAgent


@pytest.fixture
def agent():
    with patch("agent.OllamaAgent"):
        a = TerminalAgent(model="test", web_enabled=False)
        yield a


class TestTerminalAgentInit:
    """Tests for TerminalAgent construction."""

    @patch("agent.OllamaAgent")
    def test_default_construction(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        assert agent.running is False
        assert agent.iteration == 0
        assert agent.last_action is None
        assert agent.web_enabled is False

    @patch("agent.OllamaAgent")
    def test_components_created(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        assert agent.pty is not None
        assert agent.screen is not None
        assert agent.ollama is not None


class TestTerminalAgentStart:
    """Tests for starting the agent."""

    @patch("agent.OllamaAgent")
    def test_start_spawns_pty(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        try:
            assert agent.pty.is_alive()
            assert agent.running is True
        finally:
            agent.stop()

    @patch("agent.OllamaAgent")
    def test_start_sets_running_true(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        try:
            assert agent.running is True
        finally:
            agent.stop()


class TestTerminalAgentStop:
    """Tests for stopping the agent."""

    @patch("agent.OllamaAgent")
    def test_stop_closes_pty(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        agent.stop()
        assert not agent.pty.is_alive()

    @patch("agent.OllamaAgent")
    def test_stop_sets_running_false(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        agent.stop()
        assert agent.running is False

    @patch("agent.OllamaAgent")
    def test_stop_without_start(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        # Should not raise
        agent.stop()
        assert agent.running is False


class TestTerminalAgentObserve:
    """Tests for the observe step."""

    @patch("agent.OllamaAgent")
    def test_observe_returns_string(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        time.sleep(0.5)
        try:
            text = agent.observe()
            assert isinstance(text, str)
        finally:
            agent.stop()

    @patch("agent.OllamaAgent")
    def test_observe_captures_pty_output(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        time.sleep(0.3)
        try:
            agent.pty.write(b"echo observe_test_42\n")
            time.sleep(0.5)
            text = agent.observe()
            assert "observe_test_42" in text
        finally:
            agent.stop()


class TestTerminalAgentAct:
    """Tests for the act step."""

    @patch("agent.OllamaAgent")
    def test_act_type_writes_to_pty(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        time.sleep(0.3)
        try:
            agent.act({"action": "type", "value": "echo hi"})
            agent.act({"action": "key", "value": "enter"})
            time.sleep(0.5)
            text = agent.observe()
            assert "hi" in text
        finally:
            agent.stop()

    @patch("agent.OllamaAgent")
    def test_act_wait(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        try:
            start = time.time()
            agent.act({"action": "wait", "value": 0.1})
            elapsed = time.time() - start
            assert elapsed >= 0.08  # allow small tolerance
        finally:
            agent.stop()

    @patch("agent.OllamaAgent")
    def test_act_stores_last_action(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        try:
            action = {"action": "type", "value": "hello"}
            agent.act(action)
            assert agent.last_action == action
        finally:
            agent.stop()

    @patch("agent.OllamaAgent")
    def test_act_key(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        time.sleep(0.3)
        try:
            agent.act({"action": "key", "value": "enter"})
            # Should not raise
        finally:
            agent.stop()


class TestTerminalAgentThink:
    """Tests for the think step (mocked Ollama)."""

    @patch("agent.OllamaAgent")
    def test_think_calls_decide(self, mock_cls):
        mock_instance = mock_cls.return_value
        expected = {"action": "type", "value": "ls"}
        mock_instance.decide.return_value = expected

        agent = TerminalAgent(model="test", web_enabled=False)
        result = agent.think("$ ")
        assert result == expected
        mock_instance.decide.assert_called_once_with("$ ")

    @patch("agent.OllamaAgent")
    def test_think_returns_action_dict(self, mock_cls):
        mock_instance = mock_cls.return_value
        mock_instance.decide.return_value = {"action": "wait", "value": 2}

        agent = TerminalAgent(model="test", web_enabled=False)
        result = agent.think("some screen text")
        assert isinstance(result, dict)
        assert "action" in result


class TestTerminalAgentRunLoop:
    """Tests for the main run_loop method."""

    @patch("agent.OllamaAgent")
    def test_run_loop_increments_iteration(self, mock_cls):
        mock_instance = mock_cls.return_value

        def side_effect(screen_text):
            # Stop after first iteration — typing causes screen change
            # but we only need to verify iteration increments once
            agent.running = False
            return {"action": "type", "value": "x"}

        mock_instance.decide.side_effect = side_effect

        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        time.sleep(0.3)  # let shell prompt appear
        agent.run_loop()
        assert agent.iteration >= 1

    @patch("agent.OllamaAgent")
    def test_run_loop_stops_on_running_false(self, mock_cls):
        mock_instance = mock_cls.return_value
        mock_instance.decide.return_value = {"action": "wait", "value": 0.01}

        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        # Set running to False immediately so loop exits before first iteration
        agent.running = False
        agent.run_loop()
        # Agent should have stopped
        assert not agent.running

    @patch("agent.OllamaAgent")
    def test_run_loop_handles_exception(self, mock_cls):
        mock_instance = mock_cls.return_value

        def side_effect(screen_text):
            # Always stop — we just want to verify the exception is caught
            agent.running = False
            raise RuntimeError("test error")

        mock_instance.decide.side_effect = side_effect

        agent = TerminalAgent(model="test", web_enabled=False)
        agent.start()
        time.sleep(0.3)  # let shell prompt appear
        # Should not raise — errors are caught internally
        agent.run_loop()


class TestTerminalAgentBroadcast:
    """Tests for the _broadcast placeholder."""

    @patch("agent.OllamaAgent")
    def test_broadcast_is_noop(self, mock_cls):
        agent = TerminalAgent(model="test", web_enabled=False)
        # Should not raise, should be a no-op
        agent._broadcast("test", {"key": "value"})


# --- Snapshot tests ---

class TestGetSnapshot:
    """Tests for TerminalAgent.get_snapshot()."""

    def test_snapshot_returns_dict(self, agent):
        """get_snapshot returns a dict with required keys."""
        snap = agent.get_snapshot()
        assert isinstance(snap, dict)
        assert "agent_id" in snap
        assert "status" in snap
        assert "iteration" in snap
        assert "last_action" in snap
        assert "screen_text" in snap
        assert "goal" in snap

    def test_snapshot_default_values(self, agent):
        """Snapshot has correct defaults before any loop runs."""
        snap = agent.get_snapshot()
        assert snap["status"] == "idle"
        assert snap["iteration"] == 0
        assert snap["last_action"] is None
        assert snap["goal"] == ""

    def test_snapshot_reflects_agent_id(self):
        """Snapshot includes the agent_id set at construction."""
        with patch("agent.PTYManager"):
            with patch("agent.OllamaAgent"):
                a = TerminalAgent(agent_id="worker-03", web_enabled=False)
                snap = a.get_snapshot()
                assert snap["agent_id"] == "worker-03"

    def test_snapshot_reflects_iteration(self, agent):
        """Snapshot reflects current iteration count."""
        agent.iteration = 7
        snap = agent.get_snapshot()
        assert snap["iteration"] == 7

    def test_snapshot_reflects_last_action(self, agent):
        """Snapshot reflects last_action."""
        agent.last_action = {"action": "type", "value": "ls"}
        snap = agent.get_snapshot()
        assert snap["last_action"] == {"action": "type", "value": "ls"}

    def test_snapshot_reflects_goal(self):
        """Snapshot reflects goal set at construction."""
        with patch("agent.PTYManager"):
            with patch("agent.OllamaAgent"):
                a = TerminalAgent(agent_id="w1", goal="explore files", web_enabled=False)
                snap = a.get_snapshot()
                assert snap["goal"] == "explore files"

    def test_snapshot_screen_text_snippet(self, agent):
        """screen_text in snapshot is last 5 lines of screen."""
        agent.screen.feed(b"line1\r\nline2\r\nline3\r\nline4\r\nline5\r\nline6\r\nline7\r\n")
        snap = agent.get_snapshot()
        # Should contain the last 5 non-empty lines
        lines = [l for l in snap["screen_text"].split("\n") if l.strip()]
        assert len(lines) <= 5

    def test_snapshot_includes_status_field(self, agent):
        """Status transitions are reflected in snapshot."""
        agent.status = "thinking"
        snap = agent.get_snapshot()
        assert snap["status"] == "thinking"
