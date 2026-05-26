from datetime import datetime
import importlib

import pytest
import httpx

from app.services import email as email_service


@pytest.mark.parametrize(
    ("fn_name", "kwargs", "expected_subject", "expected_fragments"),
    [
        (
            "send_verification_email",
            {"to_email": "member@test.com", "token": "verify-token"},
            "Verify your ManifestBank email",
            [
                "Verify your ManifestBank email",
                "Email Verification",
                "Verify email",
                "/verify-email?token=verify-token",
            ],
        ),
        (
            "send_password_reset_email",
            {"to_email": "member@test.com", "token": "reset-token"},
            "Reset your ManifestBank password",
            [
                "Reset your ManifestBank password",
                "Security",
                "Reset password",
                "/reset-password?token=reset-token",
            ],
        ),
        (
            "send_myline_message_email",
            {
                "to_email": "member@test.com",
                "sender_name": "Nova",
                "thread_id": 42,
                "preview": "A calm and focused check-in.",
            },
            "ManifestBank™ — New My Line message",
            [
                "New My Line message",
                "Nova",
                "A calm and focused check-in.",
                "/myline/42",
                "Open My Line",
            ],
        ),
        (
            "send_signature_welcome_email",
            {"to_email": "member@test.com", "username": "Nova"},
            "Welcome to ManifestBank™ Signature ✨",
            [
                "Welcome to ManifestBank™ Signature",
                "Signature Welcome",
                "Welcome to <strong>ManifestBank™ Signature</strong>, Nova.",
                "You didn’t just upgrade. You elevated.",
                "Fortune is evolving in real time.",
                "Enter Signature",
                "/dashboard",
            ],
        ),
        (
            "send_signature_presence_email",
            {"to_email": "member@test.com"},
            "You’re Not Just Here… You’re Part of This 💫",
            [
                "You’re Not Just Here… You’re Part of This 💫",
                "Signature Presence",
                "We see you.",
                "Your presence here means something.",
                "More is unfolding.",
                "Enter ManifestBank™",
                "/dashboard",
            ],
        ),
        (
            "send_signature_recognition_email",
            {"to_email": "member@test.com"},
            "A Personal Thank You — And Something We Owe You",
            [
                "A Personal Thank You",
                "Signature Recognition",
                "We’re genuinely sorry for that delay.",
                "ManifestBank™ is catching up to you.",
                "Enter ManifestBank™",
                "/dashboard",
            ],
        ),
        (
            "send_signature_promo_email",
            {"to_email": "member@test.com"},
            "50% Off Signature Annual Membership Ends June 1 at Midnight CST",
            [
                "50% Off Signature Annual Membership Ends June 1 at Midnight CST",
                "Signature Offer",
                "Dear ManifestBank™ Members,",
                "Something special has arrived ✨",
                "50% OFF",
                "SIGNATURE50",
                "$36/year",
                "Balance Preview Vault™ 🗝️",
                "Unlock ManifestBank™ Signature",
                "/dashboard",
            ],
        ),
    ],
)
def test_branded_email_templates_render_shared_shell(monkeypatch, fn_name, kwargs, expected_subject, expected_fragments):
    email_module = importlib.reload(email_service)

    class Recorder:
        def __init__(self):
            self.to_email = None
            self.subject = None
            self.html = None
            self.reply_to = None

        def __call__(self, to_email: str, subject: str, html: str, reply_to: str | None = None) -> bool:
            self.to_email = to_email
            self.subject = subject
            self.html = html
            self.reply_to = reply_to
            return True

    recorder = Recorder()

    monkeypatch.setattr(email_module, "_send_email", recorder)
    monkeypatch.setattr(email_module.settings, "FRONTEND_BASE_URL", "https://manifestbank.app")

    result = getattr(email_module, fn_name)(**kwargs)

    assert result is True
    assert recorder.subject == expected_subject
    html = recorder.html
    assert html is not None
    assert '<meta charset="utf-8" />' in html
    assert '<meta name="color-scheme" content="light only" />' in html
    assert "ManifestBank™ is a" in html
    assert "ManifestBankâ" not in html
    assert '<img' in html
    assert 'src="https://manifestbank.app/manifestbank-glow-edge-logo.png"' in html
    assert 'alt="ManifestBank™"' in html
    assert 'href="https://manifestbank.app/auth"' in html
    assert "background:#fffaf5;color:#261b16" in html
    assert "color:#241814" in html
    assert "height:54px" in html
    assert "background-image:url('https://manifestbank.app/marble-veins.png')" in html
    for fragment in expected_fragments:
        assert fragment in html


def test_contact_email_escapes_user_supplied_html(monkeypatch):
    email_module = importlib.reload(email_service)
    captured = {}

    def fake_send(to_email: str, subject: str, html: str, reply_to: str | None = None) -> bool:
        captured["subject"] = subject
        captured["html"] = html
        captured["reply_to"] = reply_to
        return True

    monkeypatch.setattr(email_module, "_send_email", fake_send)

    result = email_module.send_contact_email(
        "team@test.com",
        name="<b>Harper</b>",
        email="sender@test.com",
        subject="<script>alert(1)</script>",
        message="<img src=x onerror=alert(1)>",
    )

    assert result is True
    assert captured["reply_to"] == "sender@test.com"
    assert "<script>" not in captured["html"]
    assert "<img src=x" not in captured["html"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in captured["html"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in captured["html"]


def test_send_email_uses_legacy_fallback_account(monkeypatch):
    email_module = importlib.reload(email_service)
    email_module._account_daily_counters.clear()
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "primary-key")
    monkeypatch.setattr(email_module.settings, "RESEND_FROM_EMAIL", "primary@manifestbank.app")
    monkeypatch.setattr(email_module.settings, "RESEND_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setattr(email_module.settings, "RESEND_FALLBACK_FROM_EMAIL", "backup@manifestbank.app")

    calls = []

    def fake_post(url: str, headers: dict, json: dict, timeout: int):
        calls.append({"headers": headers, "json": json})
        if len(calls) == 1:
            request = httpx.Request("POST", url)
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("primary failed", request=request, response=response)
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(email_module.httpx, "post", fake_post)

    assert email_module._send_email("member@test.com", "Subject", "<p>Hello</p>") is True
    assert len(calls) == 2
    assert calls[0]["headers"]["Authorization"] == "Bearer primary-key"
    assert calls[0]["json"]["from"] == "primary@manifestbank.app"
    assert calls[1]["headers"]["Authorization"] == "Bearer fallback-key"
    assert calls[1]["json"]["from"] == "backup@manifestbank.app"


def test_send_email_skips_primary_when_daily_cap_reached(monkeypatch):
    email_module = importlib.reload(email_service)
    email_module._account_daily_counters.clear()
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "primary-key")
    monkeypatch.setattr(email_module.settings, "RESEND_FROM_EMAIL", "primary@manifestbank.app")
    monkeypatch.setattr(email_module.settings, "RESEND_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setattr(email_module.settings, "RESEND_FALLBACK_FROM_EMAIL", "backup@manifestbank.app")
    monkeypatch.setattr(email_module.settings, "RESEND_PRIMARY_DAILY_LIMIT", 1)
    monkeypatch.setattr(email_module.settings, "RESEND_PRIMARY_DAILY_BUFFER", 0)
    email_module._account_daily_counters["primary"] = {"date": "9999-12-31", "count": 1}

    calls = []

    def fake_post(url: str, headers: dict, json: dict, timeout: int):
        calls.append({"headers": headers, "json": json})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(email_module.httpx, "post", fake_post)
    monkeypatch.setattr(email_module, "datetime", _FrozenDateTime)

    assert email_module._send_email("member@test.com", "Subject", "<p>Hello</p>") is True
    assert len(calls) == 1
    assert calls[0]["headers"]["Authorization"] == "Bearer fallback-key"
    assert calls[0]["json"]["from"] == "backup@manifestbank.app"


def test_send_email_uses_numbered_accounts_in_order(monkeypatch):
    email_module = importlib.reload(email_service)
    email_module._account_daily_counters.clear()
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(email_module.settings, "RESEND_FROM_EMAIL", None)
    monkeypatch.setattr(email_module.settings, "RESEND_FALLBACK_API_KEY", None)
    monkeypatch.setattr(email_module.settings, "RESEND_FALLBACK_FROM_EMAIL", None)
    monkeypatch.setenv("RESEND_ACCOUNT_1_API_KEY", "account-one-key")
    monkeypatch.setenv("RESEND_ACCOUNT_1_FROM_EMAIL", "one@manifestbank.app")
    monkeypatch.setenv("RESEND_ACCOUNT_2_API_KEY", "account-two-key")
    monkeypatch.setenv("RESEND_ACCOUNT_2_FROM_EMAIL", "two@manifestbank.app")

    calls = []

    def fake_post(url: str, headers: dict, json: dict, timeout: int):
        calls.append({"headers": headers, "json": json})
        if len(calls) == 1:
            request = httpx.Request("POST", url)
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("first account throttled", request=request, response=response)
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(email_module.httpx, "post", fake_post)

    assert email_module._send_email("member@test.com", "Subject", "<p>Hello</p>") is True
    assert len(calls) == 2
    assert calls[0]["headers"]["Authorization"] == "Bearer account-one-key"
    assert calls[0]["json"]["from"] == "one@manifestbank.app"
    assert calls[1]["headers"]["Authorization"] == "Bearer account-two-key"
    assert calls[1]["json"]["from"] == "two@manifestbank.app"


class _FrozenDateTime:
    @classmethod
    def now(cls, tz=None):
        return datetime.fromisoformat("9999-12-31T12:00:00+00:00")
