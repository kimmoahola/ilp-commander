import time
from datetime import timedelta
from decimal import Decimal

from freezegun import freeze_time

from poller_helpers import Commands
from states.auto_pipeline_pipes.general import send_command


def test_send_command_on_start(mocker):
    mock_send = mocker.patch('poller_helpers.actually_send_ir_signal')
    mock_email = mocker.patch('poller_helpers.email')

    assert send_command(
        persistent_data={},
        next_command=Commands.off,
        error=Decimal('0.1'),
        extra_info=[])[1]['last_command'] == Commands.off

    mock_send.assert_called_with(Commands.off)
    assert mock_email.call_count == 1

    assert send_command(
        persistent_data={},
        next_command=Commands.heat8,
        error=Decimal('0.1'),
        extra_info=[])[1]['last_command'] == Commands.heat8

    assert mock_send.call_count == 2
    assert mock_email.call_count == 2


def test_send_command_after_first(mocker):
    mock_send = mocker.patch('poller_helpers.actually_send_ir_signal')
    mock_email = mocker.patch('poller_helpers.email')

    assert send_command(
        persistent_data={'last_command': Commands.off},
        next_command=Commands.off,
        error=Decimal('0.1'),
        extra_info=[])[1]['last_command'] == Commands.off

    assert mock_send.call_count == 0
    assert mock_email.call_count == 0

    assert send_command(
        persistent_data={'last_command': Commands.off},
        next_command=Commands.heat8,
        error=Decimal('0.1'),
        extra_info=[])[1]['last_command'] == Commands.heat8

    assert mock_send.call_count == 1
    mock_send.assert_called_with(Commands.heat8)
    assert mock_email.call_count == 1

    assert send_command(
        persistent_data={'last_command': Commands.heat8},
        next_command=Commands.off,
        error=Decimal('0.1'),
        extra_info=[])[1]['last_command'] == Commands.heat8

    assert mock_send.call_count == 1
    assert mock_email.call_count == 1

    assert send_command(
        persistent_data={'last_command': Commands.heat8},
        next_command=Commands.heat10,
        error=Decimal(0),
        extra_info=[])[1]['last_command'] == Commands.heat10

    assert mock_send.call_count == 2
    mock_send.assert_called_with(Commands.heat10)
    assert mock_email.call_count == 1

    assert send_command(
        persistent_data={'last_command': Commands.heat10},
        next_command=Commands.heat10,
        error=Decimal(0),
        extra_info=[])[1]['last_command'] == Commands.heat10

    assert mock_send.call_count == 2
    assert mock_email.call_count == 1

    heating_start_time = time.time()

    with freeze_time(timedelta(minutes=46)):
        assert send_command(
            persistent_data={'last_command': Commands.heat8, 'heating_start_time': heating_start_time},
            next_command=Commands.off,
            error=Decimal('-0.1'),
            extra_info=[])[1]['last_command'] == Commands.off

    assert mock_send.call_count == 3
    mock_send.assert_called_with(Commands.off)
    assert mock_email.call_count == 2


def test_send_command_min_time_heating(mocker):
    mock_send = mocker.patch('poller_helpers.actually_send_ir_signal')
    mock_email = mocker.patch('poller_helpers.email')

    persistent_data = {'last_command': Commands.off}

    state, new_persistent_data = send_command(
        persistent_data=persistent_data,
        next_command=Commands.heat22,
        error=Decimal('0.1'),
        extra_info=[])

    assert new_persistent_data['last_command'] == Commands.heat22
    assert mock_send.call_count == 1
    mock_send.assert_called_with(Commands.heat22)
    assert mock_email.call_count == 1

    persistent_data.update(new_persistent_data)

    state, new_persistent_data = send_command(
        persistent_data=persistent_data,
        next_command=Commands.off,
        error=Decimal('-0.1'),
        extra_info=[])

    assert new_persistent_data['last_command'] == Commands.heat22
    assert mock_send.call_count == 1
    assert mock_email.call_count == 1

    persistent_data.update(new_persistent_data)

    with freeze_time(timedelta(minutes=46)):
        state, new_persistent_data = send_command(
            persistent_data=persistent_data,
            next_command=Commands.off,
            error=Decimal('-0.1'),
            extra_info=[])

    assert new_persistent_data['last_command'] == Commands.off
    assert mock_send.call_count == 2
    mock_send.assert_called_with(Commands.off)
    assert mock_email.call_count == 2


def test_send_command_error_none(mocker):
    mock_send = mocker.patch('poller_helpers.actually_send_ir_signal')
    mock_email = mocker.patch('poller_helpers.email')

    state, new_persistent_data = send_command(
        persistent_data={'last_command': Commands.off},
        next_command=Commands.heat22,
        error=None,
        extra_info=[])

    assert new_persistent_data['last_command'] == Commands.heat22
    assert mock_send.call_count == 1
    mock_send.assert_called_with(Commands.heat22)
    assert mock_email.call_count == 1
