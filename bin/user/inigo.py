
import logging
import os
import pickle
import stat
import sys
import time
import weecfg
import weewx
import weewx.cheetahgenerator
import weewx.engine
import weewx.manager
import weewx.units
import weeutil.weeutil

from collections import deque
from datetime import datetime, timedelta
from functools import reduce
from weeutil.weeutil import TimeSpan, to_float
from weewx.units import FtoC
from weewx.tags import TimespanBinder

log = logging.getLogger(__name__)

VERSION = "1.0.0"
JSONversion = 1000000

mm = 0
inch = 1
cm = 2
C = 0
F = 1

lag = default_lag = 1800
threshold = default_threshold = 2.0
influence = default_influence = 0.02
peak_detector = None
trend_history_maxlen = 25
trend_history = deque(maxlen=trend_history_maxlen)
last_ts = 0
current_ts = 0
current_signal = 0
current_count = 0
cache_dir = "/tmp/inigo"
temp_unit = C
rain_unit = mm
pickle_filename = None
db_lookup = None

since_hour = 0

last_report_ts = 0
last_report = None

weewx.units.obs_group_dict['since_today'] = 'group_rain'
weewx.units.obs_group_dict['since_yesterday'] = 'group_rain'
weewx.units.obs_group_dict['since_month_to_date'] = 'group_rain'
weewx.units.obs_group_dict['since_last_month'] = 'group_rain'
weewx.units.obs_group_dict['since_year_to_date'] = 'group_rain'
weewx.units.obs_group_dict['since_last_year'] = 'group_rain'
weewx.units.obs_group_dict['since_alltime'] = 'group_rain'

REQUIRED_WEEWX = "5.3.0"

def fatal_error(error_str):

    print()
    print(error_str)
    print()
    print()
    raise weewx.UnsupportedFeature("Fatal Error")


if sys.version_info[0] < 3 or (sys.version_info[0] == 3 and sys.version_info[1] < 7):
    fatal_error(f"InigoService requires Python 3.7 or later, found {sys.version_info[0]}.{sys.version_info[1]}")

if weeutil.weeutil.version_compare(weewx.__version__, REQUIRED_WEEWX) < 0:
    fatal_error(f"InigoService requires WeeWX {REQUIRED_WEEWX} or later, found {weewx.__version__}")

try:
    import numpy as np
    np.array([1.0, 2.0, 3.0])
except (ImportError, Exception):
    fatal_error(f"InigoService requires the numpy python module to be installed.\n\nPlease view this wiki page for installation details: https://github.com/evilbunny2008/InigoPlugin/blob/main/README.md")

def load_pickle_data(class_name):

    global peak_detector, trend_history, last_ts, current_ts, current_signal, current_count

    if os.path.exists(pickle_filename):

        try:
            with open(pickle_filename, "rb") as f:

                ret = pickle.load(f)

                if isinstance(ret, StrorageClass):

                    if time.time() - ret.last_ts > 600:

                        log.info(f"{class_name} StrorageClass object from {pickle_filename} is too old, skipping...")

                    elif ret.peak_detector.lag != default_lag:

                        log.info(f"{class_name} StrorageClass object from {pickle_filename} different lag, skipping...")

                    elif ret.peak_detector.influence != default_influence:

                        log.info(f"{class_name} StrorageClass object from {pickle_filename} different influence, skipping...")

                    elif ret.peak_detector.threshold != default_threshold:

                        log.info(f"{class_name} StrorageClass object from {pickle_filename} different threshold, skipping...")

                    else:

                        log.info(f"{class_name} loading a StrorageClass object from {pickle_filename} pickle cache file")

                        peak_detector = ret.peak_detector
                        trend_history = ret.trend_history
                        last_ts = ret.last_ts
                        current_ts = ret.current_ts
                        current_signal = ret.current_signal
                        current_count = ret.current_count

                        log.info(f"{class_name} loaded peak_detector of length {peak_detector.length} and lag of {peak_detector.lag} from the pickle cache file")
                        log.info(f"{class_name} loaded trend_history of length {len(trend_history)} from the pickle cache file")

                        return

        except Exception as e:
            pass

    log.info(f"{class_name} {pickle_filename} doesn't exist, creating it")
    reset_peak_detector(class_name)

def save_pickle_data(class_name, report=False):

    try:
        with open(pickle_filename, "wb") as f:

            storageClass = StrorageClass(datetime.now(), peak_detector, trend_history, int(time.time()), current_ts, current_signal, current_count)

            pickle.dump(storageClass, f)

            if report:
                log.info(f"{class_name} saved peak_detector of length {peak_detector.length} and lag of {peak_detector.lag} to the pickle cache file")
                log.info(f"{class_name} saved trend_history of length {len(trend_history)} to the pickle cache file")

    except Exception as e:
        fatal_error(f" Error!, e: {str(e)}")

def reset_peak_detector(class_name):

    global peak_detector

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

        initial_data = []
        for row in stats.records():
            outTemp = convert_temp_to_float(row.outTemp.raw)
            if outTemp is None:
                log.info(f"outTemp '{row.outTemp.raw}' type '{type(row.outTemp.raw).__name__}' failed to convert to float, skipping...")
                continue

            initial_data += [outTemp]

        initial_data_expanded = [outTemp for outTemp in np.interp(np.linspace(0, len(initial_data) - 1, lag), np.arange(len(initial_data)), initial_data).tolist()]

        log.info(f"{class_name} Generated {len(initial_data_expanded)} data points using numpy based on past {mins} minutes of archive records")

        peak_detector = real_time_peak_detection(initial_data_expanded, lag=lag, threshold=threshold, influence=influence)

    log.info(f"{class_name} {pickle_filename} saved to")
    save_pickle_data(class_name, True)

def processConfigDict(class_name, config_dict):

    global lag, threshold, influence, peak_detector, trend_history, current_ts, current_signal, current_count, cache_dir, pickle_filename, db_lookup, since_hour, VERSION, JSONversion, temp_unit, rain_unit

    try:
        root_dict = weeutil.startup.extract_roots(config_dict)
        if root_dict is not None:
            ext_dir = root_dict.get("EXT_DIR", None)
            if ext_dir is not None:
                ext_cache_dir = os.path.join(ext_dir, "Inigo")
                _, installer = weecfg.get_extension_installer(ext_cache_dir)
                VERSION = installer.get("version", "1.0.0")

                major = 1
                minor = patch = 0
                Inigoversion = VERSION.split(".")

                if len(Inigoversion) > 0:
                    major = convert_to_int(Inigoversion[0])

                if len(Inigoversion) > 1:
                    minor = convert_to_int(Inigoversion[1])

                if len(Inigoversion) > 2:
                    patch = convert_to_int(Inigoversion[2])

                if major < 1:
                    major = 1

                JSONversion = int(f"{major}{minor:03d}{patch:03d}")

    except Exception as e:
        log.info(f"Error! Unable to get plugin version, e: {str(e)}")

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

                     rain_group = groups.get("group_rain", None)
                     if rain_group is not None and rain_group == "inch":
                         rain_unit = inch

                     if rain_group is not None and rain_group == "cm":
                         rain_unit = cm

                     temp_group = groups.get("group_temperature", None)
                     if temp_group is not None and temp_group == "degree_F":
                         temp_unit = imperial

    uid = os.getuid()
    statinfo = os.stat(cache_dir)
    cuid = statinfo.st_uid

    if uid != 0 and uid != cuid:
        fatal_error(f"{class_name} failed to start due to permissions on {cache_dir} directory uid: {uid}, cuid: {cuid}")

    if not 0 <= since_hour <= 23:
        since_hour = 0

    pickle_filename = os.path.join(cache_dir, "cache.pkl")

    log.info(f"{class_name} Pickle filename set to {pickle_filename}")

    db_lookup = weewx.manager.DBBinder(config_dict).bind_default()

def get_modified_rain_reset_time(class_name, timestamp, time_period):

    if time_period in ("today", "yesterday"):
        context="day"
    elif time_period in ("month_to_date", "last_month"):
        context="month"
    elif time_period in ("year_to_date", "last_year"):
        context="year"
    elif time_period == "alltime":
        context="alltime"
    else:
        log.info(f"'{time_period}' is invalid, skipping...")
        return

    stop_time = current_stop_time = datetime.fromtimestamp(timestamp)
    start_time = stop_time.replace(hour=since_hour, minute=0, second=0, microsecond=0)
    if stop_time < start_time:
        start_time -= timedelta(days=1)

    if time_period == "yesterday":
        stop_time = start_time - timedelta(microseconds=1)
        start_time -= timedelta(days=1)

    elif time_period == "month_to_date":
        stop_time = current_stop_time
        start_time = stop_time.replace(day=1, hour=since_hour, minute=0, second=0, microsecond=0)

    elif time_period == "last_month":
        start_time = current_stop_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(microseconds=1)
        start_time = start_time.replace(day=1, hour=since_hour, minute=0, second=0, microsecond=0)
        stop_time = current_stop_time.replace(day=1, hour=since_hour, minute=0, second=0, microsecond=0) - timedelta(microseconds=1)

    elif time_period == "year_to_date":
        stop_time = current_stop_time
        start_time = stop_time.replace(month=1, day=1, hour=since_hour, minute=0, second=0, microsecond=0)

    elif time_period == "last_year":
        start_time = current_stop_time.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(microseconds=1)
        start_time = start_time.replace(month=1, day=1, hour=since_hour, minute=0, second=0, microsecond=0)
        stop_time = current_stop_time.replace(month=1, day=1, hour=since_hour, minute=0, second=0, microsecond=0) - timedelta(microseconds=1)

    elif time_period == "alltime":
        stop_time = current_stop_time
        start_time = stop_time.replace(year=2000, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    tspan = weeutil.weeutil.TimeSpan(int(start_time.timestamp()), int(stop_time.timestamp()))

    period = weewx.tags.TimespanBinder(tspan, db_lookup, context=context)

    #log.info(f"{class_name} since_{time_period}.rain.sum.raw: {period.rain.sum.raw}")

    rain = period.rain.sum

    if rain_unit == mm:
        rain = rain.convert("mm")

    if rain_unit == cm:
        rain = rain.convert("cm")

    return rain.raw

def convert_to_int(str):

    newnum = convert_temp_to_float(str)
    if newnum is None:
        return 0

    return int(newnum)

def convert_temp_to_float(temp):

    if isinstance(temp, float):
        return temp

    try:
        temp_f = to_float(temp)
        if temp_f is None:
            return None

        if not isinstance(temp_f, float):
            log.info(f"Failed to convert '{temp}' to a float, temp became `{temp_f}` of type '{type(temp_f).__name__}' but this is probably wrong, no error generated, skipping...")
            return None

        return temp_f
    except (ValueError, TypeError, Exception) as e:
        log.info(f"Failed to convert '{temp}' of type '{type(temp).__name__}' to a float, e: {str(e)}, skipping...")

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

    def __init__(self, dt, peak_detector, trend_history, last_ts, current_ts, current_signal, current_count):

        self.dt = dt
        self.peak_detector = peak_detector
        self.trend_history = trend_history
        self.last_ts = last_ts
        self.current_ts = current_ts
        self.current_signal = current_signal
        self.current_count = current_count

class InigoSearchList(weewx.cheetahgenerator.SearchList):

    def __init__(self, generator):

        super(InigoSearchList, self).__init__(generator)

    def get_extension_list(self, timespan, db_lookup):

        global last_report_ts, last_report

        log.info(f"{self.__class__.__name__} InigoSearchList v{VERSION} called!")

        if peak_detector is None:
            fatal_error(f"{self.__class__.__name__} InigoSearchList failed to detect InigoService running, exitting...")

        t1 = time.time()

        def sort_dict(dict_name):

            if dict_name is None or len(dict_name) == 0:
                return dict_name

            now = dict_name.get("now", None)
            if now is not None:
                del dict_name["now"]

            processingErrors = dict_name.get("processingErrors", None)
            if processingErrors is not None:
                del dict_name["processingErrors"]

            dict_version = dict_name.get("version", None)

            log.info(f"dict_version: {dict_version}")

            if dict_version is not None:
                del dict_name["version"]

            new_dict = dict(sorted(dict_name.items(), key=lambda x: x[0].lower()))

            now_dict = {}

            if dict_version is not None:
                now_dict["version"] = dict_version

            if now is not None:
                now_dict["now"] = now

            if processingErrors is not None:
                now_dict["processingErrors"] = processingErrors

            return {**now_dict, **new_dict}

        if last_report_ts == timespan.stop and last_report is not None:
            return [{"inigo": {"ts": last_report_ts, "report": last_report}, "sort_dict": sort_dict}]

        #log.info(f"{self.__class__.__name__} timespan.start: {timespan.start}")
        #log.info(f"{self.__class__.__name__} timespan.stop: {timespan.stop}")

        search_list_ts = []
        search_list_signal = []
        search_list_count = []

        if current_count > 0 and current_signal != 0 and current_ts <= timespan.stop:

            search_list_ts += [current_ts]
            search_list_signal += [current_signal]
            search_list_count += [current_count]

            log.info(f"{self.__class__.__name__} InigoSearchList current_ts: {current_ts}")
            log.info(f"{self.__class__.__name__} InigoSearchList current_signal: {current_signal}")
            log.info(f"{self.__class__.__name__} InigoSearchList current_count: {current_count}")

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

        since_today = get_modified_rain_reset_time(self.__class__.__name__, timespan.stop, "today")
        since_yesterday = get_modified_rain_reset_time(self.__class__.__name__, timespan.stop, "yesterday")
        since_month_to_date = get_modified_rain_reset_time(self.__class__.__name__, timespan.stop, "month_to_date")
        since_last_month = get_modified_rain_reset_time(self.__class__.__name__, timespan.stop, "last_month")
        since_year_to_date = get_modified_rain_reset_time(self.__class__.__name__, timespan.stop, "year_to_date")
        since_last_year = get_modified_rain_reset_time(self.__class__.__name__, timespan.stop, "last_year")
        since_alltime = get_modified_rain_reset_time(self.__class__.__name__, timespan.stop, "alltime")

        search_list_extension = {
            "search_list_ts": search_list_ts,
            "search_list_signal": search_list_signal,
            "search_list_count": search_list_count,
            "since_hour": since_hour,
            "since_today": since_today,
            "since_yesterday": since_yesterday,
            "since_month_to_date": since_month_to_date,
            "since_last_month": since_last_month,
            "since_year_to_date": since_year_to_date,
            "since_last_year": since_last_year,
            "since_alltime": since_alltime,
        }

        log.info(f"since_today: {since_today}")
        log.info(f"since_yesterday: {since_yesterday}")
        log.info(f"since_month_to_date: {since_month_to_date}")
        log.info(f"since_last_month: {since_last_month}")
        log.info(f"since_year_to_date: {since_year_to_date}")
        log.info(f"since_last_year: {since_last_year}")
        log.info(f"since_alltime: {since_alltime}")

        last_report_ts = timespan.stop
        last_report = search_list_extension

        t2 = time.time()

        log.info(f"{self.__class__.__name__} executed in {(t2-t1):.3f} seconds")

        return [{"inigo": {"ts": last_report_ts, "report": last_report}, "sort_dict": sort_dict}]

class InigoService(weewx.engine.StdService):

    def __init__(self, engine, config_dict):

        super(InigoService, self).__init__(engine, config_dict)

        self.done_work = False

        if peak_detector is None:
            processConfigDict(self.__class__.__name__, config_dict)
            load_pickle_data(self.__class__.__name__)
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

        global peak_detector, trend_history, last_ts, current_ts, current_signal, current_count

        self.done_work = True

        packet = event.packet

        ret = self.getTemp(packet)
        if ret is None or len(ret) != 2:
            return

        ts, temp = ret

        if ts is not None and ts > 0:
            last_ts = ts

        if temp is None:
            return

        signal = peak_detector.thresholding_algo(temp)

        # Saving on every loop packet is probably excessive when saving for archive records and on shutdown would be sufficient unless weeWX crashes frequently
        #self.save_pickle_data()

        if signal == 0:
            return

        if signal == current_signal:
            current_count += 1
            #log.info(f"{self.__class__.__name__} current_signal: {current_signal}")
            #log.info(f"{self.__class__.__name__} current_count: {current_count}")

        else:
            # Signal changed — store the completed run
            log.info(f"{self.__class__.__name__} signal switched from {current_signal} with count {current_count} to {signal}")

            if current_count > 0:
                trend_history.append((current_ts, current_signal, current_count))

            current_ts = ts
            current_signal = signal
            current_count = 1

    def getTemp(self, packet):

        ts = int(packet.get("dateTime", time.time()))
        temp = packet.get("outTemp", None)

        if temp is None:
            return ts, None

        temp = convert_temp_to_float(temp)

        return ts, temp

    def shutDown(self):

        if self.done_work:
            save_pickle_data(self.__class__.__name__, True)

        log.info(f"{self.__class__.__name__} v{VERSION} stopped")
