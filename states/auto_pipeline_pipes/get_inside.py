from decimal import Decimal
from typing import Optional, Tuple

import arrow
from dateutil import tz

import config
from poller_helpers import timing, get_temp_from_sheet, logger
from states.auto_pipeline_pipes.helpers import get_temp, caching


@timing
@caching(cache_name='inside')
def receive_inside_temperature() -> Tuple[Optional[Decimal], Optional[arrow.Arrow]]:
    temp, ts = get_temp_from_sheet(sheet_title=config.INSIDE_SHEET_TITLE)

    if ts is not None:
        ts = arrow.get(ts, 'DD.MM.YYYY klo HH:mm').replace(tzinfo=tz.gettz(config.TIMEZONE))

    logger.info('temp:%s ts:%s', temp, ts)
    return temp, ts


def get_inside(add_extra_info, **kwargs):
    inside_temp = get_temp([receive_inside_temperature])[0]
    add_extra_info('Inside temperature: %s' % inside_temp)

    return {'inside_temp': inside_temp}

