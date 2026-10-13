"""Light / dark / gray application themes: Fusion palette, a modern style sheet (rounded controls, accent
highlights, slim scroll bars) and the marker-canvas colours."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = (240, 160, 10)          # LEVEL7 orange

THEMES = {
    # window = frame, panel = toolbar / status bar / popups, base = fields / tables, border = lines between areas
    "light": dict(window=(244, 245, 247), panel=(255, 255, 255), base=(255, 255, 255), text=(28, 30, 33),
                  muted=(110, 114, 120), button=(236, 238, 241), border=(220, 223, 228), highlight=ACCENT,
                  canvas=(214, 217, 222), fabric=(253, 252, 248), ruler=(248, 249, 250), ruler_text=(90, 94, 100),
                  fabric_line=(150, 150, 150)),
    "dark": dict(window=(30, 31, 34), panel=(38, 40, 44), base=(43, 45, 49), text=(232, 233, 235),
                 muted=(150, 154, 160), button=(52, 55, 60), border=(58, 61, 66), highlight=ACCENT,
                 canvas=(22, 23, 25), fabric=(56, 58, 62), ruler=(38, 40, 44), ruler_text=(185, 188, 192),
                 fabric_line=(110, 110, 110)),
    "gray": dict(window=(84, 86, 90), panel=(96, 98, 103), base=(108, 110, 115), text=(246, 246, 247),
                 muted=(205, 207, 210), button=(112, 114, 120), border=(122, 124, 130), highlight=ACCENT,
                 canvas=(66, 68, 71), fabric=(150, 151, 154), ruler=(96, 98, 103), ruler_text=(236, 236, 238),
                 fabric_line=(200, 200, 200)),
}
CURRENT = {"name": "dark"}


def colours(name: str | None = None) -> dict:
    return {k: QColor(*v) for k, v in THEMES[name or CURRENT["name"]].items()}


def _rgb(c: QColor, a: float | None = None) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{a})" if a is not None else f"rgb({c.red()},{c.green()},{c.blue()})"


def stylesheet(c: dict) -> str:
    acc, txt, mut = c["highlight"], c["text"], c["muted"]
    return f"""
QMainWindow, QDialog {{ background: {_rgb(c['window'])}; }}
QToolTip {{ background: {_rgb(c['panel'])}; color: {_rgb(txt)}; border: 1px solid {_rgb(c['border'])};
           border-radius: 6px; padding: 5px 8px; }}

QMenuBar {{ background: {_rgb(c['panel'])}; border-bottom: 1px solid {_rgb(c['border'])}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 6px; background: transparent; }}
QMenuBar::item:selected {{ background: {_rgb(acc, 0.18)}; }}
QMenu {{ background: {_rgb(c['panel'])}; border: 1px solid {_rgb(c['border'])}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {_rgb(acc, 0.22)}; color: {_rgb(txt)}; }}
QMenu::separator {{ height: 1px; background: {_rgb(c['border'])}; margin: 5px 8px; }}

QToolBar {{ background: {_rgb(c['panel'])}; border: none; border-bottom: 1px solid {_rgb(c['border'])};
           padding: 2px 4px; spacing: 1px; }}
QToolBar::separator {{ background: {_rgb(c['border'])}; width: 1px; margin: 8px 3px; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 9px; padding: 3px 2px;
              color: {_rgb(txt)}; }}
QToolButton:hover {{ background: {_rgb(acc, 0.13)}; border-color: {_rgb(acc, 0.35)}; }}
QToolButton:pressed {{ background: {_rgb(acc, 0.28)}; }}
QToolButton:checked {{ background: {_rgb(acc, 0.22)}; border-color: {_rgb(acc, 0.75)}; }}
QToolButton:disabled {{ color: {_rgb(mut, 0.6)}; }}
QToolButton#primary {{ background: {_rgb(acc, 0.20)}; border-color: {_rgb(acc, 0.65)}; font-weight: 600; }}
QToolButton#primary:hover {{ background: {_rgb(acc, 0.32)}; }}
QToolButton::menu-indicator {{ subcontrol-position: bottom right; width: 7px; height: 7px; }}

QPushButton {{ background: {_rgb(c['button'])}; border: 1px solid {_rgb(c['border'])}; border-radius: 7px;
              padding: 6px 14px; color: {_rgb(txt)}; }}
QPushButton:hover {{ border-color: {_rgb(acc, 0.7)}; background: {_rgb(acc, 0.12)}; }}
QPushButton:pressed {{ background: {_rgb(acc, 0.25)}; }}
QPushButton:disabled {{ color: {_rgb(mut, 0.6)}; border-color: {_rgb(c['border'])}; }}
QPushButton#primary {{ background: {_rgb(acc)}; color: rgb(25,25,25); border-color: {_rgb(acc)}; font-weight: 600; }}
QPushButton#primary:hover {{ background: rgb(250,180,40); }}
QPushButton#primary:disabled {{ background: {_rgb(acc, 0.35)}; color: rgba(25,25,25,0.6); }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background: {_rgb(c['base'])}; border: 1px solid {_rgb(c['border'])}; border-radius: 7px;
    padding: 3px 6px; selection-background-color: {_rgb(acc, 0.55)}; color: {_rgb(txt)}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {{
    border-color: {_rgb(acc)}; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {_rgb(acc, 0.6)}; }}
QSpinBox[rowSelected="true"], QDoubleSpinBox[rowSelected="true"], QComboBox[rowSelected="true"] {{
    background: {_rgb(acc, 0.30)}; border-color: {_rgb(acc, 0.8)}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 16px; border: none; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ width: 7px; height: 7px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ width: 7px; height: 7px; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {_rgb(c['panel'])}; border: 1px solid {_rgb(c['border'])};
    border-radius: 8px; selection-background-color: {_rgb(acc, 0.3)}; padding: 4px; }}

QTableWidget, QTableView, QListWidget {{ background: {_rgb(c['base'])}; border: 1px solid {_rgb(c['border'])};
    border-radius: 8px; gridline-color: {_rgb(c['border'])}; selection-background-color: {_rgb(acc, 0.30)};
    selection-color: {_rgb(txt)}; alternate-background-color: {_rgb(c['panel'])}; }}
QHeaderView::section {{ background: {_rgb(c['panel'])}; color: {_rgb(mut)}; border: none;
    border-bottom: 1px solid {_rgb(c['border'])}; padding: 5px 6px; font-weight: 600; }}
QTableCornerButton::section {{ background: {_rgb(c['panel'])}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {_rgb(mut, 0.45)}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {_rgb(acc, 0.8)}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {_rgb(c['panel'])}; border-top: 1px solid {_rgb(c['border'])}; color: {_rgb(txt)}; }}
QStatusBar::item {{ border: none; }}
QLabel#statChip {{ background: {_rgb(c['base'])}; border: 1px solid {_rgb(c['border'])}; border-radius: 7px;
    padding: 2px 10px; margin: 2px 0; }}
QProgressBar {{ background: {_rgb(c['base'])}; border: 1px solid {_rgb(c['border'])}; border-radius: 7px;
    text-align: center; color: {_rgb(txt)}; min-height: 16px; }}
QProgressBar::chunk {{ background: {_rgb(acc)}; border-radius: 6px; }}

QFrame#panel {{ background: {_rgb(c['panel'])}; border: 1px solid {_rgb(acc, 0.45)}; border-radius: 4px; }}
QLabel#panelTitle {{ font-size: 10.5pt; font-weight: 600; color: {_rgb(txt)}; }}
QCheckBox {{ spacing: 6px; }}
QScrollArea {{ background: transparent; border: none; }}
"""


def apply_theme(name: str):
    if name not in THEMES:
        name = "dark"
    CURRENT["name"] = name
    c = colours(name)
    app = QApplication.instance()
    app.setStyle("Fusion")
    f = QFont("Segoe UI")
    f.setPointSizeF(9.5)
    app.setFont(f)
    pal = QPalette()
    disabled = QColor(c["text"])
    disabled.setAlpha(110)
    for role, col in ((QPalette.Window, c["window"]), (QPalette.WindowText, c["text"]), (QPalette.Base, c["base"]),
                      (QPalette.AlternateBase, c["panel"]), (QPalette.Text, c["text"]),
                      (QPalette.Button, c["button"]), (QPalette.ButtonText, c["text"]),
                      (QPalette.ToolTipBase, c["panel"]), (QPalette.ToolTipText, c["text"]),
                      (QPalette.Highlight, c["highlight"]), (QPalette.HighlightedText, QColor(20, 20, 20)),
                      (QPalette.PlaceholderText, disabled), (QPalette.BrightText, QColor(255, 80, 80)),
                      (QPalette.Mid, c["border"]), (QPalette.Midlight, c["border"])):
        pal.setColor(role, col)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, disabled)
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(c))
