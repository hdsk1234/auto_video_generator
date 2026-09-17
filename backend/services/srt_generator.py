import json
import os
import re

def format_timestamp(seconds: float) -> str:
    """Converts seconds (float) to SRT timestamp string format: HH:MM:SS,mmm"""
    millis = int((seconds % 1) * 1000)
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def generate_srt_from_timestamps(alignment: dict, max_chars_per_line: int = 25, max_gap_seconds: float = 0.5) -> str:
    """
    Parses ElevenLabs with_timestamps alignment output and generates a standard SRT subtitle string.
    
    alignment format:
    {
      "characters": ["안", "녕", "하", "세", "요", ...],
      "character_start_times_seconds": [0.0, 0.1, ...],
      "character_end_times_seconds": [0.1, 0.2, ...]
    }
    """
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    if not chars or len(chars) != len(starts) or len(chars) != len(ends):
        return ""

    subtitles = []
    current_chunk = []
    chunk_start_time = None
    last_end_time = None

    for i in range(len(chars)):
        char = chars[i]
        start_time = starts[i]
        end_time = ends[i]

        if chunk_start_time is None:
            chunk_start_time = start_time

        # Check break conditions:
        # 1. Gap between characters is larger than max_gap_seconds
        # 2. Punctuation mark (. ! ? \n)
        # 3. Current chunk length exceeds max_chars_per_line (at a space)
        is_gap = last_end_time is not None and (start_time - last_end_time > max_gap_seconds)
        is_punct = char in ['.', '!', '?', '\n']
        is_length_overflow = len("".join(current_chunk)) >= max_chars_per_line and char == ' '

        current_chunk.append(char)
        last_end_time = end_time

        if is_punct or is_gap or is_length_overflow or i == len(chars) - 1:
            text = "".join(current_chunk).strip()
            if text:
                subtitles.append({
                    "start": chunk_start_time,
                    "end": end_time,
                    "text": text
                })
            current_chunk = []
            chunk_start_time = None

    # Build SRT file content
    srt_output = []
    for idx, sub in enumerate(subtitles, 1):
        start_str = format_timestamp(sub["start"])
        end_str = format_timestamp(sub["end"])
        srt_output.append(f"{idx}\n{start_str} --> {end_str}\n{sub['text']}\n")

    return "\n".join(srt_output)

def parse_srt_to_list(srt_content: str) -> list:
    """Parses SRT content into a list of dict objects [{'index': 1, 'start': 0.0, 'end': 2.5, 'text': '...'}]"""
    blocks = srt_content.strip().split('\n\n')
    result = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            idx = lines[0]
            times = lines[1].split(' --> ')
            if len(times) == 2:
                start_sec = srt_time_to_seconds(times[0])
                end_sec = srt_time_to_seconds(times[1])
                text = "\n".join(lines[2:])
                result.append({
                    "index": idx,
                    "start": start_sec,
                    "end": end_sec,
                    "text": text
                })
    return result

def srt_time_to_seconds(srt_time_str: str) -> float:
    """Converts HH:MM:SS,mmm to seconds (float)"""
    parts = srt_time_str.replace(',', '.').split(':')
    if len(parts) == 3:
        h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
        return h * 3600 + m * 60 + s
    return 0.0
