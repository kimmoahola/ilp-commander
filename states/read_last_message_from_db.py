from pony import orm

from poller_helpers import CommandLog
from states import State


class ReadLastMessageFromDB(State):
    def run(self, payload):
        with orm.db_session:
            first = orm.select(c for c in CommandLog).order_by(orm.desc(CommandLog.ts)).first()
            if first:
                return first.to_dict()
            else:
                return {}

    def nex(self, payload):
        if payload and payload['command'] == 'auto':
            from states.auto import Auto
            return Auto
        else:
            from states.manual import Manual
            return Manual
