"""
Data migration: Labra Basketball Court has a single court ("LA Court").

- Keeps the first court record (the original Labra court) and renames it "LA Court".
- Removes the other court records ONLY if they have no bookings, so no
  booking or payment history is ever deleted.
"""
from django.db import migrations


def make_single_la_court(apps, schema_editor):
    Court = apps.get_model('booking', 'Court')
    Booking = apps.get_model('booking', 'Booking')

    courts = list(Court.objects.order_by('court_id'))
    if not courts:
        return  # fresh database: the admin creates the court record later

    la_court = courts[0]
    la_court.court_name = 'LA Court'
    la_court.save(update_fields=['court_name'])

    for court in courts[1:]:
        if not Booking.objects.filter(court=court).exists():
            court.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0002_api_integrations'),
    ]

    operations = [
        # Reversing does nothing (the removed empty court records are not recreated)
        migrations.RunPython(make_single_la_court, migrations.RunPython.noop),
    ]
