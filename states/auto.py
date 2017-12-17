# coding=utf-8
import time
from decimal import Decimal
from functools import wraps
from statistics import mean
from typing import Union

import arrow
import xmltodict
from dateutil import tz

import config
from poller_helpers import Commands, logger, send_ir_signal, timing, get_most_recent_message, get_temp_from_sheet, \
    median, get_url, time_str, write_log_to_sheet, TempTs, Forecast, decimal_round, have_valid_time
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

            # print('\n'.join(reversed(list(str(t.temp) for t in temp))))

            # temp = min(Decimal(t['temperature']['@value']) for t in time_elements)
            # min_datetime = arrow.get(min(t['@from'] for t in time_elements)).replace(tzinfo=timezone)
            # max_datetime = arrow.get(max(t['@to'] for t in time_elements)).replace(tzinfo=timezone)
            ts = arrow.now()

            logger.info('Forecast: %s', temp)

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


def receive_yr_no_forecast_mean_temperature(forecast: Forecast):
    if forecast and forecast.temps:
        return mean(t.temp for t in forecast.temps)
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
                              forecast: Union[Forecast, None],
                              cooling_time_buffer=config.COOLING_TIME_BUFFER,
                              extra_info=None) -> Decimal:
    # print('target_inside_temperature', '-' * 50)

    # from pprint import pprint
    # pprint(forecast)

    try:
        cooling_time_buffer_hours = float(cooling_time_buffer)
    except:
        cooling_time_buffer_hours = float(cooling_time_buffer(outside_temp_ts.temp))

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
    return max(iteration_inside_temp, config.MINIMUM_INSIDE_TEMP)


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
        buffer = decimal_round(buffer)

    return buffer


class Auto(State):
    last_command = None
    last_command_send_time = time.time()

    def run(self, payload, version=2):
        if version == 1:
            next_command, extra_info = self.version_1()
        elif version == 2:
            next_command, extra_info = self.version_2(Auto.last_command, Auto.last_command_send_time)
        else:
            raise ValueError(version)

        if Auto.last_command is not None:
            logger.debug('Last auto command sent %d minutes ago', (time.time() - Auto.last_command_send_time) / 60.0)

        # Send command every now and then even if command has not changed
        force_send_command_time = 60 * 60 * 8
        # force_send_command_time = 60 * 60 * 24 * 7  # 7 days

        if Auto.last_command != next_command or time.time() - Auto.last_command_send_time > force_send_command_time:
            Auto.last_command = next_command
            Auto.last_command_send_time = time.time()
            send_ir_signal(next_command, extra_info=extra_info)

        write_log_to_sheet(next_command, extra_info=extra_info)

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
    def version_2(last_command, last_command_send_time):
        extra_info = []
        valid_time = have_valid_time()
        Auto.add_extra_info(extra_info, 'have_valid_time: %s' % valid_time)

        forecast, mean_forecast = Auto.get_forecast(extra_info)
        outside_temp_ts = Auto.get_outside(extra_info, forecast)

        if mean_forecast:
            outside_for_target_calc = TempTs(mean_forecast, arrow.now())
        else:
            outside_for_target_calc = outside_temp_ts

        target_inside_temp = target_inside_temperature(outside_for_target_calc,
                                                       config.ALLOWED_MINIMUM_INSIDE_TEMP,
                                                       forecast,
                                                       extra_info=extra_info)

        Auto.add_extra_info(extra_info, 'Target inside temperature: %s' % decimal_round(target_inside_temp, 1))

        if last_command and last_command != Commands.off:
            target_inside_temp += Decimal('0.1')
        else:
            target_inside_temp -= Decimal('0.1')

        Auto.add_extra_info(extra_info, 'Hysteresis: %s' % decimal_round(target_inside_temp))

        inside_temp = Temperatures.get_temp([receive_wc_temperature])[0]
        Auto.add_extra_info(extra_info, 'Inside temperature: %s' % inside_temp)

        if inside_temp is not None and inside_temp > config.ALLOWED_MINIMUM_INSIDE_TEMP:
            buffer = get_buffer(inside_temp, outside_temp_ts, config.ALLOWED_MINIMUM_INSIDE_TEMP, forecast)
            if buffer is not None:
                if isinstance(buffer, (int, Decimal)):
                    ts = time_str(arrow.utcnow().shift(hours=float(buffer)))
                else:
                    ts = ''
                Auto.add_extra_info(extra_info, 'Current buffer: %s h (%s) to temp %s C' % (
                    buffer, ts, config.ALLOWED_MINIMUM_INSIDE_TEMP))

        next_command = Auto.version_2_next_command(inside_temp, outside_temp_ts.temp, target_inside_temp)

        # if last_command and 'heat' in last_command and next_command == Commands.off and (time.time() - last_command_send_time) / 60.0 < 60:
        #     next_command = last_command

        if inside_temp is not None and next_command == Commands.off:
            time_until_heat = get_buffer(inside_temp, outside_temp_ts, target_inside_temp, forecast)
            if time_until_heat is not None:
                if isinstance(time_until_heat, (int, Decimal)):
                    ts = time_str(arrow.utcnow().shift(hours=float(time_until_heat)))
                else:
                    ts = ''
                Auto.add_extra_info(extra_info, 'Current time_until_heat: %s h (%s) to temp %s C' % (
                    time_until_heat, ts, decimal_round(target_inside_temp)))

        return next_command, extra_info

    @staticmethod
    def get_forecast(extra_info):
        f_temps, f_ts = Temperatures.get_temp([receive_yr_no_forecast], max_ts_diff=48 * 60)
        if f_temps and f_ts:
            forecast = Forecast(temps=[TempTs(temp, ts) for temp, ts in f_temps], ts=f_ts)
        else:
            forecast = None
        logger.debug('Forecast %s', forecast)
        mean_forecast = receive_yr_no_forecast_mean_temperature(forecast)
        Auto.add_extra_info(extra_info, 'Forecast mean: %s' % decimal_round(mean_forecast))
        return forecast, mean_forecast

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
    def version_2_next_command(inside_temp, outside_temp, target_inside_temp):
        if inside_temp is not None:
            if outside_temp < target_inside_temp and inside_temp < target_inside_temp:
                next_command = Commands.find_command_just_above_temp(target_inside_temp)
            else:
                next_command = Commands.find_command_at_or_just_below_temp(target_inside_temp)
        else:
            if outside_temp < target_inside_temp:
                next_command = Commands.find_command_just_above_temp(target_inside_temp)
            else:
                next_command = Commands.find_command_at_or_just_below_temp(target_inside_temp)

        return next_command

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
                Auto.last_command = None  # Clear last command so Auto sends command after Manual
                return Manual
        else:
            return Auto
