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
        # Safe defaults so no test ever reaches a real API; tests that need a
        # specific answer patch these again with @mock.patch.
        for target, value in [
            ('booking.services.weather.requests.get', fake_response(500)),
            ('booking.services.google_calendar.requests.get', fake_response(200, {'items': []})),
            ('booking.services.emailjs.requests.post', fake_response(200, text='OK')),
        ]:
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
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
            'confirmation_id': booking.confirmation_code,
            'qr_code_url': 'https://api.qrserver.com/v1/create-qr-code/?data=' + booking.confirmation_code +
                           '&size=240x240&margin=12&ecc=M&format=png',
        })
        self.assertRegex(booking.confirmation_code, r'^LBC-')        # created when booking
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


# ───────────────────────────── Customer features (Parts 2 & 3) ─────────────
class AvailabilityTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.other = Customer.objects.create(firstname='Maria', lastname='Santos', username='maria',
                                             password=make_password('x'), email='maria@example.com')

    def book(self, customer, start, end, status='Pending', day=None):
        return Booking.objects.create(booking_date=day or self.book_date, start_time=time(start, 0),
                                      end_time=time(end, 0), total_price=(end - start) * 200,
                                      booking_status=status, customer=customer, court=self.court)

    def params(self):
        return {'start': f'{self.book_date}T00:00:00', 'end': f'{self.book_date + timedelta(days=1)}T00:00:00'}

    def test_requires_customer_login(self):
        self.assertEqual(self.client.get(reverse('customer_availability'), self.params()).status_code, 401)

    def test_bad_range(self):
        self.login_customer()
        self.assertEqual(self.client.get(reverse('customer_availability'), {'start': 'x'}).status_code, 400)

    def test_other_customers_details_are_never_sent(self):
        mine = self.book(self.customer, 10, 12, 'Approved')
        self.book(self.other, 14, 16, 'Pending')
        self.book(self.other, 17, 18, 'Cancelled')     # cancelled: slot is free again
        self.book(self.other, 8, 9, 'Completed')       # completed: not shown
        self.login_customer()
        resp = self.client.get(reverse('customer_availability'), self.params())
        body = resp.content.decode()
        self.assertNotIn('Maria', body)
        self.assertNotIn('maria', body)
        events = resp.json()['events']
        self.assertEqual(len(events), 2)
        own = [e for e in events if e['extendedProps']['mine']][0]
        other = [e for e in events if not e['extendedProps']['mine']][0]
        self.assertEqual((own['title'], own['extendedProps']['booking_id']), ('Your booking', mine.booking_id))
        self.assertEqual(other['title'], 'Booked')
        self.assertEqual(set(other['extendedProps']), {'mine'})
        self.assertEqual(other['start'], f'{self.book_date}T14:00:00')

    @mock.patch('booking.services.weather.requests.get')
    def test_includes_daily_weather(self, get):
        get.return_value = fake_response(200, owm_forecast_for(
            timezone.make_aware(datetime.combine(self.book_date, time(14, 0)))))
        self.login_customer()
        data = self.client.get(reverse('customer_availability'), self.params()).json()
        day = data['weather'][self.book_date.isoformat()]
        self.assertEqual(day['description'], 'Light rain')
        self.assertEqual(day['rain_chance'], 80)
        self.assertTrue(day['rain_warning'])
        self.assertEqual(data['open_time'], '08:00')

    def test_free_hours_and_week_overview(self):
        from . import availability as av
        self.book(self.other, 10, 12, 'Approved')
        self.book(self.customer, 13, 14, 'Pending')
        self.book(self.other, 15, 18, 'Cancelled')
        now = timezone.make_aware(datetime.combine(self.book_date - timedelta(days=1), time(9, 0)))
        self.assertEqual(av.free_hours(self.book_date, now=now), 11.0)
        # Today: slots that already started are not free
        today_now = timezone.make_aware(datetime.combine(self.book_date, time(20, 15)))
        self.assertEqual(av.free_hours(self.book_date, now=today_now), 1.5)
        week = av.week_overview(self.book_date - timedelta(days=1), now=now)
        self.assertEqual(len(week), 7)
        self.assertEqual(week[1]['free_hours'], 11.0)
        self.assertEqual(week[1]['percent_free'], round(11 / 14 * 100))

    def test_countdown_and_next_game(self):
        from . import availability as av
        later = self.book(self.customer, 16, 17, 'Approved')
        sooner = self.book(self.customer, 9, 10, 'Pending')
        self.book(self.customer, 7, 8, 'Cancelled')
        now = timezone.make_aware(datetime.combine(self.book_date - timedelta(days=2), time(6, 30)))
        self.assertEqual(av.next_game(self.customer, now), sooner)
        self.assertEqual(av.countdown_text(sooner, now), 'in 2 days, 2 hours')
        # Once the 9 AM game has ended, the 4 PM one is next
        now = timezone.make_aware(datetime.combine(self.book_date, time(10, 0)))
        self.assertEqual(av.next_game(self.customer, now), later)
        self.assertEqual(av.countdown_text(later, now), 'in 6 hours')
        self.assertEqual(av.countdown_text(later, now.replace(hour=15, minute=40)), 'in 20 min')
        now = timezone.make_aware(datetime.combine(self.book_date, time(18, 0)))
        self.assertIsNone(av.next_game(self.customer, now))

    @mock.patch('booking.services.weather.requests.get', side_effect=requests.Timeout())
    def test_daily_forecast_empty_when_unavailable(self, _get):
        from .services.weather import get_daily_forecast
        self.assertEqual(get_daily_forecast(), {})


class CustomerDashboardTests(BaseTestCase):
    def dashboard(self):
        self.login_customer()
        return self.client.get(reverse('customer_dashboard')).content.decode()

    def test_next_game_card_unpaid_pending(self):
        b = self.make_booking(status='Pending')
        html = self.dashboard()
        self.assertIn('Your next game', html)
        self.assertIn(f'<dt>Booking</dt><dd>#{b.booking_id}</dd>', html)
        self.assertIn(f'class="btn btn-primary btn-sm pay-now-btn" data-id="{b.booking_id}"', html)
        self.assertRegex(html, r'ticket-countdown">Starts in \d+ days?')
        self.assertNotIn('calendar.google.com', html)

    def test_next_game_approved_paid_has_no_pay_or_google_button(self):
        b = self.make_booking(status='Approved')
        Payment.objects.create(booking=b, payment_amount=400, payment_status='Paid', payment_method='Online')
        html = self.dashboard()
        self.assertNotIn('calendar.google.com', html)
        self.assertNotIn(f'pay-now-btn" data-id="{b.booking_id}"', html)

    def test_no_upcoming_game(self):
        html = self.dashboard()
        self.assertIn('No game booked yet', html)
        self.assertIn('Book the LA Court', html)

    def test_week_strip_and_court_card(self):
        html = self.dashboard()
        self.assertEqual(html.count('onclick="openBookingOn('), 7)
        self.assertIn('This week at the LA Court', html)
        self.assertIn('hours free today', html)
        self.assertNotIn('Court Availability', html)
        self.assertNotIn('courts-grid', html)

    def test_reminders(self):
        self.make_booking(status='Pending')
        self.make_booking(status='Cancelled', start=time(15, 0), end=time(16, 0))
        self.customer.email = ''
        self.customer.save()
        html = self.dashboard()
        self.assertIn('You have <strong>1</strong> unpaid booking.', html)
        stat = html.split('Unpaid Bills</div>')[1][:80]
        self.assertIn('>1<', stat)                       # stat matches the reminder
        self.assertIn('Add your email address', html)
        self.assertNotIn('was cancelled', html)          # cancelled banners were removed

    def test_no_reminders_when_nothing_applies(self):
        html = self.dashboard()
        self.assertNotIn('class="reminders"', html)

    def test_my_bookings_has_no_google_button(self):
        approved = self.make_booking(status='Approved')
        self.make_booking(status='Pending', start=time(14, 0), end=time(15, 0))
        html = self.dashboard()
        bookings_page = html.split('id="page-bookings"')[1].split('id="page-history"')[0]
        self.assertEqual(bookings_page.count('btn-gcal'), 0)
        self.assertIn(f'data-search="{approved.booking_id}" data-status="Approved" data-payment="Unpaid"', bookings_page)

    def test_customer_search_bars_and_calendar_present(self):
        html = self.dashboard()
        for table in ['myBookingsTable', 'historyTable', 'myPaymentsTable']:
            self.assertIn(f'data-table="{table}"', html)
            self.assertIn(f'id="{table}"', html)
        self.assertIn(f'id="availCalendar" data-url="{reverse("customer_availability")}"', html)
        self.assertIn('js/customer/customer_availability.js', html)


class LayoutTweakTests(BaseTestCase):
    def test_customer_dashboard_order(self):
        self.make_booking(status='Approved')
        self.login_customer()
        html = self.client.get(reverse('customer_dashboard')).content.decode()
        dash = html.split('id="page-dashboard"')[1].split('{% include')[0]
        order = [dash.index(x) for x in ['This week at the LA Court', 'class="stats-grid"',
                                         'Your next game', 'Recent Bookings']]
        self.assertEqual(order, sorted(order))

    def test_no_clear_buttons_anywhere(self):
        self.login_customer()
        self.assertNotIn('data-filter="clear"', self.client.get(reverse('customer_dashboard')).content.decode())
        self.client.logout()
        self.login_admin()
        self.assertNotIn('data-filter="clear"', self.client.get(reverse('admin_dashboard')).content.decode())


# ───────────────────────────── QR / Confirmation ID check-in ─────────────
import zoneinfo

MANILA = zoneinfo.ZoneInfo('Asia/Manila')
FIXED_NOW = datetime(2030, 6, 15, 15, 0, tzinfo=MANILA)      # Sat 3:00 PM
GAME_DAY = FIXED_NOW.date()


class CheckinTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch('django.utils.timezone.now', return_value=FIXED_NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    # helpers ------------------------------------------------------------
    def booking(self, start=time(15, 0), end=time(17, 0), status='Approved', paid=True, day=GAME_DAY):
        b = Booking.objects.create(booking_date=day, start_time=start, end_time=end, total_price=400,
                                   booking_status=status, customer=self.customer, court=self.court)
        if paid:
            Payment.objects.create(booking=b, payment_amount=400, payment_status='Paid', payment_method='Online')
        if status == 'Approved':
            from . import checkin
            checkin.ensure_code(b)
            b.refresh_from_db()
        return b

    def staff(self):
        self.login_admin()

    def verify(self, code):
        return self.client.post(reverse('checkin_verify'), json.dumps({'code': code}),
                                content_type='application/json').json()

    def start(self, code):
        return self.client.post(reverse('checkin_start'), json.dumps({'code': code}),
                                content_type='application/json').json()

    # codes ---------------------------------------------------------------
    def test_codes_are_unique_and_well_formed(self):
        from . import checkin
        codes = set()
        for i in range(60):
            b = Booking.objects.create(booking_date=GAME_DAY, start_time=time(8, 0), end_time=time(9, 0),
                                       total_price=200, booking_status='Approved',
                                       customer=self.customer, court=self.court)
            code = checkin.ensure_code(b)
            self.assertRegex(code, r'^LBC-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$')
            self.assertEqual(checkin.ensure_code(b), code)          # stable, not regenerated
            codes.add(code)
        self.assertEqual(len(codes), 60)

    def test_normalize_code(self):
        from .checkin import normalize_code
        for text in ['LBC-7K3P-9Q2X', 'lbc-7k3p-9q2x', ' LBC 7K3P 9Q2X ', 'LBC7K3P9Q2X', '7K3P9Q2X']:
            self.assertEqual(normalize_code(text), 'LBC-7K3P-9Q2X', text)
        for text in ['', 'hello', 'LBC-123', 'https://example.com']:
            self.assertEqual(normalize_code(text), '', text)

    def test_approval_gives_old_bookings_a_code_and_sends_no_second_email(self):
        b = Booking.objects.create(booking_date=GAME_DAY + timedelta(days=1), start_time=time(10, 0),
                                   end_time=time(12, 0), total_price=400, booking_status='Pending',
                                   customer=self.customer, court=self.court)     # made before this feature
        self.staff()
        with mock.patch('booking.services.emailjs.requests.post') as post:
            resp = self.client.post(reverse('admin_approve_booking', args=[b.booking_id]), follow=True)
        post.assert_not_called()                     # only one email: the booking email
        b.refresh_from_db()
        self.assertRegex(b.confirmation_code, r'^LBC-')
        self.assertIn(f'has been approved ({b.confirmation_code})', resp.content.decode())

    def test_approval_keeps_the_code_from_booking_time(self):
        from . import checkin
        b = Booking.objects.create(booking_date=GAME_DAY, start_time=time(18, 0), end_time=time(19, 0),
                                   total_price=200, booking_status='Pending', customer=self.customer, court=self.court)
        code = checkin.ensure_code(b)
        self.staff()
        self.client.post(reverse('admin_approve_booking', args=[b.booking_id]))
        b.refresh_from_db()
        self.assertEqual((b.booking_status, b.confirmation_code), ('Approved', code))

    # verification rules --------------------------------------------------
    def test_typed_id_verifies_ok(self):
        b = self.booking()
        self.staff()
        data = self.verify(b.confirmation_code.lower().replace('-', ' '))
        self.assertTrue(data['ok'])
        self.assertEqual(data['booking']['booking_id'], b.booking_id)
        self.assertEqual(data['booking']['customer'], 'Juan Cruz')

    def test_unknown_code(self):
        self.staff()
        data = self.verify('LBC-AAAA-BBBB')
        self.assertFalse(data['found'])
        self.assertEqual(data['reason'], 'not_found')

    def test_window_rules(self):
        self.staff()
        cases = [
            (dict(start=time(15, 10), end=time(16, 0)), True, 'ok'),        # 10 min early: allowed
            (dict(start=time(15, 30), end=time(16, 30)), False, 'early'),   # 30 min early: too early
            (dict(start=time(13, 0), end=time(15, 0)), False, 'ended'),     # just ended
            (dict(start=time(14, 0), end=time(16, 0)), True, 'ok'),         # late arrival: allowed
            (dict(day=GAME_DAY + timedelta(days=1)), False, 'day'),
        ]
        for kwargs, ok, reason in cases:
            b = self.booking(**kwargs)
            data = self.verify(b.confirmation_code)
            self.assertEqual((data['ok'], data['reason']), (ok, reason), kwargs)

    def test_status_rules(self):
        self.staff()
        for status in ['Pending', 'Cancelled', 'Completed']:
            b = self.booking()
            Booking.objects.filter(pk=b.pk).update(booking_status=status)
            data = self.verify(b.confirmation_code)
            self.assertEqual((data['ok'], data['reason']), (False, 'status'), status)

    def test_unpaid_is_blocked_until_cash_recorded(self):
        b = self.booking(paid=False)
        self.staff()
        data = self.verify(b.confirmation_code)
        self.assertEqual((data['ok'], data['reason']), (False, 'unpaid'))
        self.assertEqual(self.start(b.confirmation_code)['reason'], 'unpaid')   # start also blocked
        data = self.client.post(reverse('checkin_record_cash'), json.dumps({'code': b.confirmation_code}),
                                content_type='application/json').json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['payment_recorded'])
        payment = Payment.objects.get(booking=b)
        self.assertEqual((payment.payment_status, payment.payment_method), ('Paid', 'Cash'))

    # starting playing time -----------------------------------------------
    def test_start_once_only_and_end_is_reserved_end(self):
        b = self.booking(start=time(14, 0), end=time(16, 0))   # customer is an hour late
        self.staff()
        first = self.start(b.confirmation_code)
        self.assertEqual((first['ok'], first['reason']), (True, 'started'))
        b.refresh_from_db()
        self.assertEqual(b.checked_in_at, FIXED_NOW)
        self.assertEqual(timezone.localtime(b.session_ends_at).time(), time(16, 0))   # not 17:00
        self.assertEqual(b.checked_in_by, self.admin)

        second = self.start(b.confirmation_code)
        self.assertEqual((second['ok'], second['reason']), (False, 'already'))
        self.assertIn('Already checked in at 3:00 PM and playing now', second['message'])
        b.refresh_from_db()
        self.assertEqual(b.checked_in_at, FIXED_NOW)          # unchanged

    def test_qr_content_and_typed_id_use_the_same_record(self):
        b = self.booking()
        self.staff()
        # The camera scanner sends exactly what the QR contains: the Confirmation ID
        qr_text = b.confirmation_code
        scanned = self.verify(qr_text)
        typed = self.verify(b.confirmation_code.lower().replace('-', ''))
        self.assertEqual(scanned['booking']['booking_id'], typed['booking']['booking_id'])
        self.assertTrue(self.start(qr_text)['ok'])                                 # started by scanning
        self.assertEqual(self.verify(b.confirmation_code)['reason'], 'already')   # typed: refused
        self.assertFalse(self.start(b.confirmation_code)['ok'])

    def test_qr_image_url_contains_code(self):
        from .services.qr_code import qr_image_url
        b = self.booking()
        url = qr_image_url(b.confirmation_code)
        self.assertTrue(url.startswith('https://api.qrserver.com/v1/create-qr-code/?'))
        self.assertIn('data=' + b.confirmation_code, url)

    def test_race_two_staff_start_at_once(self):
        from . import checkin
        b = self.booking()
        stale_copy = Booking.objects.get(pk=b.pk)               # loaded before anyone checked in
        ok1, _, _ = checkin.start_session(b, self.admin)
        ok2, reason2, _ = checkin.start_session(stale_copy, self.admin)
        self.assertTrue(ok1)
        self.assertEqual((ok2, reason2), (False, 'already'))

    # sessions + auto-complete ---------------------------------------------
    def test_sessions_list_and_auto_complete(self):
        b = self.booking(start=time(14, 0), end=time(16, 0))
        self.staff()
        self.start(b.confirmation_code)
        data = self.client.get(reverse('checkin_sessions')).json()
        self.assertEqual([s['booking_id'] for s in data['sessions']], [b.booking_id])
        self.assertTrue(data['sessions'][0]['ends_at'].startswith('2030-06-15T08:00:00'))   # 16:00 Manila in UTC
        later = FIXED_NOW + timedelta(hours=1, minutes=1)
        with mock.patch('django.utils.timezone.now', return_value=later):
            data = self.client.get(reverse('checkin_sessions')).json()
        self.assertEqual(data['sessions'], [])
        self.assertEqual(data['completed'], 1)
        b.refresh_from_db()
        self.assertEqual(b.booking_status, 'Completed')

    # security ---------------------------------------------------------------
    def test_staff_endpoints_need_admin(self):
        b = self.booking()
        self.login_customer()
        for name in ['checkin_verify', 'checkin_start', 'checkin_record_cash', 'checkin_end']:
            self.assertEqual(self.client.post(reverse(name), json.dumps({'code': b.confirmation_code}),
                                              content_type='application/json').status_code, 401, name)
        self.assertEqual(self.client.get(reverse('checkin_sessions')).status_code, 401)
        b.refresh_from_db()
        self.assertIsNone(b.checked_in_at)

    def test_verify_requires_post(self):
        self.staff()
        self.assertEqual(self.client.get(reverse('checkin_verify')).status_code, 405)

    # pages ---------------------------------------------------------------
    def test_admin_checkin_page(self):
        self.staff()
        html = self.client.get(reverse('admin_dashboard')).content.decode()
        self.assertIn('id="page-checkin"', html)
        self.assertIn('vendor/html5-qrcode/html5-qrcode.min.js', html)
        for label in ['Scan QR', 'Enter ID', 'Court in use']:
            self.assertIn(label, html)
        self.assertNotIn('Upload photo', html)

    def test_customer_sees_qr_and_code(self):
        b = self.booking(start=time(17, 0), end=time(19, 0))
        self.login_customer()
        html = self.client.get(reverse('customer_dashboard')).content.decode()
        self.assertIn(f'<dd class="ticket-code">{b.confirmation_code}</dd>', html)
        self.assertIn('Show check-in QR', html)
        bookings_page = html.split('id="page-bookings"')[1].split('id="page-history"')[0]
        self.assertIn('Check-in QR', bookings_page)
        self.assertIn(f'data-code="{b.confirmation_code}"', bookings_page)
        self.assertIn('api.qrserver.com/v1/create-qr-code/', bookings_page)

    def test_pending_booking_shows_qr_with_pending_status(self):
        from . import checkin
        b = Booking.objects.create(booking_date=GAME_DAY, start_time=time(17, 0), end_time=time(18, 0), total_price=200,
                                   booking_status='Pending', customer=self.customer, court=self.court)
        checkin.ensure_code(b)
        b.refresh_from_db()
        self.login_customer()
        html = self.client.get(reverse('customer_dashboard')).content.decode()
        self.assertIn(f'data-qr-open data-status="Pending"', html)
        self.assertIn(f'data-code="{b.confirmation_code}"', html)
        # ...but staff cannot start it until it is approved
        self.client.logout()
        self.staff()
        self.assertEqual(self.verify(b.confirmation_code)['reason'], 'status')

    def test_customer_live_countdown_and_no_cancel_after_checkin(self):
        b = self.booking(start=time(14, 0), end=time(16, 0))
        self.staff()
        self.start(b.confirmation_code)
        self.client.logout()
        self.login_customer()
        html = self.client.get(reverse('customer_dashboard')).content.decode()
        self.assertIn('Playing now', html)
        self.assertIn('class="ticket-countdown ticket-live"', html)
        self.assertIn('Checked in</span>', html)
        self.client.get(reverse('cancel_booking', args=[b.booking_id]))
        b.refresh_from_db()
        self.assertEqual(b.booking_status, 'Approved')         # not cancelled

    # ending early -------------------------------------------------------
    def end(self, code):
        return self.client.post(reverse('checkin_end'), json.dumps({'code': code}),
                                content_type='application/json').json()

    def test_end_early_completes_and_frees_the_slot(self):
        b = self.booking(start=time(14, 0), end=time(16, 0))
        self.staff()
        self.start(b.confirmation_code)
        later = FIXED_NOW + timedelta(minutes=10)                 # 3:10 PM, 50 min left
        with mock.patch('django.utils.timezone.now', return_value=later):
            data = self.end(b.confirmation_code)
            self.assertEqual((data['ok'], data['reason']), (True, 'ended'))
            self.assertIn('ended early at 3:10 PM (50 min unused)', data['message'])
            b.refresh_from_db()
            self.assertEqual(b.booking_status, 'Completed')
            self.assertEqual(b.session_ends_at, later)
            self.assertEqual(self.client.get(reverse('checkin_sessions')).json()['sessions'], [])
            # second click / second staff: refused, nothing changes
            again = self.end(b.confirmation_code)
            self.assertEqual((again['ok'], again['reason']), (False, 'already_ended'))
            # verifying it again shows it is completed, so it can't be restarted
            self.assertEqual(self.verify(b.confirmation_code)['reason'], 'already')
            self.assertFalse(self.start(b.confirmation_code)['ok'])
            # the rest of the slot no longer blocks new bookings
            from . import availability
            self.assertEqual(availability.taken_bookings(GAME_DAY, GAME_DAY).filter(pk=b.pk).count(), 0)

    def test_end_early_needs_a_started_session(self):
        b = self.booking()
        self.staff()
        data = self.end(b.confirmation_code)
        self.assertEqual((data['ok'], data['reason']), (False, 'not_started'))
        b.refresh_from_db()
        self.assertEqual(b.booking_status, 'Approved')

    def test_end_early_staff_only(self):
        b = self.booking(start=time(14, 0), end=time(16, 0))
        self.staff()
        self.start(b.confirmation_code)
        self.client.logout()
        self.login_customer()
        self.assertEqual(self.client.post(reverse('checkin_end'), json.dumps({'code': b.confirmation_code}),
                                          content_type='application/json').status_code, 401)
        b.refresh_from_db()
        self.assertEqual(b.booking_status, 'Approved')

    def test_end_early_ui_present(self):
        self.staff()
        html = self.client.get(reverse('admin_dashboard')).content.decode()
        self.assertIn('id="ciEndModal"', html)
        self.assertIn('End playing time now', html)
        self.assertIn(f'data-end-url="{reverse("checkin_end")}"', html)


# ───────────────────────────── Landing page + Log in / Sign up pop-up ─────
class AuthPopupTests(BaseTestCase):
    def register(self, **overrides):
        data = {'firstname': 'Ana', 'lastname': 'Reyes', 'username': 'ana', 'email': 'ana@example.com',
                'password': 'Xyz12345!', 'confirm_password': 'Xyz12345!'}
        data.update(overrides)
        return self.client.post(reverse('register'), data)

    def test_login_with_email(self):
        resp = self.client.post(reverse('login'), {'username': 'JUAN@example.com', 'password': 'Passw0rd!'})
        self.assertRedirects(resp, reverse('customer_dashboard'), fetch_redirect_response=False)

    def test_login_with_username_still_works(self):
        resp = self.client.post(reverse('login'), {'username': 'juan', 'password': 'Passw0rd!'})
        self.assertRedirects(resp, reverse('customer_dashboard'), fetch_redirect_response=False)

    def test_admin_login_by_username(self):
        resp = self.client.post(reverse('login'), {'username': 'admin1', 'password': 'adminpass'})
        self.assertRedirects(resp, reverse('admin_dashboard'), fetch_redirect_response=False)

    def test_invalid_email_is_rejected_and_shown_in_popup(self):
        resp = self.client.post(reverse('login'), {'username': 'juan@example', 'password': 'Passw0rd!'}, follow=True)
        html = resp.content.decode()
        self.assertIn('That email address is not valid', html)
        self.assertIn('data-open="login"', html)                  # pop-up opens with the message
        self.assertIn('value="juan@example"', html)              # what they typed is kept
        self.assertNotIn('customer_id', self.client.session)

    def test_wrong_password_with_email(self):
        resp = self.client.post(reverse('login'), {'username': 'juan@example.com', 'password': 'nope'}, follow=True)
        self.assertIn('Incorrect email or password.', resp.content.decode())
        self.assertNotIn('customer_id', self.client.session)

    def test_duplicate_email_accounts_must_use_username(self):
        Customer.objects.create(firstname='J', lastname='C', username='juan2', password=make_password('x'),
                                email='juan@example.com')
        resp = self.client.post(reverse('login'), {'username': 'juan@example.com', 'password': 'Passw0rd!'}, follow=True)
        self.assertIn('used by more than one account', resp.content.decode())

    def test_register_rejects_invalid_and_taken_email(self):
        self.register(email='ana@example', username='ana1')
        self.assertFalse(Customer.objects.filter(username='ana1').exists())
        self.register(email='JUAN@example.com', username='ana2')
        self.assertFalse(Customer.objects.filter(username='ana2').exists())
        html = self.client.get(reverse('register')).content.decode()
        self.assertIn('data-open="register"', html)

    def test_register_errors_keep_typed_values_but_never_passwords(self):
        resp = self.register(confirm_password='different', username='ana3', email='ana3@example.com')
        html = self.client.get(resp.url).content.decode()
        self.assertIn('Passwords do not match.', html)
        self.assertIn('value="ana3@example.com"', html)
        self.assertNotIn('Xyz12345!', html)

    def test_register_success_then_popup_on_login(self):
        resp = self.register()
        self.assertRedirects(resp, reverse('login'), fetch_redirect_response=False)
        html = self.client.get(reverse('login')).content.decode()
        self.assertIn('Account created. You can log in now.', html)
        self.assertIn('value="ana"', html)
        self.assertEqual(Customer.objects.get(username='ana').email, 'ana@example.com')

    def test_username_with_at_sign_rejected(self):
        self.register(username='ana@x')
        self.assertFalse(Customer.objects.filter(username='ana@x').exists())

    def test_profile_email_must_be_unique(self):
        Customer.objects.create(firstname='M', lastname='S', username='maria', password=make_password('x'),
                                email='maria@example.com')
        self.login_customer()
        self.client.post(reverse('update_profile'), {'firstname': 'Juan', 'lastname': 'Cruz', 'username': 'juan',
                                                     'email': 'MARIA@example.com'})
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, 'juan@example.com')

    def test_landing_page(self):
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('Today at the LA Court', html)
        self.assertIn('data-auth="login"', html)
        self.assertIn('data-auth="register"', html)
        self.assertIn('data-open=""', html)                      # pop-up closed on the home page
        self.assertNotIn('material-icons', html)                 # old login icon removed
        self.login_customer()
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('My dashboard', html)


class SidebarBadgeTests(BaseTestCase):
    def test_admin_badges(self):
        self.make_booking(status='Pending')
        self.make_booking(status='Pending', start=time(14, 0), end=time(15, 0))
        done = self.make_booking(status='Completed', start=time(16, 0), end=time(17, 0))
        from .models import Damage
        Damage.objects.create(booking=done, description='Broken net', fee=150, status='Pending')
        self.login_admin()
        html = self.client.get(reverse('admin_dashboard')).content.decode()
        self.assertIn('title="2 waiting for approval">2</span>', html)
        self.assertIn('title="1 not settled">1</span>', html)
        self.assertIn('id="badgeCheckin" title="Playing now" hidden>0</span>', html)

    def test_admin_badges_hidden_when_zero(self):
        self.login_admin()
        html = self.client.get(reverse('admin_dashboard')).content.decode()
        self.assertNotIn('waiting for approval', html)
        self.assertNotIn('not settled', html)

    def test_customer_badges(self):
        self.make_booking(status='Approved')
        self.make_booking(status='Pending', start=time(14, 0), end=time(15, 0))
        self.make_booking(status='Cancelled', start=time(16, 0), end=time(17, 0))
        self.login_customer()
        html = self.client.get(reverse('customer_dashboard')).content.decode()
        self.assertRegex(html, r'id="badgeBookings"[^>]*data-items="\d+:Approved:unpaid,\d+:Pending:unpaid"[^>]*>2</span>')
        self.assertIn('title="2 unpaid">2</span>', html)

