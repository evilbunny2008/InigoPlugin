## What is the Inigo Plugin?

The Inigo plugin for [weeWX](https://weeWX.com) was created to feed current conditions and past statistics from weeWX weather station software into the [weeWX Weather App](https://play.google.com/store/apps/details?id=com.odiousapps.weewxweather).

## Preparing weeWX

Before you can use the app, you need to add this plugin to weeWX. To find out more about setting up and running weeWX, you can find more details on the [weeWX website](https://weewx.com/downloads/).


## Peak Temperature Detection

It's surprisingly difficult to calculate when the daily peak temperature has been reached in real time, as passing clouds and other weather phenomenon can temporarily cause the temperatures to decrease before increasing again and given the right set of circumstances this can prematurely trigger notifications in the app.

A possible way to detect peak daily temperature in real time is by using a [z-score algorithm](https://stackoverflow.com/questions/22583391/peak-signal-detection-in-realtime-timeseries-data/56451135#56451135) and to supply temperature data from loop packets to the algorithm.

So the peak detection algorithm can synthesise loop packet temperature data from archive records on startup, the Python numpy module is required, to install numpy do one of the following:

```
sudo apt update
sudo apt -y install python3-numpy
```

or for pip installs

```
pip install numpy
```

## How to Install the InigoPlugin on weeWX 5.3 or above

### Install with rain reset at midnight or when updating

```
sudo weectl extension install --yes https://github.com/evilbunny2008/InigoPlugin/archive/master.zip
```

### Install with the rain reset at 9am

Historically rainfall in Australia was given to 9am, so it's useful for comparison reasons to be able to display rain records matching time of day with the old [Bureau of Meteorology](https://reg.bom.gov.au) website.

weeWX 5.3 allows command line arguments to be passed to extension installation scripts, so to use a different time of day use the --since-hour command line argument on first install with an hour between 0 and 23, otherwise midnight will be used.

```
sudo weectl extension install --yes https://github.com/evilbunny2008/InigoPlugin/archive/master.zip --since-hour 9
```

### Non system package installs

If weeWX was installed using pip you will need to use full paths for both weectl and the weewx.conf file.

```
sudo /opt/weewx/weewx-venv/bin/weectl extension install --yes --config /opt/weewx/weewx-data/weewx.conf https://github.com/evilbunny2008/InigoPlugin/archive/master.zip 
```

## Installing the Skyfield almanac weeWX extension (optional)

If you would like to see next moon rise/set in the app, you need to install the Skyfield extension

```
sudo apt update
sudo apt -y install python3-numpy python3-pandas python3-skyfield
sudo weectl extension install --yes https://github.com/roe-dl/weewx-skyfield-almanac/archive/master.zip
```

## Restarting weeWX

You need to restart weeWX to make the above changes work.

```
sudo systemctl restart weewx
```
