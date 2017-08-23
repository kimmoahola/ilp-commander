# coding=utf-8
from decimal import Decimal

TIMEZONE = 'Europe/Helsinki'
SHEET_OAUTH_FILE = ''
SHEET_KEY = ''
MESSAGE_SHEET_INDEX = 4
MESSAGE_SHEET_CELL = 'A1'
FMI_KEY = '12345678-1234-1234-1234-123456789012'
FMI_LOCATION = 'tampere'
YR_NO_LOCATION = 'Finland/Western_Finland/Tampere'
EMAIL_ADDRESSES = []
HEALTHCHECK_URL_CRON = ''
HEALTHCHECK_URL_MESSAGE = ''
CACHE_TIMES = {
    'ulkoilma': 25,
    'wc': 15,
    'fmi': 15,
    'yr.no': 60,
}
MINIMUM_INSIDE_TEMP = Decimal(6)
COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF = Decimal('0.018')
COOLING_TIME_BUFFER = Decimal(24)  # hours
