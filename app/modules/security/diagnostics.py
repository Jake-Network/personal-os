"""Read-only security observations. Container/WSL checks never imply host protection."""
import json
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Callable


def _run(args: list[str]) -> str | None:
    if not shutil.which(args[0]):
        return None
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=4, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def diagnose(data_dir: Path, *, run: Callable[[list[str]], str | None] = _run,
             release: str | None = None, container: bool | None = None) -> dict:
    """Surface unknowns instead of inferring host encryption from an application lock."""
    release = platform.release() if release is None else release
    container = Path("/.dockerenv").exists() if container is None else container
    wsl = "microsoft" in release.lower()
    environment = "container" if container else "wsl" if wsl else platform.system().lower()
    encryption = {"id": "storage_encryption", "state": "unverified",
                  "summary": "DB·문서·벡터·임시 파일·키가 저장되는 실제 디스크의 암호화를 확인하세요."}
    firewall = {"id": "firewall", "state": "unverified", "summary": "호스트 방화벽과 loopback 공개 범위를 확인하세요."}
    if wsl or container:
        encryption["summary"] = "WSL/Docker 실제 데이터 디스크와 Windows 볼륨 암호화는 호스트에서 확인해야 합니다."
        firewall["summary"] = "WSL/컨테이너 내부에서는 호스트 방화벽 상태를 확인할 수 없습니다."
    else:
        # findmnt establishes only the mounted filesystem. ext4 and overlay do not prove
        # unencrypted storage: full-disk encryption can exist below the visible device.
        mounted = run(["findmnt", "--json", "--target", str(data_dir.resolve()), "--output", "FSTYPE"])
        if mounted:
            try:
                filesystem = json.loads(mounted)["filesystems"][0]["fstype"]
                encryption["filesystem"] = filesystem
                if filesystem in {"ecryptfs", "fuse.gocryptfs", "fuse.cryfs"}:
                    encryption["summary"] = "앱 데이터 경로의 암호화 파일시스템을 확인했습니다. DB·벡터·임시 파일 경로는 별도 확인이 필요합니다."
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        ufw = run(["ufw", "status"])
        if ufw and "Status: inactive" in ufw:
            firewall.update(state="action_needed", summary="UFW가 비활성 상태입니다. 다른 호스트 방화벽 사용 여부를 확인하세요.")
        elif ufw and "Status: active" in ufw:
            # Enabling a firewall is an observation, not proof of inbound rules. Report
            # the exact narrow claim, with the application's exposure still unverified.
            firewall.update(state="verified", summary="UFW 활성 상태를 확인했습니다. 허용 규칙과 loopback 공개 범위는 별도 확인하세요.")
    return {"environment": environment, "checks": [encryption, firewall],
            "lock_scope": "앱 잠금은 사용자 접근을 차단합니다. 승인된 worker는 데이터를 계속 읽을 수 있습니다.",
            "host_settings_modified": False}
