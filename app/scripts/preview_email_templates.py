from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.core.config import settings
from app.services import email as email_service


def main() -> None:
    settings.FRONTEND_BASE_URL = (
        os.environ.get("MANIFESTBANK_PREVIEW_BASE_URL")
        or settings.FRONTEND_BASE_URL
        or "https://manifestbank.app"
    )
    output_dir = Path("tmp/email-previews")
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_preview in output_dir.glob("*.html"):
        stale_preview.unlink()
    rendered: list[tuple[str, str, str]] = []

    def capture(to_email: str, subject: str, html: str, reply_to: str | None = None) -> bool:
        filename = f"{len(rendered) + 1:02d}-{subject.lower().replace(' ', '-').replace('—', '-').replace('™', '').replace('/', '-')}.html"
        filename = "".join(char for char in filename if char.isalnum() or char in "-_.")
        rendered.append((filename, subject, html))
        return True

    email_service._send_email = capture  # type: ignore[assignment]

    email_service.send_verification_email("member@example.com", "preview-verify-token")
    email_service.send_password_reset_email("member@example.com", "preview-reset-token")
    email_service.send_trial_grant_email("member@example.com", "Nova", 14)
    email_service.send_signature_welcome_email("member@example.com", "Nova")
    email_service.send_myline_message_email(
        "member@example.com",
        "Fortune",
        42,
        "A calm reminder to return to the intention you named this morning.",
    )
    email_service.send_post_comment_email(
        "member@example.com",
        "Nova",
        12,
        8,
        "This reflection feels clear, grounded, and beautifully specific.",
    )
    email_service.send_ledger_post_email(
        "member@example.com",
        "Future Wealth Trust",
        "credit",
        "$2,000,000.00",
        "visualization",
        "/dashboard",
    )
    email_service.send_contact_email(
        "team@example.com",
        "Harper",
        "harper@example.com",
        "Partnership inquiry",
        "I would like to learn more about ManifestBank.",
    )
    email_service.send_subscription_alert_email(
        "team@example.com",
        "member@example.com",
        "Nova",
        "annual",
    )

    index_links = []
    for filename, subject, html in rendered:
        (output_dir / filename).write_text(html, encoding="utf-8")
        index_links.append(f'<li><a href="{filename}">{subject}</a></li>')

    index_html = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>ManifestBank Email Previews</title>
        <style>
          body {{ font-family: Georgia, serif; padding: 32px; background: #f6f1ea; color: #241b16; }}
          a {{ color: #8a4f3e; }}
        </style>
      </head>
      <body>
        <h1>ManifestBank Email Previews</h1>
        <ul>{''.join(index_links)}</ul>
      </body>
    </html>
    """
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")
    print(f"Using FRONTEND_BASE_URL={settings.FRONTEND_BASE_URL}")
    print(f"Wrote {len(rendered)} previews to {output_dir.resolve()}/index.html")


if __name__ == "__main__":
    main()
