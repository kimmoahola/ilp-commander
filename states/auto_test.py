import json
import os
import random
from decimal import Decimal

import arrow
from freezegun import freeze_time

import config
from poller_helpers import Commands, TempTs, Forecast
from states.auto import receive_ulkoilma_temperature, receive_wc_temperature, \
    receive_fmi_temperature, Auto, target_inside_temperature, receive_yr_no_forecast, \
    RequestCache, receive_open_weather_map_temperature, get_buffer, make_forecast, get_temp_from_temp_api, \
    receive_fmi_forecast, forecast_mean_temperature, get_temp, get_forecast, get_outside, Controller, get_error, \
    temp_control_without_inside_temp, get_next_command

MAX_TIME_DIFF_MINUTES = 120


def assert_almost_equal(first, second, delta=None):
    if delta is None:
        delta = Decimal('0.1')

    if first == Decimal('Infinity') or second == Decimal('Infinity'):
        assert first == second
    else:
        assert abs(first - second) <= delta, '%s != %s within %s delta' % (first, second, delta)


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
    return make_forecast(temp, ts, True)


def mocker_init(mocker):
    mock_send_ir_signal = mocker.patch('states.auto.send_ir_signal')
    mocker.patch('poller_helpers.get_message_from_sheet', return_value='')
    mocker.patch('states.auto.write_log_to_sheet')
    mocker.patch('time.sleep')
    mocker.patch('states.auto.Auto.load_state')
    mocker.patch('requests.get', side_effect=Exception(''))
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

    def test_get_temp_from_temp_api(self, mocker):
        mocker.patch('states.auto.get_url',
                     return_value=FakeResponse('{"id":118143,"ts":"2017-10-01T16:20:26+00:00","temperature":"8.187"}'))
        temp, ts = get_temp_from_temp_api('host_and_port', 'table_name')
        assert temp == '8.187'
        assert ts == '2017-10-01T16:20:26+00:00'

    def test_receive_ulkoilma_temperature(self, mocker):
        mocker.patch('states.auto.get_temp_from_temp_api', return_value=('8.187', '2017-10-01T16:20:26+00:00'))
        temp, ts = receive_ulkoilma_temperature()
        assert temp == Decimal('8.187')
        assert ts == arrow.get('2017-10-01T16:20:26+00:00')

    def test_receive_wc_temperature(self, mocker):
        mocker.patch('states.auto.get_temp_from_sheet', return_value=('8.187', '11.02.2018 klo 12:10'))
        temp, ts = receive_wc_temperature()
        assert temp == Decimal('8.187')
        assert ts == arrow.get('2018-02-11T10:10:00+00:00')

    def test_receive_fmi_temperature(self, mocker):
        path = os.path.dirname(os.path.abspath(__file__))
        mocker.patch('states.auto.get_url',
                     return_value=FakeResponse(open(os.path.join(path, 'fake_fmi_temperature.xml')).read()))
        temp, ts = receive_fmi_temperature()
        assert temp == Decimal('-4.9')
        assert ts == arrow.get('2018-02-11T12:30:00+02:00')

    def test_receive_open_weather_map_temperature(self, mocker):
        mocker.patch('states.auto.get_url',
                     return_value=FakeResponse('{"coord":{"lon":23.49,"lat":60.8},"weather":[{"id":600,"main":"Snow","description":"light snow","icon":"13d"}],"base":"stations","main":{"temp":-5,"pressure":1012,"humidity":92,"temp_min":-5,"temp_max":-5},"visibility":7000,"wind":{"speed":3.1,"deg":100},"clouds":{"all":90},"dt":1518346200,"sys":{"type":1,"id":5045,"message":0.0047,"country":"FI","sunrise":1518329840,"sunset":1518361453},"id":655693,"name":"Jokioinen","cod":200}'))
        temp, ts = receive_open_weather_map_temperature()
        assert temp == Decimal(-5)
        assert ts == arrow.get('2018-02-11T12:50:00+02:00')

    def test_receive_yr_no_forecast(self, mocker):
        def yr_no_fake_response(url):
            path = os.path.dirname(os.path.abspath(__file__))
            if 'forecast_hour_by_hour' in url:
                return FakeResponse(open(os.path.join(path, 'yr_no_fake_forecast_hour_by_hour.xml')).read())
            else:
                return FakeResponse(open(os.path.join(path, 'yr_no_fake_forecast.xml')).read())

        mocker.patch('states.auto.get_url', new_callable=lambda: yr_no_fake_response)

        with freeze_time('2018-02-18T19:20:00+02:00'):
            temp1, ts1 = receive_yr_no_forecast()

        result = [
            TempTs(temp=Decimal('-10'), ts=arrow.get('2018-02-18T19:00:00+02:00')),
            TempTs(temp=Decimal('-11'), ts=arrow.get('2018-02-18T20:00:00+02:00')),
            TempTs(temp=Decimal('-12'), ts=arrow.get('2018-02-18T21:00:00+02:00')),
            TempTs(temp=Decimal('-12'), ts=arrow.get('2018-02-18T22:00:00+02:00')),
            TempTs(temp=Decimal('-12'), ts=arrow.get('2018-02-18T23:00:00+02:00')),
            TempTs(temp=Decimal('-12'), ts=arrow.get('2018-02-19T00:00:00+02:00')),
            TempTs(temp=Decimal('-13'), ts=arrow.get('2018-02-19T01:00:00+02:00')),
            TempTs(temp=Decimal('-13'), ts=arrow.get('2018-02-19T02:00:00+02:00')),
            TempTs(temp=Decimal('-13'), ts=arrow.get('2018-02-19T03:00:00+02:00')),
            TempTs(temp=Decimal('-13'), ts=arrow.get('2018-02-19T04:00:00+02:00')),
            TempTs(temp=Decimal('-13'), ts=arrow.get('2018-02-19T05:00:00+02:00')),
            TempTs(temp=Decimal('-13'), ts=arrow.get('2018-02-19T06:00:00+02:00')),
        ]

        assert temp1 == result
        assert ts1 == arrow.get('2018-02-18T19:20:00+02:00')

        mocker.patch('states.auto.get_url', side_effect=Exception('foo'))

        with freeze_time('2018-02-20T19:19:00+02:00'):
            temp2, ts2 = receive_yr_no_forecast()

        assert ts1 == ts2, 'two requests were made (mocking does not work?)'
        assert temp2 == result

        with freeze_time('2018-02-20T19:21:00+02:00'):
            assert receive_yr_no_forecast() is None

    def test_receive_fmi_forecast(self, mocker):
        path = os.path.dirname(os.path.abspath(__file__))
        mocker.patch('states.auto.get_url',
                     return_value=FakeResponse(open(os.path.join(path, 'fake_fmi_forecast.xml')).read()))
        with freeze_time('2018-02-11T17:55:00+02:00'):
            temp, ts = receive_fmi_forecast()
        assert temp == [TempTs(temp=Decimal('-4.5'), ts=arrow.get('2018-02-11T18:00:00+02:00')),
                        TempTs(temp=Decimal('-5.5'), ts=arrow.get('2018-02-11T19:00:00+02:00')),
                        TempTs(temp=Decimal('-6.5'), ts=arrow.get('2018-02-11T20:00:00+02:00'))]
        assert ts == arrow.get('2018-02-11T17:55:00+02:00')

    def test_forecast_mean_temperature(self):
        temp = [TempTs(temp=Decimal('-4.5'), ts=arrow.get('2018-02-11T18:00:00+02:00')),
                TempTs(temp=Decimal('-5.5'), ts=arrow.get('2018-02-11T19:00:00+02:00')),
                TempTs(temp=Decimal('-6.5'), ts=arrow.get('2018-02-11T20:00:00+02:00'))]
        assert forecast_mean_temperature(make_forecast(temp, arrow.now(), False)) == Decimal('-5.5')

    def test_temperatures(self):
        def temp_func1():
            return Decimal(4), arrow.get('2018-02-11T20:00:00+02:00')

        def temp_func2():
            return Decimal(6), arrow.get('2018-02-11T20:30:00+02:00')

        with freeze_time('2018-02-11T20:59:00+02:00'):
            temp, ts = get_temp([temp_func1, temp_func2])
            assert temp == Decimal(5)
            assert ts == arrow.get('2018-02-11T20:15:00+02:00')

        def temp_func3():
            return Decimal(7), arrow.get('2018-02-11T20:45:00+02:00')

        with freeze_time('2018-02-11T20:59:00+02:00'):
            temp, ts = get_temp([temp_func1, temp_func2, temp_func3])
            assert temp == Decimal(6)
            assert ts == arrow.get('2018-02-11T20:30:00+02:00')

    def test_target_inside_temperature(self):
        assert_almost_equal(target_inside_temperature(lambda x: None, TempTs(temp=Decimal(5), ts=arrow.now()), Decimal(1), Decimal(20), None),
                            Decimal(20))
        assert_almost_equal(target_inside_temperature(lambda x: None, TempTs(temp=Decimal(10), ts=arrow.now()), Decimal(1), Decimal(20), None),
                            Decimal(20))
        assert_almost_equal(target_inside_temperature(lambda x: None, TempTs(temp=Decimal(15), ts=arrow.now()), Decimal(1), Decimal(20), None),
                            Decimal(20))
        assert_almost_equal(target_inside_temperature(lambda x: None, TempTs(temp=Decimal(-5), ts=arrow.now()), Decimal(1), Decimal(0), None),
                            Decimal('7.6'))
        assert_almost_equal(target_inside_temperature(lambda x: None, TempTs(temp=Decimal(-11), ts=arrow.now()), Decimal(1), Decimal(0), None),
                            Decimal('8.8'))
        assert_almost_equal(target_inside_temperature(lambda x: None, TempTs(temp=Decimal(-12), ts=arrow.now()), Decimal(1), Decimal(0), None),
                            Decimal('8.8'))
        assert_almost_equal(target_inside_temperature(lambda x: None, TempTs(temp=Decimal(-20), ts=arrow.now()), Decimal(1), Decimal(0), None),
                            Decimal('8.3'))

        forecast = [-20] * 8 + [-10] * 16
        assert_almost_equal(
            target_inside_temperature(lambda x: None, TempTs(temp=Decimal(-20), ts=arrow.now()), Decimal(1), Decimal(1), forecast_object(forecast)),
            Decimal('6.2'))

        forecast = [-15] * 8
        assert_almost_equal(
            target_inside_temperature(lambda x: None, TempTs(temp=Decimal(-15), ts=arrow.now()), Decimal(1), Decimal(1), forecast_object(forecast)),
            Decimal('8.6'))

        forecast = [-20] * 8 + [-15] * 8 + [5] * 8
        assert_almost_equal(
            target_inside_temperature(lambda x: None, TempTs(temp=Decimal(-15), ts=arrow.now()), Decimal(1), Decimal(1), forecast_object(forecast)),
            Decimal('6.2'))

    def test_get_buffer(self):
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

    def test_get_forecast(self, mocker):
        temps1 = [TempTs(temp=Decimal('-4.5'), ts=arrow.get('2018-02-11T18:00:00+02:00')),
                  TempTs(temp=Decimal('-5.5'), ts=arrow.get('2018-02-11T19:00:00+02:00')),
                  TempTs(temp=Decimal('-6.5'), ts=arrow.get('2018-02-11T20:00:00+02:00'))]
        temps2 = [TempTs(temp=Decimal('-5.5'), ts=arrow.get('2018-02-11T18:00:00+02:00')),
                  TempTs(temp=Decimal('-6.5'), ts=arrow.get('2018-02-11T19:00:00+02:00')),
                  TempTs(temp=Decimal('-7.5'), ts=arrow.get('2018-02-11T20:00:00+02:00'))]
        ts = arrow.get('2018-02-11T21:00:00+02:00')
        mocker.patch('states.auto.receive_fmi_forecast', return_value=(temps1, ts))
        mocker.patch('states.auto.receive_yr_no_forecast', return_value=(temps2, ts))
        mocker.patch('requests.get', side_effect=Exception('mocking did not work'))

        with freeze_time('2018-02-11T17:00:00+02:00'):
            forecast, mean_forecast = get_forecast(lambda x: x, True)

        assert forecast == Forecast(
            temps=[TempTs(temp=Decimal(-5), ts=arrow.get('2018-02-11T18:00:00+02:00')),
                   TempTs(temp=Decimal(-6), ts=arrow.get('2018-02-11T19:00:00+02:00')),
                   TempTs(temp=Decimal(-7), ts=arrow.get('2018-02-11T20:00:00+02:00'))],
            ts=arrow.get('2018-02-11T18:00:00+02:00'))

        assert mean_forecast == Decimal(-6)

    def test_get_outside(self, mocker):
        ts = arrow.get('2018-02-11T21:00:00+02:00')
        mocker.patch('states.auto.receive_ulkoilma_temperature', return_value=(Decimal(-3), ts))
        mocker.patch('states.auto.receive_fmi_temperature', return_value=(Decimal(-4), ts))
        mocker.patch('states.auto.receive_open_weather_map_temperature', return_value=(Decimal(-5), ts))
        mocker.patch('requests.get', side_effect=Exception('mocking did not work'))

        with freeze_time('2018-02-11T21:30:00+02:00'):
            temp_ts, valid_outside = get_outside(lambda x: x, Decimal(-5))

        assert temp_ts == TempTs(temp=Decimal(-4), ts=ts)
        assert valid_outside

    def test_temp_control_without_inside_temp(self):
        assert temp_control_without_inside_temp(Decimal(-2), Decimal('3.5')) == Decimal(8)
        assert temp_control_without_inside_temp(Decimal(-7), Decimal(4)) == Decimal('10.93')
        assert temp_control_without_inside_temp(Decimal(-20), Decimal(4)) == Decimal(24)

    def test_get_next_command(self):
        assert get_next_command(True, Decimal(3), Decimal(-15), True, Decimal('3.5'), Decimal(9)) == Commands.heat8
        with freeze_time('2018-05-02T00:00:00+02:00'):
            assert get_next_command(False, None, Decimal(-10), False, Decimal('3.5'), Decimal(9)) == Commands.heat10
            assert get_next_command(True, None, Decimal(-10), False, Decimal('3.5'), Decimal(9)) == Commands.off
            assert get_next_command(True, None, Decimal(-10), True, Decimal('3.5'), Decimal(9)) == Commands.heat10
            assert get_next_command(True, None, Decimal('3.5'), True, Decimal('3.5'), Decimal(9)) == Commands.off
            assert get_next_command(True, Decimal('3.5'), Decimal(3), True, Decimal('3.5'), Decimal(7)) == Commands.off
        with freeze_time('2018-04-30T00:00:00+02:00'):
            assert get_next_command(True, None, Decimal(-10), False, Decimal('3.5'), Decimal(9)) == Commands.heat10

    def test_get_error(self):
        assert get_error(Decimal(4), Decimal(5), Decimal('0.2')) == -Decimal('0.8')
        assert get_error(Decimal(5), Decimal(4), Decimal('0.2')) == Decimal(1)
        assert get_error(Decimal('3.5'), Decimal('3.8'), Decimal('0.2')) == -Decimal('0.1')
        assert get_error(Decimal('3.5'), Decimal('3.7'), Decimal('0.2')) == 0
        assert get_error(Decimal('3.5'), Decimal('3.5'), Decimal('0.2')) == 0
        assert get_error(Decimal('3.5'), Decimal('3.4'), Decimal('0.2')) == Decimal('0.1')
        assert get_error(Decimal('3.5'), None, Decimal('0.2')) == 0

    def test_controller(self, mocker):

        c = Controller(
            Decimal(3),
            Decimal(1) / Decimal(3600),
            Decimal(20))

        mocker.patch('time.time', return_value=0)
        assert c.update(Decimal(1))[0] == Decimal(3)

        mocker.patch('time.time', return_value=600)
        assert c.update(Decimal(1))[0] == Decimal(3) + Decimal(1) / Decimal(3600) * Decimal(600)

        mocker.patch('time.time', return_value=1200)
        assert c.update(Decimal(2))[0] == Decimal(6) + Decimal(1) / Decimal(3600) * Decimal(1800)

        mocker.patch('time.time', return_value=1800)
        c.set_i_low_limit(3)
        assert c.update(Decimal(2))[0] == Decimal(6) + Decimal(3)

        mocker.patch('time.time', return_value=72000)
        assert c.update(Decimal(2))[0] == Decimal(6) + Decimal(20)

        mocker.patch('time.time', return_value=72000 * 2)
        assert c.update(Decimal(2))[0] == Decimal(6) + Decimal(20)


class TestAuto:
    @staticmethod
    def setup_method():
        RequestCache.reset()

    @staticmethod
    def run_auto_ver2():
        Auto.clear()
        auto = Auto()
        auto.run({})
        Auto.clear()

    def test_auto_message_wait(self, mocker):
        mocker_init(mocker)

        auto = Auto()
        payload = auto.run({})
        Auto.clear()

        assert payload == {}
        mock_get_message_from_sheet = mocker.patch('poller_helpers.get_message_from_sheet',
                                                   return_value='{ "command":"auto", "param":null }')

        auto = Auto()
        payload = auto.run({})
        Auto.clear()

        assert mock_get_message_from_sheet.call_count == 1
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
