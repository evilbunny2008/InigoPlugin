# What is the Inigo Plugin?

The Inigo plugin for [weeWX](https://weeWX.com) was created to feed current conditions and past statistics from [weeWX](https://weeWX.com) weather station software into the [weeWX Weather App](https://play.google.com/store/apps/details?id=com.odiousapps.weewxweather).

# How to Install the InigoPlugin

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

### Using offset rain times (optional)

Historically rainfall is measured in Australia at 9am, so it's useful for comparison reasons to be able to display rain records matching time of day with the [Bureau of Meteorology](https://www.bom.gov.au). To enable this simply edit /etc/weewx/since.tmpl and paste the following into it:

```
#if $varExists('since')
$since($hour=9).rain.sum.formatted|$since($hour=9,$today=False).rain.sum.formatted|9am|#slurp
#else
|||#slurp
#end if
```
