# coding=utf-8
import time
from datetime import timedelta
from urllib.parse import urlencode

import arrow
import requests
import requests_cache
import xmltodict

import config
from poller_helpers import Commands, logger, send_ir_signal, timing, get_most_recent_message
from states import State

requests_cache.install_cache(backend='memory', expire_after=timedelta(minutes=10))


class Auto(State):

    last_command = None
    last_command_send_time = time.time()

    def run(self, payload):
        requests_cache.core.remove_expired_responses()

        temperatures = []

        temp1 = self.receive_fmi_temperature()
        if temp1 is not None:
            temperatures.append(temp1)

        temp2 = self.receive_yahoo_temperature()
        if temp2 is not None:
            temperatures.append(temp2)
        temp3 = self.receive_yr_no_temperature()
        if temp3 is not None:
            temperatures.append(temp3)

        if temperatures:
            temp = Auto.take_mean(temperatures)
            logger.info('The mean temperature %f', temp)

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

        else:
            logger.error('Got no temperatures at all. Setting %s', Commands.heat16)
            next_command = Commands.heat16  # Don't know the temperature so heat up just in case

        # Send command every 3 hours even if command has not changed
        force_send_command_time = 60 * 60 * 3

        if Auto.last_command is not None:
            logger.debug('Last auto command sent %s minutes ago', (time.time() - Auto.last_command_send_time) / 60.0)

        if Auto.last_command != next_command or time.time() - Auto.last_command_send_time > force_send_command_time:
            Auto.last_command = next_command
            Auto.last_command_send_time = time.time()
            send_ir_signal(next_command)

        return get_most_recent_message(once=True)

    @staticmethod
    def take_mean(values):
        sorted_values = sorted(values)
        return sorted_values[len(sorted_values)//2]  # Take the middle value

    @staticmethod
    @timing
    def receive_yahoo_temperature():
        yql_query = "select item.condition from weather.forecast where woeid in (select woeid from geo.places(1) " \
                    "where text='{location}') and u='c'".format(location=config.YAHOO_LOCATION)
        yql_query_encoded = urlencode({'q': yql_query})
        result = requests.get('https://query.yahooapis.com/v1/public/yql?' + yql_query_encoded + '&format=json')

        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            temp = float(result.json()['query']['results']['channel']['item']['condition']['temp'])
            logger.info(temp)
            return temp

        return None

    @staticmethod
    @timing
    def receive_fmi_temperature():
        result = requests.get(
            'http://data.fmi.fi/fmi-apikey/{key}/wfs?request=getFeature&storedquery_id=fmi::observations::weather'
            '::simple&place={place}&parameters=temperature'.format(key=config.FMI_KEY, place=config.FMI_LOCATION))

        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            d = xmltodict.parse(result.content)
            temp_data = d['wfs:FeatureCollection']['wfs:member'][-1]['BsWfs:BsWfsElement']

            MAX_AGE_MINUTES = 60
            is_recent_enough = (arrow.now() - arrow.get(temp_data['BsWfs:Time'])).total_seconds() < 60 * MAX_AGE_MINUTES
            if is_recent_enough:
                temp = float(temp_data['BsWfs:ParameterValue'])
                logger.info(temp)
                return temp

        return None

    @staticmethod
    @timing
    def receive_yr_no_temperature():
        result = requests.get(
            'http://www.yr.no/place/{place}/forecast.xml'.format(place=config.YR_NO_LOCATION))

        if result.status_code != 200:
            logger.error('%d: %s' % (result.status_code, result.content))
        else:
            d = xmltodict.parse(result.content)
            timezone = d['weatherdata']['location']['timezone']['@id']
            from_ = d['weatherdata']['forecast']['tabular']['time'][0]['@from']
            temp_date_time = arrow.get(from_).replace(tzinfo=timezone)

            MAX_AGE_MINUTES = 60
            is_recent_enough = abs((arrow.now() - temp_date_time).total_seconds()) < 60 * MAX_AGE_MINUTES
            if is_recent_enough:
                temp = float(d['weatherdata']['forecast']['tabular']['time'][0]['temperature']['@value'])
                logger.info(temp)
                return temp

        return None

    def nex(self, payload):
        from states.manual import Manual

        if payload:
            if payload['command'] == 'auto':
                return Auto
            else:
                Auto.last_command = None  # Clear last command so Auto sends command after Manual
                return Manual
        else:
            return Auto
