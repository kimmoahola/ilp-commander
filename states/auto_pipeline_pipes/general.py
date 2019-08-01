# coding=utf-8
import json
import time
from decimal import Decimal
from json import JSONDecodeError

from pony import orm

import config
from poller_helpers import Commands, send_ir_signal, write_log_to_sheet, SavedState, logger, decimal_round
from states.controller import Controller


def send_command(persistent_data, next_command, extra_info, **kwargs):
    now = time.time()

    heating_start_time = persistent_data.get('heating_start_time', now)
    last_command = persistent_data.get('last_command')

    seconds_since_heating_start = now - heating_start_time

    if last_command is not None and last_command != Commands.off:
        logger.debug('Heating started %d hours ago', seconds_since_heating_start / 3600.0)

    min_time_heating = 60 * 60 * 3

    if last_command is None or \
            (next_command != last_command and (
                next_command != Commands.off or
                next_command == Commands.off and seconds_since_heating_start > min_time_heating)):

        if (last_command is None or last_command == Commands.off) and next_command != Commands.off:
            # From off to heating
            heating_start_time = now

        last_command = next_command
        send_ir_signal(next_command, extra_info=extra_info)

    extra_info.append('Actual last command: %s' % last_command)
    logger.info('Actual last command: %s' % last_command)

    return {'extra_info': extra_info}, {'last_command': last_command, 'heating_start_time': heating_start_time}


def write_log(next_command, extra_info, **kwargs):
    write_log_to_sheet(next_command, extra_info)


def get_controller(persistent_data, **kwargs):
    if 'controller' in persistent_data:
        controller = persistent_data['controller']
    else:
        controller = Controller(config.CONTROLLER_P, config.CONTROLLER_I, config.CONTROLLER_D)

    if controller.is_reset():
        with orm.db_session:
            # noinspection PyTypeChecker
            saved_state = orm.select(c for c in SavedState).where(name='Auto.controller').first()
            if saved_state:
                as_dict = saved_state.to_dict()
                try:
                    as_dict['json'] = json.loads(as_dict['json'])
                except JSONDecodeError:
                    pass
                else:
                    controller.integral = Decimal(as_dict['json']['integral'])

    return {}, {'controller': controller}


def handle_payload(payload, persistent_data, **kwargs):
    if payload:

        # Reset controller D term because otherwise after changing target the slope would be big
        persistent_data['controller'].reset_past_errors()

        if payload.get('param') and payload.get('param').get('min_inside_temp') is not None:
            minimum_inside_temp = Decimal(payload.get('param').get('min_inside_temp'))
        else:
            minimum_inside_temp = config.MINIMUM_INSIDE_TEMP

        return {}, {'minimum_inside_temp': minimum_inside_temp}

    elif 'minimum_inside_temp' not in persistent_data:
        minimum_inside_temp = config.MINIMUM_INSIDE_TEMP
        return {}, {'minimum_inside_temp': minimum_inside_temp}

    else:
        return None


def get_add_extra_info(**kwargs):
    extra_info = []

    def add_extra_info(message):
        logger.info(message)
        extra_info.append(message)

    return {'add_extra_info': add_extra_info, 'extra_info': extra_info}


def hysteresis(add_extra_info, target_inside_temp, **kwargs):
    hyst = Decimal('0.5')
    add_extra_info('Hysteresis: %s (%s)' % (decimal_round(hyst), decimal_round(target_inside_temp + hyst)))
    return {'hysteresis': hyst}


def update_controller(add_extra_info, error, error_without_hysteresis, persistent_data, **kwargs):
    controller = persistent_data.get('controller')
    degrees_per_hour_slope = Decimal('0.05')

    lowest_heating_value = Decimal(0) - Decimal('0.01')
    highest_heating_value = Decimal(1) + Decimal('0.01')

    controller.set_i_low_limit(lowest_heating_value - degrees_per_hour_slope * controller.kd)
    controller.set_i_high_limit(highest_heating_value + degrees_per_hour_slope * controller.kd)

    controller_output, controller_log = controller.update(error, error_without_hysteresis)

    add_extra_info('Controller: %s (%s)' % (decimal_round(controller_output, 2), controller_log))

    return {'controller_output': controller_output}


def save_controller_state(persistent_data, **kwargs):
    controller = persistent_data.get('controller')
    data = json.dumps({'integral': str(controller.integral)})
    with orm.db_session:
        # noinspection PyTypeChecker
        saved_state = orm.select(c for c in SavedState).where(name='Auto.controller').first()
        if saved_state:
            saved_state.set(json=data)
        else:
            SavedState(name='Auto.controller', json=data)
