from decimal import Decimal
from statistics import mean
from typing import Union, Optional, Tuple, List

import arrow
import xmltodict

import config
from poller_helpers import Forecast, TempTs, decimal_round, timing, get_url, logger
from states.auto_pipeline_pipes.helpers import get_temp, caching, forecast_mean_temperature


@timing
@caching(cache_name='yr.no')
def receive_yr_no_forecast() -> Tuple[Optional[List[TempTs]], Optional[arrow.Arrow]]:
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
def receive_fmi_forecast() -> Tuple[Optional[List[TempTs]], Optional[arrow.Arrow]]:
    temp, ts = None, None

    try:
        endtime = arrow.now().shift(hours=63).to('UTC').format('YYYY-MM-DDTHH:mm:ss') + 'Z'
        result = get_url(
            'https://opendata.fmi.fi/wfs?request=getFeature&'
            'storedquery_id=fmi::forecast::harmonie::surface::point::simple&'
            'place={place}&parameters=temperature&endtime={endtime}'.format(
                place=config.FMI_LOCATION, endtime=endtime))
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


def log_forecast(name, temp) -> None:
    temps = [t.temp for t in temp]
    if temps:
        forecast_hours = (temp[-1].ts - temp[0].ts).total_seconds() / 3600.0
        logger.info('Forecast %s between %s %s (%s h) %s (mean %s) (mean 48h %s)',
                    name, temp[0].ts, temp[-1].ts, forecast_hours, ' '.join(map(str, temps)), decimal_round(mean(temps)),
                    decimal_round(mean(temps[:48])))
    else:
        logger.info('No forecast from %s')


def make_forecast(temps, ts, valid_time):
    now = arrow.now()
    return Forecast(temps=[TempTs(temp, ts) for temp, ts in temps if not valid_time or ts > now], ts=ts)


def get_forecast(add_extra_info, have_valid_time, **kwargs):
    f_temps, f_ts = get_temp([receive_fmi_forecast, receive_yr_no_forecast], max_ts_diff=48 * 60)
    if f_temps and f_ts:
        forecast = make_forecast(f_temps, f_ts, have_valid_time)
        log_forecast('get_forecast', forecast.temps)
    else:
        forecast = None
        logger.debug('Forecast %s', forecast)
    mean_forecast = forecast_mean_temperature(forecast)
    add_extra_info('Forecast 24 h mean: %s' % decimal_round(mean_forecast))
    return {'forecast': forecast, 'mean_forecast': mean_forecast}
