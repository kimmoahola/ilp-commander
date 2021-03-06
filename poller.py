# coding=utf-8
from poller_helpers import logger, have_valid_time
from states.read_last_message_from_db import ReadLastMessageFromDB


def run():
    have_valid_time(5 * 60)

    state_klass = ReadLastMessageFromDB
    payload = None

    while True:
        state = state_klass()
        payload = state.run(payload)
        last_state_klass = state_klass
        state_klass = state.nex(payload)
        logger.info('State %s -> %s. Payload: %s', last_state_klass.__name__, state_klass.__name__, payload)


if __name__ == '__main__':
    run()
