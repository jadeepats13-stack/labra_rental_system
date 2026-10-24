"""Give every existing Approved booking a Confirmation ID (new ones get it on approval)."""
import secrets

from django.db import migrations

ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'   # no 0/O or 1/I


def new_code(existing):
    while True:
        code = 'LBC-' + ''.join(secrets.choice(ALPHABET) for _ in range(4)) + '-' + \
               ''.join(secrets.choice(ALPHABET) for _ in range(4))
        if code not in existing:
            existing.add(code)
            return code


def add_codes(apps, schema_editor):
    Booking = apps.get_model('booking', 'Booking')
    existing = set(Booking.objects.exclude(confirmation_code=None).values_list('confirmation_code', flat=True))
    for booking in Booking.objects.filter(booking_status='Approved', confirmation_code=None):
        booking.confirmation_code = new_code(existing)
        booking.save(update_fields=['confirmation_code'])


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0004_booking_checkin'),
    ]

    operations = [
        migrations.RunPython(add_codes, migrations.RunPython.noop),
    ]
