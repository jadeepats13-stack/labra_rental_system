"""
Google Gemini API (external API #6) - landing page chatbot.

Typed questions from visitors go to Gemini together with the court's facts
(rate, hours, today's free time, weather, how booking works). Gemini replies
in the visitor's language (English, Tagalog or Bisaya) and is told to answer
only from those facts.

Free tier: no credit card, small daily quota. The key lives in .env
(GEMINI_API_KEY) and is only used on the server, never sent to the browser.
If Gemini fails or the quota is used up, ask() returns None and the chatbot
answers with its built-in replies instead, so it never breaks.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API_URL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
TIMEOUT = 15

RULES = """You are "Labra Assistant", the friendly chat helper on the website of
Labra Basketball Court (the LA Court) in Zone 7, Tambacan, Iligan City, Philippines.

Rules:
- Answer ONLY questions about the court, booking, prices, hours, payment,
  check-in, the weather at the court, location and contact details.
- Use ONLY the facts below. Never invent prices, rules, discounts, refunds,
  promos or free time slots. If something is not in the facts, say you are not
  sure and give the contact number and email.
- Reply in the same language the visitor uses: English, Tagalog (Filipino) or
  Bisaya (Cebuano). Mixed Taglish/Bislish is fine if the visitor writes that way.
- Keep answers short: 1 to 4 sentences, or a short list. Plain text only, no
  markdown symbols like ** or #.
- To book, visitors must create an account or log in on this website
  (Sign up / Log in buttons at the top). You cannot make, change or cancel
  bookings yourself.
- Politely decline unrelated topics and steer back to the court.
- Never ask for passwords, card numbers or other private information.
"""


def is_configured():
    return bool(getattr(settings, 'GEMINI_API_KEY', ''))


def ask(question, history, facts_text):
    """
    Returns (reply_text or None, status). status is 'ok', 'not_configured',
    'quota', 'auth' or 'error'.
    history: list of {'role': 'user'|'bot', 'text': str}, oldest first.
    """
    if not is_configured():
        return None, 'not_configured'

    contents = []
    for turn in history:
        role = 'model' if turn.get('role') == 'bot' else 'user'
        contents.append({'role': role, 'parts': [{'text': turn['text']}]})
    contents.append({'role': 'user', 'parts': [{'text': question}]})

    body = {
        'system_instruction': {'parts': [{'text': RULES + '\nFacts (live from the booking system):\n' + facts_text}]},
        'contents': contents,
        'generationConfig': {'temperature': 0.4, 'maxOutputTokens': 400},
    }
    model = getattr(settings, 'GEMINI_MODEL', '') or 'gemini-flash-lite-latest'
    try:
        resp = requests.post(
            API_URL.format(model=model),
            headers={'x-goog-api-key': settings.GEMINI_API_KEY, 'Content-Type': 'application/json'},
            json=body,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning('Gemini request failed: %s', exc)
        return None, 'error'

    if resp.status_code == 429:
        return None, 'quota'
    if resp.status_code in (401, 403):
        logger.warning('Gemini refused the API key (%s): %s', resp.status_code, resp.text[:300])
        return None, 'auth'
    if resp.status_code != 200:
        logger.warning('Gemini error %s: %s', resp.status_code, resp.text[:300])
        return None, 'error'

    try:
        parts = resp.json()['candidates'][0]['content']['parts']
        text = ''.join(p.get('text', '') for p in parts).strip()
    except (ValueError, KeyError, IndexError, TypeError):
        logger.warning('Gemini returned an unexpected response: %s', resp.text[:300])
        return None, 'error'
    if not text:
        return None, 'error'
    return text.replace('**', '').strip(), 'ok'
