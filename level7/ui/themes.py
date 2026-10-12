"""Light / dark / gray application themes (Fusion palette + marker-canvas colours)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = {
    #           window      base (fields)  text          button      highlight     canvas      fabric       ruler bg     ruler text
    "light": dict(window=(240, 240, 240), base=(255, 255, 255), text=(25, 25, 25), button=(232, 232, 232),
                  highlight=(240, 160, 10), canvas=(205, 205, 205), fabric=(252, 251, 246),
                  ruler=(240, 240, 240), ruler_text=(60, 60, 60), fabric_line=(150, 150, 150)),
    "dark": dict(window=(37, 37, 38), base=(30, 30, 31), text=(230, 230, 230), button=(52, 52, 54),
                 highlight=(240, 160, 10), canvas=(24, 24, 24), fabric=(58, 58, 60),
                 ruler=(45, 45, 47), ruler_text=(200, 200, 200), fabric_line=(110, 110, 110)),
    "gray": dict(window=(92, 92, 94), base=(112, 112, 115), text=(245, 245, 245), button=(105, 105, 108),
                 highlight=(240, 160, 10), canvas=(70, 70, 72), fabric=(150, 150, 152),
                 ruler=(98, 98, 100), ruler_text=(240, 240, 240), fabric_line=(200, 200, 200)),
}
CURRENT = {"name": "dark"}


def colours(name: str | None = None) -> dict:
    return {k: QColor(*v) for k, v in THEMES[name or CURRENT["name"]].items()}


def apply_theme(name: str):
    if name not in THEMES:
        name = "dark"
    CURRENT["name"] = name
    c = colours(name)
    app = QApplication.instance()
    app.setStyle("Fusion")
    pal = QPalette()
    disabled = QColor(c["text"])
    disabled.setAlpha(110)
    for role, col in ((QPalette.Window, c["window"]), (QPalette.WindowText, c["text"]), (QPalette.Base, c["base"]),
                      (QPalette.AlternateBase, c["button"]), (QPalette.Text, c["text"]),
                      (QPalette.Button, c["button"]), (QPalette.ButtonText, c["text"]),
                      (QPalette.ToolTipBase, c["base"]), (QPalette.ToolTipText, c["text"]),
                      (QPalette.Highlight, c["highlight"]), (QPalette.HighlightedText, QColor(20, 20, 20)),
                      (QPalette.PlaceholderText, disabled), (QPalette.BrightText, QColor(255, 80, 80))):
        pal.setColor(role, col)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, disabled)
    app.setPalette(pal)
