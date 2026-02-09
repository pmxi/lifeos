import io
import logging
import os

from openai import AsyncOpenAI

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-transcribe"


def _get_client() -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    return AsyncOpenAI(api_key=api_key)


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    """Transcribe audio bytes into text using OpenAI's Audio API."""
    model = os.getenv("OPENAI_STT_MODEL", _DEFAULT_MODEL)
    prompt = os.getenv("OPENAI_STT_PROMPT")

    log.info("STT start: model=%s filename=%s bytes=%d", model, filename, len(audio_bytes))
    if prompt:
        log.debug("STT prompt provided (%d chars)", len(prompt))

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename  # Some clients infer format from filename.

    client = _get_client()
    request = {
        "model": model,
        "file": audio_file,
    }
    if prompt:
        request["prompt"] = prompt

    log.debug("STT request sent")
    transcription = await client.audio.transcriptions.create(**request)
    log.debug("STT response received")

    if isinstance(transcription, str):
        text = transcription
    else:
        text = getattr(transcription, "text", "")

    text = text.strip()
    log.info("STT result: %s", text)
    return text
