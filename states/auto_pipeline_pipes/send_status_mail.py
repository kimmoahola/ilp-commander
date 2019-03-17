from typing import List

from poller_helpers import email


def log_status(add_extra_info, valid_time: bool, forecast, valid_outside: bool, inside_temp,
               target_inside_temp, controller_i_max: bool):
    status: List[str] = []

    if not valid_time:
        status.append('no valid time')
    if not forecast:
        status.append('no forecast')
    if not valid_outside:
        status.append('no outside temp')

    if inside_temp is None:
        status.append('no inside temp')
    elif inside_temp <= target_inside_temp - 1:
        status.append('inside is 1 degree or more below target')

    if controller_i_max:
        status.append('controller i term at max')

    if not status:
        status.append('ok')

    status_str = ', '.join(status)
    add_extra_info('Status: %s' % status_str)

    return status_str


def send_status_mail(add_extra_info, have_valid_time, forecast, valid_outside, inside_temp,
                     target_inside_temp, persistent_data, **kwargs):

    controller = persistent_data.get('controller')
    last_status_email_sent = persistent_data.get('last_status_email_sent')

    status = log_status(add_extra_info, have_valid_time, forecast, valid_outside, inside_temp, target_inside_temp,
                        controller.integral >= controller.i_high_limit)

    if last_status_email_sent != status:
        if last_status_email_sent is not None:
            email('Status', status)
        last_status_email_sent = status

    return {}, {'last_status_email_sent': last_status_email_sent}
