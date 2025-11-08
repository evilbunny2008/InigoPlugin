# installer for the inigo template.
#
# 4th of Jan 2023

from setup import ExtensionInstaller

def loader():
    return DataInstaller()

class DataInstaller(ExtensionInstaller):
    def __init__(self):
        super(DataInstaller, self).__init__(
            version="1.0.3",
            name='Inigo',
            description='A skin to feed data to weeWx app',
            author="John Smith",
            author_email="deltafoxtrot256@gmail.com",
            config={
                'StdReport': {
                    'Inigo': {
                        'skin':'Inigo',
                        'HTML_ROOT':'',
                        'Units': {
                            'Groups': {
                                'group_altitude':'meter',
                                'group_speed2':'km_per_hour2',
                                'group_pressure':'mbar',
                                'group_rain':'mm',
                                'group_rainrate':'mm_per_hour',
                                'group_temperature':'degree_C',
                                'group_degree_day':'degree_C_day',
                                'group_speed':'km_per_hour',
            }}}}},

            files=[('skins/Inigo',
                    ['skins/Inigo/inigo-data.txt.tmpl',
                     'skins/Inigo/skin.conf']),
                   ('bin/user',
                    ['bin/user/alltime.py',
                     'bin/user/inigo-since.py'])
                   ]
            )

