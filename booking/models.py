from django.db import models

# Create your models here.
class Customer(models.Model):
    customer_id = models.AutoField(primary_key=True)
    firstname = models.CharField(max_length=100)
    lastname = models.CharField(max_length=100)
    username = models.CharField(max_length=100, unique=True)
    password = models.CharField(max_length=255)
    # Used by EmailJS to send the booking confirmation email
    email = models.EmailField(max_length=254, blank=True, default='')

    def __str__(self):
        return self.username


class Admin(models.Model):
    admin_id = models.AutoField(primary_key=True)
    firstname = models.CharField(max_length=100)
    lastname = models.CharField(max_length=100)
    username = models.CharField(max_length=100, unique=True)
    password = models.CharField(max_length=255)

    def __str__(self):
        return self.username


class Court(models.Model):
    court_id = models.AutoField(primary_key=True)
    rate_per_hour = models.DecimalField(max_digits=8, decimal_places=2, default=200.00)
    court_status = models.CharField(
        max_length=50,
        choices=[
            ('Available', 'Available'),
            ('Maintenance', 'Maintenance')
        ]
    )
    court_name = models.CharField(max_length=100, null=True, blank=True)
    court_image = models.ImageField(upload_to='courts/', null=True, blank=True)


    admin = models.ForeignKey(Admin, on_delete=models.CASCADE)

    def __str__(self):
        return f"Court {self.court_id}"



class Booking(models.Model):
    booking_id = models.AutoField(primary_key=True)

    booking_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    total_price = models.DecimalField(max_digits=10, decimal_places=2)

    booking_status = models.CharField(
        max_length=50,
        choices=[
            ('Pending', 'Pending'),
            ('Approved', 'Approved'),
            ('Completed', 'Completed'),
            ('Cancelled', 'Cancelled')
        ]
    )

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    court = models.ForeignKey(Court, on_delete=models.CASCADE)
    # ID of the event created in the admin's Google Calendar (blank = not synced yet)
    google_event_id = models.CharField(max_length=255, blank=True, default='')

    # ── QR / Confirmation ID check-in ──
    # Same code is typed by staff or read from the QR (e.g. LBC-7K3P-9Q2X).
    confirmation_code = models.CharField(max_length=14, unique=True, null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey('Admin', null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name='checked_in_bookings')
    session_ends_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Booking {self.booking_id}"

class Payment(models.Model):
    payment_id = models.AutoField(primary_key=True)

    payment_amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField(auto_now_add=True)

    payment_status = models.CharField(
        max_length=50,
        choices=[
            ('Paid', 'Paid'),
            ('Unpaid', 'Unpaid')
        ]
    )
    payment_method = models.CharField(
        max_length=50,
        choices=[
            ('Cash', 'Cash'),
            ('Online', 'Online'),
        ],
        default='Cash'
    )
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE)

    def __str__(self):
        return f"Payment {self.payment_id}"
    
class Damage(models.Model):
    damage_id = models.AutoField(primary_key=True)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE)
    description = models.TextField()
    fee = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=50, 
        choices=[('Pending','Pending'),('Settled','Settled')],
        default='Pending'
    )


class GoogleCalendarToken(models.Model):
    """Stores the admin's Google OAuth tokens so approved bookings can be
    added to their Google Calendar without logging in to Google every time."""
    admin = models.OneToOneField(Admin, on_delete=models.CASCADE)
    google_email = models.CharField(max_length=254, blank=True, default='')
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True, default='')
    token_expiry = models.DateTimeField()
    connected_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Google Calendar for {self.admin.username}"
