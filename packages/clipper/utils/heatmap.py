"""Extract and score heatmap peaks from yt-dlp metadata."""


def find_peaks(heatmap: list[dict], threshold_percentile: float = 80.0) -> list[dict]:
    """Find contiguous high-engagement segments from YouTube heatmap data.

    Args:
        heatmap: List of {start_time, end_time, value} from yt-dlp info JSON.
        threshold_percentile: Only keep segments above this percentile of intensity.

    Returns:
        List of {start, end, peak_value} for high-engagement regions.
    """
    if not heatmap:
        return []

    values = [h["value"] for h in heatmap]
    values.sort()
    threshold_idx = int(len(values) * threshold_percentile / 100)
    threshold = values[min(threshold_idx, len(values) - 1)]

    # Find contiguous segments above threshold
    peaks: list[dict] = []
    current_peak = None

    for segment in heatmap:
        if segment["value"] >= threshold:
            if current_peak is None:
                current_peak = {
                    "start": segment["start_time"],
                    "end": segment["end_time"],
                    "peak_value": segment["value"],
                }
            else:
                current_peak["end"] = segment["end_time"]
                current_peak["peak_value"] = max(current_peak["peak_value"], segment["value"])
        else:
            if current_peak is not None:
                peaks.append(current_peak)
                current_peak = None

    if current_peak is not None:
        peaks.append(current_peak)

    # Filter out very short peaks (< 10 seconds)
    peaks = [p for p in peaks if p["end"] - p["start"] >= 10]

    return sorted(peaks, key=lambda p: p["peak_value"], reverse=True)
