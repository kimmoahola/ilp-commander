from decimal import Decimal
from typing import Optional

import arrow

import neural
from poller_helpers import Commands, TempTs


def temp_control_without_inside_temp(outside_temp: Decimal, target_inside_temp: Decimal) -> Decimal:
    diff = abs(outside_temp - target_inside_temp)
    control = Decimal(3) + diff * diff * Decimal('0.03') + diff * Decimal('0.2')
    return max(min(control, Decimal(24)), Decimal(8))


def get_next_command(have_valid_time: bool,
                     inside_temp: Optional[Decimal],
                     outside_temp_ts: TempTs,
                     valid_outside: bool,
                     target_inside_temp: Decimal,
                     error: Decimal,
                     add_extra_info,
                     persistent_data,
                     **kwargs):

    if inside_temp is not None:
        neural_network = persistent_data.get('neural_network')

        error_slope = 0
        inp = [float(target_inside_temp), float(error), float(error_slope),
               float(outside_temp_ts.temp if valid_outside else 0)]
        next_command = neural.predict(neural_network, inp)
        add_extra_info('predicted {} -> {}'.format(inp, next_command))
    else:
        is_summer = have_valid_time and 5 <= arrow.now().month <= 9

        if valid_outside and outside_temp_ts.temp < target_inside_temp or not valid_outside and not is_summer:
            control_without_inside = temp_control_without_inside_temp(outside_temp_ts.temp, target_inside_temp)
            next_command = Commands.command_from_controller(control_without_inside)
        else:
            next_command = Commands.off

    return {'next_command': next_command}
