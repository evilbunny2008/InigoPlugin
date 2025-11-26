## What is the Inigo Plugin?

The Inigo plugin for [weeWX](https://weeWX.com) was created to feed current conditions and past statistics from weeWX weather station software into the [weeWX Weather App](https://play.google.com/store/apps/details?id=com.odiousapps.weewxweather).

## Preparing weeWX

Before you can use the app, you need to add this plugin to weeWX. To find out more about setting up and running weeWX, you can find more details on the [weeWX website](https://weewx.com/downloads/).

### weeWX 3.9

Starting in 3.9 a default unit option was introduced in weeWX. Please visit the upgrading to 3.9 section of [weeWX documentation](https://weewx.com/docs/upgrading.htm#Skin_defaults) for more details.

### weeWX 4.0

I've been testing weeWX 4.0 using python 3 and haven't needed any changes to keep the Inigo skin working.

### weeWX 4.6

Need a new copy of Since.py, grab the extension again and reinstall it over the top

### weeWX 5.x

So far everything seems to work fine under weeWX 5.x

## How to Install the InigoPlugin

### For imperial on weeWX 4.x or lower
```
wget -O inigo-imperial.tar.gz https://github.com/evilbunny2008/InigoPlugin/releases/download/1.0.0/inigo-imperial.tar.gz
sudo wee_extension --install inigo-imperial.tar.gz
```
For imperial on weeWX 5.x and above
```
wget -O inigo-imperial.tar.gz https://github.com/evilbunny2008/InigoPlugin/releases/download/1.0.0/inigo-imperial.tar.gz
sudo weectl extension install inigo-imperial.tar.gz
```

### For metric on weeWX 4.x or lower
```
wget -O inigo-metric.tar.gz https://github.com/evilbunny2008/InigoPlugin/releases/download/1.0.0/inigo-metric.tar.gz
sudo wee_extension --install inigo-metric.tar.gz
```
For metric on weeWX 5.x or above
```
wget -O inigo-metric.tar.gz https://github.com/evilbunny2008/InigoPlugin/releases/download/1.0.0/inigo-metric.tar.gz
sudo weectl extension install inigo-metric.tar.gz
```

### Installing an Almanac (optional)

If you would like to see moon rise/set in the app, you just need to install pyephem.
```
sudo apt -y install python3-ephem
```

### Using offset rain times (optional)

Historically rainfall is measured in Australia at 9am, so it's useful for comparison reasons to be able to display rain records matching time of day with the [Bureau of Meteorology](https://www.bom.gov.au). To enable this simply edit /etc/weewx/since.tmpl and paste the following into it:

```
#if $varExists('since')
$since($hour=9).rain.sum.formatted|$since($hour=9,$today=False).rain.sum.formatted|9am|#slurp
#else
|||#slurp
#end if
```

### Restarting weeWX

You need to restart weeWX to make the above changes work.

```
sudo systemctl restart weewx
```
