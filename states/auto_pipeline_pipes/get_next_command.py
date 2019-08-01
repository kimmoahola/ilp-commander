from decimal import Decimal
from typing import Optional

import arrow

from poller_helpers import Commands, TempTs


def get_next_command(have_valid_time: bool,
                     inside_temp: Optional[Decimal],
                     outside_temp_ts: TempTs,
                     valid_outside: bool,
                     target_inside_temp: Decimal,
                     controller_output: Decimal,
                     **kwargs):

    if inside_temp is not None:
        next_command = Commands.command_from_controller(controller_output, inside_temp, valid_outside and outside_temp_ts.temp)
    else:
        is_summer = have_valid_time and 5 <= arrow.now().month <= 9

        if valid_outside and outside_temp_ts.temp < target_inside_temp or not valid_outside and not is_summer:
            next_command = Commands.heat22
        else:
            next_command = Commands.off

    return {'next_command': next_command}
