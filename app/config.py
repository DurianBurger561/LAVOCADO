"""Fixed application resources, deployment controls, and overlay copy."""

import os

# NudeNet model input sizes. The 320 value is used only when the required
# 640m model asset is unavailable or cannot be loaded.
NUDENET_INFERENCE_RESOLUTION = 640
NUDENET_FALLBACK_INFERENCE_RESOLUTION = 320

# Pinned local context model asset identifiers.
CONTEXT_MODEL_NAME = "viddexa/nsfw-detection-2-mini"
CONTEXT_MODEL_REVISION = "15f61cddc0a1a2a9176f018fb6838ef92c8163cc"
CONTEXT_MINI_MODEL_NAME = CONTEXT_MODEL_NAME
CONTEXT_MINI_MODEL_REVISION = CONTEXT_MODEL_REVISION
CONTEXT_NANO_MODEL_NAME = "viddexa/nsfw-detection-2-nano"
CONTEXT_NANO_MODEL_REVISION = "12e57200346246b37382f746e4d94d10b014f6a1"

# Conservative screen-change scheduling. Native dirty-region metadata is used
# when available; otherwise a small grayscale map avoids retaining full frames.
CHANGE_MAP_MAX_EDGE = 64
CHANGE_PIXEL_DELTA = 12
CHANGE_PERIODIC_SCAN_INTERVAL = 8

# None selects the primary monitor automatically. Set an integer to override it.
MONITOR_INDEX: int | None = None

# Time given to close the triggering content after dismissing the overlay.
COOLDOWN_SECONDS = 8.0

# A short, deterministic intervention before the dismiss button is enabled.
INTERVENTION_PAUSE_SECONDS = 3.0
INTERVENTION_BREATHE_SECONDS = 6.0
INTERVENTION_MODEL = os.environ.get("LAVOCADO_OPENAI_MODEL", "gpt-5.6-luna")
INTERVENTION_API_TIMEOUT_SECONDS = 6.0
INTERVENTION_MAX_OUTPUT_TOKENS = 80

# Blocking interface colours.
OVERLAY_BG = "#1e1e2e"
OVERLAY_TITLE_COLOR = "#cba6f7"
OVERLAY_TEXT_COLOR = "#cdd6f4"
OVERLAY_BUTTON_BG = "#313244"
OVERLAY_BUTTON_TEXT_COLOR = "#a6e3a1"

# Blocking interface text.
OVERLAY_PAUSE_TITLE = "Pause for a moment"
OVERLAY_PAUSE_BODY = "Look away from the triggering content and let the urge pass."
OVERLAY_BREATHE_TITLE = "Take one slow breath"
OVERLAY_BREATHE_BODY = "Breathe in gently, then breathe out a little more slowly."
OVERLAY_READY_TITLE = "Choose your next action"
OVERLAY_READY_BODY = "Close the triggering page before returning to your screen."
OVERLAY_WAIT_BUTTON_LABEL = "Stay with the pause"
OVERLAY_READY_BUTTON_LABEL = "I'm ready to continue"
