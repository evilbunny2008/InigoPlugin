# installer for the inigo template
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
            description='A skin to feed data to the weeWX Weather app',
            author="John Smith",
            author_email="deltafoxtrot256@gmail.com",
            config={
                'StdReport': {
                    'Inigo': {
                        'skin':'Inigo',
                        'HTML_ROOT':''}}},

            files=[('skins/Inigo',
                    ['skins/Inigo/inigo-data.txt.tmpl',
                     'skins/Inigo/skin.conf']),
                   ('bin/user',
                    ['bin/user/alltime.py',
                     'bin/user/inigo-since.py'])
                   ]
            )

