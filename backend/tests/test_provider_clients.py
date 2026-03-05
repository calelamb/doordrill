import pytest

from app.services.provider_clients import AnthropicLlmClient, DeepgramSttClient, ElevenLabsTtsClient, OpenAiLlmClient


@pytest.mark.asyncio
async def test_deepgram_client_uses_transcript_hint_without_key():
    client = DeepgramSttClient(api_key=None, base_url="https://api.deepgram.com", model="nova-2", timeout_seconds=1)
    result = await client.finalize_utterance({"transcript_hint": "hello there"})
    assert result.text == "hello there"
    assert result.is_final is True


@pytest.mark.asyncio
async def test_openai_client_falls_back_to_mock_without_key():
    client = OpenAiLlmClient(api_key=None, model="gpt-4o-mini", base_url="https://api.openai.com/v1", timeout_seconds=1)
    chunks = [chunk async for chunk in client.stream_reply(rep_text="We can cut your price", stage="objection_handling", system_prompt="x")]
    combined = "".join(chunks)
    assert "expensive" in combined.lower()


@pytest.mark.asyncio
async def test_elevenlabs_client_falls_back_without_credentials():
    client = ElevenLabsTtsClient(
        api_key=None,
        voice_id=None,
        model_id="eleven_flash_v2_5",
        base_url="https://api.elevenlabs.io",
        timeout_seconds=1,
    )
    chunks = [chunk async for chunk in client.stream_audio("hello")]
    assert chunks
    assert chunks[0]["provider"] == "elevenlabs"


@pytest.mark.asyncio
async def test_anthropic_client_falls_back_to_mock_without_key():
    client = AnthropicLlmClient(
        api_key=None,
        model="claude-3-5-sonnet-latest",
        base_url="https://api.anthropic.com",
        timeout_seconds=1,
    )
    chunks = [chunk async for chunk in client.stream_reply(rep_text="We can cut your price", stage="objection_handling", system_prompt="x")]
    combined = "".join(chunks)
    assert "expensive" in combined.lower()
