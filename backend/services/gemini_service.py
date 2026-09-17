import os
import json
import base64
import urllib.request
import urllib.error
import re
from typing import Dict, Any, List, Optional

GEMINI_IMAGEN_MODEL = "imagen-3.0-generate-002"

def generate_image_with_gemini(
    api_key: str,
    prompt: str,
    output_image_path: str,
    aspect_ratio: str = "9:16"
) -> str:
    """
    Google Gemini Imagen 3 API를 호출하여 이미지를 생성하고 output_image_path에 저장합니다.
    standard library urllib를 사용하여 추가 패키지 없이 동작합니다.
    """
    if not api_key:
        raise ValueError("Gemini API Key is required")
    if not prompt:
        raise ValueError("Image prompt is required")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGEN_MODEL}:predict?key={api_key}"

    # Aspect ratio mapping (Gemini Imagen 3 supported formats: '1:1', '3:4', '4:3', '9:16', '16:9')
    valid_aspect_ratios = ["1:1", "3:4", "4:3", "9:16", "16:9"]
    ratio = aspect_ratio if aspect_ratio in valid_aspect_ratios else "9:16"

    payload = {
        "instances": [
            {
                "prompt": prompt
            }
        ],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": ratio,
            "outputMimeType": "image/png",
            "personGeneration": "ALLOW_ADULT"
        }
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_body = resp.read().decode("utf-8")
            result = json.loads(resp_body)
            
            predictions = result.get("predictions", [])
            if not predictions:
                raise ValueError("No image predictions returned by Gemini API")
            
            b64_img = predictions[0].get("bytesBase64Encoded")
            if not b64_img:
                raise ValueError("Base64 image data missing in Gemini response")

            os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)
            with open(output_image_path, "wb") as f:
                f.write(base64.b64decode(b64_img))

            return output_image_path

    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(err_msg)
            err_detail = err_json.get("error", {}).get("message", err_msg)
        except Exception:
            err_detail = err_msg
        raise RuntimeError(f"Gemini API Error ({e.code}): {err_detail}")
    except Exception as e:
        raise RuntimeError(f"Gemini image generation failed: {str(e)}")

def parse_srt_subtitles(srt_content: str) -> List[Dict[str, Any]]:
    """
    SRT 자막 문자열을 파싱하여 각 인덱스별 자막 텍스트와 타임스탬프 리스트를 반환합니다.
    """
    items = []
    blocks = re.split(r'\n\s*\n', srt_content.strip())
    for block in blocks:
        lines = [line.strip() for line in block.strip().split('\n') if line.strip()]
        if len(lines) >= 3:
            try:
                idx = int(lines[0])
                time_range = lines[1]
                text = " ".join(lines[2:])
                items.append({
                    "index": idx,
                    "time_range": time_range,
                    "text": text
                })
            except Exception:
                continue
    return items

def build_visual_prompt_from_subtitle(subtitle_text: str, base_style: str = "photorealistic, cinematic lighting, 8k resolution, vertical 9:16 video scene") -> str:
    """
    자막 텍스트를 고화질 시각 이미지 생성용 프롬프트로 변환/보강합니다.
    """
    clean_text = re.sub(r'\[.*?\]', '', subtitle_text).strip()
    return f"{clean_text}, {base_style}"
