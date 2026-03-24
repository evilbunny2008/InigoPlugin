
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
        self.interval_history = deque(maxlen=60)
        self.loop_interval = 0
        self.last_loop_ts = None

        self.cache_dir = "/tmp/peak_detector"

        self.usUnit = weewx.METRIC
        cfg = config_dict.get('StdReport', None)
        if cfg is not None:
            inigo = cfg.get('Inigo', None)
            if inigo is not None:

                 self.cache_dir = inigo.get("cache_dir", "/tmp/peak_detector")
                 units = inigo.get('Units', None)
                 if units is not None:
                     groups = units.get('Groups', None)
                     if groups is not None:
                         temp_group = groups.get('group_temperature', None)
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

        if self.interval_history.maxlen != 60:
            self.interval_history = deque(self.interval_history, maxlen=60)

        self.bind(weewx.NEW_LOOP_PACKET, self.handle_loop_packet)
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.handle_archive_record)

        log.info(f"{self.__class__.__name__} v{PEAKDETECTOR_VERSION} started")

    def handle_archive_record(self, event):

        record = event.record

        self.save_pickle_data(True)

        record["outTemp_trend1"] = self.get_temp_trend(60)
        record["outTemp_trend5"] = self.get_temp_trend(300)
        record["outTemp_trend10"] = self.get_temp_trend(600)
        record["outTemp_trend30"] = self.get_temp_trend(1800)
        record["outTemp_trend60"] = self.get_temp_trend(3600)
        record["outTemp_trend"] = self.get_temp_trend(0)

        log.info(f"{self.__class__.__name__} outTemp_trend1: {record['outTemp_trend1']}")
        log.info(f"{self.__class__.__name__} outTemp_trend5: {record['outTemp_trend5']}")
        log.info(f"{self.__class__.__name__} outTemp_trend10: {record['outTemp_trend10']}")
        log.info(f"{self.__class__.__name__} outTemp_trend30: {record['outTemp_trend30']}")
        log.info(f"{self.__class__.__name__} outTemp_trend60: {record['outTemp_trend60']}")
        log.info(f"{self.__class__.__name__} outTemp_trend: {record['outTemp_trend']}")

    def handle_loop_packet(self, event):

        packet = event.packet

        ts, temp = self.getTemp(packet)
        if temp is None:
            return

        self.add_interval(ts)

        self.temp_history.append((ts, temp))

        self.save_pickle_data()

    def getTemp(self, packet):

        ts = int(packet.get("dateTime", time.time()))
        temp = packet.get('outTemp', None)

        if temp is None:
            return ts, None

        try:
            return ts, float(temp)
        except (ValueError, TypeError):
            return ts, None

    # Trend calculation — call this wherever you need it
    def get_temp_trend(self, seconds):
        if len(self.temp_history) < 2 or self.loop_interval is None or self.loop_interval < 2:
            return None  # not enough data

        if seconds > 1:
            samples = int(seconds / self.loop_interval)
        else:
            samples = len(self.temp_history)

        if samples > len(self.temp_history):
            samples = len(self.temp_history)

        temps = [t for _, t in self.temp_history]

        up   = sum(1 for i in range(1, samples) if temps[i] > temps[i-1])
        down = sum(1 for i in range(1, samples) if temps[i] < temps[i-1])
        total = up + down

        if total == 0:
            return 'steady'

        ratio = down / total
        if ratio >= 0.65:
            return 'falling'
        elif ratio <= 0.35:
            return 'rising'
        else:
            return 'steady'

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
                        self.interval_history = ret.interval_history
                        self.update_interval()
                    elif isinstance(ret, PickleFormattedData):
                        log.info(f"{self.__class__.__name__} pickle file is PickleFormattedData")
                        self.temp_history = ret.temp_history
                        self.loop_interval = ret.loop_interval
                    elif isinstance(ret, deque):
                        log.info(f"{self.__class__.__name__} pickle file is raw deque")
                        self.temp_history = ret

                    log.info(f"{self.__class__.__name__} loaded {len(self.temp_history)} records from pickle file")

            except Exception as e:
                pass

    def update_interval(self):

        if len(self.interval_history) < 2:
            return

        intervals = [loop_interval for ts, loop_interval in self.interval_history if 1 <= loop_interval <= 30 and ts >= time.time() - 60]

        new_interval = round(sum(intervals) / len(intervals) * 2) / 2

        if 1 <= new_interval <= 30 and self.loop_interval != new_interval:
            self.loop_interval = new_interval
            log.info(f"{self.__class__.__name__} self.loop_interval updated to {self.loop_interval}")

    def add_interval(self, ts):

        if self.last_loop_ts is None:
            self.last_loop_ts = ts
            return

        new_interval = ts - self.last_loop_ts
        if 1 <= new_interval <= 30:
            self.interval_history.append((ts, new_interval))
            self.update_interval()

        self.last_loop_ts = ts

    def save_pickle_data(self, report=False):

        try:
            with open(self.pickle_filename, "wb") as f:

                pfd2 = PickleFormattedDataV2(self.temp_history, self.interval_history)

                pickle.dump(pfd2, f)

                if report:
                    log.info(f"{self.__class__.__name__} saved self.loop_interval as {self.loop_interval} seconds and {len(self.temp_history)} records to the pickle file")

        except Exception as e:
            raise e
