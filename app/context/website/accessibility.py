"""Conservative address-bar discovery shared by native accessibility readers."""

from __future__ import annotations

from collections import deque
from typing import Any, Protocol

from app.context.website.normalization import normalize_hostname

# Stable automation IDs where exposed by browsers, plus known address-bar
# accessibility names. Unknown/localized controls fail closed as UNKNOWN.
ADDRESS_IDS = frozenset(
    {
        "addresseditbox",
        "addressfield",
        "location-entry",
        "locationentry",
        "omnibox",
        "urlbar-input",
    }
)
ADDRESS_NAMES = frozenset(
    {
        "address and search",
        "address and search bar",
        "address bar",
        "location bar",
        "search or enter address",
        "smart search field",
        "unified search field",
    }
)


class TraversalLimitExceeded(RuntimeError):
    """The browser chrome tree could not be inspected completely."""


class AccessibilityTree(Protocol):
    def role(self, node: Any) -> str: ...

    def identifier(self, node: Any) -> str | None: ...

    def name(self, node: Any) -> str | None: ...

    def value(self, node: Any) -> str | None: ...

    def children(self, node: Any, limit: int) -> list[Any]: ...


def find_address_hostname(
    root: Any,
    tree: AccessibilityTree,
    *,
    max_nodes: int = 160,
    max_depth: int = 8,
    max_children: int = 40,
) -> str | None:
    """Return one unambiguous hostname from browser chrome, not page content."""

    if root is None:
        return None
    queue = deque([(root, 0)])
    visited = 0
    hostnames: set[str] = set()
    try:
        while queue and visited < max_nodes:
            node, depth = queue.popleft()
            visited += 1
            role = tree.role(node)
            if role == "document":
                continue
            if role == "edit":
                identifier = (tree.identifier(node) or "").strip().casefold()
                name = (tree.name(node) or "").strip().casefold()
                if identifier in ADDRESS_IDS or name in ADDRESS_NAMES:
                    hostname = normalize_hostname(tree.value(node))
                    if hostname is not None:
                        hostnames.add(hostname)
                        if len(hostnames) > 1:
                            return None
                continue
            if depth >= max_depth:
                if tree.children(node, 1):
                    return None
                continue
            remaining = max_nodes - visited - len(queue)
            if remaining <= 0:
                if tree.children(node, 1):
                    return None
                continue
            queue.extend(
                (child, depth + 1)
                for child in tree.children(node, min(max_children, remaining))
            )
    except TraversalLimitExceeded:
        return None
    if queue:
        return None
    return next(iter(hostnames)) if len(hostnames) == 1 else None
