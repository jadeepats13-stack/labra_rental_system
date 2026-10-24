from multiprocessing import context
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import render, redirect
from .models import Customer, Admin, Court, Booking, Payment, Damage
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from decimal import Decimal
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Sum

import json
import requests

from .services.weather import get_booking_forecast
from .services.emailjs import send_booking_confirmation
from .services import google_calendar
import secrets
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


def home(request):
    return render(request, 'user/landing.html')

def register(request):
    if request.method == "POST":
        firstname = request.POST['firstname']
        lastname = request.POST['lastname']
        username = request.POST['username']
        password = request.POST['password']
        confirm_password = request.POST['confirm_password']
        email = request.POST.get('email', '').strip()

        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Please enter a valid email address")
            return redirect('register')

        if password != confirm_password:
            messages.error(request, "Password does not match")
            return redirect('register')

        if Customer.objects.filter(username=username).exists():
            messages.error(request, "Username already taken")
            return redirect('register')
        hashed_password = make_password(password)
        Customer.objects.create(
            firstname=firstname,
            lastname=lastname,
            username=username,
            password=hashed_password,
            email=email,
        )

        messages.success(request, "Registered Successfully")
        return redirect('login')

    return render(request,'user/login.html')

def customer_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        # ── 1. Check Admin table first ──────────────────────
        try:
            admin = Admin.objects.get(username=username)
            if admin.password == password:  # use check_password() if hashed
                request.session['admin_id'] = admin.admin_id
                request.session.set_expiry(86400)
                messages.success(request, f'Welcome, Admin {admin.firstname}!')
                return redirect('admin_dashboard')
            else:
                messages.error(request, "Invalid credentials.")
                return redirect('login')
        except Admin.DoesNotExist:
            pass  # not an admin, fall through to customer check

        # ── 2. Check Customer table ─────────────────────────
        try:
            user = Customer.objects.get(username=username)
        except Customer.DoesNotExist:
            messages.error(request, "Invalid credentials.")
            return redirect("login")

        if check_password(password, user.password):
            request.session['customer_id'] = user.customer_id
            request.session['username'] = user.username
            request.session['firstname'] = user.firstname
            request.session['lastname'] = user.lastname
            return redirect("customer_dashboard")
        else:
            messages.error(request, "Invalid credentials.")
            return redirect("login")

    return render(request, 'user/login.html')

def get_logged_in_customer(request):
    """Return the Customer object for the session user, or None."""
    customer_id = request.session.get('customer_id')
    if not customer_id:
        return None
    try:
        return Customer.objects.get(pk=customer_id)
    except Customer.DoesNotExist:
        return None
    


def customer_dashboard(request):
    customer_id = request.session.get('customer_id')
    if not customer_id:
        return redirect('login')

    customer = Customer.objects.get(customer_id=customer_id)

    # Single LA court (kept as a list so the existing templates still work)
    courts = Court.objects.order_by('court_id')

    # Stats
    total_bookings = Booking.objects.filter(customer=customer).count()
    active_bookings = Booking.objects.filter(
        customer=customer,
        booking_status__in=['Pending', 'Approved']
    ).count()
    unpaid_count = Booking.objects.filter(
        customer=customer,
        payment__payment_status='Unpaid'
    ).count()
    total_spent = Booking.objects.filter(
        customer=customer,
        payment__payment_status='Paid'
    ).aggregate(total=Sum('total_price'))['total'] or 0

    # Recent bookings (latest 5)
    recent_bookings = Booking.objects.filter(customer=customer).order_by('-booking_date')[:5]

    # Active bookings (for My Bookings page)
    active_booking_list = Booking.objects.filter(
        customer=customer,
        booking_status__in=['Pending', 'Approved', 'Completed']
    ).order_by('-booking_date')

    # Booking history (completed/cancelled bookings)
    booking_history = Booking.objects.filter(
        customer=customer,
        booking_status__in=['Completed', 'Cancelled']
    ).order_by('-booking_date')

    # For booking page default date
    today = timezone.localdate()

    payments = Payment.objects.filter(
    booking__customer=customer
    ).order_by('-payment_date')
    
    context = {
        'customer': customer,
        'courts': courts,
        'total_bookings': total_bookings,
        'active_bookings': active_bookings,
        'unpaid_count': unpaid_count,
        'total_spent': total_spent,
        'recent_bookings': recent_bookings,
        'active_booking_list': active_booking_list,
        'booking_history': booking_history,
        'today': today,
        'payments': payments,
    }

    return render(request, 'customer/customer_dashboard.html', context)
# Book Court
def book_court(request):
    customer = get_logged_in_customer(request)
    if not customer:
        return redirect('login')

    if request.method != 'POST':
        return redirect('customer_dashboard')

    court_id       = request.POST.get('court_id')
    booking_date   = request.POST.get('booking_date')
    start_time_str = request.POST.get('start_time')
    end_time_str   = request.POST.get('end_time')
    total_price    = request.POST.get('total_price', '0')

    # Parse times to time objects
    from datetime import time, datetime, date
    try:
        start_time = time.fromisoformat(start_time_str + ':00')
        end_time = time.fromisoformat(end_time_str + ':00')
    except ValueError:
        messages.error(request, 'Invalid time format.')
        return redirect('customer_dashboard')

    # ── Validate that booking is not in the past ──────────
    try:
        booking_date_obj = date.fromisoformat(booking_date)
    except ValueError:
        messages.error(request, 'Invalid booking date.')
        return redirect('customer_dashboard')

    now = timezone.localtime(timezone.now())
    today = now.date()
    current_time = now.time()

    if booking_date_obj < today:
        messages.error(request, 'You cannot book a date in the past.')
        return redirect('customer_dashboard')

    if booking_date_obj == today and start_time <= current_time:
        messages.error(request, f'Start time {start_time_str} has already passed. Please choose a future time.')
        return redirect('customer_dashboard')
    # ─────────────────────────────────────────────────────

    # Parse court_id
    if isinstance(court_id, str) and '-' in court_id:
        court_id = court_id.split('-', 1)[0]

    try:
        court_id = int(court_id)
    except (ValueError, TypeError):
        messages.error(request, 'Invalid court selection.')
        return redirect('customer_dashboard')

    # Convert total_price to Decimal
    try:
        total_price_decimal = Decimal(total_price)
        if total_price_decimal <= 0:
            raise ValueError
    except Exception:
        messages.error(request, 'Invalid total price. Check your time selection.')
        return redirect('customer_dashboard')

    court = get_object_or_404(Court, pk=court_id, court_status='Available')

    # Check for time conflicts
    conflict = Booking.objects.filter(
        court=court,
        booking_date=booking_date,
        booking_status__in=['Pending', 'Approved'],
    ).exclude(
        end_time__lte=start_time
    ).exclude(
        start_time__gte=end_time
    ).exists()

    if conflict:
        messages.error(request, 'That time slot is already booked. Please choose a different time.')
        return redirect('customer_dashboard')

    booking = Booking.objects.create(
        booking_date=booking_date,
        start_time=start_time,
        end_time=end_time,
        total_price=total_price_decimal,
        booking_status='Pending',
        customer=customer,
        court=court,
    )

    court_name = court.court_name or f"Court {court.court_id}"
    request.session['last_booking_court_name'] = court_name

    # EmailJS: booking confirmation email (a failure never cancels the booking)
    email_sent, email_message = send_booking_confirmation(booking)
    request.session['booking_email_status'] = {
        'booking_id': booking.booking_id, 'sent': email_sent, 'message': email_message,
    }

#    messages.success(request, '🏀 Booking confirmed! Proceed to payment.')
    return redirect('booking_confirmation', booking_id=booking.booking_id)

# ─────────────────────────── booking confirmation ─────────────────────

def booking_confirmation(request, booking_id):
    """
    Show booking confirmation page with payment options.
    Route: path('booking_confirmation/<int:booking_id>/', views.booking_confirmation, name='booking_confirmation')
    """
    customer = get_logged_in_customer(request)
    if not customer:
        return redirect('login')

    booking = get_object_or_404(Booking, pk=booking_id, customer=customer)

    # Get court name from session (set during booking)
    court_name = request.session.get('last_booking_court_name', f"Court {booking.court.court_id}")

    # Calculate duration
    from datetime import datetime, time
    start = datetime.combine(datetime.today(), booking.start_time)
    end = datetime.combine(datetime.today(), booking.end_time)
    duration = end - start
    hours = duration.seconds // 3600
    minutes = (duration.seconds % 3600) // 60
    duration_str = f"{hours}h {minutes}m" if minutes else f"{hours}h"

    context = {
        'customer': customer,
        'booking': booking,
        'court_name': court_name,
        'duration_str': duration_str,
        # OpenWeatherMap forecast for the booked date/time
        'weather': get_booking_forecast(booking.booking_date, booking.start_time),
    }

    # Show the EmailJS result once, right after booking
    email_status = request.session.get('booking_email_status')
    if email_status and email_status.get('booking_id') == booking.booking_id:
        context['email_status'] = request.session.pop('booking_email_status')

    return render(request, 'customer/customer_booking_confirmation.html', context)


# ─────────────────────────── weather forecast (OpenWeatherMap) ─────

def weather_forecast(request):
    """
    JSON forecast for the date/time the customer is choosing on the booking form.
    Route: path('weather_forecast/', views.weather_forecast, name='weather_forecast')
    """
    if not get_logged_in_customer(request):
        return JsonResponse({'available': False, 'message': 'Not logged in'}, status=401)

    from datetime import date, time
    try:
        booking_date = date.fromisoformat(request.GET.get('date', ''))
        start_time = time.fromisoformat(request.GET.get('start', '') + ':00')
    except ValueError:
        return JsonResponse({'available': False, 'message': 'Choose a date and start time.'}, status=400)

    return JsonResponse(get_booking_forecast(booking_date, start_time))


# ─────────────────────────── cancel booking ─────────────────────
 
def cancel_booking(request, booking_id):
    """
    Cancel a pending or approved booking.
    Route: path('cancel_booking/<int:booking_id>/', views.cancel_booking, name='cancel_booking')
    """
    customer = get_logged_in_customer(request)
    if not customer:
        return redirect('login')
 
    booking = get_object_or_404(Booking, pk=booking_id, customer=customer)
 
    if booking.booking_status not in ['Pending', 'Approved']:
        messages.error(request, 'This booking cannot be cancelled.')
        return redirect('customer_dashboard')
 
    booking.booking_status = 'Cancelled'
    booking.save()

    # Google Calendar: remove the admin's calendar event (customer doesn't need the details)
    google_calendar.remove_booking_event(booking)
    messages.success(request, f'Booking #{booking_id} has been cancelled.')
    return redirect('customer_dashboard')
 
 
# ─────────────────────────── process payment ────────────────────
 
def process_payment(request):
    customer = get_logged_in_customer(request)
    if not customer:
        return redirect('login')

    if request.method != 'POST':
        return redirect('customer_dashboard')

    booking_id     = request.POST.get('booking_id')
    payment_method = request.POST.get('payment_method')

    booking = get_object_or_404(Booking, pk=booking_id, customer=customer)

    if booking.booking_status == 'Cancelled':
        messages.error(request, 'Cannot pay for a cancelled booking.')
        return redirect('customer_dashboard')

    payment, created = Payment.objects.get_or_create(
        booking=booking,
        defaults={
            'payment_amount': booking.total_price,
            'payment_status': 'Paid',
            'payment_method': payment_method,
        }
    )

    if not created:
        payment.payment_amount = booking.total_price
        payment.payment_status = 'Paid'
        payment.save()

    list(messages.get_messages(request))

    messages.success(request, f'✅ Payment for Booking #{booking_id} completed via {payment_method}.')
    return redirect('customer_dashboard')
 
 
# ─────────────────────────── update profile ─────────────────────
 
def update_profile(request):
    """
    Update customer profile fields and display customer info.
    """
    customer = get_logged_in_customer(request)
    if not customer:
        return redirect('login')

    if request.method == 'POST':
        firstname        = request.POST.get('firstname', '').strip()
        lastname         = request.POST.get('lastname', '').strip()
        username         = request.POST.get('username', '').strip()
        new_password     = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not all([firstname, lastname, username]):
            messages.error(request, 'First name, last name, and username are required.')
            return redirect('update_profile')

        email = request.POST.get('email', '').strip()
        if email:
            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, 'Please enter a valid email address.')
                return redirect('customer_dashboard')

        if Customer.objects.filter(username=username).exclude(pk=customer.pk).exists():
            messages.error(request, 'That username is already taken.')
            return redirect('update_profile')

        customer.firstname = firstname
        customer.lastname  = lastname
        customer.username  = username
        customer.email     = email

        if new_password:
            if new_password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return redirect('update_profile')
            customer.password = new_password  # use make_password in production

        customer.save()
        messages.success(request, 'Profile updated successfully.')
        return redirect('customer_dashboard')

    # If GET request, render the profile form with customer info
    return render(request, 'customer/customer_dashboard.html', {'customer': customer})

 
# ─────────────────────────── logout ─────────────────────────────
 
def logout_view(request):
    """
    Clear customer session and redirect to login.
    Route: path('logout/', views.logout_view, name='logout')
    """
    request.session.flush()
    return redirect('login')

# Admin Dashboard
def admin_login(request):
    """
    Handles the Admin Login form submission from the landing page.
    Route: path('admin_login/', views.admin_login, name='admin_login')
    """
    if request.method != 'POST':
        return redirect('login')
 
    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
 
    if not username or not password:
        return redirect('/login/?admin=1')
 
    try:
        admin = Admin.objects.get(username=username)
    except Admin.DoesNotExist:
        return redirect('/login/?admin=1')
 
    # Plain-text password check (matches your existing Customer pattern)
    # In production, use make_password / check_password for hashing
    if admin.password != password:
        return redirect('/login/?admin=1')
 
    # Set admin session
    request.session['admin_id'] = admin.admin_id
    request.session.set_expiry(86400)  # 24 hours
 
    messages.success(request, f'Welcome, Admin {admin.firstname}!')
    return redirect('admin_dashboard')

def get_logged_in_admin(request):
    """Return the Admin object for the session, or None."""
    admin_id = request.session.get('admin_id')
    if not admin_id:
        return None
    try:
        return Admin.objects.get(pk=admin_id)
    except Admin.DoesNotExist:
        return None
    
def admin_logout(request):
    """
    Clears admin session and redirects to the login page.
    Route: path('admin_logout/', views.admin_logout, name='admin_logout')
    """
    request.session.flush()
    return redirect('login')
 
 
# ─── main dashboard ─────────────────────────────────────────────
 
def admin_dashboard(request):
    admin_id = request.session.get('admin_id')

    if not admin_id:
        messages.error(request, 'Please log in as admin first.')
        return redirect('login')

    try:
        admin = Admin.objects.get(admin_id=admin_id)
    except Admin.DoesNotExist:
        messages.error(request, 'Admin account not found.')
        return redirect('login')

    all_bookings = (
        Booking.objects
        .select_related('customer', 'court', 'payment')
        .order_by('-booking_date', '-start_time')
    )

    context = {
        'logged_admin': admin,
        'total_customers': Customer.objects.count(),
        'total_courts': Court.objects.count(),
        'total_bookings': all_bookings.count(),
        'total_payments': Payment.objects.count(),
        'pending_bookings': all_bookings.filter(booking_status='Pending').count(),
        'courts': Court.objects.select_related('admin').all(),
        'all_bookings': all_bookings,
        'recent_bookings': all_bookings[:6],
        'customers': Customer.objects.all().order_by('lastname', 'firstname'),
        'payments': Payment.objects.select_related('booking__customer').order_by('-payment_date'),
        'damages': Damage.objects.select_related('booking__customer').order_by('-damage_id'),
        # Google Calendar connection status for the dashboard card
        'google_configured': google_calendar.is_configured(),
        'google_connection': google_calendar.get_connection(),
    }

    # Upcoming Bookings card: the next 5 approved bookings, read from Google Calendar
    context['upcoming_events'], context['upcoming_error'] = _upcoming_from_google(context['google_connection'])

    return render(request, 'admin/admin_dashboard.html', context)

# ─── court management ────────────────────────────────────────────
def update_court(request, court_id):
    """
    Update an existing court's details.
    Route: path('update_court/<int:court_id>/', views.update_court, name='update_court')
    """
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')
 
    court = get_object_or_404(Court, pk=court_id)
 
    if request.method != 'POST':
        return redirect('admin_dashboard')
 
    court_name    = request.POST.get('court_name', '').strip()
    rate_per_hour = request.POST.get('rate_per_hour', '').strip()
    court_status  = request.POST.get('court_status', court.court_status)
    court_image   = request.FILES.get('court_image')
 
    if not court_name or not rate_per_hour:
        messages.error(request, 'Court name and rate per hour are required.')
        return redirect('admin_dashboard')
 
    try:
        rate = float(rate_per_hour)
        if rate <= 0:
            raise ValueError
    except ValueError:
        messages.error(request, 'Please enter a valid rate per hour.')
        return redirect('admin_dashboard')
 
    court.court_name   = court_name
    court.rate_per_hour = rate
    court.court_status  = court_status
    if court_image:
        court.court_image = court_image
    court.save()
 
    messages.success(request, f'Court "{court_name}" has been updated successfully.')
    return redirect('admin_dashboard')
def update_court_status(request, court_id):
    """
    Quick-toggle court status (kept for backwards compatibility).
    Route: path('update_court_status/<int:court_id>/', views.update_court_status, name='update_court_status')
    """
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')
 
    if request.method != 'POST':
        return redirect('admin_dashboard')
 
    court = get_object_or_404(Court, pk=court_id)
    new_status = request.POST.get('court_status')
 
    if new_status in ['Available', 'Maintenance']:
        court.court_status = new_status
        court.save()
        messages.success(request, f'Court #{court_id} status updated to {new_status}.')
    else:
        messages.error(request, 'Invalid court status.')
 
    return redirect('admin_dashboard')
# ─── booking management ──────────────────────────────────────────
 
def admin_approve_booking(request, booking_id):
    """
    Route: path('admin_approve_booking/<int:booking_id>/', views.admin_approve_booking, name='admin_approve_booking')
    """
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')
 
    booking = get_object_or_404(Booking, pk=booking_id)
 
    if booking.booking_status != 'Pending':
        messages.error(request, 'Only pending bookings can be approved.')
        return redirect('admin_dashboard')
 
    booking.booking_status = 'Approved'
    booking.save()

    # Google Calendar: add the approved booking to the admin's calendar
    added, calendar_message = google_calendar.add_booking_event(booking)
    messages.success(request, f'Booking #{booking_id} has been approved. {calendar_message}')
    return redirect('admin_dashboard')

def admin_complete_booking(request, booking_id):
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')

    booking = get_object_or_404(Booking, pk=booking_id)

    if booking.booking_status != 'Approved':
        messages.error(request, 'Only approved bookings can be marked as completed.')
        return redirect('admin_dashboard')

    booking.booking_status = 'Completed'
    booking.save()
    messages.success(request, f'Booking #{booking_id} marked as completed.')
    return redirect('admin_dashboard')

def admin_cancel_booking(request, booking_id):
    """
    Route: path('admin_cancel_booking/<int:booking_id>/', views.admin_cancel_booking, name='admin_cancel_booking')
    """
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')
 
    booking = get_object_or_404(Booking, pk=booking_id)
 
    if booking.booking_status not in ['Pending', 'Approved']:
        messages.error(request, 'This booking cannot be cancelled.')
        return redirect('admin_dashboard')
 
    booking.booking_status = 'Cancelled'
    booking.save()

    # Google Calendar: remove the event if this booking had been approved
    removed, calendar_message = google_calendar.remove_booking_event(booking)
    messages.success(request, f'Booking #{booking_id} has been cancelled. {calendar_message}'.strip())
    return redirect('admin_dashboard')
 
 
# ─── damage management ───────────────────────────────────────────
 
def add_damage(request, booking_id):
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')

    if request.method != 'POST':
        return redirect('admin_dashboard')

    booking = get_object_or_404(Booking, pk=booking_id)
    description = request.POST.get('description', '').strip()
    fee = request.POST.get('fee', '0')

    if not description:
        messages.error(request, 'Description is required.')
        return redirect('admin_dashboard')

    try:
        fee = Decimal(fee)
        if fee <= 0:
            raise ValueError
    except Exception:
        messages.error(request, 'Enter a valid fee.')
        return redirect('admin_dashboard')

    Damage.objects.create(
        booking=booking,
        description=description,
        fee=fee,
        status='Pending'
    )

    messages.success(request, f'Damage report filed for Booking #{booking_id}.')
    return redirect('admin_dashboard')

def no_damage(request, booking_id):
    """
    Mark a completed booking as having no damage.
    Route: path('no_damage/<int:booking_id>/', views.no_damage, name='no_damage')
    """
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')

    booking = get_object_or_404(Booking, pk=booking_id)

    if booking.booking_status != 'Completed':
        messages.error(request, 'Only completed bookings can be marked.')
        return redirect('admin_dashboard')

    Damage.objects.get_or_create(
        booking=booking,
        defaults={
            'description': 'No damage reported.',
            'fee': 0.00,
            'status': 'Settled'
        }
    )

    messages.success(request, f'Booking #{booking_id} marked as no damage.')
    return redirect('admin_dashboard')

def settle_damage(request, damage_id):
    admin = get_logged_in_admin(request) 
    if not admin:
        return redirect('login')

    damage = get_object_or_404(Damage, pk=damage_id)

    if damage.status != 'Pending':
        messages.error(request, 'This damage report is already settled.')
        return redirect('admin_dashboard')

    damage.status = 'Settled'
    damage.save()
    messages.success(request, f'Damage #{damage_id} marked as settled.')
    return redirect('admin_dashboard')

def admin_customer_history(request, customer_id):
    admin = get_logged_in_admin(request)
    if not admin:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    customer = get_object_or_404(Customer, pk=customer_id)
    bookings = Booking.objects.filter(customer=customer).order_by('-booking_date')

    data = []
    for b in bookings:
        # get liabilities
        damages = b.damage_set.all()
        if damages:
            d = damages.first()
            liabilities = 'No Damage' if d.fee == 0 else f'₱{d.fee} ({d.status})'
        else:
            liabilities = '—'

        data.append({
            'booking_id': b.booking_id,
            'court_id': b.court.court_id,
            'booking_date': str(b.booking_date),
            'start_time': b.start_time.strftime('%H:%M'),
            'end_time': b.end_time.strftime('%H:%M'),
            'total_price': str(b.total_price),
            'payment_status': b.payment.payment_status if hasattr(b, 'payment') and b.payment else 'Unpaid',
            'booking_status': b.booking_status,
            'liabilities': liabilities,
        })

    return JsonResponse({'bookings': data})

def admin_update_profile(request):
    admin_id = request.session.get('admin_id')
    if not admin_id:
        return redirect('login')

    admin = get_object_or_404(Admin, pk=admin_id)

    if request.method == 'POST':
        firstname        = request.POST.get('firstname', '').strip()
        lastname         = request.POST.get('lastname', '').strip()
        username         = request.POST.get('username', '').strip()
        new_password     = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if Admin.objects.filter(username=username).exclude(pk=admin_id).exists():
            messages.error(request, 'Username already taken.')
            return redirect('admin_dashboard')

        admin.firstname = firstname
        admin.lastname  = lastname
        admin.username  = username

        if new_password:
            if new_password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return redirect('admin_dashboard')
            admin.password = new_password

        admin.save()
        messages.success(request, 'Profile updated successfully.')

    return redirect('admin_dashboard')

def get_paypal_access_token():
    """Get PayPal access token using client credentials."""
    url = 'https://api-m.sandbox.paypal.com/v1/oauth2/token'
    response = requests.post(
        url,
        headers={'Accept': 'application/json'},
        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_SECRET),
        data={'grant_type': 'client_credentials'}
    )
    return response.json().get('access_token')


def create_paypal_order(request):
    
    """Create a PayPal order and return the order ID."""
    customer = get_logged_in_customer(request)
    if not customer:
        return JsonResponse({'error': 'Not logged in'}, status=401)

    data = json.loads(request.body)
    booking_id = data.get('booking_id')
    booking = get_object_or_404(Booking, pk=booking_id, customer=customer)

    access_token = get_paypal_access_token()

    url = 'https://api-m.sandbox.paypal.com/v2/checkout/orders'
    payload = {
        'intent': 'CAPTURE',
        'purchase_units': [{
            'amount': {
                'currency_code': 'PHP',
                'value': str(booking.total_price)
            },
            'description': f'Court Booking #{booking_id} – Tambacan Basketball Court'
        }]
    }

    response = requests.post(
        url,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        },
        json=payload
    )

    return JsonResponse(response.json())


@csrf_exempt
def capture_paypal_order(request):
    customer = get_logged_in_customer(request)
    if not customer:
        return JsonResponse({'error': 'Not logged in'}, status=401)

    data = json.loads(request.body)
    order_id   = data.get('order_id')
    booking_id = int(data.get('booking_id'))

    access_token = get_paypal_access_token()

    url = f'https://api-m.sandbox.paypal.com/v2/checkout/orders/{order_id}/capture'
    response = requests.post(
        url,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
    )

    result = response.json()

    if result.get('status') == 'COMPLETED':
        booking = get_object_or_404(Booking, pk=booking_id, customer=customer)
        payment, created = Payment.objects.get_or_create(
            booking=booking,
            defaults={
                'payment_amount': booking.total_price,
                'payment_status': 'Paid',
                'payment_method': 'Online',
            }
        )
        
        if not created:
            payment.payment_amount = booking.total_price
            payment.payment_status = 'Paid'
            payment.payment_method = 'Online'
            payment.save()

        list(messages.get_messages(request))
        messages.success(request, f'Payment for Booking #{booking_id} completed via PayPal.')
        return JsonResponse({'status': 'COMPLETED'})

    return JsonResponse({'status': 'FAILED', 'details': result}, status=400)


# ─── Google Calendar (admin connects once via OAuth) ─────────────

def _admin_profile_url():
    """Admin Edit Profile page (where the Google Calendar settings live)."""
    from django.urls import reverse
    return reverse('admin_dashboard') + '#profile'


def google_connect(request):
    """Send the admin to Google's sign-in page."""
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')
    if not google_calendar.is_configured():
        messages.error(request, 'Google Calendar is not set up. Add the Google keys to the .env file.')
        return redirect(_admin_profile_url())

    state = secrets.token_urlsafe(24)
    request.session['google_oauth_state'] = state
    return redirect(google_calendar.build_auth_url(state))


def google_oauth_callback(request):
    """Google sends the admin back here after they allow access."""
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')

    expected_state = request.session.pop('google_oauth_state', None)
    if not expected_state or request.GET.get('state') != expected_state:
        messages.error(request, 'Google Calendar connection failed (invalid session). Please try again.')
        return redirect(_admin_profile_url())
    if request.GET.get('error'):
        messages.error(request, 'Google Calendar connection was cancelled.')
        return redirect(_admin_profile_url())

    try:
        google_calendar.exchange_code_and_save(admin, request.GET.get('code', ''))
    except google_calendar.CalendarError as exc:
        messages.error(request, str(exc))
        return redirect(_admin_profile_url())
    except Exception:
        messages.error(request, 'Could not reach Google. Please try connecting again.')
        return redirect(_admin_profile_url())

    messages.success(request, 'Google Calendar connected. Approved bookings will now appear in your calendar.')
    return redirect(_admin_profile_url())


def google_disconnect(request):
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')
    if request.method != 'POST':
        return redirect(_admin_profile_url())

    connection = google_calendar.get_connection()
    if connection:
        google_calendar.disconnect(connection)
    messages.success(request, 'Google Calendar disconnected.')
    return redirect(_admin_profile_url())


# ─── Court Schedule (admin) ───────────────────────────────────────

def _booking_details(b):
    """Booking facts shown in the schedule popup and the Upcoming card."""
    try:
        payment = b.payment
    except Payment.DoesNotExist:
        payment = None
    return {
        'booking_id': b.booking_id,
        'customer': f'{b.customer.firstname} {b.customer.lastname}'.strip(),
        'date': b.booking_date.strftime('%b %d, %Y'),
        'time': f"{b.start_time.strftime('%I:%M %p').lstrip('0')} – {b.end_time.strftime('%I:%M %p').lstrip('0')}",
        'total': f'{b.total_price:,.2f}',
        'payment_status': payment.payment_status if payment else 'Unpaid',
        'booking_status': b.booking_status,
    }


def _upcoming_from_google(connection, limit=5):
    """(list of upcoming bookings, error message) for the dashboard card."""
    if not connection:
        return [], ''
    try:
        events = google_calendar.upcoming_booking_events(limit=limit)
    except google_calendar.CalendarError as exc:
        return [], str(exc)
    except Exception:
        return [], 'Google Calendar could not be reached.'

    ids = [e['booking_id'] for e in events if e['booking_id']]
    bookings = {b.booking_id: b for b in Booking.objects.filter(pk__in=ids).select_related('customer')}
    upcoming = []
    for e in events:
        local_start = timezone.localtime(e['start'])
        local_end = timezone.localtime(e['end'])
        b = bookings.get(e['booking_id'])
        upcoming.append({
            'booking_id': e['booking_id'],
            'customer': f'{b.customer.firstname} {b.customer.lastname}' if b else e['summary'],
            'date': local_start.strftime('%a, %b %d'),
            'time': f"{local_start.strftime('%I:%M %p').lstrip('0')} – {local_end.strftime('%I:%M %p').lstrip('0')}",
            'total': f'{b.total_price:,.2f}' if b else '',
        })
    return upcoming, ''


def _parse_range(request):
    """FullCalendar sends ?start=...&end=... as ISO date-times."""
    from django.utils.dateparse import parse_datetime, parse_date
    from datetime import datetime as dt, timedelta as td

    def parse(value):
        value = (value or '').replace(' ', '+')   # '+' in a URL may arrive as a space
        parsed = parse_datetime(value)
        if parsed is None:
            d = parse_date(value[:10]) if value else None
            parsed = dt.combine(d, dt.min.time()) if d else None
        if parsed is not None and timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed

    start, end = parse(request.GET.get('start')), parse(request.GET.get('end'))
    if not start or not end or end <= start or (end - start) > td(days=62):
        return None, None
    return start, end


def admin_schedule_events(request):
    """
    JSON events for the admin Court Schedule calendar.
    Route: path('admin_schedule_events/', views.admin_schedule_events, name='admin_schedule_events')

    - Approved bookings: read live from Google Calendar (external API).
    - Pending bookings: from our database (they are not in Google yet).
    - If Google is unavailable, approved bookings come from the database instead.
    """
    if not get_logged_in_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    start, end = _parse_range(request)
    if not start:
        return JsonResponse({'error': 'Invalid date range'}, status=400)

    in_range = (Booking.objects
                .filter(booking_date__gte=timezone.localtime(start).date(),
                        booking_date__lte=timezone.localtime(end).date())
                .select_related('customer', 'payment'))
    events = []

    def db_event(b, source, color, title_prefix=''):
        details = _booking_details(b)
        details['source'] = source
        return {
            'id': f'{source}-{b.booking_id}',
            'title': f"{title_prefix}#{b.booking_id} {details['customer']}",
            'start': f'{b.booking_date.isoformat()}T{b.start_time.strftime("%H:%M:%S")}',
            'end': f'{b.booking_date.isoformat()}T{b.end_time.strftime("%H:%M:%S")}',
            'color': color,
            'extendedProps': details,
        }

    # Pending bookings always come from the database
    for b in in_range.filter(booking_status='Pending'):
        events.append(db_event(b, 'pending', '#ca8a04', 'Pending · '))

    connection = google_calendar.get_connection()
    google = {'status': 'ok', 'message': ''}
    approved = in_range.filter(booking_status='Approved')

    if not connection:
        google = {'status': 'not_connected',
                  'message': 'Google Calendar is not connected. Approved bookings are shown from the database.'}
    else:
        try:
            g_events = google_calendar.list_booking_events(start, end)
        except google_calendar.CalendarError as exc:
            google = {'status': 'error',
                      'message': f'{exc} Approved bookings are shown from the database instead.'}
        except Exception:
            google = {'status': 'error',
                      'message': 'Google Calendar could not be reached. Approved bookings are shown from the database instead.'}
        else:
            ids = [e['booking_id'] for e in g_events if e['booking_id']]
            bookings = {b.booking_id: b for b in
                        Booking.objects.filter(pk__in=ids).select_related('customer', 'payment')}
            for e in g_events:
                b = bookings.get(e['booking_id'])
                details = _booking_details(b) if b else {
                    'booking_id': e['booking_id'], 'customer': e['summary'], 'date': '', 'time': '',
                    'total': '', 'payment_status': '', 'booking_status': 'Not found in system'}
                details['source'] = 'google'
                events.append({
                    'id': f"google-{e['event_id']}",
                    'title': f"#{e['booking_id']} {details['customer']}" if b else e['summary'],
                    'start': timezone.localtime(e['start']).strftime('%Y-%m-%dT%H:%M:%S'),
                    'end': timezone.localtime(e['end']).strftime('%Y-%m-%dT%H:%M:%S'),
                    'color': '#16a34a',
                    'extendedProps': details,
                })
            # Approved bookings that are missing from Google (approved before connecting)
            approved = approved.exclude(pk__in=ids)

    not_synced_color = '#64748b'
    for b in approved:
        source = 'database' if google['status'] != 'ok' else 'not_synced'
        events.append(db_event(b, source, not_synced_color))

    return JsonResponse({'events': events, 'google': google})

