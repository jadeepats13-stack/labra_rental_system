"""
Landing page chatbot ("Labra Assistant").

  * Quick buttons are answered right away from our own data (no AI):
    free time today, rate, hours, weather, location, how to book / pay /
    check in, contact.
  * Typed questions go to Google Gemini (services/gemini.py) together with
    the court's live facts, so it can reply in English, Tagalog or Bisaya.
  * If Gemini is not set up, fails, or the free quota is used up, the
    built-in answers are used instead, so the chatbot always replies.
  * Each visitor can type a limited number of questions per hour, and there
    is a daily cap for the whole site to protect the free Gemini quota.
"""
import re
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import availability
from .models import Court
from .services import gemini
from .services.weather import get_daily_forecast

ADDRESS = 'Zone 7, Tambacan, Iligan City'
PHONE = '+63 912 345 6789'
EMAIL = 'labracourt@gmail.com'
MAX_MESSAGE = 500          # characters per question
MAX_HISTORY = 6            # earlier messages sent to Gemini for context


# ─── Live facts ────────────────────────────────────────────────────

def _label(minutes):
    h, m = divmod(minutes, 60)
    suffix = 'AM' if h < 12 else 'PM'
    return f"{(h - 1) % 12 + 1}:{m:02d} {suffix}"


def free_ranges(day, now=None):
    """Free time on `day` as text ranges, e.g. ['3:00 PM - 5:30 PM']."""
    now = now or timezone.localtime()
    bookings = list(availability.taken_bookings(day, day))
    taken = [(b.start_time.hour * 60 + b.start_time.minute, b.end_time.hour * 60 + b.end_time.minute)
             for b in bookings]
    ranges, start = [], None
    step = availability.SLOT_MINUTES
    for slot in range(availability.OPEN_HOUR * 60, availability.CLOSE_HOUR * 60, step):
        past = day < now.date() or (day == now.date() and slot <= now.hour * 60 + now.minute)
        busy = past or any(s < slot + step and e > slot for s, e in taken)
        if not busy and start is None:
            start = slot
        if busy and start is not None:
            ranges.append((start, slot))
            start = None
    if start is not None:
        ranges.append((start, availability.CLOSE_HOUR * 60))
    return [f'{_label(a)} - {_label(b)}' for a, b in ranges]


def court_facts(now=None):
    """Everything the chatbot may say, built from the booking database and the weather API."""
    now = now or timezone.localtime()
    court = Court.objects.order_by('court_id').first()
    rate = f'{court.rate_per_hour:,.2f}' if court else '200.00'
    available = bool(court and court.court_status == 'Available')
    weather = get_daily_forecast()

    days = []
    for offset in range(7):
        day = now.date() + timedelta(days=offset)
        w = weather.get(day.isoformat())
        days.append({
            'date': day,
            'name': 'Today' if offset == 0 else ('Tomorrow' if offset == 1 else day.strftime('%A')),
            'free': free_ranges(day, now) if available else [],
            'weather': (f"{w['description']}, {w['temperature']}°C, {w['rain_chance']}% chance of rain"
                        if w else ''),
        })
    return {'now': now, 'rate': rate, 'available': available, 'days': days}


def facts_text(facts):
    lines = [
        f"Current date and time: {facts['now'].strftime('%A, %B %d, %Y %I:%M %p')} (Philippine time).",
        'Court: one outdoor court called the LA Court, booked as a whole court.',
        f'Address: {ADDRESS}. Contact: {PHONE}, {EMAIL}.',
        f"Rate: PHP {facts['rate']} per hour. Open every day 8:00 AM to 10:00 PM. "
        'Bookings are in 30-minute steps (minimum 30 minutes).',
        'Court status: ' + ('available for booking.' if facts['available']
                            else 'closed for maintenance, no bookings right now.'),
        'How to book: sign up or log in on this website, open Book Court, pick a date and a free '
        'start and end time (booked times are greyed out), then confirm. New bookings are Pending '
        'until the staff approves them. A booking email with a QR code is sent.',
        'Payment: online with PayPal, or in cash at the court before playing. '
        'Playing time can only start once the booking is paid.',
        'Check-in: show the QR code from the booking email (or the Booking Confirmation ID, like '
        'LBC-XXXX-XXXX) to the staff. Check-in opens 15 minutes before the start time. Playing time '
        'ends at the reserved end time even if the customer arrives late.',
        'Cancelling: customers can cancel their own booking in My Bookings before they check in.',
        'Free time and weather for the next 7 days:',
    ]
    for d in facts['days']:
        free = ', '.join(d['free']) if d['free'] else 'fully booked or closed'
        weather = f"; weather: {d['weather']}" if d['weather'] else ''
        lines.append(f"- {d['name']} ({d['date'].strftime('%a %b %d')}): free {free}{weather}")
    return '\n'.join(lines)


# ─── Built-in answers (quick buttons and fallback) ────────────────

def _today(facts):
    return facts['days'][0]


def answer_free(facts):
    if not facts['available']:
        return f'The LA Court is closed for maintenance right now, so it can\'t be booked. Please call {PHONE} for updates.'
    today = _today(facts)
    if today['free']:
        text = 'Free today: ' + ', '.join(today['free']) + '.'
    elif facts['now'].hour * 60 + facts['now'].minute >= availability.CLOSE_HOUR * 60 - availability.SLOT_MINUTES:
        text = 'We\'re closed for the rest of today (open 8:00 AM to 10:00 PM).'
    else:
        text = 'Today is fully booked.'
    nxt = next((d for d in facts['days'][1:] if d['free']), None)
    if nxt:
        text += f" {nxt['name']} has free time from {nxt['free'][0].split(' - ')[0]}."
    return text + ' Log in or sign up to book.'


def answer_price(facts):
    return (f"The LA Court costs ₱{facts['rate']} per hour for the whole court. "
            'You can book in 30-minute steps, and you only pay for the time you book.')


def answer_hours(facts):
    return 'We are open every day from 8:00 AM to 10:00 PM. Bookings start on the hour or half hour.'


def answer_weather(facts):
    today = _today(facts)
    if today['weather']:
        text = f"Today at the court: {today['weather']}."
        tomorrow = facts['days'][1]
        if tomorrow['weather']:
            text += f" Tomorrow: {tomorrow['weather']}."
        return text + ' It\'s an outdoor court, so check the forecast before you book.'
    return 'The weather forecast isn\'t available right now. It\'s an outdoor court, so please check before you play.'


def answer_location(facts):
    return f'The LA Court is at {ADDRESS}. It\'s an outdoor court surrounded by trees. For directions, call {PHONE}.'


def answer_book(facts):
    return ('1) Sign up or log in (buttons at the top). 2) Open Book Court and pick a date. '
            '3) Choose a free start and end time; booked times are greyed out. 4) Confirm. '
            'Your booking is Pending until the staff approves it, and you get an email with your QR code.')


def answer_pay(facts):
    return ('You can pay online with PayPal, or in cash at the court before you play. '
            'Your playing time can only start once the booking is paid.')


def answer_checkin(facts):
    return ('Show the QR code from your booking email (or your Confirmation ID, like LBC-XXXX-XXXX) to the staff. '
            'Check-in opens 15 minutes before your start time, and your time ends at the reserved end time.')


def answer_cancel(facts):
    return 'You can cancel your own booking in My Bookings before you check in. For other changes, call ' + PHONE + '.'


def answer_contact(facts):
    return f'Call or text {PHONE}, or email {EMAIL}. You can also use the contact form at the bottom of this page.'


def answer_hello(facts):
    return ('Hi! I\'m Labra Assistant. Ask me about free times, prices, hours, payment or check-in. '
            'Pwede ka rin magtanong sa Tagalog o Bisaya.')


INTENTS = {
    'free': answer_free, 'price': answer_price, 'hours': answer_hours, 'weather': answer_weather,
    'location': answer_location, 'book': answer_book, 'pay': answer_pay, 'checkin': answer_checkin,
    'cancel': answer_cancel, 'contact': answer_contact, 'hello': answer_hello,
}

# Keywords in English, Tagalog and Bisaya (used only when the AI is unavailable)
KEYWORDS = [
    ('checkin', r'\bqr\b|check.?in|confirmation|\blbc\b'),
    ('cancel', r'cancel|kansel|i-?cancel'),
    ('weather', r'weather|rain|\bulan\b|panahon|init|hot\b'),
    ('price', r'price|rate|how much|cost|magkano|presyo|\bpila\b|hourly'),
    ('pay', r'\bpay|paypal|payment|bayad|cash|gcash'),
    ('free', r'\bfree\b|available|availability|vacant|bakante|\bslot|schedule|libre|naa.*(bakante|space)'),
    ('hours', r'\bhours?\b|\bopen|close|oras|abri|sira|what time'),
    ('location', r'where|location|address|saan|\basa\b|direction|map|tambacan'),
    ('book', r'\bbook|reserv|magpa-?book|unsaon|paano'),
    ('contact', r'contact|phone|number|email|call|tawag|text'),
    ('hello', r'^\s*(hi|hello|hey|kumusta|musta|maayong|good (morning|afternoon|evening))\b'),
]


def match_intent(text):
    lowered = (text or '').lower()
    for intent, pattern in KEYWORDS:
        if re.search(pattern, lowered):
            return intent
    return None


FALLBACK = (f'Sorry, I can only help with booking, prices, hours, payment, check-in and location. '
            f'For anything else, call {PHONE} or email {EMAIL}.')


# ─── Limits ─────────────────────────────────────────────────────

def _client_id(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', '')) or 'unknown'


def _count(key, timeout):
    cache.add(key, 0, timeout)
    try:
        return cache.incr(key)
    except ValueError:              # expired between add() and incr()
        cache.set(key, 1, timeout)
        return 1


def allow_question(request):
    """True if this visitor may send another typed question this hour."""
    limit = getattr(settings, 'CHATBOT_HOURLY_LIMIT', 20)
    return _count(f'chatbot:visitor:{_client_id(request)}', 3600) <= limit


def allow_ai_today():
    """Site-wide daily cap, so the free Gemini quota is not used up by one day's traffic."""
    limit = getattr(settings, 'CHATBOT_DAILY_AI_LIMIT', 200)
    return _count(f'chatbot:ai:{timezone.localdate().isoformat()}', 86400) <= limit


# ─── Main entry point ───────────────────────────────────────────

def clean_history(history):
    turns = []
    for turn in history if isinstance(history, list) else []:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get('text', '')).strip()[:MAX_MESSAGE]
        if text:
            turns.append({'role': 'bot' if turn.get('role') == 'bot' else 'user', 'text': text})
    return turns[-MAX_HISTORY:]


def reply(request, message='', intent='', history=None):
    """Returns a dict: {'reply': str, 'source': 'quick'|'ai'|'builtin', 'limited': bool}."""
    facts = court_facts()

    if intent:                                      # quick button: instant, no AI, no limit
        handler = INTENTS.get(intent)
        return {'reply': handler(facts) if handler else FALLBACK, 'source': 'quick', 'limited': False}

    message = (message or '').strip()[:MAX_MESSAGE]
    if not message:
        return {'reply': 'Type a question, or tap one of the buttons.', 'source': 'builtin', 'limited': False}

    if not allow_question(request):
        return {'reply': ('You\'ve reached the limit of questions for now. Please try again in an hour, '
                          f'or call {PHONE}.'), 'source': 'builtin', 'limited': True}

    if allow_ai_today():
        text, status = gemini.ask(message, clean_history(history), facts_text(facts))
        if text:
            return {'reply': text, 'source': 'ai', 'limited': False}

    intent = match_intent(message)
    return {'reply': INTENTS[intent](facts) if intent else FALLBACK, 'source': 'builtin', 'limited': False}
