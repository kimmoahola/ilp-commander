# coding=utf-8
from poller_helpers import Commands, send_ir_signal, write_log_to_sheet
from states import State


class Manual(State):
    def run(self, payload):
        command = None
        if payload['command'] == 'turn off':
            command = Commands.off
        elif payload['command'] == 'set temp':
            command = getattr(Commands, 'heat%d' % int(payload['param']['temp']))

        if command:
            send_ir_signal(command)
            write_log_to_sheet(command, extra_info=[])

    def nex(self, payload):
        from states.wait_message_manual import WaitMessageManual

        return WaitMessageManual
