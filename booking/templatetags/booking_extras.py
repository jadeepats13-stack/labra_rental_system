"""Small template helpers for the customer pages."""
from django import template

from ..availability import format_hours
from ..services.qr_code import qr_image_url

register = template.Library()


@register.filter
def hours(value):
    """{{ 9.5|hours }} -> '9.5', {{ 14.0|hours }} -> '14'"""
    try:
        return format_hours(float(value))
    except (TypeError, ValueError):
        return value


@register.filter
def qr_url(code, size=240):
    """{{ booking.confirmation_code|qr_url }} -> goQR.me image URL for that code."""
    return qr_image_url(code, int(size)) if code else ''
