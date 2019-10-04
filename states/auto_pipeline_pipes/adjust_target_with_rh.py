import math
from decimal import Decimal
from typing import Tuple, Optional

import arrow
import xmltodict

import config
from poller_helpers import decimal_round, get_url, timing, logger
from states.auto_pipeline_pipes.helpers import caching, get_temp


@timing
@caching(cache_name='fmi_dew_point')
def receive_fmi_dew_point() -> Tuple[Optional[Decimal], Optional[arrow.Arrow]]:
    dew_points = []
    ts = None

    try:
        starttime = arrow.now().shift(hours=-3).to('UTC').format('YYYY-MM-DDTHH:mm:ss') + 'Z'
        result = get_url(
            'http://data.fmi.fi/fmi-apikey/{key}/wfs?request=getFeature&storedquery_id=fmi::observations::weather'
            '::simple&place={place}&parameters=td&starttime={starttime}'.format(
                key=config.FMI_KEY, place=config.FMI_LOCATION, starttime=starttime))
    except Exception as e:
        logger.exception(e)
    else:
        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            try:
                wfs_member = xmltodict.parse(result.content).get('wfs:FeatureCollection', {}).get('wfs:member')

                for member in wfs_member:
                    temp_data = member.get('BsWfs:BsWfsElement')
                    if temp_data and 'BsWfs:Time' in temp_data and 'BsWfs:ParameterValue' in temp_data:
                        ts = arrow.get(temp_data['BsWfs:Time']).to(config.TIMEZONE)
                        dew_points.append(Decimal(temp_data['BsWfs:ParameterValue']))
            except (KeyError, TypeError):
                pass

    if dew_points:
        dew_point = sum(dew_points) / len(dew_points)
    else:
        dew_point = None
        ts = None

    logger.info('dew_point:%s ts:%s', dew_point, ts)
    return dew_point, ts


def estimate_temperature_with_rh(dew_point, rh):
    a = Decimal('243.04')
    b = Decimal('17.625')
    rh_log = Decimal(math.log(rh))
    return a * (((b * dew_point) / (a + dew_point)) - rh_log) / (b + rh_log - ((b * dew_point) / (a + dew_point)))


def adjust_target_with_rh(add_extra_info, target_inside_temp, **kwargs):
    dew_point, ts = get_temp([receive_fmi_dew_point], max_ts_diff=6 * 60)
    add_extra_info('Dew point: %s' % decimal_round(dew_point))

    if dew_point is not None:
        min_temp_with_80_rh = estimate_temperature_with_rh(dew_point, Decimal('0.8'))
        add_extra_info('Temp with 80%% RH: %s' % decimal_round(min_temp_with_80_rh, 1))

        target_inside_temp = max(target_inside_temp, min_temp_with_80_rh)

    add_extra_info('Target inside temperature: %s' % decimal_round(target_inside_temp, 1))

    return {'target_inside_temp': target_inside_temp}
