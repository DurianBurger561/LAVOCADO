"""Fixed application resources, deployment controls, and overlay copy."""

# NudeNet model input sizes. The 320 value is used only when the required
# 640m model asset is unavailable or cannot be loaded.
NUDENET_INFERENCE_RESOLUTION = 640
NUDENET_FALLBACK_INFERENCE_RESOLUTION = 320

# Conservative screen-change scheduling. Native dirty-region metadata is used
# when available; otherwise a small grayscale map avoids retaining full frames.
CHANGE_MAP_MAX_EDGE = 64
CHANGE_PIXEL_DELTA = 12
# A short, deterministic intervention before the dismiss button is enabled.
INTERVENTION_PAUSE_SECONDS = 3.0
INTERVENTION_BREATHE_SECONDS = 6.0

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
OVERLAY_READY_BODY = (
    "You are still in control. Close the triggering page, stand up, and take "
    "one small step toward what matters next."
)
OVERLAY_WAIT_BUTTON_LABEL = "Stay with the pause"
OVERLAY_READY_BUTTON_LABEL = "I'm ready to continue"
