from decimal import Decimal
from typing import Optional, Tuple

import arrow

import config
from poller_helpers import timing, get_from_lambda_url
from states.auto_pipeline_pipes.helpers import get_temp


@timing
def receive_inside_temperature() -> Tuple[Optional[Decimal], Optional[arrow.Arrow]]:
    return get_from_lambda_url(config.INSIDE_TEMP_ENDPOINT)


def get_inside(add_extra_info, **kwargs):
    inside_temp = get_temp([receive_inside_temperature])[0]
    add_extra_info('Inside temperature: %s' % inside_temp)

    return {'inside_temp': inside_temp}
