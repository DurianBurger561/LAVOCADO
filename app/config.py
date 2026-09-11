"""Central configuration for LAVOCADO."""

# Seconds between screen checks.
CHECK_INTERVAL = 0.75

# Maximum width/height passed to the vision detector.
THUMBNAIL_SIZE = 320

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

# Blocked applications and websites.
BLOCKED_APPS: list[str] = []

# Blocking interface colours.
OVERLAY_BG = "#1e1e2e"
OVERLAY_TITLE_COLOR = "#cba6f7"
OVERLAY_TEXT_COLOR = "#cdd6f4"
OVERLAY_BUTTON_BG = "#313244"
OVERLAY_BUTTON_TEXT_COLOR = "#a6e3a1"

# Blocking interface text.
OVERLAY_TITLE_TEXT = "Take a moment"
OVERLAY_BODY_TEXT = (
    "Pause and take a breath. When you are ready, close the triggering page."
)
OVERLAY_BUTTON_LABEL = "Give me a moment"
