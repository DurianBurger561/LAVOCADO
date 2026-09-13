"""Optional grouping tags. Ground truth stays Block / Allow."""

from __future__ import annotations

TAG_CATALOG: tuple[tuple[str, str], ...] = (
    ("explicit", "Explicit"),
    ("non_pornographic_purpose", "Non-pornographic Purpose"),
    ("medical", "Medical"),
    ("education", "Education"),
    ("art", "Art"),
    ("news", "News"),
    ("fitness", "Fitness"),
    ("swimwear", "Swimwear"),
    ("small_target", "Small Target"),
    ("medium_target", "Medium Target"),
    ("large_target", "Large Target"),
    ("partial_visibility", "Partial Visibility"),
    ("multiple_targets", "Multiple Targets"),
    ("video_frame", "Video Frame"),
    ("chat_media", "Chat Media"),
    ("image_viewer", "Image Viewer"),
    ("game_scene", "Game Scene"),
    ("browser", "Browser"),
    ("other", "Other"),
)

CANONICAL_TAGS = frozenset(slug for slug, _label in TAG_CATALOG)
TAG_LABELS = dict(TAG_CATALOG)
NON_PORNOGRAPHIC_PURPOSE = "non_pornographic_purpose"
PURPOSE_SUBTAGS = frozenset({"medical", "education", "art", "news", "fitness"})
RECALL_TAGS = frozenset(
    {
        "small_target",
        "medium_target",
        "large_target",
        "partial_visibility",
        "multiple_targets",
        "video_frame",
        "chat_media",
        "image_viewer",
        "game_scene",
        "browser",
        "explicit",
    }
)


def normalize_tag(value: object) -> str | None:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "nonpornographic_purpose": NON_PORNOGRAPHIC_PURPOSE,
        "non_pornographic": NON_PORNOGRAPHIC_PURPOSE,
        "non_pornographic_purpose_content": NON_PORNOGRAPHIC_PURPOSE,
        "small": "small_target",
        "medium": "medium_target",
        "large": "large_target",
        "partial": "partial_visibility",
    }
    slug = aliases.get(raw, raw)
    return slug if slug in CANONICAL_TAGS else None


def normalize_tags(values: object) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        items = [values]
    elif isinstance(values, (list, tuple, set, frozenset)):
        items = list(values)
    else:
        return set()
    tags: set[str] = set()
    for item in items:
        slug = normalize_tag(item)
        if slug is not None:
            tags.add(slug)
    return tags


def catalog_payload() -> list[dict[str, str]]:
    return [{"id": slug, "label": label} for slug, label in TAG_CATALOG]
