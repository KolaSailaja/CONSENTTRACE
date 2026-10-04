from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import SessionLocal
from app.models import ApiKey, HmacReplayRecord, SecurityAuditRecord

logger = logging.getLogger("consenttrace.security")

HUMAN_ROLES = {"ADMIN", "PRIVACY_ANALYST", "DATA_GOVERNANCE", "AUDITOR", "VIEWER"}
ALL_ROLES = HUMAN_ROLES | {"CONNECTOR"}
ROLE_PERMISSIONS = {
    "ADMIN": {"admin", "read", "investigate", "ingest", "ingest_status", "audit", "sandbox"},
    "PRIVACY_ANALYST": {"read", "investigate", "ingest_status"},
    "DATA_GOVERNANCE": {"read", "investigate", "ingest_status"},
    "AUDITOR": {"read", "audit", "ingest_status"},
    "VIEWER": {"read"},
    "CONNECTOR": {"ingest", "ingest_status"},
}
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
KEY_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


@dataclass(frozen=True)
class Principal:
    organization_id: str
    principal_id: str
    role: str
    authentication_method: str


def create_secret_hash(secret: str) -> str:
    salt = secrets.token_bytes(16)
    peppered_secret = (secret + settings.api_key_pepper).encode("utf-8")
    digest = hashlib.scrypt(peppered_secret, salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_secret(secret: str, encoded_hash: str) -> bool:
    try:
        algorithm, salt_text, expected_text = encoded_hash.split("$", 2)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(expected_text)
        actual = hashlib.scrypt(
            (secret + settings.api_key_pepper).encode("utf-8"),
            salt=salt,
            n=2**14,
            r=8,
            p=1,
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _encryption_key() -> bytes | None:
    if not settings.api_key_encryption_key:
        return None
    try:
        key = base64.urlsafe_b64decode(settings.api_key_encryption_key)
    except ValueError as exc:
        raise RuntimeError("API_KEY_ENCRYPTION_KEY must be URL-safe base64.") from exc
    if len(key) != 32:
        raise RuntimeError("API_KEY_ENCRYPTION_KEY must decode to 32 bytes.")
    return key


def encrypt_secret(secret: str) -> str | None:
    key = _encryption_key()
    if key is None:
        return None
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, secret.encode("utf-8"), b"consenttrace-api-key-v1")
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(ciphertext: str | None) -> str | None:
    key = _encryption_key()
    if key is None or ciphertext is None:
        return None
    packed = base64.urlsafe_b64decode(ciphertext)
    return AESGCM(key).decrypt(packed[:12], packed[12:], b"consenttrace-api-key-v1").decode("utf-8")


def generate_api_key() -> tuple[str, str, str]:
    key_id = uuid.uuid4().hex
    random_secret = secrets.token_urlsafe(32)
    secret = f"ct_{key_id}.{random_secret}"
    return key_id, secret, random_secret


def split_api_key(secret: str) -> tuple[str, str] | None:
    try:
        # The generated form is ct_<32-hex-key-id>.<random-secret>.
        prefix, separator, remainder = secret.partition("_")
        if prefix != "ct" or not separator:
            return None
        key_id, separator, token = remainder.partition(".")
        if not separator or not KEY_ID_PATTERN.fullmatch(key_id) or not token:
            return None
        return key_id, secret
    except ValueError:
        return None


def create_key_record(
    *,
    organization_id: str,
    name: str,
    role: str,
    secret: str | None = None,
    key_id: str | None = None,
) -> tuple[ApiKey, str]:
    if role not in ALL_ROLES:
        raise ValueError(f"Unsupported API key role: {role}")
    generated_id, generated_secret, _ = generate_api_key()
    secret = secret or generated_secret
    key_id = key_id or generated_id
    record = ApiKey(
        key_id=key_id,
        organization_id=organization_id,
        name=name,
        key_hash=create_secret_hash(secret),
        encrypted_secret=encrypt_secret(secret),
        role=role,
        active=True,
    )
    return record, secret


def bootstrap_configured_keys() -> None:
    configured: list[tuple[str, str, str, str]] = []
    if settings.app_mode in {"DEMO", "SANDBOX"} and settings.dev_bootstrap_api_key:
        configured.append((
            settings.dev_bootstrap_api_key,
            settings.dev_bootstrap_org_id,
            "Local development administrator",
            "ADMIN",
        ))
    if settings.app_mode == "SANDBOX" and settings.sandbox_connector_api_key:
        from app.sandbox import SANDBOX_ORGANIZATION_ID

        configured.append((
            settings.sandbox_connector_api_key,
            SANDBOX_ORGANIZATION_ID,
            "DemoCorp sandbox event connector",
            "CONNECTOR",
        ))
    if settings.app_mode == "SANDBOX" and settings.sandbox_admin_api_key:
        from app.sandbox import SANDBOX_ORGANIZATION_ID

        configured.append((
            settings.sandbox_admin_api_key,
            SANDBOX_ORGANIZATION_ID,
            "DemoCorp sandbox administrator",
            "ADMIN",
        ))
    if settings.app_mode == "PRODUCTION" and settings.production_admin_api_key:
        configured.append((
            settings.production_admin_api_key,
            settings.production_admin_org_id,
            "Initial production administrator",
            "ADMIN",
        ))

    if not configured:
        return
    with SessionLocal() as db:
        for secret, organization_id, name, role in configured:
            parsed = split_api_key(secret)
            if parsed is None:
                raise RuntimeError(f"Configured bootstrap credential for {name} must use ct_<key_id>.<secret> format.")
            key_id, _ = parsed
            existing = db.get(ApiKey, key_id)
            if existing is not None:
                if not existing.active or existing.revoked_at is not None:
                    raise RuntimeError(f"Configured bootstrap API key {key_id} has been revoked.")
                if existing.organization_id != organization_id or existing.role != role:
                    raise RuntimeError(f"Configured bootstrap API key {key_id} does not match its provisioned identity.")
                continue
            db.add(ApiKey(
                key_id=key_id,
                organization_id=organization_id,
                name=name,
                key_hash=create_secret_hash(secret),
                encrypted_secret=encrypt_secret(secret),
                role=role,
                active=True,
            ))
        db.commit()


def audit(
    *,
    request: Request,
    action: str,
    resource_type: str,
    resource_id: str | None,
    outcome: str,
    principal: Principal | None = None,
    metadata: dict | None = None,
    organization_id: str | None = None,
    principal_id: str | None = None,
    role: str | None = None,
) -> None:
    request_id = getattr(request.state, "request_id", "unavailable")
    source_ip = request.client.host if request.client else None
    record = SecurityAuditRecord(
        audit_id=uuid.uuid4().hex,
        organization_id=principal.organization_id if principal else organization_id,
        principal_id=principal.principal_id if principal else principal_id,
        role=principal.role if principal else role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        timestamp=datetime.now(timezone.utc),
        outcome=outcome,
        source_ip=source_ip,
        metadata_json=metadata or {},
    )
    record_organization_id = record.organization_id
    record_principal_id = record.principal_id
    with SessionLocal() as db:
        db.add(record)
        db.commit()
    logger.info(json.dumps({
        "request_id": request_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "outcome": outcome,
        "organization_id": record_organization_id,
        "principal_id": record_principal_id,
    }, separators=(",", ":")))


class InProcessRateLimiter:
    """Single-process fixed-window limiter; replace with Redis for multi-instance deployments."""

    def __init__(self) -> None:
        self._windows: dict[tuple[str, str], tuple[int, int]] = {}
        self._lock = threading.Lock()

    def allow(self, bucket: str, identity: str, limit: int, window_seconds: int = 60) -> bool:
        now = int(time.monotonic())
        window = now // window_seconds
        key = (bucket, identity)
        with self._lock:
            current_window, count = self._windows.get(key, (window, 0))
            if current_window != window:
                count = 0
            if count >= limit:
                self._windows[key] = (window, count)
                return False
            self._windows[key] = (window, count + 1)
            if len(self._windows) > 10000:
                self._windows = {item_key: item for item_key, item in self._windows.items() if item[0] >= window - 1}
            return True


rate_limiter = InProcessRateLimiter()


def _unauthorized(request: Request, key_id: str | None = None) -> None:
    client_ip = request.client.host if request.client else "unknown"
    request_id = getattr(request.state, "request_id", "unavailable")
    audit(
        request=request,
        action="AUTHENTICATION",
        resource_type="request",
        resource_id=request.url.path,
        outcome="failure",
        principal_id=key_id,
        metadata={"reason": "invalid_or_missing_credentials"},
    )
    if not rate_limiter.allow("auth-failure", client_ip, settings.rate_limit_auth_per_minute):
        raise HTTPException(status_code=429, detail={"error": {"code": "RATE_LIMITED", "message": "Authentication rate limit exceeded.", "request_id": request_id}})
    raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHENTICATED", "message": "Valid API credentials are required.", "request_id": request_id}})


def _signed_message(request: Request, timestamp: str, body: bytes) -> bytes:
    return b"\n".join((
        request.method.upper().encode("ascii"),
        request.url.path.encode("utf-8"),
        timestamp.encode("ascii"),
        body,
    ))


def _check_hmac_replay(key_id: str, signature: str, expires_at: datetime) -> bool:
    signature_hash = hashlib.sha256(signature.lower().encode("ascii")).hexdigest()
    with SessionLocal() as db:
        db.execute(delete(HmacReplayRecord).where(HmacReplayRecord.expires_at < datetime.now(timezone.utc)))
        db.add(HmacReplayRecord(
            replay_id=uuid.uuid4().hex,
            key_id=key_id,
            signature_hash=signature_hash,
            expires_at=expires_at,
        ))
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False


async def get_current_principal(request: Request) -> Principal:
    bearer = request.headers.get("authorization", "")
    hmac_key_id = request.headers.get("x-consenttrace-key-id")
    signing_timestamp = request.headers.get("x-consenttrace-timestamp")
    signature = request.headers.get("x-consenttrace-signature")
    auth_method = "bearer"
    key_id: str | None = None

    if hmac_key_id or signing_timestamp or signature:
        auth_method = "hmac"
        if not hmac_key_id or not signing_timestamp or not signature or not KEY_ID_PATTERN.fullmatch(hmac_key_id):
            _unauthorized(request, hmac_key_id)
        key_id = hmac_key_id
    elif bearer.startswith("Bearer "):
        parsed = split_api_key(bearer[7:].strip())
        if parsed is None:
            _unauthorized(request)
        key_id, _ = parsed
    else:
        _unauthorized(request)

    with SessionLocal() as db:
        key_record = db.execute(select(ApiKey).where(ApiKey.key_id == key_id)).scalars().first()
        if key_record is None or not key_record.active or key_record.revoked_at is not None:
            _unauthorized(request, key_id)

        if auth_method == "bearer":
            parsed = split_api_key(bearer[7:].strip())
            if parsed is None or not verify_secret(parsed[1], key_record.key_hash):
                _unauthorized(request, key_id)
        else:
            try:
                issued_at = int(signing_timestamp)
                now = int(time.time())
                if abs(now - issued_at) > settings.hmac_replay_window_seconds:
                    _unauthorized(request, key_id)
                hmac_secret = decrypt_secret(key_record.encrypted_secret)
                if hmac_secret is None or not re.fullmatch(r"[a-fA-F0-9]{64}", signature):
                    _unauthorized(request, key_id)
                expected = hmac.new(
                    hmac_secret.encode("utf-8"),
                    _signed_message(request, signing_timestamp, await request.body()),
                    hashlib.sha256,
                ).hexdigest()
                if not hmac.compare_digest(expected, signature.lower()):
                    _unauthorized(request, key_id)
                expires_at = datetime.fromtimestamp(issued_at + settings.hmac_replay_window_seconds, timezone.utc)
                if not _check_hmac_replay(key_id, signature, expires_at):
                    _unauthorized(request, key_id)
            except (ValueError, UnicodeEncodeError):
                _unauthorized(request, key_id)

        key_record.last_used_at = datetime.now(timezone.utc)
        principal = Principal(
            organization_id=key_record.organization_id,
            principal_id=key_record.key_id,
            role=key_record.role,
            authentication_method=auth_method,
        )
        db.commit()

    request.state.principal = principal
    audit(
        request=request,
        action="AUTHENTICATION",
        resource_type="request",
        resource_id=request.url.path,
        outcome="success",
        principal=principal,
        metadata={"authentication_method": auth_method},
    )
    return principal


def require_roles(*roles: str) -> Callable:
    async def dependency(
        request: Request,
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if principal.role not in roles:
            audit(
                request=request,
                action="AUTHORIZATION",
                resource_type="request",
                resource_id=request.url.path,
                outcome="denied",
                principal=principal,
                metadata={"required_roles": list(roles)},
            )
            raise HTTPException(status_code=403, detail={"error": {"code": "FORBIDDEN", "message": "This API key role cannot perform the requested operation."}})
        return principal
    return dependency


def require_permission(permission: str) -> Callable:
    async def dependency(
        request: Request,
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if permission not in ROLE_PERMISSIONS.get(principal.role, set()):
            audit(
                request=request,
                action="AUTHORIZATION",
                resource_type="request",
                resource_id=request.url.path,
                outcome="denied",
                principal=principal,
                metadata={"required_permission": permission},
            )
            raise HTTPException(status_code=403, detail={"error": {"code": "FORBIDDEN", "message": "This API key role cannot perform the requested operation."}})
        return principal
    return dependency


def enforce_rate_limit(request: Request, principal: Principal, action: str, limit: int) -> None:
    if not rate_limiter.allow(action, principal.principal_id, limit):
        request_id = getattr(request.state, "request_id", "unavailable")
        audit(
            request=request,
            action="RATE_LIMIT",
            resource_type="request",
            resource_id=request.url.path,
            outcome="rejected",
            principal=principal,
            metadata={"bucket": action},
        )
        raise HTTPException(status_code=429, detail={"error": {"code": "RATE_LIMITED", "message": "Request rate limit exceeded.", "request_id": request_id}})


class RequestSizeLimitMiddleware:
    def __init__(self, app, *, max_json_body_bytes: int, max_ingestion_event_bytes: int, max_evidence_payload_bytes: int):
        self.app = app
        self.max_json_body_bytes = max_json_body_bytes
        self.max_ingestion_event_bytes = max_ingestion_event_bytes
        self.max_evidence_payload_bytes = max_evidence_payload_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        limit = self.max_ingestion_event_bytes if path == "/api/v1/ingest/events" else self.max_json_body_bytes
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        request_id = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        if not SAFE_REQUEST_ID.fullmatch(request_id):
            request_id = uuid.uuid4().hex

        async def reject_too_large() -> None:
            body = json.dumps({
                "error": {
                    "code": "REQUEST_TOO_LARGE",
                    "message": "Request body exceeds the configured size limit.",
                    "request_id": request_id,
                }
            }).encode()
            await send({
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"x-request-id", request_id.encode())],
            })
            await send({"type": "http.response.body", "body": body})

        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > limit:
                    await reject_too_large()
                    return
            except ValueError:
                await reject_too_large()
                return

        chunks: list[bytes] = []
        size = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > limit:
                await reject_too_large()
                return
            chunks.append(chunk)
            more_body = message.get("more_body", False)

        raw_body = b"".join(chunks)
        if path == "/api/v1/ingest/events" and raw_body and b"application/json" in headers.get(b"content-type", b""):
            try:
                document = json.loads(raw_body)
                evidence_size = len(json.dumps({
                    "payload": document.get("payload", {}),
                    "evidence_metadata": document.get("evidence_metadata", {}),
                }, sort_keys=True, separators=(",", ":")).encode())
            except (json.JSONDecodeError, AttributeError, TypeError):
                evidence_size = 0
            if evidence_size > self.max_evidence_payload_bytes:
                await reject_too_large()
                return

        delivered = False

        async def replay_body():
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": raw_body, "more_body": False}

        await self.app(scope, replay_body, send)
