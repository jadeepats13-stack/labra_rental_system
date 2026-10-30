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
from django.db import models

import json
import requests

from .services.weather import get_booking_forecast, get_daily_forecast
from . import availability
from .services.emailjs import send_booking_confirmation
from .services import google_calendar
from .services.qr_code import qr_image_url
from . import checkin
from . import chatbot
from . import email_codes
from .models import EmailCode
import secrets
from django.core.validators import validate_email
from django.core.exceptions import ValidationError


def _landing(request, auth_tab=''):
    """
    Landing page. The Log in / Sign up pop-up lives here; /login/ and
    /register/ show the same page with the pop-up already open.
    """
    now = timezone.localtime()
    court = Court.objects.order_by('court_id').first()
    today_weather = get_daily_forecast().get(now.date().isoformat())   # cached OpenWeatherMap data
    context = {
        'court': court,
        'free_today': availability.free_hours(now.date(), now=now) if court else 0,
        'open_hours_per_day': availability.OPEN_HOURS_PER_DAY,
        'today_weather': today_weather,
        'auth_tab': auth_tab,
        # Email confirmation / password reset steps of the pop-up
        'verify_email_masked': _pending_verify_email(request),
        'reset_email_masked': email_codes.mask_email(request.session.get('reset_email', '')),
        'resend_wait': _resend_wait(request, auth_tab),
        # values typed before an error, so the user doesn't retype them (never passwords)
        'auth_form': request.session.pop('auth_form', {}),
        'logged_in_customer': bool(request.session.get('customer_id')),
        'logged_in_admin': bool(request.session.get('admin_id')),
    }
    return render(request, 'user/landing.html', context)


def chatbot_message(request):
    """
    Landing page chatbot. POST JSON {intent} for a quick button, or
    {message, history} for a typed question (answered by Google Gemini,
    with built-in answers as the fallback).
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    data = _json_body(request)
    result = chatbot.reply(request, message=str(data.get('message', '')),
                           intent=str(data.get('intent', '')), history=data.get('history'))
    return JsonResponse(result)


def home(request):
    return _landing(request)


def _auth_error(request, tab, message, form):
    messages.error(request, message)
    request.session['auth_form'] = form
    return redirect('register' if tab == 'register' else 'login')


def register(request):
    if request.method != "POST":
        return _landing(request, 'register')

    firstname = request.POST.get('firstname', '').strip()
    lastname = request.POST.get('lastname', '').strip()
    username = request.POST.get('username', '').strip()
    email = request.POST.get('email', '').strip()
    password = request.POST.get('password', '')
    confirm_password = request.POST.get('confirm_password', '')
    form = {'firstname': firstname, 'lastname': lastname, 'username': username, 'email': email}

    if not all([firstname, lastname, username, email, password]):
        return _auth_error(request, 'register', 'Please fill in all fields.', form)
    try:
        validate_email(email)
    except ValidationError:
        return _auth_error(request, 'register', 'Please enter a valid email address, e.g. name@gmail.com.', form)
    if '@' in username:
        return _auth_error(request, 'register', 'Usernames cannot contain "@". Use letters, numbers or underscores.', form)
    if password != confirm_password:
        return _auth_error(request, 'register', 'Passwords do not match.', form)
    if Customer.objects.filter(username__iexact=username).exists() or Admin.objects.filter(username__iexact=username).exists():
        return _auth_error(request, 'register', 'That username is already taken.', form)
    if Customer.objects.filter(email__iexact=email).exists():
        return _auth_error(request, 'register', 'That email is already registered. Log in instead.', form)

    customer = Customer.objects.create(
        firstname=firstname,
        lastname=lastname,
        username=username,
        password=make_password(password),
        email=email,
        email_verified=False,           # confirmed with the emailed code before the first login
    )
    return _start_email_verification(request, customer)


def customer_login(request):
    """
    One box accepts a username or an email address.
    Email login is for customers (admin accounts have no email).
    """
    if request.method != "POST":
        return _landing(request, 'login')

    identifier = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    form = {'identifier': identifier}

    if not identifier or not password:
        return _auth_error(request, 'login', 'Enter your username or email and your password.', form)

    if '@' in identifier:
        # ── Email login (customers) ─────────────────────────
        try:
            validate_email(identifier)
        except ValidationError:
            return _auth_error(request, 'login', 'That email address is not valid. Check it and try again.', form)
        matches = list(Customer.objects.filter(email__iexact=identifier)[:2])
        if len(matches) > 1:
            return _auth_error(request, 'login',
                               'This email is used by more than one account. Log in with your username instead.', form)
        user = matches[0] if matches else None
        if not user or not check_password(password, user.password):
            return _auth_error(request, 'login', 'Incorrect email or password.', form)
    else:
        # ── 1. Check Admin table first ──────────────────────
        try:
            admin = Admin.objects.get(username=identifier)
            if admin.password == password:  # use check_password() if hashed
                request.session['admin_id'] = admin.admin_id
                request.session.set_expiry(86400)
                messages.success(request, f'Welcome back, Admin {admin.firstname}!')
                return redirect('admin_dashboard')
            return _auth_error(request, 'login', 'Incorrect username or password.', form)
        except Admin.DoesNotExist:
            pass  # not an admin, fall through to customer check

        # ── 2. Check Customer table ─────────────────────────
        user = Customer.objects.filter(username=identifier).first()
        if not user or not check_password(password, user.password):
            return _auth_error(request, 'login', 'Incorrect username or password.', form)

    if not user.email_verified:
        # Correct password, but the email isn't confirmed yet: send a code first
        return _start_email_verification(request, user, from_login=True)

    _log_in_customer(request, user)
    return redirect("customer_dashboard")


def _log_in_customer(request, user):
    request.session['customer_id'] = user.customer_id
    request.session['username'] = user.username
    request.session['firstname'] = user.firstname
    request.session['lastname'] = user.lastname


# ─── Email confirmation (6-digit code after sign-up) ───────────────

def _pending_verify_customer(request):
    customer_id = request.session.get('verify_customer_id')
    return Customer.objects.filter(customer_id=customer_id).first() if customer_id else None


def _pending_verify_email(request):
    customer = _pending_verify_customer(request)
    return email_codes.mask_email(customer.email) if customer else ''


def _start_email_verification(request, customer, from_login=False):
    """Send a confirmation code and open the "Enter the code" step of the pop-up."""
    request.session['verify_customer_id'] = customer.customer_id
    wait = email_codes.seconds_until_resend(customer, EmailCode.VERIFY)
    if wait and from_login:
        # A code was sent less than a minute ago: let them use it
        messages.info(request, 'Please confirm your email first. Enter the code we just sent you.')
    else:
        sent, message = email_codes.send_code(customer, EmailCode.VERIFY)
        if sent:
            intro = 'Please confirm your email first. ' if from_login else 'Account created. '
            messages.success(request, intro + message)
        else:
            messages.error(request, message)
    return redirect('verify_email')


def verify_email(request):
    customer = _pending_verify_customer(request)
    if not customer:
        return redirect('login')
    if customer.email_verified:
        request.session.pop('verify_customer_id', None)
        messages.success(request, 'Your email is already confirmed. You can log in.')
        return redirect('login')
    if request.method != 'POST':
        return _landing(request, 'verify')

    ok, message = email_codes.check_code(customer, EmailCode.VERIFY, request.POST.get('code', ''))
    if not ok:
        messages.error(request, message)
        return redirect('verify_email')
    customer.email_verified = True
    customer.save(update_fields=['email_verified'])
    request.session.pop('verify_customer_id', None)
    _log_in_customer(request, customer)
    messages.success(request, f'Email confirmed. Welcome, {customer.firstname}!')
    return redirect('customer_dashboard')


def verify_email_resend(request):
    customer = _pending_verify_customer(request)
    if not customer:
        return redirect('login')
    if request.method == 'POST':
        sent, message = email_codes.send_code(customer, EmailCode.VERIFY)
        (messages.success if sent else messages.error)(request, message)
    return redirect('verify_email')


# ─── Forgot password (6-digit code, then a new password) ───────────

def _reset_customer(request):
    email = request.session.get('reset_email', '')
    return Customer.objects.filter(email__iexact=email).order_by('customer_id').first() if email else None


def forgot_password(request):
    if request.method != 'POST':
        return _landing(request, 'forgot')
    email = request.POST.get('email', '').strip()
    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, 'Please enter a valid email address.')
        request.session['auth_form'] = {'reset_email': email}
        return redirect('forgot_password')

    request.session['reset_email'] = email
    customer = _reset_customer(request)
    if customer:
        sent, message = email_codes.send_code(customer, EmailCode.RESET)
        if not sent:
            messages.error(request, message)
            return redirect('reset_password')
    # Same message whether or not the account exists (so nobody can check who has one)
    messages.success(request, f'If an account uses {email_codes.mask_email(email)}, we sent it a 6-digit code.')
    return redirect('reset_password')


def forgot_password_resend(request):
    if not request.session.get('reset_email'):
        return redirect('forgot_password')
    if request.method == 'POST':
        customer = _reset_customer(request)
        if customer:
            sent, message = email_codes.send_code(customer, EmailCode.RESET)
            if not sent:
                messages.error(request, message)
                return redirect('reset_password')
        messages.success(request, 'If the account exists, a new code is on its way.')
    return redirect('reset_password')


def reset_password(request):
    email = request.session.get('reset_email', '')
    if not email:
        return redirect('forgot_password')
    if request.method != 'POST':
        return _landing(request, 'reset')

    password = request.POST.get('password', '')
    confirm = request.POST.get('confirm_password', '')
    if not password:
        messages.error(request, 'Enter a new password.')
        return redirect('reset_password')
    if password != confirm:
        messages.error(request, 'Passwords do not match.')
        return redirect('reset_password')

    customer = _reset_customer(request)
    if not customer:
        messages.error(request, 'That code is not correct.')
        return redirect('reset_password')
    ok, message = email_codes.check_code(customer, EmailCode.RESET, request.POST.get('code', ''))
    if not ok:
        messages.error(request, message)
        return redirect('reset_password')

    customer.password = make_password(password)
    customer.email_verified = True        # they proved they own this email
    customer.save(update_fields=['password', 'email_verified'])
    request.session.pop('reset_email', None)
    request.session.pop('verify_customer_id', None)
    request.session['auth_form'] = {'identifier': customer.username}
    messages.success(request, 'Password changed. Log in with your new password.')
    return redirect('login')

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

    customer = Customer.objects.filter(customer_id=customer_id).first()
    if not customer:
        # The account was deleted (e.g. records were reset) while still logged in
        request.session.flush()
        messages.error(request, 'Your session has ended. Please log in again.')
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
    # Active bookings that are not paid yet (also counts bookings with no payment record)
    unpaid_count = (Booking.objects
                    .filter(customer=customer, booking_status__in=['Pending', 'Approved'])
                    .exclude(payment__payment_status='Paid')
                    .count())
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
    
    # ── Customer dashboard cards (Next Game, This Week, LA Court, reminders) ──
    now = timezone.localtime()
    daily_weather = get_daily_forecast()          # cached OpenWeatherMap data
    la_court = courts.first()

    game = availability.next_game(customer, now)
    next_game_info = None
    if game:
        try:
            game_paid = game.payment.payment_status == 'Paid'
        except Payment.DoesNotExist:
            game_paid = False
        next_game_info = {
            'booking': game,
            'countdown': availability.countdown_text(game, now),
            'weather': get_booking_forecast(game.booking_date, game.start_time),
            'paid': game_paid,
            # Check-in QR / Confirmation ID (only once approved)
            'code': game.confirmation_code or '',
            'qr_url': qr_image_url(game.confirmation_code) if game.confirmation_code else '',
            'in_session': bool(game.checked_in_at and game.session_ends_at and game.session_ends_at > timezone.now()),
            'ends_at': game.session_ends_at.isoformat() if game.session_ends_at else '',
        }

    week = availability.week_overview(now.date(), days=7, now=now)
    for day in week:
        day['weather'] = daily_weather.get(day['date'].isoformat())
        day['iso'] = day['date'].isoformat()

    unpaid_active = unpaid_count

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
        # New dashboard cards
        'next_game': next_game_info,
        'week_overview': week,
        'la_court': la_court,
        'court_free_today': availability.free_hours(now.date(), now=now) if la_court else 0,
        'open_hours_per_day': availability.OPEN_HOURS_PER_DAY,
        'unpaid_active': unpaid_active,
        # Sidebar badges
        # "id:status:paid" for each upcoming booking. The page hides the badge for
        # items already seen, so it reappears only when something new or changed.
        'badge_upcoming_items': [
            f"{b.booking_id}:{b.booking_status}:{'paid' if b.payment_status == 'Paid' else 'unpaid'}"
            for b in Booking.objects.filter(customer=customer, booking_status__in=['Pending', 'Approved'],
                                            booking_date__gte=now.date())
                                    .annotate(payment_status=models.F('payment__payment_status'))
        ],
        'missing_email': not customer.email,
    }

    return render(request, 'customer/customer_dashboard.html', context)
# Book Court
def book_court(request):
    customer = get_logged_in_customer(request)
    if not customer:
        return redirect('login')

    if request.method != 'POST':
        return _customer_page(request, 'book')

    court_id       = request.POST.get('court_id')
    booking_date   = request.POST.get('booking_date')
    start_time_str = request.POST.get('start_time')
    end_time_str   = request.POST.get('end_time')
    # total_price    = request.POST.get('total_price', '0')

    # Parse times to time objects
    from datetime import time, datetime, date
    try:
        start_time = time.fromisoformat(start_time_str + ':00')
        end_time = time.fromisoformat(end_time_str + ':00')
    except ValueError:
        messages.error(request, 'Invalid time format.')
        return _customer_page(request, 'book')

    if end_time <= start_time:
        messages.error(request, 'End time must be after the start time.')
        return _customer_page(request, 'book')
    if start_time < time(availability.OPEN_HOUR) or end_time > time(availability.CLOSE_HOUR):
        messages.error(request, 'The court is open from 8:00 AM to 10:00 PM.')
        return _customer_page(request, 'book')
    if start_time.minute % availability.SLOT_MINUTES or end_time.minute % availability.SLOT_MINUTES:
        messages.error(request, 'Please choose times on the hour or half hour.')
        return _customer_page(request, 'book')

    # ── Validate that booking is not in the past ──────────
    try:
        booking_date_obj = date.fromisoformat(booking_date)
    except ValueError:
        messages.error(request, 'Invalid booking date.')
        return _customer_page(request, 'book')

    now = timezone.localtime(timezone.now())
    today = now.date()
    current_time = now.time()

    if booking_date_obj < today:
        messages.error(request, 'You cannot book a date in the past.')
        return _customer_page(request, 'book')

    if booking_date_obj == today and start_time <= current_time:
        messages.error(request, f'Start time {start_time_str} has already passed. Please choose a future time.')
        return _customer_page(request, 'book')
    # ─────────────────────────────────────────────────────

    # Parse court_id
    if isinstance(court_id, str) and '-' in court_id:
        court_id = court_id.split('-', 1)[0]

    try:
        court_id = int(court_id)
    except (ValueError, TypeError):
        messages.error(request, 'Invalid court selection.')
        return _customer_page(request, 'book')

    # Convert total_price to Decimal
    court = get_object_or_404(Court, pk=court_id, court_status='Available')

    # Price = court rate x booked hours, calculated on the server so it can't be changed in the browser
    minutes = (end_time.hour * 60 + end_time.minute) - (start_time.hour * 60 + start_time.minute)
    total_price_decimal = (court.rate_per_hour * Decimal(minutes) / Decimal(60)).quantize(Decimal('0.01'))

    # Check for time conflicts
    # (a booking whose playing time already ended no longer holds its slot)
    conflict = availability.holding_slots(Booking.objects.filter(
        court=court,
        booking_date=booking_date,
        booking_status__in=['Pending', 'Approved'],
    )).exclude(
        end_time__lte=start_time
    ).exclude(
        start_time__gte=end_time
    ).exists()

    if conflict:
        messages.error(request, 'That time slot is already booked. Please choose a different time.')
        return _customer_page(request, 'book')

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

    # Check-in: unique Confirmation ID now, so the QR can go out in the booking email.
    # (Staff can only start playing time once the booking is approved.)
    checkin.ensure_code(booking)

    # EmailJS: booking confirmation email with the QR code (a failure never cancels the booking)
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
        return _customer_page(request, 'bookings')

    if booking.checked_in_at:
        messages.error(request, 'This booking is already checked in and cannot be cancelled.')
        return _customer_page(request, 'bookings')
 
    booking.booking_status = 'Cancelled'
    booking.save()

    # Google Calendar: remove the admin's calendar event (customer doesn't need the details)
    google_calendar.remove_booking_event(booking)
    messages.success(request, f'Booking #{booking_id} has been cancelled.')
    return _customer_page(request, 'bookings')
 
 
# ─────────────────────────── process payment ────────────────────
 
def process_payment(request):
    customer = get_logged_in_customer(request)
    if not customer:
        return redirect('login')

    if request.method != 'POST':
        return _customer_page(request, 'payment')

    booking_id     = request.POST.get('booking_id')
    payment_method = request.POST.get('payment_method')

    booking = get_object_or_404(Booking, pk=booking_id, customer=customer)

    if booking.booking_status == 'Cancelled':
        messages.error(request, 'Cannot pay for a cancelled booking.')
        return _customer_page(request, 'payment')

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
    return _customer_page(request, 'payment')
 
 
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
            return _customer_page(request, 'profile')

        email = request.POST.get('email', '').strip()
        if email:
            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, 'Please enter a valid email address.')
                return _customer_page(request, 'profile')
            if Customer.objects.filter(email__iexact=email).exclude(pk=customer.pk).exists():
                messages.error(request, 'That email is already used by another account.')
                return _customer_page(request, 'profile')

        if Customer.objects.filter(username=username).exclude(pk=customer.pk).exists():
            messages.error(request, 'That username is already taken.')
            return _customer_page(request, 'profile')

        customer.firstname = firstname
        customer.lastname  = lastname
        customer.username  = username
        customer.email     = email

        if new_password:
            if new_password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return _customer_page(request, 'profile')
            customer.password = make_password(new_password)  # stored hashed, like at sign-up

        customer.save()
        messages.success(request, 'Profile updated successfully.')
        return _customer_page(request, 'profile')

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
 
    messages.success(request, f'Welcome back, {admin.firstname}!')
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
 
 
CUSTOMER_PAGES = ('dashboard', 'book', 'bookings', 'history', 'payment', 'profile')


def _customer_page(request, default='dashboard'):
    """Back to the customer page the form was sent from (e.g. #bookings), not the Dashboard."""
    from django.urls import reverse
    page = request.POST.get('return_to', '')
    if page not in CUSTOMER_PAGES:
        page = default
    return redirect(reverse('customer_dashboard') + '#' + page)


def _admin_page(page):
    """Back to the admin page the action came from (e.g. #bookings), not the Dashboard."""
    from django.urls import reverse
    return redirect(reverse('admin_dashboard') + '#' + page)


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
        # Sidebar badges
        'badge_damages': Damage.objects.filter(status='Pending').count(),
        'badge_playing': checkin.active_sessions().count(),
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
        return _admin_page('courts')
 
    court_name    = request.POST.get('court_name', '').strip()
    rate_per_hour = request.POST.get('rate_per_hour', '').strip()
    court_status  = request.POST.get('court_status', court.court_status)
    court_image   = request.FILES.get('court_image')
 
    if not court_name or not rate_per_hour:
        messages.error(request, 'Court name and rate per hour are required.')
        return _admin_page('courts')
 
    try:
        rate = float(rate_per_hour)
        if rate <= 0:
            raise ValueError
    except ValueError:
        messages.error(request, 'Please enter a valid rate per hour.')
        return _admin_page('courts')
 
    court.court_name   = court_name
    court.rate_per_hour = rate
    court.court_status  = court_status
    if court_image:
        court.court_image = court_image
    court.save()
 
    messages.success(request, f'Court "{court_name}" has been updated successfully.')
    return _admin_page('courts')
def update_court_status(request, court_id):
    """
    Quick-toggle court status (kept for backwards compatibility).
    Route: path('update_court_status/<int:court_id>/', views.update_court_status, name='update_court_status')
    """
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')
 
    if request.method != 'POST':
        return _admin_page('courts')
 
    court = get_object_or_404(Court, pk=court_id)
    new_status = request.POST.get('court_status')
 
    if new_status in ['Available', 'Maintenance']:
        court.court_status = new_status
        court.save()
        messages.success(request, f'Court #{court_id} status updated to {new_status}.')
    else:
        messages.error(request, 'Invalid court status.')
 
    return _admin_page('courts')
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
        return _admin_page('bookings')
 
    booking.booking_status = 'Approved'
    booking.save()

    # Google Calendar: add the approved booking to the admin's calendar
    added, calendar_message = google_calendar.add_booking_event(booking)

    # Check-in: bookings made before this feature get their Confirmation ID here
    code = checkin.ensure_code(booking)

    messages.success(request, f'Booking #{booking_id} has been approved ({code}). {calendar_message}')
    return _admin_page('bookings')

def admin_complete_booking(request, booking_id):
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')

    booking = get_object_or_404(Booking, pk=booking_id)

    if request.method != 'POST':
        return _admin_page('bookings')

    # Only after the playing time has ended (never while the countdown runs)
    ok, message = checkin.complete_booking(booking)
    (messages.success if ok else messages.error)(request, message)
    return _admin_page('bookings')

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
        return _admin_page('bookings')

    if booking.checked_in_at:
        messages.error(request, f'Booking #{booking_id} is already checked in, so it cannot be cancelled.')
        return _admin_page('bookings')
 
    booking.booking_status = 'Cancelled'
    booking.save()

    # Google Calendar: remove the event if this booking had been approved
    removed, calendar_message = google_calendar.remove_booking_event(booking)
    messages.success(request, f'Booking #{booking_id} has been cancelled. {calendar_message}'.strip())
    return _admin_page('bookings')
 
 
# ─── damage management ───────────────────────────────────────────
 
def add_damage(request, booking_id):
    admin = get_logged_in_admin(request)
    if not admin:
        return redirect('login')

    if request.method != 'POST':
        return _admin_page('bookings')

    booking = get_object_or_404(Booking, pk=booking_id)
    description = request.POST.get('description', '').strip()
    fee = request.POST.get('fee', '0')

    if not description:
        messages.error(request, 'Description is required.')
        return _admin_page('bookings')

    try:
        fee = Decimal(fee)
        if fee <= 0:
            raise ValueError
    except Exception:
        messages.error(request, 'Enter a valid fee.')
        return _admin_page('bookings')

    Damage.objects.create(
        booking=booking,
        description=description,
        fee=fee,
        status='Pending'
    )

    messages.success(request, f'Damage report filed for Booking #{booking_id}.')
    return _admin_page('bookings')

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
        return _admin_page('bookings')

    Damage.objects.get_or_create(
        booking=booking,
        defaults={
            'description': 'No damage reported.',
            'fee': 0.00,
            'status': 'Settled'
        }
    )

    messages.success(request, f'Booking #{booking_id} marked as no damage.')
    return _admin_page('bookings')

def settle_damage(request, damage_id):
    admin = get_logged_in_admin(request) 
    if not admin:
        return redirect('login')

    damage = get_object_or_404(Damage, pk=damage_id)

    if damage.status != 'Pending':
        messages.error(request, 'This damage report is already settled.')
        return _admin_page('damages')

    damage.status = 'Settled'
    damage.save()
    messages.success(request, f'Damage #{damage_id} marked as settled.')
    return _admin_page('damages')

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
            return _admin_page('profile')

        admin.firstname = firstname
        admin.lastname  = lastname
        admin.username  = username

        if new_password:
            if new_password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return _admin_page('profile')
            admin.password = new_password

        admin.save()
        messages.success(request, 'Profile updated successfully.')

    return _admin_page('profile')

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


# ─── Customer availability calendar (our own database, no names) ──

def customer_availability(request):
    """
    Taken time slots for the customer availability calendar and the
    greyed-out time dropdowns. Other customers' details are never included.
    Route: path('availability/', views.customer_availability, name='customer_availability')
    """
    customer = get_logged_in_customer(request)
    if not customer:
        return JsonResponse({'error': 'Not logged in'}, status=401)

    start, end = _parse_range(request)
    if not start:
        return JsonResponse({'error': 'Invalid date range'}, status=400)

    first_day = timezone.localtime(start).date()
    last_day = timezone.localtime(end).date()
    events = []
    for b in availability.taken_bookings(first_day, last_day):
        mine = b.customer_id == customer.customer_id
        event = {
            'start': f'{b.booking_date.isoformat()}T{b.start_time.strftime("%H:%M:%S")}',
            'end': f'{b.booking_date.isoformat()}T{b.end_time.strftime("%H:%M:%S")}',
            'title': 'Your booking' if mine else 'Booked',
            'color': '#f97316' if mine else '#3f3f46',
            'extendedProps': {'mine': mine},
        }
        if mine:
            event['extendedProps'].update({'booking_id': b.booking_id, 'status': b.booking_status})
        events.append(event)

    now = timezone.localtime()
    return JsonResponse({
        'events': events,
        'weather': get_daily_forecast(),
        'now': now.strftime('%Y-%m-%dT%H:%M:%S'),
        'open_time': f'{availability.OPEN_HOUR:02d}:00',
        'close_time': f'{availability.CLOSE_HOUR:02d}:00',
    })


# ─── Check-in: QR code / Confirmation ID verification (staff = admin) ───

def _json_body(request):
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return {}


def _checkin_response(booking, extra=None, now=None):
    """Standard JSON answer for the Check-in page."""
    now = now or timezone.now()
    ok, reason, message = checkin.check(booking, now)
    data = {'found': True, 'ok': ok, 'reason': reason, 'message': message,
            'booking': checkin.booking_summary(booking), 'now': now.isoformat()}
    if extra:
        data.update(extra)
    return JsonResponse(data)


def _not_found(code_text):
    return JsonResponse({'found': False, 'ok': False, 'reason': 'not_found',
                         'message': (f'No booking matches "{code_text}". Check the Confirmation ID and try again.'
                                     if code_text else 'Enter or scan a Confirmation ID.')})


def checkin_verify(request):
    """POST {code}: look up a booking by QR content or typed Confirmation ID."""
    if not get_logged_in_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    raw = str(_json_body(request).get('code', '')).strip()
    booking = checkin.find_booking(checkin.normalize_code(raw))
    if not booking:
        return _not_found(raw)
    return _checkin_response(booking)


def checkin_start(request):
    """POST {code}: start the playing-time countdown (only once per booking)."""
    admin = get_logged_in_admin(request)
    if not admin:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    raw = str(_json_body(request).get('code', '')).strip()
    booking = checkin.find_booking(checkin.normalize_code(raw))
    if not booking:
        return _not_found(raw)
    ok, reason, message = checkin.start_session(booking, admin)
    data = {'found': True, 'ok': ok, 'reason': reason, 'message': message,
            'booking': checkin.booking_summary(booking), 'now': timezone.now().isoformat()}
    return JsonResponse(data)


def checkin_record_cash(request):
    """POST {code}: staff collected the payment in cash at the court."""
    if not get_logged_in_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    raw = str(_json_body(request).get('code', '')).strip()
    booking = checkin.find_booking(checkin.normalize_code(raw))
    if not booking:
        return _not_found(raw)
    if booking.booking_status != 'Approved' or booking.checked_in_at:
        return _checkin_response(booking)
    checkin.record_cash_payment(booking)
    booking.refresh_from_db()
    return _checkin_response(booking, {'payment_recorded': True})


def checkin_sessions(request):
    """GET: courts in use right now, with their end times (for the countdowns)."""
    if not get_logged_in_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    sessions = [checkin.booking_summary(b) for b in checkin.active_sessions()]
    return JsonResponse({'sessions': sessions, 'now': timezone.now().isoformat()})


def checkin_end(request):
    """POST {code}: "End playing time now" - stop the countdown (staff then click Complete)."""
    if not get_logged_in_admin(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    raw = str(_json_body(request).get('code', '')).strip()
    booking = checkin.find_booking(checkin.normalize_code(raw))
    if not booking:
        return _not_found(raw)
    ok, reason, message = checkin.end_session_early(booking)
    return JsonResponse({'found': True, 'ok': ok, 'reason': reason, 'message': message,
                         'booking': checkin.booking_summary(booking), 'now': timezone.now().isoformat()})


def _resend_wait(request, auth_tab):
    """Seconds before "Resend code" can be used again (the pop-up counts down)."""
    if auth_tab == 'verify':
        customer, purpose = _pending_verify_customer(request), EmailCode.VERIFY
    elif auth_tab == 'reset':
        customer, purpose = _reset_customer(request), EmailCode.RESET
    else:
        return 0
    return email_codes.seconds_until_resend(customer, purpose) if customer else email_codes.RESEND_SECONDS
