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

# Optional local context classifier. Its weights are downloaded by Transformers
# during development and are never sent screenshots over the network.
CONTEXT_MODEL_ENABLED = True
CONTEXT_MODEL_NAME = "viddexa/nsfw-detection-2-mini"
CONTEXT_MODEL_REVISION = "15f61cddc0a1a2a9176f018fb6838ef92c8163cc"
CONTEXT_MINI_MODEL_NAME = CONTEXT_MODEL_NAME
CONTEXT_MINI_MODEL_REVISION = CONTEXT_MODEL_REVISION
CONTEXT_NANO_MODEL_NAME = "viddexa/nsfw-detection-2-nano"
CONTEXT_NANO_MODEL_REVISION = "12e57200346246b37382f746e4d94d10b014f6a1"

# Selectable primary detector and context ranker. Env overrides are for
# development; persisted vision_settings.json wins when present.
PRIMARY_DETECTOR = os.environ.get("LAVOCADO_PRIMARY_DETECTOR", "nudenet_640m")
CONTEXT_RANKER = os.environ.get("LAVOCADO_CONTEXT_MODEL", "viddexa_mini")
YOLO_FULL_INPUT_SIZE = 640
YOLO_TILE_INPUT_SIZE = 640

# Conservative starting values for benchmark calibration, not scientifically
# validated optimal thresholds.
NUDENET_BORDERLINE_MARGIN = 0.10
CONTEXT_CROP_EXPANSION = 1.75
# Viddexa ranks tiles by porn/hentai risk. It cannot confirm or block.
CONTEXT_PORN_CONFIRM_THRESHOLD = 0.90
CONTEXT_PORN_RESCUE_THRESHOLD = 0.97
CONTEXT_SEXY_CAN_BLOCK = False
CONTEXT_HENTAI_CAN_BLOCK = False
YOLO_ENABLED = False
# Optional existing YOLO11 NSFW weights. Set LAVOCADO_YOLO_MODEL to a local
# .pt or .onnx file; LAVOCADO never trains or downloads this model.
RESCUE_ENABLED = True
RESCUE_TILE_ROWS = 2
RESCUE_TILE_COLUMNS = 2
RESCUE_TILE_OVERLAP = 0.15
RESCUE_CHECKS_PER_SCAN = 1
RESCUE_MAX_TILE_SKIP = 3

# Conservative screen-change scheduling. Native dirty-region metadata is used
# when available; otherwise a small grayscale map avoids retaining full frames.
CHANGE_MAP_MAX_EDGE = 64
CHANGE_PIXEL_DELTA = 12
CHANGE_RATIO_THRESHOLD = 0.01
CHANGE_PERIODIC_SCAN_INTERVAL = 8

# None selects the primary monitor automatically. Set an integer to override it.
MONITOR_INDEX: int | None = None

# Starting thresholds for NudeNet visual-violation labels.
# These are product defaults, not scientifically validated values.
# Mapping onto ViolationEvidenceType lives in app.vision.violation_policy.
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
