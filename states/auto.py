# coding=utf-8
import time
from decimal import Decimal
from functools import wraps
from statistics import mean

import arrow
import xmltodict
from dateutil import tz

import config
from poller_helpers import Commands, logger, send_ir_signal, timing, get_most_recent_message, get_temp_from_sheet, \
    median, get_url
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
    temp, ts = get_temp_from_sheet(sheet_index=0)

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
            wfs_member = xmltodict.parse(result.content).get('wfs:FeatureCollection', {}).get('wfs:member')
            if wfs_member:
                temp_data = wfs_member[-1].get('BsWfs:BsWfsElement')
                if temp_data and 'BsWfs:Time' in temp_data and 'BsWfs:ParameterValue' in temp_data:
                    ts = arrow.get(temp_data['BsWfs:Time']).to(config.TIMEZONE)
                    temp = Decimal(temp_data['BsWfs:ParameterValue'])

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
def receive_yr_no_forecast_min_temperature():
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

            time_elements = [
                t
                for t
                in d['weatherdata']['forecast']['tabular']['time']
            ]

            temp = min(Decimal(t['temperature']['@value']) for t in time_elements)
            min_datetime = arrow.get(min(t['@from'] for t in time_elements)).replace(tzinfo=timezone)
            max_datetime = arrow.get(max(t['@to'] for t in time_elements)).replace(tzinfo=timezone)
            ts = arrow.now()

            logger.info('Min forecast temp: %s between %s and %s', temp, min_datetime, max_datetime)

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


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


def target_inside_temperature(outside_temp: Decimal, allowed_min_inside_temp: Decimal):

    def foo(result: Decimal, count: int) -> Decimal:
        if count > 0:
            inside_outside_diff = mean([result - outside_temp, allowed_min_inside_temp - outside_temp])
            new_result = \
                config.COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF \
                * inside_outside_diff \
                * config.COOLING_TIME_BUFFER \
                + allowed_min_inside_temp
            return foo(new_result, count - 1)
        return result

    return max(foo(allowed_min_inside_temp, 3), config.MINIMUM_INSIDE_TEMP)


class Auto(State):

    min_forecast_temp = None
    last_command = None
    last_command_send_time = time.time()

    def run(self, payload, version=2):
        if version == 1:
            next_command, extra_info = self.version_1()
        elif version == 2:
            next_command, extra_info = self.version_2()
        else:
            raise ValueError(version)

        if Auto.last_command is not None:
            logger.debug('Last auto command sent %d minutes ago', (time.time() - Auto.last_command_send_time) / 60.0)

        # Send command every now and then even if command has not changed
        force_send_command_time = 60 * 60 * 24 * 7  # 7 days

        if Auto.last_command != next_command or time.time() - Auto.last_command_send_time > force_send_command_time:
            Auto.last_command = next_command
            Auto.last_command_send_time = time.time()
            send_ir_signal(next_command, extra_info=extra_info)

        return get_most_recent_message(once=True)

    @staticmethod
    def version_1():
        inside_temp = Temperatures.get_temp([receive_wc_temperature])[0]
        logger.info('Inside temperature: %s', inside_temp)
        extra_info = ['Inside temperature: %s' % inside_temp]

        if inside_temp is None or inside_temp < 8:

            outside_temp = Temperatures.get_temp([
                receive_ulkoilma_temperature, receive_fmi_temperature, receive_open_weather_map_temperature])[0]

            extra_info.append('Outside temperature: %s' % outside_temp)

            if outside_temp is not None:
                logger.info('Outside temperature: %.1f', outside_temp)

                if outside_temp > 0:
                    next_command = Commands.off
                elif 0 >= outside_temp > -15:
                    next_command = Commands.heat8
                elif -15 >= outside_temp > -20:
                    next_command = Commands.heat10
                elif -20 >= outside_temp > -25:
                    next_command = Commands.heat16
                else:
                    next_command = Commands.heat20

            else:
                next_command = Commands.heat16  # Don't know the temperature so heat up just in case
                logger.error('Got no temperatures at all. Setting %s', next_command)
                extra_info.append('Got no temperatures at all.')

        else:
            next_command = Commands.off  # No need to heat

        return next_command, extra_info

    @staticmethod
    def version_2():
        Auto.min_forecast_temp = Temperatures.get_temp([receive_yr_no_forecast_min_temperature], max_ts_diff=48 * 60)[0]
        allowed_min_inside_temp = Decimal(1)
        extra_info = ['Forecast min temperature: %s' % Auto.min_forecast_temp]

        outside_temp = Temperatures.get_temp([
            receive_ulkoilma_temperature, receive_fmi_temperature, receive_open_weather_map_temperature])[0]
        logger.info('Outside temperature: %s', outside_temp)
        extra_info.append('Outside temperature: %s' % outside_temp)

        if outside_temp is None:
            if Auto.min_forecast_temp is not None:
                outside_temp = Auto.min_forecast_temp
                logger.info('Using forecast: %s', Auto.min_forecast_temp)
                extra_info.append('Using forecast: %s' % Auto.min_forecast_temp)
            else:
                outside_temp = Decimal(-10)
                logger.info('Using predefined outside temperature: %s', outside_temp)
                extra_info.append('Using predefined outside temperature: %s' % outside_temp)

        target_inside_temp = target_inside_temperature(outside_temp, allowed_min_inside_temp)
        logger.info('Target inside temperature: %s', target_inside_temp)
        extra_info.append('Target inside temperature: %s' % target_inside_temp.quantize(Decimal('.1')))

        inside_temp = Temperatures.get_temp([receive_wc_temperature])[0]
        logger.info('Inside temperature: %s', inside_temp)
        extra_info.append('Inside temperature: %s' % inside_temp)

        if inside_temp is not None and outside_temp is not None and inside_temp > outside_temp:
            inside_outside_diff = mean([inside_temp - outside_temp, allowed_min_inside_temp - outside_temp])
            if inside_outside_diff != 0:
                buffer = (inside_temp - allowed_min_inside_temp) / (
                    config.COOLING_RATE_PER_HOUR_PER_TEMPERATURE_DIFF * inside_outside_diff)
                if buffer >= 0:
                    buffer = buffer.quantize(Decimal('.1'))
                    logger.info('Current buffer: %s h', buffer)
                    extra_info.append('Current buffer: %s h' % buffer)

        if inside_temp is not None:
            if outside_temp < target_inside_temp and inside_temp < target_inside_temp:
                next_command = Commands.find_command_just_above_temp(target_inside_temp)
            else:
                next_command = Commands.off
        else:
            if outside_temp < target_inside_temp:
                next_command = Commands.find_command_just_above_temp(target_inside_temp)
            else:
                next_command = Commands.off

        return next_command, extra_info

    def nex(self, payload):
        from states.manual import Manual

        if payload:
            if payload['command'] == 'auto':
                return Auto
            else:
                Auto.last_command = None  # Clear last command so Auto sends command after Manual
                return Manual
        else:
            return Auto
