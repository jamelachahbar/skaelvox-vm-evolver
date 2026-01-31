"""Tests for ai_analyzer module."""
import json
import threading
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from ai_analyzer import AIAnalyzer, AIRecommendation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analyzer(provider="anthropic"):
    """Create an AIAnalyzer with a mocked client for testing."""
    analyzer = AIAnalyzer(api_key="test-key", provider=provider)
    analyzer.client = MagicMock()
    analyzer.provider = provider
    if provider == "azure_openai":
        analyzer.azure_deployment = "gpt-4"
    return analyzer


# ---------------------------------------------------------------------------
# _extract_json tests
# ---------------------------------------------------------------------------

class TestExtractJson:
    """Tests for the _extract_json static method."""

    def test_pure_json(self):
        text = '{"recommended_sku": "Standard_D4s_v5", "confidence": "High"}'
        result = AIAnalyzer._extract_json(text)
        assert result is not None
        assert result["recommended_sku"] == "Standard_D4s_v5"
        assert result["confidence"] == "High"

    def test_markdown_fenced_json(self):
        text = 'Here is the analysis:\n```json\n{"recommended_sku": "Standard_D2s_v5", "savings": 100}\n```\nDone.'
        result = AIAnalyzer._extract_json(text)
        assert result is not None
        assert result["recommended_sku"] == "Standard_D2s_v5"
        assert result["savings"] == 100

    def test_text_wrapped_json(self):
        text = 'Sure, here is the recommendation: {"recommended_sku": "Standard_B2s", "confidence": "Low"} hope this helps!'
        result = AIAnalyzer._extract_json(text)
        assert result is not None
        assert result["recommended_sku"] == "Standard_B2s"

    def test_nested_braces(self):
        text = '{"outer": {"inner": {"deep": 1}}, "value": 42}'
        result = AIAnalyzer._extract_json(text)
        assert result is not None
        assert result["outer"]["inner"]["deep"] == 1
        assert result["value"] == 42

    def test_braces_in_strings(self):
        text = '{"message": "Use {placeholder} syntax", "count": 3}'
        result = AIAnalyzer._extract_json(text)
        assert result is not None
        assert result["count"] == 3

    def test_invalid_input_returns_none(self):
        assert AIAnalyzer._extract_json("no json here") is None
        assert AIAnalyzer._extract_json("") is None
        assert AIAnalyzer._extract_json("{invalid json}") is None

    def test_code_fence_without_json_tag(self):
        text = '```\n{"key": "value"}\n```'
        result = AIAnalyzer._extract_json(text)
        assert result is not None
        assert result["key"] == "value"


# ---------------------------------------------------------------------------
# _validate_recommendation tests
# ---------------------------------------------------------------------------

class TestValidateRecommendation:
    """Tests for the _validate_recommendation static method."""

    def test_negative_savings_clamped(self):
        result = {"estimated_monthly_savings_usd": -50, "confidence": "High"}
        validated = AIAnalyzer._validate_recommendation(result, "Standard_D4s_v5")
        assert validated["estimated_monthly_savings_usd"] == 0.0

    def test_invalid_confidence_normalized(self):
        result = {"confidence": "very high"}
        validated = AIAnalyzer._validate_recommendation(result)
        assert validated["confidence"] == "Medium"

    def test_valid_confidence_preserved(self):
        for conf in ("High", "Medium", "Low"):
            result = {"confidence": conf}
            validated = AIAnalyzer._validate_recommendation(result)
            assert validated["confidence"] == conf

    def test_confidence_case_insensitive(self):
        result = {"confidence": "high"}
        validated = AIAnalyzer._validate_recommendation(result)
        assert validated["confidence"] == "High"

    def test_missing_recommended_sku_uses_fallback(self):
        result = {"recommended_sku": ""}
        validated = AIAnalyzer._validate_recommendation(result, "Standard_D4s_v5")
        assert validated["recommended_sku"] == "Standard_D4s_v5"

    def test_none_recommended_sku_uses_fallback(self):
        result = {}
        validated = AIAnalyzer._validate_recommendation(result, "Standard_E4s_v5")
        assert validated["recommended_sku"] == "Standard_E4s_v5"

    def test_actions_string_coerced_to_list(self):
        result = {"recommended_actions": "Resize the VM"}
        validated = AIAnalyzer._validate_recommendation(result)
        assert validated["recommended_actions"] == ["Resize the VM"]

    def test_actions_non_list_coerced(self):
        result = {"recommended_actions": 123}
        validated = AIAnalyzer._validate_recommendation(result)
        assert validated["recommended_actions"] == []

    def test_invalid_complexity_normalized(self):
        result = {"migration_complexity": "extreme"}
        validated = AIAnalyzer._validate_recommendation(result)
        assert validated["migration_complexity"] == "Medium"

    def test_valid_complexity_preserved(self):
        for c in ("Low", "Medium", "High"):
            result = {"migration_complexity": c}
            validated = AIAnalyzer._validate_recommendation(result)
            assert validated["migration_complexity"] == c

    def test_non_numeric_savings(self):
        result = {"estimated_monthly_savings_usd": "not a number"}
        validated = AIAnalyzer._validate_recommendation(result)
        assert validated["estimated_monthly_savings_usd"] == 0.0


# ---------------------------------------------------------------------------
# Retry logic tests
# ---------------------------------------------------------------------------

class TestRetryLogic:
    """Tests for the _call_ai retry wrapper."""

    def test_transient_error_retries(self):
        analyzer = _make_analyzer()
        # First two calls raise transient error, third succeeds
        call_count = {"n": 0}

        def mock_inner(prompt, max_tokens):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise Exception("rate_limit exceeded, please retry")
            return '{"result": "ok"}'

        analyzer._call_ai_inner = mock_inner

        with patch("ai_analyzer.time.sleep"):  # skip real sleep
            result = analyzer._call_ai("test prompt")

        assert result == '{"result": "ok"}'
        assert call_count["n"] == 3  # 1 initial + 2 retries

    def test_non_transient_error_raises_immediately(self):
        analyzer = _make_analyzer()

        def mock_inner(prompt, max_tokens):
            raise Exception("Invalid API key")

        analyzer._call_ai_inner = mock_inner

        with pytest.raises(Exception, match="Invalid API key"):
            analyzer._call_ai("test prompt")

    def test_max_retries_exhausted(self):
        analyzer = _make_analyzer()

        def mock_inner(prompt, max_tokens):
            raise Exception("429 Too Many Requests")

        analyzer._call_ai_inner = mock_inner

        with patch("ai_analyzer.time.sleep"):
            with pytest.raises(Exception, match="429"):
                analyzer._call_ai("test prompt")


# ---------------------------------------------------------------------------
# System prompt tests
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    """Tests that system prompt is sent to both providers."""

    def test_anthropic_receives_system_prompt(self):
        analyzer = _make_analyzer("anthropic")
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"result": "ok"}')]
        analyzer.client.messages.create = MagicMock(return_value=mock_response)

        analyzer._call_ai_inner("test prompt", 1000)

        call_kwargs = analyzer.client.messages.create.call_args
        assert call_kwargs.kwargs.get("system") == AIAnalyzer.SYSTEM_PROMPT

    def test_azure_openai_receives_system_prompt(self):
        analyzer = _make_analyzer("azure_openai")
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"result": "ok"}'
        analyzer.client.chat.completions.create = MagicMock(return_value=mock_response)

        analyzer._call_ai_inner("test prompt", 1000)

        call_kwargs = analyzer.client.chat.completions.create.call_args
        messages = call_kwargs.kwargs.get("messages", [])
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == AIAnalyzer.SYSTEM_PROMPT

    def test_azure_openai_uses_json_response_format(self):
        analyzer = _make_analyzer("azure_openai")
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"result": "ok"}'
        analyzer.client.chat.completions.create = MagicMock(return_value=mock_response)

        analyzer._call_ai_inner("test prompt", 1000)

        call_kwargs = analyzer.client.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("response_format") == {"type": "json_object"}


# ---------------------------------------------------------------------------
# Semaphore / concurrency tests
# ---------------------------------------------------------------------------

class TestConcurrencyLimiter:
    """Tests for the AI concurrency semaphore."""

    def test_semaphore_initialized(self):
        analyzer = _make_analyzer()
        assert isinstance(analyzer._semaphore, threading.Semaphore)

    def test_semaphore_limits_concurrency(self):
        analyzer = _make_analyzer()
        # Replace semaphore with one that has a limit of 1 for testing
        analyzer._semaphore = threading.Semaphore(1)

        call_order = []

        def mock_inner(prompt, max_tokens):
            call_order.append("start")
            import time
            time.sleep(0.05)
            call_order.append("end")
            return '{"ok": true}'

        analyzer._call_ai_inner = mock_inner

        threads = [
            threading.Thread(target=analyzer._call_ai, args=("p",))
            for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # With semaphore(1), calls should be serialized: start, end, start, end
        assert call_order == ["start", "end", "start", "end"]
