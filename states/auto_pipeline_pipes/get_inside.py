import config
from poller_helpers import get_from_smartthings
from states.auto_pipeline_pipes.helpers import get_temp


def get_inside(add_extra_info, **kwargs):
    for device_id in config.SMARTTHINGS_INSIDE_DEVICE_IDS:
        inside_temp = get_temp([get_from_smartthings], max_ts_diff=120, device_id=device_id)[0]
        if inside_temp:
            break

    add_extra_info('Inside temperature: %s' % inside_temp)
    return {'inside_temp': inside_temp}
