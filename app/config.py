"""Central configuration for LAVOCADO."""

import os

# Seconds between screen checks.
CHECK_INTERVAL = 0.75

# Maximum width/height retained for the whole-screen NudeNet pass.
MODEL_FRAME_MAX_EDGE = 640

# NudeNet model input sizes. The 320 value is used only when the optional
# 640m model asset is unavailable or cannot be loaded.
NUDENET_INFERENCE_RESOLUTION = 640
NUDENET_FALLBACK_INFERENCE_RESOLUTION = 320

# None selects the primary monitor automatically. Set an integer to override it.
MONITOR_INDEX: int | None = None

# Starting thresholds for the MVP.
# These are product defaults, not scientifically validated values.
BLOCK_THRESHOLDS = {
    "FEMALE_GENITALIA_EXPOSED": 0.45,
    "MALE_GENITALIA_EXPOSED": 0.45,
    "ANUS_EXPOSED": 0.50,
    "FEMALE_BREAST_EXPOSED": 0.65,
    "BUTTOCKS_EXPOSED": 0.70,
}

BLOCK_LABELS = frozenset(BLOCK_THRESHOLDS)

# Require two candidate frames within the latest three checks before blocking.
CONFIRMATION_WINDOW_SIZE = 3
CONFIRMATION_REQUIRED_HITS = 2

# Time given to close the triggering content after dismissing the overlay.
COOLDOWN_SECONDS = 8.0

# A short, deterministic intervention before the dismiss button is enabled.
INTERVENTION_PAUSE_SECONDS = 3.0
INTERVENTION_BREATHE_SECONDS = 6.0
INTERVENTION_MODEL = os.environ.get("LAVOCADO_OPENAI_MODEL", "gpt-5.6-luna")
INTERVENTION_API_TIMEOUT_SECONDS = 6.0
INTERVENTION_MAX_OUTPUT_TOKENS = 80

# Case-insensitive terms matched against the foreground app name and window title.
# Examples: ["Steam", "reddit.com"]. Empty disables foreground-window inspection.
BLOCKED_APPS: list[str] = []

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
