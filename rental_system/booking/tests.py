"""
Automated tests for the Labra Basketball Court Rental System.

Run with:   python manage.py test booking

External APIs are replaced by fake responses here (unittest.mock) so the
tests run offline and never use real quota. The fake responses follow the
shape documented by each provider. Live checks are done manually; see
API_SETUP.md.
"""
import base64
import json
from datetime import date, time, timedelta, datetime
from unittest import mock

import requests
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Admin, Booking, Court, Customer, GoogleCalendarToken, Payment

API_SETTINGS = dict(
    OPENWEATHER_API_KEY='test-owm-key', COURT_LATITUDE='', COURT_LONGITUDE='',
    COURT_WEATHER_CITY='Iligan City,PH',
    EMAILJS_SERVICE_ID='service_test', EMAILJS_TEMPLATE_ID='template_test',
    EMAILJS_PUBLIC_KEY='public_test', EMAILJS_PRIVATE_KEY='private_test',
    GOOGLE_CLIENT_ID='client-id-test', GOOGLE_CLIENT_SECRET='client-secret-test',
    GOOGLE_REDIRECT_URI='http://127.0.0.1:8000/oauth2callback/',
)


def fake_response(status=200, data=None, text=''):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = data if data is not None else {}
    resp.text = text or json.dumps(data or {})
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(str(status))
    else:
        resp.raise_for_status.return_value = None
    return resp


def owm_forecast_for(booking_dt, description='light rain', main='Rain', pop=0.8, temp=27.4):
    """OpenWeatherMap /data/2.5/forecast response with 3-hour steps around booking_dt."""
    base = int(booking_dt.timestamp()) - 6 * 3600
    items = []
    for i in range(5):
        items.append({
            'dt': base + i * 3 * 3600,
            'main': {'temp': temp + i, 'feels_like': temp + i + 2},
            'weather': [{'id': 500, 'main': main if i == 2 else 'Clouds',
                         'description': description if i == 2 else 'scattered clouds', 'icon': '10d'}],
            'pop': pop if i == 2 else 0.1,
        })
    return {'cod': '200', 'list': items, 'city': {'name': 'Iligan City'}}


@override_settings(**API_SETTINGS)
class BaseTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = Admin.objects.create(firstname='Ad', lastname='Min', username='admin1', password='adminpass')
        self.court = Court.objects.create(court_name='LA Court', rate_per_hour=200,
                                          court_status='Available', admin=self.admin)
        self.customer = Customer.objects.create(firstname='Juan', lastname='Cruz', username='juan',
                                                password=make_password('Passw0rd!'), email='juan@example.com')
        self.book_date = timezone.localdate() + timedelta(days=2)

    def login_customer(self):
        resp = self.client.post(reverse('login'), {'username': 'juan', 'password': 'Passw0rd!'})
        self.assertRedirects(resp, reverse('customer_dashboard'), fetch_redirect_response=False)

    def login_admin(self):
        resp = self.client.post(reverse('login'), {'username': 'admin1', 'password': 'adminpass'})
        self.assertRedirects(resp, reverse('admin_dashboard'), fetch_redirect_response=False)

    def make_booking(self, status='Pending', start=time(10, 0), end=time(12, 0)):
        return Booking.objects.create(booking_date=self.book_date, start_time=start, end_time=end,
                                      total_price=400, booking_status=status,
                                      customer=self.customer, court=self.court)

    def post_booking(self, start='10:00', end='12:00'):
        return self.client.post(reverse('book_court'), {
            'court_id': str(self.court.court_id), 'booking_date': self.book_date.isoformat(),
            'start_time': start, 'end_time': end, 'total_price': '400.00'})


# ───────────────────────────── single LA court ─────────────────────────────
class SingleCourtTests(BaseTestCase):
    def test_pages_show_labra_not_tambacan_gym(self):
        self.login_customer()
        for url in [reverse('home'), reverse('login'), reverse('customer_dashboard')]:
            html = self.client.get(url).content.decode()
            self.assertNotIn('Tambacan Basketball Court Rental', html)
            self.assertNotIn('Tambacan Court Rental', html)
            self.assertNotIn('Tambacan Gym', html)

    def test_booking_form_has_no_court_picker(self):
        self.login_customer()
        html = self.client.get(reverse('customer_dashboard')).content.decode()
        self.assertNotIn('— Choose a Court —', html)
        self.assertIn(f'type="hidden" name="court_id" id="courtSelect" value="{self.court.court_id}"', html)

    def test_maintenance_blocks_booking_form(self):
        self.court.court_status = 'Maintenance'
        self.court.save()
        self.login_customer()
        html = self.client.get(reverse('customer_dashboard')).content.decode()
        self.assertIn('currently under maintenance', html)

    def test_admin_cannot_add_or_delete_courts(self):
        self.login_admin()
        html = self.client.get(reverse('admin_dashboard')).content.decode()
        self.assertNotIn('+ Add Court', html)
        self.assertNotIn('addCourtModal', html)
        self.assertEqual(self.client.post('/add_court/').status_code, 404)
        self.assertEqual(self.client.post(f'/delete_court/{self.court.court_id}/').status_code, 404)
        # Editing the LA court still works
        resp = self.client.post(reverse('update_court', args=[self.court.court_id]),
                                {'court_name': 'LA Court', 'rate_per_hour': '250', 'court_status': 'Available'})
        self.assertEqual(resp.status_code, 302)
        self.court.refresh_from_db()
        self.assertEqual(self.court.rate_per_hour, 250)


# ───────────────────────────── existing features still work ─────────────────
class ExistingFeatureTests(BaseTestCase):
    @mock.patch('booking.services.emailjs.requests.post', return_value=fake_response(200, text='OK'))
    @mock.patch('booking.services.weather.requests.get', return_value=fake_response(500))
    def test_booking_and_conflict_check(self, _get, _post):
        self.login_customer()
        resp = self.post_booking()
        booking = Booking.objects.get()
        self.assertRedirects(resp, reverse('booking_confirmation', args=[booking.booking_id]),
                             fetch_redirect_response=False)
        self.post_booking('11:00', '13:00')   # overlaps
        self.assertEqual(Booking.objects.count(), 1)

    def test_cash_payment_still_works(self):
        booking = self.make_booking()
        self.login_customer()
        self.client.post(reverse('process_payment'), {'booking_id': booking.booking_id, 'payment_method': 'Cash'})
        self.assertEqual(Payment.objects.get(booking=booking).payment_status, 'Paid')

    @mock.patch('booking.views.requests.post')
    def test_paypal_create_order_unchanged(self, post):
        post.side_effect = [fake_response(200, {'access_token': 'tok'}),
                            fake_response(201, {'id': 'ORDER123', 'status': 'CREATED'})]
        booking = self.make_booking()
        self.login_customer()
        resp = self.client.post(reverse('create_paypal_order'), json.dumps({'booking_id': booking.booking_id}),
                                content_type='application/json')
        self.assertEqual(resp.json()['id'], 'ORDER123')
        self.assertIn('api-m.sandbox.paypal.com/v2/checkout/orders', post.call_args_list[1].args[0])

    def test_register_saves_email(self):
        self.client.post(reverse('register'), {'firstname': 'Ana', 'lastname': 'Reyes', 'username': 'ana',
                                               'email': 'ana@example.com', 'password': 'Xyz12345!',
                                               'confirm_password': 'Xyz12345!'})
        self.assertEqual(Customer.objects.get(username='ana').email, 'ana@example.com')

    def test_register_rejects_bad_email(self):
        self.client.post(reverse('register'), {'firstname': 'Ana', 'lastname': 'Reyes', 'username': 'ana',
                                               'email': 'not-an-email', 'password': 'Xyz12345!',
                                               'confirm_password': 'Xyz12345!'})
        self.assertFalse(Customer.objects.filter(username='ana').exists())

    def test_profile_updates_email(self):
        self.login_customer()
        self.client.post(reverse('update_profile'), {'firstname': 'Juan', 'lastname': 'Cruz',
                                                     'username': 'juan', 'email': 'new@example.com'})
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, 'new@example.com')


# ───────────────────────────── OpenWeatherMap ─────────────────────────────
class WeatherTests(BaseTestCase):
    def booking_dt(self):
        return timezone.make_aware(datetime.combine(self.book_date, time(10, 0)))

    @mock.patch('booking.services.weather.requests.get')
    def test_forecast_picks_closest_3_hour_step(self, get):
        get.return_value = fake_response(200, owm_forecast_for(self.booking_dt()))
        from .services.weather import get_booking_forecast
        result = get_booking_forecast(self.book_date, time(10, 0))
        self.assertTrue(result['available'])
        self.assertEqual(result['description'], 'Light rain')
        self.assertEqual(result['rain_chance'], 80)
        self.assertTrue(result['rain_warning'])
        self.assertEqual(result['temperature'], 29)   # 27.4 + 2, rounded
        url, kwargs = get.call_args.args[0], get.call_args.kwargs
        self.assertEqual(url, 'https://api.openweathermap.org/data/2.5/forecast')
        self.assertEqual(kwargs['params']['q'], 'Iligan City,PH')
        self.assertEqual(kwargs['params']['appid'], 'test-owm-key')
        self.assertEqual(kwargs['params']['units'], 'metric')

    @override_settings(COURT_LATITUDE='8.22', COURT_LONGITUDE='124.24')
    @mock.patch('booking.services.weather.requests.get')
    def test_uses_coordinates_when_set(self, get):
        get.return_value = fake_response(200, owm_forecast_for(self.booking_dt()))
        from .services.weather import get_booking_forecast
        get_booking_forecast(self.book_date, time(10, 0))
        params = get.call_args.kwargs['params']
        self.assertEqual((params['lat'], params['lon']), ('8.22', '124.24'))
        self.assertNotIn('q', params)

    @mock.patch('booking.services.weather.requests.get')
    def test_forecast_is_cached(self, get):
        get.return_value = fake_response(200, owm_forecast_for(self.booking_dt()))
        from .services.weather import get_booking_forecast
        get_booking_forecast(self.book_date, time(10, 0))
        get_booking_forecast(self.book_date, time(10, 0))
        self.assertEqual(get.call_count, 1)

    @mock.patch('booking.services.weather.requests.get')
    def test_too_far_ahead_makes_no_call(self, get):
        from .services.weather import get_booking_forecast
        result = get_booking_forecast(timezone.localdate() + timedelta(days=10), time(10, 0))
        self.assertFalse(result['available'])
        self.assertIn('5 days', result['message'])
        get.assert_not_called()

    @mock.patch('booking.services.weather.requests.get', return_value=fake_response(401, {'cod': 401}))
    def test_inactive_key_message(self, _get):
        from .services.weather import get_booking_forecast
        result = get_booking_forecast(self.book_date, time(10, 0))
        self.assertFalse(result['available'])
        self.assertIn('not active yet', result['message'])

    @mock.patch('booking.services.weather.requests.get', side_effect=requests.Timeout())
    def test_timeout_falls_back(self, _get):
        from .services.weather import get_booking_forecast
        self.assertFalse(get_booking_forecast(self.book_date, time(10, 0))['available'])

    @override_settings(OPENWEATHER_API_KEY='')
    def test_missing_key(self):
        from .services.weather import get_booking_forecast
        self.assertIn('not set up', get_booking_forecast(self.book_date, time(10, 0))['message'])

    @mock.patch('booking.services.weather.requests.get')
    def test_weather_endpoint_json(self, get):
        get.return_value = fake_response(200, owm_forecast_for(self.booking_dt()))
        self.assertEqual(self.client.get(reverse('weather_forecast')).status_code, 401)
        self.login_customer()
        data = self.client.get(reverse('weather_forecast'),
                               {'date': self.book_date.isoformat(), 'start': '10:00'}).json()
        self.assertTrue(data['available'])
        self.assertNotIn('test-owm-key', json.dumps(data))   # key never reaches the browser
        bad = self.client.get(reverse('weather_forecast'), {'date': 'x', 'start': 'y'})
        self.assertEqual(bad.status_code, 400)

    @mock.patch('booking.services.weather.requests.get')
    def test_confirmation_page_shows_weather(self, get):
        get.return_value = fake_response(200, owm_forecast_for(self.booking_dt()))
        booking = self.make_booking()
        self.login_customer()
        html = self.client.get(reverse('booking_confirmation', args=[booking.booking_id])).content.decode()
        self.assertIn('Light rain', html)
        self.assertIn('80% chance of rain', html)


# ───────────────────────────── EmailJS ─────────────────────────────
@mock.patch('booking.services.weather.requests.get', return_value=fake_response(500))
class EmailJSTests(BaseTestCase):
    @mock.patch('booking.services.emailjs.requests.post', return_value=fake_response(200, text='OK'))
    def test_booking_sends_email_with_template_variables(self, post, _get):
        self.login_customer()
        self.post_booking()
        booking = Booking.objects.get()
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], 'https://api.emailjs.com/api/v1.0/email/send')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['service_id'], 'service_test')
        self.assertEqual(payload['template_id'], 'template_test')
        self.assertEqual(payload['user_id'], 'public_test')
        self.assertEqual(payload['accessToken'], 'private_test')
        self.assertEqual(payload['template_params'], {
            'to_email': 'juan@example.com',
            'customer_name': 'Juan Cruz',
            'booking_id': booking.booking_id,
            'booking_date': self.book_date.strftime('%B %d, %Y'),
            'booking_time': '10:00 AM – 12:00 PM',
            'total_amount': '400.00',
            'payment_status': 'Unpaid',
        })
        html = self.client.get(reverse('booking_confirmation', args=[booking.booking_id])).content.decode()
        self.assertIn('A confirmation email was sent to juan@example.com', html)
        # Shown only once
        html = self.client.get(reverse('booking_confirmation', args=[booking.booking_id])).content.decode()
        self.assertNotIn('confirmation email was sent', html)

    @mock.patch('booking.services.emailjs.requests.post',
                return_value=fake_response(403, text='API calls are disabled for non-browser applications'))
    def test_email_failure_keeps_booking(self, _post, _get):
        self.login_customer()
        self.post_booking()
        booking = Booking.objects.get()
        html = self.client.get(reverse('booking_confirmation', args=[booking.booking_id])).content.decode()
        self.assertIn('could not send your confirmation email', html)

    @mock.patch('booking.services.emailjs.requests.post', side_effect=requests.ConnectionError())
    def test_email_network_error_keeps_booking(self, _post, _get):
        self.login_customer()
        self.post_booking()
        self.assertEqual(Booking.objects.count(), 1)

    @mock.patch('booking.services.emailjs.requests.post')
    def test_no_email_address_no_call(self, post, _get):
        self.customer.email = ''
        self.customer.save()
        self.login_customer()
        self.post_booking()
        post.assert_not_called()
        booking = Booking.objects.get()
        html = self.client.get(reverse('booking_confirmation', args=[booking.booking_id])).content.decode()
        self.assertIn('Add your email address in Edit Profile', html)


# ───────────────────────────── Google Calendar ─────────────────────────────
def fake_id_token(email):
    payload = base64.urlsafe_b64encode(json.dumps({'email': email}).encode()).decode().rstrip('=')
    return f'header.{payload}.signature'


class GoogleCalendarTests(BaseTestCase):
    def connect(self, expiry_minutes=30):
        return GoogleCalendarToken.objects.create(
            admin=self.admin, access_token='access-1', refresh_token='refresh-1',
            token_expiry=timezone.now() + timedelta(minutes=expiry_minutes), google_email='admin@gmail.com')

    def test_connect_redirects_to_google(self):
        self.login_admin()
        resp = self.client.get(reverse('google_connect'))
        self.assertEqual(resp.status_code, 302)
        url = resp['Location']
        self.assertTrue(url.startswith('https://accounts.google.com/o/oauth2/v2/auth?'))
        self.assertIn('client_id=client-id-test', url)
        self.assertIn('access_type=offline', url)
        self.assertIn('calendar.events', url)
        self.assertIn(self.client.session['google_oauth_state'], url)

    def test_connect_requires_admin(self):
        self.assertRedirects(self.client.get(reverse('google_connect')), reverse('login'),
                             fetch_redirect_response=False)

    @mock.patch('booking.services.google_calendar.requests.get', return_value=fake_response(200, {'items': []}))
    @mock.patch('booking.services.google_calendar.requests.post')
    def test_callback_saves_tokens(self, post, _get):
        post.return_value = fake_response(200, {'access_token': 'acc', 'refresh_token': 'ref',
                                                'expires_in': 3599, 'id_token': fake_id_token('admin@gmail.com')})
        self.login_admin()
        self.client.get(reverse('google_connect'))
        state = self.client.session['google_oauth_state']
        self.client.get(reverse('google_oauth_callback'), {'state': state, 'code': 'abc'})
        token = GoogleCalendarToken.objects.get()
        self.assertEqual((token.access_token, token.refresh_token, token.google_email),
                         ('acc', 'ref', 'admin@gmail.com'))
        self.assertEqual(post.call_args.kwargs['data']['grant_type'], 'authorization_code')
        html = self.client.get(reverse('admin_dashboard')).content.decode()
        self.assertIn('<span class="gcal-status connected">Connected</span>', html)
        self.assertIn('<strong>admin@gmail.com</strong>', html)

    @mock.patch('booking.services.google_calendar.requests.post')
    def test_callback_rejects_wrong_state(self, post):
        self.login_admin()
        self.client.get(reverse('google_connect'))
        self.client.get(reverse('google_oauth_callback'), {'state': 'forged', 'code': 'abc'})
        post.assert_not_called()
        self.assertFalse(GoogleCalendarToken.objects.exists())

    @mock.patch('booking.services.google_calendar.requests.post')
    def test_approve_adds_event(self, post):
        post.return_value = fake_response(200, {'id': 'event123'})
        self.connect()
        booking = self.make_booking()
        self.login_admin()
        self.client.post(reverse('admin_approve_booking', args=[booking.booking_id]))
        booking.refresh_from_db()
        self.assertEqual(booking.booking_status, 'Approved')
        self.assertEqual(booking.google_event_id, 'event123')
        url = post.call_args.args[0]
        body = post.call_args.kwargs['json']
        self.assertEqual(url, 'https://www.googleapis.com/calendar/v3/calendars/primary/events')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer access-1')
        self.assertEqual(body['start'], {'dateTime': f'{self.book_date}T10:00:00', 'timeZone': 'Asia/Manila'})
        self.assertEqual(body['end'], {'dateTime': f'{self.book_date}T12:00:00', 'timeZone': 'Asia/Manila'})
        self.assertIn('Juan Cruz', body['summary'])

    def test_approve_without_connection_still_approves(self):
        booking = self.make_booking()
        self.login_admin()
        self.client.post(reverse('admin_approve_booking', args=[booking.booking_id]))
        booking.refresh_from_db()
        self.assertEqual(booking.booking_status, 'Approved')
        self.assertEqual(booking.google_event_id, '')

    @mock.patch('booking.services.google_calendar.requests.post')
    def test_expired_token_is_refreshed(self, post):
        post.side_effect = [fake_response(200, {'access_token': 'access-2', 'expires_in': 3599}),
                            fake_response(200, {'id': 'event456'})]
        self.connect(expiry_minutes=-5)
        booking = self.make_booking()
        self.login_admin()
        self.client.post(reverse('admin_approve_booking', args=[booking.booking_id]))
        self.assertEqual(post.call_args_list[0].kwargs['data']['grant_type'], 'refresh_token')
        self.assertEqual(post.call_args_list[1].kwargs['headers']['Authorization'], 'Bearer access-2')
        booking.refresh_from_db()
        self.assertEqual(booking.google_event_id, 'event456')

    @mock.patch('booking.services.google_calendar.requests.post',
                return_value=fake_response(400, {'error': 'invalid_grant'}))
    def test_refresh_failure_still_approves(self, _post):
        self.connect(expiry_minutes=-5)
        booking = self.make_booking()
        self.login_admin()
        resp = self.client.post(reverse('admin_approve_booking', args=[booking.booking_id]), follow=True)
        booking.refresh_from_db()
        self.assertEqual(booking.booking_status, 'Approved')
        self.assertIn('Please reconnect it', resp.content.decode())

    @mock.patch('booking.services.google_calendar.requests.delete', return_value=fake_response(204))
    def test_admin_cancel_removes_event(self, delete):
        self.connect()
        booking = self.make_booking(status='Approved')
        booking.google_event_id = 'event123'
        booking.save()
        self.login_admin()
        self.client.post(reverse('admin_cancel_booking', args=[booking.booking_id]))
        self.assertTrue(delete.call_args.args[0].endswith('/events/event123'))
        booking.refresh_from_db()
        self.assertEqual((booking.booking_status, booking.google_event_id), ('Cancelled', ''))

    @mock.patch('booking.services.google_calendar.requests.delete', return_value=fake_response(204))
    def test_customer_cancel_removes_event(self, delete):
        self.connect()
        booking = self.make_booking(status='Approved')
        booking.google_event_id = 'event123'
        booking.save()
        self.login_customer()
        self.client.get(reverse('cancel_booking', args=[booking.booking_id]))
        delete.assert_called_once()
        booking.refresh_from_db()
        self.assertEqual(booking.booking_status, 'Cancelled')

    @mock.patch('booking.services.google_calendar.requests.post', return_value=fake_response(200))
    def test_disconnect(self, _post):
        self.connect()
        self.login_admin()
        self.client.post(reverse('google_disconnect'))
        self.assertFalse(GoogleCalendarToken.objects.exists())


# ───────────────────────────── Court Schedule (admin, Part 1) ─────────────
def gcal_item(event_id, start, end, summary, tag=None, status='confirmed'):
    item = {'id': event_id, 'status': status, 'summary': summary,
            'start': {'dateTime': start.isoformat()}, 'end': {'dateTime': end.isoformat()}}
    if tag is not None:
        item['extendedProperties'] = {'private': {'labra_booking_id': str(tag)}}
    return item


class CourtScheduleTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.token = GoogleCalendarToken.objects.create(
            admin=self.admin, access_token='access-1', refresh_token='refresh-1',
            token_expiry=timezone.now() + timedelta(minutes=30), google_email='admin@gmail.com')
        self.approved = self.make_booking(status='Approved', start=time(10, 0), end=time(12, 0))
        self.pending = self.make_booking(status='Pending', start=time(14, 0), end=time(15, 0))
        self.unsynced = self.make_booking(status='Approved', start=time(17, 0), end=time(18, 0))

    def aware(self, h):
        return timezone.make_aware(datetime.combine(self.book_date, time(h, 0)))

    def google_items(self):
        return {'items': [
            gcal_item('ev-tagged', self.aware(10), self.aware(12), 'LA Court – Booking #x', tag=self.approved.booking_id),
            gcal_item('ev-old', self.aware(19), self.aware(20), 'LA Court – Booking #999 (Old Customer)'),
            gcal_item('ev-personal', self.aware(9), self.aware(10), 'Dentist appointment'),
            gcal_item('ev-cancelled', self.aware(11), self.aware(12), 'LA Court – Booking #5', tag=5, status='cancelled'),
        ]}

    def range_params(self):
        start = self.book_date - timedelta(days=3)
        return {'start': f'{start}T00:00:00+08:00', 'end': f'{start + timedelta(days=7)}T00:00:00+08:00'}

    def test_new_events_carry_hidden_booking_tag(self):
        from .services.google_calendar import build_event
        event = build_event(self.approved)
        self.assertEqual(event['extendedProperties']['private']['labra_booking_id'], str(self.approved.booking_id))

    @mock.patch('booking.services.google_calendar.requests.get')
    def test_list_skips_personal_and_cancelled_events(self, get):
        get.return_value = fake_response(200, self.google_items())
        from .services.google_calendar import list_booking_events
        events = list_booking_events(self.aware(0), self.aware(23))
        self.assertEqual([e['booking_id'] for e in events], [self.approved.booking_id, 999])
        params = get.call_args.kwargs['params']
        self.assertEqual(params['singleEvents'], 'true')
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer access-1')

    @mock.patch('booking.services.google_calendar.requests.get')
    def test_list_is_cached_and_cleared_after_changes(self, get):
        get.return_value = fake_response(200, self.google_items())
        from .services import google_calendar as gc
        gc.list_booking_events(self.aware(0), self.aware(23))
        gc.list_booking_events(self.aware(0), self.aware(23))
        self.assertEqual(get.call_count, 1)
        gc.clear_events_cache()
        gc.list_booking_events(self.aware(0), self.aware(23))
        self.assertEqual(get.call_count, 2)

    def test_schedule_endpoint_requires_admin(self):
        self.assertEqual(self.client.get(reverse('admin_schedule_events'), self.range_params()).status_code, 401)
        self.login_customer()
        self.assertEqual(self.client.get(reverse('admin_schedule_events'), self.range_params()).status_code, 401)

    def test_schedule_endpoint_rejects_bad_range(self):
        self.login_admin()
        self.assertEqual(self.client.get(reverse('admin_schedule_events'), {'start': 'x', 'end': 'y'}).status_code, 400)

    @mock.patch('booking.services.google_calendar.requests.get')
    def test_schedule_combines_google_and_database(self, get):
        get.return_value = fake_response(200, self.google_items())
        self.login_admin()
        data = self.client.get(reverse('admin_schedule_events'), self.range_params()).json()
        self.assertEqual(data['google']['status'], 'ok')
        by_source = {}
        for e in data['events']:
            by_source.setdefault(e['extendedProps']['source'], []).append(e)
        # Approved booking from Google, with full details from the database
        g = [e for e in by_source['google'] if e['extendedProps']['booking_id'] == self.approved.booking_id][0]
        self.assertEqual(g['extendedProps']['customer'], 'Juan Cruz')
        self.assertEqual(g['extendedProps']['total'], '400.00')
        self.assertEqual(g['start'], f'{self.book_date}T10:00:00')
        # Old untagged event whose booking no longer exists is still shown
        self.assertTrue(any(e['extendedProps']['booking_id'] == 999 for e in by_source['google']))
        # Pending comes from the database
        self.assertEqual([e['extendedProps']['booking_id'] for e in by_source['pending']], [self.pending.booking_id])
        # Approved but missing from Google is flagged
        self.assertEqual([e['extendedProps']['booking_id'] for e in by_source['not_synced']], [self.unsynced.booking_id])
        # Personal events never appear
        self.assertFalse(any('Dentist' in e['title'] for e in data['events']))

    @mock.patch('booking.services.google_calendar.requests.get', side_effect=requests.Timeout())
    def test_schedule_falls_back_when_google_unreachable(self, _get):
        self.login_admin()
        data = self.client.get(reverse('admin_schedule_events'), self.range_params()).json()
        self.assertEqual(data['google']['status'], 'error')
        self.assertIn('from the database', data['google']['message'])
        sources = sorted(e['extendedProps']['source'] for e in data['events'])
        self.assertEqual(sources, ['database', 'database', 'pending'])

    def test_schedule_when_not_connected(self):
        self.token.delete()
        self.login_admin()
        data = self.client.get(reverse('admin_schedule_events'), self.range_params()).json()
        self.assertEqual(data['google']['status'], 'not_connected')
        self.assertEqual(len(data['events']), 3)

    @mock.patch('booking.services.google_calendar.requests.get')
    def test_dashboard_upcoming_card_reads_google(self, get):
        get.return_value = fake_response(200, self.google_items())
        self.login_admin()
        html = self.client.get(reverse('admin_dashboard')).content.decode()
        self.assertIn('Upcoming Bookings', html)
        self.assertIn('Juan Cruz', html)
        self.assertIn(f'Booking #{self.approved.booking_id}', html)
        self.assertIn('View full schedule', html)
        self.assertIn('id="page-schedule"', html)
        self.assertIn('vendor/fullcalendar/index.global.min.js', html)

    @mock.patch('booking.services.google_calendar.requests.get', return_value=fake_response(403, {'error': {}}))
    def test_dashboard_still_loads_when_google_fails(self, _get):
        self.login_admin()
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Google Calendar refused the request', resp.content.decode())

    def test_dashboard_card_when_not_connected(self):
        self.token.delete()
        self.login_admin()
        html = self.client.get(reverse('admin_dashboard')).content.decode()
        self.assertIn('Connect it in Edit Profile', html)
        self.assertIn('Connect Google Calendar', html)        # button on Edit Profile
        self.assertIn('<span class="gcal-status">Not connected</span>', html)

    @mock.patch('booking.services.google_calendar.requests.post', return_value=fake_response(200))
    def test_connect_and_disconnect_return_to_edit_profile(self, _post):
        self.login_admin()
        resp = self.client.post(reverse('google_disconnect'))
        self.assertEqual(resp['Location'], reverse('admin_dashboard') + '#profile')
        self.client.get(reverse('google_connect'))
        resp = self.client.get(reverse('google_oauth_callback'), {'state': 'wrong', 'code': 'x'})
        self.assertEqual(resp['Location'], reverse('admin_dashboard') + '#profile')

    @mock.patch('booking.services.google_calendar.requests.get', return_value=fake_response(200, {'items': []}))
    def test_google_settings_moved_off_dashboard_card(self, _get):
        self.login_admin()
        html = self.client.get(reverse('admin_dashboard')).content.decode()
        card = html.split('Upcoming Bookings')[1].split('Court Status')[0]
        self.assertNotIn('Disconnect', card)
        self.assertNotIn('Connected as', card)
        profile = html.split('id="page-profile"')[1]
        self.assertIn('Disconnect', profile)


class AdminFilterMarkupTests(BaseTestCase):
    @mock.patch('booking.services.google_calendar.requests.get', return_value=fake_response(200, {'items': []}))
    def test_tables_have_filter_bars_and_row_data(self, _get):
        b = self.make_booking(status='Approved')
        Payment.objects.create(booking=b, payment_amount=400, payment_status='Paid', payment_method='Cash')
        self.login_admin()
        html = self.client.get(reverse('admin_dashboard')).content.decode()
        for table in ['bookingsTable', 'customersTable', 'paymentsTable', 'damagesTable', 'recordsTable']:
            self.assertIn(f'data-table="{table}"', html)
            self.assertIn(f'id="{table}"', html)
        self.assertIn(f'data-status="Approved" data-method="Cash" data-date="{self.book_date}"', html)
        self.assertIn('data-search="Juan Cruz juan juan@example.com"', html)
        self.assertIn('js/common/table_filter.js', html)
