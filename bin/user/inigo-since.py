# since.py
#
# A Search List Extension to provide aggregates since a given hour.
#
# python imports
import logging
import time

# weeWX imports
import weeutil.weeutil
import weewx.cheetahgenerator
import weewx.units

from datetime import datetime, timedelta

log = logging.getLogger(__name__)

since_hour = 0

def processConfigDict(class_name, config_dict):

    global since_hour

    cfg = config_dict.get("StdReport", None)
    if cfg is not None:
        inigo = cfg.get("Inigo", None)
        if inigo is not None:
             since_hour = int(inigo.get("since_hour", 0))

    if not 0 <= since_hour <= 23:
        since_hour = 0

class Since(weewx.cheetahgenerator.SearchList):
    """SLE to provide aggregates since a given time of day."""

    def __init__(self, generator):
        super(Since, self).__init__(generator)

        processConfigDict(self.__class__.__name__, generator.config_dict)

    def get_extension_list(self, timespan, db_lookup):
        """Returns a NewBinder object that supports aggregates since a given
           time.

            The NewBinder object implements the tag $since that allows
            inclusion of aggregates since the last occurrence of a give time of
            day, eg total rainfall since 9am, average temperature since midday.
            The signature of the $since tag is:

            $since([$hour=x]).obstype.aggregation[.optional_unit_conversion][.optional_formatting]

            where

            x is an integer from 0 to 23 inclusive representing the hour of the
            day

            obstype is a field in the archive table in use eg outTemp, inHumidiy
            or rain

            aggregation is an aggregate function supported by weewx (refer
            Customization Guide appendices)

            optional_unit_conversion and optional_formatting are optional weeWX
            unit conversion and formatting codes respectively

        Parameters:
            timespan: An instance of weeutil.weeutil.TimeSpan. This will hold
                      the start and stop times of the domain of valid times.

            db_lookup: This is a function that, given a data binding as its
                       only parameter, will return a database manager object.

        Returns:
            A NewBinder object with a timespan from "hour" o'clock to the
            report time
          """

        t1 = time.time()

        class NewBinder(weewx.tags.TimeBinder):

            def __init__(self, db_lookup, report_time,
                         formatter=weewx.units.Formatter(),
                         converter=weewx.units.Converter(), **option_dict):

                super(NewBinder, self).__init__(db_lookup, report_time,
                                                formatter=formatter,
                                                converter=converter,
                                                **option_dict)

            def since(self, data_binding=None, hour=since_hour, today=True):
                """Return a TimeSpanBinder for the period since 'hour'."""

                if not 0 <= hour <= 23:
                    hour = 0

                stop_time = datetime.fromtimestamp(timespan.stop)
                start_time = stop_time.replace(hour=hour, minute=0, second=0, microsecond=0)

                if stop_time < start_time:
                    start_time -= timedelta(days=1)

                if not today:
                    start_time -= timedelta(days=1)
                    stop_time -= timedelta(days=1)

                log.debug(f"{self.__class__.__name__} Since Start {start_time.strftime('%H:%M')}, Since stop {stop_time.strftime('%H:%M')}")

                tspan = weeutil.weeutil.TimeSpan(int(start_time.timestamp()), int(stop_time.timestamp()))

                return weewx.tags.TimespanBinder(tspan,
                                                 self.db_lookup,
                                                 context="day",
                                                 data_binding=data_binding,
                                                 formatter=self.formatter,
                                                 converter=self.converter)

        try:
            trend_dict = self.generator.skin_dict['Units']['Trend']
        except KeyError:
            trend_dict = {'time_delta': 10800,
                          'time_grace': 300}

        tspan_binder = NewBinder(db_lookup,
                                timespan.stop,
                                self.generator.formatter,
                                self.generator.converter,
                                trend=trend_dict)

        t2 = time.time()
        log.debug(f"{self.__class__.__name__} Since SLE executed in {(t2-t1)}:.3f seconds")

        return [tspan_binder]

    def since_hour(self):

        global since_hour

        if not 0 <= since_hour <= 23:
            since_hour = 0

        return [since_hour]
