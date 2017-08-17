from decimal import Decimal

import arrow
import pytest

import config
from poller_helpers import Commands, InitPygsheets
from states.auto import receive_yahoo_temperature, receive_ulkoilma_temperature, receive_wc_temperature, \
    receive_fmi_temperature, Temperatures, Auto

MAX_TIME_DIFF_MINUTES = 120


def run_temp_test_for(func):
    temp, ts = func()
    seconds = (arrow.now() - ts).total_seconds()
    assert abs(seconds) < 60 * MAX_TIME_DIFF_MINUTES
    assert -30 < temp < 30


def has_invalid_sheet():
    return not config.SHEET_OAUTH_FILE or not config.SHEET_KEY


def has_invalid_fmi():
    return config.FMI_KEY.startswith('12345678')


def test_receive_yahoo_temperature():
    run_temp_test_for(receive_yahoo_temperature)


@pytest.mark.skipif(has_invalid_sheet(),
                    reason='No sheet OAuth file or key in config')
def test_receive_ulkoilma_temperature():
    run_temp_test_for(receive_ulkoilma_temperature)


@pytest.mark.skipif(has_invalid_sheet(),
                    reason='No sheet OAuth file or key in config')
def test_receive_wc_temperature():
    run_temp_test_for(receive_wc_temperature)


@pytest.mark.skipif(has_invalid_fmi(),
                    reason='No FMI key in config')
def test_receive_fmi_temperature():
    run_temp_test_for(receive_fmi_temperature)


def test_temperatures(mocker):

    if has_invalid_sheet():
        mocker.patch('states.auto_test.receive_ulkoilma_temperature', return_value=(Decimal(3), arrow.now()))

    if has_invalid_fmi():
        mocker.patch('states.auto_test.receive_fmi_temperature', return_value=(Decimal(3), arrow.now()))

    outside_temp = Temperatures.get_temp([
        receive_ulkoilma_temperature, receive_yahoo_temperature, receive_fmi_temperature])

    assert -30 < outside_temp < 30


def test_auto_warm_inside(mocker):
    mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
    mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
    mock_receive_wc_temperature = mocker.patch(
        'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now()))
    mock_receive_ulkoilma_temperature = mocker.patch(
        'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(3), arrow.now()))
    mock_receive_yahoo_temperature = mocker.patch(
        'states.auto.receive_yahoo_temperature', return_value=(Decimal(5), arrow.now()))
    mock_receive_fmi_temperature = mocker.patch(
        'states.auto.receive_fmi_temperature', return_value=(Decimal(7), arrow.now()))

    auto = Auto()
    auto.run({})
    Auto.last_command = None

    mock_send_ir_signal.assert_called_once_with('off', extra_info='Inside temperature: 8')
    mock_get_most_recent_message.assert_called_once_with(once=True)
    mock_receive_wc_temperature.assert_called_once()
    mock_receive_ulkoilma_temperature.assert_not_called()
    mock_receive_yahoo_temperature.assert_not_called()
    mock_receive_fmi_temperature.assert_not_called()


def test_auto_invalid_inside(mocker):
    mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
    mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
    mock_receive_wc_temperature = mocker.patch(
        'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now().shift(minutes=-60)))
    mock_receive_ulkoilma_temperature = mocker.patch(
        'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(3), arrow.now()))
    mock_receive_yahoo_temperature = mocker.patch(
        'states.auto.receive_yahoo_temperature', return_value=(Decimal(5), arrow.now()))
    mock_receive_fmi_temperature = mocker.patch(
        'states.auto.receive_fmi_temperature', return_value=(Decimal(7), arrow.now()))

    auto = Auto()
    auto.run({})
    Auto.last_command = None

    mock_send_ir_signal.assert_called_once_with(
        'off', extra_info='Inside temperature: None  Outside temperature: 5')
    mock_get_most_recent_message.assert_called_once_with(once=True)
    mock_receive_wc_temperature.assert_called_once()
    mock_receive_ulkoilma_temperature.assert_called_once()
    mock_receive_yahoo_temperature.assert_called_once()
    mock_receive_fmi_temperature.assert_called_once()


def test_auto_invalid_all_temperatures(mocker):
    mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
    mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
    mock_receive_wc_temperature = mocker.patch(
        'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now().shift(minutes=-60)))
    mock_receive_ulkoilma_temperature = mocker.patch(
        'states.auto.receive_ulkoilma_temperature', return_value=(None, None))
    mock_receive_yahoo_temperature = mocker.patch(
        'states.auto.receive_yahoo_temperature', return_value=(None, None))
    mock_receive_fmi_temperature = mocker.patch(
        'states.auto.receive_fmi_temperature', return_value=(None, None))

    auto = Auto()
    auto.run({})
    Auto.last_command = None

    mock_send_ir_signal.assert_called_once_with(
        Commands.heat16,
        extra_info='Inside temperature: None  Outside temperature: None  '
                   'Got no temperatures at all. Setting heat_16__fan_auto__swing_auto')
    mock_get_most_recent_message.assert_called_once_with(once=True)
    mock_receive_wc_temperature.assert_called_once()
    mock_receive_ulkoilma_temperature.assert_called_once()
    mock_receive_yahoo_temperature.assert_called_once()
    mock_receive_fmi_temperature.assert_called_once()


def test_auto_cold_inside(mocker):
    mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
    mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
    mock_receive_wc_temperature = mocker.patch(
        'states.auto.receive_wc_temperature', return_value=(Decimal('7.5'), arrow.now().shift(minutes=-30)))
    mock_receive_ulkoilma_temperature = mocker.patch(
        'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(3), arrow.now()))
    mock_receive_yahoo_temperature = mocker.patch(
        'states.auto.receive_yahoo_temperature', return_value=(Decimal(5), arrow.now()))
    mock_receive_fmi_temperature = mocker.patch(
        'states.auto.receive_fmi_temperature', return_value=(Decimal(7), arrow.now()))

    auto = Auto()
    auto.run({})
    Auto.last_command = None

    mock_send_ir_signal.assert_called_once_with(
        'off', extra_info='Inside temperature: 7.5  Outside temperature: 5')
    mock_get_most_recent_message.assert_called_once_with(once=True)
    mock_receive_wc_temperature.assert_called_once()
    mock_receive_ulkoilma_temperature.assert_called_once()
    mock_receive_yahoo_temperature.assert_called_once()
    mock_receive_fmi_temperature.assert_called_once()


def test_auto_cold_inside_and_outside(mocker):
    mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
    mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
    mock_receive_wc_temperature = mocker.patch(
        'states.auto.receive_wc_temperature', return_value=(Decimal('7.5'), arrow.now().shift(minutes=-30)))
    mock_receive_ulkoilma_temperature = mocker.patch(
        'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(-3), arrow.now()))
    mock_receive_yahoo_temperature = mocker.patch(
        'states.auto.receive_yahoo_temperature', return_value=(Decimal(-5), arrow.now()))
    mock_receive_fmi_temperature = mocker.patch(
        'states.auto.receive_fmi_temperature', return_value=(Decimal(-7), arrow.now()))

    auto = Auto()
    auto.run({})
    Auto.last_command = None

    mock_send_ir_signal.assert_called_once_with(
        Commands.heat8, extra_info='Inside temperature: 7.5  Outside temperature: -5')
    mock_get_most_recent_message.assert_called_once_with(once=True)
    mock_receive_wc_temperature.assert_called_once()
    mock_receive_ulkoilma_temperature.assert_called_once()
    mock_receive_yahoo_temperature.assert_called_once()
    mock_receive_fmi_temperature.assert_called_once()


def test_auto_very_cold_inside_and_outside(mocker):
    mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
    mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
    mock_receive_wc_temperature = mocker.patch(
        'states.auto.receive_wc_temperature', return_value=(Decimal(1), arrow.now().shift(minutes=-30)))
    mock_receive_ulkoilma_temperature = mocker.patch(
        'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(-18), arrow.now()))
    mock_receive_yahoo_temperature = mocker.patch(
        'states.auto.receive_yahoo_temperature', return_value=(Decimal(-20), arrow.now()))
    mock_receive_fmi_temperature = mocker.patch(
        'states.auto.receive_fmi_temperature', return_value=(Decimal(-21), arrow.now()))

    auto = Auto()
    auto.run({})
    Auto.last_command = None

    mock_send_ir_signal.assert_called_once_with(
        Commands.heat16, extra_info='Inside temperature: 1  Outside temperature: -20')
    mock_get_most_recent_message.assert_called_once_with(once=True)
    mock_receive_wc_temperature.assert_called_once()
    mock_receive_ulkoilma_temperature.assert_called_once()
    mock_receive_yahoo_temperature.assert_called_once()
    mock_receive_fmi_temperature.assert_called_once()


@pytest.mark.skipif(has_invalid_sheet(),
                    reason='No sheet OAuth file or key in config')
def test_auto_message_wait(mocker):
    mocker.patch('states.auto.send_ir_signal')
    mocker.patch('poller_helpers.get_url')  # mock health check
    mock_time_sleep = mocker.patch('time.sleep')

    auto = Auto()
    payload = auto.run({})
    Auto.last_command = None

    mock_time_sleep.assert_called_once_with(60 * 10)
    assert payload == {}

    mocker.resetall()

    sh = InitPygsheets.init_pygsheets()
    wks = sh[config.MESSAGE_SHEET_INDEX]
    wks.update_cell(config.MESSAGE_SHEET_CELL, '{ "command":"auto", "param":null }')

    mocker.patch('states.auto.send_ir_signal')
    mocker.patch('poller_helpers.get_url')  # mock health check
    mock_time_sleep = mocker.patch('time.sleep')

    auto = Auto()
    payload = auto.run({})
    Auto.last_command = None

    mock_time_sleep.assert_not_called()
    assert payload == {'command': 'auto', 'param': None}
    assert auto.nex(payload) == Auto
