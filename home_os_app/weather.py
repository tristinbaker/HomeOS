from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_GEO_URL     = 'https://geocoding-api.open-meteo.com/v1/search'
_WEATHER_URL = 'https://api.open-meteo.com/v1/forecast'

_WMO_EMOJI: dict[int, str] = {
    0: '☀️',
    1: '🌤️', 2: '⛅', 3: '☁️',
    45: '🌫️', 48: '🌫️',
    51: '🌦️', 53: '🌦️', 55: '🌧️',
    56: '🌦️', 57: '🌧️',
    61: '🌧️', 63: '🌧️', 65: '🌧️',
    66: '🌧️', 67: '🌧️',
    71: '🌨️', 73: '🌨️', 75: '❄️', 77: '🌨️',
    80: '🌦️', 81: '🌧️', 82: '🌧️',
    85: '🌨️', 86: '❄️',
    95: '⛈️', 96: '⛈️', 99: '⛈️',
}

_WMO_DESC: dict[int, str] = {
    0: 'Clear',
    1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
    45: 'Foggy', 48: 'Icy fog',
    51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle',
    56: 'Freezing drizzle', 57: 'Heavy freezing drizzle',
    61: 'Light rain', 63: 'Rain', 65: 'Heavy rain',
    66: 'Freezing rain', 67: 'Heavy freezing rain',
    71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains',
    80: 'Rain showers', 81: 'Showers', 82: 'Heavy showers',
    85: 'Snow showers', 86: 'Heavy snow showers',
    95: 'Thunderstorm', 96: 'Thunderstorm w/ hail', 99: 'Thunderstorm w/ hail',
}


def wmo_emoji(code: int) -> str:
    return _WMO_EMOJI.get(code, '🌡️')


def wmo_desc(code: int) -> str:
    return _WMO_DESC.get(code, 'Unknown')


def geocode(city: str) -> tuple[float, float, str]:
    """Returns (lat, lon, display_name). Raises ValueError if not found."""
    params = urlencode({'name': city, 'count': 1, 'language': 'en', 'format': 'json'})
    req = Request(f'{_GEO_URL}?{params}')
    req.add_header('User-Agent', 'HomeOS/1.0')
    with urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    results = data.get('results')
    if not results:
        raise ValueError(f'No location found for "{city}"')
    result = results[0]
    name = result['name']
    if result.get('admin1'):
        name += f', {result["admin1"]}'
    return result['latitude'], result['longitude'], name


def fetch_weather(lat: float, lon: float) -> dict:
    """Returns dict with temp_f, feels_like_f, weather_code."""
    params = urlencode({
        'latitude': lat,
        'longitude': lon,
        'current': 'temperature_2m,apparent_temperature,weather_code',
        'temperature_unit': 'fahrenheit',
        'forecast_days': 1,
    })
    req = Request(f'{_WEATHER_URL}?{params}')
    req.add_header('User-Agent', 'HomeOS/1.0')
    with urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    current = data['current']
    return {
        'temp_f': current['temperature_2m'],
        'feels_like_f': current['apparent_temperature'],
        'weather_code': current['weather_code'],
    }
