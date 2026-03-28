# installer for the inigo template.
#
# 24th of Mar 2026

import configobj
import os
import stat
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
                "group_pressure": "hPa",
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
                "group_pressure": "hPa",
                "group_rain": "inch",
                "group_rainrate": "inch_per_hour",
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
                    "enable": "True",
                    "Units": self.metric_cfg,
                }
            }
        }

        self.metric = True
        self.rainInInches = False
        self.since_hour = -1

        super(InigoInstaller, self).__init__(
            version="2.0.0",
            name="Inigo",
            description="A skin to feed data to weeWx app",
            author="John Smith",
            author_email="deltafoxtrot256@gmail.com",
            config=config_dict,
            files=[
                ("skins/Inigo",
                ["skins/Inigo/inigo-data.json.tmpl",
                 "skins/Inigo/skin.conf"]),
                ("bin/user",
                ["bin/user/inigo.py"])
            ]
        )

    def process_args(self, args):

        for arg in args:

            if arg == "--imperial":

                self.metric = False

            if arg == "--rain-inches":

                self.rainInInches = True

            if arg.startswith("--since-hour-"):

                split_strs = arg.split("--since-hour-", 2)
                self.since_hour = int(split_strs[1])

    def configure(self, engine):

        if engine.config_dict is None:
            engine.printer.out(f"engine.config_dict is None, can't continue!")
            return False

        skin_dir = engine.root_dict.get('SKIN_DIR')
        if skin_dir is None:
            engine.printer.out(f"skin_dir is None, can't continue!")
            return False

        uid = os.getuid()
        statinfo = os.stat(skin_dir)
        suid = statinfo.st_uid
        sgid = statinfo.st_gid

        data_dir = engine.config_dict.get('DatabaseTypes', dict()).get('SQLite',dict()).get('SQLITE_ROOT', None)
        if data_dir is None:
            engine.printer.out(f"SQLITE_ROOT is None, can't continue!")
            return False

        cache_dir = os.path.join(data_dir, "inigo")

        if os.path.exists(cache_dir) and not os.path.isdir(cache_dir):
            os.remove(cache_dir)

        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)

        desired_mode = stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH | stat.S_ISGID
        current_mode = os.stat(cache_dir).st_mode

        if current_mode != desired_mode | stat.S_IFDIR:
            os.chmod(cache_dir, desired_mode)

        statinfo = os.stat(cache_dir)
        cuid = statinfo.st_uid
        cgid = statinfo.st_gid

        if cuid != suid or cgid != sgid:
            os.chown(cache_dir, suid, sgid)
            for fn in os.listdir(cache_dir):
                os.chown(os.path.join(cache_dir, fn), suid, sgid)

        stdreport_dict = engine.config_dict.get("StdReport", None)
        if stdreport_dict is None:
            return False

        inigo_dict = stdreport_dict.get("Inigo")
        if inigo_dict is None:
            return False

        if os.path.exists(cache_dir) and "cache_dir" not in inigo_dict:
            inigo_dict["cache_dir"] = cache_dir

        if "since_hour" not in inigo_dict:
            if 0 <= self.since_hour <= 23:
                inigo_dict["since_hour"] = self.since_hour

        else:
            tmpsince = int(inigo_dict.get("since_hour", 0))

            if 0 <= self.since_hour <= 23 and self.since_hour != tmpsince:
                inigo_dict["since_hour"] = self.since_hour
            elif not 0 <= tmpsince <= 23:
                del inigo_dict["since_hour"]

        units_dict = inigo_dict.get("Units")
        if units_dict is None:
            return False

        groups_dict = inigo_dict.get("Units")
        if groups_dict is None:
            return False

        if self.rainInInches:

            engine.printer.out(f"Removing metric rainfall settings")

            groups_dict.update(self.metric_rain_in_inches_cfg)

        elif not self.metric:

            engine.printer.out(f"Removing metric settings")

            groups_dict.update(self.imperial_cfg)

        else:

            engine.printer.out(f"Installing metric settings")

            groups_dict.update(self.metric_cfg)


        engine_dict = engine.config_dict.get("Engine", None)
        if engine_dict is not None:

            services_dict = engine_dict.get("Services", None)
            if services_dict is not None:

                prep_service = "user.peak_detector.PeakDetectorService"
                prep_services = services_dict.get("prep_services", None)
                if prep_services is not None:
                    if isinstance(prep_services, str) and prep_services == prep_service:
                        del prep_services
                    elif prep_service in prep_services:
                        prep_services.remove(prep_service)

                data_service = "user.inigo.InigoService"
                data_services = services_dict.get("data_services", None)
                if data_services is None:
                    services_dict["data_services"] = data_service
                elif data_service not in data_services:
                    if isinstance(data_services, str):
                        data_services = [data_services, data_service]
                    else:
                        data_services.append(data_service)

        if engine.dry_run:
            engine.printer.out(engine.config_dict)
            engine.printer.out("-" * 72)
            return False

        return True
