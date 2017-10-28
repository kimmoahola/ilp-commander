import arrow
from decimal import Decimal

from freezegun import freeze_time

import config
from poller_helpers import median, send_ir_signal, Commands


def test_median():
    ts1 = arrow.now()
    ts2 = ts1.shift(minutes=2)

    result_temp, result_ts = median([(Decimal(10), ts1), (Decimal(12), ts2)])

    assert result_temp == Decimal(11)
    assert result_ts == ts1.shift(minutes=1)


def test_send_ir_signal_fail(mocker):
    mock_email = mocker.patch('poller_helpers.email')

    freeze_ts = arrow.get('2017-08-18T15:00:00+00:00')
    with freeze_time(freeze_ts.datetime):
        send_ir_signal(Commands.heat20, extra_info=['Foo1', 'Foo2'])

    mock_email.assert_called_once_with(
        config.EMAIL_ADDRESSES, 'Send IR',
        'Send IR heat_20__fan_auto__swing_auto at 18.08.2017 18:00\nFoo1\nFoo2\nirsend: FileNotFoundError')


def test_send_ir_signal_ok(mocker):
    mock_email = mocker.patch('poller_helpers.email')
    mock_popen = mocker.patch('poller_helpers.Popen')

    freeze_ts = arrow.get('2017-08-18T15:00:00+00:00')
    with freeze_time(freeze_ts.datetime):
        send_ir_signal(Commands.heat20, extra_info=['Foo1', 'Foo2'])

    mock_email.assert_called_once_with(
        config.EMAIL_ADDRESSES, 'Send IR',
        'Send IR heat_20__fan_auto__swing_auto at 18.08.2017 18:00\nFoo1\nFoo2')

    mock_popen.assert_called_once()


def test_command():
    assert Commands.find_command_just_above_temp(Decimal(31)) == Commands.heat30
    assert Commands.find_command_just_above_temp(Decimal(10)) == Commands.heat16
    assert Commands.find_command_just_above_temp(Decimal(8)) == Commands.heat10
    assert Commands.find_command_just_above_temp(Decimal(7)) == Commands.heat8

    assert Commands.find_command_at_or_just_below_temp(Decimal(7)) == Commands.off
    assert Commands.find_command_at_or_just_below_temp(Decimal(8)) == Commands.heat8
    assert Commands.find_command_at_or_just_below_temp(Decimal(9)) == Commands.heat8
    assert Commands.find_command_at_or_just_below_temp(Decimal(31)) == Commands.heat30
