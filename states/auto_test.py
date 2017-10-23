import json
from datetime import datetime
from decimal import Decimal

import arrow
import pytest
from freezegun import freeze_time

import config
from poller_helpers import Commands, InitPygsheets, TempTs, Forecast
from states.auto import receive_ulkoilma_temperature, receive_wc_temperature, \
    receive_fmi_temperature, Temperatures, Auto, target_inside_temperature, receive_yr_no_forecast, \
    RequestCache, receive_open_weather_map_temperature

MAX_TIME_DIFF_MINUTES = 120


def assert_almost_equal(first, second, delta=None):
    if delta is None:
        delta = Decimal('0.1')

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


def gen_forecast(forecast):
    start = arrow.now().shift(minutes=30)
    # start = arrow.now().shift(minutes=30)
    return Forecast(temps=[TempTs(temp=Decimal(f), ts=start.shift(hours=i)) for i, f in enumerate(forecast)], ts=arrow.now())


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
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(5), ts=arrow.now()), Decimal(20), None),
                            Decimal('28.0'))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(10), ts=arrow.now()), Decimal(20), None),
                            Decimal('25.3'))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(15), ts=arrow.now()), Decimal(20), None),
                            Decimal('22.7'))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(-5), ts=arrow.now()), Decimal(0), None),
                            Decimal(6))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(-11), ts=arrow.now()), Decimal(0), None),
                            Decimal(6))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(-12), ts=arrow.now()), Decimal(0), None),
                            Decimal('6.4'))
        assert_almost_equal(target_inside_temperature(TempTs(temp=Decimal(-20), ts=arrow.now()), Decimal(0), None),
                            Decimal('10.7'))

        forecast = [-20] * 8 + [-10] * 16
        assert_almost_equal(
            target_inside_temperature(TempTs(temp=Decimal(-20), ts=arrow.now()), Decimal(1), gen_forecast(forecast)),
            Decimal('8.6'))

        forecast = [-15] * 8
        assert_almost_equal(
            target_inside_temperature(TempTs(temp=Decimal(-15), ts=arrow.now()), Decimal(1), gen_forecast(forecast)),
            Decimal('9.6'))

        forecast = [-20] * 8 + [-15] * 8 + [5] * 8
        assert_almost_equal(
            target_inside_temperature(TempTs(temp=Decimal(-15), ts=arrow.now()), Decimal(1), gen_forecast(forecast)),
            Decimal('7.3'))


class TestVer1:

    def test_auto_ver1_warm_inside(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now()))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(3), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(5), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(7), arrow.now()))

        auto = Auto()
        auto.run({}, version=1)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(Commands.off, extra_info=['Inside temperature: 8'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_not_called()
        mock_receive_open_weather_map_temperature.assert_not_called()
        mock_receive_fmi_temperature.assert_not_called()

    def test_auto_ver1_invalid_inside(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now().shift(minutes=-60)))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(3), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(7), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(7), arrow.now()))

        auto = Auto()
        auto.run({}, version=1)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.off, extra_info=['Inside temperature: None', 'Outside temperature: 7'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()

    def test_auto_ver1_invalid_all_temperatures(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now().shift(minutes=-60)))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(None, None))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(None, None))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(None, None))

        auto = Auto()
        auto.run({}, version=1)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.heat16,
            extra_info=['Inside temperature: None', 'Outside temperature: None', 'Got no temperatures at all.'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()

    def test_auto_ver1_cold_inside(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal('7.5'), arrow.now().shift(minutes=-30)))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(3), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(5), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(7), arrow.now()))

        auto = Auto()
        auto.run({}, version=1)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.off, extra_info=['Inside temperature: 7.5', 'Outside temperature: 5'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()

    def test_auto_ver1_cold_inside_and_outside(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal('7.5'), arrow.now().shift(minutes=-30)))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(-3), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(-5), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(-7), arrow.now()))

        auto = Auto()
        auto.run({}, version=1)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.heat8, extra_info=['Inside temperature: 7.5', 'Outside temperature: -5'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()

    def test_auto_ver1_very_cold_inside_and_outside(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(1), arrow.now().shift(minutes=-30)))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(-19), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(-20), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(-21), arrow.now()))

        auto = Auto()
        auto.run({}, version=1)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.heat16, extra_info=['Inside temperature: 1', 'Outside temperature: -20'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()


class TestVer2:

    @pytest.mark.skipif(has_invalid_sheet(),
                        reason='No sheet OAuth file or key in config')
    def test_auto_ver2_message_wait(self, mocker):
        # TODO: jää jumiin joskus


        mocker.patch('states.auto.send_ir_signal')
        mock_healthcheck = mocker.patch('poller_helpers.get_url')  # mock health check
        mock_time_sleep = mocker.patch('time.sleep')
        mocker.patch('states.auto.get_url')  # mock requests

        auto = Auto()
        payload = auto.run({}, version=2)
        Auto.last_command = None

        mock_healthcheck.assert_called_once()
        mock_time_sleep.assert_called_once_with(60 * 10)
        assert payload == {}

        mocker.resetall()

        sh = InitPygsheets.init_pygsheets()
        wks = sh[config.MESSAGE_SHEET_INDEX]
        wks.update_cell(config.MESSAGE_SHEET_CELL, '{ "command":"auto", "param":null }')

        mocker.patch('states.auto.send_ir_signal')
        mock_healthcheck = mocker.patch('poller_helpers.get_url')  # mock health check
        mock_time_sleep = mocker.patch('time.sleep')

        auto = Auto()
        payload = auto.run({}, version=2)
        Auto.last_command = None

        mock_healthcheck.assert_called_once()
        mock_time_sleep.assert_not_called()
        assert payload == {'command': 'auto', 'param': None}
        assert auto.nex(payload) == Auto

    def test_auto_ver2_warm_inside(self, mocker):
        with freeze_time('2017-10-22T05:00:00+00:00'):
            mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
            mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
            mock_receive_wc_temperature = mocker.patch(
                'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now()))
            mock_receive_ulkoilma_temperature = mocker.patch(
                'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(3), arrow.now()))
            mock_receive_fmi_temperature = mocker.patch(
                'states.auto.receive_fmi_temperature', return_value=(Decimal(7), arrow.now()))
            mock_receive_open_weather_map_temperature = mocker.patch(
                'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(5), arrow.now()))
            mock_receive_yr_no_forecast = mocker.patch(
                'states.auto.receive_yr_no_forecast', return_value=gen_forecast([1, 3]))

            auto = Auto()
            auto.run({}, version=2)
            Auto.last_command = None

            mock_send_ir_signal.assert_called_once_with(
                Commands.off, extra_info=['Forecast min temperature: 1', 'Outside temperature: 5',
                                          'Target inside temperature: 6.0', 'Inside temperature: 8',
                                          'Current buffer: inf h () to temp 1 C',
                                          'Current time_until_heat: 28.0 h (23.10.2017 12:00) to temp 6 C'])
            mock_get_most_recent_message.assert_called_once_with(once=True)
            mock_receive_wc_temperature.assert_called_once()
            mock_receive_ulkoilma_temperature.assert_called_once()
            mock_receive_fmi_temperature.assert_called_once()
            mock_receive_open_weather_map_temperature.assert_called_once()
            mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_invalid_inside(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now().shift(minutes=-60)))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(3), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(7), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(5), arrow.now()))
        mock_receive_yr_no_forecast = mocker.patch(
            'states.auto.receive_yr_no_forecast', return_value=gen_forecast([1, 3]))

        auto = Auto()
        auto.run({}, version=2)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.heat8,
            extra_info=['Forecast min temperature: 1', 'Outside temperature: 5',
                        'Target inside temperature: 6.0', 'Inside temperature: None'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_invalid_inside_high_outside(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now().shift(minutes=-60)))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(10), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(12), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(None, None))
        mock_receive_yr_no_forecast = mocker.patch(
            'states.auto.receive_yr_no_forecast', return_value=gen_forecast([10, 9]))

        auto = Auto()
        auto.run({}, version=2)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.off,
            extra_info=['Forecast min temperature: 9', 'Outside temperature: 11',
                        'Target inside temperature: 6.0', 'Inside temperature: None'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_invalid_outside_high_forecast(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now()))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(None, None))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(None, None))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(None, None))
        mock_receive_yr_no_forecast = mocker.patch(
            'states.auto.receive_yr_no_forecast', return_value=gen_forecast([20, 30]))

        auto = Auto()
        auto.run({}, version=2)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.off, extra_info=['Forecast min temperature: 20', 'Outside temperature: None',
                                      'Using forecast: 20', 'Target inside temperature: 6.0', 'Inside temperature: 8',
                                      'Current buffer: inf h () to temp 1 C',
                                      'Current time_until_heat: inf h () to temp 6 C'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_invalid_outside_low_forecast(self, mocker):
        with freeze_time('2017-10-22T05:00:00+00:00'):
            mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
            mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
            mock_receive_wc_temperature = mocker.patch(
                'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now()))
            mock_receive_ulkoilma_temperature = mocker.patch(
                'states.auto.receive_ulkoilma_temperature', return_value=(None, None))
            mock_receive_fmi_temperature = mocker.patch(
                'states.auto.receive_fmi_temperature', return_value=(None, None))
            mock_receive_open_weather_map_temperature = mocker.patch(
                'states.auto.receive_open_weather_map_temperature', return_value=(None, None))
            mock_receive_yr_no_forecast = mocker.patch(
                'states.auto.receive_yr_no_forecast', return_value=gen_forecast([2, 3]))

            auto = Auto()
            auto.run({}, version=2)
            Auto.last_command = None

            mock_send_ir_signal.assert_called_once_with(
                Commands.off,
                extra_info=['Forecast min temperature: 2', 'Outside temperature: None', 'Using forecast: 2',
                            'Target inside temperature: 6.0', 'Inside temperature: 8',
                            'Current buffer: inf h () to temp 1 C',
                            'Current time_until_heat: 23.9 h (23.10.2017 07:54) to temp 6 C'])
            mock_get_most_recent_message.assert_called_once_with(once=True)
            mock_receive_wc_temperature.assert_called_once()
            mock_receive_ulkoilma_temperature.assert_called_once()
            mock_receive_fmi_temperature.assert_called_once()
            mock_receive_open_weather_map_temperature.assert_called_once()
            mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_invalid_outside_and_inside_low_forecast(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(None, None))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(None, None))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(None, None))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(None, None))
        mock_receive_yr_no_forecast = mocker.patch(
            'states.auto.receive_yr_no_forecast', return_value=gen_forecast([2, 3]))

        auto = Auto()
        auto.run({}, version=2)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.heat8,
            extra_info=['Forecast min temperature: 2', 'Outside temperature: None', 'Using forecast: 2',
                        'Target inside temperature: 6.0', 'Inside temperature: None'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_invalid_all_temperatures(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(8), arrow.now().shift(minutes=-60)))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(None, None))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(None, None))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(None, None))
        mock_receive_yr_no_forecast = mocker.patch(
            'states.auto.receive_yr_no_forecast', return_value=gen_forecast([]))

        auto = Auto()
        auto.run({}, version=2)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.heat8, extra_info=['Forecast min temperature: None', 'Outside temperature: None',
                                        'Using predefined outside temperature: -10', 'Target inside temperature: 6.9',
                                        'Inside temperature: None'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_cold_inside(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal('5.5'), arrow.now().shift(minutes=-30)))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(7), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(7), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(6), arrow.now()))
        mock_receive_yr_no_forecast = mocker.patch(
            'states.auto.receive_yr_no_forecast', return_value=gen_forecast([]))

        auto = Auto()
        auto.run({}, version=2)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.off,
            extra_info=['Forecast min temperature: None', 'Outside temperature: 7',
                        'Target inside temperature: 6.0', 'Inside temperature: 5.5',
                        'Current buffer: inf h () to temp 1 C', 'Current time_until_heat: inf h () to temp 6 C'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_cold_inside_and_outside(self, mocker):
        with freeze_time('2017-10-22T15:00:00+00:00'):
            mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
            mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
            mock_receive_wc_temperature = mocker.patch(
                'states.auto.receive_wc_temperature', return_value=(Decimal(2), arrow.now().shift(minutes=-30)))
            mock_receive_ulkoilma_temperature = mocker.patch(
                'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(-3), arrow.now()))
            mock_receive_fmi_temperature = mocker.patch(
                'states.auto.receive_fmi_temperature', return_value=(Decimal(-7), arrow.now()))
            mock_receive_open_weather_map_temperature = mocker.patch(
                'states.auto.receive_open_weather_map_temperature',
                return_value=(Decimal(-6), arrow.now().shift(minutes=-60)))
            mock_receive_yr_no_forecast = mocker.patch(
                'states.auto.receive_yr_no_forecast', return_value=gen_forecast([]))

            auto = Auto()
            auto.run({}, version=2)
            Auto.last_command = None

            mock_send_ir_signal.assert_called_once_with(
                Commands.heat8,
                extra_info=['Forecast min temperature: None', 'Outside temperature: -5',
                            'Target inside temperature: 6.0', 'Inside temperature: 2',
                            'Current buffer: 8.5 h (23.10.2017 02:30) to temp 1 C'])
            mock_get_most_recent_message.assert_called_once_with(once=True)
            mock_receive_wc_temperature.assert_called_once()
            mock_receive_ulkoilma_temperature.assert_called_once()
            mock_receive_fmi_temperature.assert_called_once()
            mock_receive_open_weather_map_temperature.assert_called_once()
            mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_very_cold_inside_and_outside(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(1), arrow.now().shift(minutes=-30)))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(-18), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(-21), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal('-19.5'), arrow.now()))
        mock_receive_yr_no_forecast = mocker.patch(
            'states.auto.receive_yr_no_forecast', return_value=gen_forecast([]))

        auto = Auto()
        auto.run({}, version=2)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.heat16,
            extra_info=['Forecast min temperature: None', 'Outside temperature: -19.5',
                        'Target inside temperature: 12.0', 'Inside temperature: 1'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_warm_inside_and_outside(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(23), arrow.now()))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(15), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(16), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal('15.5'), arrow.now()))
        mock_receive_yr_no_forecast = mocker.patch(
            'states.auto.receive_yr_no_forecast', return_value=gen_forecast([]))

        auto = Auto()
        auto.run({}, version=2)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.off, extra_info=['Forecast min temperature: None', 'Outside temperature: 15.5',
                                      'Target inside temperature: 6.0', 'Inside temperature: 23',
                                      'Current buffer: inf h () to temp 1 C',
                                      'Current time_until_heat: inf h () to temp 6 C'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_buffer_diff_division_by_zero(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(3), arrow.now()))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(2), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(2), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(2), arrow.now()))
        mock_receive_yr_no_forecast = mocker.patch(
            'states.auto.receive_yr_no_forecast', return_value=gen_forecast([]))

        auto = Auto()
        auto.run({}, version=2)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.heat8, extra_info=['Forecast min temperature: None', 'Outside temperature: 2',
                                        'Target inside temperature: 6.0', 'Inside temperature: 3',
                                        'Current buffer: inf h () to temp 1 C'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_buffer(self, mocker):
        with freeze_time('2017-10-22T15:00:00+00:00'):
            mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
            mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
            mock_receive_wc_temperature = mocker.patch(
                'states.auto.receive_wc_temperature', return_value=(Decimal(3), arrow.now()))
            mock_receive_ulkoilma_temperature = mocker.patch(
                'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(-4), arrow.now()))
            mock_receive_fmi_temperature = mocker.patch(
                'states.auto.receive_fmi_temperature', return_value=(Decimal(-5), arrow.now().shift(minutes=-10)))
            mock_receive_open_weather_map_temperature = mocker.patch(
                'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(-55), arrow.now()))

            forecast = [
                -20,
                20,
                -20,
                -20,
                20,
                20,
                -20,
            ]

            mock_receive_yr_no_forecast = mocker.patch(
                'states.auto.receive_yr_no_forecast', return_value=gen_forecast(forecast))

            auto = Auto()
            auto.run({}, version=2)
            Auto.last_command = None

            mock_send_ir_signal.assert_called_once_with(
                Commands.heat8, extra_info=['Forecast min temperature: -20', 'Outside temperature: -5',
                                            'Target inside temperature: 6.0', 'Inside temperature: 3',
                                            'Current buffer: 25.1 h (23.10.2017 19:06) to temp 1 C'])
            mock_get_most_recent_message.assert_called_once_with(once=True)
            mock_receive_wc_temperature.assert_called_once()
            mock_receive_ulkoilma_temperature.assert_called_once()
            mock_receive_fmi_temperature.assert_called_once()
            mock_receive_open_weather_map_temperature.assert_called_once()
            mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_buffer2(self, mocker):
        mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
        mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
        mock_receive_wc_temperature = mocker.patch(
            'states.auto.receive_wc_temperature', return_value=(Decimal(1), arrow.now()))
        mock_receive_ulkoilma_temperature = mocker.patch(
            'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(1), arrow.now()))
        mock_receive_fmi_temperature = mocker.patch(
            'states.auto.receive_fmi_temperature', return_value=(Decimal(1), arrow.now()))
        mock_receive_open_weather_map_temperature = mocker.patch(
            'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(1), arrow.now()))

        forecast = [
            '1.01',
            '1.01',
            '1.01',
            '1.01',
            '1.01',
        ]

        mock_receive_yr_no_forecast = mocker.patch(
            'states.auto.receive_yr_no_forecast', return_value=gen_forecast(forecast))

        auto = Auto()
        auto.run({}, version=2)
        Auto.last_command = None

        mock_send_ir_signal.assert_called_once_with(
            Commands.heat8, extra_info=['Forecast min temperature: 1.01', 'Outside temperature: 1',
                                        'Target inside temperature: 6.0', 'Inside temperature: 1'])
        mock_get_most_recent_message.assert_called_once_with(once=True)
        mock_receive_wc_temperature.assert_called_once()
        mock_receive_ulkoilma_temperature.assert_called_once()
        mock_receive_fmi_temperature.assert_called_once()
        mock_receive_open_weather_map_temperature.assert_called_once()
        mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_buffer3(self, mocker):
        with freeze_time('2017-10-22T15:00:00+00:00'):

            mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
            mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
            mock_receive_wc_temperature = mocker.patch(
                'states.auto.receive_wc_temperature', return_value=(Decimal(2), arrow.now()))
            mock_receive_ulkoilma_temperature = mocker.patch(
                'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(1), arrow.now()))
            mock_receive_fmi_temperature = mocker.patch(
                'states.auto.receive_fmi_temperature', return_value=(Decimal(1), arrow.now()))
            mock_receive_open_weather_map_temperature = mocker.patch(
                'states.auto.receive_open_weather_map_temperature', return_value=(Decimal(1), arrow.now()))

            forecast = [
                -20,
                20,
                -20,
            ]

            mock_receive_yr_no_forecast = mocker.patch(
                'states.auto.receive_yr_no_forecast', return_value=gen_forecast(forecast))

            auto = Auto()
            auto.run({}, version=2)
            Auto.last_command = None

            mock_send_ir_signal.assert_called_once_with(
                Commands.heat8, extra_info=['Forecast min temperature: -20', 'Outside temperature: 1',
                                            'Target inside temperature: 6.0', 'Inside temperature: 2',
                                            'Current buffer: 10.8 h (23.10.2017 04:48) to temp 1 C'])
            mock_get_most_recent_message.assert_called_once_with(once=True)
            mock_receive_wc_temperature.assert_called_once()
            mock_receive_ulkoilma_temperature.assert_called_once()
            mock_receive_fmi_temperature.assert_called_once()
            mock_receive_open_weather_map_temperature.assert_called_once()
            mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_hysteresis(self, mocker):
        with freeze_time('2017-10-22T15:00:00+00:00'):
            mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
            mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
            mock_receive_wc_temperature = mocker.patch(
                'states.auto.receive_wc_temperature', return_value=(Decimal('7.3'), arrow.now().shift(minutes=-30)))
            mock_receive_ulkoilma_temperature = mocker.patch(
                'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(-3), arrow.now()))
            mock_receive_fmi_temperature = mocker.patch(
                'states.auto.receive_fmi_temperature', return_value=(Decimal(-7), arrow.now()))
            mock_receive_open_weather_map_temperature = mocker.patch(
                'states.auto.receive_open_weather_map_temperature',
                return_value=(Decimal(-6), arrow.now().shift(minutes=-60)))
            mock_receive_yr_no_forecast = mocker.patch(
                'states.auto.receive_yr_no_forecast', return_value=gen_forecast([]))

            auto = Auto()
            Auto.last_command = Commands.heat8
            auto.run({}, version=2)
            Auto.last_command = None

            mock_send_ir_signal.assert_called_once_with(
                Commands.off,
                extra_info=['Forecast min temperature: None', 'Outside temperature: -5',
                            'Target inside temperature: 6.0', 'Inside temperature: 7.3',
                            'Current buffer: 39.5 h (24.10.2017 09:30) to temp 1 C', 'Hysteresis: 7.2',
                            'Current time_until_heat: 0.3 h (22.10.2017 18:18) to temp 7.2 C'])
            mock_get_most_recent_message.assert_called_once_with(once=True)
            mock_receive_wc_temperature.assert_called_once()
            mock_receive_ulkoilma_temperature.assert_called_once()
            mock_receive_fmi_temperature.assert_called_once()
            mock_receive_open_weather_map_temperature.assert_called_once()
            mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_hysteresis2(self, mocker):
        with freeze_time('2017-10-22T15:00:00+00:00'):
            mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
            mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
            mock_receive_wc_temperature = mocker.patch(
                'states.auto.receive_wc_temperature', return_value=(Decimal('7.2'), arrow.now().shift(minutes=-30)))
            mock_receive_ulkoilma_temperature = mocker.patch(
                'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(-3), arrow.now()))
            mock_receive_fmi_temperature = mocker.patch(
                'states.auto.receive_fmi_temperature', return_value=(Decimal(-7), arrow.now()))
            mock_receive_open_weather_map_temperature = mocker.patch(
                'states.auto.receive_open_weather_map_temperature',
                return_value=(Decimal(-6), arrow.now().shift(minutes=-60)))
            mock_receive_yr_no_forecast = mocker.patch(
                'states.auto.receive_yr_no_forecast', return_value=gen_forecast([]))

            auto = Auto()
            Auto.last_command = Commands.heat8
            auto.run({}, version=2)
            Auto.last_command = None

            mock_send_ir_signal.assert_not_called()
            mock_get_most_recent_message.assert_called_once_with(once=True)
            mock_receive_wc_temperature.assert_called_once()
            mock_receive_ulkoilma_temperature.assert_called_once()
            mock_receive_fmi_temperature.assert_called_once()
            mock_receive_open_weather_map_temperature.assert_called_once()
            mock_receive_yr_no_forecast.assert_called_once()

    def test_auto_ver2_hysteresis3(self, mocker):
        with freeze_time('2017-10-22T15:00:00+00:00'):
            mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
            mock_get_most_recent_message = mocker.patch('states.auto.get_most_recent_message')
            mock_receive_wc_temperature = mocker.patch(
                'states.auto.receive_wc_temperature', return_value=(Decimal('5.9'), arrow.now().shift(minutes=-30)))
            mock_receive_ulkoilma_temperature = mocker.patch(
                'states.auto.receive_ulkoilma_temperature', return_value=(Decimal(0), arrow.now()))
            mock_receive_fmi_temperature = mocker.patch(
                'states.auto.receive_fmi_temperature', return_value=(Decimal(0), arrow.now()))
            mock_receive_open_weather_map_temperature = mocker.patch(
                'states.auto.receive_open_weather_map_temperature',
                return_value=(Decimal(0), arrow.now().shift(minutes=-60)))
            mock_receive_yr_no_forecast = mocker.patch(
                'states.auto.receive_yr_no_forecast', return_value=gen_forecast([]))

            auto = Auto()
            Auto.last_command = Commands.off
            auto.run({}, version=2)
            Auto.last_command = None

            mock_send_ir_signal.assert_called_once_with(
                Commands.heat8,
                extra_info=['Forecast min temperature: None', 'Outside temperature: 0',
                            'Target inside temperature: 6.0', 'Inside temperature: 5.9',
                            'Current buffer: 97.7 h (26.10.2017 19:42) to temp 1 C', 'Hysteresis: 6.7'])
            mock_get_most_recent_message.assert_called_once_with(once=True)
            mock_receive_wc_temperature.assert_called_once()
            mock_receive_ulkoilma_temperature.assert_called_once()
            mock_receive_fmi_temperature.assert_called_once()
            mock_receive_open_weather_map_temperature.assert_called_once()
            mock_receive_yr_no_forecast.assert_called_once()
