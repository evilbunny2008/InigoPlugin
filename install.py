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

        self.metric_rain_in_inches_cfg = {
            "Groups": {
                "group_altitude": "meter",
                "group_speed2": "km_per_hour2",
                "group_pressure": "mbar",
                "group_temperature": "degree_C",
                "group_degree_day": "degree_C_day",
                "group_speed": "km_per_hour",
            }
        }

        self.metric_cfg = {
            "Groups": {
                "group_altitude": "meter",
                "group_speed2": "km_per_hour2",
                "group_pressure": "mbar",
                "group_rain": "mm",
                "group_rainrate": "mm_per_hour",
                "group_temperature": "degree_C",
                "group_degree_day": "degree_C_day",
                "group_speed": "km_per_hour",
            }
        }

        config_dict = {
            "StdReport": {
                "Inigo": {
                    "skin":"Inigo",
                    "HTML_ROOT":"",
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

        config_dict = engine.config_dict

        engine.printer.out(f"config_dict: {config_dict}")

        if self.rainInInches:

            engine.printer.out(f"Removing metric rainfall settings")

            config_dict["StdReport"]["Inigo"]["Units"] = self.metric_rain_in_inches_cfg

            engine.printer.out(f"config_dict: {config_dict}")

        elif not self.metric:

            engine.printer.out(f"Removing metric settings")

            del config_dict["StdReport"]["Inigo"]["Units"]

            engine.printer.out(f"config_dict: {config_dict}")

        else:

            engine.printer.out(f"Installing metric settings")

            engine.printer.out(f"config_dict: {config_dict}")


        engine_dict = config_dict.get("Engine", None)
        if engine_dict is not None:

            services_dict = engine_dict.get("Services", None)
            if services_dict is not None:

                data_services_list = services_dict.get("data_services", None)
                if data_services_list is not None and "user.peak_detector.PeakDetectorService" not in data_services_list:

                    data_services_list.append("user.peak_detector.PeakDetectorService")
