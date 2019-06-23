# coding=utf-8

from poller_helpers import get_most_recent_message, have_valid_time, logger
from states import State
from states.auto_pipeline_pipes.adjust_target_with_rh import adjust_target_with_rh
from states.auto_pipeline_pipes import general
from states.auto_pipeline_pipes.get_error import get_error
from states.auto_pipeline_pipes.get_forecast import get_forecast
from states.auto_pipeline_pipes.get_inside import get_inside
from states.auto_pipeline_pipes.get_next_command import get_next_command
from states.auto_pipeline_pipes.get_outside import get_outside
from states.auto_pipeline_pipes.get_target_inside_temperature import target_inside_temp
from states.auto_pipeline_pipes.send_status_mail import send_status_mail


class AutoPipeline(State):
    persistent_data = {}

    def run(self, payload):

        pipeline = [
            general.get_neural_network,
            general.get_controller,
            general.handle_payload,
            lambda **kwargs: {'have_valid_time': have_valid_time()},
            general.get_add_extra_info,
            get_forecast,
            get_outside,
            target_inside_temp,
            adjust_target_with_rh,
            general.hysteresis,
            get_inside,
            get_error,
            general.update_controller,
            get_next_command,
            send_status_mail,
            general.send_command,
            general.write_log,
            general.save_controller_state,
        ]

        data = {'payload': payload}

        for pipe in pipeline:
            logger.info('Calling %s', pipe)
            result = pipe(persistent_data=AutoPipeline.persistent_data, **data)
            logger.info('Call result %s: %s', pipe, result)

            if result:
                if isinstance(result, tuple):
                    new_data, new_persistent_data = result
                else:
                    new_data, new_persistent_data = result, {}

                data.update(new_data)
                AutoPipeline.persistent_data.update(new_persistent_data)

        return get_most_recent_message(once=True)

    def nex(self, payload):
        from states.manual import Manual

        if payload:
            if payload['command'] == 'auto':
                return AutoPipeline
            else:
                AutoPipeline.persistent_data = {}
                return Manual
        else:
            return AutoPipeline
