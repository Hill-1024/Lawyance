"""Explicit maintenance commands. Backup while v2 writes are quiesced."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from datetime import timedelta
from sqlalchemy import select, delete
from workbench.store import Item, Version, Event, BlobStore, transaction, now


def backup(destination):
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    url = os.environ["LAWVER_DATABASE_URL"].replace(
        "postgresql+psycopg://", "postgresql://"
    )
    # Connection string is passed via environment rather than process arguments.
    from urllib.parse import urlsplit, unquote

    parsed = urlsplit(url)
    env = {
        **os.environ,
        "PGHOST": parsed.hostname or "localhost",
        "PGPORT": str(parsed.port or 5432),
        "PGDATABASE": parsed.path.lstrip("/"),
        "PGUSER": unquote(parsed.username or ""),
        "PGPASSWORD": unquote(parsed.password or ""),
    }
    subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(target / "database.dump")],
        env=env,
        check=True,
    )
    root = BlobStore().root
    if root.exists():
        shutil.copytree(root, target / "blobs", dirs_exist_ok=True)
    else:
        (target / "blobs").mkdir()
    checksums = {
        str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in target.rglob("*")
        if p.is_file()
    }
    (target / "manifest.json").write_text(
        json.dumps(
            {"format": 1, "created_at": now().isoformat(), "sha256": checksums},
            indent=2,
        )
    )
    os.chmod(target / "database.dump", 0o600)
    return target


def verify_backup(source):
    root = Path(source)
    manifest = json.loads((root / "manifest.json").read_text())
    for name, checksum in manifest["sha256"].items():
        path = (root / name).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != checksum
        ):
            raise RuntimeError("Backup checksum mismatch")
    return len(manifest["sha256"])


def purge_expired():
    cutoff = now() - timedelta(days=30)
    with transaction() as s:
        expired = s.scalars(
            select(Item).where(Item.deleted_at < cutoff).with_for_update()
        ).all()
        ids = {i.id for i in expired}
        for item in expired:
            if item.kind == "project":
                ids.update(s.scalars(select(Item.id).where(Item.project_id == item.id)))
        for identifier in ids:
            s.execute(delete(Version).where(Version.document_id == identifier))
            s.execute(delete(Event).where(Event.run_id == identifier))
        s.execute(delete(Item).where(Item.id.in_(ids)))
        # Blob garbage collection must run separately after backup retention; keep immutable objects here.
        return len(ids)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["backup", "verify", "purge"])
    p.add_argument("path", nargs="?")
    a = p.parse_args()
    print(
        backup(a.path)
        if a.command == "backup"
        else verify_backup(a.path)
        if a.command == "verify"
        else purge_expired()
    )
