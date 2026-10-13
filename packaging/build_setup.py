"""Build the per-user setup executable from a verified portable release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from build import FORBIDDEN, VERSION, release_allowlist, sha256, write_icon


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    stem = f"MathPath-desktop-{VERSION}-windows-x64"
    payload = output / stem
    manifest = json.loads((payload / "manifest.json").read_text(encoding="utf-8"))
    release_files = release_allowlist(manifest, payload)
    if manifest.get("version") != VERSION:
        raise RuntimeError("The portable payload version does not match the installer")
    expected_build_files = {entry["path"]: entry["sha256"] for entry in manifest["build_files"]}
    for relative in ["packaging/build_setup.py", "packaging/installer.py"]:
        if sha256(Path(__file__).resolve().parents[1] / relative) != expected_build_files[relative]:
            raise RuntimeError("Installer source changed after the portable release build")
    if sha256(payload / (stem + ".exe")) != manifest["executable_sha256"]:
        raise RuntimeError("The portable payload failed checksum verification")
    setup_stem = f"MathPath-setup-{VERSION}-windows-x64"
    with tempfile.TemporaryDirectory(prefix="mathpath-setup-build-") as temporary:
        work = Path(temporary)
        # Stage exactly the current release manifest, ignoring stale files from
        # earlier builds that may still be present in the output directory.
        staged_payload = work / "payload"
        for relative in release_files:
            original = payload / relative
            if not original.resolve().is_relative_to(payload.resolve()) or original.is_symlink():
                raise RuntimeError("Unsafe release payload path")
            destination = staged_payload / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
        icon = work / "mathpath.ico"
        write_icon(icon)
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                   "--name", "MathPath-setup", "--noupx", "--icon", str(icon), "--distpath", str(work / "dist"),
                   "--workpath", str(work / "build"), "--specpath", str(work),
                   "--add-data", str(staged_payload) + ":payload", str(Path(__file__).parent / "installer.py")]
        subprocess.run(command, check=True)
        setup = output / (setup_stem + ".exe")
        shutil.copy2(work / "dist" / "MathPath-setup.exe", setup)
        from PyInstaller.archive.readers import CArchiveReader
        entries = {name.replace("\\", "/") for name in CArchiveReader(str(setup)).toc}
        payload_entries = {name[len("payload/"):] for name in entries if name.startswith("payload/")}
        if payload_entries != set(release_files):
            raise RuntimeError("Installer payload allowlist verification failed")
        if any(FORBIDDEN.search(name) for name in entries):
            raise RuntimeError("Excluded data reached the setup executable")
    check = output / (setup_stem + "-self-test.json")
    subprocess.run([str(setup), "--self-test", "--report", str(check)], check=True, timeout=120)
    check_result = json.loads(check.read_text(encoding="utf-8"))
    check_result.update({"setup_sha256": sha256(setup),
                         "source_manifest_sha256": manifest["source_manifest_sha256"]})
    check.write_text(json.dumps(check_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"version": VERSION, "setup_executable": setup.name, "setup_bytes": setup.stat().st_size,
              "setup_sha256": sha256(setup), "payload_sha256": manifest["executable_sha256"],
              "source_manifest_sha256": manifest["source_manifest_sha256"],
              "portable_manifest_sha256": sha256(payload / "manifest.json"),
              "release_files": release_files, "payload_allowlist_verified": True,
              "excluded_data_absent": True,
              "self_test": check_result}
    (output / (setup_stem + "-manifest.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
