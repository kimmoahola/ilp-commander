# coding=utf-8
import json
import time
from decimal import Decimal
from functools import wraps
from json import JSONDecodeError
from statistics import mean
from typing import Union

import arrow
import xmltodict
from dateutil import tz
from pony import orm

import config
from poller_helpers import Commands, logger, send_ir_signal, timing, get_most_recent_message, get_temp_from_sheet, \
    median, get_url, time_str, write_log_to_sheet, TempTs, Forecast, decimal_round, have_valid_time, log_temp_info, \
    SavedState
from states import State


class RequestCache:
    _cache = {}

    @classmethod
    def put(cls, name, stale_after_if_ok, stale_after_if_failed, content):
        cls._cache[name] = (stale_after_if_ok, stale_after_if_failed, content)

    @classmethod
    def get(cls, name, stale_check='ok'):
        if name in cls._cache:
            stale_after_if_ok, stale_after_if_failed, content = cls._cache[name]

            if stale_check == 'ok' and arrow.now() <= stale_after_if_ok:
                return content
            elif stale_check == 'failed' and arrow.now() <= stale_after_if_failed:
                return content

        return None

    @classmethod
    def reset(cls):
        cls._cache.clear()


def caching(cache_name):
    def caching_inner(f):
        @wraps(f)
        def caching_wrap(*args, **kw):
            rq = RequestCache()
            result = rq.get(cache_name)
            if result:
                logger.debug('func:%r args:[%r, %r] cache hit with result: %r' % (f.__name__, args, kw, result))
            else:
                logger.debug('func:%r args:[%r, %r] cache miss' % (f.__name__, args, kw))
                result = f(*args, **kw)
                if result and result[1] is not None:  # result[1] == timestamp
                    temp, ts = result
                    logger.debug('func:%r args:[%r, %r] storing with result: %r' % (f.__name__, args, kw, result))
                    stale_after_if_ok = ts.shift(
                        minutes=config.CACHE_TIMES.get(cache_name, {}).get('if_ok', 60))
                    stale_after_if_failed = ts.shift(
                        minutes=config.CACHE_TIMES.get(cache_name, {}).get('if_failed', 120))
                    rq.put(cache_name, stale_after_if_ok, stale_after_if_failed, result)
                else:
                    result = rq.get(cache_name, stale_check='failed')
                    if result:
                        logger.debug('func:%r args:[%r, %r] failed and returning old result: %r' % (
                            f.__name__, args, kw, result))
                    else:
                        logger.debug('func:%r args:[%r, %r] failed and no result in cache' % (f.__name__, args, kw))
            return result
        return caching_wrap
    return caching_inner


def get_temp_from_temp_api(host_and_port, table_name):
    temp, ts = None, None

    try:
        result = get_url('http://{host_and_port}/latest?table={table_name}'.format(
            host_and_port=host_and_port, table_name=table_name))
    except Exception as e:
        logger.exception(e)
    else:
        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            result_json = result.json()
            if 'ts' in result_json and 'temperature' in result_json:
                ts = result_json['ts']
                temp = result_json['temperature']

    return temp, ts


@timing
@caching(cache_name='ulkoilma')
def receive_ulkoilma_temperature():
    temp, ts = get_temp_from_temp_api(
        config.TEMP_API_OUTSIDE.get('host_and_port'), config.TEMP_API_OUTSIDE.get('table_name'))

    if ts is not None and temp is not None:
        ts = arrow.get(ts).to(config.TIMEZONE)
        temp = Decimal(temp)

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


@timing
@caching(cache_name='wc')
def receive_wc_temperature():
    temp, ts = get_temp_from_sheet(sheet_index=3)

    if ts is not None and temp is not None:
        ts = arrow.get(ts, 'DD.MM.YYYY klo HH:mm').replace(tzinfo=tz.gettz(config.TIMEZONE))
        temp = Decimal(temp)

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


@timing
@caching(cache_name='fmi')
def receive_fmi_temperature():
    temp, ts = None, None

    try:
        starttime = arrow.now().shift(hours=-1).to('UTC').format('YYYY-MM-DDTHH:mm:ss') + 'Z'
        result = get_url(
            'http://data.fmi.fi/fmi-apikey/{key}/wfs?request=getFeature&storedquery_id=fmi::observations::weather'
            '::simple&place={place}&parameters=temperature&starttime={starttime}'.format(
                key=config.FMI_KEY, place=config.FMI_LOCATION, starttime=starttime))
    except Exception as e:
        logger.exception(e)
    else:
        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            try:
                wfs_member = xmltodict.parse(result.content).get('wfs:FeatureCollection', {}).get('wfs:member')
                temp_data = wfs_member[-1].get('BsWfs:BsWfsElement')
                if temp_data and 'BsWfs:Time' in temp_data and 'BsWfs:ParameterValue' in temp_data:
                    ts = arrow.get(temp_data['BsWfs:Time']).to(config.TIMEZONE)
                    temp = Decimal(temp_data['BsWfs:ParameterValue'])
            except (KeyError, TypeError):
                temp, ts = None, None

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


@timing
@caching(cache_name='open_weather_map')
def receive_open_weather_map_temperature():
    temp, ts = None, None

    try:
        result = get_url(
            'http://api.openweathermap.org/data/2.5/weather?q={place}&units=metric&appid={key}'.format(
                key=config.OPEN_WEATHER_MAP_KEY, place=config.OPEN_WEATHER_MAP_LOCATION))
    except Exception as e:
        logger.exception(e)
    else:
        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            result_json = result.json()
            temp = Decimal(result_json['main']['temp'])
            ts = arrow.get(result_json['dt']).to(config.TIMEZONE)

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


@timing
@caching(cache_name='yr.no')
def receive_yr_no_forecast():
    temp, ts = None, None

    try:
        result = get_url('http://www.yr.no/place/{place}/forecast_hour_by_hour.xml'.format(place=config.YR_NO_LOCATION))
    except Exception as e:
        logger.exception(e)
    else:
        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            d = xmltodict.parse(result.content)
            timezone = d['weatherdata']['location']['timezone']['@id']

            temp = [
                TempTs(Decimal(t['temperature']['@value']), arrow.get(t['@from']).replace(tzinfo=timezone))
                for t
                in d['weatherdata']['forecast']['tabular']['time']
            ]

            try:
                result = get_url('https://www.yr.no/place/{place}/forecast.xml'.format(place=config.YR_NO_LOCATION))
            except Exception as e:
                logger.exception(e)
            else:
                if result.status_code != 200:
                    logger.error('%d: %s' % (result.status_code, result.content))
                else:
                    d = xmltodict.parse(result.content)
                    timezone = d['weatherdata']['location']['timezone']['@id']

                    for t in d['weatherdata']['forecast']['tabular']['time']:
                        current_forecast_end_ts = arrow.get(t['@to']).replace(tzinfo=timezone)
                        while current_forecast_end_ts > temp[-1].ts:
                            temp.append(TempTs(Decimal(t['temperature']['@value']), temp[-1].ts.shift(hours=1)))

            ts = arrow.now()
            log_forecast('receive_yr_no_forecast', temp)

    return temp, ts


@timing
@caching(cache_name='fmi_forecast')
def receive_fmi_forecast():
    temp, ts = None, None

    try:
        endtime = arrow.now().shift(hours=63).to('UTC').format('YYYY-MM-DDTHH:mm:ss') + 'Z'
        url = 'http://data.fmi.fi/fmi-apikey/{key}/wfs?request=getFeature&' \
                          'storedquery_id=fmi::forecast::harmonie::surface::point::simple&' \
                          'place={place}&parameters=temperature&endtime={endtime}'.format(key=config.FMI_KEY,
                                                                                          place=config.FMI_LOCATION,
                                                                                          endtime=endtime)
        result = get_url(
            url)
    except Exception as e:
        logger.exception(e)
    else:
        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            try:
                wfs_member = xmltodict.parse(result.content).get('wfs:FeatureCollection', {}).get('wfs:member')

                temp = [
                    TempTs(
                        Decimal(t['BsWfs:BsWfsElement']['BsWfs:ParameterValue']),
                        arrow.get(t['BsWfs:BsWfsElement']['BsWfs:Time']).to(config.TIMEZONE)
                    )
                    for t
                    in wfs_member
                    if t['BsWfs:BsWfsElement']['BsWfs:ParameterValue'] != 'NaN'
                ]

                ts = arrow.now()
                log_forecast('receive_fmi_forecast', temp)

            except (KeyError, TypeError):
                temp, ts = None, None

    return temp, ts


def log_forecast(name, temp):
    temps = [t.temp for t in temp]
    if temps:
        forecast_hours = (temp[-1].ts - temp[0].ts).total_seconds() / 3600.0
        logger.info('Forecast %s between %s %s (%s h) %s (mean %s) (mean 48h %s)',
                    name, temp[0].ts, temp[-1].ts, forecast_hours, ' '.join(map(str, temps)), decimal_round(mean(temps)),
                    decimal_round(mean(temps[:48])))
    else:
        logger.info('No forecast from %s')


def forecast_mean_temperature(forecast: Forecast):
    if forecast and forecast.temps:
        cooling_time_buffer_hours = int(cooling_time_buffer_resolved(
            config.COOLING_TIME_BUFFER, config.ALLOWED_MINIMUM_INSIDE_TEMP))
        return mean(t.temp for t in forecast.temps[:cooling_time_buffer_hours])
    else:
        return None


def func_name(func):
    if hasattr(func, '__name__'):
        return func.__name__
    else:
        return func._mock_name


class Temperatures:
    MAX_TS_DIFF_MINUTES = 60

    @classmethod
    def get_temp(cls, functions: list, max_ts_diff=None, **kwargs):
        if max_ts_diff is None:
            max_ts_diff = cls.MAX_TS_DIFF_MINUTES

        temperatures = []

        for func in functions:
            result = func(**kwargs)
            if result:
                temp, ts = result
                if temp is not None:
                    if ts is None:
                        temperatures.append((temp, ts))
                    else:
                        seconds = (arrow.now() - ts).total_seconds()
                        if abs(seconds) < 60 * max_ts_diff:
                            temperatures.append((temp, ts))
                        else:
                            logger.info('Discarding temperature %s, temp: %s, temp time: %s', func_name(func), temp, ts)

        return median(temperatures)


def target_inside_temperature(outside_temp_ts: TempTs,
                              allowed_min_inside_temp: Decimal,
                              minimum_inside_temp,
                              forecast: Union[Forecast, None],
                              cooling_time_buffer=config.COOLING_TIME_BUFFER,
                              extra_info=None) -> Decimal:
    # print('target_inside_temperature', '-' * 50)

    # from pprint import pprint
    # pprint(forecast)

    cooling_time_buffer_hours = cooling_time_buffer_resolved(cooling_time_buffer, outside_temp_ts.temp)
    # logger.info('Buffer is %s h at %s C', cooling_time_buffer_hours, outside_temp_ts.temp)

    if extra_info is not None:
        Auto.add_extra_info(extra_info, 'Buffer is %s h at %s C' % (
            decimal_round(cooling_time_buffer_hours), decimal_round(outside_temp_ts.temp)))

    valid_forecast = []

    if outside_temp_ts:
        valid_forecast.append(outside_temp_ts)

    if forecast and forecast.temps:
        for f in forecast.temps:
            if f.ts > valid_forecast[-1].ts:
                valid_forecast.append(f)

    # if valid_forecast:
    #     outside_after_forecast = mean(t.temp for t in valid_forecast)
    #     while len(valid_forecast) < config.COOLING_TIME_BUFFER:
    #         valid_forecast.append(TempTs(temp=outside_after_forecast, ts=valid_forecast[-1].ts.shift(hours=1)))

    reversed_forecast = list(reversed(valid_forecast))

    # pprint(reversed_forecast)
    # pprint(reversed_forecast[-1].ts)

    iteration_inside_temp = allowed_min_inside_temp
    iteration_ts = arrow.now().shift(hours=cooling_time_buffer_hours)
    # print('iteration_ts', iteration_ts)

    # if reversed_forecast[0].ts < iteration_ts:
    outside_after_forecast = mean(t.temp for t in reversed_forecast)
    # print('outside_after_forecast', outside_after_forecast)
    while iteration_ts > reversed_forecast[0].ts:
        hours_to_forecast_start = Decimal((iteration_ts - reversed_forecast[0].ts).total_seconds() / 3600.0)
        assert hours_to_forecast_start >= 0, hours_to_forecast_start
        this_iteration_hours = min([Decimal(1), hours_to_forecast_start])
        outside_inside_diff = outside_after_forecast - iteration_inside_temp
        temp_drop = config.COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF * outside_inside_diff * this_iteration_hours
        iteration_inside_temp -= temp_drop
        iteration_ts = iteration_ts.shift(hours=float(-this_iteration_hours))

        # from pprint import pprint
        # pprint({
        #     'iteration_ts': iteration_ts,
        #     'temp_drop': temp_drop,
        #     'iteration_inside_temp': iteration_inside_temp,
        #     'this_iteration_hours': this_iteration_hours,
        # })
        # print('-' * 50)

        if iteration_inside_temp < allowed_min_inside_temp:
            iteration_inside_temp = allowed_min_inside_temp
            # print('*' * 20)

    # print('-' * 10, 'start forecast', iteration_ts, iteration_inside_temp)

    for fc in filter(lambda x: x.ts <= iteration_ts, reversed_forecast):
        this_iteration_hours = Decimal((iteration_ts - fc.ts).total_seconds() / 3600.0)
        assert this_iteration_hours >= 0, this_iteration_hours
        outside_inside_diff = fc.temp - iteration_inside_temp
        temp_drop = config.COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF * outside_inside_diff * this_iteration_hours
        # if iteration_inside_temp - temp_drop > allowed_min_inside_temp:
        #     iteration_inside_temp -= temp_drop
        # else:
        #     break

        iteration_inside_temp -= temp_drop
        iteration_ts = fc.ts

        # from pprint import pprint
        # pprint({
        #     'fc': fc,
        #     'temp_drop': temp_drop,
        #     'iteration_inside_temp': iteration_inside_temp,
        #     'this_iteration_hours': this_iteration_hours,
        # })
        # print('-' * 50)

        if iteration_inside_temp < allowed_min_inside_temp:
            iteration_inside_temp = allowed_min_inside_temp
            # print('!' * 20)
            # assert False, iteration_inside_temp

    # print('iteration_ts', iteration_ts)
    # print('target_inside_temperature', iteration_inside_temp)
    return max(iteration_inside_temp, minimum_inside_temp)


def cooling_time_buffer_resolved(cooling_time_buffer, outside_temp):
    try:
        return float(cooling_time_buffer)
    except:
        return float(cooling_time_buffer(outside_temp))


def get_buffer(inside_temp: Decimal, outside_temp_ts: TempTs, allowed_min_inside_temp: Decimal,
               forecast: Union[Forecast, None]) -> Decimal:
    buffer = Decimal(0)  # hours

    # from pprint import pprint

    # if forecast and forecast.temps:
    #     # forecast = forecast[0]  # remove fetch timestamp
    #     # if forecast:
    #     forecast = [(outside_temp, None)] + [f for f in forecast if f[1] > arrow.now()]

    valid_forecast = [outside_temp_ts]

    if forecast and forecast.temps:
        for f in forecast.temps:
            if f.ts > valid_forecast[-1].ts:
                valid_forecast.append(f)

    # TODO: sort by ts

    # pprint(valid_forecast)

    inside_ts = arrow.now().shift(minutes=-5)

    iteration_inside_temp = inside_temp
    # iteration_hours = Decimal(0)
    iteration_temp_ts = None  # TODO: inside timestamp

    for vf in valid_forecast:

        if iteration_temp_ts is None:
            # First round: from inside ts to second forecast ts using the first forecast temp
            iteration_temp_ts = TempTs(temp=vf.temp, ts=inside_ts)
        else:
            this_iteration_hours = Decimal((vf.ts - iteration_temp_ts.ts).total_seconds() / 3600.0)
            inside_outside_diff = iteration_inside_temp - iteration_temp_ts.temp
            temp_drop = config.COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF * inside_outside_diff * this_iteration_hours
            if iteration_inside_temp - temp_drop < allowed_min_inside_temp:
                this_iteration_hours *= (iteration_inside_temp - allowed_min_inside_temp) / temp_drop
                temp_drop = config.COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF * inside_outside_diff * this_iteration_hours

            # from pprint import pprint
            # pprint({
            #     'buffer': buffer,
            #     'iteration_inside_temp': iteration_inside_temp,
            #     'vf': vf,
            #     'iteration_temp_ts': iteration_temp_ts,
            #     'temp_drop': temp_drop,
            #     'this_iteration_hours': this_iteration_hours,
            # })
            # print('-' * 50)

            iteration_inside_temp -= temp_drop
            iteration_temp_ts = vf
            buffer += this_iteration_hours
        # print('1' * 50)

    # if valid_forecast:
    outside_after_forecast = mean(t.temp for t in valid_forecast)

    # print('outside_after_forecast', outside_after_forecast)
    # print('buffer', buffer)

    if outside_after_forecast < allowed_min_inside_temp:
        while (iteration_inside_temp - Decimal('0.001')) > allowed_min_inside_temp:
            this_iteration_hours = Decimal(1)
            inside_outside_diff = iteration_inside_temp - outside_after_forecast
            temp_drop = config.COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF * inside_outside_diff * this_iteration_hours
            if iteration_inside_temp - temp_drop < allowed_min_inside_temp:
                this_iteration_hours *= (iteration_inside_temp - allowed_min_inside_temp) / temp_drop
                temp_drop = config.COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF * inside_outside_diff * this_iteration_hours

            # from pprint import pprint
            # pprint({
            #     'buffer': buffer,
            #     'iteration_inside_temp': iteration_inside_temp,
            #     'iteration_temp_ts': iteration_temp_ts,
            #     'temp_drop': temp_drop,
            #     'this_iteration_hours': this_iteration_hours,
            # })
            # print('-' * 50)

            iteration_inside_temp -= temp_drop
            buffer += this_iteration_hours
    else:
        buffer = 'inf'

    if buffer == 0:
        # TODO: kun buffer on oikeasti nolla, niin palauta nolla
        buffer = 'inf'
    elif isinstance(buffer, Decimal):
        buffer = decimal_round(buffer, 0)

    return buffer


class Controller:
    def __init__(self, kp, ki, i_limit):
        self.kp = kp
        self.ki = ki
        self.i_limit = i_limit
        self.integral = 0
        self.current_time = None

    def reset(self):
        self.integral = 0
        self.current_time = None

    def is_reset(self):
        return self.current_time is None

    def update(self, error):
        logger.debug('controller error %.4f', error)

        p_term = self.kp * error

        new_time = time.time()

        if self.current_time is not None:
            delta_time = Decimal(new_time - self.current_time)
            logger.debug('controller delta_time %.4f', delta_time)
            self.integral += error * delta_time

        self.current_time = new_time

        if self.integral > self.i_limit:
            self.integral = self.i_limit
            logger.debug('controller integral high limit')
        elif self.integral < -self.i_limit:
            self.integral = -self.i_limit
            logger.debug('controller integral low limit')

        i_term = self.ki * self.integral

        logger.debug('controller p_term %.4f', p_term)
        logger.debug('controller i_term %.4f', i_term)

        output = p_term + i_term

        logger.debug('controller output %.4f', output)
        return output


class Auto(State):
    last_command = None
    last_command_send_time = time.time()
    minimum_inside_temp = config.MINIMUM_INSIDE_TEMP
    hysteresis_going_up = False

    controller = Controller(
        Decimal('1.3'),  # from target 4 to target 15, this adds (15-4) * 1.3 == 14.3 to the output
        Decimal(1) / Decimal(3600),
        Decimal(15) / (Decimal(1) / Decimal(3600)))

    @staticmethod
    def clear():
        Auto.last_command = None  # Clear last command so Auto sends command after Manual
        Auto.minimum_inside_temp = config.MINIMUM_INSIDE_TEMP
        Auto.hysteresis_going_up = False
        Auto.controller.reset()

    @staticmethod
    def save_state():
        data = json.dumps({'integral': str(Auto.controller.integral)})
        with orm.db_session:
            saved_state = orm.select(c for c in SavedState).where(name='Auto.controller').first()
            if saved_state:
                saved_state.set(json=data)
            else:
                SavedState(name='Auto.controller', json=data)

    @staticmethod
    def load_state():
        if Auto.controller.is_reset():
            with orm.db_session:
                saved_state = orm.select(c for c in SavedState).where(name='Auto.controller').first()
                if saved_state:
                    as_dict = saved_state.to_dict()
                    try:
                        as_dict['json'] = json.loads(as_dict['json'])
                    except JSONDecodeError:
                        pass
                    else:
                        Auto.controller.integral = Decimal(as_dict['json']['integral'])

    def run(self, payload):
        if payload:
            if payload.get('param') and payload.get('param').get('min_inside_temp') is not None:
                Auto.minimum_inside_temp = Decimal(payload.get('param').get('min_inside_temp'))
                log_temp_info(Auto.minimum_inside_temp)
            else:
                Auto.minimum_inside_temp = config.MINIMUM_INSIDE_TEMP

        minimum_inside_temp = Auto.minimum_inside_temp

        self.load_state()

        next_command, extra_info = self.process(Auto.last_command, minimum_inside_temp)

        if Auto.last_command is not None:
            logger.debug('Last auto command sent %d minutes ago', (time.time() - Auto.last_command_send_time) / 60.0)

        # Send command every now and then even if command has not changed
        force_send_command_time = 60 * 60 * 24

        if Auto.last_command != next_command or time.time() - Auto.last_command_send_time > force_send_command_time:
            Auto.last_command = next_command
            Auto.last_command_send_time = time.time()
            send_ir_signal(next_command, extra_info=extra_info)

        write_log_to_sheet(next_command, extra_info=extra_info)

        self.save_state()

        return get_most_recent_message(once=True)

    @staticmethod
    def process(last_command, minimum_inside_temp):
        extra_info = []
        valid_time = have_valid_time()
        Auto.add_extra_info(extra_info, 'have_valid_time: %s' % valid_time)

        forecast, mean_forecast = Auto.get_forecast(extra_info, valid_time)
        outside_temp_ts = Auto.get_outside(extra_info, mean_forecast)

        if mean_forecast:
            outside_for_target_calc = TempTs(mean_forecast, arrow.now())
        else:
            outside_for_target_calc = outside_temp_ts

        target_inside_temp = target_inside_temperature(outside_for_target_calc,
                                                       config.ALLOWED_MINIMUM_INSIDE_TEMP,
                                                       minimum_inside_temp,
                                                       forecast,
                                                       extra_info=extra_info)

        Auto.add_extra_info(extra_info, 'Target inside temperature: %s' % decimal_round(target_inside_temp, 1))

        hysteresis = Auto.hysteresis(outside_temp_ts.temp, target_inside_temp)
        Auto.add_extra_info(extra_info, 'Hysteresis: %s' % decimal_round(hysteresis))

        inside_temp = Temperatures.get_temp([receive_wc_temperature])[0]
        Auto.add_extra_info(extra_info, 'Inside temperature: %s' % inside_temp)

        if inside_temp is not None:
            target_diff = inside_temp - target_inside_temp
            Auto.add_extra_info(extra_info, 'Inside vs target diff: %s' % decimal_round(target_diff, 2))
            if target_diff < -1:
                logger.warning('Inside vs target diff is less than -1: %s' % decimal_round(target_diff, 2))

        if inside_temp is not None and inside_temp > config.ALLOWED_MINIMUM_INSIDE_TEMP:
            buffer = get_buffer(inside_temp, outside_temp_ts, config.ALLOWED_MINIMUM_INSIDE_TEMP, forecast)
            if buffer is not None:
                if isinstance(buffer, (int, Decimal)):
                    ts = time_str(arrow.utcnow().shift(hours=float(buffer)))
                else:
                    ts = ''
                Auto.add_extra_info(extra_info, 'Current buffer: %s h (%s) to temp %s C' % (
                    buffer, ts, config.ALLOWED_MINIMUM_INSIDE_TEMP))

        if inside_temp is not None:
            if inside_temp < target_inside_temp:
                error = target_inside_temp - inside_temp
                if Auto.controller.integral < 0:
                    Auto.controller.integral = 0
            elif inside_temp > hysteresis:
                error = hysteresis - inside_temp
            else:
                error = 0
        else:
            error = 0

        controller_off_limit = config.COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF * (
                target_inside_temp - outside_temp_ts.temp) * 6

        if inside_temp is not None and inside_temp > hysteresis + controller_off_limit:
            next_command = Commands.off
            Auto.hysteresis_going_up = False
        else:
            target_inside_temp_correction = target_inside_temp + Auto.controller.update(error)

            Auto.add_extra_info(
                extra_info, 'target_inside_temp_correction: %s' % decimal_round(target_inside_temp_correction, 2))

            if Auto.hysteresis_going_up:
                target_inside_temp = hysteresis

            next_command, Auto.hysteresis_going_up = Auto.version_2_next_command(
                inside_temp, outside_temp_ts.temp, target_inside_temp, target_inside_temp_correction)

        return next_command, extra_info

    @staticmethod
    def hysteresis(outside_temp, target_inside_temp):
        hysteresis_add = config.COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF * (target_inside_temp - outside_temp) * 2
        return target_inside_temp + max(hysteresis_add, 0)

    @staticmethod
    def get_forecast(extra_info, valid_time):
        f_temps, f_ts = Temperatures.get_temp([receive_fmi_forecast, receive_yr_no_forecast], max_ts_diff=48 * 60)
        if f_temps and f_ts:
            forecast = Auto.make_forecast(f_temps, f_ts, valid_time)
            log_forecast('get_forecast', forecast.temps)
        else:
            forecast = None
            logger.debug('Forecast %s', forecast)
        mean_forecast = forecast_mean_temperature(forecast)
        Auto.add_extra_info(extra_info, 'Forecast mean: %s' % decimal_round(mean_forecast))
        return forecast, mean_forecast

    @staticmethod
    def make_forecast(temps, ts, valid_time):
        now = arrow.now()
        return Forecast(temps=[TempTs(temp, ts) for temp, ts in temps if not valid_time or ts > now], ts=ts)

    @staticmethod
    def get_outside(extra_info, mean_forecast):
        outside_temp, outside_ts = Temperatures.get_temp([
            receive_ulkoilma_temperature, receive_fmi_temperature, receive_open_weather_map_temperature])
        Auto.add_extra_info(extra_info, 'Outside temperature: %s' % outside_temp)
        if outside_temp is None:
            outside_ts = arrow.now()
            if mean_forecast is not None:
                outside_temp = mean_forecast
                Auto.add_extra_info(extra_info,
                                    'Using mean forecast as outside temp: %s' % decimal_round(mean_forecast))
            else:
                outside_temp = Decimal(-10)
                Auto.add_extra_info(extra_info, 'Using predefined outside temperature: %s' % outside_temp)

        return TempTs(temp=outside_temp, ts=outside_ts)

    @staticmethod
    def version_2_next_command(inside_temp, outside_temp, target_inside_temp, target_inside_temp_correction):
        if inside_temp is not None:
            if outside_temp < target_inside_temp and inside_temp < target_inside_temp:
                hysteresis_going_up = True
                next_command = Commands.find_command_just_above_temp(target_inside_temp_correction)
            else:
                hysteresis_going_up = False
                next_command = Commands.find_command_at_or_just_below_temp(target_inside_temp_correction)
        else:
            if outside_temp < target_inside_temp:
                hysteresis_going_up = True
                next_command = Commands.find_command_just_above_temp(target_inside_temp_correction)
            else:
                hysteresis_going_up = False
                next_command = Commands.find_command_at_or_just_below_temp(target_inside_temp_correction)

        return next_command, hysteresis_going_up

    @staticmethod
    def add_extra_info(extra_info, message):
        logger.info(message)
        extra_info.append(message)

    def nex(self, payload):
        from states.manual import Manual

        if payload:
            if payload['command'] == 'auto':
                return Auto
            else:
                self.clear()
                return Manual
        else:
            return Auto
