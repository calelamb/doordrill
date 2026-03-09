"""
Quick provider connectivity test.
Run from backend/: python test_providers.py
Tests Deepgram, ElevenLabs, and OpenAI using the keys in your .env
"""
import asyncio
import os
import sys
from pathlib import Path

# Load .env manually so we don't need the full app stack
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")


async def test_openai():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌  OpenAI:     OPENAI_API_KEY not set")
        return False

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "Say hello."}],
                },
            )
            resp.raise_for_status()
            reply = resp.json()["choices"][0]["message"]["content"].strip()
            print(f"✅  OpenAI:     Connected — model replied: \"{reply}\"")
            return True
    except Exception as e:
        print(f"❌  OpenAI:     {e}")
        return False


async def test_deepgram():
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        print("❌  Deepgram:   DEEPGRAM_API_KEY not set")
        return False

    # Hit the projects endpoint — no audio needed, just verifies auth
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.deepgram.com/v1/projects",
                headers={"Authorization": f"Token {api_key}"},
            )
            resp.raise_for_status()
            projects = resp.json().get("projects", [])
            name = projects[0]["name"] if projects else "(no projects yet)"
            print(f"✅  Deepgram:   Connected — project: \"{name}\"")
            return True
    except Exception as e:
        print(f"❌  Deepgram:   {e}")
        return False


async def test_elevenlabs():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID")

    if not api_key:
        print("❌  ElevenLabs: ELEVENLABS_API_KEY not set")
        return False
    if not voice_id:
        print("❌  ElevenLabs: ELEVENLABS_VOICE_ID not set")
        return False

    # Generate a tiny audio sample — "Hello." — and verify we get bytes back
    import httpx
    try:
        model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "text": "Hello, is anyone home?",
                    "model_id": model_id,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            )
            resp.raise_for_status()
            audio_bytes = resp.content
            kb = len(audio_bytes) / 1024
            print(f"✅  ElevenLabs: Connected — received {kb:.1f} KB of audio (voice_id: {voice_id[:8]}...)")
            # Optionally save a sample so you can listen
            out_path = Path(__file__).parent / "elevenlabs_sample.mp3"
            out_path.write_bytes(audio_bytes)
            print(f"   ↳ Sample saved to backend/elevenlabs_sample.mp3 — open it to hear the voice")
            return True
    except Exception as e:
        print(f"❌  ElevenLabs: {e}")
        return False


async def main():
    print("\n── DoorDrill Provider Connectivity Test ──\n")

    llm_provider = os.getenv("LLM_PROVIDER", "mock")
    stt_provider = os.getenv("STT_PROVIDER", "mock")
    tts_provider = os.getenv("TTS_PROVIDER", "mock")

    print(f"   LLM_PROVIDER={llm_provider}  STT_PROVIDER={stt_provider}  TTS_PROVIDER={tts_provider}\n")

    if llm_provider != "openai":
        print(f"⚠️   OpenAI:     LLM_PROVIDER is '{llm_provider}', not 'openai' — add LLM_PROVIDER=openai to .env to activate")
    else:
        await test_openai()

    if stt_provider != "deepgram":
        print(f"⚠️   Deepgram:   STT_PROVIDER is '{stt_provider}', not 'deepgram' — add STT_PROVIDER=deepgram to .env to activate")
    else:
        await test_deepgram()

    if tts_provider != "elevenlabs":
        print(f"⚠️   ElevenLabs: TTS_PROVIDER is '{tts_provider}', not 'elevenlabs' — add TTS_PROVIDER=elevenlabs to .env to activate")
    else:
        await test_elevenlabs()

    print("\n──────────────────────────────────────────\n")


if __name__ == "__main__":
    asyncio.run(main())
