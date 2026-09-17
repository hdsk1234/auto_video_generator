import http.server
import socketserver
import json
import os
import urllib.parse
import subprocess
import traceback
import sys
import ssl

# Fix macOS Python SSL certificate verification failure globally
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.elevenlabs_service import get_voices, generate_tts_with_srt
from backend.services.openai_service import generate_image, generate_video_prompts
from backend.services.video_renderer import render_video_with_ffmpeg

PORT = 8080
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
RESULT_DIR = os.path.join(PROJECT_ROOT, "result")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

# Ensure default folder_1 exists inside result/
default_project = os.path.join(RESULT_DIR, "folder_1")
os.makedirs(default_project, exist_ok=True)
os.makedirs(os.path.join(default_project, "images"), exist_ok=True)

class AutoVideoHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_file_with_range(self, file_path: str, content_type: str):
        """Helper to send files with HTTP 206 Partial Content & Accept-Ranges for seeking support"""
        file_size = os.path.getsize(file_path)
        range_header = self.headers.get('Range')

        if range_header:
            try:
                bytes_range = range_header.strip().split("=")[1]
                start_str, end_str = bytes_range.split("-")
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else file_size - 1
                if start >= file_size:
                    start = file_size - 1
                if end >= file_size:
                    end = file_size - 1
                length = end - start + 1

                self.send_response(206)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.end_headers()

                with open(file_path, "rb") as f:
                    f.seek(start)
                    self.wfile.write(f.read(length))
                return
            except Exception:
                pass

        # Fallback response for full file with Accept-Ranges
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(file_size))
        self.end_headers()
        with open(file_path, "rb") as f:
            self.wfile.write(f.read())

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/" or path == "/index.html":
            file_path = os.path.join(STATIC_DIR, "index.html")
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        if path.endswith(".html") or path in ["/workflow", "/index"]:
            clean_name = os.path.basename(path)
            if not clean_name.endswith(".html"):
                clean_name += ".html"
            file_path = os.path.join(STATIC_DIR, clean_name)
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
                return
        
        # Serve static files (images, audio, mp4)
        if path.startswith("/static/"):
            rel_path = path[len("/static/"):].lstrip("/")
            file_path = os.path.join(STATIC_DIR, rel_path)
            if os.path.exists(file_path) and os.path.isfile(file_path):
                if file_path.endswith(".mp3"):
                    return self.send_file_with_range(file_path, "audio/mpeg")
                elif file_path.endswith(".mp4"):
                    return self.send_file_with_range(file_path, "video/mp4")
                elif file_path.endswith(".png"):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                elif file_path.endswith(".srt"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        if path == "/api/projects/list":
            projects = []
            if os.path.exists(RESULT_DIR):
                for entry in sorted(os.listdir(RESULT_DIR)):
                    p_path = os.path.join(RESULT_DIR, entry)
                    if os.path.isdir(p_path) and not entry.startswith("."):
                        has_script = os.path.exists(os.path.join(p_path, "script.txt"))
                        has_audio = os.path.exists(os.path.join(p_path, "tts_audio.mp3"))
                        has_srt = os.path.exists(os.path.join(p_path, "subtitles.srt"))
                        has_video = os.path.exists(os.path.join(p_path, "final_video.mp4"))
                        
                        img_dir = os.path.join(p_path, "images")
                        image_count = len([f for f in os.listdir(img_dir) if f.endswith(('.png', '.jpg'))]) if os.path.exists(img_dir) else 0

                        projects.append({
                            "name": entry,
                            "has_script": has_script,
                            "has_audio": has_audio,
                            "has_srt": has_srt,
                            "has_video": has_video,
                            "image_count": image_count
                        })
            return self.send_json_success({"projects": projects})

        if path.startswith("/result/"):
            rel_path = path[len("/result/"):].lstrip("/")
            file_path = os.path.join(RESULT_DIR, rel_path)
            if os.path.exists(file_path) and os.path.isfile(file_path):
                if file_path.endswith(".mp3"):
                    return self.send_file_with_range(file_path, "audio/mpeg")
                elif file_path.endswith(".mp4"):
                    return self.send_file_with_range(file_path, "video/mp4")
                elif file_path.endswith(".png"):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                elif file_path.endswith(".srt"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                elif file_path.endswith(".txt") or file_path.endswith(".json"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        self.send_error(404, "File Not Found")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body_data = self.rfile.read(content_length)
            data = json.loads(body_data.decode('utf-8')) if body_data else {}

            # API Router
            if path == "/api/audio/process":
                from backend.services.audio_processor import process_audio_silence_and_speed
                folder_name = data.get("folder_name", "folder_1").strip()
                remove_silence = bool(data.get("remove_silence", True))
                silence_db = int(data.get("silence_db", -40))
                speed = float(data.get("speed", 1.0))

                p_dir = os.path.join(RESULT_DIR, folder_name)
                audio_path = os.path.join(p_dir, "tts_audio.mp3")
                srt_path = os.path.join(p_dir, "subtitles.srt")

                raw_audio_path = os.path.join(p_dir, "raw_tts_audio.mp3")
                raw_srt_path = os.path.join(p_dir, "raw_subtitles.srt")

                if os.path.exists(audio_path):
                    if not os.path.exists(raw_audio_path):
                        import shutil
                        shutil.copyfile(audio_path, raw_audio_path)
                    if os.path.exists(srt_path) and not os.path.exists(raw_srt_path):
                        import shutil
                        shutil.copyfile(srt_path, raw_srt_path)

                source_audio = raw_audio_path if os.path.exists(raw_audio_path) else audio_path
                source_srt = raw_srt_path if os.path.exists(raw_srt_path) else srt_path

                if not os.path.exists(source_audio):
                    return self.send_json_error(400, "TTS audio file not found. Generate TTS first.")

                proc_res = process_audio_silence_and_speed(
                    input_audio_path=source_audio,
                    output_audio_path=audio_path,
                    input_srt_path=source_srt if os.path.exists(source_srt) else None,
                    output_srt_path=srt_path,
                    remove_silence=remove_silence,
                    silence_db=silence_db,
                    speed=speed
                )

                return self.send_json_success({
                    "status": "success",
                    "audio_url": f"/result/{folder_name}/tts_audio.mp3?t={int(os.times().elapsed * 1000)}",
                    "audio_path": audio_path,
                    "srt_url": f"/result/{folder_name}/subtitles.srt?t={int(os.times().elapsed * 1000)}",
                    "srt_path": srt_path,
                    "srt_content": proc_res.get("srt_content", ""),
                    "duration_seconds": proc_res.get("duration_seconds", 10.0),
                    "speed": speed,
                    "silence_removed": remove_silence,
                    "silence_db": silence_db
                })

            elif path == "/api/projects/create":
                folder_name = data.get("folder_name", "").strip()
                if not folder_name:
                    return self.send_json_error(400, "Folder name is required")
                p_dir = os.path.join(RESULT_DIR, folder_name)
                os.makedirs(p_dir, exist_ok=True)
                os.makedirs(os.path.join(p_dir, "images"), exist_ok=True)
                return self.send_json_success({"status": "success", "folder_name": folder_name})

            elif path == "/api/projects/load":
                folder_name = data.get("folder_name", "folder_1").strip()
                p_dir = os.path.join(RESULT_DIR, folder_name)
                if not os.path.exists(p_dir):
                    os.makedirs(p_dir, exist_ok=True)
                    os.makedirs(os.path.join(p_dir, "images"), exist_ok=True)

                # Read script.txt if exists
                script_path = os.path.join(p_dir, "script.txt")
                full_script = ""
                if os.path.exists(script_path):
                    with open(script_path, "r", encoding="utf-8") as f:
                        full_script = f.read()

                # Read TTS & SRT if exists
                audio_path = os.path.join(p_dir, "tts_audio.mp3")
                srt_path = os.path.join(p_dir, "subtitles.srt")
                tts_output = None
                if os.path.exists(audio_path) and os.path.exists(srt_path):
                    with open(srt_path, "r", encoding="utf-8") as f:
                        srt_content = f.read()
                    tts_output = {
                        "audio_url": f"/result/{folder_name}/tts_audio.mp3",
                        "audio_path": audio_path,
                        "srt_url": f"/result/{folder_name}/subtitles.srt",
                        "srt_path": srt_path,
                        "srt_content": srt_content,
                        "duration_seconds": 10.0
                    }

                # Read Prompts if exists
                prompts_path = os.path.join(p_dir, "prompts.json")
                video_prompts = {}
                if os.path.exists(prompts_path):
                    try:
                        with open(prompts_path, "r", encoding="utf-8") as f:
                            video_prompts = json.load(f)
                    except Exception:
                        pass

                # Read Images if exists
                images_dir = os.path.join(p_dir, "images")
                scene_images = {}
                if os.path.exists(images_dir):
                    for fname in os.listdir(images_dir):
                        if fname.startswith("scene_") and fname.endswith(".png"):
                            try:
                                idx_str = fname.replace("scene_", "").replace(".png", "")
                                idx = int(idx_str)
                                img_path = os.path.join(images_dir, fname)
                                scene_images[str(idx)] = {
                                    "image_url": f"/result/{folder_name}/images/{fname}",
                                    "image_path": img_path
                                }
                            except Exception:
                                pass

                # Read Final Video if exists
                final_video_path = os.path.join(p_dir, "final_video.mp4")
                rendered_video = None
                if os.path.exists(final_video_path):
                    rendered_video = {
                        "video_url": f"/result/{folder_name}/final_video.mp4",
                        "filename": f"{folder_name}_final.mp4"
                    }

                # Read Flow Videos if exists
                videos_dir = os.path.join(p_dir, "flow_videos")
                flow_videos = []
                if os.path.exists(videos_dir):
                    for fname in sorted(os.listdir(videos_dir)):
                        if fname.lower().endswith(('.mp4', '.mov', '.webm', '.avi', '.mkv')):
                            v_path = os.path.join(videos_dir, fname)
                            flow_videos.append({
                                "video_name": fname,
                                "video_url": f"/result/{folder_name}/flow_videos/{fname}",
                                "video_path": v_path
                            })

                return self.send_json_success({
                    "status": "success",
                    "folder_name": folder_name,
                    "full_script": full_script,
                    "tts_output": tts_output,
                    "video_prompts": video_prompts,
                    "scene_images": scene_images,
                    "flow_videos": flow_videos,
                    "rendered_video": rendered_video
                })

            elif path == "/api/projects/save-script":
                folder_name = data.get("folder_name", "folder_1").strip()
                script_text = data.get("script", "").strip()
                p_dir = os.path.join(RESULT_DIR, folder_name)
                os.makedirs(p_dir, exist_ok=True)
                with open(os.path.join(p_dir, "script.txt"), "w", encoding="utf-8") as f:
                    f.write(script_text)
                return self.send_json_success({"status": "success"})

            elif path == "/api/demo/setup":
                # Generate demo sample files (images, audio, SRT) without needing external API keys
                media_dir = os.path.join(STATIC_DIR, "media")
                images_dir = os.path.join(STATIC_DIR, "images")
                os.makedirs(media_dir, exist_ok=True)
                os.makedirs(images_dir, exist_ok=True)

                demo_audio_path = os.path.join(media_dir, "demo_audio.mp3")
                demo_srt_path = os.path.join(media_dir, "demo_subtitles.srt")

                # Generate demo audio (5s sine tone converted to mp3 if missing)
                if not os.path.exists(demo_audio_path):
                    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=523:duration=10", "-c:a", "libmp3lame", demo_audio_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                # Generate demo SRT content
                demo_srt_content = """1\n00:00:00,000 --> 00:00:02,500\n[테스트 모드] 안녕하세요! AI 영상 제작 테스트입니다.\n\n2\n00:00:02,500 --> 00:00:05,000\nAPI Key 없이도 FFmpeg 서버 합성 성능을 체험해보세요.\n\n3\n00:00:05,000 --> 00:00:07,500\n3번째 장면: 고화질 샘플 배경 이미지 슬라이드\n\n4\n00:00:07,500 --> 00:00:10,000\n4번째 장면: 자막과 음성, 비디오가 하나로 합성됩니다."""
                with open(demo_srt_path, "w", encoding="utf-8") as f:
                    f.write(demo_srt_content)

                # Generate 4 colorful sample scene images
                colors = ["#3368A0", "#66A3BF", "#475569", "#0F172A"]
                demo_images = []
                for idx, color in enumerate(colors, 1):
                    img_path = os.path.join(images_dir, f"demo_scene_{idx}.png")
                    if not os.path.exists(img_path):
                        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=1080x1920:d=1", "-frames:v", "1", img_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    demo_images.append({
                        "scene_index": idx - 1,
                        "image_url": f"/static/images/demo_scene_{idx}.png",
                        "image_path": img_path
                    })

                demo_prompt = """다음 3개의 프롬프트로 각각 독립된 영상을 동시에 생성해줘:
1. 노을이 지는 해변을 달리는 백마, 시네마틱 4k
2. 비 내리는 사이버펑크 도시의 네온사인 골목, 드론 샷
3. 깊은 숲속에서 빛나는 신비로운 버섯 군락, 매크로 렌즈"""

                return self.send_json_success({
                    "status": "success",
                    "audio_url": "/static/media/demo_audio.mp3",
                    "audio_path": demo_audio_path,
                    "srt_url": "/static/media/demo_subtitles.srt",
                    "srt_path": demo_srt_path,
                    "srt_content": demo_srt_content,
                    "duration_seconds": 10.0,
                    "demo_images": demo_images,
                    "demo_prompt": demo_prompt
                })

            elif path == "/api/elevenlabs/voices":
                api_key = data.get("elevenlabs_key", "").strip()
                if not api_key:
                    return self.send_json_error(400, "ElevenLabs API Key is required")
                voices = get_voices(api_key)
                return self.send_json_success({"voices": voices})

            elif path == "/api/generate/tts-srt":
                import importlib
                import backend.services.elevenlabs_service as elevenlabs_mod
                importlib.reload(elevenlabs_mod)

                api_key = data.get("elevenlabs_key", "").strip()
                text = data.get("text", "").strip()
                voice_id = data.get("voice_id", "").strip()
                folder_name = data.get("folder_name", "").strip()
                remove_silence = bool(data.get("remove_silence", False))
                silence_db = int(data.get("silence_db", -40))
                speed = float(data.get("speed", 1.0))
                
                if not api_key:
                    return self.send_json_error(400, "ElevenLabs API Key is required")
                if not text:
                    return self.send_json_error(400, "Script text is required")

                if folder_name:
                    p_dir = os.path.join(RESULT_DIR, folder_name)
                    os.makedirs(p_dir, exist_ok=True)
                    audio_path = os.path.join(p_dir, "tts_audio.mp3")
                    srt_path = os.path.join(p_dir, "subtitles.srt")
                    audio_url = f"/result/{folder_name}/tts_audio.mp3"
                    srt_url = f"/result/{folder_name}/subtitles.srt"
                else:
                    job_id = f"job_{int(os.times().elapsed * 1000)}"
                    audio_path = os.path.join(STATIC_DIR, "media", f"{job_id}.mp3")
                    srt_path = os.path.join(STATIC_DIR, "media", f"{job_id}.srt")
                    audio_url = f"/static/media/{job_id}.mp3"
                    srt_url = f"/static/media/{job_id}.srt"

                res = elevenlabs_mod.generate_tts_with_srt(
                    api_key=api_key,
                    text=text,
                    voice_id=voice_id,
                    output_audio_path=audio_path,
                    output_srt_path=srt_path,
                    remove_silence=remove_silence,
                    silence_db=silence_db,
                    speed=speed
                )

                return self.send_json_success({
                    "status": "success",
                    "audio_url": audio_url,
                    "audio_path": audio_path,
                    "srt_url": srt_url,
                    "srt_path": srt_path,
                    "srt_content": res["srt_content"],
                    "duration_seconds": res["duration_seconds"]
                })

            elif path == "/api/generate/video-prompts":
                api_key = data.get("openai_key", "").strip()
                scenes = data.get("scenes", [])
                folder_name = data.get("folder_name", "").strip()

                prompts_result = generate_video_prompts(api_key=api_key, scenes=scenes)
                
                if folder_name:
                    p_dir = os.path.join(RESULT_DIR, folder_name)
                    os.makedirs(p_dir, exist_ok=True)
                    with open(os.path.join(p_dir, "prompts.json"), "w", encoding="utf-8") as f:
                        json.dump({p["scene_index"]: p["prompt"] for p in prompts_result}, f, ensure_ascii=False, indent=2)

                return self.send_json_success({
                    "status": "success",
                    "prompts": prompts_result
                })

            elif path == "/api/generate/image":
                api_key = data.get("openai_key", "").strip()
                prompt = data.get("prompt", "").strip()
                scene_index = data.get("scene_index", 0)
                folder_name = data.get("folder_name", "").strip()

                if not api_key:
                    return self.send_json_error(400, "OpenAI API Key is required")
                if not prompt:
                    return self.send_json_error(400, "Image prompt is required")

                if folder_name:
                    img_dir = os.path.join(RESULT_DIR, folder_name, "images")
                    os.makedirs(img_dir, exist_ok=True)
                    img_filename = f"scene_{scene_index}.png"
                    output_path = os.path.join(img_dir, img_filename)
                    image_url = f"/result/{folder_name}/images/{img_filename}"
                else:
                    img_filename = f"scene_{scene_index}_{int(os.times().elapsed * 1000)}.png"
                    output_path = os.path.join(STATIC_DIR, "images", img_filename)
                    image_url = f"/static/images/{img_filename}"

                res_path = generate_image(
                    api_key=api_key,
                    prompt=prompt,
                    output_image_path=output_path
                )

                return self.send_json_success({
                    "status": "success",
                    "scene_index": scene_index,
                    "image_url": image_url,
                    "image_path": res_path
                })

            elif path == "/api/upload/flow-video":
                folder_name = data.get("folder_name", "folder_1").strip()
                filename = data.get("filename", "flow_video.mp4").strip()
                file_base64 = data.get("file_data", "")

                if not file_base64:
                    return self.send_json_error(400, "file_data (base64) is required")

                p_dir = os.path.join(RESULT_DIR, folder_name, "flow_videos")
                os.makedirs(p_dir, exist_ok=True)

                # sanitize filename
                clean_filename = f"{int(os.times().elapsed * 1000)}_{os.path.basename(filename)}"
                save_path = os.path.join(p_dir, clean_filename)

                import base64
                if "," in file_base64:
                    file_base64 = file_base64.split(",", 1)[1]

                with open(save_path, "wb") as f:
                    f.write(base64.b64decode(file_base64))

                return self.send_json_success({
                    "status": "success",
                    "video": {
                        "video_name": clean_filename,
                        "video_url": f"/result/{folder_name}/flow_videos/{clean_filename}",
                        "video_path": save_path
                    }
                })

            elif path == "/api/delete/flow-video":
                folder_name = data.get("folder_name", "folder_1").strip()
                filename = data.get("filename", "").strip()
                if filename:
                    target_path = os.path.join(RESULT_DIR, folder_name, "flow_videos", os.path.basename(filename))
                    if os.path.exists(target_path):
                        try:
                            os.remove(target_path)
                        except Exception:
                            pass
                return self.send_json_success({"status": "success"})

            elif path == "/api/automate/flow-video":
                folder_name = data.get("folder_name", "folder_1").strip()
                prompt = data.get("prompt", "").strip()
                target_url = data.get("target_url", "https://labs.google/fx/tools/flow").strip()

                if not prompt:
                    return self.send_json_error(400, "Prompt is required for automation")

                p_dir = os.path.join(RESULT_DIR, folder_name, "flow_videos")
                os.makedirs(p_dir, exist_ok=True)

                try:
                    import backend.services.flow_automation_service as flow_auto_mod
                    import importlib
                    importlib.reload(flow_auto_mod)

                    res_videos = flow_auto_mod.run_flow_automation(
                        prompt=prompt,
                        output_dir=p_dir,
                        target_url=target_url,
                        headless=False
                    )

                    return self.send_json_success({
                        "status": "success",
                        "videos": res_videos
                    })
                except Exception as auto_err:
                    return self.send_json_error(500, f"[Flow 브라우저 자동화 오류] {str(auto_err)}")

            elif path == "/api/generate/flow-video":
                # Step 5: Flow AI Video Generator (Stub step as requested by user)
                scene_index = data.get("scene_index", 0)
                image_url = data.get("image_url", "")
                image_path = data.get("image_path", "")

                return self.send_json_success({
                    "status": "skipped",
                    "message": "Step 5 (Flow Video) skipped per user workflow setting.",
                    "scene_index": scene_index,
                    "output_video_url": None,
                    "fallback_image_url": image_url,
                    "fallback_image_path": image_path
                })

            elif path == "/api/render/video":
                image_paths = data.get("image_paths", [])
                audio_path = data.get("audio_path", "")
                srt_path = data.get("srt_path", "")
                duration = float(data.get("duration", 10.0))
                aspect_ratio = data.get("aspect_ratio", "9:16")
                folder_name = data.get("folder_name", "").strip()

                if not image_paths:
                    return self.send_json_error(400, "At least one scene image is required for rendering")
                if not audio_path or not os.path.exists(audio_path):
                    return self.send_json_error(400, "Valid TTS audio path is required")

                # Verify image paths exist locally
                valid_images = [img for img in image_paths if os.path.exists(img)]
                if not valid_images:
                    return self.send_json_error(400, "No valid image files found on server")

                if folder_name:
                    p_dir = os.path.join(RESULT_DIR, folder_name)
                    os.makedirs(p_dir, exist_ok=True)
                    output_filename = "final_video.mp4"
                    output_video_path = os.path.join(p_dir, output_filename)
                    video_url = f"/result/{folder_name}/{output_filename}"
                else:
                    output_filename = f"final_video_{int(os.times().elapsed * 1000)}.mp4"
                    output_video_path = os.path.join(OUTPUT_DIR, output_filename)
                    video_url = f"/output/{output_filename}"

                final_mp4 = render_video_with_ffmpeg(
                    image_paths=valid_images,
                    audio_path=audio_path,
                    srt_path=srt_path,
                    output_video_path=output_video_path,
                    total_duration=duration,
                    aspect_ratio=aspect_ratio
                )

                return self.send_json_success({
                    "status": "success",
                    "video_url": video_url,
                    "filename": output_filename
                })

            else:
                self.send_json_error(404, f"API endpoint '{path}' not found")

        except Exception as e:
            traceback.print_exc()
            self.send_json_error(500, str(e))

    def send_json_success(self, payload: dict, status_code: int = 200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

    def send_json_error(self, status_code: int, error_message: str):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"error": error_message, "status": "error"}, ensure_ascii=False).encode('utf-8'))

def run_server(start_port=8080):
    port = int(os.environ.get("PORT", start_port))
    max_attempts = 10
    httpd = None

    for attempt in range(max_attempts):
        current_port = port + attempt
        try:
            server_address = ('', current_port)
            httpd = socketserver.ThreadingTCPServer(server_address, AutoVideoHandler)
            httpd.allow_reuse_address = True
            print(f"🚀 Auto Video Generator Web Server running at http://localhost:{current_port}")
            break
        except OSError as e:
            if e.errno == 48: # Address already in use
                print(f"⚠️ Port {current_port} is already in use, trying port {current_port + 1}...")
                continue
            else:
                raise e

    if httpd is None:
        print(f"❌ Failed to bind to any port in range {port}-{port + max_attempts - 1}")
        return

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
