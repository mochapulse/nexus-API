"""Tests for api.mc.service: systemctl is-active/restart wrappers.

``subprocess.run`` is always patched: this suite must never invoke a
real ``systemctl`` command.
"""

import subprocess
from unittest.mock import MagicMock, patch

from api.mc import service


class TestIsActive:
    def test_returns_stripped_stdout(self):
        completed = MagicMock(stdout="active\n")
        with patch.object(service.subprocess, "run", return_value=completed) as run:
            result = service.is_active("mc-server-create")

        assert result == "active"
        run.assert_called_once()
        args, kwargs = run.call_args
        assert args[0] == ["systemctl", "is-active", "mc-server-create"]
        assert kwargs["timeout"] == 10

    def test_reports_failed_state(self):
        completed = MagicMock(stdout="failed\n")
        with patch.object(service.subprocess, "run", return_value=completed):
            assert service.is_active("mc-server-create") == "failed"

    def test_empty_stdout_returns_unknown(self):
        completed = MagicMock(stdout="")
        with patch.object(service.subprocess, "run", return_value=completed):
            assert service.is_active("mc-server-create") == "unknown"

    def test_timeout_returns_unknown(self):
        with patch.object(
            service.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="systemctl", timeout=10),
        ):
            assert service.is_active("mc-server-create") == "unknown"

    def test_os_error_returns_unknown(self):
        with patch.object(service.subprocess, "run", side_effect=OSError("no exec")):
            assert service.is_active("mc-server-create") == "unknown"


class TestRestart:
    def test_success_returns_none(self):
        with patch.object(service.subprocess, "run", return_value=MagicMock()) as run:
            result = service.restart("mc-server-create")

        assert result is None
        args, kwargs = run.call_args
        assert args[0] == [
            "systemctl",
            "restart",
            "mc-server-create",
            "--no-ask-password",
        ]
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 60

    def test_called_process_error_returns_stderr(self):
        error = subprocess.CalledProcessError(
            returncode=1, cmd="systemctl", stderr="unit not found\n"
        )
        with patch.object(service.subprocess, "run", side_effect=error):
            result = service.restart("mc-server-create")

        assert result == "unit not found"

    def test_called_process_error_without_stderr_falls_back_to_str(self):
        error = subprocess.CalledProcessError(returncode=1, cmd="systemctl", stderr=None)
        with patch.object(service.subprocess, "run", side_effect=error):
            result = service.restart("mc-server-create")

        assert result == str(error)

    def test_timeout_returns_message(self):
        error = subprocess.TimeoutExpired(cmd="systemctl", timeout=60)
        with patch.object(service.subprocess, "run", side_effect=error):
            result = service.restart("mc-server-create")

        assert result == str(error)

    def test_os_error_returns_message(self):
        with patch.object(service.subprocess, "run", side_effect=OSError("no exec")):
            result = service.restart("mc-server-create")

        assert result == "no exec"
