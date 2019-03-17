import json
from json import JSONDecodeError

from pony import orm

from poller_helpers import CommandLog
from states import State


class ReadLastMessageFromDB(State):
    def run(self, payload):
        with orm.db_session:
            first = orm.select(c for c in CommandLog).order_by(orm.desc(CommandLog.ts)).first()
            if first:
                as_dict = first.to_dict()
                try:
                    as_dict['param'] = json.loads(as_dict['param'])
                except JSONDecodeError:
                    pass
                return as_dict
            else:
                return {}

    def nex(self, payload):
        if payload and payload['command'] == 'auto':
            from states.auto_pipeline import AutoPipeline
            return AutoPipeline
        else:
            from states.manual import Manual
            return Manual
