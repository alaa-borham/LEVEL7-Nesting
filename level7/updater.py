"""Online updates from the project's GitHub Releases.

Every successful Windows build of the default branch publishes a release ``v<version>`` with the installer
``LEVEL7Nesting-<version>-Setup.exe`` and ``SHA256SUMS.txt``. The application asks the GitHub API for the
latest release, compares versions, downloads the installer over HTTPS from github.com only, verifies its
SHA-256 and starts it. Nothing is sent except the plain API/download requests (no telemetry, no IDs).
The installer is not code-signed, so Windows SmartScreen/UAC may still ask for confirmation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from . import __version__

REPO = "alaa-borham/LEVEL7-Nesting"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
ALLOWED_HOSTS = ("github.com", "api.github.com")
USER_AGENT = f"LEVEL7-Nesting/{__version__}"


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str
    tag: str
    notes: str
    page_url: str
    setup_name: str
    setup_url: str
    setup_size: int
    sums_url: str | None


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    if not nums:
        raise ValueError(f"not a version: {v!r}")
    return tuple(int(n) for n in nums)


def is_newer(remote: str, local: str = __version__) -> bool:
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _check_url(url: str):
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise UpdateError(f"refusing update URL outside GitHub: {url}")


def _get(url: str, timeout: float, accept: str = "application/octet-stream"):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(req, timeout=timeout)       # follows the redirect to GitHub's asset storage


def parse_release(data: dict) -> UpdateInfo | None:
    """Pick the installer and checksum file from a GitHub release JSON; None if it has no installer."""
    if data.get("draft") or data.get("prerelease"):
        return None
    assets = {a["name"]: a for a in data.get("assets", [])}
    setup = [a for n, a in assets.items() if n.endswith("-Setup.exe")]
    if not setup:
        return None
    s = setup[0]
    sums = assets.get("SHA256SUMS.txt")
    tag = data.get("tag_name", "")
    return UpdateInfo(version=tag.lstrip("vV"), tag=tag, notes=(data.get("body") or "").strip(),
                      page_url=data.get("html_url", ""), setup_name=s["name"],
                      setup_url=s["browser_download_url"], setup_size=int(s.get("size", 0)),
                      sums_url=sums["browser_download_url"] if sums else None)


def check_latest(timeout: float = 10.0, current: str = __version__) -> UpdateInfo | None:
    """Return the latest release if it is newer than ``current``, else None. Raises UpdateError when offline."""
    try:
        with _get(LATEST_API, timeout, "application/vnd.github+json") as r:
            data = json.loads(r.read().decode("utf-8"))
    except UpdateError:
        raise
    except Exception as exc:                                    # offline, proxy, rate limit, 404 (no release yet)
        raise UpdateError(f"update check failed: {exc}") from exc
    info = parse_release(data)
    if info is None:
        return None
    try:
        return info if is_newer(info.version, current) else None
    except ValueError:
        return None


def expected_sha256(sums_text: str, name: str) -> str | None:
    for ln in sums_text.splitlines():
        parts = ln.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return None


def download(info: UpdateInfo, dest_dir: str | None = None, progress=None, cancelled=None,
             timeout: float = 30.0) -> str:
    """Download and verify the installer. ``progress(done, total)``; ``cancelled()`` -> True aborts."""
    if not info.sums_url:
        raise UpdateError("release has no SHA256SUMS.txt; refusing unverified installer")
    with _get(info.sums_url, timeout) as r:
        want = expected_sha256(r.read().decode("utf-8", "replace"), info.setup_name)
    if not want:
        raise UpdateError(f"no checksum for {info.setup_name}")
    dest_dir = dest_dir or os.path.join(tempfile.gettempdir(), "LEVEL7Nesting-update")
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, os.path.basename(info.setup_name))
    h, done = hashlib.sha256(), 0
    with _get(info.setup_url, timeout) as r, open(path + ".part", "wb") as fh:
        total = int(r.headers.get("Content-Length") or info.setup_size or 0)
        while True:
            if cancelled and cancelled():
                fh.close()
                os.remove(path + ".part")
                raise UpdateError("cancelled")
            chunk = r.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if h.hexdigest() != want:
        os.remove(path + ".part")
        raise UpdateError("checksum mismatch: downloaded installer rejected")
    os.replace(path + ".part", path)
    return path


def installer_arguments() -> list[str]:
    """Inno Setup: show progress only, close the running app, and start LEVEL7 again afterwards."""
    return ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/LAUNCH=1"]


def start_installer(path: str):
    """Start the verified installer (Windows only); the caller quits the application afterwards."""
    if os.name != "nt":
        raise UpdateError("installing updates is only supported on Windows")
    args = " ".join(installer_arguments())
    os.startfile(path, "open", args)        # ShellExecute: lets the installer request elevation (UAC) itself
