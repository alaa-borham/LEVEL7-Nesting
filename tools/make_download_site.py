"""Build the files published on LEVEL7's own download host (Cloudflare R2):

    latest.json                         update manifest read by the application
    index.html                          download page (Arabic / English)

Usage: python tools/make_download_site.py SETUP_EXE PUBLIC_URL OUTDIR [--notes FILE]
The installer itself is uploaded twice by CI: versioned (LEVEL7Nesting-<ver>-Setup.exe, immutable) and as
LEVEL7Nesting-Setup.exe (stable "always latest" link for sharing).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import os
import re

STABLE_NAME = "LEVEL7Nesting-Setup.exe"


def build(setup: str, public_url: str, outdir: str, notes: str = "") -> dict:
    public_url = public_url.rstrip("/")
    if not public_url.startswith("https://"):
        raise SystemExit("PUBLIC_URL must be https://")
    name = os.path.basename(setup)
    m = re.search(r"LEVEL7Nesting-(.+)-Setup\.exe$", name)
    if not m:
        raise SystemExit(f"unexpected installer name {name}")
    ver = m.group(1)
    h = hashlib.sha256()
    with open(setup, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    size = os.path.getsize(setup)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    man = {"version": ver, "notes": notes.strip(), "published": now,
           "setup": {"name": name, "url": f"{public_url}/{name}", "sha256": h.hexdigest(), "size": size}}
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "latest.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page(man, public_url))
    return man


def page(man: dict, public_url: str) -> str:
    e = html.escape
    st = man["setup"]
    mb = st["size"] / 1e6
    notes = "".join(f"<li>{e(ln.lstrip('-* '))}</li>" for ln in man["notes"].splitlines() if ln.strip())
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LEVEL7 Nesting — تحميل</title>
<style>
:root {{ --bg:#f6f4ef; --card:#fff; --fg:#1f1f1f; --muted:#666; --accent:#f0a00a; --line:#e3ded3; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1c1c1c; --card:#262626; --fg:#eee; --muted:#aaa; --line:#3a3a3a; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.6 "Segoe UI", Tahoma, sans-serif; }}
main {{ max-width:720px; margin:0 auto; padding:40px 16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:28px; }}
h1 {{ margin:0 0 4px; font-size:28px }} .muted {{ color:var(--muted) }}
.btn {{ display:inline-block; margin:22px 0 8px; padding:14px 28px; background:var(--accent); color:#1b1300;
        font-weight:700; font-size:18px; border-radius:10px; text-decoration:none }}
.btn:hover {{ filter:brightness(1.05) }}
code {{ direction:ltr; unicode-bidi:embed; font-size:12px; word-break:break-all; color:var(--muted) }}
ol, ul {{ padding-inline-start:22px }} h2 {{ font-size:18px; margin:26px 0 6px }}
.en {{ direction:ltr; text-align:left; border-top:1px solid var(--line); margin-top:26px; padding-top:14px }}
</style>
</head>
<body><main><div class="card">
<h1>LEVEL7 Nesting</h1>
<div class="muted">الإصدار {e(man['version'])} · {e(man['published'])} · Windows 10/11 (64-bit)</div>
<a class="btn" href="{e(st['url'])}">تحميل البرنامج ({mb:.0f} ميجابايت)</a>
<div class="muted">رابط ثابت لأحدث إصدار دائمًا: <code>{e(public_url)}/{STABLE_NAME}</code></div>
<h2>التثبيت</h2>
<ol>
<li>شغّل الملف بعد التحميل.</li>
<li>إذا ظهر «Windows protected your PC» اضغط <b>More info</b> ثم <b>Run anyway</b> (الملف غير موقّع رقميًا).</li>
<li>اترك خيار أيقونة سطح المكتب مفعّلًا.</li>
<li>بعد ذلك تصلك التحديثات تلقائيًا داخل البرنامج برسالة إشعار.</li>
</ol>
{f"<h2>الجديد في هذا الإصدار</h2><ul dir='auto'>{notes}</ul>" if notes else ""}
<h2>التحقق</h2>
<div class="muted">SHA-256: <code>{e(st['sha256'])}</code></div>
<div class="en"><b>LEVEL7 Nesting {e(man['version'])}</b> — <a href="{e(st['url'])}">Download for Windows</a>.
Unsigned installer: if SmartScreen appears choose <i>More info → Run anyway</i>. Updates are delivered inside the app.</div>
</div></main></body></html>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("setup")
    ap.add_argument("public_url")
    ap.add_argument("outdir")
    ap.add_argument("--notes", default=None)
    a = ap.parse_args()
    notes = open(a.notes, encoding="utf-8").read() if a.notes else ""
    print(json.dumps(build(a.setup, a.public_url, a.outdir, notes), indent=1))
