"""
EmailJS integration (external API #3).

Sends the "Booking Confirmation" email to the customer right after they book,
using EmailJS's REST endpoint from the Django server:
    POST https://api.emailjs.com/api/v1.0/email/send

The template variables below match the existing EmailJS template:
    {{customer_name}}, {{booking_id}}, {{booking_date}}, {{booking_time}},
    {{total_amount}}, {{payment_status}}
plus {{to_email}}, which the template's "To Email" setting must use.

Requirements in the EmailJS dashboard:
  * Account -> Security -> "Allow EmailJS API for non-browser applications" ON
  * The private key is sent as accessToken (keeps the request authorised).
A failed email never cancels the booking; we just report it.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SEND_URL = 'https://api.emailjs.com/api/v1.0/email/send'
REQUEST_TIMEOUT = 8  # seconds


def build_booking_template_params(booking):
    """Values for each {{variable}} in the EmailJS booking template."""
    customer = booking.customer
    payment = getattr(booking, 'payment', None)
    payment_status = payment.payment_status if payment else 'Unpaid'
    start = booking.start_time.strftime('%I:%M %p').lstrip('0')
    end = booking.end_time.strftime('%I:%M %p').lstrip('0')

    return {
        'to_email': customer.email,
        'customer_name': f'{customer.firstname} {customer.lastname}'.strip(),
        'booking_id': booking.booking_id,
        'booking_date': booking.booking_date.strftime('%B %d, %Y'),
        'booking_time': f'{start} – {end}',
        'total_amount': f'{booking.total_price:,.2f}',
        'payment_status': payment_status,
    }


def send_booking_confirmation(booking):
    """
    Send the booking confirmation email.
    Returns (sent: bool, message: str) so the view can tell the customer.
    """
    # Reload from the database so dates/times are real date objects
    # (book_court creates the booking from the raw form text)
    booking.refresh_from_db()

    if not booking.customer.email:
        return False, 'Add your email address in Edit Profile to receive booking emails.'

    required = [settings.EMAILJS_SERVICE_ID, settings.EMAILJS_TEMPLATE_ID,
                settings.EMAILJS_PUBLIC_KEY, settings.EMAILJS_PRIVATE_KEY]
    if not all(required):
        return False, 'Booking email is not set up yet.'

    payload = {
        'service_id': settings.EMAILJS_SERVICE_ID,
        'template_id': settings.EMAILJS_TEMPLATE_ID,
        'user_id': settings.EMAILJS_PUBLIC_KEY,
        'accessToken': settings.EMAILJS_PRIVATE_KEY,
        'template_params': build_booking_template_params(booking),
    }

    try:
        response = requests.post(SEND_URL, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning('EmailJS request failed: %s', exc)
        return False, 'We could not send your confirmation email right now.'

    if response.status_code == 200:
        return True, f'A confirmation email was sent to {booking.customer.email}.'

    # EmailJS returns a short plain-text reason, e.g. when non-browser access is off
    logger.warning('EmailJS error %s: %s', response.status_code, response.text[:300])
    return False, 'We could not send your confirmation email right now.'
