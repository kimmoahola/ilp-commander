#!/bin/sh

chmod a+x *.sh

chmod u+rw-x,go+r-wx crontab
chown root:root crontab logrotate.conf

ln -sf /home/pi/ilp-commander/logrotate.conf /etc/logrotate.d/ilp-commander
ln -sf /home/pi/ilp-commander/supervisor.conf /etc/supervisor/conf.d/ilp-commander.conf
ln -sf /home/pi/ilp-commander/crontab /etc/cron.d/ilp-commander
cp /home/pi/ilp-commander/lircd.conf /etc/lirc/lircd.conf

su - pi -c 'cd ~/ilp-commander/ && /home/pi/.pyenv/bin/pyenv install -s'
su - pi -c 'cd ~/ilp-commander/ && /home/pi/.pyenv/shims/pip install -q -r requirements.txt 2> /dev/null'

/usr/sbin/service lirc stop && /usr/sbin/service lirc start
supervisorctl stop ilp-commander > /dev/null
supervisorctl remove ilp-commander > /dev/null
supervisorctl update > /dev/null
