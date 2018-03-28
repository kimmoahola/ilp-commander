[![Build Status](https://travis-ci.org/termopetteri/ilp-commander.svg?branch=master)](https://travis-ci.org/termopetteri/ilp-commander)

# Install

- Automatic installation script assumes that this is cloned to `/home/pi/ilp-commander/` and that there's a user `pi` at `/home/pi`

- Install pyenv

- `cd /home/pi && git clone https://github.com/termopetteri/ilp-commander.git`

- `cd ilp-commander`

- Install correct python version: `pyenv install --skip-existing`

- `sudo sh install_or_update.sh`

# Tests

Run: `py.test`

## Run one test and print output

`py.test -s .\states\auto_test.py::TestVer2::test_auto_ver2_warm_inside_and_outside`

## Run matching tests and print output

`py.test -s -k buffer`

# Tips for development

## Get raw timings from IR sensor

`mode2 -d /dev/lirc0 -m`

## Manually send commands

`irsend SEND_ONCE ilp off`
