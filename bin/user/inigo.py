
import inspect
import logging
import os
import pickle
import pprint
import stat
import sys
import time
import traceback
import weecfg
import weewx
import weewx.cheetahgenerator
import weewx.engine
import weewx.manager
import weewx.reportengine
import weewx.units
import weeutil.weeutil

from collections import deque
from datetime import datetime, timedelta
from functools import reduce
from pathlib import Path
from weeutil.weeutil import TimeSpan, to_bool, to_float
from weewx.reportengine import build_skin_dict, ReportTiming, set_cwd, set_locale
from weewx.units import FtoC, getUnitGroup, ValueHelper
from weewx.tags import AggTypeBinder, TimeBinder, TimespanBinder

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
pickle_filename = None

last_report_ts = 0
last_report = None

weewx.units.obs_group_dict["since_today"] = "group_rain"
weewx.units.obs_group_dict["since_yesterday"] = "group_rain"
weewx.units.obs_group_dict["since_month_to_date"] = "group_rain"
weewx.units.obs_group_dict["since_last_month"] = "group_rain"
weewx.units.obs_group_dict["since_year_to_date"] = "group_rain"
weewx.units.obs_group_dict["since_last_year"] = "group_rain"
weewx.units.obs_group_dict["since_alltime"] = "group_rain"

REQUIRED_WEEWX = "5.3.0"

def fatal_error(error_str):

    log.error(error_str)
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

def load_pickle_data(class_name, db_lookup):

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

                        log.debug(f"{class_name} loading a StrorageClass object from {pickle_filename} pickle cache file")

                        peak_detector = ret.peak_detector
                        trend_history = ret.trend_history
                        last_ts = ret.last_ts
                        current_ts = ret.current_ts
                        current_signal = ret.current_signal
                        current_count = ret.current_count

                        log.debug(f"{class_name} loaded peak_detector of length {peak_detector.length} and lag of {peak_detector.lag} from the pickle cache file")
                        log.debug(f"{class_name} loaded trend_history of length {len(trend_history)} from the pickle cache file")

                        return

        except Exception as e:
            pass

    log.debug(f"{class_name} {pickle_filename} doesn't exist, creating it")
    reset_peak_detector(class_name, db_lookup)

def save_pickle_data(class_name, report=False):

    try:
        with open(pickle_filename, "wb") as f:

            storageClass = StrorageClass(datetime.now(), peak_detector, trend_history, int(time.time()), current_ts, current_signal, current_count)

            pickle.dump(storageClass, f)

            if report:
                log.debug(f"{class_name} saved peak_detector of length {peak_detector.length} and lag of {peak_detector.lag} to the pickle cache file")
                log.debug(f"{class_name} saved trend_history of length {len(trend_history)} to the pickle cache file")

    except Exception as e:
        fatal_error(f" Error!, e: {str(e)}")

def reset_peak_detector(class_name, db_lookup):

    global peak_detector

    now = datetime.now()

    if now.hour < 6:

        initial_data = [0.0] * lag

        log.debug(f"{class_name} Overnight reset, generated {len(initial_data)} zero data points")

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
                log.error(f"outTemp '{row.outTemp.raw}' type '{type(row.outTemp.raw).__name__}' failed to convert to float, skipping...")
                continue

            initial_data += [outTemp]

        initial_data_expanded = [outTemp for outTemp in np.interp(np.linspace(0, len(initial_data) - 1, lag), np.arange(len(initial_data)), initial_data).tolist()]

        log.debug(f"{class_name} Generated {len(initial_data_expanded)} data points using numpy based on past {mins} minutes of archive records")

        peak_detector = real_time_peak_detection(initial_data_expanded, lag=lag, threshold=threshold, influence=influence)

    log.debug(f"{class_name} {pickle_filename} saved to")
    save_pickle_data(class_name, True)

def processConfigDict(class_name, config_dict):

    global lag, threshold, influence, peak_detector, trend_history, current_ts, current_signal, current_count, cache_dir, pickle_filename, VERSION, JSONversion

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
        log.error(f"Error! Unable to get plugin version, e: {str(e)}")

    cfg = config_dict.get("StdReport", None)
    if cfg is not None:
        inigo_data_dict = cfg.get("Inigo-Data", None)
        if inigo_data_dict is not None:
             cache_dir = inigo_data_dict.get("cache_dir", cache_dir)

    uid = os.getuid()
    statinfo = os.stat(cache_dir)
    cuid = statinfo.st_uid

    if uid != 0 and uid != cuid:
        fatal_error(f"{class_name} failed to start due to permissions on {cache_dir} directory uid: {uid}, cuid: {cuid}")

    pickle_filename = os.path.join(cache_dir, "cache.pkl")

    log.debug(f"{class_name} Pickle filename set to {pickle_filename}")

def get_modified_rain_reset_time(class_name, db_lookup, timestamp, time_period, group_rain, since_hour):

    if time_period in ("today", "yesterday"):
        context="day"
    elif time_period in ("month_to_date", "last_month"):
        context="month"
    elif time_period in ("year_to_date", "last_year", "alltime"):
        context="year"
    else:
        log.error(f"'{time_period}' is invalid, skipping...")
        return

    current_stop_time = datetime.fromtimestamp(timestamp)

    if time_period == "today":
        stop_time = current_stop_time
        start_time = stop_time.replace(hour=since_hour, minute=0, second=0, microsecond=0)
        if stop_time < start_time:
            start_time = current_stop_time.replace(hour=since_hour, minute=0, second=0, microsecond=0)
            stop_time = start_time - timedelta(microseconds=1)
            start_time -= timedelta(days=1)

    elif time_period == "yesterday":
        stop_time = current_stop_time.replace(hour=since_hour, minute=0, second=0, microsecond=0)

        if stop_time > datetime.now():
            stop_time -= timedelta(days=1)

        start_time = stop_time - timedelta(days=1)
        stop_time -= timedelta(microseconds=1)

    elif time_period == "month_to_date":
        stop_time = current_stop_time
        start_time = stop_time.replace(day=1, hour=since_hour, minute=0, second=0, microsecond=0)
        if stop_time < start_time:
            stop_time = current_stop_time.replace(day=1, hour=since_hour, minute=0, second=0, microsecond=0)
            start_time = current_stop_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(microseconds=1)
            start_time = start_time.replace(day=1, hour=since_hour, minute=0, second=0, microsecond=0)

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

    tspan = TimeSpan(int(start_time.timestamp()), int(stop_time.timestamp()))

    period = TimespanBinder(tspan, db_lookup, context=context)

    rain = period.rain.sum

    if not rain.has_data():
        log.info(f"{time_period}.rain.sum.has_data() is False")
        return None

    return rain.convert(group_rain).raw

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
            log.error(f"Failed to convert '{temp}' to a float, temp became `{temp_f}` of type '{type(temp_f).__name__}' but this is probably wrong, no error generated, skipping...")
            return None

        return temp_f
    except (ValueError, TypeError, Exception) as e:
        log.error(f"Failed to convert '{temp}' of type '{type(temp).__name__}' to a float, e: {str(e)}, skipping...")

def dict_search(d, key_search):

    results = []

    if d is None or key_search is None or key_search.strip() == "":
        return results

    for key, value in d.items():

        if key == key_search:
            results.append(value)

        elif isinstance(value, dict):
            results.extend(dict_search(value, key_search))

    return results

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

class PeriodicReportTiming(ReportTiming):

    def __init__(self, raw_line, skin_dict):

        self.create_if_missing = False
        self.skin_dict = skin_dict

        try:
            line_str = raw_line.strip()
        except AttributeError:
            line_str = ','.join(raw_line).strip()

        for unsupported_char in ('%', '#', 'L', 'W'):
            if unsupported_char in line_str:
                self.is_valid = False
                self.validation_error = "Unsupported character '%s' in '%s'." % (unsupported_char,
                                                                                 self.raw_line)
                return

        if "@createIfMissing" in line_str:
            self.create_if_missing = True
            line_str = line_str.replace(",@createIfMissing", "")

        super().__init__(line_str)

    def is_triggered(self, ts_hi, ts_lo=None):
        """Determine if CRON like line is to be triggered.

        Return True if line is triggered between timestamps ts_lo and ts_hi
        (exclusive on ts_lo inclusive on ts_hi), False if it is not
        triggered or None if the line is invalid or ts_hi is not valid.
        If ts_lo is not specified check for triggering on ts_hi only.

        ts_hi:  Timestamp of latest time to be checked for triggering.
        ts_lo:  Timestamp used for earliest time in range of times to be
                checked for triggering. May be omitted in which case only
                ts_hi is checked.
        """

        if self.is_valid and self.create_if_missing:

            #log.info(f"self.skin_dict: {self.skin_dict}")

            skin_dir = self.skin_dict["SKIN_ROOT"]

            skin_dir = os.path.join(skin_dir, self.skin_dict["skin"])

            html_dest_dir = self.skin_dict["HTML_ROOT"]

            if os.path.exists(skin_dir):

                if os.path.exists(html_dest_dir):

                    templates = dict_search(self.skin_dict.get("CheetahGenerator", None), "template")

                    for template in templates:

                        if not template.endswith(".tmpl"):
                            continue

                        template_filename = os.path.join(skin_dir, template)

                        if os.path.exists(template_filename):

                            output_filename = os.path.join(html_dest_dir, template[:-5])

                            if not os.path.exists(output_filename):
                                log.debug(f"{self.__class__.__name__} {output_filename} doesn't exist, triggering report generation")
                                return True

                            template_mtime = os.path.getmtime(template_filename)
                            output_mtime = os.path.getmtime(output_filename)

                            if template_mtime > output_mtime:
                                log.debug(f"{self.__class__.__name__} {output_filename} exists but mtime is older than {template_filename}, triggering report generation")
                                return True

                else:
                    log.debug(f"{self.__class__.__name__} {html_dest_dir} doesn't exist, triggering report generation")
                    return True

        #log.debug(f"{self.__class__.__name__} all files exist, allowing existing timing checks to happen")
        return super().is_triggered(ts_hi, ts_lo)

def patched_run(self, reports=None):
    """This is where the actual work gets done.

    Args:
        reports(list[str]|None): If None, run all enabled reports. If a list, run only the
            reports in the list, whether they are enabled or not.
    """

    if self.gen_ts:
        log.debug("Running reports for time %s",
                  weeutil.weeutil.timestamp_to_string(self.gen_ts))
    else:
        log.debug("Running reports for latest time in the database.")

    # If we have not been given a list of reports to run, then run all reports (although not
    # all of them may be enabled).
    run_reports = reports or self.config_dict['StdReport'].sections

    # Iterate over each requested report
    for report in run_reports:

        # Ignore the [[Defaults]] section
        if report == 'Defaults':
            continue

        # If reports is None, then we need to check whether this particular report has
        # been enabled.
        if reports is None:
            enabled = to_bool(self.config_dict['StdReport'][report].get('enable', True))
            if not enabled:
                log.debug("Report '%s' not enabled. Skipping.", report)
                continue

        log.debug("Running report '%s'", report)

        # Fetch and build the skin_dict:
        try:
            skin_dict = build_skin_dict(self.config_dict, report)
        except SyntaxError as e:
            log.error("Syntax error: %s", e)
            log.error("   ****       Report ignored")
            continue

        # Default action is to run the report. Only reason to not run it is
        # if we have a valid report report_timing, and it did not trigger.
        if self.record:
            # StdReport called us not "weectl report run" so look for a report_timing
            # entry if we have one.
            timing_line = skin_dict.get('report_timing')
            if timing_line:
                # Get a ReportTiming object.
                timing = PeriodicReportTiming(timing_line, skin_dict)
                if timing.is_valid:
                    # Get timestamp and interval, so we can check if the
                    # report timing is triggered.
                    _ts = self.record['dateTime']
                    _interval = self.record['interval'] * 60
                    # Is our report timing triggered? timing.is_triggered
                    # returns True if triggered, False if not triggered
                    # and None if an invalid report timing line.
                    if timing.is_triggered(_ts, _ts - _interval) is False:
                        # report timing was valid but not triggered so do
                        # not run the report.
                        log.debug("Report '%s' skipped due to report_timing setting", report)
                        continue
                else:
                    log.debug("Invalid report_timing setting for report '%s', "
                              "running report anyway", report)
                    log.debug("       ****  %s", timing.validation_error)

        skin_dir = Path(self.config_dict['WEEWX_ROOT'],
                        skin_dict['SKIN_ROOT'],
                        skin_dict['skin'])

        # We are using two "with" statements below:
        # 1. Set the current working directory to the skin's location. This allows #include
        # statements to work.
        # 2. Set the locale to 'lang'. If 'lang' was not specified, set it to the user's
        # default locale.
        with set_cwd(skin_dir) as cwd, set_locale(skin_dict.get('lang', '')) as loc:
            log.debug("Running generators for report '%s' in directory '%s' with locale '%s'",
                      report, cwd, loc)

            if 'Generators' in skin_dict and 'generator_list' in skin_dict['Generators']:
                for generator in weeutil.weeutil.option_as_list(
                        skin_dict['Generators']['generator_list']):

                    try:
                        # Instantiate an instance of the class.
                        obj = weeutil.weeutil.get_object(generator)(
                            self.config_dict,
                            skin_dict,
                            self.gen_ts,
                            self.first_run,
                            self.stn_info,
                            self.record)
                    except Exception as e:
                        log.error("Unable to instantiate generator '%s'", generator)
                        log.error("        ****  %s", e)
                        weeutil.logger.log_traceback(log.error, "        ****  ")
                        log.error("        ****  Generator ignored")
                        traceback.print_exc()
                        continue

                    try:
                        # Call its start() method
                        obj.start()

                    except Exception as e:
                        # Caught unrecoverable error. Log it, continue on to the
                        # next generator.
                        log.error("Caught unrecoverable exception in generator '%s'",
                                  generator)
                        log.error("        ****  %s", e)
                        weeutil.logger.log_traceback(log.error, "        ****  ")
                        log.error("        ****  Generator terminated")
                        traceback.print_exc()
                        continue

                    finally:
                        obj.finalize()

            else:
                log.debug("No generators specified for report '%s'", report)

ReportTimingSig = inspect.signature(ReportTiming)
if len(ReportTimingSig.parameters) == 1:
    log.info("Replacing weewx.reportengine.StdReportEngine.run with patched_run as ReportTiming takes 1 argument")
    weewx.reportengine.StdReportEngine.run = patched_run

class InigoSearchList(weewx.cheetahgenerator.SearchList):

    def __init__(self, generator):

        super(InigoSearchList, self).__init__(generator)

    def get_extension_list(self, timespan, db_lookup):

        global last_report_ts, last_report

        log.debug(f"{self.__class__.__name__} InigoSearchList v{VERSION} called!")

        if peak_detector is None:
            fatal_error(f"{self.__class__.__name__} InigoSearchList failed to detect InigoService running, exitting...")

        t1 = time.time()

        since_hour = 0

        skin_dict = self.generator.skin_dict
        if skin_dict is not None:

            since_hour = int(float(skin_dict.get("since_hour", 0)))

            if not 0 <= since_hour <= 23:
                since_hour = 0

        hour_ago_time = timespan.stop - 3600
        hour_ago = TimeBinder(db_lookup, hour_ago_time)

        #log.info(f"skin_dict: {pprint.pformat(skin_dict)}")

        def raw_value(var):

            if var is None:
                return -999.9

            #log.info(f"getUnitGroup(var.obs_type): {getUnitGroup(var.obs_type)}")

            if isinstance(var, AggTypeBinder):
                log.info(f"Before var.raw: {var.raw}")
                log.info(f"var.obs_type: {var.obs_type}")
                group_name = getUnitGroup(var.obs_type)
                log.info(f"group_name: {group_name}")

                #log.info(f"skin_dict: {pprint.pformat(skin_dict)}")

                group = None
                units_dict = skin_dict.get("Units", None)
                #log.info(f"units_dict: {pprint.pformat(units_dict)}")
                if units_dict is not None and units_dict != {}:
                    groups_dict = units_dict.get("Groups", None)
                    #log.info(f"groups_dict: {groups_dict}")
                    if groups_dict is not None and groups_dict != {}:
                        group = groups_dict.get(group_name, None)
                        log.info(f"group: {group}")

                if group is not None and not group:
                    var = var.convert(group)

                log.info(f"group: {group}")
                log.info(f"After var.raw: {var.raw}")

            elif isinstance(var, ValueHelper):
                log.info(f"var.raw: {var.raw}")
                log.info(f"var.value_t: {var.value_t}")
            else:

                log.info(f"var: {pprint.pformat(var)}")

            """

            log.info(f"var.raw: {var.raw}")
            """


            #log.info(f"db_lookup: {pprint.pformat(db_lookup)}")

            #try:
            #    return var.convert(group).raw
            #except:
            #    return -999

            return var.raw

        def sort_dict(dict_name):

            if dict_name is None or len(dict_name) == 0:
                return dict_name

            report_time = dict_name.get("report_time", None)
            if report_time is not None:
                del dict_name["report_time"]

            processingErrors = dict_name.get("processingErrors", None)
            if processingErrors is not None:
                del dict_name["processingErrors"]

            dict_version = dict_name.get("version", None)

            if dict_version is not None:
                del dict_name["version"]

            new_dict = dict(sorted(dict_name.items(), key=lambda x: x[0].lower()))

            output_dict = {}

            if dict_version is not None:
                output_dict["version"] = JSONversion

            if report_time is not None:
                output_dict["report_time"] = report_time

            if processingErrors is not None:
                output_dict["processingErrors"] = processingErrors

            return {**output_dict, **new_dict}

        if last_report_ts == timespan.stop and last_report is not None:
            return [{"inigo": {"ts": last_report_ts, "report": last_report}, "sort_dict": sort_dict, "raw_value": raw_value, "hour_ago": hour_ago, "hour_ago_time": hour_ago_time}]

        #log.info(f"{self.__class__.__name__} timespan.start: {timespan.start}")
        #log.info(f"{self.__class__.__name__} timespan.stop: {timespan.stop}")

        search_list_ts = []
        search_list_signal = []
        search_list_count = []

        if current_count > 0 and current_signal != 0 and current_ts <= timespan.stop:

            search_list_ts += [current_ts]
            search_list_signal += [current_signal]
            search_list_count += [current_count]

            log.debug(f"{self.__class__.__name__} InigoSearchList current_ts: {current_ts}")
            log.debug(f"{self.__class__.__name__} InigoSearchList current_signal: {current_signal}")
            log.debug(f"{self.__class__.__name__} InigoSearchList current_count: {current_count}")

        for ts, signal, count in reversed(trend_history):

            if signal == 0:
                continue

            if ts > timespan.stop:
                continue

            search_list_ts += [ts]
            search_list_signal += [signal]
            search_list_count += [count]

            #log.debug(f"{self.__class__.__name__} outTemp_trend_{trendCount}_ts: {ts}")
            #log.debug(f"{self.__class__.__name__} outTemp_trend_{trendCount}_signal: {signal}")
            #log.debug(f"{self.__class__.__name__} outTemp_trend_{trendCount}_count: {count}")

        group_rain = "mm"

        since_today = get_modified_rain_reset_time(self.__class__.__name__, db_lookup, timespan.stop, "today", group_rain, since_hour)
        since_yesterday = get_modified_rain_reset_time(self.__class__.__name__, db_lookup, timespan.stop, "yesterday", group_rain, since_hour)
        since_month_to_date = get_modified_rain_reset_time(self.__class__.__name__, db_lookup, timespan.stop, "month_to_date", group_rain, since_hour)
        since_last_month = get_modified_rain_reset_time(self.__class__.__name__, db_lookup, timespan.stop, "last_month", group_rain, since_hour)
        since_year_to_date = get_modified_rain_reset_time(self.__class__.__name__, db_lookup, timespan.stop, "year_to_date", group_rain, since_hour)
        since_last_year = get_modified_rain_reset_time(self.__class__.__name__, db_lookup, timespan.stop, "last_year", group_rain, since_hour)
        since_alltime = get_modified_rain_reset_time(self.__class__.__name__, db_lookup, timespan.stop, "alltime", group_rain, since_hour)

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

        #log.debug(f"{self.__class__.__name__} since_hour: {since_hour}")
        #log.debug(f"since_today: {since_today}")
        #log.debug(f"since_yesterday: {since_yesterday}")
        #log.debug(f"since_month_to_date: {since_month_to_date}")
        #log.debug(f"since_last_month: {since_last_month}")
        #log.debug(f"since_year_to_date: {since_year_to_date}")
        #log.debug(f"since_last_year: {since_last_year}")
        #log.debug(f"since_alltime: {since_alltime}")

        last_report_ts = timespan.stop
        last_report = search_list_extension

        t2 = time.time()

        log.debug(f"{self.__class__.__name__} executed in {(t2-t1):.3f} seconds")

        return [{"inigo": {"ts": last_report_ts, "report": last_report}, "sort_dict": sort_dict, "raw_value": raw_value, "hour_ago": hour_ago, "hour_ago_time": hour_ago_time}]

class InigoService(weewx.engine.StdService):

    def __init__(self, engine, config_dict):

        super(InigoService, self).__init__(engine, config_dict)

        self.done_work = False

        self.db_lookup = weewx.manager.DBBinder(config_dict).bind_default()

        if peak_detector is None:
            processConfigDict(self.__class__.__name__, config_dict)
            load_pickle_data(self.__class__.__name__, self.db_lookup)
        else:
            log.debug(f"{self.__class__.__name__} Data already loaded")

        self.bind(weewx.NEW_LOOP_PACKET, self.handle_loop_packet)
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.handle_archive_record)

        log.info(f"{self.__class__.__name__} v{VERSION} started")

    def handle_archive_record(self, event):

        now = datetime.now()
        if peak_detector.start_time.date() != now.date():
            log.debug(f"{self.__class__.__name__} {peak_detector.start_time.date()} != {now.date()} calling reset_peak_detector()")

            reset_peak_detector(self.__class__.__name__, self.db_lookup)

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
            #log.debug(f"{self.__class__.__name__} current_signal: {current_signal}")
            #log.debug(f"{self.__class__.__name__} current_count: {current_count}")

        else:
            # Signal changed — store the completed run
            log.debug(f"{self.__class__.__name__} signal switched from {current_signal} with count {current_count} to {signal}")

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
