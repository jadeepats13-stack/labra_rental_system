"""
EmailJS integration (external API #3).

Sends the "Booking Confirmation" email to the customer right after they book,
using EmailJS's REST endpoint from the Django server:
    POST https://api.emailjs.com/api/v1.0/email/send

The template variables below match the existing EmailJS template:
    {{customer_name}}, {{booking_id}}, {{booking_date}}, {{booking_time}},
    {{total_amount}}, {{payment_status}}, {{confirmation_id}}, {{qr_code_url}}
plus {{to_email}}, which the template's "To Email" setting must use.

Requirements in the EmailJS dashboard:
  * Account -> Security -> "Allow EmailJS API for non-browser applications" ON
  * The private key is sent as accessToken (keeps the request authorised).
A failed email never cancels the booking; we just report it.
"""
import logging
from html import escape

import requests
from django.conf import settings

from .qr_code import qr_image_url

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
        # Check-in QR (goQR.me image) + Booking Confirmation ID
        'confirmation_id': booking.confirmation_code or '',
        'qr_code_url': qr_image_url(booking.confirmation_code) if booking.confirmation_code else '',
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


# ─── Second template: short messages (codes + contact form) ─────────
# The free EmailJS plan allows 2 templates: the booking email above, and this
# general "message" template (EMAILJS_CODE_TEMPLATE_ID) with:
#     To Email: {{to_email}}    Reply To: {{reply_to}}
#     Subject:  {{subject}}     Content:  {{{message}}}
# (three braces so the line breaks in the message show up)

def send_message_email(to_email, subject, message_html, reply_to='', extra=None):
    """Send one email with the message template. Returns (sent: bool, error_message: str)."""
    required = [settings.EMAILJS_SERVICE_ID, getattr(settings, 'EMAILJS_CODE_TEMPLATE_ID', ''),
                settings.EMAILJS_PUBLIC_KEY, settings.EMAILJS_PRIVATE_KEY]
    if not all(required) or not to_email:
        return False, 'Email is not set up yet. Please contact the court by phone.'
    params = {'to_email': to_email, 'subject': subject, 'message': message_html, 'reply_to': reply_to}
    params.update(extra or {})
    payload = {
        'service_id': settings.EMAILJS_SERVICE_ID,
        'template_id': settings.EMAILJS_CODE_TEMPLATE_ID,
        'user_id': settings.EMAILJS_PUBLIC_KEY,
        'accessToken': settings.EMAILJS_PRIVATE_KEY,
        'template_params': params,
    }
    try:
        response = requests.post(SEND_URL, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning('EmailJS message request failed: %s', exc)
        return False, 'We could not send the email right now. Please try again in a minute.'
    if response.status_code == 200:
        return True, ''
    logger.warning('EmailJS message error %s: %s', response.status_code, response.text[:300])
    return False, 'We could not send the email right now. Please try again in a minute.'


# ─── Verification codes (sign-up confirmation and password reset) ───
CODE_TEXT = {
    'verify': ('Confirm your email', 'Use this code to confirm your email and finish creating your account.'),
    'reset': ('Reset your password', 'Use this code to set a new password for your account.'),
}


def send_code_email(customer, code, purpose, minutes):
    """Email a 6-digit code. Returns (sent: bool, message: str)."""
    title, text = CODE_TEXT[purpose]
    name = escape(f'{customer.firstname} {customer.lastname}'.strip())
    message_html = (f'Hi {name},<br><br>{text}<br><br>'
                    f'Your code: <b style="font-size:22px;letter-spacing:3px">{code}</b><br><br>'
                    f'It expires in {minutes} minutes. If you didn\'t ask for this, you can ignore this email.'
                    '<br><br>Labra Basketball Court')
    sent, error = send_message_email(
        customer.email, f'{code} is your code – {title}', message_html,
        extra={'code': code, 'purpose_title': title, 'purpose_text': text, 'expires_minutes': minutes,
               'customer_name': f'{customer.firstname} {customer.lastname}'.strip()})
    if not sent:
        return False, ('Email codes are not set up yet. Please contact the court.'
                       if error.startswith('Email is not set up') else
                       'We could not send the code right now. Please try again in a minute.')
    return True, 'Code sent.'


def send_contact_email(name, email, message):
    """Landing page contact form -> the court's inbox (CONTACT_EMAIL). Reply goes to the visitor."""
    body = escape(message).replace('\n', '<br>')
    message_html = (f'New message from the website contact form.<br><br>'
                    f'<b>Name:</b> {escape(name)}<br><b>Email:</b> {escape(email)}<br><br>{body}')
    return send_message_email(getattr(settings, 'CONTACT_EMAIL', ''),
                              f'Website message from {name}', message_html, reply_to=email)
