from poller_helpers import get_most_recent_message
from states import State


class WaitMessageManual(State):
    def run(self, payload):
        return get_most_recent_message()

    def nex(self, payload):
        from states.auto_pipeline import AutoPipeline
        from states.manual import Manual

        if payload['command'] == 'auto':
            return AutoPipeline
        else:
            return Manual
