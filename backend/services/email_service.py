"""Transactional email via Resend.

Sends invite, password-reset and welcome emails. When RESEND_API_KEY is not
configured it logs the email (including the action link) to the console so
local development keeps working without an email provider.
"""
import logging
import resend

from config import Config

logger = logging.getLogger(__name__)

ROLE_LABELS = {
    'super_admin': 'Super Admin',
    'location_admin': 'Location Admin',
    'coach': 'Coach',
    'player': 'Player',
}

BRAND = "#0D9488"


def _role_label(role):
    return ROLE_LABELS.get(role, role or "member")


def _button(label, url):
    return (
        f'<a href="{url}" '
        f'style="display:inline-block;background:{BRAND};color:#ffffff;'
        'text-decoration:none;font-weight:600;font-size:15px;'
        'padding:12px 28px;border-radius:8px;">'
        f'{label}</a>'
    )


def _layout(body_html):
    """Wrap body content in the shared Teko email shell (logo + footer)."""
    return f"""\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border-radius:12px;border:1px solid #e4e4e7;">
            <tr>
              <td style="padding:28px 32px 8px 32px;">
                <span style="font-size:22px;font-weight:800;letter-spacing:-0.5px;color:{BRAND};">Teko</span>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 32px 32px 32px;color:#27272a;font-size:15px;line-height:1.6;">
                {body_html}
              </td>
            </tr>
            <tr>
              <td style="padding:20px 32px;border-top:1px solid #e4e4e7;color:#a1a1aa;font-size:12px;">
                Teko &middot; <a href="https://tekohq.com" style="color:#a1a1aa;">tekohq.com</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _send(to_email, subject, html, fallback_detail=None):
    """Send via Resend, or log to console when no API key is configured."""
    if not Config.RESEND_API_KEY:
        msg = f"[email] RESEND_API_KEY not set — not sending '{subject}' to {to_email}."
        if fallback_detail:
            msg += f" {fallback_detail}"
        logger.warning(msg)
        return

    try:
        resend.api_key = Config.RESEND_API_KEY
        resend.Emails.send({
            "from": Config.RESEND_FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "html": html,
        })
        logger.info("[email] Sent '%s' to %s", subject, to_email)
    except Exception as e:
        logger.error("[email] Failed to send '%s' to %s: %s", subject, to_email, e)


def send_invite_email(to_email, invite_link, org_name, invited_by_name, role):
    """Email an invitee a link to set up their account."""
    role_label = _role_label(role)
    subject = f"You've been invited to join {org_name} on Teko"
    body = f"""\
<p style="margin:0 0 16px 0;font-size:18px;font-weight:700;">You've been invited</p>
<p style="margin:0 0 24px 0;">
  {invited_by_name} has invited you to join <strong>{org_name}</strong> on Teko as a {role_label}.
</p>
<p style="margin:0 0 24px 0;">{_button("Accept Invitation", invite_link)}</p>
<p style="margin:0;color:#71717a;font-size:13px;">This link expires in 48 hours.</p>"""
    _send(
        to_email,
        subject,
        _layout(body),
        fallback_detail=f"invite link for {to_email}: {invite_link}",
    )


def send_password_reset_email(to_email, reset_link, name):
    """Email a user a link to reset their password."""
    subject = "Reset your Teko password"
    body = f"""\
<p style="margin:0 0 16px 0;font-size:18px;font-weight:700;">Reset your password</p>
<p style="margin:0 0 24px 0;">Hi {name}, we received a request to reset your password.</p>
<p style="margin:0 0 24px 0;">{_button("Reset Password", reset_link)}</p>
<p style="margin:0;color:#71717a;font-size:13px;">
  This link expires in 1 hour. If you didn't request this, you can ignore this email.
</p>"""
    _send(
        to_email,
        subject,
        _layout(body),
        fallback_detail=f"reset link for {to_email}: {reset_link}",
    )


def send_welcome_email(to_email, name, org_name, login_url):
    """Email a newly created user a welcome message with a sign-in link."""
    subject = "Welcome to Teko"
    body = f"""\
<p style="margin:0 0 16px 0;font-size:18px;font-weight:700;">Welcome to Teko, {name}</p>
<p style="margin:0 0 24px 0;">Your account for <strong>{org_name}</strong> is ready.</p>
<p style="margin:0 0 24px 0;">{_button("Sign In", login_url)}</p>"""
    _send(
        to_email,
        subject,
        _layout(body),
        fallback_detail=f"login url for {to_email}: {login_url}",
    )
