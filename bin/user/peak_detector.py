
# Simple weeWX loop and archive service to detect when outTemp has peaked.

import logging
import numpy as np
import os
import pickle
import stat
import sys
import time
import weewx
import weewx.engine
import weewx.manager
import weewx.units

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

# https://stackoverflow.com/questions/22583391/peak-signal-detection-in-realtime-timeseries-data/56451135#56451135
class real_time_peak_detection():

    def __init__(self, array, lag, threshold, influence):
        self.y = list(array)
        self.length = len(self.y)
        self.lag = lag
        self.threshold = threshold
        self.influence = influence
        self.signals = [0] * len(self.y)
        self.filteredY = np.array(self.y).tolist()
        self.avgFilter = [0] * len(self.y)
        self.stdFilter = [0] * len(self.y)
        self.avgFilter[self.lag - 1] = np.mean(self.y[0:self.lag]).tolist()
        self.stdFilter[self.lag - 1] = np.std(self.y[0:self.lag]).tolist()

    def thresholding_algo(self, new_value):
        self.y.append(new_value)
        i = len(self.y) - 1
        self.length = len(self.y)

        if i < self.lag:
            return 0

        elif i == self.lag:
            self.signals = [0] * len(self.y)
            self.filteredY = np.array(self.y).tolist()
            self.avgFilter = [0] * len(self.y)
            self.stdFilter = [0] * len(self.y)
            self.avgFilter[self.lag] = np.mean(self.y[0:self.lag]).tolist()
            self.stdFilter[self.lag] = np.std(self.y[0:self.lag]).tolist()
            return 0

        self.signals += [0]
        self.filteredY += [0]
        self.avgFilter += [0]
        self.stdFilter += [0]

        if abs(self.y[i] - self.avgFilter[i - 1]) > (self.threshold * self.stdFilter[i - 1]):

            if self.y[i] > self.avgFilter[i - 1]:
                self.signals[i] = 1
            else:
                self.signals[i] = -1

            self.filteredY[i] = self.influence * self.y[i] + \
                (1 - self.influence) * self.filteredY[i - 1]
            self.avgFilter[i] = np.mean(self.filteredY[(i - self.lag):i])
            self.stdFilter[i] = np.std(self.filteredY[(i - self.lag):i])

        else:
            self.signals[i] = 0
            self.filteredY[i] = self.y[i]
            self.avgFilter[i] = np.mean(self.filteredY[(i - self.lag):i])
            self.stdFilter[i] = np.std(self.filteredY[(i - self.lag):i])

        return self.signals[i]

class PeakDetectorService(weewx.engine.StdService):

    def __init__(self, engine, config_dict):

        super(PeakDetectorService, self).__init__(engine, config_dict)

        self.config_dict = config_dict

        self.peak_detector = None

        self.drop_count = 0

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

        self.bind(weewx.NEW_LOOP_PACKET, self.handle_loop_packet)
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.handle_archive_record)

        log.info(f"{self.__class__.__name__} v{PEAKDETECTOR_VERSION} started")

    def handle_archive_record(self, event):

        record = event.record

        self.save_pickle_data(True)

        ts, temp = self.getTemp(record)
        if temp is None:
            return

        #log.info(f"{self.__class__.__name__} outTemp_max: {record['outTemp_max']}")

    def handle_loop_packet(self, event):

        packet = event.packet

        ts, temp = self.getTemp(packet)
        if temp is None:
            return

        signal = self.peak_detector.thresholding_algo(temp)

        log.info(f"signal: {signal}")

        if signal == -1:
            self.drop_count += 1
            if self.drop_count >= 5:
                self.has_peaked = True
        else:
            self.drop_count = 0

        log.info(f"self.drop_count: {self.drop_count}")

    def getTemp(self, packet):

        ts = packet.get("dateTime", int(time.time()))
        temp = packet.get("outTemp", None)

        if temp is None:
            return None

        try:
            return ts, round(float(temp), 1)
        except (ValueError, TypeError):
            return ts, None

    def shutDown(self):

        self.save_pickle_data(True)

        log.info(f"{self.__class__.__name__} v{PEAKDETECTOR_VERSION} stopped")

    def load_pickle_data(self):

        if os.path.exists(self.pickle_filename):

            try:
                with open(self.pickle_filename, "rb") as f:

                    ret = pickle.load(f)

                    if isinstance(ret, real_time_peak_detection):
                        log.info(f"{self.__class__.__name__} loaded a real_time_peak_detection class from the pickle file")
                        self.peak_detector = ret
                        return

            except Exception as e:
                pass

        self.db_lookup = weewx.manager.DBBinder(self.config_dict).bind_default()

        last_5min = int(time.time() / 300) * 300

        start = last_5min - (30 * 300)

        stats = TimespanBinder(TimeSpan(start, last_5min), self.db_lookup)

        initial_data = [round(row.outTemp.raw, 1) for row in stats.records()]

        log.logging(f"initial_data: {initial_data}")

        self.peak_detector = real_time_peak_detection(initial_data, lag=900, threshold=2.5, influence=0.1)

    def save_pickle_data(self, report=False):

        try:
            with open(self.pickle_filename, "wb") as f:

                pickle.dump(self.peak_detector, f)

                if report:
                    log.info(f"{self.__class__.__name__} saved self.peak_detector to the pickle file")

        except Exception as e:
            raise e
