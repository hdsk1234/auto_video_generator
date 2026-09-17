import urllib.request
import json
import os
import ssl

OPENAI_IMAGE_URL = "https://api.openai.com/v1/images/generations"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

# Unverified SSL context to handle macOS python certificate issues
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

def generate_video_prompts(api_key: str, scenes: list, model: str = "gpt-4o-mini") -> list:
    """
    Generates detailed AI Video Prompts (optimized for Flow / Kling / Runway / Luma)
    for each scene using OpenAI Chat Completion API.
    """
    if not api_key:
        # Fallback template prompt generator if API key is empty
        return [
            {
                "scene_index": i,
                "scene_text": sc.get("text", ""),
                "prompt": f"Cinematic 8k video, photorealistic, {sc.get('text', '')}, slow camera motion, 60fps, octane render, vivid lighting"
            }
            for i, sc in enumerate(scenes)
        ]

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are an expert AI Video Prompt Engineer for tools like Flow, Kling, Runway, and Luma. "
                "Given a list of script scenes, generate a highly detailed, cinematic, high-quality video generation prompt in English for each scene. "
                "Include camera movement, lighting, style, rendering quality, and movement details. "
                "Output JSON format strictly: {\"prompts\": [\"prompt for scene 1\", \"prompt for scene 2\", ...]}"
            )
        },
        {
            "role": "user",
            "content": f"Script scenes: {json.dumps([sc.get('text', '') for sc in scenes], ensure_ascii=False)}"
        }
    ]

    payload = {
        "model": model,
        "messages": prompt_messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.7
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        OPENAI_CHAT_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, context=ssl_context) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            content = res["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            prompt_list = parsed.get("prompts", [])
            
            result = []
            for i, sc in enumerate(scenes):
                generated_prompt = prompt_list[i] if i < len(prompt_list) else f"Cinematic 8k video of {sc.get('text', '')}"
                result.append({
                    "scene_index": i,
                    "scene_text": sc.get("text", ""),
                    "prompt": generated_prompt
                })
            return result
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        # Fallback to smart template if API fails
        return [
            {
                "scene_index": i,
                "scene_text": sc.get("text", ""),
                "prompt": f"Cinematic photorealistic 8k video showing {sc.get('text', '')}, smooth 60fps camera pan, natural lighting, ultra-detailed"
            }
            for i, sc in enumerate(scenes)
        ]
    except Exception as e:
        return [
            {
                "scene_index": i,
                "scene_text": sc.get("text", ""),
                "prompt": f"Cinematic 8k video representing {sc.get('text', '')}, slow motion, professional lighting"
            }
            for i, sc in enumerate(scenes)
        ]

def generate_image(api_key: str, prompt: str, output_image_path: str, model: str = "dall-e-3", size: str = "1024x1024") -> str:
    """
    Calls OpenAI DALL-E API to generate image from scene text prompt and saves to disk.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "response_format": "url"
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        OPENAI_IMAGE_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, context=ssl_context) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            data_list = res.get("data", [])
            if not data_list:
                raise ValueError("No image data returned from OpenAI API")

            image_url = data_list[0].get("url")
            
            img_req = urllib.request.Request(image_url)
            with urllib.request.urlopen(img_req, context=ssl_context) as img_resp:
                img_bytes = img_resp.read()
                os.makedirs(os.path.dirname(output_image_path), exist_ok=True)
                with open(output_image_path, "wb") as f:
                    f.write(img_bytes)

            return output_image_path
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        raise RuntimeError(f"OpenAI DALL-E API Error ({e.code}): {err_body}")
    except Exception as e:
        raise RuntimeError(f"OpenAI Image Generation Error: {str(e)}")
