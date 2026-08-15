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
