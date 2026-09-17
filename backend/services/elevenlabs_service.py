import urllib.request
import urllib.parse
import json
import base64
import os
import ssl
from backend.services.srt_generator import generate_srt_from_timestamps

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_ELEVENLABS_API_KEY = "sk_7fd47907245c458e3d11ccb07d0e6f0900f74bcea25d7945"

# Unverified SSL context to handle macOS python certificate issues
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# ElevenLabs Guaranteed Free Premade Voice IDs
FREE_PREMADE_VOICE_IDS = [
    "JBFqnCBsd6RMkjVDRZzb", # George (Premade - Free Plan Compatible)
    "cgSgspJ2msm6clMCkdW9", # Jessica (Premade - Free Plan Compatible)
    "pNInz6obpgDQGcFmaJgB", # Adam (Premade - Free Plan Compatible)
    "EXAVITQu4vr4xnSDxMaL", # Bella (Premade - Free Plan Compatible)
    "21m00Tcm4TlvDq8ikWAM"  # Rachel
]

DEFAULT_FREE_VOICE_ID = FREE_PREMADE_VOICE_IDS[0]

def get_voices(api_key: str = None) -> list:
    """Fetch available voices from ElevenLabs API"""
    if not api_key:
        api_key = DEFAULT_ELEVENLABS_API_KEY
    req = urllib.request.Request(
        f"{ELEVENLABS_BASE_URL}/voices",
        headers={"xi-api-key": api_key, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, context=ssl_context) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            voices = data.get("voices", [])
            
            # Sort premade voices first for Free plan safety
            premade = [v for v in voices if v.get("category") in ("premade", "default")]
            others = [v for v in voices if v.get("category") not in ("premade", "default")]
            sorted_voices = premade + others

            return [
                {
                    "voice_id": v.get("voice_id"),
                    "name": f"{v.get('name')} ({'무료 지원' if v.get('category') in ('premade', 'default') else '유료/라이브러리'})",
                    "category": v.get("category", "default"),
                    "preview_url": v.get("preview_url")
                }
                for v in sorted_voices
            ]
    except Exception as e:
        raise RuntimeError(f"ElevenLabs Voices API Error: {str(e)}")

def generate_tts_with_srt(
    api_key: str = None,
    text: str = "",
    voice_id: str = "",
    output_audio_path: str = "",
    output_srt_path: str = "",
    model_id: str = "eleven_multilingual_v2",
    tried_voices: set = None,
    remove_silence: bool = False,
    silence_db: int = -40,
    speed: float = 1.0
) -> dict:
    """
    Calls ElevenLabs text-to-speech with-timestamps API, saves MP3 audio, creates SRT subtitle file,
    and applies optional silence removal and speed adjustments.
    Returns metadata dict. Automatically falls back across free voices if 402 error occurs.
    """
    if not api_key:
        api_key = DEFAULT_ELEVENLABS_API_KEY

    if tried_voices is None:
        tried_voices = set()

    target_voice_id = voice_id or DEFAULT_FREE_VOICE_ID
    tried_voices.add(target_voice_id)

    url = f"{ELEVENLABS_BASE_URL}/text-to-speech/{target_voice_id}/with-timestamps"
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, context=ssl_context) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            
            # Extract Audio (Base64 encoded)
            audio_b64 = res_data.get("audio_base64")
            if not audio_b64:
                raise ValueError("No audio_base64 returned from ElevenLabs API")

            audio_bytes = base64.b64decode(audio_b64)
            os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)
            with open(output_audio_path, "wb") as f:
                f.write(audio_bytes)

            # Extract Alignment & Generate SRT
            alignment = res_data.get("alignment", {})
            srt_content = generate_srt_from_timestamps(alignment)

            os.makedirs(os.path.dirname(output_srt_path), exist_ok=True)
            with open(output_srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)

            # Calculate total duration from last timestamp
            ends = alignment.get("character_end_times_seconds", [0.0])
            total_duration = max(ends) if ends else 0.0

            # Apply Audio Post-Processing (Silence removal / Speed adjustment) if needed
            if remove_silence or speed != 1.0:
                from backend.services.audio_processor import process_audio_silence_and_speed
                temp_audio_path = output_audio_path + ".tmp.mp3"
                os.rename(output_audio_path, temp_audio_path)

                proc_res = process_audio_silence_and_speed(
                    input_audio_path=temp_audio_path,
                    output_audio_path=output_audio_path,
                    input_srt_path=output_srt_path,
                    output_srt_path=output_srt_path,
                    remove_silence=remove_silence,
                    silence_db=silence_db,
                    speed=speed
                )
                if os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)

                return {
                    "status": "success",
                    "audio_path": output_audio_path,
                    "srt_path": output_srt_path,
                    "srt_content": proc_res.get("srt_content", srt_content),
                    "duration_seconds": proc_res.get("duration_seconds", total_duration),
                    "character_count": len(text)
                }

            return {
                "status": "success",
                "audio_path": output_audio_path,
                "srt_path": output_srt_path,
                "srt_content": srt_content,
                "duration_seconds": total_duration,
                "character_count": len(text)
            }
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8')
        if e.code == 402 or "paid_plan_required" in err_msg:
            # Find next free voice that hasn't been tried yet
            next_free_voice = next((v_id for v_id in FREE_PREMADE_VOICE_IDS if v_id not in tried_voices), None)
            if next_free_voice:
                print(f"⚠️ Voice '{target_voice_id}' required paid plan. Falling back to free voice '{next_free_voice}'...")
                return generate_tts_with_srt(
                    api_key=api_key,
                    text=text,
                    voice_id=next_free_voice,
                    output_audio_path=output_audio_path,
                    output_srt_path=output_srt_path,
                    model_id=model_id,
                    tried_voices=tried_voices,
                    remove_silence=remove_silence,
                    silence_db=silence_db,
                    speed=speed
                )
            raise RuntimeError("ElevenLabs 계정이 무료 플랜 정책으로 인해 요청한 음성 사용이 제한되었습니다. ElevenLabs 대시보드에서 기본(Premade) 음성을 선택해 주세요.")
        raise RuntimeError(f"ElevenLabs HTTP Error ({e.code}): {err_msg}")
    except Exception as e:
        raise RuntimeError(f"ElevenLabs TTS Exception: {str(e)}")
