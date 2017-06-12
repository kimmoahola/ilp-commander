from poller_helpers import get_most_recent_message
from states import State


class WaitMessageManual(State):
    def run(self, payload):
        return get_most_recent_message()

    def nex(self, payload):
        from states.auto import Auto
        from states.manual import Manual

        if payload['command'] == 'auto':
            return Auto
        else:
            return Manual
