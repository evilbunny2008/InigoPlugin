# installer for the inigo template.
#
# 24th of Mar 2026

import configobj
import os
import stat
import weeutil.weeutil
import weewx

from weecfg.extension import ExtensionInstaller
from weeutil.config import conditional_merge

VERSION="2.0.5"

def loader():

    return InigoInstaller()

def fatal_error(error_str):

    print()
    print(error_str)
    print()
    print()
    raise weewx.UnsupportedFeature("Fatal Error")

def is_integer(s):

    try:
        int(s)
        return True
    except (ValueError, TypeError) as e:
        return False

class InigoInstaller(ExtensionInstaller):

    def __init__(self):

        config_dict = {
        }

        self.metric = True
        self.rainInInches = False
        self.since_hour = -1

        super(InigoInstaller, self).__init__(
            version=VERSION,
            name="Inigo",
            description="A skin to feed data to weeWx app",
            author="John Smith",
            author_email="deltafoxtrot256@gmail.com",
            config={
                "StdReport": {
                    "Inigo": {
                        "skin": "Inigo",
                        "enable": "True",
                    },
                    "Inigo-Dicts": {
                        "skin": "Inigo-Dicts",
                        "enable": "True",
                        "report_timing": "@yearly",
                    }
                }
            },
            files=[
                ("bin/user",
                ["bin/user/inigo.py"]),
                ("skins/Inigo",
                ["skins/Inigo/inigo-data.json.tmpl",
                 "skins/Inigo/skin.conf"]),
                ("skins/Inigo-Dicts",
                ["skins/Inigo-Dicts/inigo-dicts.json.tmpl",
                 "skins/Inigo-Dicts/skin.conf"]),
            ]
        )

    def process_args(self, args):

        args_iter = iter(args)

        for arg in args_iter:

            if arg == "--since-hour":

                arg = next(args_iter, "-1")

                if arg != "-1":
                    if is_integer(arg):

                        self.since_hour = int(arg)

                        if not 0 <= self.since_hour <= 23:
                            fatal_error(f"'{self.since_hour}' isn't valid hour, you need to specify a number between 0 and 23 or leave unset to keep the current setting")

                    else:
                        fatal_error(f"{arg} isn't valid hour, you need to specify a number between 0 and 23 or leave unset to keep the current setting")

    def configure(self, engine):

        if engine.config_dict is None:
            fatal_error("engine.config_dict is None, can't continue...")

        try:
            import numpy as np
            np.array([1.0, 2.0, 3.0])
            del np
        except (ImportError, Exception):
            fatal_error(f"The numpy python module wasn't detected, this is required to detect peak daily temperature in real time.\n\nPlease view this wiki page for installation details: https://github.com/evilbunny2008/InigoPlugin/blob/main/README.md")

        data_dir = engine.config_dict.get('DatabaseTypes', dict()).get('SQLite',dict()).get('SQLITE_ROOT', None)
        if data_dir is None:
            fatal_error("SQLITE_ROOT is None, can't continue...")

        uid = os.getuid()
        statinfo = os.stat(data_dir)
        data_uid = statinfo.st_uid
        data_gid = statinfo.st_gid

        cache_dir = os.path.join(data_dir, "inigo")

        if os.path.exists(cache_dir) and not os.path.isdir(cache_dir):
            os.remove(cache_dir)

        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)

        if not os.path.exists(cache_dir):
            fatal_error("Failed to create the directory for the InigoService cache files, can't continue...")

        desired_mode = stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH | stat.S_ISGID
        current_mode = os.stat(cache_dir).st_mode

        if current_mode != desired_mode | stat.S_IFDIR:
            os.chmod(cache_dir, desired_mode)

        statinfo = os.stat(cache_dir)
        cache_uid = statinfo.st_uid
        cache_gid = statinfo.st_gid

        if cache_uid != data_uid or cache_gid != data_gid:
            os.chown(cache_dir, data_uid, data_gid)
            for fn in os.listdir(cache_dir):
                os.chown(os.path.join(cache_dir, fn), data_uid, data_gid)

        current_mode = os.stat(cache_dir).st_mode
        statinfo = os.stat(cache_dir)
        cache_uid = statinfo.st_uid
        cache_gid = statinfo.st_gid

        if current_mode != desired_mode | stat.S_IFDIR or cache_uid != data_uid or cache_gid != data_gid:
            fatal_error("Failed to set the correct permissions for the InigoService cache directory, can't continue...")

        stdreport_dict = engine.config_dict.get("StdReport", None)
        if stdreport_dict is None:
            fatal_error("StdReport is None, can't continue...")

        inigo_dict = stdreport_dict.get("Inigo")
        if inigo_dict is None:
            fatal_error("Inigo section of weewx.conf is None, can't continue...")

        if "cache_dir" not in inigo_dict or inigo_dict.get("cache_dir") != cache_dir:
            inigo_dict["cache_dir"] = cache_dir

        if "since" in inigo_dict:
            del inigo_dict["since"]

        if "since_hour" not in inigo_dict:
            if 0 <= self.since_hour <= 23:
                inigo_dict["since_hour"] = self.since_hour
            else:
                inigo_dict["since_hour"] = 0

        else:
            tmpsince = int(inigo_dict.get("since_hour", -1))

            if 0 <= self.since_hour <= 23:
                if self.since_hour != tmpsince:
                    inigo_dict["since_hour"] = self.since_hour

            elif not 0 <= tmpsince <= 23:
                inigo_dict["since_hour"] = 0

        if "Units" in inigo_dict:
            del inigo_dict["Units"]

        engine_dict = engine.config_dict.get("Engine", None)
        if engine_dict is None:
            engine.config_dict["Engine"] = {}
            engine_dict = engine.config_dict.get("Engine", None)

        services_dict = engine_dict.get("Services", None)
        if services_dict is None:
            engine_dict["Services"] = {}
            services_dict = engine_dict.get("Services", None)

        prep_service = "user.peak_detector.PeakDetectorService"
        prep_services = services_dict.get("prep_services", None)
        if prep_services is not None:
            if isinstance(prep_services, str) and prep_services == prep_service:
                del services_dict["prep_services"]
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
