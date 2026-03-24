
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

class PeakDetectorService(weewx.engine.StdService):

    def __init__(self, engine, config_dict):

        super(PeakDetectorService, self).__init__(engine, config_dict)

        self.temp_history = None

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
        suid = statinfo.st_uid

        if uid != suid:
            raise weewx.UnsupportedFeature(
                f"PeakDetectorService failed to start due to permissions on {self.cache_dir} directory")

        self.pickle_filename = os.path.join(self.cache_dir, "peak_detector.pkl")

        self.load_pickle_data()

        self.loop_interval = 0
        self.last_loop_ts = None

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

        log.info(f"{self.__class__.__name__} outTemp_trend1: {record['outTemp_trend1']}")
        log.info(f"{self.__class__.__name__} outTemp_trend5: {record['outTemp_trend5']}")
        log.info(f"{self.__class__.__name__} outTemp_trend10: {record['outTemp_trend10']}")
        log.info(f"{self.__class__.__name__} outTemp_trend30: {record['outTemp_trend30']}")
        log.info(f"{self.__class__.__name__} outTemp_trend60: {record['outTemp_trend60']}")

    def handle_loop_packet(self, event):

        packet = event.packet

        ts, temp = self.getTemp(packet)
        if temp is None:
            return

        self.temp_history.append((ts, temp))

        self.save_pickle_data()

        if self.last_loop_ts is None:
            self.last_loop_ts = ts
            return

        #log.info(f"{self.__class__.__name__} ts - self.last_loop_ts == {(ts - self.last_loop_ts)} seconds")

        if self.loop_interval != ts - self.last_loop_ts and ts - self.last_loop_ts >= 2:
            self.loop_interval = ts - self.last_loop_ts
            log.info(f"{self.__class__.__name__} self.loop_interval set to {self.loop_interval} seconds")

        self.last_loop_ts = ts

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

        samples = int(seconds / self.loop_interval)

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

                    if ret is not None:
                        if isinstance(ret, PickleFormattedData):
                            self.temp_history = ret.temp_history
                            self.loop_interval = ret.loop_interval
                        elif isinstance(ret, deque):
                            self.temp_history = ret

                        if self.temp_history is not None:
                            temps = [t for _, t in self.temp_history]

                            log.info(f"{self.__class__.__name__} loaded {len(temps)} records from pickle file")
                            if self.loop_interval > 0:
                                log.info(f"{self.__class__.__name__} self.loop_interval set to {self.loop_interval} seconds")

                            return

            except Exception as e:
                pass

        log.info(f"{self.__class__.__name__} self.temp_history = deque(maxlen=1800)")
        self.temp_history = deque(maxlen=1800)

    def save_pickle_data(self, report=False):

        try:
            with open(self.pickle_filename, "wb") as f:

                pfd = PickleFormattedData(self.temp_history, self.loop_interval)

                pickle.dump(pfd, f)

                if report:
                    log.info(f"{self.__class__.__name__} saved self.loop_interval as {self.loop_interval} seconds and {len(self.temp_history)} records to the pickle file")

        except Exception as e:
            raise e

