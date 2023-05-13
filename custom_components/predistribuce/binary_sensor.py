__version__ = "1.0"

import logging
import voluptuous as vol
from datetime import timedelta, datetime, date
from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.util import Throttle

import requests
from lxml import html, etree

MIN_TIME_BETWEEN_SCANS = timedelta(seconds=15*60)  # cervena carka ukazujici aktualni cas se stahuje take.
_LOGGER = logging.getLogger(__name__)

URL = "https:/predistribuce.cz/blabla/dd"

DOMAIN = "predistribuce"
CONF_CMD = "receiver_command_id"
CONF_SENSOR_NAME = "sensor_name"
CONF_PERIODS = "periods"
CONF_NAME = "name"
CONF_MINUTES = "minutes"

STYLES = """
  <style>
    .hdo-bar > span.span-overflow { z-index: 101; }
    .hdont { background: #242f65; }
    .hdovt { background: #9babc5; }
    .hdo-bar { margin-bottom: 10px; margin-top: 20px; height: 80px; clear: both; position: relative; }
    .hdo-bar span { border-radius: 0 3px 3px 0; }
    .hdo-bar span { height: 29px; margin: 0; padding: 0; display: inline-block; border: 0; position: absolute; top: 20px; right: 0; z-index: 99; }
    .hdo-bar span:first-of-type { border-radius: 3px; }
    .hdo-bar span.span-actualTime { border-left: 2px solid red; z-index: 100; height: 39px; top: 16px; }
    .overflow-bar { width: 100%; height: 55px; background: url('https://www.predistribuce.cz/images/hdo_bar.png') 0 0 no-repeat; background-size: 100% 55px; position: absolute; left: 0; top: 20px; z-index: 101; }
    .blue-text { color: #242f65; }
    .pull-left { float: left !important; }
    .pull-right { float: right !important; }
    .status .wrapper.dark-blue { background: #242F65; }
    .status .wrapper.light-blue { background: #9CACC5; }
    .hdo-sections.wrapper { padding: 6px 7px; margin: 0 5px 0 10px; }
    #component-hdo-dnes { min-width: 300px; width: auto; max-width: 650px; margin-left: -10px; margin-right: -10px; }
    .clear { clear: both; }
  </style> 
"""

PERIOD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=300))
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_CMD): cv.string,
        vol.Optional(CONF_SENSOR_NAME): cv.string,
        vol.Optional(CONF_PERIODS): vol.All(cv.ensure_list, [PERIOD_SCHEMA])
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    conf_cmd = config.get(CONF_CMD)
    conf_name = config.get(CONF_SENSOR_NAME, "aktuálně")
    conf_periods = config.get(CONF_PERIODS, [])
    ents = []
    ents.append(PreDistribuce(conf_cmd, 0, conf_name))
    for pre in conf_periods:
        ents.append(PreDistribuce(conf_cmd, pre.get(CONF_MINUTES), pre.get(CONF_NAME)))
    add_entities(ents)

class PreDistribuce(BinarySensorEntity):

    def __init__(self, conf_cmd, minutes, name):
        """Initialize the sensor."""
        self.conf_cmd = conf_cmd
        self.minutes = minutes
        self.entity_id = f"binary_sensor.hdo_{conf_cmd}"
        self._attr_unique_id = f"{DOMAIN}-hdo-{conf_cmd}"
        self._name = f"HDO {name}"
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
    def icon(self):
        return "mdi:flash-red-eye"

    @property
    def is_on(self):
        """Return entity state."""
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
                hdoTed = hdoNizkyVysoky[idx-1]
                idxTed = idx
                break

        zacne = datetime.strptime(hdoCasyZacatky[idxTed], '%H:%M').time()
        zbyvaMinut = (datetime.combine(date.today(), zacne) - datetime.combine(date.today(), time_now)).seconds / 60

        if self.minutes == 0:
            if hdoTed == 'N':
                return True
            else:
                return False
        else:
            # Reflect gap in minute that low tariff need to be active
            if hdoTed == 'N':
                #kdy zacne vysoky tarif?
                if self.minutes < zbyvaMinut:
                    return True   # Currently there is low tariff and it will still be longer than we need
                else:
                    return False   # Currently there is low tariff but not enough as we need
            else:
                #kdy zacne nizky?
                return False

        return None

    @property
    def extra_state_attributes(self):
        attributes = {}
        if self.minutes == 0:
            attributes['html_values'] = STYLES + self.html
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
        page = requests.get("https://www.predistribuce.cz/cs/potrebuji-zaridit/zakaznici/stav-hdo/?povel={3}&den_od={0}&mesic_od={1}&rok_od={2}&den_do={0}&mesic_do={1}&rok_do={2}".format(today.day, today.month, today.year, self.conf_cmd))
        if page.status_code == 200:
            self.tree = html.fromstring(page.content)
            self.html = etree.tostring(self.tree.xpath('//div[@id="component-hdo-dnes"]')[0]).decode("utf-8").replace('\n', '').replace('\t', '').replace('"/>', '"></span>')
            self.html = self.html.replace('<div class="overflow-bar"></span>', '<div class="overflow-bar"></div>')
            #_LOGGER.warn("UPDATING POST {}".format(self.html))
            self.last_update_success = True
        else:
            self.last_update_success = False
