"""CLI subcommands for JustScrape: setup, doctor."""

import os
import secrets
import shutil
import subprocess
import sys

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8080")


def _make_searxng_settings() -> str:
    return f"""\
use_default_settings: true
search:
  formats:
    - html
    - json
server:
  limiter: false
  secret_key: "{secrets.token_hex(16)}"
"""


def _print(msg: str, ok: bool = True):
    prefix = "  [ok]" if ok else "  [!!]"
    print(f"{prefix} {msg}")


def cmd_setup():
    """Set up SearXNG via Docker for high-quality search."""
    print("JustScrape Setup — SearXNG Search Backend\n")

    # Check Docker
    docker = shutil.which("docker")
    if not docker:
        print("ERROR: Docker is not installed or not in PATH.")
        print("Install Docker: https://docs.docker.com/get-docker/")
        sys.exit(1)
    _print("Docker found")

    # Check if container already running
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", "searxng"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "true" in result.stdout.lower():
            _print("SearXNG container already running")
            _verify_searxng()
            return
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Create settings file
    settings_dir = os.path.expanduser("~/searxng")
    settings_path = os.path.join(settings_dir, "settings.yml")
    os.makedirs(settings_dir, exist_ok=True)
    with open(settings_path, "w") as f:
        f.write(_make_searxng_settings())
    _print(f"Created {settings_path}")

    # Check if container exists but stopped
    try:
        result = subprocess.run(
            ["docker", "inspect", "searxng"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            # Container exists, just start it
            subprocess.run(
                ["docker", "start", "searxng"],
                capture_output=True, text=True, timeout=30,
            )
            _print("Started existing SearXNG container")
            _verify_searxng()
            return
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Pull and run
    print("\n  Pulling SearXNG image (this may take a minute)...")
    pull = subprocess.run(
        ["docker", "pull", "searxng/searxng"],
        capture_output=True, text=True, timeout=300,
    )
    if pull.returncode != 0:
        print(f"ERROR: Failed to pull image: {pull.stderr}")
        sys.exit(1)
    _print("Pulled searxng/searxng image")

    run = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", "searxng",
            "-p", "8080:8080",
            "-v", f"{settings_path}:/etc/searxng/settings.yml",
            "--restart", "unless-stopped",
            "searxng/searxng",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if run.returncode != 0:
        print(f"ERROR: Failed to start container: {run.stderr}")
        sys.exit(1)
    _print("Started SearXNG container on port 8080")

    _verify_searxng()


def _verify_searxng():
    """Wait for SearXNG to be ready and verify it works."""
    import time

    print("\n  Waiting for SearXNG to be ready...", end="", flush=True)
    for _ in range(15):
        try:
            import requests
            resp = requests.get(
                f"{SEARXNG_URL}/search",
                params={"q": "test", "format": "json"},
                timeout=3,
            )
            if resp.status_code == 200:
                print(" ready!")
                _print("SearXNG is working — JustScrape will use it automatically")
                return
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(2)

    print("\n  WARNING: SearXNG started but not responding yet. It may need more time.")


def cmd_doctor():
    """Check JustScrape health and dependencies."""
    print("JustScrape Doctor\n")
    all_ok = True

    # Python version
    v = sys.version_info
    ok = v >= (3, 10)
    _print(f"Python {v.major}.{v.minor}.{v.micro}", ok)
    if not ok:
        all_ok = False

    # MCP SDK
    try:
        import mcp
        _print(f"MCP SDK installed (v{getattr(mcp, '__version__', '?')})")
    except ImportError:
        _print("MCP SDK not installed", False)
        all_ok = False

    # SearXNG
    try:
        import requests
        resp = requests.get(
            f"{SEARXNG_URL}/search",
            params={"q": "test", "format": "json"},
            timeout=5,
        )
        if resp.status_code == 200:
            _print(f"SearXNG running at {SEARXNG_URL}")
        else:
            _print("SearXNG returned non-200 status", False)
            all_ok = False
    except Exception:
        _print("SearXNG not reachable (optional — DuckDuckGo fallback active)", False)

    # Playwright
    try:
        from playwright.sync_api import sync_playwright
        _print("Playwright installed (JS rendering available)")
    except ImportError:
        _print("Playwright not installed (optional — install with: pip install 'justscrape[browser]' && playwright install chromium)", False)

    # Docker
    docker = shutil.which("docker")
    if docker:
        _print("Docker available")
    else:
        _print("Docker not found (needed for SearXNG setup)", False)

    print()
    if all_ok:
        print("All checks passed!")
    else:
        print("Some optional components missing — JustScrape will still work with fallback backends.")
