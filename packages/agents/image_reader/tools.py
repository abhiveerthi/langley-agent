def get_image_reader_tools():
    """Image Reader has no LLM-callable tools.

    OCR and image analysis run on Claude's native vision — image content
    blocks are passed straight into ChatAnthropic, so there's nothing for the
    model to call out to. Transcription is handled by a graph node
    (packages/agents/core/transcription.py), not an LLM tool, so the model
    can't trigger an audio download on its own.

    The empty factory still exists so the manifest-truth guard
    (tests/test_manifest_truth.py) can assert manifest.tools == [] matches
    the registered set.
    """
    return []
