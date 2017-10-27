# coding=utf-8

from poller_helpers import logger, log_temp_info
from states.read_last_message_from_db import ReadLastMessageFromDB


def run():
    state_klass = ReadLastMessageFromDB
    payload = None

    log_temp_info()

    while True:
        state = state_klass()
        payload = state.run(payload)
        last_state_klass = state_klass
        state_klass = state.nex(payload)
        logger.info('State %s -> %s. Payload: %s', last_state_klass.__name__, state_klass.__name__, payload)


if __name__ == '__main__':
    run()
