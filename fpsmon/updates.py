"""
Optional update check against the project's GitHub releases.

Deliberately limited: it asks GitHub for the latest release tag, compares it
with the running version, and says so. It never downloads or installs
anything, sends nothing about the machine, and can be switched off. A failure
is silent, because a monitoring overlay complaining about network errors while
you game would be worse than not checking at all.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import GITHUB_REPO, __version__

API = "https://api.github.com/repos/{repo}/releases/latest"
TIMEOUT = 6.0


@dataclass
class Release:
    version: str
    tag: str
    url: str
    notes: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Unparseable input sorts lowest."""
    nums = re.findall(r"\d+", (text or "").strip().lstrip("vV"))
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    # pad so (1, 1) and (1, 1, 0) compare equal rather than by length
    size = max(len(a), len(b))
    a = a + (0,) * (size - len(a))
    b = b + (0,) * (size - len(b))
    return a > b


def latest_release(repo: str = GITHUB_REPO) -> Release | None:
    """Ask GitHub for the newest published release, or None on any failure."""
    req = urllib.request.Request(
        API.format(repo=repo),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"FPSMonitor/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    except Exception:
        return None

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None
    return Release(
        version=tag.lstrip("vV"),
        tag=tag,
        url=str(data.get("html_url") or ""),
        notes=str(data.get("body") or "")[:400],
    )


def check(repo: str = GITHUB_REPO, current: str = __version__) -> Release | None:
    """The newest release if it is ahead of `current`, otherwise None."""
    rel = latest_release(repo)
    if rel is None:
        return None
    return rel if is_newer(rel.version, current) else None
