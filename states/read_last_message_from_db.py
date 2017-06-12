from pony import orm

from poller_helpers import CommandLog
from states import State


class ReadLastMessageFromDB(State):
    def run(self, payload):
        with orm.db_session:
            return orm.select(c for c in CommandLog).order_by(orm.desc(CommandLog.ts)).first().to_dict()

    def nex(self, payload):
        from states.auto import Auto
        from states.wait_message_manual import WaitMessageManual

        if payload['command'] == 'auto':
            return Auto
        else:
            return WaitMessageManual
