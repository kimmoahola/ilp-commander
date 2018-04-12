# coding=utf-8
from decimal import Decimal

TIMEZONE = 'Europe/Helsinki'
SHEET_OAUTH_FILE = ''
SHEET_KEY = ''
MESSAGE_SHEET_INDEX = 4
MESSAGE_SHEET_CELL = 'A1'
INSIDE_SHEET_TITLE = 'some title'
FMI_KEY = '12345678-1234-1234-1234-123456789012'
FMI_LOCATION = 'tampere'
OPEN_WEATHER_MAP_KEY = ''
OPEN_WEATHER_MAP_LOCATION = ''
YR_NO_LOCATION = 'Finland/Western_Finland/Tampere'
EMAIL_ADDRESSES = []
HEALTHCHECK_URL_CRON = ''
HEALTHCHECK_URL_MESSAGE = ''
CACHE_TIMES = {
    'ulkoilma': {
        'if_ok': 25,
        'if_failed': 120,
    },
    'inside': {
        'if_ok': 15,
        'if_failed': 120,
    },
    'fmi': {
        'if_ok': 15,
        'if_failed': 120,
    },
    'yr.no': {
        'if_ok': 60,
        'if_failed': 60 * 48,
    },
    'fmi_forecast': {
        'if_ok': 60,
        'if_failed': 60 * 48,
    },
    'open_weather_map': {
        'if_ok': 50,
        'if_failed': 120,
    },
}
ALLOWED_MINIMUM_INSIDE_TEMP = Decimal(1)
MINIMUM_INSIDE_TEMP = Decimal('3.5')
COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF = Decimal('0.015')


def cooling_time_buffer_func(outside_temp):
    a = 0
    b = 2
    c = 38
    return max(a * outside_temp * outside_temp + b * outside_temp + c, 10)  # hours


COOLING_TIME_BUFFER = cooling_time_buffer_func  # hours
TEMP_API_OUTSIDE = {
    'host_and_port': '192.168.1.36:8080',
    'table_name': 'ulkoilma',
}
