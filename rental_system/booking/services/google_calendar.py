"""
Google Calendar integration (external API #4).

The admin connects their Google account once (OAuth 2.0). After that, every
booking the admin approves is added to the admin's primary Google Calendar,
and removed again if that booking is cancelled.

Endpoints used (all plain HTTPS calls with `requests`):
    https://accounts.google.com/o/oauth2/v2/auth          (admin signs in)
    https://oauth2.googleapis.com/token                   (code/refresh -> tokens)
    https://oauth2.googleapis.com/revoke                  (disconnect)
    https://www.googleapis.com/calendar/v3/calendars/primary/events

Only the admin's tokens are stored (GoogleCalendarToken table). Calendar
problems never block approving or cancelling a booking.
"""
import base64
import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ..models import GoogleCalendarToken

logger = logging.getLogger(__name__)

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
REVOKE_URL = 'https://oauth2.googleapis.com/revoke'
EVENTS_URL = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'
SCOPES = 'openid email https://www.googleapis.com/auth/calendar.events'
REQUEST_TIMEOUT = 8  # seconds
TIME_ZONE = 'Asia/Manila'
BOOKING_TAG = 'labra_booking_id'
LIST_CACHE_SECONDS = 60   # reuse a schedule read for 1 minute
# Older events (created before the tag existed) are recognised by their title
TITLE_PATTERN = re.compile(r'Booking #(\d+)')


class CalendarError(Exception):
    """Raised when Google Calendar cannot be reached or refuses a request."""


def is_configured():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def build_auth_url(state):
    params = {
        'client_id': settings.GOOGLE_CLIENT_ID,
        'redirect_uri': settings.GOOGLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPES,
        'access_type': 'offline',   # ask for a refresh token
        'prompt': 'consent',        # always return a refresh token
        'state': state,             # protects against forged callbacks
    }
    return f'{AUTH_URL}?{urlencode(params)}'


def _email_from_id_token(id_token):
    """Read the Google email from the ID token we just received from Google."""
    try:
        payload = id_token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get('email', '')
    except Exception:
        return ''


def exchange_code_and_save(admin, code):
    """Swap the one-time code from Google for tokens and store them."""
    response = requests.post(TOKEN_URL, data={
        'code': code,
        'client_id': settings.GOOGLE_CLIENT_ID,
        'client_secret': settings.GOOGLE_CLIENT_SECRET,
        'redirect_uri': settings.GOOGLE_REDIRECT_URI,
        'grant_type': 'authorization_code',
    }, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        logger.warning('Google token exchange failed: %s', response.text[:300])
        raise CalendarError('Google did not accept the sign-in. Please try connecting again.')

    data = response.json()
    existing = GoogleCalendarToken.objects.filter(admin=admin).first()
    GoogleCalendarToken.objects.update_or_create(
        admin=admin,
        defaults={
            'access_token': data['access_token'],
            # Google only sends a refresh token on first consent; keep the old one otherwise
            'refresh_token': data.get('refresh_token') or (existing.refresh_token if existing else ''),
            'token_expiry': timezone.now() + timedelta(seconds=int(data.get('expires_in', 3600)) - 60),
            'google_email': _email_from_id_token(data.get('id_token', '')),
        },
    )


def _valid_access_token(token):
    """Return a working access token, refreshing it if it has expired."""
    if token.token_expiry > timezone.now():
        return token.access_token
    if not token.refresh_token:
        raise CalendarError('Google Calendar connection expired. Please reconnect it.')

    response = requests.post(TOKEN_URL, data={
        'client_id': settings.GOOGLE_CLIENT_ID,
        'client_secret': settings.GOOGLE_CLIENT_SECRET,
        'refresh_token': token.refresh_token,
        'grant_type': 'refresh_token',
    }, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        # e.g. "invalid_grant": testing-mode refresh tokens expire after 7 days
        logger.warning('Google token refresh failed: %s', response.text[:300])
        raise CalendarError('Google Calendar connection expired. Please reconnect it.')

    data = response.json()
    token.access_token = data['access_token']
    token.token_expiry = timezone.now() + timedelta(seconds=int(data.get('expires_in', 3600)) - 60)
    token.save(update_fields=['access_token', 'token_expiry'])
    return token.access_token


def get_connection():
    """The admin's stored Google connection (single-admin system), or None."""
    return GoogleCalendarToken.objects.select_related('admin').first()


def build_event(booking):
    customer = booking.customer
    court_name = booking.court.court_name or 'LA Court'
    start = datetime.combine(booking.booking_date, booking.start_time)
    end = datetime.combine(booking.booking_date, booking.end_time)
    return {
        'summary': f'{court_name} – Booking #{booking.booking_id} ({customer.firstname} {customer.lastname})',
        'location': 'Labra Basketball Court, Tambacan, Iligan City',
        'description': (
            f'Customer: {customer.firstname} {customer.lastname} (@{customer.username})\n'
            f'Total: PHP {booking.total_price}\n'
            f'Added automatically by the Labra Basketball Court Rental System.'
        ),
        'start': {'dateTime': start.strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': TIME_ZONE},
        'end': {'dateTime': end.strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': TIME_ZONE},
        # Hidden tag so the system can find its own events (and ignore personal ones)
        'extendedProperties': {'private': {BOOKING_TAG: str(booking.booking_id)}},
    }


def add_booking_event(booking):
    """
    Add an approved booking to the admin's Google Calendar.
    Returns (ok: bool, message: str). Never raises.
    """
    token = get_connection()
    if not token:
        return False, 'Google Calendar is not connected, so this booking was not added to it.'
    if booking.google_event_id:
        return True, 'This booking is already in Google Calendar.'

    try:
        access_token = _valid_access_token(token)
        response = requests.post(
            EVENTS_URL, json=build_event(booking),
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=REQUEST_TIMEOUT,
        )
    except CalendarError as exc:
        return False, str(exc)
    except requests.RequestException as exc:
        logger.warning('Google Calendar request failed: %s', exc)
        return False, 'Google Calendar could not be reached, so this booking was not added to it.'

    if response.status_code in (200, 201):
        booking.google_event_id = response.json().get('id', '')
        booking.save(update_fields=['google_event_id'])
        clear_events_cache()
        return True, 'Added to Google Calendar.'

    logger.warning('Google Calendar error %s: %s', response.status_code, response.text[:300])
    return False, 'Google Calendar refused the request, so this booking was not added to it.'


def remove_booking_event(booking):
    """Delete a cancelled booking's event, if it was added. Never raises."""
    if not booking.google_event_id:
        return True, ''
    token = get_connection()
    if not token:
        return False, 'Google Calendar is not connected, so the event could not be removed.'

    try:
        access_token = _valid_access_token(token)
        response = requests.delete(
            f'{EVENTS_URL}/{booking.google_event_id}',
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=REQUEST_TIMEOUT,
        )
    except CalendarError as exc:
        return False, str(exc)
    except requests.RequestException:
        return False, 'Google Calendar could not be reached, so the event could not be removed.'

    # 404/410 = already deleted in Google Calendar, which is fine
    if response.status_code in (200, 204, 404, 410):
        booking.google_event_id = ''
        booking.save(update_fields=['google_event_id'])
        clear_events_cache()
        return True, 'Removed from Google Calendar.'
    return False, 'Google Calendar refused to remove the event.'


# ─── Reading the schedule back from Google Calendar ────────────────

def clear_events_cache():
    cache.delete_many([k for k in (cache.get('gcal_cache_keys') or [])])
    cache.delete('gcal_cache_keys')


def _to_rfc3339(dt):
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt.isoformat()


def list_booking_events(time_min, time_max):
    """
    Read the court-booking events between time_min and time_max (datetimes)
    from the admin's Google Calendar. Personal events are skipped.

    Returns a list of dicts: booking_id (int or None), event_id, summary,
    start, end (aware datetimes). Raises CalendarError if Google is not
    connected or cannot be reached.
    """
    token = get_connection()
    if not token:
        raise CalendarError('Google Calendar is not connected.')

    params = {
        'timeMin': _to_rfc3339(time_min),
        'timeMax': _to_rfc3339(time_max),
        'singleEvents': 'true',
        'orderBy': 'startTime',
        'maxResults': 250,
        'timeZone': TIME_ZONE,
    }
    cache_key = 'gcal_events_' + params['timeMin'] + '_' + params['timeMax']
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        access_token = _valid_access_token(token)
        response = requests.get(EVENTS_URL, params=params,
                                headers={'Authorization': f'Bearer {access_token}'},
                                timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning('Google Calendar list failed: %s', exc)
        raise CalendarError('Google Calendar could not be reached.')

    if response.status_code != 200:
        logger.warning('Google Calendar list error %s: %s', response.status_code, response.text[:300])
        raise CalendarError('Google Calendar refused the request.')

    events = []
    for item in response.json().get('items', []):
        if item.get('status') == 'cancelled':
            continue
        tag = (item.get('extendedProperties') or {}).get('private', {}).get(BOOKING_TAG)
        match = TITLE_PATTERN.search(item.get('summary', ''))
        if not tag and not (match and 'LA Court' in item.get('summary', '')):
            continue  # not created by this system: a personal event
        start = parse_datetime((item.get('start') or {}).get('dateTime', ''))
        end = parse_datetime((item.get('end') or {}).get('dateTime', ''))
        if not start or not end:
            continue
        booking_id = tag or (match.group(1) if match else None)
        events.append({
            'booking_id': int(booking_id) if booking_id and str(booking_id).isdigit() else None,
            'event_id': item.get('id', ''),
            'summary': item.get('summary', ''),
            'start': start,
            'end': end,
        })

    cache.set(cache_key, events, LIST_CACHE_SECONDS)
    keys = cache.get('gcal_cache_keys') or []
    cache.set('gcal_cache_keys', list(set(keys + [cache_key])), LIST_CACHE_SECONDS * 10)
    return events


def upcoming_booking_events(limit=5, days_ahead=60):
    """The next few approved bookings, read from Google Calendar."""
    now = timezone.now()
    events = list_booking_events(now, now + timedelta(days=days_ahead))
    return [e for e in events if e['end'] > now][:limit]


def disconnect(token):
    """Revoke Google access (best effort) and delete the stored tokens."""
    try:
        requests.post(REVOKE_URL, data={'token': token.refresh_token or token.access_token},
                      timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        pass
    token.delete()
    clear_events_cache()
