"""SendGrid email delivery."""

import httpx

from app.core.config import settings
from app.core.resilience import http_retry


class EmailConfigurationError(RuntimeError):
    pass


@http_retry
async def _post_sendgrid_mail(payload: dict) -> None:
    timeout = httpx.Timeout(settings.sendgrid_timeout_s)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            settings.sendgrid_api_url,
            headers={
                "Authorization": f"Bearer {settings.sendgrid_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()


async def send_invitation_email(*, to_email: str, subject: str, body: str) -> None:
    if not settings.sendgrid_api_key:
        raise EmailConfigurationError("SENDGRID_API_KEY is not configured")
    if not settings.sendgrid_from_email:
        raise EmailConfigurationError("SENDGRID_FROM_EMAIL is not configured")

    sender: dict[str, str] = {"email": settings.sendgrid_from_email}
    if settings.sendgrid_from_name:
        sender["name"] = settings.sendgrid_from_name

    payload = {
        "personalizations": [
            {
                "to": [{"email": to_email}],
                "subject": subject,
            }
        ],
        "from": sender,
        "content": [{"type": "text/plain", "value": body}],
    }
    await _post_sendgrid_mail(payload)
