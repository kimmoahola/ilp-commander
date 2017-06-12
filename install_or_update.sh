#!/bin/sh

chmod a+x *.sh

chmod u+rw-x,go+r-wx crontab
chown root:root crontab

sudo ln -sf /home/pi/ilp-commander/logrotate.conf /etc/logrotate.d/ilp-commander.conf
sudo ln -sf /home/pi/ilp-commander/supervisor.conf /etc/supervisor/conf.d/ilp-commander.conf
sudo cp /home/pi/ilp-commander/lircd.conf /etc/lirc/lircd.conf
pip install -q -r requirements.txt 2> /dev/null

sudo service lirc stop && sudo service lirc start
sudo supervisorctl add ilp-commander > /dev/null
sudo supervisorctl restart ilp-commander > /dev/null
