import hashlib
import io
import json

import pytest

from level7 import updater

SETUP = b"MZ fake installer" * 1000
SUM = hashlib.sha256(SETUP).hexdigest()


def release(tag="v0.2.99", sums=True, **kw):
    assets = [{"name": f"LEVEL7Nesting-{tag[1:]}-Setup.exe", "size": len(SETUP),
               "browser_download_url": f"https://github.com/alaa-borham/LEVEL7-Nesting/releases/download/{tag}/x.exe"}]
    if sums:
        assets.append({"name": "SHA256SUMS.txt",
                       "browser_download_url": f"https://github.com/alaa-borham/LEVEL7-Nesting/releases/download/{tag}/s"})
    d = {"tag_name": tag, "body": "notes", "html_url": "https://github.com/x", "assets": assets}
    d.update(kw)
    return d


class Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def fake_net(monkeypatch, rel, setup=SETUP, sums_name=None):
    seen = []

    def urlopen(req, timeout=None):
        url = req.full_url
        seen.append(url)
        if url == updater.LATEST_API:
            return Resp(json.dumps(rel).encode())
        if url.endswith("/s"):
            name = sums_name or rel["assets"][0]["name"]
            return Resp(f"{SUM}  {name}\n".encode())
        return Resp(setup)
    monkeypatch.setattr(updater.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(updater, "MANIFEST_URL", "")
    return seen


def test_version_compare():
    assert updater.is_newer("0.2.15", "0.2.9")
    assert updater.is_newer("0.3", "0.2.40")
    assert not updater.is_newer("0.2.15", "0.2.15")
    assert not updater.is_newer("0.2.0", "0.2")
    assert updater.is_newer("0.2.1", "0.1.0")        # first online build replaces the manual 0.1.0 install


def test_check_latest_newer_and_not_newer(monkeypatch):
    fake_net(monkeypatch, release("v0.2.99"))
    info = updater.check_latest(current="0.2.5")
    assert info and info.version == "0.2.99" and info.setup_name.endswith("-Setup.exe") and info.sums_url
    assert updater.check_latest(current="0.2.99") is None


def test_prerelease_draft_and_no_installer_are_ignored(monkeypatch):
    for rel in (release(prerelease=True), release(draft=True), {**release(), "assets": []}):
        fake_net(monkeypatch, rel)
        assert updater.check_latest(current="0.0.1") is None


def test_offline_raises_update_error(monkeypatch):
    def urlopen(req, timeout=None):
        raise OSError("no network")
    monkeypatch.setattr(updater.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(updater, "MANIFEST_URL", "https://dl.example.com/latest.json")
    with pytest.raises(updater.UpdateError):
        updater.check_latest()


def test_download_verified(monkeypatch, tmp_path):
    fake_net(monkeypatch, release())
    info = updater.check_latest(current="0.0.1")
    prog = []
    p = updater.download(info, str(tmp_path), progress=lambda d, t: prog.append((d, t)))
    assert open(p, "rb").read() == SETUP and prog[-1] == (len(SETUP), len(SETUP))


def test_download_rejects_bad_checksum_missing_sums_and_foreign_hosts(monkeypatch, tmp_path):
    fake_net(monkeypatch, release(), setup=SETUP + b"tampered")
    info = updater.check_latest(current="0.0.1")
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(info, str(tmp_path))
    assert not list(tmp_path.iterdir())                     # nothing left behind
    fake_net(monkeypatch, release(sums=False))
    with pytest.raises(updater.UpdateError, match="SHA256SUMS"):
        updater.download(updater.check_latest(current="0.0.1"), str(tmp_path))
    fake_net(monkeypatch, release(), sums_name="other.exe")
    with pytest.raises(updater.UpdateError, match="no checksum"):
        updater.download(updater.check_latest(current="0.0.1"), str(tmp_path))
    bad = release()
    bad["assets"][0]["browser_download_url"] = "https://evil.example.com/x.exe"
    fake_net(monkeypatch, bad)
    with pytest.raises(updater.UpdateError, match="outside the update host"):
        updater.download(updater.check_latest(current="0.0.1"), str(tmp_path))
    bad["assets"][0]["browser_download_url"] = "http://github.com/x.exe"
    with pytest.raises(updater.UpdateError, match="outside the update host"):
        updater.download(updater.check_latest(current="0.0.1"), str(tmp_path))


def test_cancel(monkeypatch, tmp_path):
    fake_net(monkeypatch, release())
    with pytest.raises(updater.UpdateError, match="cancelled"):
        updater.download(updater.check_latest(current="0.0.1"), str(tmp_path), cancelled=lambda: True)
    assert not list(tmp_path.iterdir())


def test_installer_arguments_relaunch_app():
    a = updater.installer_arguments()
    assert "/SILENT" in a and "/LAUNCH=1" in a and "/CLOSEAPPLICATIONS" in a


MANIFEST = "https://dl.level7.example/latest.json"


def manifest(url="https://dl.level7.example/LEVEL7Nesting-0.2.99-Setup.exe", sha=SUM, ver="0.2.99"):
    return {"version": ver, "notes": "new", "setup": {"name": url.rsplit("/", 1)[-1], "url": url, "sha256": sha,
                                                       "size": len(SETUP)}}


def fake_host(monkeypatch, man, setup=SETUP, down=False):
    seen = []

    def urlopen(req, timeout=None):
        seen.append(req.full_url)
        if req.full_url == MANIFEST:
            if down:
                raise OSError("host down")
            return Resp(json.dumps(man).encode())
        if req.full_url == updater.LATEST_API:
            return Resp(json.dumps(release("v0.2.50")).encode())
        if req.full_url.endswith("/s"):
            return Resp(f"{SUM}  LEVEL7Nesting-0.2.50-Setup.exe\n".encode())
        return Resp(setup)
    monkeypatch.setattr(updater.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(updater, "MANIFEST_URL", MANIFEST)
    return seen


def test_own_host_manifest_is_used_first(monkeypatch, tmp_path):
    seen = fake_host(monkeypatch, manifest())
    info = updater.check_latest(current="0.2.5")
    assert info.version == "0.2.99" and info.host == "dl.level7.example" and info.sha256 == SUM
    assert updater.LATEST_API not in seen                      # GitHub not contacted
    p = updater.download(info, str(tmp_path))
    assert open(p, "rb").read() == SETUP
    assert updater.check_latest(current="0.2.99") is None


def test_own_host_rejects_foreign_installer_and_bad_hash(monkeypatch, tmp_path):
    for bad in ("https://github.com/x/a.exe", "http://dl.level7.example/a.exe"):
        with pytest.raises(updater.UpdateError):               # installer must be HTTPS on the manifest's host
            updater.parse_manifest(manifest(url=bad), MANIFEST)
    fake_host(monkeypatch, manifest(), setup=SETUP + b"x")
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(updater.check_latest(current="0.0.1"), str(tmp_path))
    assert updater.parse_manifest(manifest(sha="nothex"), MANIFEST) is None


def test_github_is_fallback_when_own_host_is_down(monkeypatch, tmp_path):
    seen = fake_host(monkeypatch, manifest(), down=True)
    info = updater.check_latest(current="0.2.5")
    assert info.version == "0.2.50" and info.host is None and updater.LATEST_API in seen
