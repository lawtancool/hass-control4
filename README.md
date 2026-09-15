# hass-control4

This custom integration for Home Assistant allows control of Control4 lights, locks (only locks that are relay-based in Control4), alarm control panels, door/window/motion sensors (as binary sensors), thermostats, fans, relay devices (as switches), and blinds/shades (as covers, stateless open/close/stop).

## Installation

First, add this repository as a [custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/) in HACS. 

Then, you can use the link below to install the integration through HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=lawtancool&repository=hass-control4)

Once installed, follow the same setup instructions as the default integration: https://www.home-assistant.io/integrations/control4

### Additional configuration required for alarm control panel

If you are using an alarm control panel, you must go to Home Assistant -> Configuration -> Devices and Services -> Integrations and click "Configure" on the Control4 entry.

In the dialog that appears, choose the Control4 alarm arming modes that you want to correspond to each Home Assistant arming mode. For example, a DSC alarm system uses "Stay" as the "Alarm arm home mode name", and "Away" as the "Alarm arm away mode name". If your alarm system does not use one of the mode names, select `(not set)`. Once you click submit on the dialog, Home Assistant will be able to arm your alarm control panel and detect its state.

### Alarm-zone sensors

Some alarm drivers expose zones through the security panel without creating separate
items in Control4's sensors category. These zones are also discovered as read-only
binary sensors, disabled by default to avoid duplicating existing sensors. Enable
only the additional zones you need from the integration's entity list in Home
Assistant. Their names come from the panel; IDs remain stable when names change.

Enabled zones use live events and a shared five-second refresh per panel. Missing
or unreadable states are unavailable, rather than reported as closed or clear.
Zone types that the driver does not identify as motion retain a generic binary
sensor class; they can be customized in Home Assistant.

### Older controller compatibility

Some controllers, including OS 2.10.6, return malformed XML from the optional UI
configuration endpoint. Setup logs a warning and continues loading the other
platforms. Room media players cannot be discovered without that endpoint.

### Regression checks

Run the focused checks with Python 3.12 or later:

```sh
python tests/test_legacy_setup.py
python tests/test_alarm_zones.py
```

These dependency-free checks execute the relevant integration functions against
Home Assistant/Director test doubles. They cover startup fallback, zone discovery,
unknown states, event isolation, disconnect/recovery, and listener cleanup; they
do not replace an integration test inside a running Home Assistant installation.

## Disclaimer

This integration is essentially a newer version of the Control4 integration that is included in Home Assistant by default, and will receive new updates faster than the default integration.

This means, however, that this custom integration may not be as stable as the default integration, as the code has not gone through Home Assistant's review process and contains the newest, bleeding-edge features.

This integration is not affiliated with or endorsed by Control4.
