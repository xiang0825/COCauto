"""手机端与桌面机器人之间的安全控制原语。

网络线程只完成配对、授权和排队；实际控制由 Tk 主线程调用
``SerializedCommandBroker.process_pending`` 串行执行。
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import os
import queue
import secrets
import ssl
import threading
import tempfile
import time
import base64
import http.server
import socket
import urllib.parse
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, ClassVar, Mapping


class Unauthorized(PermissionError):
    """配对码、访问令牌或机器人/计划绑定无效。"""


class StaleRevisionError(ValueError):
    """命令基于过期的桌面状态。"""


class QueueFullError(RuntimeError):
    """手机控制队列已满。"""


class PairingRateLimitedError(RuntimeError):
    """配对码错误次数过多。"""


class RequestConflictError(ValueError):
    """同一个幂等请求 ID 被用于不同命令。"""


class SecretStoreError(RuntimeError):
    """当前 Windows 用户无法安全读取或写入配对凭据。"""


def _dpapi_protect(data: bytes, description: str) -> bytes:
    try:
        import win32crypt

        return win32crypt.CryptProtectData(data, description, None, None, None, 0)
    except Exception as error:
        raise SecretStoreError("无法使用当前 Windows 用户 DPAPI 保护凭据") from error


def _dpapi_unprotect(data: bytes, description: str) -> bytes:
    try:
        import win32crypt

        stored_description, plaintext = win32crypt.CryptUnprotectData(
            data, None, None, None, 0
        )
        if stored_description != description:
            raise ValueError("DPAPI 凭据用途标记不匹配")
        return plaintext
    except Exception as error:
        raise SecretStoreError("无法解密或校验 DPAPI 凭据") from error


@dataclass(frozen=True)
class PairingTicket:
    code: str
    expires_at: float
    robot_id: str
    plan_fingerprint: str


@dataclass(frozen=True)
class TokenBinding:
    client_id: str
    robot_id: str
    plan_fingerprint: str
    issued_at: float


@dataclass(frozen=True)
class PairingGrant:
    token: str
    binding: TokenBinding


class DpapiTokenStore:
    """使用当前 Windows 用户 DPAPI 加密桌面端访问令牌摘要和绑定信息。"""

    _DESCRIPTION = "CoC paired phone bindings v1"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> dict[str, TokenBinding]:
        with self._lock:
            if not self.path.exists():
                return {}
            try:
                plaintext = _dpapi_unprotect(
                    self.path.read_bytes(), self._DESCRIPTION
                )
                document = json.loads(plaintext.decode("utf-8"))
                if document.get("version") != 1 or not isinstance(
                    document.get("tokens"), dict
                ):
                    raise ValueError("凭据文件版本或结构无效")
                bindings = {}
                for digest, raw in document["tokens"].items():
                    if (
                        not isinstance(digest, str)
                        or len(digest) != 64
                        or any(ch not in "0123456789abcdef" for ch in digest)
                        or not isinstance(raw, dict)
                    ):
                        raise ValueError("凭据绑定条目无效")
                    binding = TokenBinding(
                        client_id=str(raw["client_id"]),
                        robot_id=str(raw["robot_id"]),
                        plan_fingerprint=str(raw["plan_fingerprint"]),
                        issued_at=float(raw["issued_at"]),
                    )
                    if not all(
                        (
                            binding.client_id,
                            binding.robot_id,
                            binding.plan_fingerprint,
                        )
                    ):
                        raise ValueError("凭据绑定缺少客户端、机器人或任务计划")
                    bindings[digest] = binding
                return bindings
            except Exception as error:
                raise SecretStoreError("无法解密或校验手机配对凭据；远程控制已关闭") from error

    def save(self, bindings: Mapping[str, TokenBinding]) -> None:
        document = {
            "version": 1,
            "tokens": {
                digest: {
                    "client_id": binding.client_id,
                    "robot_id": binding.robot_id,
                    "plan_fingerprint": binding.plan_fingerprint,
                    "issued_at": binding.issued_at,
                }
                for digest, binding in bindings.items()
            },
        }
        plaintext = json.dumps(
            document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        protected = _dpapi_protect(plaintext, self._DESCRIPTION)

        temporary_path = None
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=self.path.name + ".",
                    suffix=".tmp",
                    dir=self.path.parent,
                    delete=False,
                ) as temporary:
                    temporary.write(protected)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_path = Path(temporary.name)
                os.replace(temporary_path, self.path)
            except Exception as error:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise SecretStoreError("无法原子保存 DPAPI 保护的配对凭据") from error


@dataclass(frozen=True)
class TlsIdentity:
    certificate_pem: bytes
    private_key_pem: bytes
    fingerprint: str
    bind_address: str

    _DESCRIPTION: ClassVar[str] = "CoC local TLS identity v1"

    @classmethod
    def load_or_create(cls, path: str | Path, bind_address: str) -> "TlsIdentity":
        """加载稳定证书；接口地址变化时生成新证书并要求手机重新配对。"""
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
        except Exception as error:
            raise SecretStoreError("缺少 TLS 证书依赖 cryptography") from error

        path = Path(path)
        certificate_pem = None
        private_key_pem = None
        if path.exists():
            try:
                document = json.loads(
                    _dpapi_unprotect(path.read_bytes(), cls._DESCRIPTION).decode(
                        "utf-8"
                    )
                )
                if document.get("version") == 1 and document.get("bind_address") == bind_address:
                    certificate_pem = base64.b64decode(
                        document["certificate_pem"], validate=True
                    )
                    private_key_pem = base64.b64decode(
                        document["private_key_pem"], validate=True
                    )
                    loaded_certificate = x509.load_pem_x509_certificate(
                        certificate_pem
                    )
                    now = datetime.now(timezone.utc)
                    if now >= loaded_certificate.not_valid_after_utc:
                        certificate_pem = None
                        private_key_pem = None
                    elif now < loaded_certificate.not_valid_before_utc:
                        raise ValueError("TLS 证书尚未生效")
            except SecretStoreError:
                raise
            except Exception as error:
                raise SecretStoreError("无法读取持久 TLS 身份；远程控制已关闭") from error

        if certificate_pem is None or private_key_pem is None:
            private_key = ec.generate_private_key(ec.SECP256R1())
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CoC local agent")])
            now = datetime.now(timezone.utc)
            ip_value = ipaddress.ip_address(bind_address)
            certificate = (
                x509.CertificateBuilder()
                .subject_name(name)
                .issuer_name(name)
                .public_key(private_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1))
                .not_valid_after(now + timedelta(days=730))
                .add_extension(
                    x509.SubjectAlternativeName([x509.IPAddress(ip_value)]),
                    critical=False,
                )
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
                .add_extension(
                    x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                    critical=False,
                )
                .sign(private_key, hashes.SHA256())
            )
            certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)
            private_key_pem = private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            document = {
                "version": 1,
                "bind_address": bind_address,
                "certificate_pem": base64.b64encode(certificate_pem).decode("ascii"),
                "private_key_pem": base64.b64encode(private_key_pem).decode("ascii"),
            }
            protected = _dpapi_protect(
                json.dumps(document, separators=(",", ":"), sort_keys=True).encode(
                    "utf-8"
                ),
                cls._DESCRIPTION,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=path.name + ".",
                    suffix=".tmp",
                    dir=path.parent,
                    delete=False,
                ) as temporary:
                    temporary.write(protected)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_path = Path(temporary.name)
                os.replace(temporary_path, path)
            except Exception as error:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise SecretStoreError("无法保存 DPAPI 保护的 TLS 身份") from error

        try:
            certificate = x509.load_pem_x509_certificate(certificate_pem)
            private_key = serialization.load_pem_private_key(private_key_pem, None)
            expected_public = certificate.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            actual_public = private_key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            if expected_public != actual_public:
                raise ValueError("证书和私钥不匹配")
            san = certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
            now = datetime.now(timezone.utc)
            if not (
                certificate.not_valid_before_utc
                <= now
                < certificate.not_valid_after_utc
            ):
                raise ValueError("TLS 证书不在有效期内")
            if ipaddress.ip_address(bind_address) not in san.get_values_for_type(
                x509.IPAddress
            ):
                raise ValueError("TLS 证书没有所选接口地址")
            fingerprint = certificate.fingerprint(hashes.SHA256()).hex().upper()
        except Exception as error:
            raise SecretStoreError("TLS 身份证书校验失败；远程控制已关闭") from error
        return cls(certificate_pem, private_key_pem, fingerprint, bind_address)

    def create_server_context(self) -> ssl.SSLContext:
        """加载密钥后立即删除 PEM 临时文件；磁盘长期只保留 DPAPI 密文。"""
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        with tempfile.TemporaryDirectory(prefix="coc-tls-context-") as temporary:
            certificate_path = Path(temporary) / "server-cert.pem"
            private_key_path = Path(temporary) / "server-key.pem"
            certificate_path.write_bytes(self.certificate_pem)
            private_key_path.write_bytes(self.private_key_pem)
            context.load_cert_chain(str(certificate_path), str(private_key_path))
        return context


class PairingAuthority:
    """单次五分钟配对码及绑定到一个客户端/机器人/任务计划的令牌。"""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        code_factory: Callable[[], str] | None = None,
        token_factory: Callable[[], str] | None = None,
        token_store: DpapiTokenStore | None = None,
    ):
        self._clock = clock
        self._code_factory = code_factory or (lambda: f"{secrets.randbelow(1_000_000):06d}")
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._ticket: PairingTicket | None = None
        self._token_store = token_store
        self._tokens: dict[str, TokenBinding] = (
            token_store.load() if token_store is not None else {}
        )
        self._lock = threading.RLock()

    def begin_pairing(
        self,
        robot_id: str,
        plan_fingerprint: str,
        *,
        ttl_seconds: float = 300,
    ) -> PairingTicket:
        robot_id = str(robot_id or "").strip()
        plan_fingerprint = str(plan_fingerprint or "").strip()
        if not robot_id or not plan_fingerprint:
            raise ValueError("配对必须绑定机器人和已保存的任务计划")
        if not 0 < float(ttl_seconds) <= 300:
            raise ValueError("配对码有效期必须在五分钟以内")
        code = str(self._code_factory())
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            raise ValueError("配对码生成器必须返回六位数字")
        ticket = PairingTicket(
            code=code,
            expires_at=self._clock() + float(ttl_seconds),
            robot_id=robot_id,
            plan_fingerprint=plan_fingerprint,
        )
        with self._lock:
            self._ticket = ticket
        return ticket

    def exchange_code(self, code: str, client_id: str) -> PairingGrant:
        candidate = str(code or "")
        client_id = str(client_id or "").strip()
        if not client_id or len(client_id) > 128:
            raise Unauthorized("配对失败")
        with self._lock:
            ticket = self._ticket
            if ticket is None or self._clock() >= ticket.expires_at:
                self._ticket = None
                raise Unauthorized("配对失败")
            if not candidate.isascii() or not hmac.compare_digest(
                candidate, ticket.code
            ):
                raise Unauthorized("配对失败")

            token = str(self._token_factory())
            if len(token) < 32:
                raise RuntimeError("访问令牌生成器返回了过短的令牌")
            binding = TokenBinding(
                client_id=client_id,
                robot_id=ticket.robot_id,
                plan_fingerprint=ticket.plan_fingerprint,
                issued_at=self._clock(),
            )
            digest = self._token_digest(token)
            self._tokens[digest] = binding
            try:
                self._persist_tokens()
            except Exception:
                self._tokens.pop(digest, None)
                raise
            self._ticket = None
            return PairingGrant(token=token, binding=binding)

    def authenticate(
        self,
        token: str,
        robot_id: str | None = None,
        plan_fingerprint: str | None = None,
    ) -> TokenBinding:
        candidate = str(token or "")
        if not candidate:
            raise Unauthorized("未授权")
        digest = self._token_digest(candidate)
        with self._lock:
            binding = next(
                (
                    item
                    for known_digest, item in self._tokens.items()
                    if hmac.compare_digest(digest, known_digest)
                ),
                None,
            )
        if binding is None:
            raise Unauthorized("未授权")
        if robot_id is not None and not hmac.compare_digest(
            binding.robot_id, str(robot_id)
        ):
            raise Unauthorized("未授权")
        if plan_fingerprint is not None and not hmac.compare_digest(
            binding.plan_fingerprint, str(plan_fingerprint)
        ):
            raise Unauthorized("任务计划已变化，请重新配对")
        return binding

    def revoke(self, token: str) -> bool:
        digest = self._token_digest(str(token or ""))
        with self._lock:
            binding = self._tokens.pop(digest, None)
            if binding is None:
                return False
            try:
                self._persist_tokens()
            except Exception:
                self._tokens[digest] = binding
                raise
            return True

    def revoke_all(self) -> int:
        """撤销所有手机令牌并使尚未兑换的配对码失效。"""
        with self._lock:
            previous = self._tokens
            self._tokens = {}
            self._ticket = None
            try:
                self._persist_tokens()
            except Exception:
                self._tokens = previous
                raise
            return len(previous)

    def _persist_tokens(self) -> None:
        if self._token_store is not None:
            self._token_store.save(self._tokens)

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PairingAttemptLimiter:
    """按来源 IP 限制短时配对失败次数，并限制追踪状态的内存上限。"""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        limit: int = 5,
        window_seconds: float = 60.0,
        max_clients: int = 4096,
    ):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("配对失败次数上限必须是正整数")
        if (
            isinstance(window_seconds, bool)
            or not math.isfinite(float(window_seconds))
            or window_seconds <= 0
        ):
            raise ValueError("配对失败统计窗口必须是正数")
        if isinstance(max_clients, bool) or not isinstance(max_clients, int) or max_clients < 1:
            raise ValueError("配对来源追踪容量必须是正整数")
        self._clock = clock
        self._limit = limit
        self._window_seconds = float(window_seconds)
        self._max_clients = max_clients
        self._attempts: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def _key(address: str) -> str:
        try:
            candidate = str(address).split("%", 1)[0]
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            return ""

    def _live_attempts(self, key: str, now: float) -> list[float]:
        attempts = self._attempts.get(key, [])
        cutoff = now - self._window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.pop(0)
        if attempts:
            self._attempts.move_to_end(key)
        else:
            self._attempts.pop(key, None)
        return attempts

    def allow(self, address: str) -> bool:
        key = self._key(address)
        if not key:
            return False
        now = float(self._clock())
        if not math.isfinite(now):
            return False
        with self._lock:
            return len(self._live_attempts(key, now)) < self._limit

    def record_failure(self, address: str) -> None:
        key = self._key(address)
        if not key:
            return
        now = float(self._clock())
        if not math.isfinite(now):
            return
        with self._lock:
            attempts = self._live_attempts(key, now)
            if len(attempts) >= self._limit:
                return
            if key not in self._attempts and len(self._attempts) >= self._max_clients:
                self._attempts.popitem(last=False)
            self._attempts.setdefault(key, attempts).append(now)
            self._attempts.move_to_end(key)

    def record_success(self, address: str) -> None:
        key = self._key(address)
        if key:
            with self._lock:
                self._attempts.pop(key, None)


@dataclass
class _QueuedCommand:
    command: str
    expected_revision: int
    request_id: str
    future: Future


class SerializedCommandBroker:
    """将远程输入排队，且只允许 UI 主线程串行执行固定控制命令。"""

    ALLOWED_COMMANDS = frozenset({"start", "pause", "stop"})

    def __init__(
        self,
        *,
        revision_provider: Callable[[], int],
        execute: Callable[[str], object],
        max_queue: int = 64,
        request_cache_size: int = 512,
    ):
        if max_queue < 1 or request_cache_size < 1:
            raise ValueError("队列和幂等缓存容量必须大于零")
        self._revision_provider = revision_provider
        self._execute = execute
        self._queue: queue.Queue[_QueuedCommand] = queue.Queue(maxsize=max_queue)
        self._requests: OrderedDict[str, tuple[str, int, Future]] = OrderedDict()
        self._request_cache_size = request_cache_size
        self._lock = threading.RLock()
        self._closed = False

    def submit(self, command: str, *, expected_revision: int, request_id: str) -> Future:
        command = str(command or "").strip().lower()
        request_id = str(request_id or "").strip()
        if command not in self.ALLOWED_COMMANDS:
            raise ValueError("仅允许 start、pause、stop 控制命令")
        if not request_id or len(request_id) > 128:
            raise ValueError("缺少有效的幂等请求 ID")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError("状态修订号必须是整数")

        with self._lock:
            if self._closed:
                raise RuntimeError("远程控制服务已关闭")
            cached = self._requests.get(request_id)
            if cached is not None:
                prior_command, prior_revision, prior_future = cached
                if (prior_command, prior_revision) != (command, expected_revision):
                    raise RequestConflictError("请求 ID 已用于另一条命令")
                self._requests.move_to_end(request_id)
                return prior_future

            current_revision = self._read_revision()
            if expected_revision != current_revision:
                raise StaleRevisionError("桌面状态已变化，请刷新后重试")

            future = Future()
            item = _QueuedCommand(command, expected_revision, request_id, future)
            try:
                self._queue.put_nowait(item)
            except queue.Full as error:
                raise QueueFullError("远程控制队列已满") from error
            self._requests[request_id] = (command, expected_revision, future)
            while len(self._requests) > self._request_cache_size:
                self._requests.popitem(last=False)
            return future

    def process_pending(self, *, limit: int = 32) -> int:
        """由 Tk 主线程调用；每批最多执行一个命令。"""
        if limit < 1:
            return 0
        with self._lock:
            batch = []
            for _ in range(min(limit, self._queue.qsize())):
                try:
                    batch.append(self._queue.get_nowait())
                    self._queue.task_done()
                except queue.Empty:
                    break

        if not batch:
            return 0

        stops = [item for item in batch if item.command == "stop"]
        pauses = [item for item in batch if item.command == "pause"]
        selected = (stops or pauses or batch)[0]
        for item in batch:
            if item is not selected:
                self._resolve(item.future, {"status": "superseded"})

        if selected.expected_revision != self._read_revision():
            self._resolve(
                selected.future,
                {"status": "stale", "revision": self._read_revision()},
            )
            return len(batch)

        try:
            result = self._execute(selected.command)
        except Exception:
            # 网络响应不携带异常堆栈、路径或设备参数。
            self._resolve(selected.future, {"status": "error", "message": "命令执行失败"})
        else:
            payload = dict(result) if isinstance(result, Mapping) else {"result": result}
            self._resolve(selected.future, {"status": "applied", **payload})
        return len(batch)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            while True:
                try:
                    item = self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break
                self._resolve(item.future, {"status": "unavailable"})
            self._requests.clear()

    def _read_revision(self) -> int:
        revision = self._revision_provider()
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise TypeError("revision_provider 必须返回整数")
        return revision

    @staticmethod
    def _resolve(future: Future, result: dict) -> None:
        if not future.done():
            future.set_result(result)


def validate_bind_address(address: str, local_addresses) -> str:
    """只接受显式选择的本机私有 LAN 地址，拒绝通配或公网监听。"""
    try:
        parsed = ipaddress.ip_address(str(address).strip())
    except ValueError as error:
        raise ValueError("请选择有效的本机 LAN 地址") from error
    if (
        not parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_unspecified
        or parsed.is_multicast
        or parsed.is_reserved
    ):
        raise ValueError("远程控制只能绑定本机私有 LAN 地址")
    normalized_local = set()
    for candidate in local_addresses or ():
        try:
            normalized_local.add(ipaddress.ip_address(str(candidate).strip()))
        except ValueError:
            continue
    if parsed not in normalized_local:
        raise ValueError("所选地址不属于本机网络接口")
    return str(parsed)


def list_private_local_addresses() -> tuple[str, ...]:
    """枚举可选的本机私有接口地址，不返回公网、回环或链路本地地址。"""
    addresses = set()
    try:
        candidates = socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except OSError:
        candidates = ()
    for result in candidates:
        try:
            parsed = ipaddress.ip_address(result[4][0])
        except ValueError:
            continue
        if (
            parsed.is_private
            and not parsed.is_loopback
            and not parsed.is_link_local
            and not parsed.is_unspecified
            and not parsed.is_multicast
            and not parsed.is_reserved
        ):
            addresses.add(str(parsed))
    return tuple(sorted(addresses))


def pairing_qr_payload(
    endpoint: str, code: str, fingerprint: str, robot_id: str
) -> str:
    """二维码仅携带局域网端点、一次性码和证书指纹，不含长期令牌。"""
    if not endpoint.startswith("https://"):
        raise ValueError("手机配对端点必须使用 HTTPS")
    normalized_fingerprint = str(fingerprint or "").replace(":", "").upper()
    if len(normalized_fingerprint) != 64 or any(
        char not in "0123456789ABCDEF" for char in normalized_fingerprint
    ):
        raise ValueError("TLS 指纹必须是 SHA-256 十六进制值")
    if len(str(code)) != 6 or not str(code).isascii() or not str(code).isdigit():
        raise ValueError("二维码配对码必须是六位数字")
    if not str(robot_id or "").strip():
        raise ValueError("二维码必须绑定桌面机器人")
    return json.dumps(
        {
            "api_version": 1,
            "endpoint": endpoint,
            "pair_code": str(code),
            "fingerprint": normalized_fingerprint,
            "robot_id": str(robot_id),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def create_pairing_qr_image(payload: str):
    """生成适合桌面展示和手机扫描的二维码图像。"""
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_M
    except Exception as error:
        raise RuntimeError("缺少二维码依赖 qrcode") from error
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=5,
        border=3,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="#233142", back_color="white").convert("RGB")


class PlanChangedError(RuntimeError):
    """桌面保存的任务计划已不同于手机配对时的计划。"""


class MobileControlServer:
    """私有接口 HTTPS 服务；控制请求必须回到 UI 线程的 broker。"""

    API_VERSION = 1
    DEFAULT_PORT = 47652
    MAX_BODY_BYTES = 8192
    MAX_LOG_ITEMS = 100
    COMMAND_TIMEOUT_SECONDS = 4.0

    def __init__(
        self,
        *,
        bind_address: str,
        local_addresses,
        port: int,
        tls_identity: TlsIdentity,
        pairing_authority: PairingAuthority,
        command_broker: SerializedCommandBroker,
        snapshot_provider: Callable[[str], Mapping],
        logs_provider: Callable[[str, float, int], list] | None = None,
        pairing_attempt_limiter: PairingAttemptLimiter | None = None,
        command_timeout: float = COMMAND_TIMEOUT_SECONDS,
    ):
        self.bind_address = validate_bind_address(bind_address, local_addresses)
        if tls_identity.bind_address != self.bind_address:
            raise ValueError("TLS 证书与所选本机接口地址不匹配")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("HTTPS 端口必须在 0 至 65535 之间")
        self.port = port
        self.tls_identity = tls_identity
        self.pairing_authority = pairing_authority
        self.command_broker = command_broker
        self.snapshot_provider = snapshot_provider
        self.logs_provider = logs_provider or (lambda _robot, _after, _limit: [])
        self.pairing_attempt_limiter = (
            pairing_attempt_limiter or PairingAttemptLimiter()
        )
        self.command_timeout = max(0.1, min(float(command_timeout), 10.0))
        self._server = None
        self._thread = None
        self._server_lock = threading.RLock()

    @property
    def endpoint(self) -> str:
        host = f"[{self.bind_address}]" if ":" in self.bind_address else self.bind_address
        return f"https://{host}:{self.port}"

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> "MobileControlServer":
        with self._server_lock:
            if self._server is not None:
                return self
            address_family = (
                socket.AF_INET6 if ":" in self.bind_address else socket.AF_INET
            )
            server_class = type(
                "_BoundedCoCControlHTTPServer",
                (http.server.ThreadingHTTPServer,),
                {
                    "address_family": address_family,
                    "allow_reuse_address": False,
                    "daemon_threads": True,
                    "request_queue_size": 16,
                },
            )
            server = server_class(
                self._server_address(), self._make_handler(), bind_and_activate=True
            )
            try:
                server.socket = self.tls_identity.create_server_context().wrap_socket(
                    server.socket, server_side=True
                )
            except Exception:
                server.server_close()
                raise
            server.timeout = 0.5
            self._server = server
            self.port = int(server.server_address[1])
            self._thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.2},
                name="CoC 手机 HTTPS 控制服务",
                daemon=True,
            )
            try:
                self._thread.start()
            except Exception:
                self._server = None
                self._thread = None
                server.server_close()
                raise
            return self

    def begin_pairing(
        self, robot_id: str, plan_fingerprint: str, *, ttl_seconds: float = 300
    ) -> dict:
        if not self.is_running:
            raise RuntimeError("请先启动本机 HTTPS 服务")
        snapshot = self._read_snapshot(robot_id)
        if snapshot["plan_fingerprint"] != plan_fingerprint:
            raise PlanChangedError("配对请求的任务计划已变化，请刷新桌面页面")
        ticket = self.pairing_authority.begin_pairing(
            robot_id, plan_fingerprint, ttl_seconds=ttl_seconds
        )
        payload = pairing_qr_payload(
            self.endpoint,
            ticket.code,
            self.tls_identity.fingerprint,
            ticket.robot_id,
        )
        return {
            "code": ticket.code,
            "expires_at": ticket.expires_at,
            "endpoint": self.endpoint,
            "fingerprint": self.tls_identity.fingerprint,
            "robot_id": ticket.robot_id,
            "qr_payload": payload,
        }

    def process_pending(self) -> int:
        """供 Tk 的 root.after 回调调用；网络线程绝不直接触碰机器人或 UI。"""
        return self.command_broker.process_pending(limit=8)

    def close(self) -> None:
        with self._server_lock:
            server, thread = self._server, self._thread
            self._server = None
            self._thread = None
        if server is not None:
            try:
                server.shutdown()
            finally:
                server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        self.command_broker.close()

    def _server_address(self):
        if ":" in self.bind_address:
            return (self.bind_address, self.port, 0, 0)
        return (self.bind_address, self.port)

    def _read_snapshot(self, robot_id: str) -> dict:
        raw = self.snapshot_provider(robot_id)
        if not isinstance(raw, Mapping):
            raise RuntimeError("桌面状态不可用")
        try:
            revision = raw["revision"]
            if isinstance(revision, bool) or not isinstance(revision, int):
                raise ValueError("状态修订号无效")
            plan = str(raw["plan_fingerprint"])
            state = str(raw["state"])
        except Exception as error:
            raise RuntimeError("桌面状态契约无效") from error
        raw_tasks = raw.get("selected_tasks")
        if not isinstance(raw_tasks, (list, tuple)):
            raw_tasks = ()
        game_installed = raw.get("game_installed")
        return {
            "api_version": self.API_VERSION,
            "robot_id": str(robot_id),
            "plan_fingerprint": plan,
            "revision": revision,
            "state": state[:64],
            "stop_reason": str(raw.get("stop_reason", ""))[:160],
            "selected_tasks": [
                str(item)[:80]
                for item in list(raw_tasks)[:32]
                if str(item).strip()
            ],
            "version": str(raw.get("version", ""))[:64],
            "adb_connected": bool(raw.get("adb_connected", False)),
            "adb_state": str(raw.get("adb_state", "未知"))[:64],
            "game_installed": (
                None if game_installed is None else bool(game_installed)
            ),
            "game_state": str(raw.get("game_state", "未知"))[:64],
            "last_step": str(raw.get("last_step", ""))[:160],
        }

    def _authorize(self, handler):
        header = str(handler.headers.get("Authorization", ""))
        scheme, separator, token = header.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise Unauthorized("未授权")
        binding = self.pairing_authority.authenticate(token.strip())
        snapshot = self._read_snapshot(binding.robot_id)
        if snapshot["plan_fingerprint"] != binding.plan_fingerprint:
            raise PlanChangedError("任务计划已变化，请重新配对")
        return binding, snapshot

    def _make_handler(self):
        control_server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "CoC-Control"
            sys_version = ""

            def setup(self):
                super().setup()
                self.connection.settimeout(5.0)

            def log_message(self, _format, *_args):
                return

            def _send(self, status: int, payload: Mapping, *, headers=None):
                body = json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                self.close_connection = True

            def _read_json(self):
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("请求必须使用 application/json")
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("不接受分块请求体")
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                except ValueError as error:
                    raise ValueError("请求体长度无效") from error
                if length < 0 or length > control_server.MAX_BODY_BYTES:
                    raise ValueError("请求体过大或长度缺失")
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception as error:
                    raise ValueError("JSON 请求体无效") from error
                if not isinstance(payload, dict):
                    raise ValueError("请求体必须是 JSON 对象")
                return payload

            def _error(self, error):
                if isinstance(error, Unauthorized):
                    status = 401
                elif isinstance(error, PairingRateLimitedError):
                    status = 429
                elif isinstance(error, PlanChangedError):
                    status = 409
                elif isinstance(error, StaleRevisionError):
                    status = 409
                elif isinstance(error, QueueFullError):
                    status = 429
                elif isinstance(error, RequestConflictError):
                    status = 409
                elif isinstance(error, ValueError):
                    status = 400
                else:
                    status = 503
                message = str(error) if status in (400, 409, 429) else "请求无法完成"
                self._send(status, {"error": message})

            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                try:
                    binding, snapshot = control_server._authorize(self)
                    if path == "/v1/status":
                        return self._send(200, snapshot)
                    if path == "/v1/logs":
                        query = urllib.parse.parse_qs(
                            urllib.parse.urlsplit(self.path).query, strict_parsing=False
                        )
                        after = float((query.get("after") or ["0"])[0])
                        if not math.isfinite(after) or after < 0:
                            raise ValueError("日志游标必须是非负有限数值")
                        limit = min(
                            control_server.MAX_LOG_ITEMS,
                            max(1, int((query.get("limit") or ["30"])[0])),
                        )
                        entries = control_server.logs_provider(
                            binding.robot_id, after, limit
                        )
                        safe_entries = []
                        for entry in list(entries or [])[:limit]:
                            if not isinstance(entry, Mapping):
                                continue
                            safe_entries.append(
                                {
                                    "time": float(entry.get("time", 0) or 0),
                                    "level": str(entry.get("level", "info"))[:16],
                                    "message": str(
                                        entry.get("message", entry.get("text", ""))
                                    )[:500],
                                }
                            )
                        return self._send(
                            200,
                            {
                                "api_version": control_server.API_VERSION,
                                "robot_id": binding.robot_id,
                                "logs": safe_entries,
                            },
                        )
                    return self._send(404, {"error": "not found"})
                except Exception as error:
                    return self._error(error)

            def do_POST(self):
                path = urllib.parse.urlsplit(self.path).path
                try:
                    payload = self._read_json()
                    if path == "/v1/pair":
                        client_address = str(self.client_address[0])
                        if not control_server.pairing_attempt_limiter.allow(
                            client_address
                        ):
                            raise PairingRateLimitedError(
                                "配对请求过多，请稍后重试"
                            )
                        if set(payload) != {"code", "client_id"}:
                            control_server.pairing_attempt_limiter.record_failure(
                                client_address
                            )
                            raise ValueError("配对请求字段无效")
                        try:
                            grant = control_server.pairing_authority.exchange_code(
                                payload["code"], payload["client_id"]
                            )
                        except Unauthorized:
                            control_server.pairing_attempt_limiter.record_failure(
                                client_address
                            )
                            raise
                        control_server.pairing_attempt_limiter.record_success(
                            client_address
                        )
                        snapshot = control_server._read_snapshot(
                            grant.binding.robot_id
                        )
                        if snapshot["plan_fingerprint"] != grant.binding.plan_fingerprint:
                            control_server.pairing_authority.revoke(grant.token)
                            raise PlanChangedError("任务计划已变化，请重新生成配对码")
                        return self._send(
                            200,
                            {
                                "api_version": control_server.API_VERSION,
                                "access_token": grant.token,
                                "token_type": "Bearer",
                                "robot_id": grant.binding.robot_id,
                                "plan_fingerprint": grant.binding.plan_fingerprint,
                                "certificate_fingerprint": control_server.tls_identity.fingerprint,
                            },
                        )

                    binding, snapshot = control_server._authorize(self)
                    if path == "/v1/control":
                        if set(payload) != {"command", "revision", "request_id"}:
                            raise ValueError("控制请求只接受 command、revision 和 request_id")
                        future = control_server.command_broker.submit(
                            payload["command"],
                            expected_revision=payload["revision"],
                            request_id=payload["request_id"],
                        )
                        try:
                            result = future.result(
                                timeout=control_server.command_timeout
                            )
                        except TimeoutError:
                            return self._send(
                                202,
                                {
                                    "status": "queued",
                                    "request_id": str(payload["request_id"]),
                                    "robot_id": binding.robot_id,
                                },
                            )
                        status = result.get("status")
                        http_status = {
                            "applied": 200,
                            "stale": 409,
                            "superseded": 409,
                            "unavailable": 503,
                            "error": 503,
                        }.get(status, 503)
                        return self._send(http_status, result)
                    if path == "/v1/unpair":
                        if payload:
                            raise ValueError("解除配对请求不接受额外字段")
                        control_server.pairing_authority.revoke(
                            self._bearer_token()
                        )
                        return self._send(200, {"status": "unpaired"})
                    return self._send(404, {"error": "not found"})
                except Exception as error:
                    return self._error(error)

            def _bearer_token(self):
                header = str(self.headers.get("Authorization", ""))
                scheme, separator, token = header.partition(" ")
                if not separator or scheme.lower() != "bearer":
                    raise Unauthorized("未授权")
                return token.strip()

        return Handler
