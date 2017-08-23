from poller_helpers import Commands
from states.manual import Manual


def test_manual(mocker):
    mock_send_ir_signal = mocker.patch('states.manual.send_ir_signal')

    manual = Manual()
    manual.run({'command': 'turn off', 'param': None})

    mock_send_ir_signal.assert_called_once_with(Commands.off)

