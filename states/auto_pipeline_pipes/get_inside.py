from decimal import Decimal
from typing import Optional, Tuple

import arrow

import config
from poller_helpers import timing, get_from_smartthings
from states.auto_pipeline_pipes.helpers import caching, get_temp


@timing
@caching(cache_name='smartthings')
def receive_inside_temperature() -> Tuple[Optional[Decimal], Optional[arrow.Arrow]]:
    for device_id in config.SMARTTHINGS_INSIDE_DEVICE_IDS:
        temp, ts = get_from_smartthings(device_id)
        if temp and ts:
            return temp, ts

    return None, None


def get_inside(add_extra_info, **kwargs):
    inside_temp = get_temp([receive_inside_temperature], max_ts_diff=120)[0]
    add_extra_info('Inside temperature: %s' % inside_temp)

    return {'inside_temp': inside_temp}
