__version__ = "1.0"

import math
import logging
import voluptuous as vol
from datetime import timedelta, datetime, date
from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

import requests
from lxml import html, etree

MIN_TIME_BETWEEN_SCANS = timedelta(seconds=3600)
_LOGGER = logging.getLogger(__name__)

DOMAIN = "predistribuce"
CONF_CMD = "receiver_command_id"
CONF_PERIODS = "periods"
CONF_NAME = "name"
CONF_MINUTES = "minutes"

PERIOD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=300))
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_CMD): cv.string,
        vol.Optional(CONF_PERIODS): vol.All(cv.ensure_list, [PERIOD_SCHEMA])
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    conf_cmd = config.get(CONF_CMD)
    ents = []
    ents.append(PreDistribuce(conf_cmd, 0, "HDO čas do nízkého tarifu"))
    add_entities(ents)

class PreDistribuce(Entity):

    def __init__(self, conf_cmd, minutes, name):
        """Initialize the sensor."""
        self.conf_cmd = conf_cmd
        self.minutes = minutes
        self._name = name
        self.timeToNT = 0
        self.html = "<div><i>Není spojení</i></div>"
        self.tree = ""
        self.update()

    @property
    def name(self):
        """Return name of the sensor."""
        return self._name

    @property
    def unit_of_measurement(self):
        return "minut"

    @property
    def icon(self):
        return "mdi:av-timer"

    @property
    def state(self):
        """Return time to wait until low tariff."""
        hdoNizkyVysoky = self.tree.xpath('//div[@id="component-hdo-dnes"]/div[@class="hdo-bar"]/span[starts-with(@class, "hdo")]/@class')
        hdoCasyCitelne = self.tree.xpath('//div[@id="component-hdo-dnes"]/div/span[@class="span-overflow"]/@title')
        hdoNizkyVysoky = [ x[3].upper() for x in hdoNizkyVysoky ]
        hdoCasyZacatky = [ x[0:5].upper() for x in hdoCasyCitelne ]

        time_now = datetime.now().time()
        hdoTed = hdoNizkyVysoky[:1][0]
        idxTed = len(hdoNizkyVysoky)-1
        for idx,t in enumerate(hdoCasyZacatky, start=0):
            time_start = datetime.strptime(t, '%H:%M').time()
            if time_now < time_start:
                hdoTed = hdoNizkyVysoky[idx - 1]
                idxTed = idx
                break

        zacne = datetime.strptime(hdoCasyZacatky[idxTed], '%H:%M').time()
        zbyvaMinut = (datetime.combine(date.today(), zacne) - datetime.combine(date.today(), time_now)).seconds / 60
        if hdoTed == 'N':
            self.timeToNT = 0
            self.timetoVT = zbyvaMinut
        else:
            self.timeToNT = zbyvaMinut
            self.timetoVT = 0

        return math.floor(self.timeToNT)


    @property
    def extra_state_attributes(self):
        attributes = {}
        attributes['HDO čas do vysokého tarifu'] = math.floor(self.timetoVT)
        return attributes

    @property
    def should_poll(self):
        return True

    @property
    def available(self):
        """Return if entity is available."""
        return self.last_update_success

    @property
    def device_class(self):
        return 'plug'

    # TODO make default sensor (minutes=0) responsible for fetching, storing tree and html as static global variables
    @Throttle(MIN_TIME_BETWEEN_SCANS)
    def update(self):
        """Update the entity by scraping website"""
        today = date.today()
        page = requests.get("https://www.predistribuce.cz/cs/potrebuji-zaridit/zakaznici/stav-hdo/?povel={3}&den_od={0}&mesic_od={1}&rok_od={2}&den_do={0}&mesic_do={1}&rok_do={2}".format(today.day,today.month,today.year,self.conf_cmd))
        if page.status_code == 200:
            self.tree = html.fromstring(page.content)
            self.html = etree.tostring(self.tree.xpath('//div[@id="component-hdo-dnes"]')[0]).decode("utf-8").replace('\n', '').replace('\t', '').replace('"/>', '"></span>')
            #_LOGGER.warn("UPDATING POST {}".format(self.html))
            self.last_update_success = True
        else:
            self.last_update_success = False
