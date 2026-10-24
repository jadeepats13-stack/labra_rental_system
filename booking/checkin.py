"""
Booking check-in: Confirmation IDs, verification and playing-time sessions.

Both verification methods (QR scan / photo and typed Confirmation ID) end up
here with the same code, so they always act on the same booking record.

Rules (agreed with the client):
  * A booking gets its Confirmation ID when the admin approves it.
  * Check-in is allowed from 15 minutes before the start time until the end
    time, on the booking date, for Approved and PAID bookings only.
  * A booking can be checked in only once (enforced in the database).
  * Playing time ends at the reserved end time, even if the customer is late.
  * When the time is up the booking is marked Completed automatically.
"""
import re
import secrets
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Booking, Payment

ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'   # no 0/O or 1/I to avoid typos
EARLY_MINUTES = 15
CODE_PATTERN = re.compile(r'^LBC-[A-Z0-9]{4}-[A-Z0-9]{4}$')


# ─── Confirmation IDs ─────────────────────────────────────────────

def _random_code():
    part = lambda: ''.join(secrets.choice(ALPHABET) for _ in range(4))  # noqa: E731
    return f'LBC-{part()}-{part()}'


def ensure_code(booking):
    """Give the booking a unique Confirmation ID if it does not have one."""
    if booking.confirmation_code:
        return booking.confirmation_code
    for _ in range(20):
        code = _random_code()
        try:
            with transaction.atomic():
                updated = (Booking.objects
                           .filter(pk=booking.pk, confirmation_code__isnull=True)
                           .update(confirmation_code=code))
        except IntegrityError:
            continue   # extremely unlikely clash with another booking: try again
        booking.refresh_from_db(fields=['confirmation_code'])
        if updated or booking.confirmation_code:
            return booking.confirmation_code
    raise RuntimeError('Could not generate a unique Confirmation ID')


def normalize_code(text):
    """
    Accept what staff type or what a QR contains: 'lbc 7k3p 9q2x',
    'LBC7K3P9Q2X', ' LBC-7K3P-9Q2X ' all become 'LBC-7K3P-9Q2X'.
    Returns '' when the text cannot be a Confirmation ID.
    """
    raw = re.sub(r'[^A-Za-z0-9]', '', text or '').upper()
    if raw.startswith('LBC'):
        raw = raw[3:]
    if len(raw) != 8:
        return ''
    code = f'LBC-{raw[:4]}-{raw[4:]}'
    return code if CODE_PATTERN.match(code) else ''


# ─── Verification ─────────────────────────────────────────────────

def _local(dt):
    return timezone.localtime(dt)


def booking_window(booking):
    """(opens_at, starts_at, ends_at) as aware datetimes in Philippine time."""
    starts = timezone.make_aware(datetime.combine(booking.booking_date, booking.start_time))
    ends = timezone.make_aware(datetime.combine(booking.booking_date, booking.end_time))
    return starts - timedelta(minutes=EARLY_MINUTES), starts, ends


def is_paid(booking):
    try:
        return booking.payment.payment_status == 'Paid'
    except Payment.DoesNotExist:
        return False


def booking_summary(booking):
    _, starts, ends = booking_window(booking)
    return {
        'booking_id': booking.booking_id,
        'code': booking.confirmation_code or '',
        'customer': f'{booking.customer.firstname} {booking.customer.lastname}'.strip(),
        'username': booking.customer.username,
        'court': booking.court.court_name or 'LA Court',
        'date': booking.booking_date.strftime('%a, %b %d, %Y'),
        'time': f"{starts.strftime('%I:%M %p').lstrip('0')} – {ends.strftime('%I:%M %p').lstrip('0')}",
        'total': f'{booking.total_price:,.2f}',
        'paid': is_paid(booking),
        'status': booking.booking_status,
        'checked_in_at': _local(booking.checked_in_at).strftime('%I:%M %p').lstrip('0') if booking.checked_in_at else '',
        'checked_in_by': (booking.checked_in_by.firstname if booking.checked_in_by else ''),
        'ends_at': booking.session_ends_at.isoformat() if booking.session_ends_at else '',
    }


def check(booking, now=None):
    """
    Can this booking start playing time now?
    Returns (ok: bool, reason: str, message: str). reason is a short key the
    page uses for styling: ok, already, status, day, early, ended, unpaid.
    """
    now = now or timezone.now()
    opens, starts, ends = booking_window(booking)

    if booking.checked_in_at:
        checked = _local(booking.checked_in_at).strftime('%I:%M %p').lstrip('0')
        if booking.session_ends_at and booking.session_ends_at <= now:
            ended = _local(booking.session_ends_at).strftime('%I:%M %p').lstrip('0')
            return False, 'already', (f'This booking is finished: checked in at {checked}, '
                                      f'playing time ended at {ended}. It cannot be started again.')
        return False, 'already', (f'Already checked in at {checked} and playing now. '
                                  'Playing time cannot be started twice.')
    if booking.booking_status != 'Approved':
        messages = {
            'Pending': 'This booking has not been approved yet.',
            'Cancelled': 'This booking was cancelled.',
            'Completed': 'This booking is already completed.',
        }
        return False, 'status', messages.get(booking.booking_status, 'This booking cannot be checked in.')

    local_now = _local(now)
    if local_now.date() != booking.booking_date:
        return False, 'day', f"This booking is for {booking.booking_date.strftime('%a, %b %d')}, not today."
    if now < opens:
        return False, 'early', (f"Too early. Check-in opens at "
                                f"{_local(opens).strftime('%I:%M %p').lstrip('0')} "
                                f"({EARLY_MINUTES} minutes before the start).")
    if now >= ends:
        return False, 'ended', 'This booking time has already ended.'
    if not is_paid(booking):
        return False, 'unpaid', (f'Unpaid. Collect ₱{booking.total_price:,.2f} and record the payment '
                                 'before starting the playing time.')
    return True, 'ok', 'Booking verified. Ready to start the playing time.'


def find_booking(code):
    if not code:
        return None
    return (Booking.objects.select_related('customer', 'court', 'checked_in_by')
            .filter(confirmation_code=code).first())


# ─── Starting and ending playing time ─────────────────────────────

def start_session(booking, admin, now=None):
    """
    Start playing time. Safe against double check-in: the database update
    only succeeds while checked_in_at is still empty.
    Returns (ok, reason, message).
    """
    now = now or timezone.now()
    ok, reason, message = check(booking, now)
    if not ok:
        return ok, reason, message

    _, _, ends = booking_window(booking)
    updated = (Booking.objects
               .filter(pk=booking.pk, checked_in_at__isnull=True, booking_status='Approved')
               .update(checked_in_at=now, checked_in_by=admin, session_ends_at=ends))
    booking.refresh_from_db()
    if not updated:
        return check(booking, now)          # someone else checked it in a moment ago
    return True, 'started', 'Playing time started.'


def record_cash_payment(booking):
    """Staff collected cash at the court: mark the booking Paid (Cash)."""
    payment, created = Payment.objects.get_or_create(
        booking=booking,
        defaults={'payment_amount': booking.total_price, 'payment_status': 'Paid', 'payment_method': 'Cash'},
    )
    if not created and payment.payment_status != 'Paid':
        payment.payment_amount = booking.total_price
        payment.payment_status = 'Paid'
        payment.payment_method = 'Cash'
        payment.save()
    return payment


def complete_finished_sessions(now=None):
    """Mark bookings Completed once their playing time is over. Returns the count."""
    now = now or timezone.now()
    return (Booking.objects
            .filter(booking_status='Approved', checked_in_at__isnull=False, session_ends_at__lte=now)
            .update(booking_status='Completed'))


def active_sessions(now=None):
    now = now or timezone.now()
    return (Booking.objects.select_related('customer', 'court', 'checked_in_by', 'payment')
            .filter(booking_status='Approved', checked_in_at__isnull=False, session_ends_at__gt=now)
            .order_by('session_ends_at'))


def end_session_early(booking, now=None):
    """
    The customer finished before their time was up: stop the countdown now
    and mark the booking Completed. The rest of the slot becomes free for
    new bookings. Safe against double clicks (only one update can succeed).
    Returns (ok, reason, message).
    """
    now = now or timezone.now()
    if not booking.checked_in_at:
        return False, 'not_started', 'Playing time has not started for this booking.'
    updated = (Booking.objects
               .filter(pk=booking.pk, booking_status='Approved',
                       checked_in_at__isnull=False, session_ends_at__gt=now)
               .update(session_ends_at=now, booking_status='Completed'))
    unused = booking.session_ends_at - now if booking.session_ends_at else None
    booking.refresh_from_db()
    if not updated:
        return False, 'already_ended', 'Playing time for this booking has already ended.'
    minutes = max(int(unused.total_seconds() // 60), 0) if unused else 0
    left = f'{minutes // 60} h {minutes % 60} min' if minutes >= 60 else f'{minutes} min'
    return True, 'ended', (f"Playing time ended early at {_local(now).strftime('%I:%M %p').lstrip('0')} "
                           f"({left} unused). The booking is now Completed.")

