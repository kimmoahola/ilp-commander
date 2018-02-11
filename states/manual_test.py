from poller_helpers import Commands
from states.manual import Manual


def test_manual(mocker):
    mock_send_ir_signal = mocker.patch('states.manual.send_ir_signal')
    mock_write_log_to_sheet = mocker.patch('states.manual.write_log_to_sheet')

    manual = Manual()
    manual.run({'command': 'turn off', 'param': None})

    mock_send_ir_signal.assert_called_once_with(Commands.off)
    mock_write_log_to_sheet.assert_called_once_with(Commands.off, extra_info=[])

