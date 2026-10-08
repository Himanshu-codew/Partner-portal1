import re

from django.core.exceptions import ValidationError

# Re-export partner utilities for project-wide convenience
from partners.utils import get_partner_profile, user_can_access_object, approved_partner_required

__all__ = [
    'get_partner_profile',
    'user_can_access_object',
    'approved_partner_required',
    'normalize_phone',
]


def normalize_phone(raw, default_country_code='91'):
    """
    Normalize a phone number to strict E.164: '+<country_code><number>'.

    Accepts national numbers ('9876543210', '09876543210'), country-code
    prefixed numbers ('919876543210') and already international numbers
    ('+919876543210'), with spaces, dashes, dots or brackets anywhere.

    Returns the normalized string; raises django ValidationError when the
    input cannot be interpreted as a phone number.
    """
    cc = re.sub(r'\D', '', default_country_code or '')
    if not cc:
        raise ValidationError('A default country code is required to normalize phone numbers.')

    if raw is None:
        raise ValidationError('Enter a valid phone number, e.g. +919876543210.')

    # Strip formatting characters but keep a leading '+' marker for now.
    text = re.sub(r'[\s\-\(\)\.\[\]]', '', str(raw)).strip()
    if not text:
        raise ValidationError('Enter a valid phone number, e.g. +919876543210.')

    if text.startswith('+'):
        digits = text[1:]
        if not digits.isdigit():
            raise ValidationError('A phone number can only contain digits after "+".')
        if not 10 <= len(digits) <= 15:
            raise ValidationError('A phone number must be between 10 and 15 digits.')
        normalized = '+' + digits
    else:
        digits = text
        if not digits.isdigit():
            raise ValidationError('Phone number can only contain digits, spaces, -, or +.')
        # National trunk prefix (leading zero, or '00' international
        # prefix) is not part of E.164.
        while digits.startswith('0') and len(digits) > 1:
            digits = digits[1:]
        if digits.startswith(cc) and 11 <= len(digits) <= 15:
            normalized = '+' + digits
        elif len(digits) == 10:
            normalized = '+' + cc + digits
        else:
            raise ValidationError('Enter a valid phone number, e.g. +919876543210.')

    if len(normalized) - 1 > 15:
        raise ValidationError('A phone number must be between 10 and 15 digits.')
    return normalized
