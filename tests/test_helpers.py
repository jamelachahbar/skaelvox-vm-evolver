"""Tests for helper functions in main.py."""
import pytest


def test_format_currency_basic():
    from main import format_currency
    assert format_currency(1234.56) == "$1,234.56"


def test_format_currency_zero():
    from main import format_currency
    assert format_currency(0) == "$0.00"


def test_format_currency_large():
    from main import format_currency
    assert format_currency(1000000) == "$1,000,000.00"


def test_format_currency_negative():
    from main import format_currency
    assert format_currency(-50.5) == "$-50.50"


def test_format_percent_basic():
    from main import format_percent
    assert format_percent(75.3) == "75.3%"


def test_format_percent_zero():
    from main import format_percent
    assert format_percent(0) == "0.0%"


def test_format_percent_hundred():
    from main import format_percent
    assert format_percent(100) == "100.0%"


def test_format_percent_decimal():
    from main import format_percent
    assert format_percent(33.333) == "33.3%"
