"""Listing sources for MyHome.ge.

``api`` is the primary source; ``html_fallback`` (Patch 3) is used automatically
when the API fails. Both return ``list[Listing]``.
"""

from __future__ import annotations


class SourceError(RuntimeError):
    """A listing source failed in a way retries will not fix."""
