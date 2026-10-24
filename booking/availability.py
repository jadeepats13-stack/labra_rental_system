"""
Court availability helpers (plain Django, no external API).

Used by the customer availability calendar, the greyed-out time dropdowns,
and the customer dashboard ("This Week" strip, LA Court card).

Opening hours match the booking form: 8:00 AM to 10:00 PM, in 30-minute steps.
A slot is taken when a Pending or Approved booking overlaps it.
"""
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from .models import Booking

OPEN_HOUR = 8
CLOSE_HOUR = 22
SLOT_MINUTES = 30
OPEN_HOURS_PER_DAY = CLOSE_HOUR - OPEN_HOUR          # 14
ACTIVE_STATUSES = ('Pending', 'Approved')


def _minutes(t):
    return t.hour * 60 + t.minute


def taken_bookings(start_date, end_date):
    """Pending/Approved bookings from start_date to end_date (inclusive)."""
    return (Booking.objects
            .filter(booking_date__gte=start_date, booking_date__lte=end_date,
                    booking_status__in=ACTIVE_STATUSES)
            .order_by('booking_date', 'start_time'))


def free_hours(day, bookings=None, now=None):
    """
    Hours still free on `day` within opening hours.
    For today, slots that have already started are not counted as free.
    """
    now = now or timezone.localtime()
    if bookings is None:
        bookings = taken_bookings(day, day)
    intervals = [(_minutes(b.start_time), _minutes(b.end_time))
                 for b in bookings if b.booking_date == day]

    free_slots = 0
    for start in range(OPEN_HOUR * 60, CLOSE_HOUR * 60, SLOT_MINUTES):
        end = start + SLOT_MINUTES
        if day < now.date():
            continue
        if day == now.date() and start <= _minutes(now.time()):
            continue
        if any(s < end and e > start for s, e in intervals):
            continue
        free_slots += 1
    return free_slots * SLOT_MINUTES / 60


def week_overview(start_day, days=7, now=None):
    """Free hours for each of the next `days` days (one database query)."""
    now = now or timezone.localtime()
    end_day = start_day + timedelta(days=days - 1)
    bookings = list(taken_bookings(start_day, end_day))
    overview = []
    for i in range(days):
        day = start_day + timedelta(days=i)
        hours_free = free_hours(day, bookings, now)
        overview.append({
            'date': day,
            'free_hours': hours_free,
            'percent_free': round(hours_free / OPEN_HOURS_PER_DAY * 100),
        })
    return overview


def format_hours(value):
    """14.0 -> '14', 9.5 -> '9.5'"""
    return f'{value:g}'


def countdown_text(booking, now=None):
    """'in 2 days, 5 hours', 'in 3 hours', 'in 25 minutes', 'now'"""
    now = now or timezone.localtime()
    start = timezone.make_aware(datetime.combine(booking.booking_date, booking.start_time))
    seconds = (start - now).total_seconds()
    if seconds <= 0:
        return 'happening now'
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        parts = [f"{days} day{'s' if days != 1 else ''}"]
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        return 'in ' + ', '.join(parts)
    if hours:
        return f"in {hours} hour{'s' if hours != 1 else ''}" + (f", {minutes} min" if minutes else '')
    return f"in {max(minutes, 1)} min"


def next_game(customer, now=None):
    """The customer's next Pending/Approved booking that hasn't ended yet."""
    now = now or timezone.localtime()
    candidates = (Booking.objects
                  .filter(customer=customer, booking_status__in=ACTIVE_STATUSES,
                          booking_date__gte=now.date())
                  .select_related('court')
                  .order_by('booking_date', 'start_time'))
    for b in candidates:
        if b.booking_date > now.date() or b.end_time > now.time():
            return b
    return None
