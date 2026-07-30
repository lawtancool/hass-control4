# hass-control4

This custom integration for Home Assistant allows control of Control4 lights, locks (only locks that are relay-based in Control4), alarm control panels, door/window/motion sensors (as binary sensors), thermostats, pool/spa (climate + optional aux switches), fans, relay devices (as switches), and blinds/shades (as covers, stateless open/close/stop).

## Installation

First, add this repository as a [custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/) in HACS. 

Then, you can use the link below to install the integration through HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=lawtancool&repository=hass-control4)

Once installed, follow the same setup instructions as the default integration: https://www.home-assistant.io/integrations/control4

### Additional configuration required for alarm control panel

If you are using an alarm control panel, you must go to Home Assistant -> Configuration -> Devices and Services -> Integrations and click "Configure" on the Control4 entry.

In the dialog that appears, choose the Control4 alarm arming modes that you want to correspond to each Home Assistant arming mode. For example, a DSC alarm system uses "Stay" as the "Alarm arm home mode name", and "Away" as the "Alarm arm away mode name". If your alarm system does not use one of the mode names, select `(not set)`. Once you click submit on the dialog, Home Assistant will be able to arm your alarm control panel and detect its state.

### Pool / spa (Pentair IntelliCenter and similar)

Pool and spa are exposed as heat-only `climate` entities:

- Current water temperature
- Heat setpoint
- Heat on/off (`hvac_mode` heat / off)
- Pump on/off (`fan_mode` on / off)

#### Pool / spa auxiliaries

Auxiliary circuits are optional `switch` entities. Circuit **numbers** (1–5) match Control4 Auxiliary Control IDs; you assign a **friendly name** to each slot you want in Home Assistant.

**When this is needed.** Climates work without this. Aux switches only appear for slots you name.

**How to find your aux IDs (Control4).**

1. Open **Composer Pro** (dealer) or the **Control4 app / Navigator** pool controls.
2. Open the pool controller's **Auxiliary** / circuit list.
3. Note the numeric ID next to each name (for example `2 = Pool Light`, `3 = Air Blower`, `4 = Spa Light`).

**How to configure in Home Assistant.**

1. **Settings → Devices & services**
2. Find **Control4** → overflow menu (**⋮**) → **Configure**
3. Fill **Pool aux 1–5 name** for circuits you want (leave blank for unused IDs), for example:
   - Aux 2 → `Pool Light`
   - Aux 3 → `Air Blower`
   - Aux 4 → `Spa Light`
4. **Submit** — the integration reloads.
5. Confirm the named switches appear on the Pentair / pool device.

**Troubleshooting.**

- Switch missing after save → that aux slot name was left blank, or reload still in progress; re-check **Configure**.
- Switch toggles but nothing happens → wrong aux ID for that circuit; rename/move the label to the correct slot.
- Climate works, lights don't → expected until you name the matching aux slots.

## Disclaimer

This integration is essentially a newer version of the Control4 integration that is included in Home Assistant by default, and will receive new updates faster than the default integration.

This means, however, that this custom integration may not be as stable as the default integration, as the code has not gone through Home Assistant's review process and contains the newest, bleeding-edge features.

This integration is not affiliated with or endorsed by Control4.
