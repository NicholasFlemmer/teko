import re


def mask_phone(phone_number):
    """Mask a phone number for logging, keeping only the last 4 digits.

    Never log a raw phone number -- this is the only form that should
    reach a log line. Handles None, empty, and malformed input safely.

    Examples:
      '+27821234567' -> '****4567'
      '27821234567'  -> '****4567'
      '123'          -> '****'  (too short to reveal any digits)
      None / ''      -> '****'
    """
    if not phone_number:
        return '****'

    digits = re.sub(r'[^\d]', '', str(phone_number))

    if len(digits) < 4:
        return '****'

    return '****' + digits[-4:]


def normalize_sa_phone(phone_number):
    """Normalize a South African phone number to international format (27XXXXXXXXX).

    Handles common formats:
      +27 82 123 4567  -> 27821234567
      0821234567       -> 27821234567
      27821234567      -> 27821234567
      +27-82-123-4567  -> 27821234567

    Returns empty string if the input is empty/None or clearly invalid.
    """
    if not phone_number:
        return ''

    # Strip whitespace, dashes, parentheses, plus sign, and Unicode control/formatting chars
    cleaned = re.sub(r'[^\d]', '', str(phone_number))

    if not cleaned.isdigit() or len(cleaned) < 9:
        return ''

    # Leading 0 -> replace with 27
    if cleaned.startswith('0') and len(cleaned) == 10:
        cleaned = '27' + cleaned[1:]

    # Already has country code
    if cleaned.startswith('27') and len(cleaned) == 11:
        return cleaned

    # Didn't match any valid SA phone pattern
    return ''


def normalize_phone_for_sending(phone_number):
    """Normalize a phone number for outbound WhatsApp sends — international,
    not SA-only.

    Unlike normalize_sa_phone(), this applies no country-specific allowlist
    beyond the one SA-specific convenience below: it accepts any number
    whose digit count falls in the E.164 range (8-15 digits), so a UAE,
    Brazilian, or UK number is sent as-is rather than refused outright.
    normalize_sa_phone() itself is unchanged and still used wherever strict
    SA validation is required (identity storage/migration); this function
    exists only for the outbound send path.

    Rules:
      1. Strip everything that isn't a digit.
      2. If exactly 10 digits and starts with '0', treat as a locally
         formatted SA number and replace the leading 0 with 27 (preserves
         normalize_sa_phone()'s existing behaviour for that one shape).
      3. Accept the result if it's 8-15 digits (E.164 range).
      4. Otherwise return ''.

    Returns empty string if the input is empty/None or outside the E.164
    digit-count range.
    """
    if not phone_number:
        return ''

    cleaned = re.sub(r'[^\d]', '', str(phone_number))

    if len(cleaned) == 10 and cleaned.startswith('0'):
        cleaned = '27' + cleaned[1:]

    if 8 <= len(cleaned) <= 15:
        return cleaned

    return ''


def normalize_phone_for_matching(phone_number):
    """Normalize a phone number for identity-matching comparisons only.

    Tries normalize_sa_phone() first — if the number is SA-shaped, its
    canonical form is used. If not (e.g. a Brazilian number, or any other
    international number), falls back to a permissive strip-only
    normalization (digits only) instead of rejecting it outright.

    This is deliberately MORE PERMISSIVE than normalize_sa_phone(): it
    exists for matching an incoming phone against stored records
    (PersonService), where a number of any shape must be able to resolve —
    not just South African ones. normalize_sa_phone() itself is
    unchanged and still used wherever strict SA validation/display is
    required; do not use this function as a substitute for it.

    Apply this to BOTH sides of a comparison (incoming and stored) so an
    SA number and an international number both match correctly regardless
    of which format either side happens to be stored/sent in.

    Returns empty string if the input is empty/None.
    """
    if not phone_number:
        return ''

    sa_canonical = normalize_sa_phone(phone_number)
    if sa_canonical:
        return sa_canonical

    # Not SA-shaped — permissive fallback: strip everything but digits,
    # rather than rejecting the number outright.
    return re.sub(r'[^\d]', '', str(phone_number))
