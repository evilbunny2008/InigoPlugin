# since.py
#
# A Search List Extension to provide aggregates since a given hour.
#
# python imports
import logging
import time

# weeWX imports
import weeutil.weeutil
import weewx.cheetahgenerator
import weewx.units

from datetime import datetime, timedelta

log = logging.getLogger(__name__)

since_hour = 0

def processConfigDict(class_name, config_dict):

    global since_hour

    cfg = config_dict.get("StdReport", None)
    if cfg is not None:
        inigo = cfg.get("Inigo", None)
        if inigo is not None:
             since_hour = int(inigo.get("since_hour", 0))

    if not 0 <= since_hour <= 23:
        since_hour = 0

class Since(weewx.cheetahgenerator.SearchList):
    """SLE to provide aggregates since a given time of day."""

    def __init__(self, generator):
        super(Since, self).__init__(generator)

        processConfigDict(self.__class__.__name__, generator.config_dict)

    def get_extension_list(self, timespan, db_lookup):

        global since_hour

        t1 = time.time()

        if not 0 <= since_hour <= 23:
            since_hour = 0

        stop_time = datetime.fromtimestamp(timespan.stop)
        start_time = stop_time.replace(hour=since_hour, minute=0, second=0, microsecond=0)

        if stop_time < start_time:
            start_time -= timedelta(days=1)

        tspan = weeutil.weeutil.TimeSpan(int(start_time.timestamp()), int(stop_time.timestamp()))

        today = weewx.tags.TimespanBinder(tspan, db_lookup, context="day")

        start_time -= timedelta(days=1)
        stop_time -= timedelta(days=1)

        tspan = weeutil.weeutil.TimeSpan(int(start_time.timestamp()), int(stop_time.timestamp()))

        yesterday = weewx.tags.TimespanBinder(tspan, db_lookup, context="day")

        t2 = time.time()
        log.debug(f"{self.__class__.__name__} Since SLE executed in {(t2-t1)}:.3f seconds")

        return [{"since": {"since_hour": since_hour, "since_rain_today": today.rain.sum.raw, "since_rain_yesterday": yesterday.rain.sum.raw}}]
