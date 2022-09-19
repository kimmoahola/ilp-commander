# coding=utf-8
import datetime
import itertools
import json
import logging
import os
import platform
import smtplib
import time
from decimal import Decimal, ROUND_HALF_UP
from email.mime.text import MIMEText
from functools import wraps, total_ordering
from subprocess import Popen, PIPE
from typing import NamedTuple, List, Optional, Tuple

import arrow
import pygsheets
import pytz
import requests
from pony import orm
from retry import retry

import config

logger = logging.getLogger('poller')
handler = logging.FileHandler('poller.log')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(funcName)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
logger.info('----- START -----')


TempTs = NamedTuple("TempTs", [('temp', Decimal), ('ts', arrow.Arrow)])
Forecast = NamedTuple("Forecast", [('temps', List[TempTs]), ('ts', arrow.Arrow)])


@total_ordering
class Command:
    def __init__(self, command_string: str, temp: Optional[Decimal]) -> None:
        self.command_string = command_string
        self.temp = temp

    def __eq__(self, other):
        return isinstance(other, Command) and self.temp == other.temp

    def __lt__(self, other):
        if self.temp is None and other.temp is None:
            return False
        elif other.temp is None:
            return False
        elif self.temp is None:
            return True
        else:
            return self.temp < other.temp

    def __str__(self):
        return self.command_string

    def __repr__(self):
        return str(self)


class Commands:
    off = Command('off', None)
    heat8 = Command('heat_8__swing_down', Decimal(8))
    heat10 = Command('heat_10__swing_down', Decimal(10))
    heat16 = Command('heat_16__fan_high__swing_down', Decimal(16))
    heat18 = Command('heat_18__fan_high__swing_down', Decimal(18))
    heat20 = Command('heat_20__fan_high__swing_down', Decimal(20))
    heat22 = Command('heat_22__fan_high__swing_down', Decimal(22))
    heat24 = Command('heat_24__fan_high__swing_down', Decimal(24))
    heat26 = Command('heat_26__fan_high__swing_down', Decimal(26))
    heat28 = Command('heat_28__fan_high__swing_down', Decimal(28))
    heat30 = Command('heat_30__fan_high__swing_down', Decimal(30))

    @staticmethod
    def command_from_controller(
            value: Decimal, inside_temp: Decimal, outside_temp: Optional[Decimal]) -> Command:

        list_of_commands = [
            Commands.heat8,
            Commands.heat10,
            Commands.heat16,
            Commands.heat18,
            Commands.heat20,
            Commands.heat22,
        ]

        if outside_temp is not None and outside_temp < 15:
            list_of_commands.append(Commands.heat24)

        heating_commands = list(filter(lambda c: c.temp > inside_temp, list_of_commands))

        ranges = []

        if len(heating_commands) >= 2:

            command_range = 1 / (len(heating_commands) - 1)

            ranges.append([0, heating_commands[0]])

            for heating_command in heating_commands[1:]:
                ranges.append([ranges[-1][0] + command_range, heating_command])

        logger.info('Ranges %s' % ranges)

        if value <= 0:
            return Commands.off

        for r in reversed(ranges):
            if value >= r[0]:
                return r[1]

        return list_of_commands[-1]


db = orm.Database()


class CommandLog(db.Entity):
    command = orm.Required(str)
    param = orm.Optional(str, default='')

    # Use str here because pony uses str() to convert datetime before insert.
    # That puts datetime in wrong format to DB.
    ts = orm.Required(str, default=lambda: arrow.utcnow().isoformat())

    def ts_local(self):
        return arrow.get(self.ts).to(config.TIMEZONE)


class IRSendLog(db.Entity):
    command = orm.Required(str)

    # Use str here because pony uses str() to convert datetime before insert.
    # That puts datetime in wrong format to DB.
    ts = orm.Required(str, default=lambda: arrow.utcnow().isoformat())

    def ts_local(self):
        return arrow.get(self.ts).to(config.TIMEZONE)


class SavedState(db.Entity):
    name = orm.Required(str)
    json = orm.Required(str)


with db.set_perms_for(CommandLog):
    orm.perm('view', group='anybody')


with db.set_perms_for(IRSendLog):
    orm.perm('view', group='anybody')


with db.set_perms_for(SavedState):
    orm.perm('view', group='anybody')


db.bind('sqlite', 'db.sqlite', create_db=True)
db.generate_mapping(create_tables=True)


@retry(tries=6, delay=3)
def send_email(address, mime_text):
    s = smtplib.SMTP('localhost')
    s.sendmail(address, [address], mime_text.as_string())
    s.quit()


def email(subject, message):

    for address in config.EMAIL_ADDRESSES:

        mime_text = MIMEText(message.encode('utf-8'), 'plain', 'utf-8')
        mime_text['Subject'] = subject
        mime_text['From'] = address
        mime_text['To'] = address

        try:
            send_email(address, mime_text)
        except Exception as e:
            logger.exception(e)


def send_ir_signal(command: Command, extra_info: Optional[list] = None, send_command_email: bool = True):
    if extra_info is None:
        extra_info = []

    logger.info(str(command))

    message = '\n'.join([time_str(), str(command)] + extra_info)

    try:
        actually_send_ir_signal(command)
    except IOError as e:
        logger.exception(e)
        message += '\nirsend: %s' % type(e).__name__

    if send_command_email:
        email('Send IR', message)


def time_str(from_str=None):
    if from_str:
        a = arrow.get(from_str)
    else:
        a = arrow.utcnow()

    return a.to(config.TIMEZONE).format('DD.MM.YYYY HH:mm')


def get_now_isoformat():
    return datetime.datetime.utcnow().replace(tzinfo=pytz.utc, microsecond=0).isoformat()


@retry(tries=2, delay=5)
def actually_send_ir_signal(command: Command):
    try:
        p = Popen(['irsend', 'SEND_ONCE', 'ilp', str(command)], stdin=PIPE, stdout=PIPE, stderr=PIPE)
        output, err = p.communicate('')
        if p.returncode != 0:
            logger.warning('%d: %s - %s' % (p.returncode, output, err))
            p_lirc_restart = Popen(['sudo', 'service', 'lirc', 'restart'])
            output, err = p_lirc_restart.communicate('')
            if p_lirc_restart.returncode != 0:
                logger.error('lirc restart failed: %d: %s - %s' % (p_lirc_restart.returncode, output, err))
            raise IOError()
    except IOError:
        raise
    except Exception as e:
        logger.exception(e)
    else:
        with orm.db_session:
            IRSendLog(command=str(command))


def timing(f):
    @wraps(f)
    def timing_wrap(*args, **kw):
        ts = time.time()
        result = f(*args, **kw)
        te = time.time()
        logger.debug('func:%r args:[%r, %r] took: %2.4f sec' % (f.__name__, args, kw, te-ts))
        return result
    return timing_wrap


def get_most_recent_message(once=False) -> dict:

    logger.info('Start polling messages')

    while True:
        most_recent_message = get_message_from_sheet()

        if most_recent_message:
            break
        else:
            sleep_time = 60 * 15
            logger.info('Sleeping %d %s', sleep_time, 'secs')
            time.sleep(sleep_time)

        if once:
            most_recent_message = get_message_from_sheet()
            break

    if most_recent_message:
        message_dict = json.loads(most_recent_message)
        command = message_dict.get('command')

        if command:
            with orm.db_session:
                param = message_dict.get('param')
                if param is None:
                    param = ''
                else:
                    param = json.dumps(param)

                CommandLog(command=command, param=param)
        else:
            message_dict = {}
    else:
        message_dict = {}

    return message_dict


class InitPygsheets:
    _sh = None

    @classmethod
    def init_pygsheets(cls):

        if not cls._sh:
            try:
                cls._get_work_sheet()
            except Exception as e:
                logger.exception(e)
                cls._sh = None

        return cls._sh

    @classmethod
    def reset_pygsheets(cls):
        logger.info('Reset pygsheets')
        cls._sh = None

    @classmethod
    @retry(tries=3, delay=30)
    @timing
    def _get_work_sheet(cls):
        logger.info('Init pygsheets')
        gc = pygsheets.authorize(
            outh_file=config.SHEET_OAUTH_FILE,
            outh_nonlocal=True,
            no_cache=True)
        cls._sh = gc.open_by_key(config.SHEET_KEY)


@retry(tries=3, delay=10)
def get_url(url, headers=None):
    logger.debug(url)
    return requests.get(url, timeout=60, headers=headers)


def get_from_smartthings(device_id):
    temp, ts = None, None

    try:
        result = get_url("https://api.smartthings.com/v1/devices/%s/status" % device_id,
            headers={"Authorization": "Bearer %s" % config.SMARTTHINGS_TOKEN})
        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            item = result.json()["components"]["main"]["temperatureMeasurement"]["temperature"]
            if item["unit"] == "C":
                temp = decimal_round(item["value"])
                ts = arrow.get(item["timestamp"])
    except Exception as e:
        logger.exception(e)

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


@retry(tries=3, delay=10)
def post_url(url, data):
    logger.debug(url)

    def decimal_default(obj):
        if isinstance(obj, Decimal):
            return str(obj)
        raise TypeError

    dumps = json.dumps(data, default=decimal_default)
    logger.debug(dumps)
    return requests.post(url, data=dumps, timeout=60)


def get_from_lambda_url(url):
    temp, ts = None, None

    try:
        result = get_url(url)
    except Exception as e:
        logger.exception(e)
    else:
        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            latest_item = result.json().get('latestItem')
            temp = Decimal(latest_item.get('temperature'))
            ts = arrow.get(latest_item.get('ts'))

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


@timing
def get_message_from_sheet() -> str:
    sh = InitPygsheets.init_pygsheets()
    cell_value = ''
    cell = config.MESSAGE_SHEET_CELL

    if sh:
        try:
            wks = sh[config.MESSAGE_SHEET_INDEX]
            cell_value = wks.cell(cell).value_unformatted
            if cell_value:
                wks.update_cell(cell, '')

            get_url(config.HEALTHCHECK_URL_MESSAGE)

        except (pygsheets.exceptions.RequestError, ConnectionError):
            pass
        except Exception as e:
            logger.exception(e)
            InitPygsheets.reset_pygsheets()

    return cell_value


@timing
def write_log_to_sheet(command: Command, extra_info: list):
    sh = InitPygsheets.init_pygsheets()
    cell = 'B2'

    msg = '\n'.join([str(command), time_str()] + extra_info)

    if sh:
        try:
            wks = sh[config.MESSAGE_SHEET_INDEX]
            wks.update_cell(cell, msg)
        except (pygsheets.exceptions.RequestError, ConnectionError):
            pass
        except Exception as e:
            logger.exception(e)
            InitPygsheets.reset_pygsheets()


@timing
def get_temp_from_sheet(sheet_title) -> Tuple[Optional[Decimal], Optional[str]]:
    sh = InitPygsheets.init_pygsheets()

    temp, ts = None, None

    if sh:
        try:
            wks = sh.worksheet_by_title(sheet_title)
            ts_and_temp = wks.range('B2:C2')[0]
            if len(ts_and_temp) == 2:
                ts, temp = ts_and_temp
                ts = ts.value
                temp = decimal_round(temp.value_unformatted, 3)
        except pygsheets.exceptions.RequestError as e:
            logger.exception(e)
        except Exception as e:
            logger.exception(e)
            InitPygsheets.reset_pygsheets()

    return temp, ts


def median(data):

    is_list_of_temps = all(d is None or isinstance(d[0], Decimal) and isinstance(d[1], arrow.Arrow) for d in data)

    if not is_list_of_temps:
        list_of_temps = make_tempts_lists_start_same(data)

        temp = [
            median(d)
            for d
            in itertools.zip_longest(*list_of_temps)
        ]
        if temp:
            ts = temp[0][1]
        else:
            ts = None
    else:
        data = filter(lambda x: x is not None, data)
        data = sorted(data, key=lambda r: r[0])
        n = len(data)

        if n == 0:
            temp = None
            ts = None
        elif n % 2 == 1:
            temp, ts = data[n // 2]
        else:
            i = n // 2
            temp = (data[i - 1][0] + data[i][0]) / 2
            secs = abs((data[i - 1][1] - data[i][1]).total_seconds() / 2)
            ts = data[i - 1][1].shift(seconds=secs)

    return temp, ts


def list_items_equal(lst):
    return lst[1:] == lst[:-1]


def make_tempts_lists_start_same(data):
    list_of_temps = list(list(zip(*data))[0])
    list_of_first_timestamps = get_list_of_first_timestamps(list_of_temps)

    while not list_items_equal(list_of_first_timestamps):
        list_index_to_delete_from = min(enumerate(list_of_temps), key=lambda x: x[1][0][1])[0]
        del list_of_temps[list_index_to_delete_from][0]
        list_of_first_timestamps = get_list_of_first_timestamps(list_of_temps)

    return list_of_temps


def get_list_of_first_timestamps(list_of_temps):
    try:
        return [l[0][1] for l in list_of_temps]
    except IndexError:
        return []


def decimal_round(value, decimals=1) -> Optional[Decimal]:
    if value is None:
        return None

    if not isinstance(value, Decimal):
        value = Decimal(value)

    if decimals > 0:
        rounder = '.' + ('0' * (decimals - 1)) + '1'
    else:
        rounder = '1'

    return value.quantize(Decimal(rounder), rounding=ROUND_HALF_UP)


def have_valid_time(wait_time=30) -> bool:
    logger.info('Waiting valid time')

    if 'windows' in platform.system().lower():
        logger.info('Got valid time')
        return True

    sleep_time = 10

    for i in range(max(int(wait_time / sleep_time), 1)):
        if i > 0:
            # Sleep only between reads
            time.sleep(sleep_time)

        if os.system("(ntpq -pn | egrep '^\*') >/dev/null 2>&1") == 0:
            logger.info('Got valid time')
            return True

    logger.info('Did not get valid time')
    return False
