from pathlib import Path
import base64, hashlib, zipfile, shutil
root = Path("handoff/2026-11-02")
parts = sorted((root / "encoded").glob("*.b64"))
assert len(parts) == 71, len(parts)
out = Path("release-assets")
out.mkdir(exist_ok=True)
archive = out / "Lifeboat-Developer-Handoff-20261102.zip"
with archive.open("wb") as dst:
    for part in parts:
        dst.write(base64.b64decode(part.read_bytes(), validate=True))
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
assert archive.stat().st_size == 54172328
assert digest == "33fa6b4ecfe77c3c5ae9af831129ccde83463d785ac3aa499247c9136704dc27", digest
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for name in z.namelist():
        path = Path(name)
        assert not path.is_absolute() and ".." not in path.parts
        if name.endswith("/"):
            continue
        relative = Path(*path.parts[1:])
        if relative.suffix.lower() == ".pdf":
            (out / relative.name).write_bytes(z.read(name))
        elif relative.suffix.lower() not in (".zip", ".exe", ".dll", ".pdf"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
(out / "SHA256SUMS.txt").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name+"\n" for p in sorted(out.iterdir()) if p.is_file()))
print("Verified original archive SHA256:", digest)
