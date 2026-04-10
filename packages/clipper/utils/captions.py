"""Generate SRT subtitle files from word-level transcripts."""


def _format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT time format: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(
    transcript: list[dict],
    clip_start: float,
    clip_end: float,
    output_path: str,
) -> str:
    """Generate an SRT subtitle file for a clip segment.

    Args:
        transcript: Word-level transcript [{word, start, end}, ...].
        clip_start: Start time of the clip in the original video.
        clip_end: End time of the clip in the original video.
        output_path: Where to write the .srt file.

    Returns:
        Path to the generated .srt file.
    """
    # Filter words within clip range
    clip_words = [
        w for w in transcript
        if w["end"] > clip_start and w["start"] < clip_end
    ]

    # Group words into lines (max 4 words per line for readability on 9:16)
    lines: list[dict] = []
    current_words: list[dict] = []

    for word in clip_words:
        current_words.append(word)
        if len(current_words) >= 4:
            lines.append({
                "text": " ".join(w["word"] for w in current_words),
                "start": current_words[0]["start"] - clip_start,
                "end": current_words[-1]["end"] - clip_start,
            })
            current_words = []

    if current_words:
        lines.append({
            "text": " ".join(w["word"] for w in current_words),
            "start": current_words[0]["start"] - clip_start,
            "end": current_words[-1]["end"] - clip_start,
        })

    # Build SRT content
    srt_content = ""
    for i, line in enumerate(lines, 1):
        start = _format_srt_time(max(0, line["start"]))
        end = _format_srt_time(line["end"])
        text = line["text"].strip()
        srt_content += f"{i}\n{start} --> {end}\n{text}\n\n"

    with open(output_path, "w") as f:
        f.write(srt_content)

    return output_path
