
# Simple weeWX loop and archive service to detect when outTemp has peaked.

import logging
import os
import pickle
import stat
import sys
import time
import weewx
import weewx.engine
import weewx.manager

from collections import deque
from datetime import datetime, timedelta
from weeutil.weeutil import TimeSpan
from weewx.units import FtoC
from weewx.tags import TimespanBinder

log = logging.getLogger(__name__)

PEAKDETECTOR_VERSION = "0.0.2"

if sys.version_info[0] < 3 or (sys.version_info[0] == 3 and sys.version_info[1] < 7):
    raise weewx.UnsupportedFeature(
        f"PeakDetectorService v{PEAKDETECTOR_VERSION} requires Python 3.7 or later, found %s.%s" % (sys.version_info[0], sys.version_info[1]))

if weewx.__version__ < "4":
    raise weewx.UnsupportedFeature(
        f"PeakDetectorService v{PEAKDETECTOR_VERSION} requires WeeWX 4 or later, found %s" % weewx.__version__)

class PickleFormattedData():

    def __init__(self, temp_history, loop_interval):

        self.temp_history = temp_history
        self.loop_interval = loop_interval

class PickleFormattedDataV2():

    def __init__(self, temp_history, interval_history):

        self.temp_history = temp_history
        self.interval_history = interval_history

class PeakDetectorService(weewx.engine.StdService):

    def __init__(self, engine, config_dict):

        super(PeakDetectorService, self).__init__(engine, config_dict)

        self.temp_history = deque(maxlen=3600)

        self.cache_dir = "/tmp/peak_detector"

        self.usUnit = weewx.METRIC
        cfg = config_dict.get("StdReport", None)
        if cfg is not None:
            inigo = cfg.get("Inigo", None)
            if inigo is not None:

                 self.cache_dir = inigo.get("cache_dir", "/tmp/peak_detector")
                 units = inigo.get("Units", None)
                 if units is not None:
                     groups = units.get("Groups", None)
                     if groups is not None:
                         temp_group = groups.get("group_temperature", None)
                         if temp_group is not None and temp_group == "degree_F":
                             self.usUnit = weewx.US

        uid = os.getuid()
        statinfo = os.stat(self.cache_dir)
        cuid = statinfo.st_uid

        if uid != 0 and uid != cuid:
            raise weewx.UnsupportedFeature(
                f"PeakDetectorService failed to start due to permissions on {self.cache_dir} directory uid: {uid}, cuid: {cuid}")

        self.pickle_filename = os.path.join(self.cache_dir, "peak_detector.pkl")

        self.load_pickle_data()

        if self.temp_history.maxlen != 3600:
            self.temp_history = deque(self.temp_history, maxlen=3600)

        self.db_lookup = weewx.manager.DBBinder(config_dict).bind_default()

        self.bind(weewx.NEW_LOOP_PACKET, self.handle_loop_packet)
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.handle_archive_record)

        log.info(f"{self.__class__.__name__} v{PEAKDETECTOR_VERSION} started")

    def handle_archive_record(self, event):

        record = event.record

        self.save_pickle_data(True)

        ts, temp = self.getTemp(record)
        if temp is None:
            return

        record["outTemp_trend1"] = self.get_temp_trend(1)
        record["outTemp_trend5"] = self.get_temp_trend(5)
        record["outTemp_trend10"] = self.get_temp_trend(10)
        record["outTemp_trend30"] = self.get_temp_trend(30)
        record["outTemp_trend60"] = self.get_temp_trend(60)

        now = datetime.now()

        after4pm = now.hour >= 16

        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        stats = TimespanBinder(TimeSpan(int(midnight.timestamp()), int(now.timestamp())), self.db_lookup)

        outTemp_max = round(stats.outTemp.max.raw, 1)

        record["outTemp_max"] = outTemp_max

        outTemp_peaked = temp < outTemp_max

        log.info(f"{self.__class__.__name__} outTemp_trend1: {record['outTemp_trend1']}")
        log.info(f"{self.__class__.__name__} outTemp_trend5: {record['outTemp_trend5']}")
        log.info(f"{self.__class__.__name__} outTemp_trend10: {record['outTemp_trend10']}")
        log.info(f"{self.__class__.__name__} outTemp_trend30: {record['outTemp_trend30']}")
        log.info(f"{self.__class__.__name__} outTemp_trend60: {record['outTemp_trend60']}")
        log.info(f"{self.__class__.__name__} outTemp_max: {record['outTemp_max']}")

    def handle_loop_packet(self, event):

        packet = event.packet

        ts, temp = self.getTemp(packet)
        if temp is None:
            return

        self.temp_history.append((ts, temp))

        self.save_pickle_data()

    def getTemp(self, packet):

        ts = packet.get("dateTime", int(time.time()))
        temp = packet.get("outTemp", None)

        if temp is None:
            return None

        try:
            return ts, round(float(temp), 1)
        except (ValueError, TypeError):
            return ts, None

    # Trend calculation — call this wherever you need it
    def get_temp_trend(self, minutes):
        if len(self.temp_history) < 2:
            return None  # not enough data

        temps = [temp for ts, temp in self.temp_history if ts >= time.time() - (minutes * 60)]

        up   = sum(1 for i in range(1, len(temps)) if temps[i] > temps[i-1])
        down = sum(1 for i in range(1, len(temps)) if temps[i] < temps[i-1])
        total = up + down

        if total == 0:
            return "steady"

        ratio = down / total
        if ratio >= 0.65:
            return "falling"
        elif ratio <= 0.35:
            return "rising"
        else:
            return "steady"

    def shutDown(self):

        self.save_pickle_data(True)

        log.info(f"{self.__class__.__name__} v{PEAKDETECTOR_VERSION} stopped")

    def load_pickle_data(self):

        if os.path.exists(self.pickle_filename):

            try:
                with open(self.pickle_filename, "rb") as f:

                    ret = pickle.load(f)

                    if isinstance(ret, PickleFormattedDataV2):
                        log.info(f"{self.__class__.__name__} pickle file is PickleFormattedDataV2")
                        self.temp_history = ret.temp_history
                    elif isinstance(ret, PickleFormattedData):
                        log.info(f"{self.__class__.__name__} pickle file is PickleFormattedData")
                        self.temp_history = ret.temp_history
                    elif isinstance(ret, deque):
                        log.info(f"{self.__class__.__name__} pickle file is raw deque")
                        self.temp_history = ret

                    log.info(f"{self.__class__.__name__} loaded {len(self.temp_history)} records from pickle file")

            except Exception as e:
                pass

    def save_pickle_data(self, report=False):

        try:
            with open(self.pickle_filename, "wb") as f:

                pickle.dump(self.temp_history, f)

                if report:
                    log.info(f"{self.__class__.__name__} saved {len(self.temp_history)} records to the pickle file")

        except Exception as e:
            raise e
