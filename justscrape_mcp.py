#!/usr/bin/env python3
"""Backward-compatible entry point for existing MCP client configs.

If your config points to this file:
    {"command": "python", "args": ["/path/to/JustScrape/justscrape_mcp.py"]}

It will still work. For new setups, use:
    {"command": "uvx", "args": ["justscrape"]}
"""

import sys
print(
    "[justscrape] Running via legacy justscrape_mcp.py shim. "
    "Consider updating your config to: uvx justscrape",
    file=sys.stderr,
)

from justscrape import main
main()
