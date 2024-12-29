# Deye/Sunsynk Inverters

This repo enables access to Deye Hybrid Inverters & Deye branded inverters like Sunsynk through a Python 3 library. It also provides an Add-On that can be installed in the Home Assistant OS.

This code was developed on a [Sunsynk](https://www.sunsynk.org/) 5.5 kWh inverter.

> DISCLAIMER: Use at your own risk! Especially when writing any settings.

## Documentation

Refer to [https://sunsynk.wectrl.net/](https://sunsynk.wectrl.net/)

## Home Assistant Sunsynk Add-On

For the Add-On you require Home Assistant OS and a RS-485 adaptor to connect to your Sunsynk inverter. Sensors are read using the Modbus protocol and sent to a MQTT server. See [deployment options](https://sunsynk.wectrl.net/guide/deployment-options) for examples of tested hardware.

### Installation

1. Add this repository to your HA Supervisor

   [![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmaslyankov%2Fsunsynk)

   `https://github.com/maslyankov/sunsynk`

2. Install the Sunsynk Add-On from the **Add-On Store** and configure through the UI

   ![Install Sunsynk Addon](https://github.com/maslyankov/sunsynk/raw/main/images/addon-install.png)


Below an example of the HomeAssistant Energy management dashboard using sensors from the Sunsynk.

![HASS Energy management](https://github.com/maslyankov/sunsynk/raw/main/images/energy.png)

## Sunsynk Python Library
[![PyPI version](https://badge.fury.io/py/sunsynk.svg)](https://pypi.org/project/sunsynk/)
[![codecov](https://codecov.io/gh/kellerza/sunsynk/branch/main/graph/badge.svg?token=ILKRC5UTXI)](https://codecov.io/gh/kellerza/sunsynk)

The Python library is available through pip: `pip install sunsynk`

## Special Thanks

Special thanks to [Johann Kellerman (kellerza)](https://github.com/kellerza) for creating and maintaining the original Sunsynk library and Home Assistant integration. His work laid the foundation for this project and has been instrumental in helping many users monitor and control their Deye/Sunsynk inverters.

Thanks also to all the contributors who have helped improve this project through:
- Code contributions
- Bug reports and testing
- Documentation improvements
- Hardware compatibility testing
- Community support and knowledge sharing

Your contributions have helped make this project better for everyone in the community.

For a complete list of contributors, please see the [GitHub contributors page](https://github.com/maslyankov/sunsynk/graphs/contributors).

## License

Apache 2.0 | Copyright © 2021-2025

