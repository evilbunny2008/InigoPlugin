# installer for the inigo template.
#
# 23rd of Mar 2026

import weeutil.weeutil

from weecfg.extension import ExtensionInstaller
from weeutil.config import conditional_merge

def loader():

    return DataInstaller()

class DataInstaller(ExtensionInstaller):

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

        install_dict = {
            "version": "1.0.9",
            "name": "Inigo",
            "description": "A skin to feed data to weeWx app",
            "author": "John Smith",
            "author_email": "deltafoxtrot256@gmail.com",
            "config": {
                "StdReport": {
                    "Inigo": {
                        "skin":"Inigo",
                        "HTML_ROOT":"",
                        "Units": self.metric_cfg,
                    }
                }
            },

            "files": [
                ("skins/Inigo",
                ["skins/Inigo/inigo-data.txt.tmpl",
                 "skins/Inigo/skin.conf"]),
                ("bin/user",
                ["bin/user/inigo-since.py",
                 "bin/user/peak_detector.py"])
            ],

            "data_services": "user.peak_detector.PeakDetectorService",
        }

        self.metric = True
        self.rainInInches = False

        super().__init__(install_dict)

    def process_args(self, args):

        for arg in args:

            if arg == "--imperial":

                self.metric = False

                return

            if arg == "--rain-inches":

                self.rainInInches = True

                return

    def configure(self, engine):

        install_dict = engine.install_dict

        engine.printer.out(f"install_dict: {install_dict}")

        if self.rainInInches:

            engine.printer.out(f"Removing metric rainfall settings")

            install_dict["StdReport"]["Inigo"]["Units"] = self.metric_rain_in_inches_cfg

        elif not self.metric:

            engine.printer.out(f"Removing metric settings")

            del install_dict["StdReport"]["Inigo"]["Units"]

        else:

            engine.printer.out(f"Installing metric settings")
