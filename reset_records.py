"""
Deletes all customers, bookings, payments and damage reports, then restarts
their ID numbers at 1. Keeps the admin account(s), the LA Court record and
the Google Calendar connection.

Run from the project folder (PowerShell):
    Get-Content reset_records.py | python manage.py shell
"""
from django.db import connection, transaction

from booking.models import Booking, Customer, Damage, Payment

MODELS = [Damage, Payment, Booking, Customer]  # children first

with transaction.atomic():
    for model in MODELS:
        count, _ = model.objects.all().delete()
        print(f'Deleted {count} row(s) from {model._meta.db_table}')

    # SQLite remembers the last used ID in sqlite_sequence; removing the
    # entry makes the next record start at 1 again.
    tables = [m._meta.db_table for m in MODELS]
    with connection.cursor() as cursor:
        cursor.execute(
            'DELETE FROM sqlite_sequence WHERE name IN (%s)' % ','.join(['%s'] * len(tables)),
            tables,
        )

print('Done. New customers, bookings, payments and damage reports will start at ID 1.')