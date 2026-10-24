"""Offline encrypted local backups; restoration is always to a disposable directory.

Requires restic on PATH, RESTIC_REPOSITORY (absolute local directory), and
RESTIC_PASSWORD_FILE. Run with --help. Plaintext staging MUST be on an OS-encrypted
volume. This tool never restores over an operating database or changes OS settings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def run(*args: str, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)


def restic(*args: str, **kwargs):
    repository = os.environ.get("RESTIC_REPOSITORY", "")
    if not Path(repository).is_absolute() or ":" in repository:
        raise ValueError("RESTIC_REPOSITORY must be an absolute local directory")
    if not os.environ.get("RESTIC_PASSWORD_FILE"):
        raise ValueError("Set RESTIC_PASSWORD_FILE outside the repository and retain a separate copy")
    return run("restic", *args, **kwargs)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def manifest(directory: Path, database_kind: str) -> None:
    files = {str(path.relative_to(directory)): digest(path) for path in sorted(directory.rglob("*")) if path.is_file()}
    root = Path(__file__).resolve().parents[1]
    source_files = sorted([*root.glob("app/**/*.py"), *root.glob("migrations/**/*.py"),
                           root / "pyproject.toml", root / "uv.lock", root / "frontend/package.json",
                           root / "frontend/yarn.lock"])
    source_hash = hashlib.sha256()
    for path in source_files:
        if path.is_file():
            source_hash.update(str(path.relative_to(root)).encode())
            source_hash.update(bytes.fromhex(digest(path)))
    metadata = {"format": 1, "database_kind": database_kind, "files": files,
                "git_revision": run("git", "-C", str(root), "rev-parse", "HEAD").stdout.decode().strip(),
                "source_sha256": source_hash.hexdigest(),
                "working_tree_modified": bool(run("git", "-C", str(root), "status", "--porcelain").stdout),
                "migration_files": {p.name: digest(p) for p in sorted(root.glob("migrations/versions/*.py"))}}
    (directory / "manifest.json").write_text(json.dumps(metadata, indent=2))


def backup(args) -> None:
    if not args.confirm_app_stopped:
        raise ValueError("Stop app and workers first, then pass --confirm-app-stopped")
    source = Path(args.data_dir).resolve()
    settings = Path(args.settings_file).resolve()
    if not source.is_dir() or not settings.is_file():
        raise ValueError("Existing data directory and settings file are required")
    stage_root = Path(args.staging_dir).resolve()
    # Keeping staging outside the source prevents recursive copies of plaintext backups.
    if stage_root == source or source in stage_root.parents:
        raise ValueError("Staging must be outside the data directory on encrypted storage")
    with tempfile.TemporaryDirectory(prefix="personal-os-backup-", dir=stage_root) as temporary:
        stage = Path(temporary)
        bundle = stage / "bundle"
        shutil.copytree(source, bundle / "data", symlinks=False)
        shutil.copy2(settings, bundle / "settings.env")
        shutil.copy2(args.postgres_dump, bundle / "database.dump")
        manifest(bundle, "postgresql")
        archive = stage / "personal-os.tar"
        with tarfile.open(archive, "w") as tar:
            tar.add(bundle, arcname="bundle")
        if args.init:
            restic("init")
        with archive.open("rb") as stream:
            result = restic("backup", "--stdin", "--stdin-filename", "personal-os.tar", "--json", stdin=stream)
        summaries = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        print(json.dumps({"snapshot_id": next(item["snapshot_id"] for item in summaries if item.get("message_type") == "summary")}))


def restore_check(args) -> None:
    with tempfile.TemporaryDirectory(prefix="personal-os-restore-check-", dir=args.staging_dir) as temporary:
        stage = Path(temporary)
        restic("restore", args.snapshot, "--target", str(stage))
        archive = stage / "personal-os.tar"
        with tarfile.open(archive) as tar:
            tar.extractall(stage, filter="data")
        bundle = stage / "bundle"
        metadata = json.loads((bundle / "manifest.json").read_text())
        if metadata["format"] != 1:
            raise ValueError("Unsupported backup format")
        for name, expected in metadata["files"].items():
            path = (bundle / name).resolve()
            if bundle.resolve() not in path.parents or not path.is_file() or digest(path) != expected:
                raise ValueError("Backup content does not match its manifest")
        if metadata["database_kind"] != "postgresql":
            raise ValueError("Unsupported database kind in backup")
        if not args.postgres_image:
            raise ValueError("PostgreSQL backups require --postgres-image to validate in an isolated container")
        name = "personal-os-restore-" + os.urandom(8).hex()
        try:
            run("docker", "run", "--detach", "--rm", "--network", "none", "--name", name,
                "-e", "POSTGRES_HOST_AUTH_METHOD=trust", args.postgres_image)
            import time
            for _ in range(60):
                if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    break
                time.sleep(0.5)
            else:
                raise ValueError("Disposable PostgreSQL did not become ready")
            with (bundle / "database.dump").open("rb") as stream:
                run("docker", "exec", "-i", name, "pg_restore", "--exit-on-error", "--no-owner", "-U", "postgres", "-d", "postgres", stdin=stream)
            run("docker", "exec", name, "psql", "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", "SELECT version_num FROM alembic_version")
        finally:
            subprocess.run(["docker", "rm", "--force", "--volumes", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(json.dumps({"restored": True, "database": metadata["database_kind"], "verified_files": len(metadata["files"]), "operating_database_modified": False}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("backup")
    create.add_argument("--data-dir", required=True)
    create.add_argument("--settings-file", required=True)
    create.add_argument("--staging-dir", required=True)
    create.add_argument("--confirm-app-stopped", action="store_true")
    create.add_argument("--postgres-dump", required=True)
    create.add_argument("--init", action="store_true")
    check = sub.add_parser("restore-check")
    check.add_argument("--snapshot", default="latest")
    check.add_argument("--staging-dir", required=True)
    check.add_argument("--postgres-image")
    args = parser.parse_args()
    try:
        (backup if args.command == "backup" else restore_check)(args)
    except ValueError as error:
        parser.exit(1, f"Backup operation failed: {error}\n")
    except (OSError, subprocess.CalledProcessError) as error:
        # Commands and provider errors may include private paths; do not print subprocess output.
        parser.exit(1, f"Backup operation failed: {type(error).__name__}. Check local prerequisites; operating DB was not restored.\n")


if __name__ == "__main__":
    main()
