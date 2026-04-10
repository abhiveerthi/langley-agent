"""Deterministic video clipper workflow — linear StateGraph, no agent loops."""

from langgraph.graph import StateGraph, START, END

from packages.clipper.state import ClipperState
from packages.clipper.nodes.ingest import ingest
from packages.clipper.nodes.transcribe import transcribe
from packages.clipper.nodes.detect import detect_clips
from packages.clipper.nodes.render import render
from packages.clipper.nodes.upload import upload


def create_clipper_workflow() -> StateGraph:
    """Build the clipper pipeline: ingest → transcribe → detect → render → upload."""
    graph = StateGraph(ClipperState)

    graph.add_node("ingest", ingest)
    graph.add_node("transcribe", transcribe)
    graph.add_node("detect_clips", detect_clips)
    graph.add_node("render", render)
    graph.add_node("upload", upload)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "transcribe")
    graph.add_edge("transcribe", "detect_clips")
    graph.add_edge("detect_clips", "render")
    graph.add_edge("render", "upload")
    graph.add_edge("upload", END)

    return graph


def run_clipper(video_url: str) -> dict:
    """Compile and run the clipper workflow synchronously."""
    graph = create_clipper_workflow()
    app = graph.compile()
    result = app.invoke({"video_url": video_url})
    return result
