# coding=utf-8
from decimal import Decimal

TIMEZONE = 'Europe/Helsinki'
SHEET_OAUTH_FILE = ''
SHEET_KEY = ''
MESSAGE_SHEET_INDEX = 4
MESSAGE_SHEET_CELL = 'A1'
INSIDE_SHEET_TITLE = 'some title'
FMI_LOCATION = 'tampere'
OPEN_WEATHER_MAP_KEY = ''
OPEN_WEATHER_MAP_LOCATION = ''
YR_NO_LOCATION = 'Finland/Western_Finland/Tampere'
SMARTTHINGS_INSIDE_DEVICE_IDS = ["...", "..."]
SMARTTHINGS_TOKEN = "..."
OUTSIDE_TEMP_ENDPOINT = "https://1234.execute-api.eu-north-1.amazonaws.com/..."
STORAGE_ROOT_URL = "https://1234.execute-api.eu-north-1.amazonaws.com/..."
EMAIL_ADDRESSES = []
HEALTHCHECK_URL_CRON = ''
HEALTHCHECK_URL_MESSAGE = ''
CACHE_TIMES = {
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

CONTROLLER_P = Decimal(2)
CONTROLLER_I = Decimal(2)
CONTROLLER_D = Decimal(25)


def cooling_time_buffer_func(outside_temp):
    a = 0
    b = 2
    c = 38
    return max(a * outside_temp * outside_temp + b * outside_temp + c, 10)  # hours


COOLING_TIME_BUFFER = cooling_time_buffer_func  # hours
