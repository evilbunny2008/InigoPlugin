# installer for the inigo template.
#
# 23rd of Mar 2026

import configobj
import weeutil.weeutil

from weecfg.extension import ExtensionInstaller
from weeutil.config import conditional_merge

def loader():

    return InigoInstaller()

class InigoInstaller(ExtensionInstaller):

    def __init__(self):

        self.metric_cfg = {
            "Groups": {
                "group_altitude": "meter",
                "group_degree_day": "degree_C_day",
                "group_distance": "km",
                "group_pressure": "mbar",
                "group_rain": "mm",
                "group_rainrate": "mm_per_hour",
                "group_speed": "km_per_hour",
                "group_speed2": "km_per_hour2",
                "group_temperature": "degree_C",
            }
        }

        self.metric_rain_in_inches_cfg = {
            "Groups": {
                "group_altitude": "meter",
                "group_degree_day": "degree_C_day",
                "group_distance": "km",
                "group_pressure": "mbar",
                "group_rain": "mm",
                "group_rainrate": "mm_per_hour",
                "group_speed": "km_per_hour",
                "group_speed2": "km_per_hour2",
                "group_temperature": "degree_C",
            }
        }

        self.imperial_cfg = {
            "Groups": {
                "group_altitude": "foot",
                "group_degree_day": "degree_F_day",
                "group_distance": "mile",
                "group_pressure": "mmHg",
                "group_rain": "inch",
                "group_rainrate": "inch_per_hour",
                "group_speed": "mile_per_hour",
                "group_speed2": "mile_per_hour2",
                "group_temperature": "degree_F",
            }
        }

        config_dict = {
            "StdReport": {
                "Inigo": {
                    "skin": "Inigo",
                    "HTML_ROOT": "",
                    "enable": "True",
                    "Units": self.metric_cfg,
                }
            }
        }

        self.metric = True
        self.rainInInches = False

        super(InigoInstaller, self).__init__(
            version="1.0.9",
            name="Inigo",
            description="A skin to feed data to weeWx app",
            author="John Smith",
            author_email="deltafoxtrot256@gmail.com",
            config=config_dict,
            files=[
                ("skins/Inigo",
                ["skins/Inigo/inigo-data.txt.tmpl",
                 "skins/Inigo/skin.conf"]),
                ("bin/user",
                ["bin/user/inigo-since.py",
                 "bin/user/peak_detector.py"])
            ]
        )

    def process_args(self, args):

        for arg in args:

            if arg == "--imperial":

                self.metric = False

            if arg == "--rain-inches":

                self.rainInInches = True

    def configure(self, engine):

        if engine.config_dict is None:
            return False

        stdreport_dict = engine.config_dict.get("StdReport", None)
        if stdreport_dict is None:
            return False

        inigo_dict = stdreport_dict.get("Inigo")
        if inigo_dict is None:
            return False

        units_dict = inigo_dict.get("Units")
        if units_dict is None:
            return False

        if self.rainInInches:

            engine.printer.out(f"Removing metric rainfall settings")

            units_dict["Groups"].update(self.metric_rain_in_inches_cfg)

            engine.printer.out(f"engine.config_dict: {engine.config_dict}")

        elif not self.metric:

            engine.printer.out(f"Removing metric settings")

            units_dict["Groups"].update(self.imperial_cfg)

            engine.printer.out(f"engine.config_dict: {engine.config_dict}")

        else:

            engine.printer.out(f"Installing metric settings")

            engine.printer.out(f"engine.config_dict: {engine.config_dict}")


        engine_dict = engine.config_dict.get("Engine", None)
        if engine_dict is not None:

            services_dict = engine_dict.get("Services", None)
            if services_dict is not None:

                prep_services_list = services_dict.get("prep_services", None)
                if prep_services_list is not None and "user.peak_detector.PeakDetectorService" not in prep_services_list:

                    prep_services_list.append("user.peak_detector.PeakDetectorService")

        if engine.dry_run:
            engine.printer.out(engine.config_dict)
            engine.printer.out("-" * 72)
            return False

        return True
