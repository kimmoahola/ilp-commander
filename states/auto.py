# coding=utf-8
import time
from decimal import Decimal
from statistics import median
from urllib.parse import urlencode

import arrow
import requests
import xmltodict
from arrow.parser import ParserError
from dateutil import tz

import config
from poller_helpers import Commands, logger, send_ir_signal, timing, get_most_recent_message, get_ulkoilma, get_wc, \
    get_url
from states import State


class RequestCache:
    _cache = {}

    @classmethod
    def put(cls, name, stale_after, content):
        stale_after = max([stale_after, arrow.now().shift(minutes=10)])
        cls._cache[name] = (stale_after, content)

    @classmethod
    def get(cls, name):
        if name in cls._cache:
            stale_after = cls._cache[name][0]
            if arrow.now() <= stale_after:
                content = cls._cache[name][1]
                return content

        return None


@timing
def receive_yahoo_temperature():
    temp, ts = None, None

    rq = RequestCache()
    content = rq.get('yahoo')
    if content:
        temp, ts = content
    else:
        try:
            yql_query = "select item.condition from weather.forecast where woeid in (select woeid from geo.places(1) " \
                        "where text='{location}') and u='c'".format(location=config.YAHOO_LOCATION)
            yql_query_encoded = urlencode({'q': yql_query})
            result = get_url('https://query.yahooapis.com/v1/public/yql?' + yql_query_encoded + '&format=json')
        except Exception as e:
            logger.exception(e)
        else:
            if result.status_code != 200:
                logger.error('%d: %s' % (result.status_code, result.content))
            else:
                condition_ = result.json()['query']['results']['channel']['item']['condition']
                temp = Decimal(condition_['temp'])
                try:
                    ts = arrow.get(condition_['date'], 'DD MMM YYYY HH:mm A ZZZ')
                except ParserError:
                    # Hack for Windows
                    if condition_['date'].split(' ')[-1] == 'EEST':
                        from dateutil.tz import gettz
                        ts = arrow.get(condition_['date'], 'DD MMM YYYY HH:mm A').replace(tzinfo=gettz(config.TIMEZONE))

                rq.put('yahoo', ts.shift(minutes=95), (temp, ts))

    logger.info('%s %s', temp, ts)
    return temp, ts


@timing
def receive_ulkoilma_temperature():

    rq = RequestCache()
    content = rq.get('ulkoilma')
    if content:
        temp, ts = content
    else:
        temp, ts = get_ulkoilma()

        if ts is not None and temp is not None:
            ts = arrow.get(ts, 'DD.MM.YYYY klo HH:mm').replace(tzinfo=tz.gettz(config.TIMEZONE))
            temp = Decimal(temp)

            rq.put('ulkoilma', ts.shift(minutes=25), (temp, ts))

    logger.info('%s %s', temp, ts)
    return temp, ts


@timing
def receive_wc_temperature():

    rq = RequestCache()
    content = rq.get('wc')
    if content:
        temp, ts = content
    else:
        temp, ts = get_wc()

        if ts is not None and temp is not None:
            ts = arrow.get(ts, 'DD.MM.YYYY klo HH:mm').replace(tzinfo=tz.gettz(config.TIMEZONE))
            temp = Decimal(temp)

            rq.put('wc', ts.shift(minutes=25), (temp, ts))

    logger.info('%s %s', temp, ts)
    return temp, ts


@timing
def receive_fmi_temperature():
    temp, ts = None, None

    rq = RequestCache()
    content = rq.get('fmi')
    if content:
        temp, ts = content
    else:
        try:
            starttime = arrow.now().shift(hours=-1).to('UTC').format('YYYY-MM-DDTHH:mm:ss') + 'Z'
            result = requests.get(
                'http://data.fmi.fi/fmi-apikey/{key}/wfs?request=getFeature&storedquery_id=fmi::observations::weather'
                '::simple&place={place}&parameters=temperature&starttime={starttime}'.format(
                    key=config.FMI_KEY, place=config.FMI_LOCATION, starttime=starttime))
        except Exception as e:
            logger.exception(e)
        else:
            if result.status_code != 200:
                logger.error('%d: %s' % (result.status_code, result.content))
            else:
                temp_data = xmltodict.parse(result.content)['wfs:FeatureCollection']['wfs:member'][-1]['BsWfs:BsWfsElement']
                ts = arrow.get(temp_data['BsWfs:Time'])
                temp = Decimal(temp_data['BsWfs:ParameterValue'])
                rq.put('fmi', ts.shift(minutes=15), (temp, ts))

    logger.info('%s %s', temp, ts)
    return temp, ts

#
# @timing
# def receive_yr_no_temperature():
#     try:
#         result = requests.get(
#             'http://www.yr.no/place/{place}/forecast.xml'.format(place=config.YR_NO_LOCATION))
#     except Exception as e:
#         logger.exception(e)
#         result = None
#
#     if result:
#         if result.status_code != 200:
#             logger.error('%d: %s' % (result.status_code, result.content))
#         else:
#             d = xmltodict.parse(result.content)
#             timezone = d['weatherdata']['location']['timezone']['@id']
#             from_ = d['weatherdata']['forecast']['tabular']['time'][0]['@from']
#             temp_date_time = arrow.get(from_).replace(tzinfo=timezone)
#
#             MAX_AGE_MINUTES = 60
#             is_recent_enough = abs((arrow.now() - temp_date_time).total_seconds()) < 60 * MAX_AGE_MINUTES
#             if is_recent_enough:
#                 temp = Decimal(d['weatherdata']['forecast']['tabular']['time'][0]['temperature']['@value'])
#                 logger.info(temp)
#                 return temp
#
#     return None


class Temperatures:
    MAX_TS_DIFF_MINUTES = 60

    @classmethod
    def get_temp(cls, functions: list):
        temperatures = []

        for func in functions:
            temp, ts = func()
            if temp is not None and ts is not None:
                seconds = (arrow.now() - ts).total_seconds()
                if abs(seconds) < 60 * cls.MAX_TS_DIFF_MINUTES:
                    temperatures.append(temp)
                else:
                    logger.info('Discarding temperature %s %s %s', func, ts, temp)

        if temperatures:
            return median(temperatures)
        else:
            return None


class Auto(State):

    last_command = None
    last_command_send_time = time.time()

    def run(self, payload):

        inside_temp = Temperatures.get_temp([receive_wc_temperature])

        if inside_temp is None or inside_temp < 8:

            outside_temp = Temperatures.get_temp([
                receive_ulkoilma_temperature, receive_yahoo_temperature, receive_fmi_temperature])

            if outside_temp is not None:
                logger.info('Outside median temperature: %.1f', outside_temp)

                if outside_temp > 0:
                    next_command = Commands.off
                elif 0 >= outside_temp > -15:
                    next_command = Commands.heat8
                elif -15 >= outside_temp > -20:
                    next_command = Commands.heat10
                elif -20 >= outside_temp > -25:
                    next_command = Commands.heat16
                else:
                    next_command = Commands.heat20

            else:
                logger.error('Got no temperatures at all. Setting %s', Commands.heat16)
                next_command = Commands.heat16  # Don't know the temperature so heat up just in case

        else:
            logger.info('Inside temperature: %.1f', inside_temp)
            next_command = Commands.off  # No need to heat

        # Send command every 3 hours even if command has not changed
        force_send_command_time = 60 * 60 * 3

        if Auto.last_command is not None:
            logger.debug('Last auto command sent %d minutes ago', (time.time() - Auto.last_command_send_time) / 60.0)

        if Auto.last_command != next_command or time.time() - Auto.last_command_send_time > force_send_command_time:
            Auto.last_command = next_command
            Auto.last_command_send_time = time.time()
            send_ir_signal(next_command)

        return get_most_recent_message(once=True)

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
