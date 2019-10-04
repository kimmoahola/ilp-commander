import time
from decimal import Decimal
from typing import List, Tuple, Optional

from poller_helpers import logger, decimal_round


class Controller:
    def __init__(self, kp: Decimal, ki: Decimal, kd: Decimal) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.i_high_limit = Decimal(0)
        self.i_low_limit = Decimal(0)
        self.integral = Decimal(0)
        self.current_time: float = None
        self.past_errors: List[Tuple[Decimal, Decimal]] = []  # time and error

    def reset(self):
        self.integral = Decimal(0)
        self.current_time: float = None
        self.reset_past_errors()

    def reset_past_errors(self):
        self.past_errors: List[Tuple[Decimal, Decimal]] = []  # time and error

    def is_reset(self):
        return self.current_time is None

    def set_i_low_limit(self, value):
        logger.debug('controller set i low limit %.4f', value)
        self.i_low_limit = value

    def set_i_high_limit(self, value):
        logger.debug('controller set i high limit %.4f', value)
        self.i_high_limit = value

    def set_integral_to_lower_limit(self):
        self.integral = self.i_low_limit
        logger.debug('controller integral low limit %.4f', self.i_low_limit)

    def _update_past_errors(self, error: Decimal):
        self.past_errors.append((Decimal(time.time()), error))

        hours = Decimal(3600) * Decimal(2)
        past_error_time_limit = Decimal(time.time()) - hours

        self.past_errors = [
            past_error
            for past_error
            in self.past_errors
            if past_error[0] >= past_error_time_limit
        ]

    def _past_error_slope_per_second(self) -> Decimal:
        n = Decimal(len(self.past_errors))
        sum_xy = Decimal(sum(p[0] * p[1] for p in self.past_errors))
        sum_x = Decimal(sum(p[0] for p in self.past_errors))
        sum_y = Decimal(sum(p[1] for p in self.past_errors))
        sum_x2 = Decimal(sum(p[0] * p[0] for p in self.past_errors))
        divider = (n * sum_x2 - sum_x * sum_x)
        if divider == 0:
            return Decimal(0)
        return (n * sum_xy - sum_x * sum_y) / divider

    def update(self, error: Optional[Decimal], error_without_hysteresis: Optional[Decimal]) -> Tuple[Decimal, str]:
        if error is None:
            error = Decimal(0)
        else:
            self._update_past_errors(error_without_hysteresis)

        logger.debug('controller error %.4f', error)

        p_term = self.kp * error

        new_time = time.time()

        error_slope_per_second = self._past_error_slope_per_second()
        error_slope_per_hour = error_slope_per_second * Decimal(3600)

        error_slope_per_hour = min(error_slope_per_hour, Decimal('0.5'))
        error_slope_per_hour = max(error_slope_per_hour, Decimal('-0.5'))

        if self.current_time is not None:
            delta_time = Decimal(new_time - self.current_time)
            logger.debug('controller delta_time %.4f', delta_time)

            if error > 0 and error_slope_per_hour >= Decimal('-0.05') or error < 0 and error_slope_per_hour <= 0:
                integral_update_value = self.ki * error * delta_time / Decimal(3600)
                logger.info('Updating integral with %.4f', integral_update_value)
                self.integral += integral_update_value
            else:
                logger.info('Not updating integral')

        self.current_time = new_time

        if self.integral > self.i_high_limit:
            self.integral = self.i_high_limit
            logger.debug('controller integral high limit %.4f', self.i_high_limit)
        elif self.integral < self.i_low_limit:
            self.set_integral_to_lower_limit()

        i_term = self.integral

        d_term = self.kd * error_slope_per_hour

        logger.debug('controller p_term %.4f', p_term)
        logger.debug('controller i_term %.4f', i_term)
        logger.debug('controller d_term %.4f', d_term)
        past_errors_for_log = [(decimal_round(p[0]), decimal_round(p[1])) for p in self.past_errors]
        logger.debug('controller past errors %s', past_errors_for_log)

        output = p_term + i_term + d_term

        logger.debug('controller output %.4f', output)
        return output, self.log(error, p_term, i_term, d_term, error_slope_per_hour, self.i_low_limit, self.i_high_limit, output)

    @staticmethod
    def log(error, p_term, i_term, d_term, error_slope_per_hour, i_low_limit, i_high_limit, output) -> str:
        return 'e %.2f, p %.2f, i %.2f (%.2f-%.2f), d %.2f slope %.2f, out %.2f' % (
            error, p_term, i_term, i_low_limit, i_high_limit, d_term, error_slope_per_hour, output)
