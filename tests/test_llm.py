"""Tests for the shared LLM client (app/services/llm.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import llm


class TestBackendDetection:
    """Test that the backend is correctly detected as 'none' in test mode."""

    def test_backend_is_none(self):
        assert llm.BACKEND == "none"

    def test_is_available_false(self):
        assert llm.is_available() is False

    def test_anthropic_client_is_none(self):
        assert llm._anthropic_client is None

    def test_openai_client_is_none(self):
        assert llm._openai_client is None

    def test_model_is_empty(self):
        assert llm._model == ""


class TestNoneBackendGuards:
    """Calling LLM functions with no backend should raise RuntimeError."""

    @pytest.mark.asyncio
    async def test_raw_structured_completion_raises(self):
        with pytest.raises(RuntimeError, match="no client"):
            await llm.raw_structured_completion(
                messages=[{"role": "user", "content": "test"}],
                schema={"type": "object"},
            )

    @pytest.mark.asyncio
    async def test_structured_completion_raises(self):
        from pydantic import BaseModel

        class SampleModel(BaseModel):
            value: str = ""

        with pytest.raises(RuntimeError, match="no client"):
            await llm.structured_completion(
                messages=[{"role": "user", "content": "test"}],
                response_model=SampleModel,
            )


class TestStripMarkdownFence:
    """Test the markdown fence stripping helper."""

    def test_strips_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        assert llm._strip_markdown_fence(raw) == '{"key": "value"}'

    def test_strips_plain_fence(self):
        raw = '```\n{"key": "value"}\n```'
        assert llm._strip_markdown_fence(raw) == '{"key": "value"}'

    def test_no_fence_unchanged(self):
        raw = '{"key": "value"}'
        assert llm._strip_markdown_fence(raw) == '{"key": "value"}'


class TestAnthropicPath:
    """Test that the Anthropic path correctly handles messages and responses."""

    @pytest.mark.asyncio
    async def test_raw_completion_anthropic(self):
        mock_block = MagicMock()
        mock_block.text = '{"key": "claude_value"}'

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(llm, "_anthropic_client", mock_client),
            patch.object(llm, "_openai_client", None),
            patch.object(llm, "BACKEND", "anthropic"),
            patch.object(llm, "_model", "claude-sonnet-4-5"),
        ):
            result = await llm.raw_structured_completion(
                messages=[
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "test"},
                ],
                schema={"type": "object", "properties": {}},
                schema_name="test_schema",
            )

        assert result == '{"key": "claude_value"}'
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-sonnet-4-5"
        assert "You are helpful." in call_kwargs.kwargs["system"]

    @pytest.mark.asyncio
    async def test_structured_completion_anthropic(self):
        from pydantic import BaseModel

        class TestModel(BaseModel):
            value: str = ""

        mock_block = MagicMock()
        mock_block.text = '{"value": "from_claude"}'

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(llm, "_anthropic_client", mock_client),
            patch.object(llm, "_openai_client", None),
            patch.object(llm, "BACKEND", "anthropic"),
            patch.object(llm, "_model", "claude-sonnet-4-5"),
        ):
            result = await llm.structured_completion(
                messages=[
                    {"role": "system", "content": "Extract data."},
                    {"role": "user", "content": "test"},
                ],
                response_model=TestModel,
                schema_name="test_model",
            )

        assert result is not None
        assert result.value == "from_claude"


class TestOpenAIPath:
    """Test that OpenAI path uses strict JSON schema."""

    @pytest.mark.asyncio
    async def test_raw_completion_openai_uses_strict(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"key": "value"}'

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(llm, "_anthropic_client", None),
            patch.object(llm, "_openai_client", mock_client),
            patch.object(llm, "BACKEND", "openai"),
            patch.object(llm, "_model", "gpt-5.2"),
        ):
            result = await llm.raw_structured_completion(
                messages=[{"role": "user", "content": "test"}],
                schema={"type": "object", "properties": {}},
                schema_name="test_schema",
            )

        assert result == '{"key": "value"}'
        call_kwargs = mock_client.chat.completions.create.call_args
        rf = call_kwargs.kwargs["response_format"]
        assert rf["json_schema"]["strict"] is True

    @pytest.mark.asyncio
    async def test_structured_completion_openai_uses_parse(self):
        from pydantic import BaseModel

        class TestModel(BaseModel):
            value: str = "hello"

        mock_parsed = TestModel(value="from_openai")
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.parsed = mock_parsed

        mock_client = AsyncMock()
        mock_client.beta.chat.completions.parse = AsyncMock(
            return_value=mock_response
        )

        with (
            patch.object(llm, "_anthropic_client", None),
            patch.object(llm, "_openai_client", mock_client),
            patch.object(llm, "BACKEND", "openai"),
            patch.object(llm, "_model", "gpt-5.2"),
        ):
            result = await llm.structured_completion(
                messages=[{"role": "user", "content": "test"}],
                response_model=TestModel,
            )

        assert result is not None
        assert result.value == "from_openai"
        mock_client.beta.chat.completions.parse.assert_called_once()


class TestModalPath:
    """Test that Modal path omits strict and uses manual parsing."""

    @pytest.mark.asyncio
    async def test_raw_completion_modal_no_strict(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"key": "modal_value"}'

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(llm, "_anthropic_client", None),
            patch.object(llm, "_openai_client", mock_client),
            patch.object(llm, "BACKEND", "modal"),
            patch.object(llm, "_model", "Qwen/Qwen3-8B"),
        ):
            result = await llm.raw_structured_completion(
                messages=[{"role": "user", "content": "test"}],
                schema={"type": "object", "properties": {}},
                schema_name="test_schema",
            )

        assert result == '{"key": "modal_value"}'
        call_kwargs = mock_client.chat.completions.create.call_args
        rf = call_kwargs.kwargs["response_format"]
        assert "strict" not in rf["json_schema"]

    @pytest.mark.asyncio
    async def test_structured_completion_modal_parses_json(self):
        from pydantic import BaseModel

        class TestModel(BaseModel):
            value: str = ""

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"value": "from_modal"}'

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(llm, "_anthropic_client", None),
            patch.object(llm, "_openai_client", mock_client),
            patch.object(llm, "BACKEND", "modal"),
            patch.object(llm, "_model", "Qwen/Qwen3-8B"),
        ):
            result = await llm.structured_completion(
                messages=[{"role": "user", "content": "test"}],
                response_model=TestModel,
                schema_name="test_model",
            )

        assert result is not None
        assert result.value == "from_modal"
        # Modal path should NOT call beta.chat.completions.parse
        mock_client.beta.chat.completions.parse.assert_not_called()

    @pytest.mark.asyncio
    async def test_structured_completion_modal_bad_json_returns_none(self):
        from pydantic import BaseModel

        class StrictModel(BaseModel):
            required_field: str

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not valid json"

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(llm, "_anthropic_client", None),
            patch.object(llm, "_openai_client", mock_client),
            patch.object(llm, "BACKEND", "modal"),
            patch.object(llm, "_model", "test-model"),
        ):
            result = await llm.structured_completion(
                messages=[{"role": "user", "content": "test"}],
                response_model=StrictModel,
            )

        assert result is None
