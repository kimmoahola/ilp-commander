from decimal import Decimal
from statistics import mean
from typing import Union

import arrow

import config
from poller_helpers import decimal_round, Forecast, TempTs, logger
from states.auto_pipeline_pipes.helpers import forecast_mean_temperature


def cooling_time_buffer_resolved(cooling_time_buffer, outside_temp, forecast: Union[Forecast, None]) -> Decimal:
    try:
        return Decimal(cooling_time_buffer)
    except:
        buffer = Decimal(20)

        for i in range(3):
            forecast_mean = forecast_mean_temperature(forecast, buffer)
            if forecast_mean is None:
                forecast_mean = outside_temp

            buffer = Decimal(cooling_time_buffer(forecast_mean))

        return buffer


def target_inside_temp(add_extra_info,
                       mean_forecast,
                       outside_temp_ts: TempTs,
                       forecast: Union[Forecast, None],
                       persistent_data,
                       **kwargs):

    minimum_inside_temp = persistent_data.get('minimum_inside_temp')
    allowed_min_inside_temp = config.ALLOWED_MINIMUM_INSIDE_TEMP
    cooling_time_buffer = config.COOLING_TIME_BUFFER

    if mean_forecast:
        outside_for_target_calc = TempTs(mean_forecast, arrow.now())
    else:
        outside_for_target_calc = outside_temp_ts

    # print('target_inside_temperature', '-' * 50)

    # from pprint import pprint
    # pprint(forecast)

    cooling_time_buffer_hours = cooling_time_buffer_resolved(cooling_time_buffer, outside_for_target_calc.temp, forecast)

    add_extra_info('Buffer is %s h at %s C' % (
        decimal_round(cooling_time_buffer_hours), decimal_round(outside_for_target_calc.temp)))

    valid_forecast = []

    if outside_for_target_calc:
        valid_forecast.append(outside_for_target_calc)

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
    iteration_ts = arrow.now().shift(hours=float(cooling_time_buffer_hours))
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

        if outside_after_forecast <= -17:
            # When outside temp is about -17 or colder, then the pump heating power will decrease a lot
            logger.debug('Forecast temp <= -17: %.1f' % outside_after_forecast)
            temp_drop *= 2

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

        if fc.temp <= -17:
            # When outside temp is about -17 or colder, then the pump heating power will decrease a lot
            logger.debug('Forecast temp <= -17: %.1f' % fc.temp)
            temp_drop *= 2

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
    return {'target_inside_temp': max(iteration_inside_temp, minimum_inside_temp)}
