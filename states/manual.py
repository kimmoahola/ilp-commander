# coding=utf-8
from poller_helpers import Commands, send_ir_signal
from states import State


class Manual(State):
    def run(self, payload):
        command = None
        if payload['command'] == 'turn off':
            command = Commands.off
        elif payload['command'] == 'set temp':
            command = getattr(Commands, 'heat%d' % payload['param'])

        if command:
            send_ir_signal(command)

        # TODO: lähetä maili, että mitä tehtiin?

    def nex(self, payload):
        from states.wait_message_manual import WaitMessageManual

        return WaitMessageManual
