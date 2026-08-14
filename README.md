# hass-control4

This custom integration for Home Assistant allows control of Control4 lights, locks (only locks that are relay-based in Control4), alarm control panels, door/window/motion sensors (as binary sensors), thermostats, fans, relay devices (as switches), and blinds/shades (as covers, stateless open/close/stop). Composer **custom variables** and **macros** (buttons) are discovered automatically.

## Installation

First, add this repository as a [custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/) in HACS. 

Then, you can use the link below to install the integration through HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=lawtancool&repository=hass-control4)

Once installed, follow the same setup instructions as the default integration: https://www.home-assistant.io/integrations/control4

### Additional configuration required for alarm control panel

If you are using an alarm control panel, you must go to Home Assistant -> Configuration -> Devices and Services -> Integrations and click "Configure" on the Control4 entry.

In the dialog that appears, choose the Control4 alarm arming modes that you want to correspond to each Home Assistant arming mode. For example, a DSC alarm system uses "Stay" as the "Alarm arm home mode name", and "Away" as the "Alarm arm away mode name". If your alarm system does not use one of the mode names, select `(not set)`. Once you click submit on the dialog, Home Assistant will be able to arm your alarm control panel and detect its state.

### Custom variables and macros

All Composer **custom variables** (Variables agent) and **macros** (Macros agent) are discovered automatically on setup and reload.

- **Variables** → read-only entities by Composer type (WebSocket push):
  - **Number** / **Float** → `number`
  - **Boolean** → `switch`
  - **String** → `text`
  - **Device** → `select`
  - other types → `sensor`
- **Macros** → one `button` per macro (single press to run)

Entities are **disabled by default** so programming objects do not clutter automations or dashboards until you enable the ones you want under **Settings → Devices & services → Entities** (filter by the **Variables** or **Macros** device).

After adding or renaming variables/macros in Composer, call **`control4.reload_programming`** (or reload the Control4 integration) to pick up the new list.

**Services**

- `control4.execute_macro` — run a macro by name (`macro_name`)
- `control4.read_custom_variable` — read a variable by name (`variable_name`); returns `{ "value": ... }`
- `control4.reload_programming` — re-discover variables and macros from the director

**Testing**

Safe defaults for verifying the integration:

- Variable: enable **`DebugInt1`** under **Variables**
- Macro: enable **`Test`** under **Macros**, or:

```yaml
service: control4.execute_macro
data:
  macro_name: Test
```

## Disclaimer

This integration is essentially a newer version of the Control4 integration that is included in Home Assistant by default, and will receive new updates faster than the default integration.

This means, however, that this custom integration may not be as stable as the default integration, as the code has not gone through Home Assistant's review process and contains the newest, bleeding-edge features.

This integration is not affiliated with or endorsed by Control4.
