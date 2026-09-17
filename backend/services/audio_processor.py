import subprocess
import os
import re
from backend.services.srt_generator import format_timestamp, parse_srt_to_list, srt_time_to_seconds

def get_audio_duration(audio_path: str) -> float:
    """Returns exact audio duration in seconds using ffprobe"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 0.0

def detect_silence_intervals(audio_path: str, noise_db: int = -40, min_duration: float = 0.1) -> list:
    """
    Detects silence intervals [(start1, end1), (start2, end2), ...] in seconds using ffmpeg silencedetect filter.
    """
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}s",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    silence_starts = []
    silence_ends = []
    
    for line in res.stderr.split("\n"):
        if "silence_start:" in line:
            m = re.search(r"silence_start:\s*([\d\.]+)", line)
            if m:
                silence_starts.append(float(m.group(1)))
        elif "silence_end:" in line:
            m = re.search(r"silence_end:\s*([\d\.]+)", line)
            if m:
                silence_ends.append(float(m.group(1)))

    intervals = []
    total_dur = get_audio_duration(audio_path)
    for i in range(len(silence_starts)):
        start = silence_starts[i]
        end = silence_ends[i] if i < len(silence_ends) else total_dur
        intervals.append((start, end))

    return intervals

def compute_keep_intervals(total_duration: float, silence_intervals: list, pad: float = 0.02) -> list:
    """
    Inverts silence intervals to derive non-silent speech intervals [(start, end), ...]
    """
    if not silence_intervals:
        return [(0.0, total_duration)]

    keep = []
    current_pos = 0.0

    for s_start, s_end in silence_intervals:
        speech_start = current_pos
        speech_end = max(0.0, s_start - pad)
        
        if speech_end > speech_start + 0.01:
            keep.append((speech_start, speech_end))
        current_pos = min(total_duration, s_end + pad)

    if current_pos < total_duration - 0.01:
        keep.append((current_pos, total_duration))

    return keep

def map_time(t: float, keep_intervals: list) -> float:
    """
    Maps original timestamp t to the output timestamp after silence removal.
    """
    accum = 0.0
    for start, end in keep_intervals:
        if t <= start:
            return accum
        elif t <= end:
            return accum + (t - start)
        else:
            accum += (end - start)
    return accum

def remap_srt_content(srt_content: str, keep_intervals: list, speed: float = 1.0) -> str:
    """
    Remaps SRT subtitle content according to keep_intervals (silence cut) and speed factor.
    """
    subs = parse_srt_to_list(srt_content)
    if not subs:
        return srt_content

    new_subs = []
    sub_idx = 1

    for sub in subs:
        orig_start = sub["start"]
        orig_end = sub["end"]

        mapped_start = map_time(orig_start, keep_intervals) / speed
        mapped_end = map_time(orig_end, keep_intervals) / speed

        if mapped_end - mapped_start >= 0.05:
            start_str = format_timestamp(mapped_start)
            end_str = format_timestamp(mapped_end)
            new_subs.append(f"{sub_idx}\n{start_str} --> {end_str}\n{sub['text']}\n")
            sub_idx += 1

    return "\n".join(new_subs)

def process_audio_silence_and_speed(
    input_audio_path: str,
    output_audio_path: str,
    input_srt_path: str = None,
    output_srt_path: str = None,
    remove_silence: bool = True,
    silence_db: int = -40,
    speed: float = 1.0,
    min_silence_len: float = 0.1
) -> dict:
    """
    Processes audio to remove silence (<= silence_db) and adjust speed (1.0x to 2.0x).
    Also updates SRT file and timestamps if input_srt_path is provided.
    """
    total_duration = get_audio_duration(input_audio_path)
    if total_duration <= 0:
        total_duration = 10.0

    silence_intervals = []
    if remove_silence:
        silence_intervals = detect_silence_intervals(input_audio_path, noise_db=silence_db, min_duration=min_silence_len)

    keep_intervals = compute_keep_intervals(total_duration, silence_intervals)

    # Build FFmpeg filter chain
    if remove_silence and silence_intervals and len(keep_intervals) > 0:
        filter_complex_parts = []
        concat_inputs = []
        for i, (k_start, k_end) in enumerate(keep_intervals):
            filter_complex_parts.append(f"[0:a]atrim=start={k_start:.3f}:end={k_end:.3f},asetpts=PTS-STARTPTS[a{i}]")
            concat_inputs.append(f"[a{i}]")
        
        concat_str = "".join(concat_inputs) + f"concat=n={len(keep_intervals)}:v=0:a=1[acut]"
        filter_complex_parts.append(concat_str)

        if speed != 1.0:
            filter_complex_parts.append(f"[acut]atempo={speed}[aout]")
            out_map = "[aout]"
        else:
            out_map = "[acut]"

        full_filter_complex = ";".join(filter_complex_parts)
        cmd = [
            "ffmpeg", "-y", "-i", input_audio_path,
            "-filter_complex", full_filter_complex,
            "-map", out_map,
            "-c:a", "libmp3lame", output_audio_path
        ]
    else:
        cmd = ["ffmpeg", "-y", "-i", input_audio_path]
        if speed != 1.0:
            cmd.extend(["-af", f"atempo={speed}"])
        cmd.extend(["-c:a", "libmp3lame", output_audio_path])

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        fallback_af = []
        if remove_silence:
            fallback_af.append(f"silenceremove=stop_periods=-1:stop_duration={min_silence_len}:stop_threshold={silence_db}dB")
        if speed != 1.0:
            fallback_af.append(f"atempo={speed}")
        
        fallback_cmd = ["ffmpeg", "-y", "-i", input_audio_path]
        if fallback_af:
            fallback_cmd.extend(["-af", ",".join(fallback_af)])
        fallback_cmd.extend(["-c:a", "libmp3lame", output_audio_path])
        subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)

    new_duration = get_audio_duration(output_audio_path)

    # Process SRT if provided
    srt_content = ""
    target_srt_path = output_srt_path or input_srt_path
    if input_srt_path and os.path.exists(input_srt_path):
        with open(input_srt_path, "r", encoding="utf-8") as f:
            orig_srt = f.read()
        
        srt_content = remap_srt_content(orig_srt, keep_intervals, speed=speed)
        
        if target_srt_path:
            os.makedirs(os.path.dirname(target_srt_path), exist_ok=True)
            with open(target_srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)

    return {
        "status": "success",
        "audio_path": output_audio_path,
        "srt_path": target_srt_path,
        "srt_content": srt_content,
        "duration_seconds": new_duration,
        "original_duration": total_duration,
        "speed": speed,
        "silence_removed": remove_silence,
        "silence_db": silence_db
    }
