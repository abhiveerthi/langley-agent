from typing import TypedDict


class Clip(TypedDict):
    start: float
    end: float
    title: str
    score: float


class ClipperState(TypedDict):
    video_url: str
    video_path: str
    metadata: dict
    heatmap: list[dict]
    transcript: list[dict]
    clips: list[Clip]
    output_paths: list[str]
    storage_urls: list[str]
