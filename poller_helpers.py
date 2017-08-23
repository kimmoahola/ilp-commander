# coding=utf-8
import json
import logging
import smtplib
import time
from decimal import Decimal
from email.mime.text import MIMEText
from functools import wraps
from subprocess import Popen, PIPE

import arrow
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


db = orm.Database()


class CommandLog(db.Entity):
    command = orm.Required(str)
    param = orm.Optional(str, default='')

    # Use str here because pony uses str() to convert datetime before insert.
    # That puts datetime in wrong format to DB.
    ts = orm.Required(str, default=lambda: arrow.utcnow().isoformat())

    def ts_local(self):
        return arrow.get(self.ts).to(config.TIMEZONE)


with db.set_perms_for(CommandLog):
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
    actually_send_ir_signal(command)

    message = '\n'.join(extra_info)

    email(
        config.EMAIL_ADDRESSES,
        'Send IR %s' % command,
        'Send IR %s at %s\n%s' % (command, arrow.now().format('DD.MM.YYYY HH:mm'), message))


def actually_send_ir_signal(command: str):
    try:
        p = Popen(['irsend', 'SEND_ONCE', 'ilp', command], stdin=PIPE, stdout=PIPE, stderr=PIPE)
        output, err = p.communicate('')
        if p.returncode != 0:
            logger.error('%d: %s - %s', p.returncode, output, err)
    except Exception as e:
        logger.exception(e)


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
            break

    if most_recent_message:
        message_dict = json.loads(most_recent_message)

        with orm.db_session:
            param = message_dict['param']
            if param is None:
                param = ''

            CommandLog(command=message_dict['command'], param=str(param))
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
            outh_nonlocal=True)
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
def get_temp_from_sheet(sheet_index):
    sh = InitPygsheets.init_pygsheets()

    temp, ts = None, None

    if sh:
        try:
            wks = sh[sheet_index]
            ts_and_temp = wks.range('B2:C2')[0]
            if len(ts_and_temp) == 2:
                ts, temp = ts_and_temp
                ts = ts.value_unformatted
                temp = temp.value_unformatted
        except pygsheets.exceptions.RequestError as e:
            logger.exception(e)
        except Exception as e:
            logger.exception(e)
            InitPygsheets.reset_pygsheets()

    return temp, ts


def median(data):
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
