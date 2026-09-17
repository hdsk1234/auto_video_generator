import subprocess
import os
import shutil
import math

def render_video_with_ffmpeg(
    image_paths: list,
    audio_path: str,
    srt_path: str,
    output_video_path: str,
    total_duration: float,
    aspect_ratio: str = "9:16",  # 9:16 (Shorts/Reels) or 16:9 (Landscape)
    apply_zoom: bool = True
) -> str:
    """
    Renders high-quality MP4 video using FFmpeg by combining:
    - Scene images (with optional subtle Ken Burns zoom effect)
    - TTS audio track
    - SRT subtitle burn-in
    """
    if not image_paths:
        raise ValueError("At least one image path is required for video rendering.")
    if not os.path.exists(audio_path):
        raise ValueError(f"Audio file not found: {audio_path}")

    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
    temp_dir = os.path.join(os.path.dirname(output_video_path), "temp_render")
    os.makedirs(temp_dir, exist_ok=True)

    # Resolution settings
    if aspect_ratio == "9:16":
        width, height = 1080, 1920
    else:
        width, height = 1920, 1080

    num_images = len(image_paths)
    per_image_duration = max(2.0, total_duration / num_images) if total_duration > 0 else 5.0

    # Step 1: Render each image or video file into a standardized individual clip
    clip_files = []
    video_exts = {".mp4", ".mov", ".webm", ".avi", ".mkv"}
    for idx, media_path in enumerate(image_paths):
        clip_path = os.path.join(temp_dir, f"clip_{idx:03d}.mp4")
        ext = os.path.splitext(media_path)[1].lower()

        if ext in video_exts:
            # Media is already a video clip (e.g. Flow AI generated video)
            vf_filter = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=25,format=yuv420p"
            cmd = [
                "ffmpeg", "-y",
                "-i", media_path,
                "-vf", vf_filter,
                "-c:v", "libx264",
                "-an",
                "-pix_fmt", "yuv420p",
                clip_path
            ]
        else:
            # Media is an image file
            if apply_zoom:
                vf_filter = (
                    f"scale={width*2}:{height*2},"
                    f"zoompan=z='min(zoom+0.0015,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(per_image_duration*25)}:s={width}x{height},"
                    f"fps=25,format=yuv420p"
                )
            else:
                vf_filter = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=25,format=yuv420p"

            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", media_path,
                "-t", str(per_image_duration),
                "-vf", vf_filter,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                clip_path
            ]
        
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg Clip Processing Error (clip {idx}): {res.stderr}")
        clip_files.append(clip_path)

    # Step 2: Concatenate clips using concat filter / file list
    concat_list_path = os.path.join(temp_dir, "concat_list.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for clip in clip_files:
            f.write(f"file '{os.path.abspath(clip)}'\n")

    merged_video_path = os.path.join(temp_dir, "merged_video.mp4")
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        merged_video_path
    ]
    res_concat = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res_concat.returncode != 0:
        raise RuntimeError(f"FFmpeg Concat Error: {res_concat.stderr}")

    # Step 3: Combine merged video + audio + burn-in SRT subtitles
    # Prepare SRT style (White text, dark box/outline, centered bottom)
    escaped_srt = os.path.abspath(srt_path).replace("\\", "/").replace(":", "\\:")
    sub_style = "FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=4,Outline=2,Shadow=1,Alignment=2,MarginV=60"

    final_cmd = [
        "ffmpeg", "-y",
        "-i", merged_video_path,
        "-i", audio_path,
        "-vf", f"subtitles='{escaped_srt}':force_style='{sub_style}'",
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_video_path
    ]

    res_final = subprocess.run(final_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res_final.returncode != 0:
        # Fallback without subtitle filter if libass error occurs
        final_cmd_fallback = [
            "ffmpeg", "-y",
            "-i", merged_video_path,
            "-i", audio_path,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-shortest",
            output_video_path
        ]
        res_fb = subprocess.run(final_cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res_fb.returncode != 0:
            raise RuntimeError(f"FFmpeg Final Render Error: {res_fb.stderr}")

    # Clean up temporary clip directory
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass

    return output_video_path
