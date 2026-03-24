"""Tests for centralized URL validation (SSRF protection)."""

import pytest
from justscrape.url_validator import validate_url, is_safe_url, validate_url_or_raise


class TestSchemeValidation:
    """Verify only http/https schemes are allowed."""

    def test_allows_http(self):
        ok, reason = validate_url("http://example.com")
        assert ok is True
        assert reason == "ok"

    def test_allows_https(self):
        ok, reason = validate_url("https://example.com/page")
        assert ok is True

    def test_blocks_file_scheme(self):
        ok, reason = validate_url("file:///etc/passwd")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_file_scheme_windows(self):
        ok, reason = validate_url("file:///C:/Users/test/.ssh/id_rsa")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_data_scheme(self):
        ok, reason = validate_url("data:text/html,<script>alert(1)</script>")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_javascript_scheme(self):
        ok, reason = validate_url("javascript:alert(1)")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_ftp_scheme(self):
        ok, reason = validate_url("ftp://example.com/file")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_gopher_scheme(self):
        ok, reason = validate_url("gopher://evil.com/")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_no_scheme(self):
        ok, reason = validate_url("example.com")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_dict_scheme(self):
        ok, reason = validate_url("dict://evil.com/")
        assert ok is False
        assert "blocked_scheme" in reason


class TestPrivateIPBlocking:
    """Verify private/internal IPs are blocked."""

    def test_blocks_loopback_127(self):
        ok, reason = validate_url("http://127.0.0.1/admin")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_loopback_localhost(self):
        ok, reason = validate_url("http://localhost:8080/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_private_10(self):
        ok, reason = validate_url("http://10.0.0.1/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_private_10_deep(self):
        ok, reason = validate_url("http://10.255.255.255:9200/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_private_172(self):
        ok, reason = validate_url("http://172.16.0.1/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_private_192(self):
        ok, reason = validate_url("http://192.168.1.1/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_aws_metadata(self):
        ok, reason = validate_url("http://169.254.169.254/latest/meta-data/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_link_local(self):
        ok, reason = validate_url("http://169.254.1.1/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_ipv6_loopback(self):
        ok, reason = validate_url("http://[::1]/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_zero_address(self):
        ok, reason = validate_url("http://0.0.0.0/")
        assert ok is False
        assert "private_ip" in reason


class TestCloudMetadataBlocking:
    """Verify cloud metadata hostnames are blocked."""

    def test_blocks_gcp_metadata(self):
        ok, reason = validate_url("http://metadata.google.internal/computeMetadata/v1/")
        assert ok is False
        assert "blocked_hostname" in reason

    def test_blocks_gcp_metadata_goog(self):
        ok, reason = validate_url("http://metadata.goog/computeMetadata/v1/")
        assert ok is False
        assert "blocked_hostname" in reason


class TestEdgeCases:
    """Edge cases and malformed input."""

    def test_blocks_empty_url(self):
        ok, reason = validate_url("")
        assert ok is False

    def test_blocks_none_url(self):
        ok, reason = validate_url(None)
        assert ok is False

    def test_blocks_whitespace_url(self):
        ok, reason = validate_url("   ")
        assert ok is False

    def test_allows_url_with_path(self):
        ok, _ = validate_url("https://docs.python.org/3/library/urllib.html")
        assert ok is True

    def test_allows_url_with_port(self):
        ok, _ = validate_url("https://example.com:8443/api")
        assert ok is True

    def test_allows_url_with_query(self):
        ok, _ = validate_url("https://example.com/search?q=test&page=1")
        assert ok is True


class TestConvenienceFunctions:
    """Test helper functions."""

    def test_is_safe_url_true(self):
        assert is_safe_url("https://example.com") is True

    def test_is_safe_url_false_scheme(self):
        assert is_safe_url("file:///etc/passwd") is False

    def test_is_safe_url_false_ip(self):
        assert is_safe_url("http://127.0.0.1") is False

    def test_validate_url_or_raise_safe(self):
        result = validate_url_or_raise("https://example.com")
        assert result == "https://example.com"

    def test_validate_url_or_raise_unsafe(self):
        with pytest.raises(ValueError, match="URL blocked"):
            validate_url_or_raise("file:///etc/passwd")

    def test_validate_url_or_raise_private_ip(self):
        with pytest.raises(ValueError, match="URL blocked"):
            validate_url_or_raise("http://10.0.0.1/admin")
