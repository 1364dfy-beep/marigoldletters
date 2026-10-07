import os
import wave

from google import genai
from google.genai import types

from .util import with_fallback

SAMPLE_RATE = 24000  # Gemini TTS returns 24 kHz, 16-bit, mono PCM


def synthesize(text: str, out_wav: str, settings: dict) -> None:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = f"{settings['tts_style']}\n\n{text}"

    def run(model: str) -> bytes:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=settings["voice"]
                        )
                    )
                ),
            ),
        )
        data = resp.candidates[0].content.parts[0].inline_data.data
        if not data or len(data) < SAMPLE_RATE * 2 * 20:  # < 20 s of audio = something went wrong
            raise ValueError("TTS returned empty or suspiciously short audio")
        return data

    pcm = with_fallback(settings["tts_models"], run, label="tts")
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
