from decimal import Decimal
from functools import wraps
from statistics import mean
from typing import Dict, Tuple, Any, Optional, Union

import arrow

import config
from poller_helpers import median, logger, Forecast


def func_name(func):
    if hasattr(func, '__name__'):
        return func.__name__
    else:
        return func._mock_name


def get_temp(functions: list, max_ts_diff=None, **kwargs):

    MAX_TS_DIFF_MINUTES = 60

    if max_ts_diff is None:
        max_ts_diff = MAX_TS_DIFF_MINUTES

    temperatures = []

    for func in functions:
        result = func(**kwargs)
        if result:
            temp, ts = result
            if temp is not None:
                if ts is None:
                    temperatures.append((temp, ts))
                else:
                    seconds = (arrow.now() - ts).total_seconds()
                    if abs(seconds) < 60 * max_ts_diff:
                        temperatures.append((temp, ts))
                    else:
                        logger.info('Discarding temperature %s, temp: %s, temp time: %s', func_name(func), temp, ts)

    return median(temperatures)


class RequestCache:
    _cache: Dict[str, Tuple[arrow.Arrow, arrow.Arrow, Any]] = {}

    @classmethod
    def put(cls, name, stale_after_if_ok, stale_after_if_failed, content):
        cls._cache[name] = (stale_after_if_ok, stale_after_if_failed, content)

    @classmethod
    def get(cls, name, stale_check='ok') -> Optional[Any]:
        if name in cls._cache:
            stale_after_if_ok, stale_after_if_failed, content = cls._cache[name]

            if stale_check == 'ok' and arrow.now() <= stale_after_if_ok:
                return content
            elif stale_check == 'failed' and arrow.now() <= stale_after_if_failed:
                return content

        return None

    @classmethod
    def reset(cls):
        cls._cache.clear()


def caching(cache_name):
    def caching_inner(f):
        @wraps(f)
        def caching_wrap(*args, **kw):
            rq = RequestCache()
            result = rq.get(cache_name)
            if result:
                logger.debug('func:%r args:[%r, %r] cache hit with result: %r' % (f.__name__, args, kw, result))
            else:
                logger.debug('func:%r args:[%r, %r] cache miss' % (f.__name__, args, kw))
                try:
                    result = f(*args, **kw)
                except Exception as e:
                    logger.exception(e)
                    result = None
                if result and result[1] is not None:  # result[1] == timestamp
                    temp, ts = result
                    logger.debug('func:%r args:[%r, %r] storing with result: %r' % (f.__name__, args, kw, result))
                    stale_after_if_ok = ts.shift(
                        minutes=config.CACHE_TIMES.get(cache_name, {}).get('if_ok', 60))
                    stale_after_if_failed = ts.shift(
                        minutes=config.CACHE_TIMES.get(cache_name, {}).get('if_failed', 120))
                    rq.put(cache_name, stale_after_if_ok, stale_after_if_failed, result)
                else:
                    result = rq.get(cache_name, stale_check='failed')
                    if result:
                        logger.debug('func:%r args:[%r, %r] failed and returning old result: %r' % (
                            f.__name__, args, kw, result))
                    else:
                        logger.debug('func:%r args:[%r, %r] failed and no result in cache' % (f.__name__, args, kw))
            return result
        return caching_wrap
    return caching_inner


def forecast_mean_temperature(forecast: Forecast, hours: Union[int, Decimal] = 24) -> Optional[Decimal]:
    if forecast and forecast.temps:
        return mean(t.temp for t in forecast.temps[:int(hours)])
    else:
        return None
