
# Simple weeWX loop and archive service to detect when outTemp has peaked.

import logging
import sys
import weewx
import weewx.engine
import weewx.manager

from datetime import datetime, timedelta
from weeutil.weeutil import TimeSpan
from weewx.units import FtoC
from weewx.tags import TimespanBinder

log = logging.getLogger(__name__)

PEAKDETECTOR_VERSION = "0.0.1"

if sys.version_info[0] < 3 or (sys.version_info[0] == 3 and sys.version_info[1] < 7):
    raise weewx.UnsupportedFeature(
        f"PeakDetectorService v{PEAKDETECTOR_VERSION} requires Python 3.7 or later, found %s.%s" % (sys.version_info[0], sys.version_info[1]))

if weewx.__version__ < "4":
    raise weewx.UnsupportedFeature(
        f"PeakDetectorService v{PEAKDETECTOR_VERSION} requires WeeWX 4 or later, found %s" % weewx.__version__)

class PeakDetectorService(weewx.engine.StdService):

    def __init__(self, engine, config_dict):

        super(PeakDetectorService, self).__init__(engine, config_dict)

        self.loop_up_count = 0
        self.loop_down_count = 0
        self.last_loop_temp = None

        self.usUnit = weewx.METRIC
        cfg = config_dict.get('StdReport', None)
        if cfg is not None:
            inigo = cfg.get('Inigo', None)
            if inigo is not None:
                 units = inigo.get('Units', None)
                 if units is not None:
                     groups = units.get('Groups', None)
                     if groups is not None:
                         temp_group = groups.get('group_temperature', None)
                         if temp_group is not None and temp_group == "degree_F":
                             self.usUnit = weewx.US

        now = datetime.now()

        self.db_lookup = weewx.manager.DBBinder(config_dict).bind_default()

        min10_ago = now - timedelta(minutes=10)
        stats = TimespanBinder(TimeSpan(int(min10_ago.timestamp()), int(now.timestamp())), self.db_lookup)

        outTemp10min_avg = stats.outTemp.avg.raw

        if self.usUnit != weewx.US:
            outTemp10min_avg = FtoC(outTemp10min_avg)

        outTemp10min_avg = round(outTemp10min_avg, 1)

        self.last_loop_temp = outTemp10min_avg

        self.bind(weewx.NEW_LOOP_PACKET, self.handle_loop_packet)
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.handle_archive_record)

        log.info(f"{self.__class__.__name__} v{PEAKDETECTOR_VERSION} started")

    def handle_archive_record(self, event):

        record = event.record

        temp = self.getTemp(record)
        if temp is None:
            return

        after4pm = datetime.now().hour >= 16

        trending_down = False
        total = self.loop_up_count + self.loop_down_count
        if total > 0:
            down_ratio = self.loop_down_count / total
            trending_down = down_ratio >= 0.65

        now = datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        stats = TimespanBinder(TimeSpan(int(midnight.timestamp()), int(now.timestamp())), self.db_lookup)

        effective_peak = stats.outTemp.max.raw

        outTemp_peaked = (trending_down or after4pm) and temp < effective_peak

        if self.usUnit != weewx.US:
            effective_peak = FtoC(effective_peak)

        if not outTemp_peaked:
            effective_peak = -999.9

        effective_peak = round(effective_peak, 1)

        record["outTemp_peak"] = effective_peak

        log.info(f"{self.__class__.__name__} outTemp_peak {effective_peak}{unitSym}")

        self.loop_up_count = 0
        self.loop_down_count = 0

    def handle_loop_packet(self, event):

        packet = event.packet

        temp = self.getTemp(packet)
        if temp is None:
            return

        if self.last_loop_temp is None:
            self.last_loop_temp = temp
            return

        if temp > self.last_loop_temp:
            self.loop_up_count += 1

        if temp < self.last_loop_temp:
            self.loop_down_count += 1

        self.last_loop_temp = temp

    def getTemp(self, packet):

        temp = packet.get('outTemp', None)

        if temp is None:
            return None

        try:
            return round(float(temp), 1)
        except (ValueError, TypeError):
            return None

    def shutDown(self):

        log.info(f"{self.__class__.__name__} v{PEAKDETECTOR_VERSION} stopped")
