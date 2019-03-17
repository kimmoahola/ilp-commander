from decimal import Decimal
from typing import Tuple, Optional

import arrow
import xmltodict

import config
from poller_helpers import TempTs, decimal_round, get_url, timing, logger
from states.auto_pipeline_pipes.helpers import get_temp, caching


PREDEFINED_OUTSIDE_TEMP = Decimal(-10)


def get_temp_from_temp_api(host_and_port, table_name) -> Tuple[Optional[Decimal], Optional[str]]:
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
                temp = Decimal(result_json['temperature'])

    return temp, ts


@timing
@caching(cache_name='ulkoilma')
def receive_ulkoilma_temperature() -> Tuple[Optional[Decimal], Optional[arrow.Arrow]]:
    temp, ts = get_temp_from_temp_api(
        config.TEMP_API_OUTSIDE.get('host_and_port'), config.TEMP_API_OUTSIDE.get('table_name'))

    if ts is not None:
        ts = arrow.get(ts).to(config.TIMEZONE)

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


@timing
@caching(cache_name='fmi')
def receive_fmi_temperature() -> Tuple[Optional[Decimal], Optional[arrow.Arrow]]:
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
                    if not temp.is_finite():
                        raise TypeError()
            except (KeyError, TypeError):
                temp, ts = None, None

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


@timing
@caching(cache_name='open_weather_map')
def receive_open_weather_map_temperature() -> Tuple[Optional[Decimal], Optional[arrow.Arrow]]:
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
            temp = decimal_round(result_json['main']['temp'])
            ts = arrow.get(result_json['dt']).to(config.TIMEZONE)

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


def get_outside(add_extra_info, mean_forecast, **kwargs):
    outside_temp, outside_ts = get_temp([
        receive_ulkoilma_temperature, receive_fmi_temperature, receive_open_weather_map_temperature])
    add_extra_info('Outside temperature: %s' % outside_temp)
    if outside_temp is None:
        valid_outside = False
        outside_ts = arrow.now()
        if mean_forecast is not None:
            outside_temp = mean_forecast
            add_extra_info('Using mean forecast as outside temp: %s' % decimal_round(mean_forecast))
        else:
            outside_temp = PREDEFINED_OUTSIDE_TEMP
            add_extra_info('Using predefined outside temperature: %s' % outside_temp)
    else:
        valid_outside = True

    return {'outside_temp_ts': TempTs(temp=outside_temp, ts=outside_ts), 'valid_outside': valid_outside}
