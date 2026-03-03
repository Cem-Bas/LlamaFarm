"""Tests for PTYManager — shell subprocess control via pseudo-terminal."""

import time

import pytest

from pty_manager import PTYManager


class TestPTYManagerInit:
    """Tests for PTYManager construction."""

    def test_default_params(self):
        mgr = PTYManager()
        assert mgr._process is None
        assert mgr._shell == "/bin/bash"
        assert mgr._cols == 120
        assert mgr._rows == 40

    def test_custom_params(self):
        mgr = PTYManager(shell="/bin/sh", cols=80, rows=24)
        assert mgr._shell == "/bin/sh"
        assert mgr._cols == 80
        assert mgr._rows == 24


class TestPTYManagerSpawn:
    """Tests for spawning the shell process."""

    def test_spawn_creates_process(self):
        mgr = PTYManager()
        mgr.spawn()
        try:
            assert mgr._process is not None
            assert mgr.is_alive()
        finally:
            mgr.close()

    def test_spawn_sets_term_env(self):
        mgr = PTYManager()
        mgr.spawn()
        time.sleep(0.3)
        try:
            mgr.write(b"echo $TERM\n")
            time.sleep(0.5)
            output = mgr.read(timeout=0.5)
            assert b"xterm-256color" in output
        finally:
            mgr.close()


class TestPTYManagerRead:
    """Tests for reading from the PTY."""

    def test_read_returns_bytes(self):
        mgr = PTYManager()
        mgr.spawn()
        time.sleep(0.3)
        try:
            mgr.write(b"echo hello_pty_test\n")
            time.sleep(0.5)
            output = mgr.read(timeout=0.5)
            assert isinstance(output, bytes)
            assert b"hello_pty_test" in output
        finally:
            mgr.close()

    def test_read_returns_empty_when_nothing_available(self):
        mgr = PTYManager()
        mgr.spawn()
        time.sleep(0.3)
        try:
            # Drain any initial output (shell prompt, etc.)
            mgr.read(timeout=0.3)
            # Now read again — should be empty
            output = mgr.read(timeout=0.1)
            assert output == b""
        finally:
            mgr.close()

    def test_read_returns_empty_when_no_process(self):
        mgr = PTYManager()
        output = mgr.read(timeout=0.1)
        assert output == b""

    def test_read_drains_all_data(self):
        mgr = PTYManager()
        mgr.spawn()
        time.sleep(0.3)
        try:
            # Send a command that produces substantial output
            mgr.write(b"for i in $(seq 1 20); do echo line_$i; done\n")
            time.sleep(0.5)
            output = mgr.read(timeout=0.5)
            # Should contain first and last lines — proves draining
            assert b"line_1" in output
            assert b"line_20" in output
        finally:
            mgr.close()


class TestPTYManagerWrite:
    """Tests for writing to the PTY."""

    def test_write_noop_when_no_process(self):
        mgr = PTYManager()
        # Should not raise
        mgr.write(b"echo test\n")

    def test_write_sends_command(self):
        mgr = PTYManager()
        mgr.spawn()
        time.sleep(0.3)
        try:
            mgr.write(b"echo write_test_42\n")
            time.sleep(0.5)
            output = mgr.read(timeout=0.5)
            assert b"write_test_42" in output
        finally:
            mgr.close()


class TestPTYManagerResize:
    """Tests for resizing the PTY."""

    def test_resize_updates_terminal_size(self):
        mgr = PTYManager()
        mgr.spawn()
        time.sleep(0.3)
        try:
            mgr.resize(cols=60, rows=20)
            time.sleep(0.3)
            # Verify via stty that the terminal size changed
            mgr.write(b"stty size\n")
            time.sleep(0.5)
            output = mgr.read(timeout=0.5)
            assert b"20 60" in output
        finally:
            mgr.close()

    def test_resize_noop_when_no_process(self):
        mgr = PTYManager()
        # Should not raise
        mgr.resize(cols=80, rows=24)


class TestPTYManagerIsAlive:
    """Tests for checking if the process is alive."""

    def test_is_alive_false_when_no_process(self):
        mgr = PTYManager()
        assert mgr.is_alive() is False

    def test_is_alive_true_after_spawn(self):
        mgr = PTYManager()
        mgr.spawn()
        try:
            assert mgr.is_alive() is True
        finally:
            mgr.close()

    def test_is_alive_false_after_close(self):
        mgr = PTYManager()
        mgr.spawn()
        mgr.close()
        assert mgr.is_alive() is False


class TestPTYManagerClose:
    """Tests for closing the PTY process."""

    def test_close_terminates_process(self):
        mgr = PTYManager()
        mgr.spawn()
        mgr.close()
        assert mgr._process is None

    def test_close_noop_when_no_process(self):
        mgr = PTYManager()
        # Should not raise
        mgr.close()

    def test_close_allows_respawn(self):
        mgr = PTYManager()
        mgr.spawn()
        mgr.close()
        mgr.spawn()
        try:
            assert mgr.is_alive()
        finally:
            mgr.close()
