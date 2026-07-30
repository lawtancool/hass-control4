# hass-control4

This custom integration for Home Assistant allows control of Control4 lights, locks (only locks that are relay-based in Control4), alarm control panels, door/window/motion sensors (as binary sensors), thermostats (including schedule presets and hold), fans, relay devices (as switches), and blinds/shades (as covers, stateless open/close/stop).

## Installation

First, add this repository as a [custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/) in HACS. 

Then, you can use the link below to install the integration through HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=lawtancool&repository=hass-control4)

Once installed, follow the same setup instructions as the default integration: https://www.home-assistant.io/integrations/control4

### Climate presets (thermostats)

Control4 schedule activities (`SET_PRESET`, e.g. Home / Away / Night) and permanent hold are exposed together as Home Assistant `climate` preset modes:

- Configure the available schedule names under **Settings → Devices & services → Control4 → Configure** (`Climate schedule presets`, comma-separated). Default: `Night, Evening, Day, Home, Away, Off`
- Names must match Control4 exactly (spelling and casing)
- Choosing a schedule preset clears hold, then applies that activity
- Choosing `Hold` enables permanent hold on the current setpoints
- Legacy hold values `Permanent` / `Off` still work (`Permanent` → Hold, `Off` → clear hold only)

### Additional configuration required for alarm control panel

If you are using an alarm control panel, you must go to Home Assistant -> Configuration -> Devices and Services -> Integrations and click "Configure" on the Control4 entry.

In the dialog that appears, choose the Control4 alarm arming modes that you want to correspond to each Home Assistant arming mode. For example, a DSC alarm system uses "Stay" as the "Alarm arm home mode name", and "Away" as the "Alarm arm away mode name". If your alarm system does not use one of the mode names, select `(not set)`. Once you click submit on the dialog, Home Assistant will be able to arm your alarm control panel and detect its state.

## Disclaimer

This integration is essentially a newer version of the Control4 integration that is included in Home Assistant by default, and will receive new updates faster than the default integration.

This means, however, that this custom integration may not be as stable as the default integration, as the code has not gone through Home Assistant's review process and contains the newest, bleeding-edge features.

This integration is not affiliated with or endorsed by Control4.
