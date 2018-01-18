# coding=utf-8
import json
import logging
import os
import smtplib
import time
from decimal import Decimal, ROUND_HALF_UP
from email.mime.text import MIMEText
from functools import wraps
from subprocess import Popen, PIPE
from typing import NamedTuple, List

import arrow
import itertools
import pygsheets
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


class Commands:
    off = 'off'
    heat8 = 'heat_8__swing_auto'
    heat10 = 'heat_10__swing_auto'
    heat16 = 'heat_16__fan_auto__swing_auto'
    heat18 = 'heat_18__fan_auto__swing_auto'
    heat20 = 'heat_20__fan_auto__swing_auto'
    heat22 = 'heat_22__fan_auto__swing_auto'
    heat24 = 'heat_24__fan_auto__swing_auto'
    heat26 = 'heat_26__fan_auto__swing_auto'
    heat28 = 'heat_28__fan_auto__swing_auto'
    heat30 = 'heat_30__fan_auto__swing_auto'

    @staticmethod
    def find_command_just_above_temp(temp: Decimal):
        if temp >= 28:
            return Commands.heat30
        if temp >= 26:
            return Commands.heat28
        if temp >= 24:
            return Commands.heat26
        if temp >= 22:
            return Commands.heat24
        if temp >= 20:
            return Commands.heat22
        if temp >= 18:
            return Commands.heat20
        if temp >= 16:
            return Commands.heat18
        if temp >= 10:
            return Commands.heat16
        if temp >= 8:
            return Commands.heat10

        return Commands.heat8

    @staticmethod
    def find_command_at_or_just_below_temp(temp: Decimal):
        if temp < 8:
            return Commands.off
        if temp < 10:
            return Commands.heat8
        if temp < 16:
            return Commands.heat10
        if temp < 18:
            return Commands.heat16
        if temp < 20:
            return Commands.heat18
        if temp < 22:
            return Commands.heat20
        if temp < 24:
            return Commands.heat22
        if temp < 26:
            return Commands.heat24
        if temp < 28:
            return Commands.heat26
        if temp < 30:
            return Commands.heat28

        return Commands.heat30


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


with db.set_perms_for(CommandLog):
    orm.perm('view', group='anybody')


with db.set_perms_for(IRSendLog):
    orm.perm('view', group='anybody')


db.bind('sqlite', 'db.sqlite', create_db=True)
db.generate_mapping(create_tables=True)


@retry(tries=6, delay=3)
def send_email(address, mime_text):
    s = smtplib.SMTP('localhost')
    s.sendmail(address, [address], mime_text.as_string())
    s.quit()


def email(addresses, subject, message):

    for address in addresses:

        mime_text = MIMEText(message.encode('utf-8'), 'plain', 'utf-8')
        mime_text['Subject'] = subject
        mime_text['From'] = address
        mime_text['To'] = address

        try:
            send_email(address, mime_text)
        except Exception as e:
            logger.exception(e)


def send_ir_signal(command: str, extra_info: list = None):
    if extra_info is None:
        extra_info = []

    logger.info(command)

    message = '\n'.join(extra_info)

    try:
        actually_send_ir_signal(command)
    except IOError as e:
        logger.exception(e)
        message += '\nirsend: %s' % type(e).__name__

    email(
        config.EMAIL_ADDRESSES,
        'Send IR',
        'Send IR %s at %s\n%s' % (command, time_str(), message))


def time_str(from_str=None):
    if from_str:
        a = arrow.get(from_str)
    else:
        a = arrow.utcnow()

    return a.to(config.TIMEZONE).format('DD.MM.YYYY HH:mm')


@retry(tries=2, delay=5)
def actually_send_ir_signal(command: str):
    try:
        p = Popen(['irsend', 'SEND_ONCE', 'ilp', command], stdin=PIPE, stdout=PIPE, stderr=PIPE)
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
            IRSendLog(command=command)


def timing(f):
    @wraps(f)
    def timing_wrap(*args, **kw):
        ts = time.time()
        result = f(*args, **kw)
        te = time.time()
        logger.debug('func:%r args:[%r, %r] took: %2.4f sec' % (f.__name__, args, kw, te-ts))
        return result
    return timing_wrap


def get_most_recent_message(once=False):

    logger.info('Start polling messages')

    while True:
        most_recent_message = get_message_from_sheet()

        if most_recent_message:
            break
        else:
            sleep_time = 60 * 10
            logger.info('Sleeping %d %s', sleep_time, 'secs')
            time.sleep(sleep_time)

        if once:
            most_recent_message = get_message_from_sheet()
            break

    if most_recent_message:
        message_dict = json.loads(most_recent_message)

        with orm.db_session:
            param = message_dict['param']
            if param is None:
                param = ''
            else:
                param = json.dumps(param)

            CommandLog(command=message_dict['command'], param=param)
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
def get_url(url):
    return requests.get(url, timeout=60)


@timing
def get_message_from_sheet():
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
def write_log_to_sheet(next_command, extra_info):
    sh = InitPygsheets.init_pygsheets()
    cell = 'B1'

    msg = '\n'.join([next_command, time_str()] + extra_info)

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
def get_temp_from_sheet(sheet_index):
    sh = InitPygsheets.init_pygsheets()

    temp, ts = None, None

    if sh:
        try:
            wks = sh[sheet_index]
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


def decimal_round(value, decimals=1):
    if value is None:
        return None

    if not isinstance(value, Decimal):
        value = Decimal(value)

    if decimals > 0:
        rounder = '.' + ('0' * (decimals - 1)) + '1'
    else:
        rounder = '1'

    return value.quantize(Decimal(rounder), rounding=ROUND_HALF_UP)


def log_temp_info(minimum_inside_temp):
    from states.auto import Auto, target_inside_temperature, get_buffer

    seen_off = None
    warn_off = False

    for outside_temp in range(-30, int(minimum_inside_temp + 2), 1):
        outside_temp_ts = TempTs(Decimal(outside_temp), arrow.now())

        target_inside_temp = target_inside_temperature(
            outside_temp_ts, config.ALLOWED_MINIMUM_INSIDE_TEMP, minimum_inside_temp, None)

        buffer = get_buffer(target_inside_temp, outside_temp_ts, config.ALLOWED_MINIMUM_INSIDE_TEMP, None)

        hysteresis = Auto.hysteresis(outside_temp_ts.temp, target_inside_temp)

        target_inside_temp_correction = target_inside_temp

        command1 = Auto.version_2_next_command(
            hysteresis - Decimal('0.01'), outside_temp, hysteresis, target_inside_temp_correction)
        command2 = Auto.version_2_next_command(
            target_inside_temp + Decimal('0.01'), outside_temp, target_inside_temp, target_inside_temp_correction)

        if seen_off and command2 != Commands.off:
            warn_off = True

        if seen_off is None and command2 == Commands.off:
            seen_off = outside_temp

        logger.info(
            'Target inside is %5.2f (hysteresis %5.2f) when outside is %5.1f. '
            'Buffer %s h. When below target temp -> %s until hysteresis reached %s',
            target_inside_temp,
            hysteresis,
            outside_temp,
            buffer,
            command1,
            command2)

    if warn_off:
        logger.warning('Will turn off when outside is %5.1f.', seen_off)


def have_valid_time(wait_time=30):

    sleep_time = 10

    for i in range(max(int(wait_time / sleep_time), 1)):
        if i > 0:
            # Sleep only between reads
            time.sleep(sleep_time)

        if os.system("(ntpq -pn | egrep '^\*') >/dev/null 2>&1") == 0:
            return True

    return False
