# coding=utf-8
import json
import logging
from subprocess import Popen, PIPE

import arrow
import boto3
from botocore.exceptions import BotoCoreError
from pony import orm

import config

logger = logging.getLogger('poller')
handler = logging.FileHandler('poller.log')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(funcName)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
logger.info('----- START -----')


class Commands(object):
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


boto_session = boto3.Session(
    aws_access_key_id=config.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
)

sqs = boto_session.resource('sqs', region_name=config.AWS_REGION_NAME)

queue = sqs.get_queue_by_name(QueueName=config.AWS_SQS_QUEUE_NAME)


def send_ir_signal(command):
    logger.info(command)
    actually_send_ir_signal(command)
    time.sleep(5)
    actually_send_ir_signal(command)
    time.sleep(5)
    actually_send_ir_signal(command)


def actually_send_ir_signal(command):
    try:
        p = Popen(['irsend', 'SEND_ONCE', 'ilp', command], stdin=PIPE, stdout=PIPE, stderr=PIPE)
        output, err = p.communicate('')
        if p.returncode != 0:
            logger.error('%d: %s - %s', p.returncode, output, err)
    except Exception as e:
        logger.exception(e)


from functools import wraps
import time


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

    WAIT_TIME_MAX = 20

    most_recent_message = None

    while True:
        if most_recent_message:
            wait_time = 1
        else:
            wait_time = WAIT_TIME_MAX

        messages = receive_messages(wait_time)

        if not messages and most_recent_message:
            break

        for message in messages:

            if most_recent_message:
                if int(message.attributes['SentTimestamp']) > int(most_recent_message.attributes['SentTimestamp']):
                    most_recent_message = message
            else:
                most_recent_message = message

            message.delete()

        if not messages:
            sleep_time = 60
            logger.info('Sleeping %d %s', sleep_time, 'secs')
            time.sleep(sleep_time)  # Avoid continuously polling SQS to save bandwidth

        if once:
            break

    if most_recent_message:
        message_dict = json.loads(most_recent_message.body)

        with orm.db_session:
            param = message_dict['param']
            if param is None:
                param = ''

            CommandLog(command=message_dict['command'], param=str(param))
    else:
        message_dict = {}

    return message_dict


@timing
def receive_messages(wait_time):
    try:
        messages = queue.receive_messages(
            WaitTimeSeconds=wait_time, MaxNumberOfMessages=10, AttributeNames=['SentTimestamp'])
        logger.info('receive_messages: got %d messages' % len(messages))
    except BotoCoreError as e:
        logger.warn('receive_messages: %s', e)
        messages = []
    return messages
