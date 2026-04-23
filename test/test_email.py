import importlib

import pytest

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
                "manifestbank-app-logo-latest.png",
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
                "You didn’t just upgrade. You elevated.",
                "Fortune is evolving in real time.",
                "Enter Signature",
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
    assert "ManifestBank™ is a" in html
    assert "ManifestBankâ" not in html
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
