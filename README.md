# WCM — Wayfire Config Manager (Python/PyQt5)

A Python rewrite of [WCM](https://github.com/WayfireWM/wcm) (Wayfire Config Manager),
faithfully reproducing the same layout and functionality using PyQt5.

## Key Design Goals

Per the upstream developer's requirements:

1. **Configure everything** without manually editing the config file by hand.
2. **Single-line config changes** — only the relevant line is modified on each
   option change. Comments, blank lines, and file structure are fully preserved.
   (This contrasts with wf-config which rewrites the entire file.)
3. **Compound option support** — first-class handling of dynamic-list/compound
   options like `autostart` and `command` bindings.

## Architecture

```
wcm.py              — Main application window, UI widgets, entry point
config_backend.py   — Line-preserving INI reader/writer (the backend)
metadata.py         — XML metadata parser for plugin/option discovery
```

The backend (`config_backend.py`) maintains an ordered list of every line in the
config file. When an option is changed, only that single `ConfigEntry` is updated.
When saved, all lines are written back verbatim — comments and blank lines included.

The metadata parser (`metadata.py`) reads Wayfire's XML plugin description files
(typically from `/usr/share/wayfire/metadata/*.xml`) to discover available plugins,
their options, types, defaults, min/max ranges, labels, groups, and subgroups.

## UI Layout (same as C++ WCM)

```
┌──────────────┬──────────────────────────────────────┐
│              │                                      │
│   Filter     │  ┌─ General ────────────────────┐    │
│   [search]   │  │ ☑ Core   ☑ Input   ☑ Place  │    │
│              │  └──────────────────────────────┘    │
│              │  ┌─ Effects ────────────────────┐    │
│              │  │ ☐ Wobbly  ☑ Alpha  ☐ Blur   │    │
│              │  └──────────────────────────────┘    │
│              │  ┌─ Window Management ──────────┐    │
│              │  │ ☑ Move   ☑ Resize  ☑ Grid   │    │
│  [Outputs]   │  └──────────────────────────────┘    │
│  [Close]     │                                      │
└──────────────┴──────────────────────────────────────┘
```

Clicking a plugin opens its config page with tabbed option groups:

```
┌──────────────┬──────────────────────────────────────┐
│              │  ┌─General─┬─Advanced─┐              │
│  Plugin Name │  │                    │              │
│  Description │  │ Activate  [binding]│              │
│              │  │ Speed     [=====]  │              │
│  ☑ Enabled   │  │ Enable    [✓]      │              │
│              │  │ Color     [■■■■]   │              │
│  [Back]      │  │                    │              │
└──────────────┴──────────────────────────────────────┘
```

## Supported Option Types

| Type         | Widget                          |
|--------------|---------------------------------|
| `int`        | SpinBox or ComboBox (if labels) |
| `double`     | DoubleSpinBox                   |
| `bool`       | CheckBox                        |
| `string`     | LineEdit or ComboBox (if labels)|
| `key`        | LineEdit (binding entry)        |
| `button`     | LineEdit (binding entry)        |
| `activator`  | LineEdit (binding entry)        |
| `gesture`    | LineEdit                        |
| `color`      | Color picker button             |
| `animation`  | SpinBox (ms) + ComboBox (easing)|
| `dynamic-list` | Compound option list editor   |

## Requirements

- Python 3.8+
- PyQt5
- lxml

## Installation

```bash
pip install PyQt5 lxml
```

## Usage

```bash
# Run directly
python wcm.py

# With a specific config file
python wcm.py -c ~/.config/wayfire/wayfire.ini

# Open a specific plugin at launch
python wcm.py -p move

# Install system-wide
pip install .
wcm
```

## Icon Loading

Icons are loaded from the same paths as the C++ version:
1. `$XDG_DATA_HOME/wayfire/icons/`
2. `/usr/share/wayfire/icons/`
3. `/usr/share/wcm/icons/`

Plugin icons are named `plugin-<name>.svg` (e.g., `plugin-move.svg`).

## License

MIT — same as the original WCM.
