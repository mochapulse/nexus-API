"""Tests for api.lib.durations: parse_duration and format_duration."""

import pytest

from api.lib.durations import format_duration, parse_duration


class TestParseDurationValid:
    @pytest.mark.parametrize(
        "text,expected_seconds",
        [
            ("5h", 5 * 3600),
            ("10h", 10 * 3600),
            ("1h", 3600),
            ("30m", 30 * 60),
            ("1m", 60),
            ("1h-30m", 3600 + 30 * 60),
            ("1h30m", 3600 + 30 * 60),
            ("0h30m", 30 * 60),
            ("  5h  ", 5 * 3600),
            ("5H", 5 * 3600),
            ("1H-30M", 3600 + 30 * 60),
        ],
    )
    def test_parses_valid_formats(self, text, expected_seconds):
        assert parse_duration(text) == expected_seconds


class TestParseDurationInvalid:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "-",
            "1h-",
            "-30m",
            "0h",
            "0m",
            "0h0m",
            "0h-0m",
            "h",
            "m",
            "abc",
            "5",
            "5x",
            "5h5",
            "5 h",
            "1h--30m",
            "1h30",
        ],
    )
    def test_rejects_invalid_formats(self, text):
        with pytest.raises(ValueError, match="use formats like"):
            parse_duration(text)


class TestFormatDuration:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (5400, "1h 30m"),
            (90, "1m 30s"),
            (45, "45s"),
            (0, "0s"),
            (3600, "1h"),
            (60, "1m"),
            (3661, "1h 1m"),
            (7200, "2h"),
        ],
    )
    def test_formats_durations(self, seconds, expected):
        assert format_duration(seconds) == expected
