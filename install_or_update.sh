#!/bin/sh

chmod a+x *.sh

chmod u+rw-x,go+r-wx crontab
chown root:root crontab logrotate.conf

ln -sf /home/pi/ilp-commander/logrotate.conf /etc/logrotate.d/ilp-commander
ln -sf /home/pi/ilp-commander/supervisor.conf /etc/supervisor/conf.d/ilp-commander.conf
ln -sf /home/pi/ilp-commander/crontab /etc/cron.d/ilp-commander.conf
cp /home/pi/ilp-commander/lircd.conf /etc/lirc/lircd.conf

runuser -l pi -c 'cd ~/ilp-commander/ && pyenv install -s'
runuser -l pi -c 'cd ~/ilp-commander/ && pip install -q -r requirements.txt 2> /dev/null'

service lirc stop && sudo service lirc start
supervisorctl add ilp-commander > /dev/null
supervisorctl restart ilp-commander > /dev/null
