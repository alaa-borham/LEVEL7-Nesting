"""Several LEVEL7 sessions (windows) in one running program, and single-instance file hand-over.

Selecting several files in Explorer and pressing Enter starts LEVEL7 once per file. The first process becomes
the primary (it holds a lock file and a local server); every further process hands its files to the primary
and exits. The primary opens each file in its own window (session), up to MAX_WINDOWS.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import tempfile

from PySide6.QtCore import QLockFile, QObject, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QMessageBox

from .i18n import tr

MAX_WINDOWS = 10


def _key() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return "LEVEL7Nesting-" + re.sub(r"[^A-Za-z0-9_-]", "_", user)


def acquire_primary():
    """Lock held by the primary process for its lifetime; None if another LEVEL7 is already running."""
    lock = QLockFile(os.path.join(tempfile.gettempdir(), _key() + ".lock"))
    lock.setStaleLockTime(0)
    return lock if lock.tryLock(200) else None


def forward_to_primary(paths: list[str], attempts: int = 20) -> bool:
    """Send file paths to the running primary (it may still be starting); True when delivered."""
    payload = json.dumps({"open": [os.path.abspath(p) for p in paths]}).encode("utf-8")
    for _ in range(attempts):
        s = QLocalSocket()
        s.connectToServer(_key())
        if s.waitForConnected(300):
            s.write(payload)
            s.flush()
            s.waitForBytesWritten(2000)
            s.disconnectFromServer()
            return True
        import time
        time.sleep(0.25)
    return False


class SessionManager(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.windows = []
        self.server = None

    # -- single instance -------------------------------------------------------------------
    def listen(self):
        QLocalServer.removeServer(_key())
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)
        self.server.listen(_key())

    def _on_connection(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.setProperty("buf", b"")
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: (self._read(s, done=True), s.deleteLater()))

    def _read(self, sock, done=False):
        # a long file list can arrive in several chunks: parse once it is complete
        data = bytes(sock.property("buf") or b"") + bytes(sock.readAll())
        try:
            paths = json.loads(data.decode("utf-8")).get("open", [])
        except ValueError:
            if not done:
                sock.setProperty("buf", data)
            return
        sock.setProperty("buf", b"")
        if paths:
            self.open_files(paths)
        elif self.windows:
            self._front(self.windows[-1])

    # -- windows -----------------------------------------------------------------------------
    def new_window(self, show=True):
        from .main_window import MainWindow
        if len(self.windows) >= MAX_WINDOWS:
            parent = self.windows[-1] if self.windows else None
            QMessageBox.information(parent, tr("sessions"), tr("sessions_max", n=MAX_WINDOWS))
            return None
        w = MainWindow(sessions=self, primary=not self.windows)
        w.setAttribute(Qt.WA_DeleteOnClose, True)
        self.windows.append(w)
        if len(self.windows) > 1:                      # cascade new sessions
            ref = self.windows[-2]
            w.resize(ref.size())
            w.move(ref.pos().x() + 30, ref.pos().y() + 30)
        if show:
            w.show()
        return w

    def remove(self, w):
        if w in self.windows:
            self.windows.remove(w)

    def free_window(self):
        return next((w for w in self.windows if w.project is None), None)

    def open_files(self, paths, prefer=None):
        """Open each file in its own session: an empty window first (prefer), else a new one."""
        paths = [p for p in paths if os.path.isfile(p)]
        last = None
        for p in paths:
            w = prefer if (prefer is not None and prefer.project is None) else self.free_window()
            prefer = None
            if w is None:
                w = self.new_window()
                if w is None:
                    break
            w.open_path(p)
            last = w
        if last is not None:
            self._front(last)

    @staticmethod
    def _front(w):
        w.show()
        w.setWindowState((w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        w.raise_()
        w.activateWindow()
