# coding=utf-8

from poller_helpers import logger
from states.read_last_message_from_db import ReadLastMessageFromDB

try:
    import serial
except ImportError:
    serial = {}

# last_command = None
#
# while True:
#
#     begin = time.time()
#
#     try:
#
#         if last_command:
#             params = {'after_ts': last_command['ts']}
#         else:
#             params = None
#
#         print 'begin connection'
#         response = requests.get('http://localhost:5000/command_queue', params=params, timeout=(3.05, 600))
#         print 'response', response
#
#         # noinspection PyBroadException
#         try:
#             last_command = response.json()
#             print last_command
#
#             if last_command['command'] == 'auto':
#                 print 'auto', '-' * 10
#             else:
#                 print 'run command', last_command['command'], last_command['param']
#         except:
#             pass
#
#     except requests.exceptions.RequestException as e:
#         print e
#         pass
#
#     end = time.time()
#     print 'time', end-begin
#
#     print 'sleeping...'
#     print
#     time.sleep(10)


def run():
    state_klass = ReadLastMessageFromDB
    payload = None

    while True:
        state = state_klass()
        logger.info('State %s run', state.__class__.__name__)
        logger.debug('State %s payload in: %s', state.__class__.__name__, payload)
        payload = state.run(payload)
        logger.debug('State %s payload out: %s', state.__class__.__name__, payload)
        logger.info('State %s nex', state.__class__.__name__)
        state_klass = state.nex(payload)


if __name__ == '__main__':
    run()
