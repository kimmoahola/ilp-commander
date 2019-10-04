from decimal import Decimal

import arrow

from poller_helpers import Commands, TempTs
from states.auto_pipeline_pipes.get_next_command import command_without_inside_temp, get_next_command


def test_get_next_command():
    assert get_next_command(
        have_valid_time=True, inside_temp=Decimal(5),
        outside_temp_ts=TempTs(temp=Decimal(3), ts=arrow.now()), valid_outside=True,
        target_inside_temp=Decimal(5), controller_output=Decimal('0.1')) == {'next_command': Commands.heat8}
    assert get_next_command(
        have_valid_time=True, inside_temp=Decimal(5),
        outside_temp_ts=TempTs(temp=Decimal(3), ts=arrow.now()), valid_outside=True,
        target_inside_temp=Decimal(5), controller_output=Decimal('1.1')) == {'next_command': Commands.heat24}
    assert get_next_command(
        have_valid_time=False, inside_temp=Decimal(5),
        outside_temp_ts=TempTs(temp=Decimal(3), ts=arrow.now()), valid_outside=False,
        target_inside_temp=Decimal(15), controller_output=Decimal('1.1')) == {'next_command': Commands.heat24}
    assert get_next_command(
        have_valid_time=False, inside_temp=None,
        outside_temp_ts=TempTs(temp=Decimal(3), ts=arrow.now()), valid_outside=False,
        target_inside_temp=Decimal(15), controller_output=Decimal('1.1')) == {'next_command': Commands.heat16}
    assert get_next_command(
        have_valid_time=False, inside_temp=None,
        outside_temp_ts=TempTs(temp=Decimal(-5), ts=arrow.now()), valid_outside=True,
        target_inside_temp=Decimal(10), controller_output=Decimal('1.1')) == {'next_command': Commands.heat20}


def test_command_without_inside_temp():
    assert command_without_inside_temp(Decimal(1), Decimal(5)) == Commands.heat8
    assert command_without_inside_temp(Decimal(-4), Decimal(5)) == Commands.heat16
    assert command_without_inside_temp(Decimal(-5), Decimal(15)) == Commands.heat22
