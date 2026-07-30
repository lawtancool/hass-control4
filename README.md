# hass-control4

This custom integration for Home Assistant allows control of Control4 lights, locks (only locks that are relay-based in Control4), alarm control panels, door/window/motion sensors (as binary sensors), thermostats, fans, relay devices (as switches), and blinds/shades (as covers, stateless open/close/stop). Optional Composer **custom variables** (sensors) and **macros** (buttons) can be exposed via integration options.

## Installation

First, add this repository as a [custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/) in HACS. 

Then, you can use the link below to install the integration through HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=lawtancool&repository=hass-control4)

Once installed, follow the same setup instructions as the default integration: https://www.home-assistant.io/integrations/control4

### Additional configuration required for alarm control panel

If you are using an alarm control panel, you must go to Home Assistant -> Configuration -> Devices and Services -> Integrations and click "Configure" on the Control4 entry.

In the dialog that appears, choose the Control4 alarm arming modes that you want to correspond to each Home Assistant arming mode. For example, a DSC alarm system uses "Stay" as the "Alarm arm home mode name", and "Away" as the "Alarm arm away mode name". If your alarm system does not use one of the mode names, select `(not set)`. Once you click submit on the dialog, Home Assistant will be able to arm your alarm control panel and detect its state.

### Custom variables and macros

Composer **custom variables** (Variables agent) and **macros** (Macros agent) can be exposed in Home Assistant without creating device drivers for each one.

**Custom variables** become `sensor` entities updated over the Control4 WebSocket (`OnDataToUI` on the Variables agent), same as lights and thermostats — not polled. Names must match Composer exactly (case-sensitive), for example `DebugInt1` or `GateHoldOpen`. The Director REST API supports **read**; there is no generic write endpoint for custom variables today.

**Macros** become `button` entities and can also be triggered with the `control4.execute_macro` service. Macro names must match Composer exactly, for example `AllOff`.

**Configure**

1. **Settings → Devices & services → Control4 → Configure**
2. Fill **Custom variable N name** slots for variables you want as sensors
3. Fill **Macro N name** slots for macros you want as buttons
4. **Submit** — the integration reloads

**Services**

- `control4.execute_macro` — run a macro by name (`macro_name`)
- `control4.read_custom_variable` — read a variable by name (`variable_name`); returns `{ "value": ... }`

## Disclaimer

This integration is essentially a newer version of the Control4 integration that is included in Home Assistant by default, and will receive new updates faster than the default integration.

This means, however, that this custom integration may not be as stable as the default integration, as the code has not gone through Home Assistant's review process and contains the newest, bleeding-edge features.

This integration is not affiliated with or endorsed by Control4.
