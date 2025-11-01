# vcontrold configuration files for Viessmann Vitodens 200-W (B2HB-19)
## vcontrold.xml
Program-specific settings (device connection, network port, units, protocols) for [vcontrold](https://github.com/openv/openv/wiki/vcontrold)

## vito.xml
Command and device definitions (read/write commands, memory addresses, data types) for [vcontrold](https://github.com/openv/openv/wiki/vcontrold)

## vcontrold.yaml
configuration file for [Vcontrol Home Assistant add-on](https://github.com/Alexandre-io/homeassistant-vcontrol)

### Notes:
1. My configuration does not include a room temperature sensor. These sensors are therefore commented out.
2. My configuration does not include heating circuit 1. These sensors are therefore commented out.
3. My configuration has two heating circuits: HK2 and HK3, which can be heated by the Vitodens 200-W (in addition to a heat pump).
4. I also have a DHW cylinder (hot water boiler) that can be heated by the Vitodens 200-W (in addition to solar and electricity).
