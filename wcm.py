#!/usr/bin/env python3
"""
Wayfire Config Manager (WCM) — Python/GTK4 Edition

A faithful port of the C++/GTK3 WCM to Python/GTK4, implementing:
 1) Configure anything without manually editing config files.
 2) Only change the relevant line(s) in the config on each option change,
    preserving comments and formatting.
 3) First-class support for compound/dynamic-list options.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')

import sys
import os
import subprocess
import glob
import shutil
import traceback

from gi.repository import Gtk, Gdk, GLib, Gio, GdkPixbuf, Pango

from config_backend import WayfireConfigFile
from metadata import (
    load_all_metadata, load_metadata_from_dir, find_metadata_dirs,
    Plugin, Option, OptionType, PluginType,
)


# ─── Color parsing ───────────────────────────────────────────────────────────

def parse_color(color_str):
    """Parse Wayfire color strings into Gdk.RGBA.

    Supported:
      - 'R G B A'
      - 'R G B'
      - '#RRGGBB'
      - '#RRGGBBAA'
      - '\#RRGGBB'
      - '\#RRGGBBAA'
    """
    rgba = Gdk.RGBA()

    if color_str is None:
        rgba.red = rgba.green = rgba.blue = 0.0
        rgba.alpha = 1.0
        return rgba

    s = str(color_str).strip()
    if not s:
        rgba.red = rgba.green = rgba.blue = 0.0
        rgba.alpha = 1.0
        return rgba

    # unescape escaped hash from config strings like \#FF0000FF
    if s.startswith(r'\#'):
        s = s[1:]

    # strip wrapping quotes
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()

    # unescape again in case quoted string was "\#FF0000FF"
    if s.startswith(r'\#'):
        s = s[1:]

    # trim comment-like junk, but don't break hex colors
    if not s.startswith('#'):
        for sep in (' ;', '\t;', ' #'):
            if sep in s:
                s = s.split(sep, 1)[0].strip()

    # hex forms
    if s.startswith('#'):
        h = s[1:]
        if len(h) == 6:
            h += 'FF'
        if len(h) == 8:
            try:
                rgba.red = int(h[0:2], 16) / 255.0
                rgba.green = int(h[2:4], 16) / 255.0
                rgba.blue = int(h[4:6], 16) / 255.0
                rgba.alpha = int(h[6:8], 16) / 255.0
                return rgba
            except ValueError:
                pass

    # float RGB / RGBA
    parts = s.split()
    if len(parts) == 3:
        parts.append('1.0')

    if len(parts) == 4:
        try:
            rgba.red = max(0.0, min(1.0, float(parts[0])))
            rgba.green = max(0.0, min(1.0, float(parts[1])))
            rgba.blue = max(0.0, min(1.0, float(parts[2])))
            rgba.alpha = max(0.0, min(1.0, float(parts[3])))
            return rgba
        except ValueError:
            pass

    print(f"[ClassicWCM] Could not parse color: {color_str!r}", file=sys.stderr)
    rgba.red = rgba.green = rgba.blue = 0.0
    rgba.alpha = 1.0
    return rgba


def color_to_str(rgba):
    return f"{rgba.red:.4f} {rgba.green:.4f} {rgba.blue:.4f} {rgba.alpha:.4f}"


# ─── Key names mapping ───────────────────────────────────────────────────────

_GDK_TO_LINUX = {
    Gdk.KEY_Escape: 'KEY_ESC', Gdk.KEY_Return: 'KEY_ENTER',
    Gdk.KEY_KP_Enter: 'KEY_ENTER', Gdk.KEY_Tab: 'KEY_TAB',
    Gdk.KEY_BackSpace: 'KEY_BACKSPACE', Gdk.KEY_Delete: 'KEY_DELETE',
    Gdk.KEY_Insert: 'KEY_INSERT', Gdk.KEY_Home: 'KEY_HOME',
    Gdk.KEY_End: 'KEY_END', Gdk.KEY_Page_Up: 'KEY_PAGEUP',
    Gdk.KEY_Page_Down: 'KEY_PAGEDOWN', Gdk.KEY_Left: 'KEY_LEFT',
    Gdk.KEY_Right: 'KEY_RIGHT', Gdk.KEY_Up: 'KEY_UP',
    Gdk.KEY_Down: 'KEY_DOWN', Gdk.KEY_space: 'KEY_SPACE',
    Gdk.KEY_Pause: 'KEY_PAUSE', Gdk.KEY_Print: 'KEY_SYSRQ',
    Gdk.KEY_Scroll_Lock: 'KEY_SCROLLLOCK', Gdk.KEY_Caps_Lock: 'KEY_CAPSLOCK',
    Gdk.KEY_Num_Lock: 'KEY_NUMLOCK',
}
# Add F-keys and letter/number keys
for i in range(1, 13):
    _GDK_TO_LINUX[getattr(Gdk, f'KEY_F{i}')] = f'KEY_F{i}'
for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
    _GDK_TO_LINUX[getattr(Gdk, f'KEY_{c.lower()}')] = f'KEY_{c}'
    _GDK_TO_LINUX[getattr(Gdk, f'KEY_{c}')] = f'KEY_{c}'
for c in '0123456789':
    _GDK_TO_LINUX[getattr(Gdk, f'KEY_{c}')] = f'KEY_{c}'

_MODIFIER_KEYVALS = {
    Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, Gdk.KEY_Control_R,
    Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R,
    Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_ISO_Level3_Shift,
}


def _keyval_to_linux(keyval):
    """Convert GDK keyval to Linux KEY_* name."""
    name = _GDK_TO_LINUX.get(keyval)
    if name:
        return name
    gdk_name = Gdk.keyval_name(keyval)
    if gdk_name:
        return 'KEY_' + gdk_name.upper()
    return None


# ─── Key grab window ─────────────────────────────────────────────────────────

class KeyGrabWindow(Gtk.Window):
    """Captures a key/button binding — mirrors C++ KeyEntry::grab_key."""

    def __init__(self, parent):
        super().__init__(title='Waiting for Binding', modal=True,
                         transient_for=parent.get_root(),
                         default_width=350, default_height=100)
        self.result = ''
        self._mods = set()
        self._done = False

        self._label = Gtk.Label(label='Press a key combination…\n(Escape to cancel)')
        self._label.set_halign(Gtk.Align.CENTER)
        self._label.set_valign(Gtk.Align.CENTER)
        self.set_child(self._label)

        # Key controller
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect('key-pressed', self._on_key_pressed)
        key_ctrl.connect('key-released', self._on_key_released)
        self.add_controller(key_ctrl)

        # Mouse button controller
        click = Gtk.GestureClick()
        click.set_button(0)  # any button
        click.connect('pressed', self._on_click)
        self.add_controller(click)

    def _mod_string(self):
        parts = []
        if self._mods & {Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R}:
            parts.append('<super>')
        if self._mods & {Gdk.KEY_Control_L, Gdk.KEY_Control_R}:
            parts.append('<ctrl>')
        if self._mods & {Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_ISO_Level3_Shift}:
            parts.append('<alt>')
        if self._mods & {Gdk.KEY_Shift_L, Gdk.KEY_Shift_R}:
            parts.append('<shift>')
        return ' '.join(parts)

    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape and not self._mods:
            self.close()
            return True
        if keyval in _MODIFIER_KEYVALS:
            self._mods.add(keyval)
            ms = self._mod_string()
            self._label.set_text(ms if ms else '(No modifiers pressed)')
            return True
        key_name = _keyval_to_linux(keyval)
        if key_name:
            mod = self._mod_string()
            self.result = (mod + ' ' + key_name).strip()
            self._done = True
            self.close()
        return True

    def _on_key_released(self, ctrl, keyval, keycode, state):
        self._mods.discard(keyval)
        ms = self._mod_string()
        self._label.set_text(ms if ms else 'Press a key combination…')

    def _on_click(self, gesture, n_press, x, y):
        btn_map = {1: 'BTN_LEFT', 2: 'BTN_MIDDLE', 3: 'BTN_RIGHT',
                   8: 'BTN_SIDE', 9: 'BTN_EXTRA'}
        button = gesture.get_current_button()
        btn_name = btn_map.get(button)
        if btn_name:
            mod = self._mod_string()
            self.result = (mod + ' ' + btn_name).strip()
            self._done = True
            self.close()


# ─── Icon helpers — replicates C++ WCM::find_icon() ─────────────────────────

_wf_icon_dir = None
_wcm_icon_dir = None
_xdg_icon_dir = None
_icons_resolved = False


def _resolve_icon_dirs():
    """Resolve icon dirs same way as C++ WCM (compile-time constants derived at runtime)."""
    global _xdg_icon_dir, _wf_icon_dir, _wcm_icon_dir, _icons_resolved
    if _icons_resolved:
        return
    _icons_resolved = True

    # 1. XDG_DATA_HOME/wayfire/icons
    xdg = os.environ.get('XDG_DATA_HOME', '')
    if not xdg:
        xdg = os.path.join(os.path.expanduser('~'), '.local', 'share')
    _xdg_icon_dir = os.path.join(xdg, 'wayfire', 'icons')

    # 2. WAYFIRE_ICONDIR from pkg-config
    try:
        r = subprocess.run(['pkg-config', '--variable=icondir', 'wayfire'],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            _wf_icon_dir = r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 3. WCM_ICONDIR = <prefix>/share/wcm/icons — derive from binary locations
    for binary in ('wcm', 'wayfire'):
        path = shutil.which(binary)
        if path:
            prefix = os.path.dirname(os.path.dirname(os.path.realpath(path)))
            d = os.path.join(prefix, 'share', 'wcm', 'icons')
            if os.path.isdir(d):
                _wcm_icon_dir = d
                break

    # Also try pkg-config prefix
    if not _wcm_icon_dir:
        try:
            r = subprocess.run(['pkg-config', '--variable=prefix', 'wayfire'],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                d = os.path.join(r.stdout.strip(), 'share', 'wcm', 'icons')
                if os.path.isdir(d):
                    _wcm_icon_dir = d
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Dev mode — relative to script
    if not _wcm_icon_dir:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for rel in ('icons/plugins', 'icons', '../icons/plugins',
                    '../wcm/icons/plugins', '../wcm/icons'):
            d = os.path.normpath(os.path.join(script_dir, rel))
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, 'plugin-core.svg')):
                _wcm_icon_dir = d
                break

    # Last resort — filesystem search
    if not _wcm_icon_dir:
        for root in ('/usr/share', '/usr/local/share', '/opt'):
            try:
                r = subprocess.run(
                    ['find', root, '-maxdepth', '5', '-name',
                     'plugin-core.svg', '-type', 'f'],
                    capture_output=True, text=True, timeout=10)
                for line in (r.stdout or '').strip().splitlines():
                    d = os.path.dirname(line.strip())
                    if d:
                        _wcm_icon_dir = d
                        break
                if _wcm_icon_dir:
                    break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    print(f"WCM: XDG icon dir: {_xdg_icon_dir}")
    print(f"WCM: WAYFIRE_ICONDIR: {_wf_icon_dir or '(not found)'}")
    print(f"WCM: WCM_ICONDIR: {_wcm_icon_dir or '(not found)'}")


def find_icon(name):
    """Find an icon file by name — exact replica of C++ WCM::find_icon()."""
    _resolve_icon_dirs()
    if _xdg_icon_dir:
        p = os.path.join(_xdg_icon_dir, name)
        if os.path.isfile(p):
            return p
    if _wf_icon_dir:
        p = os.path.join(_wf_icon_dir, name)
        if os.path.isfile(p):
            return p
    if _wcm_icon_dir:
        p = os.path.join(_wcm_icon_dir, name)
        if os.path.isfile(p):
            return p
    # Fallback: search standard wayfire icon directories
    # (covers icons from wayfire-plugins-extra and other packages)
    for prefix in ('/usr', '/usr/local', os.path.expanduser('~/.local')):
        p = os.path.join(prefix, 'share', 'wayfire', 'icons', name)
        if os.path.isfile(p):
            return p
    return ''


def find_plugin_icon(plugin_name):
    # Try exact name first, then hyphen/underscore variants
    for name in (plugin_name,
                 plugin_name.replace('_', '-'),
                 plugin_name.replace('-', '_')):
        path = find_icon(f"plugin-{name}.svg")
        if path:
            return path
    return None


def find_app_icon():
    return find_icon('wcm.svg') or None


# ─── Categories (same as C++ WCM) ───────────────────────────────────────────

CATEGORIES = [
    ('General', 'preferences-system'),
    ('Accessibility', 'preferences-desktop-accessibility'),
    ('Desktop', 'preferences-desktop'),
    ('Shell', 'user-desktop'),
    ('Effects', 'applications-graphics'),
    ('Window Management', 'applications-accessories'),
    ('Utility', 'applications-other'),
    ('Other', 'applications-other'),
]
CATEGORY_NAMES = [c[0] for c in CATEGORIES]


def get_category_index(cat):
    for i, (n, _) in enumerate(CATEGORIES):
        if n == cat:
            return i
    return len(CATEGORIES) - 1


# ─── Config path ─────────────────────────────────────────────────────────────

def get_config_path():
    override = os.environ.get('WAYFIRE_CONFIG_FILE')
    if override:
        return os.path.expanduser(override)
    ch = os.environ.get('XDG_CONFIG_HOME', '')
    if not ch:
        ch = os.path.join(os.path.expanduser('~'), '.config')
    p = os.path.join(ch, 'wayfire', 'wayfire.ini')
    return p if os.path.isfile(p) else os.path.join(ch, 'wayfire.ini')


# ─── Option Widgets ──────────────────────────────────────────────────────────

LABEL_W = 200


def _int(val, default):
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    return default if isinstance(default, int) else 0


def _parse_anim(s):
    parts = str(s).split()
    dur, easing = 300, 'linear'
    if parts:
        try:
            dur = int(parts[0].replace('ms', ''))
        except ValueError:
            pass
    if len(parts) > 1:
        easing = parts[1]
    return dur, easing


class OptionWidget(Gtk.Box):
    """Widget for a single plugin option — mirrors C++ OptionWidget."""

    def __init__(self, option, config, plugin):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.option = option
        self.config = config
        self.plugin = plugin
        self._block = False

        self.set_margin_start(4)
        self.set_margin_end(4)
        self.set_margin_top(2)
        self.set_margin_bottom(2)

        # Label
        self.lbl = Gtk.Label(label=option.disp_name or option.name)
        self.lbl.set_tooltip_text(option.tooltip or '')
        self.lbl.set_size_request(LABEL_W, -1)
        self.lbl.set_xalign(0)
        self.lbl.set_hexpand(False)
        self.lbl.set_halign(Gtk.Align.START)
        self.append(self.lbl)

        # Right-aligned area for editor buttons / controls
        self.end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.end_box.set_hexpand(True)
        self.end_box.set_halign(Gtk.Align.FILL)
        self.append(self.end_box)

        current = config.get_option(plugin.name, option.name)
        self._build(option, current)

        # Compact widgets (checkbox, color, spinbutton) stay right-aligned;
        # expanding widgets (entries, combos) fill the row
        if option.type in (OptionType.BOOL, OptionType.COLOR,
                           OptionType.DOUBLE) or (
                option.type == OptionType.INT and not option.int_labels):
            self.end_box.set_hexpand(True)
            self.end_box.set_halign(Gtk.Align.END)

        # Reset button
        self.reset_btn = Gtk.Button.new_from_icon_name('edit-clear')
        self.reset_btn.set_tooltip_text('Reset to default')
        self.reset_btn.connect('clicked', self._reset)
        self.end_box.append(self.reset_btn)

    def _build(self, opt, cur):
        ot = opt.type

        if ot == OptionType.INT:
            if opt.int_labels:
                self.ed = Gtk.ComboBoxText()
                for lb, v in opt.int_labels:
                    self.ed.append(str(v), lb)
                cv = _int(cur, opt.default_value)
                self.ed.set_active_id(str(cv))
                self.ed.connect('changed', lambda w: self._save(w.get_active_id() or '0'))
                self.ed.set_hexpand(True)
            else:
                adj = Gtk.Adjustment(
                    value=_int(cur, opt.default_value),
                    lower=opt.min_val,
                    upper=min(opt.max_val, 2**31 - 1),
                    step_increment=1
                )
                self.ed = Gtk.SpinButton(adjustment=adj)
                self.ed.connect('value-changed', lambda w: self._save(str(w.get_value_as_int())))
                self.ed.set_hexpand(False)
            self.end_box.append(self.ed)

        elif ot == OptionType.DOUBLE:
            try:
                v = float(cur) if cur else float(opt.default_value)
            except (ValueError, TypeError):
                v = 0.0
            dec = len(str(opt.precision).split('.')[-1]) if '.' in str(opt.precision) else 3
            adj = Gtk.Adjustment(
                value=v,
                lower=max(opt.min_val, -1e15),
                upper=min(opt.max_val, 1e15),
                step_increment=opt.precision
            )
            self.ed = Gtk.SpinButton(adjustment=adj, digits=dec)
            self.ed.set_hexpand(False)
            self.ed.connect('value-changed', lambda w: self._save(str(w.get_value())))
            self.end_box.append(self.ed)

        elif ot == OptionType.BOOL:
            self.ed = Gtk.CheckButton()
            if cur is not None:
                self.ed.set_active(str(cur).strip().lower() in ('true', '1', 'yes', 'on'))
            else:
                self.ed.set_active(bool(opt.default_value))
            self.ed.set_hexpand(False)
            self.ed.set_halign(Gtk.Align.END)
            self.ed.connect('toggled', lambda w: self._save('true' if w.get_active() else 'false'))
            self.end_box.append(self.ed)

        elif ot in (OptionType.STRING, OptionType.GESTURE):
            if opt.str_labels:
                self.ed = Gtk.ComboBoxText()
                for lb, v in opt.str_labels:
                    self.ed.append(v, lb)
                cv = cur if cur is not None else str(opt.default_value or '')
                self.ed.set_active_id(cv)
                self.ed.connect('changed', lambda w: self._save(w.get_active_id() or ''))
                self.ed.set_hexpand(True)
                self.end_box.append(self.ed)
            else:
                entry_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                entry_box.set_hexpand(True)

                self.ed = Gtk.Entry()
                self.ed.set_text(cur if cur is not None else str(opt.default_value or ''))
                self.ed.set_hexpand(True)
                self.ed.connect('activate', lambda w: self._save(w.get_text()))
                fc = Gtk.EventControllerFocus()
                fc.connect('leave', lambda c: self._save(self.ed.get_text()))
                self.ed.add_controller(fc)
                entry_box.append(self.ed)

                if 'directory' in opt.hints:
                    b = Gtk.Button.new_from_icon_name('folder-open')
                    b.set_tooltip_text('Choose Directory')
                    b.connect('clicked', self._choose_dir)
                    entry_box.append(b)

                if 'file' in opt.hints:
                    b = Gtk.Button.new_from_icon_name('document-open')
                    b.set_tooltip_text('Choose File')
                    b.connect('clicked', self._choose_file)
                    entry_box.append(b)

                self.end_box.append(entry_box)

        elif ot in (OptionType.KEY, OptionType.BUTTON, OptionType.ACTIVATOR):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            box.set_hexpand(True)
            self.ed = Gtk.Entry()
            self.ed.set_text(cur if cur is not None else str(opt.default_value or ''))
            self.ed.set_hexpand(True)
            self.ed.connect('activate', lambda w: self._save(w.get_text()))
            fc = Gtk.EventControllerFocus()
            fc.connect('leave', lambda c: self._save(self.ed.get_text()))
            self.ed.add_controller(fc)
            box.append(self.ed)

            grab = Gtk.Button(label='…')
            grab.set_tooltip_text('Grab key/button binding')
            grab.connect('clicked', self._grab_key)
            box.append(grab)

            self.end_box.append(box)

        elif ot == OptionType.COLOR:
            cs = cur if cur is not None else str(opt.default_value or '0.0 0.0 0.0 1.0')
            self.ed = Gtk.ColorButton()
            self.ed.set_use_alpha(True)
            self.ed.set_rgba(parse_color(cs))
            self.ed.set_hexpand(False)
            self.ed.set_halign(Gtk.Align.END)
            self.ed.connect('color-set', self._on_color_set)
            self.end_box.append(self.ed)

        elif ot == OptionType.ANIMATION:
            dur, easing = _parse_anim(
                cur if cur is not None else str(opt.default_value or '300ms linear')
            )

            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

            adj = Gtk.Adjustment(
                value=dur,
                lower=opt.min_val,
                upper=min(opt.max_val, 100000),
                step_increment=1
            )
            self._aspin = Gtk.SpinButton(adjustment=adj)
            self._acb = Gtk.ComboBoxText()
            for e in ('linear', 'circle', 'sigmoid'):
                self._acb.append_text(e)
            for i, e in enumerate(('linear', 'circle', 'sigmoid')):
                if e == easing:
                    self._acb.set_active(i)

            self._aspin.connect('value-changed', lambda w: self._save_anim())
            self._acb.connect('changed', lambda w: self._save_anim())

            box.append(self._aspin)
            box.append(self._acb)
            self.end_box.append(box)
            self.ed = self._aspin

        else:
            self.ed = Gtk.Entry()
            self.ed.set_text(cur if cur is not None else str(opt.default_value or ''))
            self.ed.set_hexpand(True)
            self.ed.connect('activate', lambda w: self._save(w.get_text()))
            self.end_box.append(self.ed)

    def _save(self, val):
        if self._block:
            return
        self.config.set_option(self.plugin.name, self.option.name, str(val))
        self.config.save()

    def _save_anim(self):
        self._save(f"{self._aspin.get_value_as_int()}ms {self._acb.get_active_text() or 'linear'}")

    def _on_color_set(self, btn):
        self._save(color_to_str(btn.get_rgba()))

    def _grab_key(self, btn):
        win = KeyGrabWindow(self)
        win.connect('close-request', self._on_grab_done)
        win.present()

    def _on_grab_done(self, win):
        if win.result:
            self.ed.set_text(win.result)
            self._save(win.result)
        return False

    def _choose_dir(self, btn):
        dlg = Gtk.FileChooserNative(
            title='Select Directory', transient_for=self.get_root(),
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dlg.connect('response', self._on_file_response)
        dlg.show()

    def _choose_file(self, btn):
        dlg = Gtk.FileChooserNative(
            title='Select File', transient_for=self.get_root(),
            action=Gtk.FileChooserAction.OPEN
        )
        dlg.connect('response', self._on_file_response)
        dlg.show()

    def _on_file_response(self, dlg, response):
        if response == Gtk.ResponseType.ACCEPT:
            f = dlg.get_file()
            if f:
                self.ed.set_text(f.get_path())
                self._save(f.get_path())

    def _reset(self, btn):
        d = self.option.default_value
        self._block = True
        try:
            if self.option.type == OptionType.INT:
                if self.option.int_labels:
                    self.ed.set_active_id(str(d))
                else:
                    self.ed.set_value(d if isinstance(d, int) else 0)

            elif self.option.type == OptionType.DOUBLE:
                self.ed.set_value(d if isinstance(d, float) else 0.0)

            elif self.option.type == OptionType.BOOL:
                self.ed.set_active(bool(d))

            elif self.option.type in (
                OptionType.STRING, OptionType.KEY,
                OptionType.BUTTON, OptionType.ACTIVATOR,
                OptionType.GESTURE
            ):
                if self.option.str_labels:
                    self.ed.set_active_id(str(d or ''))
                else:
                    self.ed.set_text(str(d or ''))

            elif self.option.type == OptionType.COLOR:
                self.ed.set_rgba(parse_color(str(d or '0 0 0 1')))

            elif self.option.type == OptionType.ANIMATION:
                dur, easing = _parse_anim(str(d or '300ms linear'))
                self._aspin.set_value(dur)
                for i, e in enumerate(('linear', 'circle', 'sigmoid')):
                    if e == easing:
                        self._acb.set_active(i)
                        break

        finally:
            self._block = False

        self._save(str(d or ''))

class SubgroupWidget(Gtk.Frame):
    """Expandable subgroup — mirrors C++ OptionSubgroupWidget."""

    def __init__(self, sg, config, plugin):
        super().__init__()
        exp = Gtk.Expander(label=sg.name or 'Options')
        exp.set_expanded(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        for opt in sg.options:
            if opt.hidden:
                continue
            try:
                box.append(OptionWidget(opt, config, plugin))
            except Exception as e:
                box.append(Gtk.Label(label=f"⚠ {opt.name}: {e}"))
        exp.set_child(box)
        self.set_child(exp)


# ─── Plugin Page (tabbed option groups) ──────────────────────────────────────

class PluginPage(Gtk.Notebook):
    """Tabbed option groups — mirrors C++ PluginPage."""

    def __init__(self, plugin, config):
        super().__init__()
        self.set_scrollable(True)
        self._bindings_rendered = False

        for group in plugin.option_groups:
            if group.type != OptionType.GROUP or group.hidden:
                continue

            scroll = Gtk.ScrolledWindow()
            scroll.set_vexpand(True)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.set_margin_start(10)
            box.set_margin_end(10)
            box.set_margin_top(10)
            box.set_margin_bottom(10)

            for opt in group.options:
                if opt.hidden:
                    continue
                try:
                    if opt.type == OptionType.SUBGROUP and opt.options:
                        box.append(SubgroupWidget(opt, config, plugin))
                    elif opt.type == OptionType.DYNAMIC_LIST:
                        w = self._make_dynlist(opt, config, plugin)
                        if w:
                            box.append(w)
                    elif opt.type != OptionType.GROUP:
                        box.append(OptionWidget(opt, config, plugin))
                except Exception as e:
                    err = Gtk.Label(label=f"⚠ Error: '{opt.name}': {e}")
                    box.append(err)
                    traceback.print_exc()

            scroll.set_child(box)
            self.append_page(scroll, Gtk.Label(label=group.name or 'General'))

    def _make_dynlist(self, option, config, plugin):
        """Build compound option widgets matching C++ WCM."""
        # Determine which compound type based on entries and option name
        prefixes = [e.prefix for e in option.entries] if option.entries else []
        sopts = config.get_section_options(plugin.name)

        # Autostart: entries with empty prefix → all keys are commands
        if option.name == 'autostart' or (prefixes == ['']):
            return self._make_autostart_list(option, config, plugin, sopts)

        # Command bindings: entries with command_ and binding_ prefixes
        if any('binding' in p for p in prefixes) or option.name in (
                'bindings', 'repeatable_bindings', 'always_bindings',
                'release_bindings'):
            if self._bindings_rendered:
                return None
            self._bindings_rendered = True
            return self._make_bindings_list(option, config, plugin, sopts)

        # Generic compound: show as labeled rows
        frame = Gtk.Frame(label=option.disp_name or option.name)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8); box.set_margin_end(8)
        box.set_margin_top(8); box.set_margin_bottom(8)
        if prefixes:
            for key, val in sopts.items():
                if any(key.startswith(p) for p in prefixes if p):
                    self._add_simple_row(box, key, val, config, plugin)
        frame.set_child(box)
        return frame

    # ── Autostart list (mirrors C++ AutostartDynamicList) ──

    def _make_autostart_list(self, option, config, plugin, sopts):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        # Collect autostart entries (all keys except autostart_wf_shell)
        reserved = {'autostart_wf_shell'}
        for key, val in sopts.items():
            if key not in reserved:
                box.append(self._make_autostart_row(key, val, config, plugin, box))

        # Add button
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_btn = Gtk.Button.new_from_icon_name('list-add')
        add_btn.set_tooltip_text('Add autostart entry')
        add_btn.set_halign(Gtk.Align.END)
        add_btn.connect('clicked', lambda w: self._add_autostart(config, plugin, box))
        add_box.append(add_btn)
        add_box.set_halign(Gtk.Align.END)
        box.append(add_box)

        return box

    def _make_autostart_row(self, key, val, config, plugin, parent_box):
        """Single autostart entry: [command] [choose] [run] [remove]."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        entry = Gtk.Entry()
        entry.set_text(val)
        entry.set_hexpand(True)
        entry.connect('activate',
                       lambda w, k=key: self._save_opt(config, plugin, k, w.get_text()))
        fc = Gtk.EventControllerFocus()
        fc.connect('leave',
                   lambda c, e=entry, k=key: self._save_opt(config, plugin, k, e.get_text()))
        entry.add_controller(fc)
        row.append(entry)

        # Choose executable button
        choose = Gtk.Button.new_from_icon_name('application-x-executable')
        choose.set_tooltip_text('Choose Executable')
        choose.connect('clicked', lambda w, e=entry: self._choose_exec(e))
        row.append(choose)

        # Run button
        run = Gtk.Button.new_from_icon_name('media-playback-start')
        run.set_tooltip_text('Run command')
        run.connect('clicked', lambda w, e=entry: self._run_cmd(e.get_text()))
        row.append(run)

        # Remove button
        rm = Gtk.Button.new_from_icon_name('list-remove')
        rm.set_tooltip_text('Remove from autostart list')
        rm.connect('clicked',
                   lambda w, k=key, r=row: self._remove_row(config, plugin, k, r, parent_box))
        row.append(rm)

        return row

    def _add_autostart(self, config, plugin, box):
        """Add a new autostart entry."""
        # Find next available key name
        sopts = config.get_section_options(plugin.name)
        i = 0
        while f"a{i}" in sopts:
            i += 1
        key = f"a{i}"
        config.set_option(plugin.name, key, '')
        config.save()
        # Insert before the add button
        row = self._make_autostart_row(key, '', config, plugin, box)
        # Insert before last child (the add button box)
        child = box.get_first_child()
        last = None
        while child:
            last = child
            child = child.get_next_sibling()
        if last:
            box.insert_child_after(row, None)  # prepend
            box.reorder_child_after(row, last.get_prev_sibling() if last.get_prev_sibling() else None)
        else:
            box.append(row)

    # ── Command bindings list (mirrors C++ BindingsDynamicList) ──

    def _make_bindings_list(self, option, config, plugin, sopts):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Find all unique command names (suffixes after command_)
        cmd_names = []
        for key in sopts:
            if key.startswith('command_'):
                name = key[len('command_'):]
                if name and name not in cmd_names:
                    cmd_names.append(name)

        for cmd_name in sorted(cmd_names):
            box.append(self._make_binding_widget(cmd_name, config, plugin, sopts, box))

        # Add button
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_box.set_hexpand(True)
        add_btn = Gtk.Button.new_from_icon_name('list-add')
        add_btn.set_tooltip_text('Add command binding')
        add_btn.set_halign(Gtk.Align.END)
        add_btn.connect('clicked', lambda w: self._add_binding(config, plugin, box))
        add_box.append(add_btn)
        add_box.set_halign(Gtk.Align.END)
        add_box.set_margin_top(6)
        box.append(add_box)

        return box

    def _make_binding_widget(self, cmd_name, config, plugin, sopts, parent_box):
        """
        Single command binding — expandable frame with Type/Binding/Command.
        Mirrors C++ BindingsDynamicList::BindingWidget.
        """
        command_key = f"command_{cmd_name}"
        regular_key = f"binding_{cmd_name}"
        repeat_key = f"repeatable_binding_{cmd_name}"
        always_key = f"always_binding_{cmd_name}"

        command_val = sopts.get(command_key, '')
        regular_val = sopts.get(regular_key)
        repeat_val = sopts.get(repeat_key)
        always_val = sopts.get(always_key)

        # Determine current type and binding value
        if always_val is not None:
            bind_type = 2  # Always
            bind_val = always_val
            bind_key = always_key
        elif repeat_val is not None:
            bind_type = 1  # Repeat
            bind_val = repeat_val
            bind_key = repeat_key
        elif regular_val is not None:
            bind_type = 0  # Regular
            bind_val = regular_val
            bind_key = regular_key
        else:
            bind_type = 0
            bind_val = 'none'
            bind_key = regular_key

        # Expander frame
        frame = Gtk.Frame()
        frame.set_margin_top(1)
        frame.set_margin_bottom(1)
        exp = Gtk.Expander(label=f"Command {cmd_name}: {command_val}")
        exp.set_expanded(not command_val)  # expand if command is empty
        exp.set_margin_top(4)
        exp.set_margin_bottom(4)
        exp.set_margin_start(4)
        exp.set_margin_end(4)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(5); vbox.set_margin_end(5)
        vbox.set_margin_top(5); vbox.set_margin_bottom(5)

        # Type row
        type_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        type_lbl = Gtk.Label(label='Type')
        type_lbl.set_size_request(LABEL_W, -1)
        type_lbl.set_xalign(0)
        type_row.append(type_lbl)
        type_cb = Gtk.ComboBoxText()
        type_cb.append_text('Regular')
        type_cb.append_text('Repeat')
        type_cb.append_text('Always')
        type_cb.set_active(bind_type)
        type_cb.set_hexpand(True)
        type_cb.connect('changed', lambda w, cn=cmd_name:
                        self._change_binding_type(config, plugin, cn, w.get_active()))
        type_row.append(type_cb)
        vbox.append(type_row)

        # Binding row
        bind_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bind_lbl = Gtk.Label(label='Binding')
        bind_lbl.set_size_request(LABEL_W, -1)
        bind_lbl.set_xalign(0)
        bind_row.append(bind_lbl)
        bind_entry = Gtk.Entry()
        bind_entry.set_text(bind_val)
        bind_entry.set_hexpand(True)
        bind_entry.connect('activate', lambda w, bk=bind_key:
                           self._save_opt(config, plugin, bk, w.get_text()))
        fc = Gtk.EventControllerFocus()
        fc.connect('leave', lambda c, e=bind_entry, bk=bind_key:
                   self._save_opt(config, plugin, bk, e.get_text()))
        bind_entry.add_controller(fc)
        bind_row.append(bind_entry)
        grab = Gtk.Button.new_from_icon_name('input-keyboard')
        grab.set_tooltip_text('Grab key/button binding')
        grab.connect('clicked', lambda w, e=bind_entry, bk=bind_key:
                     self._grab_for_entry(e, config, plugin, bk))
        bind_row.append(grab)
        vbox.append(bind_row)

        # Command row
        cmd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        cmd_lbl = Gtk.Label(label='Command')
        cmd_lbl.set_size_request(LABEL_W, -1)
        cmd_lbl.set_xalign(0)
        cmd_row.append(cmd_lbl)
        cmd_entry = Gtk.Entry()
        cmd_entry.set_text(command_val)
        cmd_entry.set_hexpand(True)
        cmd_entry.connect('changed', lambda w, e=exp, cn=cmd_name:
                          e.set_label(f"Command {cn}: {w.get_text()}"))
        cmd_entry.connect('activate', lambda w, ck=command_key:
                          self._save_opt(config, plugin, ck, w.get_text()))
        fc2 = Gtk.EventControllerFocus()
        fc2.connect('leave', lambda c, e=cmd_entry, ck=command_key:
                    self._save_opt(config, plugin, ck, e.get_text()))
        cmd_entry.add_controller(fc2)
        cmd_row.append(cmd_entry)
        rm = Gtk.Button.new_from_icon_name('list-remove')
        rm.set_tooltip_text('Remove binding')
        rm.connect('clicked', lambda w, cn=cmd_name, f=frame:
                   self._remove_binding(config, plugin, cn, f, parent_box))
        cmd_row.append(rm)
        vbox.append(cmd_row)

        exp.set_child(vbox)
        frame.set_child(exp)
        return frame

    def _change_binding_type(self, config, plugin, cmd_name, new_type):
        """Change binding type (Regular/Repeat/Always) for a command."""
        regular_key = f"binding_{cmd_name}"
        repeat_key = f"repeatable_binding_{cmd_name}"
        always_key = f"always_binding_{cmd_name}"
        sopts = config.get_section_options(plugin.name)

        # Get current binding value
        bind_val = (sopts.get(always_key) or sopts.get(repeat_key)
                    or sopts.get(regular_key) or 'none')

        # Remove old binding keys
        for k in (regular_key, repeat_key, always_key):
            if k in sopts:
                config.remove_option(plugin.name, k)

        # Set new binding key
        new_key = [regular_key, repeat_key, always_key][new_type]
        config.set_option(plugin.name, new_key, bind_val)
        config.save()

    def _remove_binding(self, config, plugin, cmd_name, frame, parent_box):
        """Remove all keys for a command binding."""
        for prefix in ('command_', 'binding_', 'repeatable_binding_',
                        'always_binding_'):
            config.remove_option(plugin.name, prefix + cmd_name)
        config.save()
        parent_box.remove(frame)

    def _add_binding(self, config, plugin, box):
        """Add a new command binding."""
        sopts = config.get_section_options(plugin.name)
        i = 0
        while f"command_new{i}" in sopts:
            i += 1
        name = f"new{i}"
        config.set_option(plugin.name, f"command_{name}", '')
        config.set_option(plugin.name, f"binding_{name}", 'none')
        config.save()
        sopts = config.get_section_options(plugin.name)
        widget = self._make_binding_widget(name, config, plugin, sopts, box)
        child = box.get_first_child()
        last = None
        while child:
            last = child
            child = child.get_next_sibling()
        if last:
            box.insert_child_after(widget, last.get_prev_sibling() if last.get_prev_sibling() else None)
        else:
            box.append(widget)

    # ── Shared helpers ──

    def _add_simple_row(self, box, key, val, config, plugin):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        lbl = Gtk.Label(label=key)
        lbl.set_size_request(LABEL_W, -1)
        lbl.set_xalign(0)
        row.append(lbl)
        entry = Gtk.Entry()
        entry.set_text(val)
        entry.set_hexpand(True)
        entry.connect('activate',
                       lambda w, k=key: self._save_opt(config, plugin, k, w.get_text()))
        row.append(entry)
        box.append(row)

    def _save_opt(self, config, plugin, key, text):
        config.set_option(plugin.name, key, text)
        config.save()

    def _remove_row(self, config, plugin, key, row, parent_box):
        config.remove_option(plugin.name, key)
        config.save()
        parent_box.remove(row)

    def _choose_exec(self, entry):
        dlg = Gtk.FileChooserNative(
            title='Choose Executable', transient_for=self.get_root(),
            action=Gtk.FileChooserAction.OPEN)
        dlg.connect('response', lambda d, r, e=entry: self._on_exec_response(d, r, e))
        dlg.show()

    def _on_exec_response(self, dlg, response, entry):
        if response == Gtk.ResponseType.ACCEPT:
            f = dlg.get_file()
            if f:
                entry.set_text(f.get_path())

    def _run_cmd(self, cmd):
        if cmd:
            try:
                GLib.spawn_command_line_async(cmd)
            except Exception as e:
                print(f"WCM: Failed to run '{cmd}': {e}")

    def _grab_for_entry(self, entry, config, plugin, key):
        win = KeyGrabWindow(self)
        def on_done(w, e=entry, k=key):
            if w.result:
                e.set_text(w.result)
                self._save_opt(config, plugin, k, w.result)
            return False
        win.connect('close-request', on_done)
        win.present()


# ─── Plugin Button (for main page FlowBox) ──────────────────────────────────

class PluginButtonWidget(Gtk.Box):
    """[checkbox] [icon] Name — matches C++ Plugin::init_widget()."""

    def __init__(self, plugin, wcm):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.plugin = plugin
        self.wcm = wcm
        self.set_halign(Gtk.Align.START)

        # Enabled checkbox
        self.check = Gtk.CheckButton()
        self.check.set_active(plugin.enabled)
        if plugin.is_core_plugin or plugin.type == PluginType.WF_SHELL:
            self.check.set_sensitive(False)
        else:
            self.check.connect('toggled', self._on_toggled)
        self.append(self.check)

        # Button (icon + label, flat, no relief)
        btn = Gtk.Button()
        btn.add_css_class('flat')
        btn.set_tooltip_text(plugin.tooltip or '')
        btn.connect('clicked', lambda w: wcm.open_page(plugin))

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        btn_box.set_halign(Gtk.Align.START)

        # Icon — 32px, same as Gtk::ICON_SIZE_DND
        icon_path = find_plugin_icon(plugin.name)
        if not icon_path:
            # Fallback to Wayfire/WCM icon, matching C++ WCM behavior
            icon_path = (find_icon('wcm.svg') or find_icon('wcm.png')
                         or find_icon('wayfire.svg') or find_icon('wayfire.png'))
        if icon_path:
            img = Gtk.Image.new_from_file(icon_path)
            img.set_pixel_size(32)
        else:
            img = Gtk.Image.new_from_icon_name('preferences-system')
            img.set_pixel_size(32)
        btn_box.append(img)

        # Label
        label = Gtk.Label(label=plugin.disp_name or plugin.name)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        btn_box.append(label)

        btn.set_child(btn_box)
        self.append(btn)

    def _on_toggled(self, check):
        self.wcm.set_plugin_enabled(self.plugin, check.get_active())


# ─── Main Page ───────────────────────────────────────────────────────────────

class MainPage(Gtk.ScrolledWindow):
    """Plugin grid with categories — mirrors C++ MainPage using FlowBox."""

    def __init__(self, plugins, wcm):
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)

        self._filter_text = ''
        self._plugin_widgets = []

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)

        self.size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.BOTH)
        self.cat_data = {}

        for i, (cn, icon_name) in enumerate(CATEGORIES):
            # Header
            title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            title_box.set_margin_start(10)
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(24)
            title_box.append(img)
            lbl = Gtk.Label()
            lbl.set_markup(f"<span size='14000'><b>{cn}</b></span>")
            title_box.append(lbl)
            vbox.append(title_box)

            # FlowBox — native reflow on filter!
            fb = Gtk.FlowBox()
            fb.set_selection_mode(Gtk.SelectionMode.NONE)
            fb.set_halign(Gtk.Align.START)
            fb.set_min_children_per_line(3)
            fb.set_max_children_per_line(10)
            fb.set_margin_start(20)
            fb.set_filter_func(self._filter_func)
            vbox.append(fb)

            # Separator
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            if i < len(CATEGORIES) - 1:
                vbox.append(sep)

            self.cat_data[cn] = (title_box, fb, sep)

        # Populate plugins into categories
        for p in plugins:
            ci = get_category_index(p.category)
            cn = CATEGORIES[ci][0]
            _, fb, _ = self.cat_data[cn]

            widget = PluginButtonWidget(p, wcm)
            self.size_group.add_widget(widget)
            fb.append(widget)
            self._plugin_widgets.append(widget)

        self.set_child(vbox)

    def _filter_func(self, child):
        widget = child.get_child()
        if not widget or not hasattr(widget, 'plugin'):
            return True
        if not self._filter_text:
            return True
        p = widget.plugin
        return (self._filter_text in p.name.lower()
                or self._filter_text in p.disp_name.lower()
                or self._filter_text in p.tooltip.lower())

    def set_filter(self, text):
        self._filter_text = text.lower()

        for cn in CATEGORY_NAMES:
            title, fb, sep = self.cat_data[cn]
            fb.invalidate_filter()

        # Update category visibility after filter invalidation
        GLib.idle_add(self._update_cat_visibility)

    def _update_cat_visibility(self):
        for cn in CATEGORY_NAMES:
            title, fb, sep = self.cat_data[cn]
            has_visible = False
            child = fb.get_first_child()
            while child:
                widget = child.get_child()
                if widget and hasattr(widget, 'plugin'):
                    p = widget.plugin
                    if not self._filter_text or (
                        self._filter_text in p.name.lower()
                        or self._filter_text in p.disp_name.lower()
                        or self._filter_text in p.tooltip.lower()):
                        has_visible = True
                        break
                child = child.get_next_sibling()
            title.set_visible(has_visible)
            fb.set_visible(has_visible)
            sep.set_visible(has_visible)
        return False  # don't repeat


# ─── WCM Main Window ────────────────────────────────────────────────────────

class WCM(Gtk.ApplicationWindow):
    """Main Wayfire Config Manager window — mirrors C++ WCM class."""

    def __init__(self, app):
        super().__init__(application=app, title='Wayfire Config Manager')
        self.set_default_size(1000, 580)
        self.set_size_request(750, 550)

        # Icon
        ip = find_app_icon()
        if ip:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(ip)
                self.set_icon_name('wcm')
            except Exception:
                pass

        # Load config
        self.config = WayfireConfigFile(get_config_path())

        # Load plugins
        self.plugins = load_all_metadata()
        if not self.plugins:
            self._gen_from_config()

        enabled = self.config.get_enabled_plugins()
        for p in self.plugins:
            p.enabled = (p.is_core_plugin or p.type == PluginType.WF_SHELL
                         or p.name in enabled)
        self.plugins.sort(key=lambda p: (get_category_index(p.category),
                                         (p.disp_name or p.name).lower()))

        _resolve_icon_dirs()
        found = sum(1 for p in self.plugins if find_plugin_icon(p.name))
        print(f"WCM: Found icons for {found}/{len(self.plugins)} plugins")

        self.current_plugin = None
        self._build_ui()

        # Ctrl+Q to quit
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect('key-pressed', self._on_key)
        self.add_controller(key_ctrl)

    def _gen_from_config(self):
        for sec in self.config.get_sections():
            p = Plugin()
            p.name = sec
            p.disp_name = sec.replace('-', ' ').replace('_', ' ').title()
            p.category = 'Other'
            p.type = PluginType.WAYFIRE
            p.tooltip = f'Configuration for {sec}'
            g = Option(name='General', type=OptionType.GROUP, plugin_name=sec)
            for k, v in self.config.get_section_options(sec).items():
                o = Option()
                o.name = k
                o.disp_name = k.replace('_', ' ').title()
                o.plugin_name = sec
                o.default_value = v
                if v.lower() in ('true', 'false'):
                    o.type = OptionType.BOOL
                    o.default_value = v.lower() == 'true'
                else:
                    try:
                        o.default_value = int(v); o.type = OptionType.INT
                    except ValueError:
                        try:
                            o.default_value = float(v); o.type = OptionType.DOUBLE
                        except ValueError:
                            o.type = OptionType.STRING; o.default_value = v
                g.options.append(o)
            if g.options:
                p.option_groups.append(g)
            self.plugins.append(p)

    def _build_ui(self):
        global_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # ── Left stack ──
        self.left_stack = Gtk.Stack()
        self.left_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.left_stack.set_size_request(250, -1)

        # Main left panel
        main_left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        filter_lbl = Gtk.Label()
        filter_lbl.set_markup("<span size='large'><b>Filter</b></span>")
        filter_lbl.set_margin_top(10)
        filter_lbl.set_margin_start(10)
        main_left.append(filter_lbl)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_margin_start(10)
        self.search_entry.set_margin_end(10)
        self.search_entry.set_margin_top(5)
        self.search_entry.connect('search-changed', self._on_search)
        main_left.append(self.search_entry)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        main_left.append(spacer)

        # Output config button
        out_btn = self._make_button('Configure Outputs', 'video-display')
        out_btn.set_margin_start(10)
        out_btn.set_margin_end(10)
        out_btn.connect('clicked', self._launch_wdisplays)
        main_left.append(out_btn)

        # Close button
        close_btn = self._make_button('Close', 'window-close')
        close_btn.set_margin_start(10)
        close_btn.set_margin_end(10)
        close_btn.set_margin_bottom(10)
        close_btn.connect('clicked', lambda w: self.close())
        main_left.append(close_btn)

        self.left_stack.add_named(main_left, 'main')

        # Plugin left panel
        plugin_left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.plugin_name_label = Gtk.Label()
        self.plugin_name_label.set_wrap(True)
        self.plugin_name_label.set_max_width_chars(15)
        self.plugin_name_label.set_justify(Gtk.Justification.CENTER)
        self.plugin_name_label.set_halign(Gtk.Align.CENTER)
        self.plugin_name_label.set_margin_top(50)
        self.plugin_name_label.set_margin_bottom(25)
        self.plugin_name_label.set_margin_start(10)
        self.plugin_name_label.set_margin_end(10)
        plugin_left.append(self.plugin_name_label)

        self.plugin_desc_label = Gtk.Label()
        self.plugin_desc_label.set_wrap(True)
        self.plugin_desc_label.set_max_width_chars(20)
        self.plugin_desc_label.set_justify(Gtk.Justification.CENTER)
        self.plugin_desc_label.set_halign(Gtk.Align.CENTER)
        self.plugin_desc_label.set_margin_start(10)
        self.plugin_desc_label.set_margin_end(10)
        plugin_left.append(self.plugin_desc_label)

        self.enabled_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.enabled_box.set_halign(Gtk.Align.CENTER)
        self.enabled_box.set_margin_top(25)
        self.enabled_check = Gtk.CheckButton()
        self.enabled_box.append(self.enabled_check)
        self.enabled_label = Gtk.Label(label='Use This Plugin')
        self.enabled_box.append(self.enabled_label)
        self.enabled_check.connect('toggled', self._on_plugin_enable_toggled)
        plugin_left.append(self.enabled_box)

        spacer2 = Gtk.Box()
        spacer2.set_vexpand(True)
        plugin_left.append(spacer2)

        back_btn = self._make_button('Back', 'go-previous')
        back_btn.set_margin_start(10)
        back_btn.set_margin_end(10)
        back_btn.set_margin_bottom(10)
        back_btn.connect('clicked', lambda w: self.open_page(None))
        plugin_left.append(back_btn)

        self.left_stack.add_named(plugin_left, 'plugin')
        global_box.append(self.left_stack)

        # ── Main stack ──
        self.main_stack = Gtk.Stack()
        self.main_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.main_stack.set_hexpand(True)
        self.main_stack.set_vexpand(True)

        self.main_page = MainPage(self.plugins, self)
        self.main_stack.add_named(self.main_page, 'main')

        global_box.append(self.main_stack)
        self.set_child(global_box)

        self.plugin_page = None

    def _make_button(self, text, icon_name):
        """Button with icon + text — mirrors C++ PrettyButton."""
        btn = Gtk.Button()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        box.set_halign(Gtk.Align.CENTER)
        box.append(Gtk.Image.new_from_icon_name(icon_name))
        box.append(Gtk.Label(label=text))
        btn.set_child(box)
        return btn

    def _on_search(self, entry):
        self.main_page.set_filter(entry.get_text())

    def open_page(self, plugin=None):
        """Open a plugin page or go back to main — mirrors C++ WCM::open_page."""
        if plugin:
            self.current_plugin = plugin
            self.enabled_box.set_visible(
                not plugin.is_core_plugin and plugin.type != PluginType.WF_SHELL)
            self.enabled_check.handler_block_by_func(self._on_plugin_enable_toggled)
            self.enabled_check.set_active(plugin.enabled)
            self.enabled_check.handler_unblock_by_func(self._on_plugin_enable_toggled)
            self.plugin_name_label.set_markup(
                f"<span size='12000'><b>{plugin.disp_name or plugin.name}</b></span>")
            self.plugin_desc_label.set_markup(
                f"<span size='10000'><b>{plugin.tooltip or ''}</b></span>")

            if self.plugin_page:
                self.main_stack.remove(self.plugin_page)
            self.plugin_page = PluginPage(plugin, self.config)
            self.main_stack.add_named(self.plugin_page, 'plugin')
            self.main_stack.set_visible_child_name('plugin')
            self.left_stack.set_visible_child_name('plugin')
        else:
            self.main_stack.set_visible_child_name('main')
            self.left_stack.set_visible_child_name('main')
            self.current_plugin = None

    def set_plugin_enabled(self, plugin, enabled):
        """Enable/disable a plugin — mirrors C++ WCM::set_plugin_enabled."""
        if plugin.is_core_plugin or plugin.type == PluginType.WF_SHELL:
            return
        plugin.enabled = enabled
        if enabled:
            self.config.enable_plugin(plugin.name)
        else:
            self.config.disable_plugin(plugin.name)
        self.config.save()

        # Sync checkboxes
        for w in self.main_page._plugin_widgets:
            if w.plugin is plugin:
                w.check.handler_block_by_func(w._on_toggled)
                w.check.set_active(enabled)
                w.check.handler_unblock_by_func(w._on_toggled)
                break

    def _on_plugin_enable_toggled(self, check):
        if self.current_plugin:
            self.set_plugin_enabled(self.current_plugin, check.get_active())

    def _launch_wdisplays(self, btn):
        try:
            subprocess.Popen(['wdisplays'])
        except FileNotFoundError:
            dlg = Gtk.AlertDialog()
            dlg.set_message('Cannot find program wdisplays.')
            dlg.show(self)

    def _on_key(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_q and state & Gdk.ModifierType.CONTROL_MASK:
            self.close()
            return True
        return False


# ─── Application ─────────────────────────────────────────────────────────────

class WCMApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.wayfire.wcm',
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = WCM(self)
        self.window.present()


def main():
    import argparse
    pa = argparse.ArgumentParser(description='Wayfire Config Manager')
    pa.add_argument('-c', '--config', help='Wayfire config file')
    pa.add_argument('-p', '--plugin', help='Plugin to open at launch')
    args = pa.parse_args()

    if args.config:
        os.environ['WAYFIRE_CONFIG_FILE'] = args.config

    app = WCMApp()

    if args.plugin:
        def on_activate_open_plugin(a):
            if app.window:
                for p in app.window.plugins:
                    if p.name == args.plugin:
                        app.window.open_page(p)
                        break
        app.connect('activate', on_activate_open_plugin)

    sys.exit(app.run(sys.argv[:1]))  # don't pass our args to GTK


if __name__ == '__main__':
    main()