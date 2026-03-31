#!/usr/bin/env python3
"""Backward-compatible entry point for existing MCP client configs.

If your config points to this file:
    {"command": "python", "args": ["/path/to/JustScrape/justscrape_mcp.py"]}

It will still work. This shim prefers the repo-local virtualenv when present so
clients do not depend on whichever Python happens to be on PATH.
"""

from __future__ import annotations

import site
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
TARGET_SITE_PACKAGES = REPO_ROOT / ".venv" / "Lib" / "site-packages"

if TARGET_SITE_PACKAGES.exists():
    site.addsitedir(str(TARGET_SITE_PACKAGES))
    print(
        "[justscrape] Running via legacy justscrape_mcp.py shim. "
        f"Loading site-packages from {TARGET_SITE_PACKAGES}",
        file=sys.stderr,
    )

print(
    "[justscrape] Running via legacy justscrape_mcp.py shim.",
    file=sys.stderr,
)

from justscrape import main

main()
