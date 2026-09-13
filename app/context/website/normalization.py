"""Reduce an address-bar value to a validated hostname immediately."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_hostname(address: str | None) -> str | None:
    """Return only the host; reject non-web, malformed, or ambiguous addresses.

    The full input is never logged, cached, or included in an exception. Native
    address-bar readers should call this before publishing a WebsiteContext.
    """

    if not isinstance(address, str):
        return None
    value = address.strip()
    if (
        not value
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return None
    if "://" in value and not _SCHEME.match(value):
        return None
    if _SCHEME.match(value):
        if value.partition("://")[0].casefold() not in {"http", "https"}:
            return None
        candidate = value
    elif ":" in value.split("/", 1)[0] and not value.startswith("["):
        # Reject address-bar pseudo-schemes such as about: and javascript:.
        return None
    else:
        candidate = "https://" + value

    try:
        parsed = urlsplit(candidate)
        if parsed.username is not None or parsed.password is not None:
            return None
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not host or (port is not None and not 1 <= port <= 65535):
        return None

    try:
        return str(ipaddress.ip_address(host)).casefold()
    except ValueError:
        pass
    try:
        ascii_host = host.rstrip(".").encode("idna").decode("ascii").casefold()
    except (UnicodeError, ValueError):
        return None
    if len(ascii_host) > 253:
        return None
    labels = ascii_host.split(".")
    if len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels):
        return None
    return ascii_host
