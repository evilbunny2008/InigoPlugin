
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

        self.start_time = datetime.now()

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

class StrorageClass():

    def __init__(self, dt, peak_detector, trend_history, current_ts, current_signal, current_count):

        self.dt = dt
        self.peak_detector = peak_detector
        self.trend_history = trend_history
        self.current_ts = current_ts
        self.current_signal = current_signal
        self.current_count = current_count

class PeakDetectorService(weewx.engine.StdService):

    def __init__(self, engine, config_dict):

        super(PeakDetectorService, self).__init__(engine, config_dict)

        self.config_dict = config_dict

        self.lag = 900
        self.threshold = 2.0
        self.influence = 0.02

        self.peak_detector = None

        self.trend_history = deque(maxlen=50)
        self.current_ts = 0
        self.current_signal = 0
        self.current_count = 0

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
                f"{self.__class__.__name__} failed to start due to permissions on {self.cache_dir} directory uid: {uid}, cuid: {cuid}")

        self.pickle_filename = os.path.join(self.cache_dir, "peak_detector.pkl")

        self.db_lookup = weewx.manager.DBBinder(self.config_dict).bind_default()

        self.load_pickle_data()

        self.bind(weewx.NEW_LOOP_PACKET, self.handle_loop_packet)
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.handle_archive_record)

        log.info(f"{self.__class__.__name__} v{PEAKDETECTOR_VERSION} started")

    def handle_archive_record(self, event):

        record = event.record

        now = datetime.now()
        if self.peak_detector.start_time.date() != now.date():
            log.info(f"{self.peak_detector.start_time.date()} != {now.date()} calling self.reset_peak_detector()")

            self.reset_peak_detector()

            self.outputTrendHistory(record)

            return

        self.save_pickle_data(True)

        self.outputTrendHistory(record)

    def handle_loop_packet(self, event):

        packet = event.packet

        ts, temp = self.getTemp(packet)
        if temp is None:
            return

        signal = self.peak_detector.thresholding_algo(temp)

        # Saving on every loop packet is probably excessive when saving for archive records and on shutdown would be sufficient unless weeWX crashes frequently
        #self.save_pickle_data()

        if signal == self.current_signal:
            self.current_count += 1

        else:
            # Signal changed — store the completed run
            if self.current_count > 0:
                self.trend_history.append((self.current_ts, self.current_signal, self.current_count))

            self.current_ts = ts
            self.current_signal = signal
            self.current_count = 1

    def outputTrendHistory(self, record):

        trendCount = -1
        if self.current_count > 0:

            trendCount += 1

            record[f"outTemp_trend{trendCount}_ts"] = self.current_ts
            record[f"outTemp_trend{trendCount}_signal"] = self.current_signal
            record[f"outTemp_trend{trendCount}_count"] = self.current_count

            #log.info(f"{self.__class__.__name__} outTemp_trend{trendCount}_ts: {self.current_ts}")
            #log.info(f"{self.__class__.__name__} outTemp_trend{trendCount}_signal: {self.current_signal}")
            #log.info(f"{self.__class__.__name__} outTemp_trend{trendCount}_count: {self.current_count}")

        for ts, signal, count in reversed(self.trend_history):

            trendCount += 1

            record[f"outTemp_trend{trendCount}_ts"] = ts
            record[f"outTemp_trend{trendCount}_signal"] = signal
            record[f"outTemp_trend{trendCount}_count"] = count

            #log.info(f"{self.__class__.__name__} outTemp_trend{trendCount}_ts: {ts}")
            #log.info(f"{self.__class__.__name__} outTemp_trend{trendCount}_signal: {signal}")
            #log.info(f"{self.__class__.__name__} outTemp_trend{trendCount}_count: {count}")

    def reset_peak_detector(self):

        now = datetime.now()

        if now.hour < 6:

            initial_data = [0.0] * self.lag

            log.info(f"{self.__class__.__name__} Overnight reset, generated {len(initial_data)} zero data points")

            self.peak_detector = real_time_peak_detection(initial_data, lag=self.lag, threshold=self.threshold, influence=self.influence)

        else:

            min5_ago = int(time.time() / 300) * 300

            mins = self.lag * 2 / 60

            start = min5_ago - (self.lag * 2) - 60

            stats = TimespanBinder(TimeSpan(start, min5_ago), self.db_lookup)

            initial_data = [row.outTemp.raw for row in stats.records()]

            initial_data_expanded = [round(outTemp, 1) for outTemp in np.interp(np.linspace(0, len(initial_data) - 1, self.lag), np.arange(len(initial_data)), initial_data).tolist()]

            log.info(f"{self.__class__.__name__} Generated {len(initial_data_expanded)} data points using numpy based on past {mins} minutes of archive records")

            self.peak_detector = real_time_peak_detection(initial_data_expanded, lag=self.lag, threshold=self.threshold, influence=self.influence)

        self.save_pickle_data(True)

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

                    if isinstance(ret, StrorageClass):
                        log.info(f"{self.__class__.__name__} loading a StrorageClass object from the pickle file")
                        self.peak_detector = ret.peak_detector
                        self.trend_history = ret.trend_history
                        self.current_ts = ret.current_ts
                        self.current_signal = ret.current_signal
                        self.current_count = ret.current_count
                        log.info(f"{self.__class__.__name__} loaded a real_time_peak_detection class from the pickle file with length of {self.peak_detector.length} and lag of {self.peak_detector.lag} and\n" + \
                                 f"self.trend_history of length {len(self.trend_history)} from the pickle cache file")
                        return

            except Exception as e:
                pass

        self.reset_peak_detector()

    def save_pickle_data(self, report=False):

        try:
            with open(self.pickle_filename, "wb") as f:

                storageClass = StrorageClass(datetime.now(), self.peak_detector, self.trend_history, self.current_ts, self.current_signal, self.current_count)

                pickle.dump(storageClass, f)

                if report:
                    log.info(f"{self.__class__.__name__} saved self.peak_detector of length {self.peak_detector.length} and lag of {self.peak_detector.lag} and\n" + \
                              f"self.trend_history of length {len(self.trend_history)} to the pickle cache file")

        except Exception as e:
            raise e
