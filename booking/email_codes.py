"""
6-digit email codes: confirm the email after sign-up, and reset a forgotten password.

  * A code is valid for 10 minutes and can be used once.
  * After 5 wrong tries the code stops working (request a new one).
  * "Resend" works after 60 seconds, at most 5 codes per hour per account.
  * Codes are stored hashed, so even the database never shows them.
Emails are sent with EmailJS (services/emailjs.py), template EMAILJS_CODE_TEMPLATE_ID.
"""
import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import EmailCode
from .services.emailjs import send_code_email

CODE_MINUTES = 10
MAX_ATTEMPTS = 5
RESEND_SECONDS = 60
MAX_PER_HOUR = 5


def mask_email(email):
    """juan.cruz@gmail.com -> ju*******@gmail.com"""
    if not email or '@' not in email:
        return ''
    name, domain = email.split('@', 1)
    shown = name[:2] if len(name) > 2 else name[:1]
    return f"{shown}{'*' * max(len(name) - len(shown), 3)}@{domain}"


def seconds_until_resend(customer, purpose, now=None):
    now = now or timezone.now()
    last = EmailCode.objects.filter(customer=customer, purpose=purpose).first()
    if not last:
        return 0
    wait = RESEND_SECONDS - (now - last.created_at).total_seconds()
    return max(int(wait + 0.999), 0)


def send_code(customer, purpose, now=None):
    """
    Create a new code and email it. Earlier unused codes for the same purpose
    stop working. Returns (sent: bool, message: str).
    """
    now = now or timezone.now()
    wait = seconds_until_resend(customer, purpose, now)
    if wait:
        return False, f'Please wait {wait} seconds before asking for a new code.'
    recent = EmailCode.objects.filter(customer=customer, purpose=purpose,
                                      created_at__gte=now - timedelta(hours=1)).count()
    if recent >= MAX_PER_HOUR:
        return False, 'Too many codes were requested. Please try again in an hour.'

    code = f'{secrets.randbelow(1_000_000):06d}'
    EmailCode.objects.filter(customer=customer, purpose=purpose, used=False).update(used=True)
    EmailCode.objects.create(customer=customer, purpose=purpose, code_hash=make_password(code),
                             expires_at=now + timedelta(minutes=CODE_MINUTES))
    sent, message = send_code_email(customer, code, purpose, CODE_MINUTES)
    if not sent:
        return False, message
    return True, f'We sent a 6-digit code to {mask_email(customer.email)}.'


def check_code(customer, purpose, code, now=None):
    """
    Returns (ok: bool, message: str). A correct code is used up immediately.
    """
    now = now or timezone.now()
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if len(code) != 6:
        return False, 'Enter the 6-digit code from the email.'

    current = EmailCode.objects.filter(customer=customer, purpose=purpose, used=False).first()
    if not current:
        return False, 'This code is no longer valid. Tap "Resend code" to get a new one.'
    if current.expires_at <= now:
        return False, 'This code has expired. Tap "Resend code" to get a new one.'
    if current.attempts >= MAX_ATTEMPTS:
        return False, 'Too many wrong tries. Tap "Resend code" to get a new one.'

    if not check_password(code, current.code_hash):
        current.attempts += 1
        current.save(update_fields=['attempts'])
        left = MAX_ATTEMPTS - current.attempts
        if left <= 0:
            return False, 'Too many wrong tries. Tap "Resend code" to get a new one.'
        return False, f'That code is not correct. {left} {"try" if left == 1 else "tries"} left.'

    # Mark used only if nobody used it a moment ago (double click / two tabs)
    updated = EmailCode.objects.filter(pk=current.pk, used=False).update(used=True)
    if not updated:
        return False, 'This code was already used. Tap "Resend code" to get a new one.'
    return True, 'Code accepted.'
