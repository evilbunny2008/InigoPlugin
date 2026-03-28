
import logging
import numpy as np
import os
import pickle
import stat
import sys
import time
import weewx
import weewx.cheetahgenerator
import weewx.engine
import weewx.manager
import weewx.units
import weeutil.weeutil

from collections import deque
from datetime import datetime, timedelta
from weeutil.weeutil import TimeSpan
from weewx.units import FtoC
from weewx.tags import TimespanBinder

log = logging.getLogger(__name__)

VERSION = "0.0.3"

lag = 900
threshold = 2.0
influence = 0.02
peak_detector = None
done_work = False
trend_history = deque(maxlen=50)
current_ts = 0
current_signal = 0
current_count = 0
cache_dir = "/tmp/inigo"
usUnit = weewx.METRIC
pickle_filename = None
db_lookup = None

since_hour = 0

last_report_ts = 0
last_report = None

if sys.version_info[0] < 3 or (sys.version_info[0] == 3 and sys.version_info[1] < 7):
    raise weewx.UnsupportedFeature(
        f"InigoService v{VERSION} requires Python 3.7 or later, found %s.%s" % (sys.version_info[0], sys.version_info[1]))

if weewx.__version__ < "4":
    raise weewx.UnsupportedFeature(
        f"InigoService v{VERSION} requires WeeWX 4 or later, found %s" % weewx.__version__)

def load_pickle_data(class_name, createOrLoadData):

    global peak_detector, trend_history, current_ts, current_signal, current_count

    if os.path.exists(pickle_filename):

        try:
            with open(pickle_filename, "rb") as f:

                ret = pickle.load(f)

                if isinstance(ret, StrorageClass):
                    log.info(f"{class_name} loading a StrorageClass object from {pickle_filename} pickle cache file")
                    peak_detector = ret.peak_detector
                    trend_history = ret.trend_history
                    current_ts = ret.current_ts
                    current_signal = ret.current_signal
                    current_count = ret.current_count
                    log.info(f"{class_name} loaded peak_detector of length {peak_detector.length} and lag of {peak_detector.lag} from the pickle cache file")
                    log.info(f"{class_name} loaded trend_history of length {len(trend_history)} from the pickle cache file")
                    return

        except Exception as e:
            pass

    if not createOrLoadData:
        log.info(f"{class_name} {pickle_filename} doesn't exist, but not allowed to create one either")
        return

    reset_peak_detector(class_name)

def save_pickle_data(class_name, report=False):

    if not done_work:
        return

    try:
        with open(pickle_filename, "wb") as f:

            storageClass = StrorageClass(datetime.now(), peak_detector, trend_history, current_ts, current_signal, current_count)

            pickle.dump(storageClass, f)

            if report:
                log.info(f"{class_name} saved peak_detector of length {peak_detector.length} and lag of {peak_detector.lag} to the pickle cache file")
                log.info(f"{class_name} saved trend_history of length {len(trend_history)} to the pickle cache file")

    except Exception as e:
        raise e

def reset_peak_detector(class_name):

    global peak_detector

    if not done_work:
        return

    now = datetime.now()

    if now.hour < 6:

        initial_data = [0.0] * lag

        log.info(f"{class_name} Overnight reset, generated {len(initial_data)} zero data points")

        peak_detector = real_time_peak_detection(initial_data, lag=lag, threshold=threshold, influence=influence)

    else:

        min5_ago = int(time.time() / 300) * 300

        mins = lag * 2 / 60

        start = min5_ago - (lag * 2) - 60

        stats = TimespanBinder(TimeSpan(start, min5_ago), db_lookup)

        initial_data = [row.outTemp.raw for row in stats.records()]

        initial_data_expanded = [round(outTemp, 1) for outTemp in np.interp(np.linspace(0, len(initial_data) - 1, lag), np.arange(len(initial_data)), initial_data).tolist()]

        log.info(f"{class_name} Generated {len(initial_data_expanded)} data points using numpy based on past {mins} minutes of archive records")

        peak_detector = real_time_peak_detection(initial_data_expanded, lag=lag, threshold=threshold, influence=influence)

    log.info(f"{class_name} {pickle_filename} saved to")
    save_pickle_data(class_name, True)

def processConfigDict(class_name, config_dict):

    global lag, threshold, influence, peak_detector, done_work, trend_history, current_ts, current_signal, current_count, cache_dir, usUnit, pickle_filename, db_lookup, since_hour

    cfg = config_dict.get("StdReport", None)
    if cfg is not None:
        inigo = cfg.get("Inigo", None)
        if inigo is not None:
             cache_dir = inigo.get("cache_dir", "/tmp/inigo")
             since_hour = int(inigo.get("since_hour", 0))
             units = inigo.get("Units", None)
             if units is not None:
                 groups = units.get("Groups", None)
                 if groups is not None:
                     temp_group = groups.get("group_temperature", None)
                     if temp_group is not None and temp_group == "degree_F":
                         usUnit = weewx.US

    uid = os.getuid()
    statinfo = os.stat(cache_dir)
    cuid = statinfo.st_uid

    if uid != 0 and uid != cuid:
        raise weewx.UnsupportedFeature(
            f"{class_name} failed to start due to permissions on {cache_dir} directory uid: {uid}, cuid: {cuid}")

    if not 0 <= since_hour <= 23:
        since_hour = 0

    pickle_filename = os.path.join(cache_dir, "cache.pkl")

    log.info(f"{class_name} Pickle filename set to {pickle_filename}")

    db_lookup = weewx.manager.DBBinder(config_dict).bind_default()

def get_since_rain(class_name, timestamp):

    stop_time = datetime.fromtimestamp(timestamp)
    start_time = stop_time.replace(hour=since_hour, minute=0, second=0, microsecond=0)

    if stop_time < start_time:
        start_time -= timedelta(days=1)

    tspan = weeutil.weeutil.TimeSpan(int(start_time.timestamp()), int(stop_time.timestamp()))

    today = weewx.tags.TimespanBinder(tspan, db_lookup, context="day")

    start_time -= timedelta(days=1)
    stop_time -= timedelta(days=1)

    tspan = weeutil.weeutil.TimeSpan(int(start_time.timestamp()), int(stop_time.timestamp()))

    yesterday = weewx.tags.TimespanBinder(tspan, db_lookup, context="day")

    log.info(f"{class_name} since_hour: {since_hour}")
    log.info(f"{class_name} today.rain.sum.raw: {today.rain.sum.raw}")
    log.info(f"{class_name} yesterday.rain.sum.raw: {yesterday.rain.sum.raw}")

    return today.rain.sum.raw, yesterday.rain.sum.raw

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

class InigoSearchList(weewx.cheetahgenerator.SearchList):

    def __init__(self, generator):

        super(InigoSearchList, self).__init__(generator)

        self.generator = generator

    def get_extension_list(self, timespan, db_lookup):

        global last_report_ts, last_report

        if peak_detector is None:
            processConfigDict(self.__class__.__name__, self.generator.config_dict)
            load_pickle_data(self.__class__.__name__, False)
        else:
            log.info(f"{self.__class__.__name__} Data already loaded")

        log.info(f"{self.__class__.__name__} get_extension_list() called!")

        t1 = time.time()

        if last_report_ts == timespan.stop and last_report is not None:
            return [{"inigo": {"ts": last_report_ts, "report": last_report}}]

        log.info(f"{self.__class__.__name__} timespan.stop: {timespan.stop}")

        search_list_ts = []
        search_list_signal = []
        search_list_count = []

        if current_count > 0 and current_signal != 0 and current_ts <= timespan.stop:

            search_list_ts += [current_ts]
            search_list_signal += [current_signal]
            search_list_count += [current_count]

            log.info(f"{self.__class__.__name__} search_list_ts: {current_ts}")
            log.info(f"{self.__class__.__name__} search_list_signal: {current_signal}")
            log.info(f"{self.__class__.__name__} search_list_count: {current_count}")

        for ts, signal, count in reversed(trend_history):

            if signal == 0:
                continue

            if ts > timespan.stop:
                continue

            search_list_ts += [ts]
            search_list_signal += [signal]
            search_list_count += [count]

            #log.info(f"{self.__class__.__name__} outTemp_trend_{trendCount}_ts: {ts}")
            #log.info(f"{self.__class__.__name__} outTemp_trend_{trendCount}_signal: {signal}")
            #log.info(f"{self.__class__.__name__} outTemp_trend_{trendCount}_count: {count}")

        since_today, since_yesterday = get_since_rain(self.__class__.__name__, timespan.stop)

        search_list_extension = {
            "since_hour": since_hour,
            "since_today": since_today,
            "since_yesterday": since_yesterday,
            "search_list_ts": search_list_ts,
            "search_list_signal": search_list_signal,
            "search_list_count": search_list_count,
        }

        last_report_ts = timespan.stop
        last_report = search_list_extension

        t2 = time.time()

        log.info(f"{self.__class__.__name__} Since SLE executed in {(t2-t1):.3f} seconds")

        return [{"inigo": {"ts": last_report_ts, "report": last_report}}]

class InigoService(weewx.engine.StdService):

    def __init__(self, engine, config_dict):

        super(InigoService, self).__init__(engine, config_dict)

        if peak_detector is None:
            processConfigDict(self.__class__.__name__, config_dict)
            load_pickle_data(self.__class__.__name__, True)
        else:
            log.info(f"{self.__class__.__name__} Data already loaded")

        self.bind(weewx.NEW_LOOP_PACKET, self.handle_loop_packet)
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.handle_archive_record)

        log.info(f"{self.__class__.__name__} v{VERSION} started")

    def handle_archive_record(self, event):

        now = datetime.now()
        if peak_detector.start_time.date() != now.date():
            log.info(f"{self.__class__.__name__} {peak_detector.start_time.date()} != {now.date()} calling reset_peak_detector()")

            reset_peak_detector(self.__class__.__name__)

        save_pickle_data(self.__class__.__name__, True)

    def handle_loop_packet(self, event):

        global peak_detector, trend_history, current_ts, current_signal, current_count

        packet = event.packet

        ts, temp = self.getTemp(packet)
        if temp is None:
            return

        done_work = True

        signal = peak_detector.thresholding_algo(temp)

        # Saving on every loop packet is probably excessive when saving for archive records and on shutdown would be sufficient unless weeWX crashes frequently
        #self.save_pickle_data()

        if signal == 0:
            return

        if signal == current_signal:
            current_count += 1

        else:
            # Signal changed — store the completed run
            if current_count > 0:
                trend_history.append((current_ts, current_signal, current_count))

            current_ts = ts
            current_signal = signal
            current_count = 1

    def getTemp(self, packet):

        ts = int(packet.get("dateTime", time.time()))
        temp = packet.get("outTemp", None)

        if temp is None:
            return None

        try:
            return ts, round(float(temp), 1)
        except (ValueError, TypeError):
            return ts, None

    def shutDown(self):

        save_pickle_data(self.__class__.__name__, True)

        log.info(f"{self.__class__.__name__} v{VERSION} stopped")
