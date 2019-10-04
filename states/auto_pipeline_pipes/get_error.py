from decimal import Decimal
from typing import Optional


def calc_error(target_inside_temp: Decimal, inside_temp: Optional[Decimal], hyst: Decimal) -> Optional[Decimal]:
    if inside_temp is not None:
        error = target_inside_temp - inside_temp
        error -= max([min([error, Decimal(0)]), -hyst])
    else:
        error = None

    return error


def get_error(target_inside_temp, inside_temp, hysteresis, **kwargs):
    error = calc_error(target_inside_temp, inside_temp, hysteresis)
    error_without_hysteresis = calc_error(target_inside_temp, inside_temp, Decimal(0))

    return {'error': error, 'error_without_hysteresis': error_without_hysteresis}
