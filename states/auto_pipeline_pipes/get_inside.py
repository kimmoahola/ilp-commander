from decimal import Decimal
from typing import Optional, Tuple

import arrow

import config
from poller_helpers import timing, get_from_smarttings
from states.auto_pipeline_pipes.helpers import caching, get_temp


@timing
@caching(cache_name='smartthings')
def receive_inside_temperature() -> Tuple[Optional[Decimal], Optional[arrow.Arrow]]:
    return get_from_smarttings(config.SMARTTHINGS_DEVICE_ID)


def get_inside(add_extra_info, **kwargs):
    inside_temp = get_temp([receive_inside_temperature], max_ts_diff=120)[0]
    add_extra_info('Inside temperature: %s' % inside_temp)

    return {'inside_temp': inside_temp}
