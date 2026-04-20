#!/usr/bin/env python3
"""
Wayfire Config Manager (WCM) — Python/PyQt5 Edition

A faithful port of the C++/GTK3 WCM to Python/PyQt5.
"""

import sys
import os
import subprocess
import glob
import traceback

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QScrollArea, QFrame,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox,
    QColorDialog, QTabWidget, QSizePolicy, QGridLayout,
    QGroupBox, QToolButton, QFileDialog, QMessageBox, QDialog,
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap, QColor, QFont, QKeySequence

from config_backend import WayfireConfigFile
from metadata import (
    load_all_metadata, load_metadata_from_dir, find_metadata_dirs,
    Plugin, Option, OptionType, PluginType,
)


# ─── Color parsing (handles both hex #RRGGBBAA and float R G B A) ────────────

def parse_color(color_str):
    """Parse a wayfire color string into QColor. Handles #hex and float formats."""
    if not color_str:
        return QColor(0, 0, 0, 255)
    color_str = color_str.strip()
    if color_str.startswith('#'):
        h = color_str[1:]
        try:
            if len(h) == 8:  # #RRGGBBAA — wayfire format
                r = int(h[0:2], 16)
                g = int(h[2:4], 16)
                b = int(h[4:6], 16)
                a = int(h[6:8], 16)
                return QColor(r, g, b, a)
            elif len(h) == 6:  # #RRGGBB
                return QColor(int(h[0:2], 16), int(h[2:4], 16),
                              int(h[4:6], 16), 255)
        except ValueError:
            pass
        return QColor(0, 0, 0, 255)
    # Float format: "R G B A"
    parts = color_str.split()
    try:
        r = min(max(float(parts[0]), 0), 1) if len(parts) > 0 else 0
        g = min(max(float(parts[1]), 0), 1) if len(parts) > 1 else 0
        b = min(max(float(parts[2]), 0), 1) if len(parts) > 2 else 0
        a = min(max(float(parts[3]), 0), 1) if len(parts) > 3 else 1
        return QColor.fromRgbF(r, g, b, a)
    except (ValueError, IndexError):
        return QColor(0, 0, 0, 255)


def color_to_str(qcolor):
    """Convert QColor back to wayfire float format."""
    return (f"{qcolor.redF():.4f} {qcolor.greenF():.4f} "
            f"{qcolor.blueF():.4f} {qcolor.alphaF():.4f}")


# ─── Key names ───────────────────────────────────────────────────────────────

_QT_KEY_TO_LINUX = {
    Qt.Key_Escape: 'KEY_ESC', Qt.Key_1: 'KEY_1', Qt.Key_2: 'KEY_2',
    Qt.Key_3: 'KEY_3', Qt.Key_4: 'KEY_4', Qt.Key_5: 'KEY_5',
    Qt.Key_6: 'KEY_6', Qt.Key_7: 'KEY_7', Qt.Key_8: 'KEY_8',
    Qt.Key_9: 'KEY_9', Qt.Key_0: 'KEY_0', Qt.Key_Minus: 'KEY_MINUS',
    Qt.Key_Equal: 'KEY_EQUAL', Qt.Key_Backspace: 'KEY_BACKSPACE',
    Qt.Key_Tab: 'KEY_TAB', Qt.Key_Q: 'KEY_Q', Qt.Key_W: 'KEY_W',
    Qt.Key_E: 'KEY_E', Qt.Key_R: 'KEY_R', Qt.Key_T: 'KEY_T',
    Qt.Key_Y: 'KEY_Y', Qt.Key_U: 'KEY_U', Qt.Key_I: 'KEY_I',
    Qt.Key_O: 'KEY_O', Qt.Key_P: 'KEY_P', Qt.Key_BracketLeft: 'KEY_LEFTBRACE',
    Qt.Key_BracketRight: 'KEY_RIGHTBRACE', Qt.Key_Return: 'KEY_ENTER',
    Qt.Key_Enter: 'KEY_ENTER', Qt.Key_A: 'KEY_A', Qt.Key_S: 'KEY_S',
    Qt.Key_D: 'KEY_D', Qt.Key_F: 'KEY_F', Qt.Key_G: 'KEY_G',
    Qt.Key_H: 'KEY_H', Qt.Key_J: 'KEY_J', Qt.Key_K: 'KEY_K',
    Qt.Key_L: 'KEY_L', Qt.Key_Semicolon: 'KEY_SEMICOLON',
    Qt.Key_Apostrophe: 'KEY_APOSTROPHE', Qt.Key_QuoteLeft: 'KEY_GRAVE',
    Qt.Key_Backslash: 'KEY_BACKSLASH', Qt.Key_Z: 'KEY_Z', Qt.Key_X: 'KEY_X',
    Qt.Key_C: 'KEY_C', Qt.Key_V: 'KEY_V', Qt.Key_B: 'KEY_B',
    Qt.Key_N: 'KEY_N', Qt.Key_M: 'KEY_M', Qt.Key_Comma: 'KEY_COMMA',
    Qt.Key_Period: 'KEY_DOT', Qt.Key_Slash: 'KEY_SLASH',
    Qt.Key_Space: 'KEY_SPACE', Qt.Key_F1: 'KEY_F1', Qt.Key_F2: 'KEY_F2',
    Qt.Key_F3: 'KEY_F3', Qt.Key_F4: 'KEY_F4', Qt.Key_F5: 'KEY_F5',
    Qt.Key_F6: 'KEY_F6', Qt.Key_F7: 'KEY_F7', Qt.Key_F8: 'KEY_F8',
    Qt.Key_F9: 'KEY_F9', Qt.Key_F10: 'KEY_F10', Qt.Key_F11: 'KEY_F11',
    Qt.Key_F12: 'KEY_F12', Qt.Key_Home: 'KEY_HOME', Qt.Key_Up: 'KEY_UP',
    Qt.Key_PageUp: 'KEY_PAGEUP', Qt.Key_Left: 'KEY_LEFT',
    Qt.Key_Right: 'KEY_RIGHT', Qt.Key_End: 'KEY_END',
    Qt.Key_Down: 'KEY_DOWN', Qt.Key_PageDown: 'KEY_PAGEDOWN',
    Qt.Key_Insert: 'KEY_INSERT', Qt.Key_Delete: 'KEY_DELETE',
    Qt.Key_Pause: 'KEY_PAUSE', Qt.Key_Print: 'KEY_SYSRQ',
    Qt.Key_ScrollLock: 'KEY_SCROLLLOCK', Qt.Key_CapsLock: 'KEY_CAPSLOCK',
    Qt.Key_NumLock: 'KEY_NUMLOCK',
    Qt.Key_VolumeUp: 'KEY_VOLUMEUP', Qt.Key_VolumeDown: 'KEY_VOLUMEDOWN',
    Qt.Key_VolumeMute: 'KEY_MUTE',
    Qt.Key_MediaPlay: 'KEY_PLAYPAUSE', Qt.Key_MediaStop: 'KEY_STOPCD',
    Qt.Key_MediaPrevious: 'KEY_PREVIOUSSONG', Qt.Key_MediaNext: 'KEY_NEXTSONG',
}

_MODIFIER_KEYS = {
    Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta,
    Qt.Key_Super_L, Qt.Key_Super_R, Qt.Key_AltGr,
}


class KeyGrabDialog(QDialog):
    """Dialog to capture a key/button binding — mirrors C++ KeyEntry::grab_key."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Waiting for Binding')
        self.setModal(True)
        self.setFixedSize(350, 120)
        self.result_str = ''
        self._mods = set()

        layout = QVBoxLayout(self)
        self._label = QLabel('Press a key combination...\n(Press Escape to cancel)')
        self._label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._label)

    def _mod_string(self):
        parts = []
        if Qt.Key_Super_L in self._mods or Qt.Key_Super_R in self._mods or Qt.Key_Meta in self._mods:
            parts.append('<super>')
        if Qt.Key_Control in self._mods:
            parts.append('<ctrl>')
        if Qt.Key_Alt in self._mods or Qt.Key_AltGr in self._mods:
            parts.append('<alt>')
        if Qt.Key_Shift in self._mods:
            parts.append('<shift>')
        return ' '.join(parts)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape and not self._mods:
            self.reject()
            return
        if key in _MODIFIER_KEYS:
            self._mods.add(key)
            ms = self._mod_string()
            self._label.setText(ms if ms else '(No modifiers pressed)')
            return
        # Non-modifier key pressed — build the binding string
        key_name = _QT_KEY_TO_LINUX.get(key, f'KEY_{event.text().upper()}')
        if not key_name or key_name == 'KEY_':
            key_name = QKeySequence(key).toString()
            if key_name:
                key_name = 'KEY_' + key_name.upper()
        mod = self._mod_string()
        self.result_str = (mod + ' ' + key_name).strip()
        self.accept()

    def keyReleaseEvent(self, event):
        key = event.key()
        self._mods.discard(key)
        ms = self._mod_string()
        self._label.setText(ms if ms else 'Press a key combination...')

    def mousePressEvent(self, event):
        btn_map = {
            Qt.LeftButton: 'BTN_LEFT',
            Qt.MiddleButton: 'BTN_MIDDLE',
            Qt.RightButton: 'BTN_RIGHT',
            Qt.BackButton: 'BTN_SIDE',
            Qt.ForwardButton: 'BTN_EXTRA',
        }
        btn_name = btn_map.get(event.button())
        if btn_name:
            mod = self._mod_string()
            self.result_str = (mod + ' ' + btn_name).strip()
            self.accept()




# ─── Icon helpers ────────────────────────────────────────────────────────────
#
# Replicates the C++ WCM::find_icon() logic exactly:
#   1. $XDG_DATA_HOME/wayfire/icons/<name>
#   2. WAYFIRE_ICONDIR/<name>    (from pkg-config --variable=icondir wayfire)
#   3. WCM_ICONDIR/<name>       (from <wcm-prefix>/share/wcm/icons)
#
# The C++ version has these paths compiled in. We derive them at runtime
# from pkg-config and the installed binary locations so it works no matter
# where things are installed (/usr, /usr/local, /opt/wayfire, ~/.local, etc).

import shutil

_wcm_icon_dir = None   # equivalent to WCM_ICONDIR
_wf_icon_dir = None    # equivalent to WAYFIRE_ICONDIR
_xdg_icon_dir = None   # $XDG_DATA_HOME/wayfire/icons
_icon_dirs_resolved = False


def _resolve_icon_dirs():
    """One-time resolution of the three icon directories, same as C++ WCM."""
    global _xdg_icon_dir, _wf_icon_dir, _wcm_icon_dir, _icon_dirs_resolved
    if _icon_dirs_resolved:
        return
    _icon_dirs_resolved = True

    # ── 1. XDG_DATA_HOME/wayfire/icons ──
    xdg = os.environ.get('XDG_DATA_HOME', '')
    if not xdg:
        home = os.environ.get('HOME', os.path.expanduser('~'))
        xdg = os.path.join(home, '.local', 'share')
    _xdg_icon_dir = os.path.join(xdg, 'wayfire', 'icons')

    # ── 2. WAYFIRE_ICONDIR from pkg-config ──
    try:
        r = subprocess.run(['pkg-config', '--variable=icondir', 'wayfire'],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            _wf_icon_dir = r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # ── 3. WCM_ICONDIR = <wcm-prefix>/share/wcm/icons ──
    # Derive from the installed wcm binary, just like the C++ version
    # bakes it in from the meson install prefix.
    wcm_bin = shutil.which('wcm')
    if wcm_bin:
        # /opt/wayfire/bin/wcm → prefix = /opt/wayfire
        prefix = os.path.dirname(os.path.dirname(os.path.realpath(wcm_bin)))
        _wcm_icon_dir = os.path.join(prefix, 'share', 'wcm', 'icons')

    # Also try deriving from wayfire binary if wcm not found
    if not _wcm_icon_dir or not os.path.isdir(_wcm_icon_dir):
        wf_bin = shutil.which('wayfire')
        if wf_bin:
            prefix = os.path.dirname(os.path.dirname(os.path.realpath(wf_bin)))
            d = os.path.join(prefix, 'share', 'wcm', 'icons')
            if os.path.isdir(d):
                _wcm_icon_dir = d

    # If still no WCM_ICONDIR, try deriving from wayfire pkg-config prefix
    if not _wcm_icon_dir or not os.path.isdir(_wcm_icon_dir):
        try:
            r = subprocess.run(['pkg-config', '--variable=prefix', 'wayfire'],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                d = os.path.join(r.stdout.strip(), 'share', 'wcm', 'icons')
                if os.path.isdir(d):
                    _wcm_icon_dir = d
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Also look relative to this script (for development)
    if not _wcm_icon_dir or not os.path.isdir(_wcm_icon_dir):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for rel in ('icons/plugins', 'icons', '../icons/plugins',
                    '../wcm/icons/plugins', '../wcm/icons'):
            d = os.path.normpath(os.path.join(script_dir, rel))
            if os.path.isdir(d) and os.path.isfile(
                    os.path.join(d, 'plugin-core.svg')):
                _wcm_icon_dir = d
                break

    # Print diagnostics
    print(f"WCM: XDG icon dir: {_xdg_icon_dir}"
          f" ({'found' if _xdg_icon_dir and os.path.isdir(_xdg_icon_dir) else 'not present'})")
    print(f"WCM: WAYFIRE_ICONDIR: {_wf_icon_dir or '(not found)'}")
    print(f"WCM: WCM_ICONDIR: {_wcm_icon_dir or '(not found)'}")


def find_icon(name):
    """
    Find an icon file by name — exact replica of C++ WCM::find_icon().

    Args:
        name: icon filename, e.g. "plugin-move.svg" or "wcm.svg"

    Returns:
        Full path to the icon file, or empty string if not found.
    """
    _resolve_icon_dirs()

    # 1. User XDG dir (highest priority)
    if _xdg_icon_dir:
        path = os.path.join(_xdg_icon_dir, name)
        if os.path.isfile(path):
            return path

    # 2. WAYFIRE_ICONDIR
    if _wf_icon_dir:
        path = os.path.join(_wf_icon_dir, name)
        if os.path.isfile(path):
            return path

    # 3. WCM_ICONDIR (final fallback — same as C++ which always returns this)
    if _wcm_icon_dir:
        path = os.path.join(_wcm_icon_dir, name)
        if os.path.isfile(path):
            return path

    return ''


def find_plugin_icon(plugin_name):
    """Find plugin-<name>.svg — convenience wrapper."""
    return find_icon(f"plugin-{plugin_name}.svg") or None


def find_app_icon():
    """Find wcm.svg application icon."""
    return find_icon('wcm.svg') or None


def load_icon_pixmap(path, size):
    """Load an SVG/PNG icon at the given size."""
    if path and os.path.isfile(path):
        icon = QIcon(path)
        if not icon.isNull():
            pm = icon.pixmap(size, size)
            if not pm.isNull():
                return pm
    return QIcon.fromTheme('application-x-executable').pixmap(size, size)

# ─── Categories ──────────────────────────────────────────────────────────────

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
    for i, (name, _) in enumerate(CATEGORIES):
        if name == cat:
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
    if os.path.isfile(p):
        return p
    return os.path.join(ch, 'wayfire.ini')


# ─── Option Widgets ──────────────────────────────────────────────────────────

LABEL_W = 180


class OptionWidget(QWidget):
    """Widget for a single plugin option."""

    def __init__(self, option, config, plugin, parent=None):
        super().__init__(parent)
        self.option = option
        self.config = config
        self.plugin = plugin
        self._block = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)

        lbl = QLabel(option.disp_name or option.name)
        lbl.setToolTip(option.tooltip or '')
        lbl.setFixedWidth(LABEL_W)
        lay.addWidget(lbl)

        current = config.get_option(plugin.name, option.name)
        self._build(lay, option, current)

        rb = QToolButton()
        rb.setIcon(QIcon.fromTheme('edit-clear', QIcon.fromTheme('edit-undo')))
        rb.setToolTip('Reset to default')
        rb.setFocusPolicy(Qt.NoFocus)
        rb.setAutoRaise(True)
        rb.clicked.connect(self._reset)
        lay.addWidget(rb)

    def _build(self, lay, opt, cur):
        ot = opt.type

        if ot == OptionType.INT:
            if opt.int_labels:
                self.ed = QComboBox()
                for lb, v in opt.int_labels:
                    self.ed.addItem(lb, v)
                cv = _int(cur, opt.default_value)
                for i, (_, v) in enumerate(opt.int_labels):
                    if v == cv:
                        self.ed.setCurrentIndex(i)
                        break
                self.ed.currentIndexChanged.connect(
                    lambda: self._save(str(self.ed.currentData())))
            else:
                self.ed = QSpinBox()
                self.ed.setRange(int(opt.min_val),
                                 int(min(opt.max_val, 2**31 - 1)))
                self.ed.setValue(_int(cur, opt.default_value))
                self.ed.valueChanged.connect(lambda v: self._save(str(v)))
            lay.addWidget(self.ed, 1)

        elif ot == OptionType.DOUBLE:
            self.ed = QDoubleSpinBox()
            self.ed.setRange(max(opt.min_val, -1e15),
                             min(opt.max_val, 1e15))
            dec = len(str(opt.precision).split('.')[-1]) \
                if '.' in str(opt.precision) else 3
            self.ed.setDecimals(dec)
            self.ed.setSingleStep(opt.precision)
            try:
                v = float(cur) if cur else float(opt.default_value)
            except (ValueError, TypeError):
                v = 0.0
            self.ed.setValue(v)
            self.ed.valueChanged.connect(lambda v: self._save(str(v)))
            lay.addWidget(self.ed, 1)

        elif ot == OptionType.BOOL:
            self.ed = QCheckBox()
            if cur is not None:
                self.ed.setChecked(cur.lower() in ('true', '1', 'yes'))
            else:
                self.ed.setChecked(bool(opt.default_value))
            self.ed.toggled.connect(
                lambda c: self._save('true' if c else 'false'))
            lay.addWidget(self.ed, 1)

        elif ot in (OptionType.STRING, OptionType.GESTURE):
            if opt.str_labels:
                self.ed = QComboBox()
                for lb, v in opt.str_labels:
                    self.ed.addItem(lb, v)
                cv = cur if cur is not None else str(opt.default_value or '')
                for i, (_, v) in enumerate(opt.str_labels):
                    if v == cv:
                        self.ed.setCurrentIndex(i)
                        break
                self.ed.currentIndexChanged.connect(
                    lambda: self._save(str(self.ed.currentData() or '')))
            else:
                self.ed = QLineEdit()
                self.ed.setText(cur if cur is not None
                                else str(opt.default_value or ''))
                self.ed.editingFinished.connect(
                    lambda: self._save(self.ed.text()))
                if 'directory' in opt.hints:
                    b = QToolButton()
                    b.setIcon(QIcon.fromTheme('folder-open'))
                    b.setFocusPolicy(Qt.NoFocus)
                    b.clicked.connect(self._choose_dir)
                    lay.addWidget(b)
                if 'file' in opt.hints:
                    b = QToolButton()
                    b.setIcon(QIcon.fromTheme('document-open'))
                    b.setFocusPolicy(Qt.NoFocus)
                    b.clicked.connect(self._choose_file)
                    lay.addWidget(b)
            lay.addWidget(self.ed, 1)

        elif ot in (OptionType.KEY, OptionType.BUTTON, OptionType.ACTIVATOR):
            # Text entry + grab button (like C++ KeyEntry)
            self.ed = QLineEdit()
            self.ed.setText(cur if cur is not None
                            else str(opt.default_value or ''))
            self.ed.editingFinished.connect(
                lambda: self._save(self.ed.text()))
            lay.addWidget(self.ed, 1)

            grab_btn = QToolButton()
            grab_btn.setText('...')
            grab_btn.setToolTip('Grab key/button binding')
            grab_btn.setFocusPolicy(Qt.NoFocus)
            grab_btn.clicked.connect(self._grab_key)
            lay.addWidget(grab_btn)

        elif ot == OptionType.COLOR:
            self._color_btn = QPushButton()
            self._color_btn.setFocusPolicy(Qt.NoFocus)
            cs = cur if cur is not None \
                else str(opt.default_value or '0.0 0.0 0.0 1.0')
            self._set_color_btn(cs)
            self._color_btn.clicked.connect(self._choose_color)
            self.ed = self._color_btn
            lay.addWidget(self._color_btn, 1)

        elif ot == OptionType.ANIMATION:
            dur, easing = _parse_anim(
                cur if cur is not None
                else str(opt.default_value or '300ms linear'))
            self._aspin = QSpinBox()
            self._aspin.setRange(int(opt.min_val),
                                 int(min(opt.max_val, 100000)))
            self._aspin.setValue(dur)
            self._aspin.setSuffix(' ms')
            self._acombo = QComboBox()
            for e in ('linear', 'circle', 'sigmoid'):
                self._acombo.addItem(e)
            idx = self._acombo.findText(easing)
            if idx >= 0:
                self._acombo.setCurrentIndex(idx)
            self._aspin.valueChanged.connect(self._save_anim)
            self._acombo.currentTextChanged.connect(self._save_anim)
            lay.addWidget(self._aspin)
            lay.addWidget(self._acombo)
            self.ed = self._aspin

        else:
            # Fallback for unknown types — just a text field
            self.ed = QLineEdit()
            self.ed.setText(cur if cur is not None
                            else str(opt.default_value or ''))
            self.ed.editingFinished.connect(
                lambda: self._save(self.ed.text()))
            lay.addWidget(self.ed, 1)

    def _save(self, val):
        if self._block:
            return
        self.config.set_option(self.plugin.name, self.option.name, str(val))
        self.config.save()

    def _save_anim(self, *_):
        self._save(f"{self._aspin.value()}ms {self._acombo.currentText()}")

    def _grab_key(self):
        dlg = KeyGrabDialog(self)
        if dlg.exec_() == QDialog.Accepted and dlg.result_str:
            self.ed.setText(dlg.result_str)
            self._save(dlg.result_str)

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, 'Select Directory')
        if d:
            self.ed.setText(d)
            self._save(d)

    def _choose_file(self):
        f, _ = QFileDialog.getOpenFileName(self, 'Select File')
        if f:
            self.ed.setText(f)
            self._save(f)

    def _choose_color(self):
        cs = self.config.get_option(self.plugin.name, self.option.name) \
            or str(self.option.default_value or '0.0 0.0 0.0 1.0')
        initial = parse_color(cs)
        c = QColorDialog.getColor(
            initial, self, 'Choose Color', QColorDialog.ShowAlphaChannel)
        if c.isValid():
            s = color_to_str(c)
            self._save(s)
            self._set_color_btn(s)

    def _set_color_btn(self, cs):
        c = parse_color(cs)
        self._color_btn.setStyleSheet(
            f"background-color: {c.name(QColor.HexArgb)};"
            " min-width:60px; min-height:20px; border:1px solid gray;")

    def _reset(self):
        d = self.option.default_value
        self._block = True
        try:
            if self.option.type == OptionType.INT:
                if self.option.int_labels:
                    for i, (_, v) in enumerate(self.option.int_labels):
                        if v == d:
                            self.ed.setCurrentIndex(i)
                else:
                    self.ed.setValue(d if isinstance(d, int) else 0)
            elif self.option.type == OptionType.DOUBLE:
                self.ed.setValue(d if isinstance(d, float) else 0.0)
            elif self.option.type == OptionType.BOOL:
                self.ed.setChecked(bool(d))
            elif self.option.type in (OptionType.STRING, OptionType.KEY,
                                      OptionType.BUTTON, OptionType.ACTIVATOR,
                                      OptionType.GESTURE):
                if self.option.str_labels:
                    for i, (_, v) in enumerate(self.option.str_labels):
                        if v == str(d or ''):
                            self.ed.setCurrentIndex(i)
                else:
                    self.ed.setText(str(d or ''))
            elif self.option.type == OptionType.COLOR:
                self._set_color_btn(str(d or '0.0 0.0 0.0 1.0'))
            elif self.option.type == OptionType.ANIMATION:
                dur, easing = _parse_anim(str(d or '300ms linear'))
                self._aspin.setValue(dur)
                idx = self._acombo.findText(easing)
                if idx >= 0:
                    self._acombo.setCurrentIndex(idx)
        finally:
            self._block = False
        self._save(str(d or ''))


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


class SubgroupWidget(QGroupBox):
    def __init__(self, sg, config, plugin, parent=None):
        super().__init__(sg.name or 'Options', parent)
        self.setCheckable(True)
        self.setChecked(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        for opt in sg.options:
            if opt.hidden:
                continue
            try:
                lay.addWidget(OptionWidget(opt, config, plugin))
            except Exception as e:
                lay.addWidget(QLabel(f"⚠ {opt.name}: {e}"))


# ─── Plugin Page ─────────────────────────────────────────────────────────────

class PluginPage(QTabWidget):
    """Tabbed option groups for a plugin."""

    def __init__(self, plugin, config, parent=None):
        super().__init__(parent)

        for group in plugin.option_groups:
            if group.type != OptionType.GROUP or group.hidden:
                continue

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            container = QWidget()
            vl = QVBoxLayout(container)
            vl.setContentsMargins(10, 10, 10, 10)
            vl.setSpacing(4)

            for opt in group.options:
                if opt.hidden:
                    continue
                try:
                    if opt.type == OptionType.SUBGROUP and opt.options:
                        vl.addWidget(SubgroupWidget(opt, config, plugin))
                    elif opt.type == OptionType.DYNAMIC_LIST:
                        w = self._make_dynlist(opt, config, plugin)
                        if w:
                            vl.addWidget(w)
                    elif opt.type != OptionType.GROUP:
                        vl.addWidget(OptionWidget(opt, config, plugin))
                except Exception as e:
                    # Don't let one bad option kill the whole page
                    err = QLabel(f"⚠ Error loading '{opt.name}': {e}")
                    err.setStyleSheet("color: red;")
                    vl.addWidget(err)
                    traceback.print_exc()

            vl.addStretch(1)
            scroll.setWidget(container)
            self.addTab(scroll, group.name or 'General')

    def _make_dynlist(self, option, config, plugin):
        frame = QGroupBox(option.disp_name or option.name)
        lay = QVBoxLayout(frame)
        sopts = config.get_section_options(plugin.name)

        # Determine prefixes from entries
        prefixes = [e.prefix for e in option.entries] if option.entries else []

        if prefixes:
            # Compound option: show all matching keys
            for key, val in sopts.items():
                if any(key.startswith(p) for p in prefixes if p):
                    row = QHBoxLayout()
                    lbl = QLabel(key)
                    lbl.setFixedWidth(LABEL_W)
                    entry = QLineEdit(val)
                    entry.editingFinished.connect(
                        lambda e=entry, k=key:
                            self._save_dyn(config, plugin, k, e.text()))
                    row.addWidget(lbl)
                    row.addWidget(entry, 1)
                    rm = QToolButton()
                    rm.setIcon(QIcon.fromTheme('list-remove'))
                    rm.setFocusPolicy(Qt.NoFocus)
                    rm.clicked.connect(
                        lambda _, k=key: self._remove_dyn(config, plugin, k))
                    row.addWidget(rm)
                    w = QWidget()
                    w.setLayout(row)
                    lay.addWidget(w)
        elif option.name == 'autostart':
            for key, val in sopts.items():
                if key.startswith('autostart') and key != 'autostart_wf_shell':
                    row = QHBoxLayout()
                    lbl = QLabel(key)
                    lbl.setFixedWidth(LABEL_W)
                    entry = QLineEdit(val)
                    entry.editingFinished.connect(
                        lambda e=entry, k=key:
                            self._save_dyn(config, plugin, k, e.text()))
                    row.addWidget(lbl)
                    row.addWidget(entry, 1)
                    rm = QToolButton()
                    rm.setIcon(QIcon.fromTheme('list-remove'))
                    rm.setFocusPolicy(Qt.NoFocus)
                    rm.clicked.connect(
                        lambda _, k=key: self._remove_dyn(config, plugin, k))
                    row.addWidget(rm)
                    w = QWidget()
                    w.setLayout(row)
                    lay.addWidget(w)
        else:
            lay.addWidget(QLabel(f"Dynamic list: {option.name}"))

        return frame

    def _save_dyn(self, config, plugin, key, text):
        config.set_option(plugin.name, key, text)
        config.save()

    def _remove_dyn(self, config, plugin, key):
        config.remove_option(plugin.name, key)
        config.save()


# ─── Plugin Button ───────────────────────────────────────────────────────────

class PluginButton(QWidget):
    """[checkbox] [icon] Name — flat, compact, matching original GTK WCM."""
    clicked = pyqtSignal(object)
    enabled_toggled = pyqtSignal(object, bool)
    ICON_SZ = 32  # Gtk::ICON_SIZE_DND = 32x32

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(38)
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(4)

        self.check = QCheckBox()
        self.check.setChecked(plugin.enabled)
        self.check.setFocusPolicy(Qt.NoFocus)
        if plugin.is_core_plugin or plugin.type == PluginType.WF_SHELL:
            self.check.setEnabled(False)
        else:
            self.check.toggled.connect(
                lambda c: self.enabled_toggled.emit(self.plugin, c))
        lay.addWidget(self.check)

        ic = QLabel()
        ic.setFocusPolicy(Qt.NoFocus)
        ip = find_plugin_icon(plugin.name)
        ic.setPixmap(load_icon_pixmap(ip, self.ICON_SZ))
        ic.setFixedSize(self.ICON_SZ + 2, self.ICON_SZ + 2)
        lay.addWidget(ic)

        nm = QLabel(plugin.disp_name or plugin.name)
        nm.setToolTip(plugin.tooltip or '')
        nm.setFocusPolicy(Qt.NoFocus)
        lay.addWidget(nm)
        lay.addStretch()

    def mousePressEvent(self, ev):
        child = self.childAt(ev.pos())
        if child is not self.check:
            self.clicked.emit(self.plugin)
        else:
            super().mousePressEvent(ev)


# ─── Main Page ───────────────────────────────────────────────────────────────

class MainPage(QScrollArea):
    plugin_clicked = pyqtSignal(object)
    plugin_enabled = pyqtSignal(object, bool)
    COLS = 3

    def __init__(self, plugins, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.plugins = plugins
        self.plugin_buttons = []
        # buttons grouped by category name for reflow
        self.cat_buttons = {cn: [] for cn, _ in CATEGORIES}

        container = QWidget()
        self.ml = QVBoxLayout(container)
        self.ml.setContentsMargins(10, 5, 10, 5)
        self.ml.setSpacing(5)
        self.cat_w = {}

        for i, (cn, icon) in enumerate(CATEGORIES):
            h = QWidget()
            hl = QHBoxLayout(h)
            hl.setContentsMargins(0, 8, 0, 2)
            hl.setSpacing(6)
            ic = QLabel()
            ic.setPixmap(QIcon.fromTheme(icon).pixmap(22, 22))
            hl.addWidget(ic)
            lb = QLabel(f"<b>{cn}</b>")
            f = lb.font()
            f.setPointSize(f.pointSize() + 2)
            lb.setFont(f)
            hl.addWidget(lb)
            hl.addStretch()
            self.ml.addWidget(h)

            gw = QWidget()
            grid = QGridLayout(gw)
            grid.setContentsMargins(20, 0, 0, 0)
            grid.setSpacing(2)
            self.ml.addWidget(gw)

            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFrameShadow(QFrame.Sunken)
            if i < len(CATEGORIES) - 1:
                self.ml.addWidget(sep)

            self.cat_w[cn] = [h, gw, grid, sep]

        for p in plugins:
            ci = get_category_index(p.category)
            cn = CATEGORIES[ci][0]

            btn = PluginButton(p)
            btn.clicked.connect(self.plugin_clicked.emit)
            btn.enabled_toggled.connect(self.plugin_enabled.emit)
            self.plugin_buttons.append(btn)
            self.cat_buttons[cn].append(btn)

        # Initial layout
        self._reflow_all()

        self.ml.addStretch(1)
        self.setWidget(container)

    def _reflow_category(self, cn, visible_btns):
        """Remove all widgets from a category grid and re-add only visible ones."""
        _, _, grid, _ = self.cat_w[cn]
        # Remove all from grid (don't delete — just take out of layout)
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
        # Re-add visible buttons in compact grid
        for i, btn in enumerate(visible_btns):
            grid.addWidget(btn, i // self.COLS, i % self.COLS)
            btn.setVisible(True)

    def _reflow_all(self):
        """Reflow all categories with all buttons."""
        for cn in CATEGORY_NAMES:
            self._reflow_category(cn, self.cat_buttons[cn])

    def set_filter(self, text):
        text = text.lower()
        for cn in CATEGORY_NAMES:
            btns = self.cat_buttons[cn]
            if text:
                visible = [b for b in btns
                           if text in b.plugin.name.lower()
                           or text in b.plugin.disp_name.lower()
                           or text in b.plugin.tooltip.lower()]
            else:
                visible = btns

            self._reflow_category(cn, visible)

            h, gw, _, sep = self.cat_w[cn]
            has_visible = len(visible) > 0
            h.setVisible(has_visible)
            gw.setVisible(has_visible)
            sep.setVisible(has_visible)


# ─── Left Panel ──────────────────────────────────────────────────────────────

class LeftPanel(QWidget):
    back_clicked = pyqtSignal()
    close_clicked = pyqtSignal()
    plugin_enabled_changed = pyqtSignal(object, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.stack = QStackedWidget()
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(self.stack)

        # Main panel
        self.main_panel = QWidget()
        mp = QVBoxLayout(self.main_panel)
        mp.setContentsMargins(8, 8, 8, 8)
        lbl = QLabel('<b>Filter</b>')
        f = lbl.font(); f.setPointSize(f.pointSize() + 2); lbl.setFont(f)
        mp.addWidget(lbl)
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText('Search plugins...')
        self.search_entry.setClearButtonEnabled(True)
        mp.addWidget(self.search_entry)
        mp.addStretch(1)
        ob = QPushButton(' Configure Outputs')
        ob.setIcon(QIcon.fromTheme('video-display'))
        ob.setFocusPolicy(Qt.NoFocus)
        ob.clicked.connect(self._launch_wd)
        mp.addWidget(ob)
        cb = QPushButton(' Close')
        cb.setIcon(QIcon.fromTheme('window-close'))
        cb.setFocusPolicy(Qt.NoFocus)
        cb.clicked.connect(self.close_clicked.emit)
        mp.addWidget(cb)
        self.stack.addWidget(self.main_panel)

        # Plugin panel
        self.plugin_panel = QWidget()
        pp = QVBoxLayout(self.plugin_panel)
        pp.setContentsMargins(8, 8, 8, 8)
        self.pname = QLabel()
        self.pname.setWordWrap(True)
        self.pname.setAlignment(Qt.AlignCenter)
        f2 = self.pname.font(); f2.setPointSize(f2.pointSize()+2)
        f2.setBold(True); self.pname.setFont(f2)
        self.pname.setContentsMargins(5, 30, 5, 10)
        pp.addWidget(self.pname)
        self.pdesc = QLabel()
        self.pdesc.setWordWrap(True)
        self.pdesc.setAlignment(Qt.AlignCenter)
        self.pdesc.setContentsMargins(5, 0, 5, 5)
        pp.addWidget(self.pdesc)
        self.ebox = QWidget()
        eb = QHBoxLayout(self.ebox)
        eb.setAlignment(Qt.AlignCenter)
        self.echeck = QCheckBox('Use This Plugin')
        self.echeck.toggled.connect(self._on_en)
        eb.addWidget(self.echeck)
        self.ebox.setContentsMargins(0, 15, 0, 0)
        pp.addWidget(self.ebox)
        pp.addStretch(1)
        bb = QPushButton(' Back')
        bb.setIcon(QIcon.fromTheme('go-previous'))
        bb.setFocusPolicy(Qt.NoFocus)
        bb.clicked.connect(self.back_clicked.emit)
        pp.addWidget(bb)
        self.stack.addWidget(self.plugin_panel)
        self._cp = None

    def show_main(self):
        self.stack.setCurrentWidget(self.main_panel)

    def show_plugin(self, p):
        self._cp = p
        self.pname.setText(p.disp_name or p.name)
        self.pdesc.setText(p.tooltip or '')
        self.echeck.blockSignals(True)
        self.echeck.setChecked(p.enabled)
        self.echeck.blockSignals(False)
        self.ebox.setVisible(
            not p.is_core_plugin and p.type != PluginType.WF_SHELL)
        self.stack.setCurrentWidget(self.plugin_panel)

    def _on_en(self, c):
        if self._cp:
            self.plugin_enabled_changed.emit(self._cp, c)

    def _launch_wd(self):
        try:
            subprocess.Popen(['wdisplays'])
        except FileNotFoundError:
            QMessageBox.warning(self, 'Not Found',
                                'Cannot find program wdisplays.')


# ─── Main Window ─────────────────────────────────────────────────────────────

class WCM(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Wayfire Config Manager')
        self.setMinimumSize(640, 400)
        self.resize(900, 540)

        ip = find_app_icon()
        self.setWindowIcon(QIcon(ip) if ip else QIcon.fromTheme('preferences-system'))

        self.config_path = get_config_path()
        self.config = WayfireConfigFile(self.config_path)

        self.plugins = load_all_metadata()
        if not self.plugins:
            self._gen_from_config()

        el = self.config.get_enabled_plugins()
        for p in self.plugins:
            p.enabled = (p.is_core_plugin or p.type == PluginType.WF_SHELL
                         or p.name in el)

        self.plugins.sort(key=lambda p: (get_category_index(p.category),
                                         (p.disp_name or p.name).lower()))

        # Print icon search info
        _resolve_icon_dirs()
        
        if _wcm_icon_dir or _wf_icon_dir:
            found = sum(1 for p in self.plugins if find_plugin_icon(p.name))
            print(f"WCM: Found icons for {found}/{len(self.plugins)} plugins")
        else:
            print("WCM: No icon directory found — run: find /usr -name plugin-core.svg")

        self._build_ui()

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
        cw = QWidget()
        self.setCentralWidget(cw)
        h = QHBoxLayout(cw)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self.lp = LeftPanel()
        self.lp.search_entry.textChanged.connect(self._filter)
        self.lp.close_clicked.connect(self.close)
        self.lp.back_clicked.connect(self._back)
        self.lp.plugin_enabled_changed.connect(self._set_en)
        h.addWidget(self.lp)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        h.addWidget(sep)

        self.cs = QStackedWidget()
        h.addWidget(self.cs, 1)

        self.mp = MainPage(self.plugins)
        self.mp.plugin_clicked.connect(self._open)
        self.mp.plugin_enabled.connect(self._set_en)
        self.cs.addWidget(self.mp)
        self.pp = None

    def _filter(self, t):
        self.mp.set_filter(t)

    def _open(self, plugin):
        if self.pp:
            self.cs.removeWidget(self.pp)
            self.pp.deleteLater()
        self.pp = PluginPage(plugin, self.config)
        self.cs.addWidget(self.pp)
        self.cs.setCurrentWidget(self.pp)
        self.lp.show_plugin(plugin)

    def _back(self):
        if self.pp:
            self.cs.removeWidget(self.pp)
            self.pp.deleteLater()
            self.pp = None
        self.cs.setCurrentWidget(self.mp)
        self.lp.show_main()

    def _set_en(self, plugin, en):
        plugin.enabled = en
        if en:
            self.config.enable_plugin(plugin.name)
        else:
            self.config.disable_plugin(plugin.name)
        self.config.save()
        for btn in self.mp.plugin_buttons:
            if btn.plugin is plugin:
                btn.check.blockSignals(True)
                btn.check.setChecked(en)
                btn.check.blockSignals(False)
                break

    def keyPressEvent(self, ev):
        if ev.modifiers() & Qt.ControlModifier and ev.key() == Qt.Key_Q:
            self.close()
        super().keyPressEvent(ev)


def main():
    import argparse
    pa = argparse.ArgumentParser(description='Wayfire Config Manager')
    pa.add_argument('-c', '--config', help='Wayfire config file')
    pa.add_argument('-s', '--shell-config', help='wf-shell config file')
    pa.add_argument('-p', '--plugin', help='Plugin to open at launch')
    args = pa.parse_args()
    if args.config:
        os.environ['WAYFIRE_CONFIG_FILE'] = args.config
    app = QApplication(sys.argv)
    app.setApplicationName('wcm')
    w = WCM()
    if args.plugin:
        for p in w.plugins:
            if p.name == args.plugin:
                w._open(p)
                break
    w.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
