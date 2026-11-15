"""Build only public extension assets, with verified bundled KaTeX provenance."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT / "browser-extension" / "mathpath-canvas"
FILES = ["manifest.json", "background.js", "content.js", "panel.css", "popup.html", "popup.js", "popup.css", "先看这里.md"]


def build():
    vendor = PROJECT / "static" / "vendor" / "katex"
    provenance = vendor / "provenance.json"
    expected = "dd0779593b0cee2078bc9a16cbbf1d9d5472fce173f0b8bb3646f6077d293c9b"
    if hashlib.sha256(provenance.read_bytes()).hexdigest() != expected:
        raise RuntimeError("KaTeX provenance changed; review before packaging")
    assets = json.loads(provenance.read_bytes())["files"]
    included = []
    for asset in assets:
        name = asset["path"]
        if name not in {"katex.min.js", "auto-render.min.js", "katex.min.css", "LICENSE.txt"} and not name.startswith("fonts/"):
            continue
        path = vendor / name
        if not path.resolve().is_relative_to(vendor.resolve()) or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise RuntimeError("Unverified KaTeX asset")
        target = EXTENSION / "vendor" / "katex" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        included.append("vendor/katex/" + name)
    shutil.copyfile(provenance, EXTENSION / "vendor" / "katex" / "provenance.json")
    names = FILES + included + ["vendor/katex/provenance.json"]
    output = PROJECT / "outputs" / "canvas-companion"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "MathPath-Canvas-Companion-0.2.1.zip"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as zipped:
        for name in names:
            path = EXTENSION / name
            if path.is_symlink() or not path.resolve().is_relative_to(EXTENSION.resolve()): raise RuntimeError("Unexpected extension path")
            zipped.write(path, "mathpath-canvas/" + name)
    report = {"extension_version":"0.2.1", "backend":"MathPath 0.6.2 desktop or current source", "sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
              "files":names, "private_data_included":False, "live_canvas_acceptance":"not performed"}
    (output / "package-check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(str(archive))
    print(f"{len(names)} public files; verified KaTeX; no account, key or learning data")


if __name__ == "__main__": build()
