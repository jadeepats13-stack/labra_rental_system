"""
OpenWeatherMap integration (external API #2).

Uses the free "5 day / 3 hour forecast" endpoint:
    GET https://api.openweathermap.org/data/2.5/forecast

The API key stays on the Django server; the browser only ever talks to our
own /weather_forecast/ view. If OpenWeatherMap is slow, down or the key is
invalid, we return {'available': False, ...} and booking keeps working.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

FORECAST_URL = 'https://api.openweathermap.org/data/2.5/forecast'
REQUEST_TIMEOUT = 6           # seconds
CACHE_SECONDS = 30 * 60       # reuse one forecast for 30 minutes (saves API calls)
FORECAST_DAYS = 5             # the free plan only forecasts 5 days ahead


def _unavailable(message):
    return {'available': False, 'message': message}


def _location_params():
    """Use the court's exact coordinates if set in .env, else the city."""
    lat = getattr(settings, 'COURT_LATITUDE', '')
    lon = getattr(settings, 'COURT_LONGITUDE', '')
    if lat and lon:
        return {'lat': lat, 'lon': lon}
    return {'q': getattr(settings, 'COURT_WEATHER_CITY', 'Iligan City,PH')}


def _fetch_forecast():
    """Call OpenWeatherMap (or return the cached result). Raises on failure."""
    params = _location_params()
    cache_key = 'owm_forecast_' + '_'.join(f'{k}={v}' for k, v in sorted(params.items()))
    data = cache.get(cache_key)
    if data is not None:
        return data

    params.update({'appid': settings.OPENWEATHER_API_KEY, 'units': 'metric'})
    response = requests.get(FORECAST_URL, params=params, timeout=REQUEST_TIMEOUT)
    if response.status_code == 401:
        raise PermissionError('invalid or not-yet-active API key')
    if response.status_code == 429:
        raise RuntimeError('free-plan rate limit reached')
    response.raise_for_status()
    data = response.json()
    if 'list' not in data:
        raise ValueError('unexpected response from OpenWeatherMap')

    cache.set(cache_key, data, CACHE_SECONDS)
    return data


def get_booking_forecast(booking_date, start_time):
    """
    Return the forecast closest to the booking's start time.

    booking_date: datetime.date, start_time: datetime.time (Philippine time).
    """
    if not getattr(settings, 'OPENWEATHER_API_KEY', ''):
        return _unavailable('Weather forecast is not set up yet.')

    local_tz = timezone.get_current_timezone()
    booking_dt = datetime.combine(booking_date, start_time).replace(tzinfo=local_tz)
    now = timezone.now()

    if booking_dt < now - timedelta(hours=3):
        return _unavailable('This booking time has already passed.')
    if booking_dt > now + timedelta(days=FORECAST_DAYS):
        return _unavailable('Forecast will be available 5 days before your booking.')

    try:
        data = _fetch_forecast()
    except PermissionError:
        return _unavailable('Weather service key is not active yet. Please try again later.')
    except Exception:
        return _unavailable('Weather forecast is unavailable right now.')

    target = booking_dt.timestamp()
    closest = min(data['list'], key=lambda item: abs(item.get('dt', 0) - target))
    # Only trust the match if it is within the 3-hour forecast step
    if abs(closest.get('dt', 0) - target) > 3 * 3600:
        return _unavailable('Forecast will be available 5 days before your booking.')

    weather = (closest.get('weather') or [{}])[0]
    rain_chance = round(float(closest.get('pop', 0)) * 100)
    forecast_time = datetime.fromtimestamp(closest['dt'], tz=dt_timezone.utc).astimezone(local_tz)

    return {
        'available': True,
        'temperature': round(closest.get('main', {}).get('temp', 0)),
        'feels_like': round(closest.get('main', {}).get('feels_like', 0)),
        'description': (weather.get('description') or '').capitalize(),
        'icon_url': f"https://openweathermap.org/img/wn/{weather.get('icon', '01d')}@2x.png",
        'rain_chance': rain_chance,
        'rain_warning': rain_chance >= 50 or weather.get('main') in ('Rain', 'Thunderstorm'),
        'forecast_time': forecast_time.strftime('%b %d, %I:%M %p'),
        'location': data.get('city', {}).get('name', ''),
    }
