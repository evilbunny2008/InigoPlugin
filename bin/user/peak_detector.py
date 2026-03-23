
# Simple weeWX loop and archive service to detect when outTemp has peaked.

import logging
import os
import pickle
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

        tmp_dir = os.path.abspath("/tmp")
        self.cache_dir = os.path.join(tmp_dir, "pickle_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.pickle_filename = os.path.join(self.cache_dir, "peak_detector.pkl")

        self.load_pickle_data()

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
        if outTemp10min_avg is not None:

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

        self.save_pickle_data(True)

        after4pm = datetime.now().hour >= 16

        trending_down = False
        total = self.loop_up_count + self.loop_down_count
        if total >= 3:
            down_ratio = self.loop_down_count / total
            trending_down = down_ratio >= 0.65

        now = datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        stats = TimespanBinder(TimeSpan(int(midnight.timestamp()), int(now.timestamp())), self.db_lookup)

        effective_peak = stats.outTemp.max.raw
        if effective_peak is None:
            effective_peak = -999.9

        outTemp_peaked = (trending_down or after4pm) and temp < effective_peak

        if not outTemp_peaked:
            effective_peak = -999.9

        record["outTemp_peak"] = round(effective_peak, 1)
        record["outTemp_trend1"] = self.get_temp_trend(30)
        record["outTemp_trend5"] = self.get_temp_trend(150)
        record["outTemp_trend10"] = self.get_temp_trend(300)
        record["outTemp_trend30"] = self.get_temp_trend(900)
        record["outTemp_trend60"] = self.get_temp_trend(1800)

        print(f"record['outTemp_trend1']: {record['outTemp_trend1']}")
        print(f"record['outTemp_trend5']: {record['outTemp_trend5']}")
        print(f"record['outTemp_trend10']: {record['outTemp_trend10']}")
        print(f"record['outTemp_trend30']: {record['outTemp_trend30']}")
        print(f"record['outTemp_trend60']: {record['outTemp_trend60']}")

        if self.usUnit == weewx.US:
            log.info(f"{self.__class__.__name__} outTemp_peak {effective_peak:.1f}°F")
        else:
            log.info(f"{self.__class__.__name__} outTemp_peak {FtoC(effective_peak):.1f}°C")

        self.loop_up_count = 0
        self.loop_down_count = 0

    def handle_loop_packet(self, event):

        packet = event.packet

        temp = self.getTemp(packet)
        if temp is None:
            return

        self.temp_history.append((time.time(), temp))

        self.save_pickle_data()

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
            return float(temp)
        except (ValueError, TypeError):
            return None

    # Trend calculation — call this wherever you need it
    def get_temp_trend(self, samples):
        if len(self.temp_history) < 2:
            return None  # not enough data

        temps = [t for _, t in self.temp_history]

        if samples > len(temps):
            samples = len(temps)

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
                    self.temp_history = pickle.load(f)

                    temps = [t for _, t in self.temp_history]

                    log.info(f"{self.__class__.__name__} loaded {len(temps)} records from pickle file")
                    return

            except Exception as e:
                pass

        log.info(f"{self.__class__.__name__} self.temp_history = deque(maxlen=1800)")
        self.temp_history = deque(maxlen=1800)

    def save_pickle_data(self, report=False):

        try:
            with open(self.pickle_filename, "wb") as f:
                pickle.dump(self.temp_history, f)

                if report:

                    temps = [t for _, t in self.temp_history]

                    log.info(f"{self.__class__.__name__} saved {len(temps)} records to pickle file")

        except Exception as e:
            raise e

