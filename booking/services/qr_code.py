"""
goQR.me QR Code API (external API #5) - https://goqr.me/api/

Free, no API key. The create-qr-code endpoint builds the check-in QR image
for each approved booking (it contains the Booking Confirmation ID). The
image URL is shown in the customer's account and in the approval email.

If goQR.me is unavailable the Confirmation ID (printed under every QR) still
works, because staff can type it and both methods check the same booking.
"""
from urllib.parse import urlencode

CREATE_URL = 'https://api.qrserver.com/v1/create-qr-code/'


def qr_image_url(code, size=240):
    """URL of a PNG QR code containing the booking's Confirmation ID."""
    params = {
        'data': code,
        'size': f'{size}x{size}',
        'margin': 12,
        'ecc': 'M',
        'format': 'png',
    }
    return f'{CREATE_URL}?{urlencode(params)}'
