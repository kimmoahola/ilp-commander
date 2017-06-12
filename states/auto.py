# coding=utf-8
import time
import urllib

import requests
import requests_cache

from poller_helpers import Commands, logger, send_ir_signal, timing
from states import State


class Auto(State):

    last_command = None
    last_command_send_time = time.time()

    def run(self, payload):
        requests_cache.core.remove_expired_responses()

        # TODO: hae huussista, fmi:ltä pirkkan kentältä ja jostain kolmannesta. laske näistä mediaani ja käytä sitä
        # http://data.fmi.fi/fmi-apikey/91e0f171-0f53-492d-a383-c9562ec13230/wfs?request=getFeature&storedquery_id=fmi::observations::weather::simple&place=tampere&parameters=temperature

        temp = self.receive_yahoo_temperature()

        if temp > 0:
            next_command = Commands.off
        elif 0 >= temp > -15:
            next_command = Commands.heat8
        elif -15 >= temp > -20:
            next_command = Commands.heat10
        elif -20 >= temp > -25:
            next_command = Commands.heat16
        else:
            next_command = Commands.heat20

        # Send command every 3 hours even if command has not changed
        force_send_command_time = 60 * 60 * 3

        if Auto.last_command is not None:
            logger.debug('Last auto command sent %s minutes ago', (time.time() - Auto.last_command_send_time) / 60.0)

        if Auto.last_command != next_command or time.time() - Auto.last_command_send_time > force_send_command_time:
            Auto.last_command = next_command
            Auto.last_command_send_time = time.time()
            send_ir_signal(next_command)

    @staticmethod
    @timing
    def receive_yahoo_temperature():
        yql_query = "select item.condition from weather.forecast where woeid in (select woeid from geo.places(1) " \
                    "where text='tampere') and u='c'"
        yql_query_encoded = urllib.urlencode({'q': yql_query})
        result = requests.get('https://query.yahooapis.com/v1/public/yql?' + yql_query_encoded + '&format=json')
        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        temp = int(result.json()['query']['results']['channel']['item']['condition']['temp'])
        logger.info(temp)
        return temp

    def nex(self, payload):
        from states.wait_message_auto import WaitMessageAuto

        return WaitMessageAuto
