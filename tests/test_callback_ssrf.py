"""SSRF 防护单元测试 — validate_callback_url"""
import pytest
from services.exporter.callback import validate_callback_url


class TestSSRProtection:
    """验证 callback URL 的 SSRF 防护"""

    # ── 应拦截的 URL ──

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/x",
        "http://10.0.0.1/x",
        "http://10.255.255.255/x",
        "http://172.16.0.1/x",
        "http://172.31.255.255/x",
        "http://192.168.0.5/x",
        "http://192.168.1.100/x",
        "http://169.254.169.254/x",  # AWS metadata
        "http://0.0.0.0/x",
        "http://100.64.0.1/x",  # CGNAT
        "http://[::1]/x",  # IPv6 loopback
        "http://[fe80::1]/x",  # IPv6 link-local
        "http://[fc00::1]/x",  # IPv6 unique local
    ])
    def test_private_ip_blocked(self, url):
        with pytest.raises(ValueError):
            validate_callback_url(url)

    @pytest.mark.parametrize("url", [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "gopher://localhost/x",
        "javascript:alert(1)",
    ])
    def test_non_http_scheme_blocked(self, url):
        with pytest.raises(ValueError):
            validate_callback_url(url)

    def test_empty_url_blocked(self):
        with pytest.raises(ValueError):
            validate_callback_url("")

    def test_no_hostname_blocked(self):
        with pytest.raises(ValueError):
            validate_callback_url("http:///path")

    # ── 应通过的 URL ──

    @pytest.mark.parametrize("url", [
        "http://example.com/callback",
        "https://api.example.com/v1/webhook",
        "http://203.0.113.1/callback",  # 公网 IP
        "https://192.0.2.1/callback",  # TEST-NET-1 (公网保留但非私有)
    ])
    def test_valid_url_passes(self, url):
        result = validate_callback_url(url)
        assert result == url

    def test_domain_url_passes(self):
        """域名形式 URL 应通过（DNS rebinding 由网络层防护）"""
        result = validate_callback_url("https://my-service.com/webhook")
        assert result == "https://my-service.com/webhook"
