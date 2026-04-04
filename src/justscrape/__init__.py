"""JustScrape — God-status web search MCP server for AI."""

__version__ = "2.0.4"


def main():
    """Entry point: run MCP server by default, or handle subcommands."""
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "setup":
            from .cli import cmd_setup
            cmd_setup()
            return
        elif cmd == "doctor":
            from .cli import cmd_doctor
            cmd_doctor()
            return
        elif cmd == "--version":
            print(f"justscrape {__version__}")
            return
        elif cmd == "--help":
            print(f"justscrape {__version__}")
            print()
            print("Usage:")
            print("  justscrape          Start the MCP server (default)")
            print("  justscrape setup    Set up SearXNG via Docker")
            print("  justscrape doctor   Check health and dependencies")
            print("  justscrape --version  Show version")
            return

    # Default: run the MCP server
    import asyncio
    from .server import main as _server_main

    asyncio.run(_server_main())
