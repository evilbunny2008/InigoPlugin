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
            },


            "data_services": "user.peak_detector.PeakDetectorService",
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


        try:
            config = configobj.ConfigObj(dest_fn, encoding='utf-8', interpolation=False)
        except configobj.ConfigObjError as e:
            engine.printer.out('cannot merge to %s: %s %s' % (dest_fn,e.__class__.__name__,e))
            return

        if engine.dry_run:
            engine.printer.out(config)
            engine.printer.out("-" * 72)
        else:
            config.write()
