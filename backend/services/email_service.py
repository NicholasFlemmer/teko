"""Transactional email via Resend.

Sends invite, password-reset and welcome emails. Fails closed: if
RESEND_API_KEY is not configured, or the Resend API call itself fails,
_send() raises rather than returning silently, so a caller can never treat
an email that was never sent as delivered. The email body -- which carries
the invite/reset/login link -- is never written to logs, at any log level,
under any condition. Only the subject, recipient, and (on failure) the
exception type are logged.
"""
import html
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

# =============================================================================
# Brand tokens (Teko brand guide). Presentation only -- none of these feed
# into content or logic below.
# =============================================================================
COLOR_ORANGE = "#F78B29"   # Signal Orange -- accent, used sparingly
COLOR_TEAL = "#2E9E8C"     # Field Teal -- accent, used sparingly
COLOR_INK = "#23303F"      # Ink Navy -- neutral, also body text
COLOR_INDIGO = "#516AF7"   # Action Indigo -- primary action / buttons
COLOR_CANVAS = "#F6F7F9"   # page background (light mode)
COLOR_SURFACE = "#FFFFFF"  # card background (light mode)
COLOR_LINE = "#E7EAEE"     # 1px borders (light mode)
COLOR_MUTED = "#727C8B"    # secondary text (light mode)

RADIUS_CARD = "18px"
RADIUS_CONTROL = "12px"
SHADOW_CARD = "0 1px 2px rgba(23,48,63,.05)"

# Dark-mode equivalents. Applied only inside the @media (prefers-color-scheme:
# dark) block in _layout() -- the light tokens above remain the default for
# any client that strips <style>, so legibility never depends on that block
# actually running.
_DARK_CANVAS = "#12181F"
_DARK_SURFACE = "#1B222C"
_DARK_TEXT = "#EDEFF2"
_DARK_MUTED = "#97A1AF"
_DARK_LINE = "#2B3542"

# Wordmark font: Poppins requested, with a system fallback stack chosen to
# still look like a wordmark when Gmail/Outlook strip the webfont request.
_WORDMARK_FONT = "'Poppins','Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,Helvetica,Arial,sans-serif"
# Body font: Plus Jakarta Sans requested, same fallback approach.
_BODY_FONT = "'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

_GOOGLE_FONTS_HREF = (
    "https://fonts.googleapis.com/css2?"
    "family=Poppins:wght@700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap"
)


def _role_label(role):
    return ROLE_LABELS.get(role, role or "member")


def _button(label, url):
    return (
        f'<a href="{url}" '
        f'style="display:inline-block;background:{COLOR_INDIGO};color:#ffffff;'
        f'text-decoration:none;font-family:{_BODY_FONT};font-weight:700;font-size:15px;'
        f'padding:13px 22px;border-radius:{RADIUS_CONTROL};">'
        f'{label}</a>'
    )


def _layout(body_html):
    """Wrap body content in the shared teko email shell (wordmark + footer).

    Table-based layout, inline styles throughout. The one <style> block
    below is scoped to dark-mode colour overrides only -- never layout --
    so a client that strips <style> entirely just falls back to the inline
    (light-mode) styles, which are legible on their own.
    """
    footer_domain = Config.EMAIL_FOOTER_DOMAIN
    return f"""\
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="light dark">
    <meta name="supported-color-schemes" content="light dark">
    <link rel="stylesheet" href="{_GOOGLE_FONTS_HREF}">
    <style>
      /* Colour only -- never layout. Ignored harmlessly by clients that
         strip <style>; the inline styles on each element below are the
         light-mode fallback in that case. */
      @media (prefers-color-scheme: dark) {{
        .bg-canvas {{ background-color: {_DARK_CANVAS} !important; }}
        .bg-surface {{ background-color: {_DARK_SURFACE} !important; }}
        .text-ink {{ color: {_DARK_TEXT} !important; }}
        .text-muted {{ color: {_DARK_MUTED} !important; }}
        .border-line {{ border-color: {_DARK_LINE} !important; }}
      }}
    </style>
  </head>
  <body style="margin:0;padding:0;background:{COLOR_CANVAS};font-family:{_BODY_FONT};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{COLOR_CANVAS}" class="bg-canvas" style="background:{COLOR_CANVAS};padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{COLOR_SURFACE}" class="bg-surface border-line" style="max-width:600px;background:{COLOR_SURFACE};border-radius:{RADIUS_CARD};border:1px solid {COLOR_LINE};box-shadow:{SHADOW_CARD};">
            <tr>
              <td height="6" style="height:6px;line-height:6px;font-size:1px;background:{COLOR_TEAL};border-radius:{RADIUS_CARD} {RADIUS_CARD} 0 0;">&nbsp;</td>
            </tr>
            <tr>
              <td style="padding:28px 32px 8px 32px;">
                <span class="text-ink" style="font-family:{_WORDMARK_FONT};font-size:22px;font-weight:700;letter-spacing:-0.3px;color:{COLOR_INK};">teko</span>
              </td>
            </tr>
            <tr>
              <td class="text-ink" style="padding:8px 32px 32px 32px;font-family:{_BODY_FONT};color:{COLOR_INK};font-size:15px;line-height:1.6;">
                {body_html}
              </td>
            </tr>
            <tr>
              <td class="text-muted border-line" style="padding:20px 32px;border-top:1px solid {COLOR_LINE};font-family:{_BODY_FONT};color:{COLOR_MUTED};font-size:12px;">
                teko &middot; <a href="https://{footer_domain}" class="text-muted" style="color:{COLOR_MUTED};">{footer_domain}</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


class EmailNotConfiguredError(RuntimeError):
    """Raised by _send() when RESEND_API_KEY is not configured.

    Fails closed: a caller must not be able to mistake an unconfigured
    mailer for a successful send.
    """


def _send(to_email, subject, html):
    """Send via Resend. Raises on any failure to send -- never returns
    silently, and never logs `html` (or anything derived from it) at any
    log level, so the invite/reset/login link inside it can't reach logs."""
    if not Config.RESEND_API_KEY:
        logger.warning("[email] RESEND_API_KEY not set — cannot send '%s' to %s.", subject, to_email)
        raise EmailNotConfiguredError(f"RESEND_API_KEY not configured; cannot send '{subject}' to {to_email}")

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
        # Log the exception TYPE only, never str(e) -- the Resend client's
        # exception can embed the request body (i.e. `html`, i.e. the link)
        # in its message, and that must not end up in logs either.
        logger.error("[email] Failed to send '%s' to %s (%s)", subject, to_email, type(e).__name__)
        raise


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
<p style="margin:0;color:{COLOR_MUTED};font-size:13px;">This link expires in 48 hours.</p>"""
    _send(to_email, subject, _layout(body))


def send_password_reset_email(to_email, reset_link, name):
    """Email a user a link to reset their password."""
    subject = "Reset your Teko password"
    body = f"""\
<p style="margin:0 0 16px 0;font-size:18px;font-weight:700;">Reset your password</p>
<p style="margin:0 0 24px 0;">Hi {name}, we received a request to reset your password.</p>
<p style="margin:0 0 24px 0;">{_button("Reset Password", reset_link)}</p>
<p style="margin:0;color:{COLOR_MUTED};font-size:13px;">
  This link expires in 1 hour. If you didn't request this, you can ignore this email.
</p>"""
    _send(to_email, subject, _layout(body))


def send_welcome_email(to_email, name, org_name, login_url):
    """Email a newly created user a welcome message with a sign-in link."""
    subject = "Welcome to Teko"
    body = f"""\
<p style="margin:0 0 16px 0;font-size:18px;font-weight:700;">Welcome to Teko, {name}</p>
<p style="margin:0 0 24px 0;">Your account for <strong>{org_name}</strong> is ready.</p>
<p style="margin:0 0 24px 0;">{_button("Sign In", login_url)}</p>"""
    _send(to_email, subject, _layout(body))


_PERSON_TYPE_LABELS = {
    'participant': 'Participant',
    'coach': 'Coach',
}


def send_safeguarding_alert_email(to_email, org_name, flag_id, person_name, person_type,
                                   phone_masked, message_text, matched_categories,
                                   matched_terms, detected_at_display):
    """Email one safeguarding alert recipient about a single flagged message.

    FACTUAL RECORD ONLY, per the client's safeguarding policy: every field
    below is an identifier, a masked phone number, the matched keyword
    data, or the inbound message text reproduced EXACTLY as received --
    no paraphrasing, no summarising, no AI-generated interpretation, no
    severity rating, no recommended action. See
    services/safeguarding_service.py's record_safeguarding_flag for the
    same verbatim-storage rule this mirrors.

    Subject is deliberately neutral -- it names only the organisation,
    never the message, category, or person's name, because subjects
    render on lock screens where anyone nearby can read them.

    Called once per resolved recipient (see
    services/safeguarding_service.py's send_safeguarding_alert) --
    recipients are always sent to individually, one call per address,
    never CC'd/BCC'd together.

    Dynamic values are HTML-escaped (quotes left alone, so the
    message/name text a test compares byte-for-byte still matches unless
    it contains literal '<', '>' or '&') to stop an inbound message from
    ever being interpreted as markup by an HTML email client.
    """
    subject = f"Safeguarding alert - {org_name}"

    person_label = _PERSON_TYPE_LABELS.get(person_type, person_type or 'Person')
    categories_display = ", ".join(matched_categories) or "(none)"
    terms_display = ", ".join(matched_terms) or "(none)"

    esc = lambda s: html.escape(s or '', quote=False)  # noqa: E731

    body = f"""\
<p style="margin:0 0 16px 0;font-size:18px;font-weight:700;">Safeguarding alert</p>
<p style="margin:0 0 20px 0;">
  A keyword match was detected in an inbound WhatsApp message for <strong>{esc(org_name)}</strong>.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px 0;font-size:14px;">
  <tr><td style="padding:4px 0;color:{COLOR_MUTED};width:140px;vertical-align:top;">From</td><td style="padding:4px 0;">{esc(person_name) or 'Unknown'} ({esc(person_label)})</td></tr>
  <tr><td style="padding:4px 0;color:{COLOR_MUTED};vertical-align:top;">Phone</td><td style="padding:4px 0;">{esc(phone_masked) or '****'}</td></tr>
  <tr><td style="padding:4px 0;color:{COLOR_MUTED};vertical-align:top;">Categories</td><td style="padding:4px 0;">{esc(categories_display)}</td></tr>
  <tr><td style="padding:4px 0;color:{COLOR_MUTED};vertical-align:top;">Matched terms</td><td style="padding:4px 0;">{esc(terms_display)}</td></tr>
  <tr><td style="padding:4px 0;color:{COLOR_MUTED};vertical-align:top;">Detected at</td><td style="padding:4px 0;">{esc(detected_at_display)}</td></tr>
  <tr><td style="padding:4px 0;color:{COLOR_MUTED};vertical-align:top;">Flag ID</td><td style="padding:4px 0;">{esc(flag_id)}</td></tr>
</table>
<p style="margin:0 0 8px 0;color:{COLOR_MUTED};font-size:13px;">Message (verbatim, as received):</p>
<div style="margin:0 0 20px 0;padding:12px 14px;background:{COLOR_CANVAS};border:1px solid {COLOR_LINE};border-radius:{RADIUS_CONTROL};white-space:pre-wrap;font-size:14px;">{esc(message_text)}</div>
<p style="margin:0;color:{COLOR_MUTED};font-size:12px;">
  This is an automated keyword detection. It has not been assessed by a person and may be a false positive.
</p>"""
    _send(to_email, subject, _layout(body))
