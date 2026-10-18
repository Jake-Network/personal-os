"""Authentication orchestration. Only explicit activity renews a session's idle deadline."""
import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.modules.database.model import AppOAuthAttempt, AppOwner, AppSession
from app.modules.database.model.base import utcnow

COOKIE = "personal_os_session"
IDLE_SECONDS = 900


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${key.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def active_session(session: Session, token: str | None) -> AppSession | None:
    if not token:
        return None
    record = session.get(AppSession, digest(token), populate_existing=True)
    if record and record.last_activity_at + timedelta(seconds=IDLE_SECONDS) > utcnow():
        return record
    return None


def revoke_all(session: Session) -> None:
    _serialize_owner_access(session)
    session.execute(delete(AppOAuthAttempt))
    session.execute(delete(AppSession))
    session.commit()


def authenticate(session: Session, password: str) -> str:
    _serialize_owner_access(session)
    owner = session.scalar(select(AppOwner).where(AppOwner.id == 1).with_for_update()
                           .execution_options(populate_existing=True))
    if owner is None:
        raise HTTPException(409, "소유자 비밀번호를 먼저 설정하세요.")
    now = utcnow()
    if owner.blocked_until and owner.blocked_until > now:
        raise HTTPException(429, "로그인 시도가 많습니다. 잠시 후 다시 시도하세요.")
    if not verify_password(password, owner.password_hash):
        owner.failed_attempts += 1
        if owner.failed_attempts >= 5:
            owner.blocked_until = now + timedelta(minutes=5)
        session.commit()
        raise HTTPException(401, "비밀번호를 확인하세요.")
    owner.failed_attempts = 0
    owner.blocked_until = None
    return new_session(session)


def _serialize_owner_access(session: Session) -> None:
    # Both password verification and global revocation own the same row lock.
    # An UPDATE also obtains a SQLite write lock, where SELECT FOR UPDATE is ignored.
    session.execute(update(AppOwner).where(AppOwner.id == 1).values(
        failed_attempts=AppOwner.failed_attempts))


def new_session(session: Session) -> str:
    token = secrets.token_urlsafe(48)
    session.add(AppSession(token_hash=digest(token), csrf_token=secrets.token_urlsafe(32), last_activity_at=utcnow()))
    session.commit()
    return token


def status(session: Session, token: str | None) -> dict:
    record = active_session(session, token)
    return {"configured": session.get(AppOwner, 1) is not None, "authenticated": record is not None,
            "locked": record is None, "csrf_token": record.csrf_token if record else None,
            "idle_timeout_seconds": IDLE_SECONDS, "storage_encryption": "unverified", "firewall": "unverified"}


def bind_oauth(session: Session, token: str, state: str, provider: str) -> str:
    record = active_session(session, token)
    if record is None:
        raise HTTPException(401, "앱 잠금을 해제하세요.")
    proof = secrets.token_urlsafe(32)
    session.add(AppOAuthAttempt(state_hash=digest(state), session_hash=record.token_hash,
                               provider=provider, proof_hash=digest(proof)))
    session.commit()
    return proof


def consume_oauth(session: Session, token: str | None, state: str, provider: str, proof: str | None) -> bool:
    record = active_session(session, token)
    attempt = session.get(AppOAuthAttempt, digest(state))
    if not record or not attempt or not proof:
        return False
    valid = (attempt.session_hash == record.token_hash and attempt.provider == provider
             and hmac.compare_digest(attempt.proof_hash, digest(proof))
             and attempt.created_at + timedelta(minutes=10) > utcnow())
    if valid:
        session.delete(attempt)
        session.commit()
    return valid


def guard_oauth_commit(session: Session, token: str | None) -> None:
    """Serialize callback credential persistence with a concurrent global lock."""
    record = session.scalar(select(AppSession).where(AppSession.token_hash == digest(token or ""))
                            .with_for_update().execution_options(populate_existing=True))
    if record is None or record.last_activity_at + timedelta(seconds=IDLE_SECONDS) <= utcnow():
        raise HTTPException(401, "OAuth를 시작한 앱 세션이 만료되었습니다.")
