from decimal import Decimal
from typing import Optional

import arrow

from poller_helpers import Commands, TempTs, Command


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

        if valid_outside and outside_temp_ts.temp < target_inside_temp:
            next_command = command_without_inside_temp(outside_temp_ts.temp, target_inside_temp)
        elif not valid_outside and not is_summer:
            next_command = Commands.heat16
        else:
            next_command = Commands.off

    return {'next_command': next_command}


def command_without_inside_temp(outside_temp: Decimal, target_inside_temp: Decimal) -> Command:

    diff = target_inside_temp - outside_temp

    margin_to_add = diff * Decimal('0.625')

    list_of_commands = [
        Commands.heat8,
        Commands.heat10,
        Commands.heat16,
        Commands.heat18,
        Commands.heat20,
        Commands.heat22,
    ]

    for c in list_of_commands:
        if c.temp > target_inside_temp + margin_to_add:
            return c

    return list_of_commands[-1]
