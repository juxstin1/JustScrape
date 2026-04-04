"""
Centralized URL validation for SSRF protection.

All outbound HTTP requests MUST pass through validate_url() before execution.
Blocks private IPs, non-HTTP schemes, and known-dangerous endpoints.
"""

import ipaddress
import socket
from urllib.parse import urlparse
from typing import Tuple

from .config import ALLOWED_SCHEMES, BLOCKED_HOSTNAMES


def validate_url(url: str) -> Tuple[bool, str]:
    """
    Validate that a URL is safe for outbound HTTP requests.

    Checks:
    1. URL is non-empty and parseable
    2. Scheme is http or https
    3. Hostname does not resolve to private/loopback/link-local IP
    4. Hostname is not a known cloud metadata endpoint

    Returns:
        (is_safe, reason) -- reason is "ok" if safe, or a description of why blocked.
    """
    if not url or not isinstance(url, str):
        return False, "empty_or_invalid_url"

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "url_parse_error"

    # Check scheme
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return False, f"blocked_scheme:{scheme or 'none'}"

    hostname = parsed.hostname
    if not hostname:
        return False, "no_hostname"

    # Check known blocked hostnames
    hostname_lower = hostname.lower()
    if hostname_lower in BLOCKED_HOSTNAMES:
        return False, f"blocked_hostname:{hostname_lower}"

    # Resolve hostname and check all IPs
    try:
        # Try parsing as IP literal first (avoids DNS lookup)
        try:
            ip = ipaddress.ip_address(hostname)
            if _is_dangerous_ip(ip):
                return False, f"private_ip:{ip}"
            return True, "ok"
        except ValueError:
            pass  # Not an IP literal, resolve via DNS

        # DNS resolution -- check all returned addresses
        port = parsed.port or (443 if scheme == 'https' else 80)
        addr_infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)

        if not addr_infos:
            return False, "dns_no_results"

        for family, _, _, _, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if _is_dangerous_ip(ip):
                return False, f"private_ip:{ip}"

    except socket.gaierror:
        return False, "dns_resolution_failed"
    except Exception:
        return False, "ip_check_error"

    return True, "ok"


def _is_dangerous_ip(ip) -> bool:
    """Check if an IP address is private, loopback, link-local, or otherwise dangerous."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def is_safe_url(url: str) -> bool:
    """Convenience wrapper -- returns True if URL passes validation."""
    ok, _ = validate_url(url)
    return ok


def validate_url_or_raise(url: str) -> str:
    """Validate URL, raising ValueError if unsafe. Returns the URL if safe."""
    ok, reason = validate_url(url)
    if not ok:
        raise ValueError(f"URL blocked: {reason}")
    return url
