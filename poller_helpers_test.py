import arrow
from decimal import Decimal

from poller_helpers import median


def test_median():
    ts1 = arrow.now()
    ts2 = ts1.shift(minutes=2)

    result_temp, result_ts = median([(Decimal(10), ts1), (Decimal(12), ts2)])

    assert result_temp == Decimal(11)
    assert result_ts == ts1.shift(minutes=1)
