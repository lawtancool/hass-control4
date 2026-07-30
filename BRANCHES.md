# Branch layout (Chew fork)

This fork uses two kinds of branches:

## `house` — Bellevue aggregate

Deploy this branch to Home Assistant. It merges every feature branch below that we run at home, plus house-only fixes that are not intended for upstream.

```bash
git checkout house
```

Current aggregate includes (among others): garage covers, alarm panel, pool/spa, climate schedule presets, Domosapiens temperature fix, custom variables/macros.

## `pr/*` — upstream-ready slices

Each `pr/<feature>` branch is rebased or branched from `upstream/master` (lawtancool/hass-control4) with **one feature per branch** for clean pull requests.

| Branch | Feature |
|--------|---------|
| `pr/garage-covers` | Garage door covers |
| `pr/alarm_control_panel` | Alarm panel |
| `pr/pool-spa` | Pool/spa climate + aux switches |
| `pr/climate-schedule-presets` | Climate schedule presets + Hold |
| `pr/variables-macros` | Composer custom variables + macros |

Workflow when a feature is ready for upstream:

1. Finish and test on `pr/<feature>`
2. Open PR to `lawtancool/hass-control4` from that branch
3. Keep `house` updated: `git checkout house && git merge pr/<feature>`

## `master` — fork default

Contains fork-specific work (e.g. garage covers) that may predate the `pr/*` split. Prefer new work on `pr/*` + merge to `house`.

## Remotes

- `origin` — `armedad/hass-control4` (this fork)
- `upstream` — `lawtancool/hass-control4`

```bash
git fetch upstream
git checkout -b pr/my-feature upstream/master
# ... commits ...
git push -u origin pr/my-feature
git checkout house && git merge pr/my-feature
git push origin house
```
