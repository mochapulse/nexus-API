"""Tests for the ``nexus-API mc-server`` CLI subcommand.

Covers the ``mc-server active|disable|status`` argument parser (accepted
forms, rejected forms) and ``cmd_mc_server`` (DEBUG never sends a real
request; production builds the right request and formats the response).
No real HTTP call is ever made — ``nexus_post``/``nexus_get``/
``nexus_delete`` are always mocked.
"""

from unittest.mock import MagicMock

import pytest

import api.config.runtime as runtime
from api.cli import build_parser
from api.cli.commands import cmd_health, cmd_mc_server


class TestMcServerParser:
    """Argument parsing for ``mc-server active|disable|status``."""

    def test_active_with_duration_only(self):
        args = build_parser().parse_args(["mc-server", "active", "5h"])
        assert args.mc_command == "active"
        assert args.duration == "5h"
        assert args.extra == []

    def test_active_with_threshold(self):
        args = build_parser().parse_args(
            ["mc-server", "active", "5h", "threshold", "10m"]
        )
        assert args.duration == "5h"
        assert args.extra == ["threshold", "10m"]

    def test_active_with_compound_duration(self):
        args = build_parser().parse_args(["mc-server", "active", "1h-30m"])
        assert args.duration == "1h-30m"
        assert args.extra == []

    def test_disable(self):
        args = build_parser().parse_args(["mc-server", "disable"])
        assert args.mc_command == "disable"

    def test_status(self):
        args = build_parser().parse_args(["mc-server", "status"])
        assert args.mc_command == "status"

    def test_no_subcommand_parses(self):
        args = build_parser().parse_args(["mc-server"])
        assert args.mc_command is None
        assert args.mc_parser is not None

    def test_active_without_duration_rejected(self):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["mc-server", "active"])
        assert exc.value.code == 2

    def test_active_threshold_without_value_rejected(self):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["mc-server", "active", "5h", "threshold"])
        assert exc.value.code == 2

    def test_active_bad_keyword_rejected(self):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["mc-server", "active", "5h", "foo", "10m"])
        assert exc.value.code == 2

    def test_active_too_many_extra_tokens_rejected(self):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(
                ["mc-server", "active", "5h", "threshold", "10m", "extra"]
            )
        assert exc.value.code == 2


class TestDispatchPassesArgs:
    """Every handler shares the ``handler(args: Namespace) -> None`` signature."""

    def test_all_handlers_accept_the_same_args_namespace(self, monkeypatch):
        """main() calls every handler as ``handler(args)`` uniformly (no more
        telemetry-only special case); each handler must accept one
        positional ``args.Namespace`` without raising ``TypeError``.
        """
        monkeypatch.setattr("api.cli.commands.nexus_get", MagicMock())
        args = build_parser().parse_args(["health"])
        # A TypeError here would mean the handler still has the old
        # zero-argument signature.
        try:
            cmd_health(args)
        except SystemExit:
            pass

        args = build_parser().parse_args(["mc-server", "status"])
        monkeypatch.setattr(runtime, "DEBUG", True)
        cmd_mc_server(args)  # no TypeError, no HTTP call in DEBUG


class TestCmdMcServerDebug:
    """DEBUG mode must never call the HTTP helpers."""

    def _patch_http(self, monkeypatch):
        post, get, delete = MagicMock(), MagicMock(), MagicMock()
        monkeypatch.setattr("api.cli.commands.nexus_post", post)
        monkeypatch.setattr("api.cli.commands.nexus_get", get)
        monkeypatch.setattr("api.cli.commands.nexus_delete", delete)
        return post, get, delete

    def test_active_debug_sends_no_request(self, monkeypatch, capsys):
        monkeypatch.setattr(runtime, "DEBUG", True)
        post, get, delete = self._patch_http(monkeypatch)

        args = build_parser().parse_args(
            ["mc-server", "active", "5h", "threshold", "10m"]
        )
        cmd_mc_server(args)

        post.assert_not_called()
        get.assert_not_called()
        delete.assert_not_called()
        out = capsys.readouterr().out
        assert "[DEBUG] No request sent." in out
        assert "active_seconds" in out
        assert "Armed:" in out

    def test_disable_debug_sends_no_request(self, monkeypatch, capsys):
        monkeypatch.setattr(runtime, "DEBUG", True)
        post, get, delete = self._patch_http(monkeypatch)

        args = build_parser().parse_args(["mc-server", "disable"])
        cmd_mc_server(args)

        post.assert_not_called()
        get.assert_not_called()
        delete.assert_not_called()
        out = capsys.readouterr().out
        assert "[DEBUG] No request sent." in out
        assert "Armed:" in out

    def test_status_debug_sends_no_request(self, monkeypatch, capsys):
        monkeypatch.setattr(runtime, "DEBUG", True)
        post, get, delete = self._patch_http(monkeypatch)

        args = build_parser().parse_args(["mc-server", "status"])
        cmd_mc_server(args)

        post.assert_not_called()
        get.assert_not_called()
        delete.assert_not_called()
        out = capsys.readouterr().out
        assert "[DEBUG] No request sent." in out
        assert "Armed:" in out


class TestCmdMcServerProduction:
    """Production paths build the right requests and format responses."""

    def test_active_sends_active_seconds_only_when_no_threshold(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(runtime, "DEBUG", False)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "armed": True,
            "deadline": "2026-09-24T04:00:00Z",
            "remaining_seconds": 18000,
            "threshold_seconds": 1800,
            "empty_seconds": None,
            "players_online": None,
            "mc_reachable": False,
            "restarts_used": 0,
            "max_restarts": 3,
            "last_disarm_reason": None,
        }
        post = MagicMock(return_value=resp)
        monkeypatch.setattr("api.cli.commands.nexus_post", post)

        args = build_parser().parse_args(["mc-server", "active", "5h"])
        cmd_mc_server(args)

        post.assert_called_once_with(
            "mc-server/watchdog", json={"active_seconds": 18000}
        )
        out = capsys.readouterr().out
        assert "Armed:" in out
        assert "unreachable" in out

    def test_active_sends_threshold_when_given(self, monkeypatch):
        monkeypatch.setattr(runtime, "DEBUG", False)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "armed": True,
            "deadline": "2026-09-24T04:00:00Z",
            "remaining_seconds": 18000,
            "threshold_seconds": 600,
            "empty_seconds": None,
            "players_online": None,
            "mc_reachable": False,
            "restarts_used": 0,
            "max_restarts": 3,
            "last_disarm_reason": None,
        }
        post = MagicMock(return_value=resp)
        monkeypatch.setattr("api.cli.commands.nexus_post", post)

        args = build_parser().parse_args(
            ["mc-server", "active", "5h", "threshold", "10m"]
        )
        cmd_mc_server(args)

        post.assert_called_once_with(
            "mc-server/watchdog",
            json={"active_seconds": 18000, "threshold_seconds": 600},
        )

    def test_disable_sends_delete(self, monkeypatch, capsys):
        monkeypatch.setattr(runtime, "DEBUG", False)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "armed": False,
            "deadline": None,
            "remaining_seconds": 0,
            "threshold_seconds": 1800,
            "empty_seconds": None,
            "players_online": None,
            "mc_reachable": False,
            "restarts_used": 0,
            "max_restarts": 3,
            "last_disarm_reason": "manual",
        }
        delete = MagicMock(return_value=resp)
        monkeypatch.setattr("api.cli.commands.nexus_delete", delete)

        args = build_parser().parse_args(["mc-server", "disable"])
        cmd_mc_server(args)

        delete.assert_called_once_with("mc-server/watchdog")
        out = capsys.readouterr().out
        assert "Armed:" in out
        assert "manual" in out

    def test_status_sends_get_and_prints_fields(self, monkeypatch, capsys):
        monkeypatch.setattr(runtime, "DEBUG", False)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "armed": True,
            "deadline": "2026-09-23T23:00:00Z",
            "remaining_seconds": 17820,
            "threshold_seconds": 1800,
            "empty_seconds": 120,
            "players_online": 0,
            "mc_reachable": True,
            "restarts_used": 0,
            "max_restarts": 3,
            "last_disarm_reason": None,
        }
        get = MagicMock(return_value=resp)
        monkeypatch.setattr("api.cli.commands.nexus_get", get)

        args = build_parser().parse_args(["mc-server", "status"])
        cmd_mc_server(args)

        get.assert_called_once_with("mc-server/watchdog")
        out = capsys.readouterr().out
        for field in (
            "Armed:",
            "Remaining:",
            "Deadline:",
            "Threshold:",
            "Empty for:",
            "Players online:",
            "MC reachable:",
            "Restarts:",
            "Last disarm reason:",
        ):
            assert field in out

    def test_invalid_duration_exits_1(self, monkeypatch, capsys):
        monkeypatch.setattr(runtime, "DEBUG", False)

        args = build_parser().parse_args(["mc-server", "active", "5x"])
        with pytest.raises(SystemExit) as exc:
            cmd_mc_server(args)

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Error" in err

    def test_non_2xx_exits_1(self, monkeypatch, capsys):
        monkeypatch.setattr(runtime, "DEBUG", False)
        resp = MagicMock()
        resp.status_code = 422
        resp.json.return_value = {
            "detail": [{"loc": ["body", "active_seconds"], "msg": "must be positive"}]
        }
        post = MagicMock(return_value=resp)
        monkeypatch.setattr("api.cli.commands.nexus_post", post)

        args = build_parser().parse_args(["mc-server", "active", "5h"])
        with pytest.raises(SystemExit) as exc:
            cmd_mc_server(args)

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "active_seconds" in err

    def test_network_error_exits_1(self, monkeypatch, capsys):
        monkeypatch.setattr(runtime, "DEBUG", False)
        monkeypatch.setattr(
            "api.cli.commands.nexus_get",
            MagicMock(side_effect=ConnectionError("refused")),
        )

        args = build_parser().parse_args(["mc-server", "status"])
        with pytest.raises(SystemExit) as exc:
            cmd_mc_server(args)

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Error" in err

    def test_no_subcommand_prints_help_and_exits_1(self, capsys):
        args = build_parser().parse_args(["mc-server"])
        with pytest.raises(SystemExit) as exc:
            cmd_mc_server(args)

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "mc-server" in out
