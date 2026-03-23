## What is the Inigo Plugin?

The Inigo plugin for [weeWX](https://weeWX.com) was created to feed current conditions and past statistics from weeWX weather station software into the [weeWX Weather App](https://play.google.com/store/apps/details?id=com.odiousapps.weewxweather).

## Preparing weeWX

Before you can use the app, you need to add this plugin to weeWX. To find out more about setting up and running weeWX, you can find more details on the [weeWX website](https://weewx.com/downloads/).

## How to Install the InigoPlugin on weeWX 5.3 or above

weeWX 5.3 allows command line arguments to be passed to extention installation scripts

### Install with metric defaults

```
sudo weectl extension install --yes https://github.com/evilbunny2008/InigoPlugin/archive/master.zip
```

### Install with metric defaults but rain in imperial

Use the --rain-inches argument

```
sudo weectl extension install --yes https://github.com/evilbunny2008/InigoPlugin/archive/master.zip --rain-inches
```

### Install with imperial defaults

Use the --imperial argument

```
sudo weectl extension install --yes https://github.com/evilbunny2008/InigoPlugin/archive/master.zip --imperial
```

## Installing an Almanac (optional)

If you would like to see next moon rise/set in the app, you just need to install the skyfield extension

```
sudo apt update
sudo apt -y install python3-numpy python3-pandas python3-skyfield
sudo weectl extension install --yes https://github.com/roe-dl/weewx-skyfield-almanac/archive/master.zip
```

## Using offset rain times (optional)

Historically rainfall is measured in Australia at 9am, so it's useful for comparison reasons to be able to display rain records matching time of day with the [Bureau of Meteorology](https://www.bom.gov.au). To enable this simply edit /etc/weewx/since.tmpl and paste the following into it:

```
#if $varExists('since')
$since($hour=9).rain.sum.formatted|$since($hour=9,$today=False).rain.sum.formatted|9am|#slurp
#else
|||#slurp
#end if
```

## Restarting weeWX

You need to restart weeWX to make the above changes work.

```
sudo systemctl restart weewx
```
