import json
import random
from datetime import datetime
from decimal import Decimal
from unittest.mock import call

import arrow
import pytest
from freezegun import freeze_time

import config
from poller_helpers import Commands, InitPygsheets, TempTs
from states.auto import receive_ulkoilma_temperature, receive_wc_temperature, \
    receive_fmi_temperature, Temperatures, Auto, target_inside_temperature, receive_yr_no_forecast, \
    RequestCache, receive_open_weather_map_temperature, get_buffer

MAX_TIME_DIFF_MINUTES = 120


def assert_almost_equal(first, second, delta=None):
    if delta is None:
        delta = Decimal('0.1')

    if first == Decimal('Infinity') or second == Decimal('Infinity'):
        assert first == second
    else:
        assert abs(first - second) <= delta, '%s != %s within %s delta' % (first, second, delta)


def run_temp_test_for(func, max_ts_diff=None, **kwargs):
    temp, ts = Temperatures.get_temp([func], max_ts_diff=max_ts_diff, **kwargs)
    if temp is not None:
        if isinstance(temp, list):
            for t in temp:
                assert -30 < t[0] < 30
        else:
            assert -30 < temp < 30
    return temp, ts


def has_invalid_sheet():
    return not config.SHEET_OAUTH_FILE or not config.SHEET_KEY


def has_invalid_fmi():
    return not config.FMI_KEY or not config.FMI_LOCATION or config.FMI_KEY.startswith('12345678')


def has_invalid_open_weather_map():
    return not config.OPEN_WEATHER_MAP_KEY or not config.OPEN_WEATHER_MAP_LOCATION


class FakeResponse:
    status_code = 200
    content = ''

    def __init__(self, content):
        self.content = content

    def json(self):
        return json.loads(self.content)


ts_for_forecast = arrow.now().shift(minutes=30)


def forecast_response(forecast):
    start = ts_for_forecast.clone()
    temp = [TempTs(temp=Decimal(f), ts=start.shift(hours=i)) for i, f in enumerate(forecast)]
    ts = arrow.now()
    return temp, ts


def forecast_object(forecast):
    temp, ts = forecast_response(forecast)
    return Auto.make_forecast(temp, ts, True)


def mocker_init(mocker):
    mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
    mocker.patch('states.auto.get_most_recent_message')
    mocker.patch('states.auto.write_log_to_sheet')
    mocker.patch('time.sleep')
    return mock_send_ir_signal


def mock_inside(mocker, temp):
    if temp is not None:
        mocker.patch('states.auto.receive_wc_temperature', return_value=(Decimal(temp), arrow.now().shift(minutes=-59)))
    else:
        mocker.patch('states.auto.receive_wc_temperature', return_value=(Decimal(500), arrow.now().shift(minutes=-60)))


def mock_outside(mocker, temp, forecast_average=None):
    if temp is not None:
        temp = Decimal(temp)
        temps = [temp - 5, temp + 5, None]
        random.shuffle(temps)
    else:
        temps = [None] * 3

    mocker.patch('states.auto.receive_ulkoilma_temperature', return_value=(temps[0], arrow.now().shift(minutes=-30)))
    mocker.patch('states.auto.receive_fmi_temperature', return_value=(temps[1], arrow.now().shift(minutes=-30)))
    mocker.patch('states.auto.receive_open_weather_map_temperature',
                 return_value=(temps[2], arrow.now().shift(minutes=-30)))

    forecast = []

    if forecast_average is None:
        forecast_average = temp

    if forecast_average is not None:
        forecast = [forecast_average - 5, forecast_average + 5] * 24  # 48 hours

    mocker.patch('states.auto.receive_yr_no_forecast', return_value=forecast_response(forecast))
    mocker.patch('states.auto.receive_fmi_forecast', return_value=forecast_response(forecast))


def assert_ir_call(mock_send_ir_signal, command):
    if command:
        mock_send_ir_signal.assert_called_once()
        assert_info = '  '.join(mock_send_ir_signal.call_args[1:][0]['extra_info'])
        assert mock_send_ir_signal.call_args[0][0] == command, assert_info
    else:
        mock_send_ir_signal.assert_not_called()


class TestGeneral:
    @staticmethod
    def setup_method():
        RequestCache.reset()

    def test_receive_ulkoilma_temperature(self, mocker):
        mocker.patch('states.auto.get_url')  # mock requests
        run_temp_test_for(receive_ulkoilma_temperature)

    def test_receive_ulkoilma_temperature_2(self, mocker):
        mocker.patch('states.auto.get_url',
                     return_value=FakeResponse('{"id":118143,"ts":"2017-10-01T16:20:26+00:00","temperature":"8.187"}'))
        temp, ts = receive_ulkoilma_temperature()
        assert temp == Decimal('8.187')
        assert ts == arrow.get('"2017-10-01T16:20:26+00:00')

    @pytest.mark.skipif(has_invalid_sheet(),
                        reason='No sheet OAuth file or key in config')
    def test_receive_wc_temperature(self):
        run_temp_test_for(receive_wc_temperature)

    @pytest.mark.skipif(has_invalid_fmi(),
                        reason='No FMI key in config')
    def test_receive_fmi_temperature(self):
        run_temp_test_for(receive_fmi_temperature)

    @pytest.mark.skipif(has_invalid_open_weather_map(),
                        reason='No open weather map key in config')
    def test_receive_open_weather_map_temperature(self):
        run_temp_test_for(receive_open_weather_map_temperature)

    def test_receive_yr_no_forecast(self):
        forecast = Temperatures.get_temp([receive_yr_no_forecast], max_ts_diff=48 * 60)
        assert len(forecast[0]) > 24

    def test_receive_yr_no_forecast_cache(self, mocker):
        # Tests that after network is gone, we still get forecast for 24 hours

        freeze_ts1 = arrow.get('2017-08-18T15:00:00+00:00')
        with freeze_time(freeze_ts1.datetime):
            assert datetime(2017, 8, 18, 15) == datetime.now()
            temp1, ts1 = run_temp_test_for(receive_yr_no_forecast, max_ts_diff=48 * 60)
            assert isinstance(ts1, arrow.Arrow)

        mocker.patch('requests.get', side_effect=Exception('foo'))
        mock_time_sleep = mocker.patch('time.sleep')  # mock sleep so retry does not take a long time

        with freeze_time('2017-08-20T14:59:00+00:00'):
            assert datetime(2017, 8, 20, 14, 59) == datetime.now()
            temp2, ts2 = run_temp_test_for(receive_yr_no_forecast, max_ts_diff=48 * 60)
            assert isinstance(ts2, arrow.Arrow)

        assert ts1 == ts2, 'two requests were made (mocking does not work?)'

        with freeze_time('2017-08-20T15:00:00+00:00'):
            assert datetime(2017, 8, 20, 15) == datetime.now()
            temp3, ts3 = run_temp_test_for(receive_yr_no_forecast, max_ts_diff=48 * 60)
            assert temp3 is None
            assert ts3 is None

        RequestCache.reset()

        with freeze_time('2017-08-20T15:00:00+00:00'):
            assert datetime(2017, 8, 20, 15) == datetime.now()
            temp4, ts4 = run_temp_test_for(receive_yr_no_forecast, max_ts_diff=48 * 60)
            assert temp4 is None
            assert ts4 is None

        assert mock_time_sleep.call_count == 6

    def test_temperatures(self, mocker):

        mocker.patch('states.auto_test.receive_ulkoilma_temperature', return_value=(Decimal(3), arrow.now()))

        if has_invalid_fmi():
            mocker.patch('states.auto_test.receive_fmi_temperature', return_value=(Decimal(3), arrow.now()))

        outside_temp = Temperatures.get_temp([receive_ulkoilma_temperature, receive_fmi_temperature])[0]

        assert -30 < outside_temp < 30

    def test_target_temp(self):
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(5), ts=arrow.now()), Decimal(1), Decimal(20), None),
                            Decimal(20))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(10), ts=arrow.now()), Decimal(1), Decimal(20), None),
                            Decimal(20))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(15), ts=arrow.now()), Decimal(1), Decimal(20), None),
                            Decimal(20))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(-5), ts=arrow.now()), Decimal(1), Decimal(0), None),
                            Decimal('7.6'))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(-11), ts=arrow.now()), Decimal(1), Decimal(0), None),
                            Decimal('8.8'))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(-12), ts=arrow.now()), Decimal(1), Decimal(0), None),
                            Decimal('8.8'))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(-20), ts=arrow.now()), Decimal(1), Decimal(0), None),
                            Decimal('8.3'))

        forecast = [-20] * 8 + [-10] * 16
        assert_almost_equal(
            target_inside_temperature(TempTs(temp=Decimal(-20), ts=arrow.now()), Decimal(1), Decimal(1), forecast_object(forecast)),
            Decimal('6.2'))

        forecast = [-15] * 8
        assert_almost_equal(
            target_inside_temperature(TempTs(temp=Decimal(-15), ts=arrow.now()), Decimal(1), Decimal(1), forecast_object(forecast)),
            Decimal('8.6'))

        forecast = [-20] * 8 + [-15] * 8 + [5] * 8
        assert_almost_equal(
            target_inside_temperature(TempTs(temp=Decimal(-15), ts=arrow.now()), Decimal(1), Decimal(1), forecast_object(forecast)),
            Decimal('6.2'))

    def test_buffer(self):
        forecast = [
            -20,
            20,
            -20,
        ]
        buffer = get_buffer(
            Decimal(2), TempTs(temp=Decimal(1), ts=arrow.now()), Decimal(1), forecast_object(forecast))
        assert_almost_equal(Decimal(buffer), Decimal(13))

        forecast = [
            '1.01',
            '1.01',
            '1.01',
            '1.01',
            '1.01',
        ]
        buffer = get_buffer(
            Decimal(1), TempTs(temp=Decimal(1), ts=arrow.now()), Decimal(1), forecast_object(forecast))
        assert_almost_equal(Decimal(buffer), Decimal('Infinity'))

        forecast = [
            -20,
            20,
            -20,
            -20,
            20,
            20,
            -20,
        ]
        buffer = get_buffer(
            Decimal(3), TempTs(temp=Decimal(-5), ts=arrow.now()), Decimal(1), forecast_object(forecast))
        assert_almost_equal(Decimal(buffer), Decimal(29))


class TestAuto:

    @staticmethod
    def run_auto_ver2():
        Auto.clear()
        auto = Auto()
        auto.run({})
        Auto.clear()

    @pytest.mark.skipif(has_invalid_sheet(),
                        reason='No sheet OAuth file or key in config')
    def test_auto_message_wait(self, mocker):
        mocker.patch('states.auto.send_ir_signal')
        mock_healthcheck = mocker.patch('poller_helpers.get_url')  # mock health check
        mock_time_sleep = mocker.patch('time.sleep')
        mocker.patch('states.auto.get_url')  # mock requests

        auto = Auto()
        payload = auto.run({})
        Auto.clear()

        assert mock_healthcheck.call_count == 2
        assert mock_time_sleep.call_count == 3
        mock_time_sleep.assert_has_calls([call(10), call(10), call(60 * 10)])
        assert payload == {}

        mocker.resetall()

        sh = InitPygsheets.init_pygsheets()
        wks = sh[config.MESSAGE_SHEET_INDEX]
        wks.update_cell(config.MESSAGE_SHEET_CELL, '{ "command":"auto", "param":null }')

        mocker.patch('states.auto.send_ir_signal')
        mock_healthcheck = mocker.patch('poller_helpers.get_url')  # mock health check
        mock_time_sleep = mocker.patch('time.sleep')

        auto = Auto()
        payload = auto.run({})
        Auto.clear()

        assert mock_healthcheck.call_count == 1
        mock_time_sleep.assert_has_calls([call(10), call(10)])
        assert payload == {'command': 'auto', 'param': None}
        assert auto.nex(payload) == Auto

    def test_auto_minimum_inside_temp(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP + 5)
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP + 3)

        auto = Auto()
        auto.run({'command': 'auto', 'param': {'min_inside_temp': 18}})
        assert mock_send_ir_signal.call_count == 1
        assert mock_send_ir_signal.call_args[0][0] == Commands.heat30

        auto.run({})
        assert_ir_call(mock_send_ir_signal, Commands.heat30)
        assert mock_send_ir_signal.call_count == 1
        assert mock_send_ir_signal.call_args[0][0] == Commands.heat30

        auto.run({'command': 'auto', 'param': None})
        assert mock_send_ir_signal.call_count == 2
        assert mock_send_ir_signal.call_args[0][0] == Commands.off

    def test_auto_warm_inside(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP)
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP - 1)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.off)

    def test_auto_cold_inside(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP - 1)
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP - 1)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.heat8)

    def test_auto_invalid_inside_low_outside(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, None)
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP - 1, config.MINIMUM_INSIDE_TEMP - 5)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.heat8)

    def test_auto_invalid_inside_high_outside(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, None)
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP + 1)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.off)

    def test_auto_invalid_outside_high_forecast(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP - 1)
        mock_outside(mocker, None, config.MINIMUM_INSIDE_TEMP + 10)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.off)

    def test_auto_invalid_outside_low_forecast(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP + 1)
        mock_outside(mocker, None, config.MINIMUM_INSIDE_TEMP - 10)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.heat20)

    def test_auto_invalid_outside_and_inside_low_forecast(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, None)
        mock_outside(mocker, None, config.MINIMUM_INSIDE_TEMP - 5)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.heat8)

    def test_auto_all_invalid(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, None)
        mock_outside(mocker, None)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.heat16)

    def test_auto_cold_inside_and_outside(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP - 1)
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP - 5)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.heat16)

    def test_auto_very_cold_inside_and_outside(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP - 4)
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP - 23)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.heat28)

    def test_auto_warm_inside_and_outside(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP + 5)
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP + 10)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.off)

    def test_auto_should_not_turn_off_when_warn_inside_but_cold_outside(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP + 5)
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP - 20)

        self.run_auto_ver2()
        assert_ir_call(mock_send_ir_signal, Commands.heat10)

    def test_auto_hysteresis(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP + Decimal('20'))
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP - 11)

        Auto.last_command = Commands.heat8
        auto = Auto()
        auto.run({})
        Auto.clear()

        assert_ir_call(mock_send_ir_signal, Commands.off)

    def test_auto_hysteresis2(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP + Decimal('1.2'))
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP - 11)

        Auto.last_command = Commands.heat20
        auto = Auto()
        auto.run({})
        Auto.clear()

        assert_ir_call(mock_send_ir_signal, None)

    def test_auto_hysteresis3(self, mocker):
        mock_send_ir_signal = mocker_init(mocker)
        mock_inside(mocker, config.MINIMUM_INSIDE_TEMP - Decimal('0.1'))
        mock_outside(mocker, config.MINIMUM_INSIDE_TEMP - 6)

        Auto.last_command = Commands.off
        auto = Auto()
        auto.run({})
        Auto.clear()

        assert_ir_call(mock_send_ir_signal, Commands.heat16)
