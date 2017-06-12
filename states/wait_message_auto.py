from poller_helpers import get_most_recent_message
from states import State


class WaitMessageAuto(State):
    def run(self, payload):
        return get_most_recent_message(once=True)

    def nex(self, payload):
        from states.auto import Auto
        from states.manual import Manual

        if payload:
            if payload['command'] == 'auto':
                return Auto
            else:
                Auto.last_command = None  # Clear last command so Auto sends command after Manual
                return Manual
        else:
            return Auto
