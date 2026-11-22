"""Regression tests for the paired phone control boundary."""

import base64
import importlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


def load_service(test_case):
    module_path = Path(__file__).resolve().parents[1] / "服务" / "局域网控制服务.py"
    test_case.assertTrue(
        module_path.is_file(),
        "paired LAN control service has not been implemented",
    )
    return importlib.import_module("服务.局域网控制服务")


class PairingAuthorityTests(unittest.TestCase):
    def test_pair_code_is_single_use_and_token_is_bound_to_robot_plan_and_client(self):
        service = load_service(self)
        authority = service.PairingAuthority(
            clock=lambda: 100.0,
            code_factory=lambda: "418205",
            token_factory=lambda: "secret-token-with-sufficient-length-123456",
        )

        ticket = authority.begin_pairing("robot_1", "plan-a")
        grant = authority.exchange_code(ticket.code, "phone-7")

        self.assertEqual(grant.token, "secret-token-with-sufficient-length-123456")
        self.assertEqual(grant.binding.robot_id, "robot_1")
        self.assertEqual(grant.binding.plan_fingerprint, "plan-a")
        self.assertEqual(grant.binding.client_id, "phone-7")
        self.assertEqual(
            authority.authenticate(
                "secret-token-with-sufficient-length-123456", "robot_1", "plan-a"
            ),
            grant.binding,
        )
        with self.assertRaises(service.Unauthorized):
            authority.exchange_code(ticket.code, "phone-7")

    def test_expired_pair_code_cannot_issue_a_token(self):
        service = load_service(self)
        now = [10.0]
        authority = service.PairingAuthority(
            clock=lambda: now[0],
            code_factory=lambda: "510204",
            token_factory=lambda: "must-not-be-issued",
        )
        ticket = authority.begin_pairing("robot_1", "plan-a", ttl_seconds=300)
        now[0] = ticket.expires_at + 0.01

        with self.assertRaises(service.Unauthorized):
            authority.exchange_code(ticket.code, "phone-7")

    def test_non_ascii_pairing_attempt_is_a_normal_auth_failure(self):
        service = load_service(self)
        authority = service.PairingAuthority(
            clock=lambda: 10.0,
            code_factory=lambda: "510204",
        )
        authority.begin_pairing("robot_1", "plan-a")

        with self.assertRaises(service.Unauthorized):
            authority.exchange_code("不正确", "phone-7")

    def test_token_rejects_other_robot_or_changed_saved_plan_and_can_be_revoked(self):
        service = load_service(self)
        authority = service.PairingAuthority(
            clock=lambda: 1.0,
            code_factory=lambda: "302918",
            token_factory=lambda: "secret-token-with-sufficient-length-123456",
        )
        ticket = authority.begin_pairing("robot_1", "plan-a")
        authority.exchange_code(ticket.code, "phone-7")

        for robot_id, plan in (("robot_2", "plan-a"), ("robot_1", "plan-b")):
            with self.subTest(robot_id=robot_id, plan=plan):
                with self.assertRaises(service.Unauthorized):
                    authority.authenticate(
                        "secret-token-with-sufficient-length-123456", robot_id, plan
                    )

        authority.revoke("secret-token-with-sufficient-length-123456")
        with self.assertRaises(service.Unauthorized):
            authority.authenticate("secret-token-with-sufficient-length-123456")

    def test_revoke_all_removes_every_pairing_and_pending_ticket(self):
        service = load_service(self)
        codes = iter(("302918", "114572", "883100", "417205"))
        tokens = iter(
            (
                "first-token-with-sufficient-entropy-123456",
                "second-token-with-sufficient-entropy-123456",
            )
        )
        authority = service.PairingAuthority(
            clock=lambda: 1.0,
            code_factory=lambda: next(codes),
            token_factory=lambda: next(tokens),
        )
        first_ticket = authority.begin_pairing("robot_1", "plan-a")
        first_grant = authority.exchange_code(first_ticket.code, "phone-1")
        authority.begin_pairing("robot_2", "plan-b")
        second_ticket = authority.begin_pairing("robot_1", "plan-a")
        second_grant = authority.exchange_code(second_ticket.code, "phone-2")
        authority.begin_pairing("robot_1", "plan-a")

        self.assertEqual(authority.revoke_all(), 2)
        for token in (first_grant.token, second_grant.token):
            with self.assertRaises(service.Unauthorized):
                authority.authenticate(token)
        with self.assertRaises(service.Unauthorized):
            authority.exchange_code("302918", "phone-3")


class SerializedCommandBrokerTests(unittest.TestCase):
    def setUp(self):
        self.service = load_service(self)
        self.revision = 4
        self.executed = []

        def execute(command):
            self.executed.append(command)
            self.revision += 1
            return {"state": command, "revision": self.revision}

        self.broker = self.service.SerializedCommandBroker(
            revision_provider=lambda: self.revision,
            execute=execute,
            max_queue=4,
        )

    def test_pause_supersedes_a_start_waiting_in_the_same_queue(self):
        start = self.broker.submit("start", expected_revision=4, request_id="r1")
        pause = self.broker.submit("pause", expected_revision=4, request_id="r2")

        self.broker.process_pending()

        self.assertEqual(self.executed, ["pause"])
        self.assertEqual(start.result()["status"], "superseded")
        self.assertEqual(pause.result()["status"], "applied")

    def test_stop_supersedes_pause_and_start_waiting_in_the_same_queue(self):
        start = self.broker.submit("start", expected_revision=4, request_id="r1")
        pause = self.broker.submit("pause", expected_revision=4, request_id="r2")
        stop = self.broker.submit("stop", expected_revision=4, request_id="r3")

        self.broker.process_pending()

        self.assertEqual(self.executed, ["stop"])
        self.assertEqual(start.result()["status"], "superseded")
        self.assertEqual(pause.result()["status"], "superseded")
        self.assertEqual(stop.result()["status"], "applied")

    def test_stale_revision_and_unknown_command_are_rejected(self):
        with self.assertRaises(self.service.StaleRevisionError):
            self.broker.submit("start", expected_revision=3, request_id="stale")
        with self.assertRaises(ValueError):
            self.broker.submit("change_tasks", expected_revision=4, request_id="bad")
        self.assertEqual(self.executed, [])

    def test_duplicate_request_id_returns_same_future_without_duplicate_action(self):
        first = self.broker.submit("start", expected_revision=4, request_id="same")
        duplicate = self.broker.submit("start", expected_revision=4, request_id="same")

        self.assertIs(first, duplicate)
        self.broker.process_pending()
        self.assertEqual(self.executed, ["start"])

    def test_command_queue_has_a_hard_capacity(self):
        for i in range(4):
            self.broker.submit("start", expected_revision=4, request_id=f"r{i}")

        with self.assertRaises(self.service.QueueFullError):
            self.broker.submit("start", expected_revision=4, request_id="overflow")


class BindAddressTests(unittest.TestCase):
    def test_only_an_explicit_private_address_on_this_machine_is_accepted(self):
        service = load_service(self)

        self.assertEqual(
            service.validate_bind_address("192.168.1.23", {"192.168.1.23"}),
            "192.168.1.23",
        )

    def test_wildcard_loopback_public_and_unselected_addresses_are_rejected(self):
        service = load_service(self)
        cases = (
            ("0.0.0.0", {"0.0.0.0"}),
            ("127.0.0.1", {"127.0.0.1"}),
            ("8.8.8.8", {"8.8.8.8"}),
            ("192.168.1.24", {"192.168.1.23"}),
        )
        for address, local_addresses in cases:
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    service.validate_bind_address(address, local_addresses)


class DpapiTokenStoreTests(unittest.TestCase):
    def test_token_binding_survives_restart_in_a_dpapi_protected_file(self):
        if os.name != "nt":
            self.skipTest("DPAPI is available only on Windows")
        service = load_service(self)
        self.assertTrue(
            hasattr(service, "DpapiTokenStore"),
            "DPAPI-protected token persistence has not been implemented",
        )

        with tempfile.TemporaryDirectory(prefix="coc-remote-token-") as temporary:
            token_path = Path(temporary) / "pairing.dat"
            store = service.DpapiTokenStore(token_path)
            authority = service.PairingAuthority(
                token_store=store,
                clock=lambda: 100.0,
                code_factory=lambda: "714203",
                token_factory=lambda: "secret-token-with-sufficient-length-123456",
            )
            ticket = authority.begin_pairing("robot_1", "plan-a")
            grant = authority.exchange_code(ticket.code, "phone-7")

            protected_bytes = token_path.read_bytes()
            self.assertNotIn(b"phone-7", protected_bytes)
            restored = service.PairingAuthority(token_store=store)
            self.assertEqual(
                restored.authenticate(grant.token, "robot_1", "plan-a"),
                grant.binding,
            )

    def test_tls_identity_keeps_a_pinned_certificate_and_never_writes_the_key_in_plaintext(self):
        if os.name != "nt":
            self.skipTest("the desktop TLS identity is protected with Windows DPAPI")
        service = load_service(self)
        self.assertTrue(
            hasattr(service, "TlsIdentity"),
            "persistent pinned TLS identity has not been implemented",
        )

        with tempfile.TemporaryDirectory(prefix="coc-remote-tls-") as temporary:
            identity_path = Path(temporary) / "tls-identity.dat"
            first = service.TlsIdentity.load_or_create(
                identity_path, "192.168.1.23"
            )
            persisted = identity_path.read_bytes()
            second = service.TlsIdentity.load_or_create(
                identity_path, "192.168.1.23"
            )

            self.assertEqual(first.fingerprint, second.fingerprint)
            self.assertNotIn(first.private_key_pem, persisted)
            self.assertEqual(len(first.fingerprint), 64)

    def test_expired_tls_identity_is_rotated_before_it_is_served(self):
        if os.name != "nt":
            self.skipTest("the desktop TLS identity is protected with Windows DPAPI")
        service = load_service(self)
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.x509.oid import NameOID

        with tempfile.TemporaryDirectory(prefix="coc-expired-tls-") as temporary:
            identity_path = Path(temporary) / "tls-identity.dat"
            original = service.TlsIdentity.load_or_create(
                identity_path, "192.168.1.23"
            )
            private_key = serialization.load_pem_private_key(
                original.private_key_pem, password=None
            )
            now = datetime.now(timezone.utc)
            expired = (
                x509.CertificateBuilder()
                .subject_name(
                    x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CoC local agent")])
                )
                .issuer_name(
                    x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CoC local agent")])
                )
                .public_key(private_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=3))
                .not_valid_after(now - timedelta(days=1))
                .add_extension(
                    x509.SubjectAlternativeName(
                        [x509.IPAddress(ipaddress.ip_address("192.168.1.23"))]
                    ),
                    critical=False,
                )
                .add_extension(
                    x509.BasicConstraints(ca=False, path_length=None), critical=True
                )
                .add_extension(
                    x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                    critical=False,
                )
                .sign(private_key, hashes.SHA256())
            )
            document = json.loads(
                service._dpapi_unprotect(
                    identity_path.read_bytes(), service.TlsIdentity._DESCRIPTION
                ).decode("utf-8")
            )
            document["certificate_pem"] = base64.b64encode(
                expired.public_bytes(serialization.Encoding.PEM)
            ).decode("ascii")
            protected = service._dpapi_protect(
                json.dumps(document, separators=(",", ":"), sort_keys=True).encode(
                    "utf-8"
                ),
                service.TlsIdentity._DESCRIPTION,
            )
            identity_path.write_bytes(protected)

            rotated = service.TlsIdentity.load_or_create(
                identity_path, "192.168.1.23"
            )

            self.assertNotEqual(rotated.fingerprint, original.fingerprint)
            renewed_certificate = x509.load_pem_x509_certificate(
                rotated.certificate_pem
            )
            self.assertGreater(
                renewed_certificate.not_valid_after_utc, datetime.now(timezone.utc)
            )


class MobileControlHttpTests(unittest.TestCase):
    def test_https_api_requires_pairing_and_only_routes_safe_serialized_controls(self):
        if os.name != "nt":
            self.skipTest("the desktop agent requires Windows DPAPI")
        service_module = load_service(self)
        self.assertTrue(
            hasattr(service_module, "MobileControlServer"),
            "authenticated HTTPS control API has not been implemented",
        )
        # Keep tests loopback-only so test runs never open a LAN listener or
        # trigger a Windows Firewall prompt. The real-interface rule has its
        # own pure validation tests above.
        bind_address = "127.0.0.1"

        with tempfile.TemporaryDirectory(prefix="coc-remote-http-") as temporary:
            identity = service_module.TlsIdentity.load_or_create(
                Path(temporary) / "identity.dat", bind_address
            )
            authority = service_module.PairingAuthority(
                code_factory=lambda: "640218",
                token_factory=lambda: "https-test-token-with-enough-entropy-12345",
            )
            ticket = authority.begin_pairing("robot_1", "plan-v1")
            revision = [1]
            executed = []

            def execute(command):
                executed.append(command)
                revision[0] += 1
                return {"state": command, "revision": revision[0]}

            broker = service_module.SerializedCommandBroker(
                revision_provider=lambda: revision[0], execute=execute
            )
            snapshot = lambda robot_id: {
                "robot_id": robot_id,
                "plan_fingerprint": "plan-v1",
                "revision": revision[0],
                "state": "stopped" if revision[0] == 1 else "running",
                "selected_tasks": ["main_resource"],
                "private_value": "must-not-be-returned",
                "stop_reason": "人工停止",
                "adb_state": "未运行时未检测",
                "game_state": "未检测",
                "game_installed": None,
            }
            requested_logs = []

            def read_logs(robot, after, limit):
                requested_logs.append((robot, after, limit))
                return [{"time": 1.0, "message": "ready", "private_value": "hidden"}]

            with mock.patch.object(
                service_module,
                "validate_bind_address",
                side_effect=lambda selected, _local: selected,
            ):
                server = service_module.MobileControlServer(
                    bind_address=bind_address,
                    local_addresses={bind_address},
                    port=0,
                    tls_identity=identity,
                    pairing_authority=authority,
                    command_broker=broker,
                    snapshot_provider=snapshot,
                    logs_provider=read_logs,
                ).start()
            stop_pump = threading.Event()
            pump = threading.Thread(
                target=lambda: _pump_until_stopped(server, stop_pump), daemon=True
            )
            pump.start()
            client_context = ssl.create_default_context(
                cadata=identity.certificate_pem.decode("ascii")
            )
            connection = http.client.HTTPSConnection(
                bind_address, server.port, context=client_context, timeout=5
            )

            try:
                connection.request("GET", "/v1/status")
                response = connection.getresponse()
                self.assertEqual(response.status, 401)
                response.read()

                request = json.dumps(
                    {"code": ticket.code, "client_id": "phone-test"}
                ).encode()
                connection.request(
                    "POST",
                    "/v1/pair",
                    body=request,
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                grant = json.loads(response.read())
                token = grant["access_token"]

                connection.request(
                    "GET", "/v1/status", headers={"Authorization": f"Bearer {token}"}
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                status = json.loads(response.read())
                self.assertEqual(status["selected_tasks"], ["main_resource"])
                self.assertNotIn("private_value", status)
                self.assertIsNone(status["game_installed"])
                self.assertEqual(status["stop_reason"], "人工停止")
                self.assertEqual(status["adb_state"], "未运行时未检测")

                for invalid_after in ("-1", "nan", "inf"):
                    connection.request(
                        "GET",
                        f"/v1/logs?after={invalid_after}",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    response = connection.getresponse()
                    self.assertEqual(response.status, 400)
                    response.read()
                self.assertEqual(requested_logs, [])

                connection.request(
                    "GET",
                    "/v1/logs?after=0&limit=20",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertNotIn("private_value", json.loads(response.read())["logs"][0])
                self.assertEqual(requested_logs, [("robot_1", 0.0, 20)])

                bad_body = json.dumps(
                    {
                        "command": "start",
                        "revision": 1,
                        "request_id": "bad-task-change",
                        "tasks": ["wall"],
                    }
                ).encode()
                connection.request(
                    "POST",
                    "/v1/control",
                    body=bad_body,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
                self.assertEqual(executed, [])

                good_body = json.dumps(
                    {"command": "start", "revision": 1, "request_id": "start-1"}
                ).encode()
                connection.request(
                    "POST",
                    "/v1/control",
                    body=good_body,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["status"], "applied")
                self.assertEqual(executed, ["start"])

                stale_body = json.dumps(
                    {"command": "pause", "revision": 1, "request_id": "stale-1"}
                ).encode()
                connection.request(
                    "POST",
                    "/v1/control",
                    body=stale_body,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 409)
                response.read()
                self.assertEqual(executed, ["start"])

                server.begin_pairing("robot_1", "plan-v1")
                wrong_pair_body = json.dumps(
                    {"code": "000000", "client_id": "phone-guess"}
                ).encode()
                for _ in range(5):
                    connection.request(
                        "POST",
                        "/v1/pair",
                        body=wrong_pair_body,
                        headers={"Content-Type": "application/json"},
                    )
                    response = connection.getresponse()
                    self.assertEqual(response.status, 401)
                    response.read()
                connection.request(
                    "POST",
                    "/v1/pair",
                    body=wrong_pair_body,
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 429)
                response.read()

                connection.request(
                    "POST",
                    "/v1/unpair",
                    body=b"{}",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                connection.request(
                    "GET", "/v1/status", headers={"Authorization": f"Bearer {token}"}
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 401)
                response.read()
            finally:
                connection.close()
                stop_pump.set()
                pump.join(timeout=2)
                server.close()


class MobileControlStartupTests(unittest.TestCase):
    def test_tls_setup_failure_closes_the_bound_socket(self):
        service = load_service(self)
        bind_address = "127.0.0.1"

        class FailingIdentity:
            def __init__(self):
                self.bind_address = bind_address

            def create_server_context(self):
                raise RuntimeError("test TLS setup failure")

        with mock.patch.object(
            service,
            "validate_bind_address",
            side_effect=lambda selected, _local: selected,
        ):
            server = service.MobileControlServer(
                bind_address=bind_address,
                local_addresses={bind_address},
                port=0,
                tls_identity=FailingIdentity(),
                pairing_authority=service.PairingAuthority(),
                command_broker=service.SerializedCommandBroker(
                    revision_provider=lambda: 1, execute=lambda _command: None
                ),
                snapshot_provider=lambda _robot: {
                    "revision": 1,
                    "plan_fingerprint": "plan",
                    "state": "stopped",
                },
            )
        original_close = service.http.server.ThreadingHTTPServer.server_close
        closed_servers = []

        def tracked_close(instance):
            closed_servers.append(instance)
            return original_close(instance)

        with mock.patch.object(
            service.http.server.ThreadingHTTPServer, "server_close", tracked_close
        ):
            with self.assertRaisesRegex(RuntimeError, "test TLS setup failure"):
                server.start()

        self.assertEqual(len(closed_servers), 1)
        self.assertFalse(server.is_running)


class PairingAttemptLimiterTests(unittest.TestCase):
    def test_repeated_bad_codes_are_rate_limited_and_success_clears_attempts(self):
        service = load_service(self)
        self.assertTrue(
            hasattr(service, "PairingAttemptLimiter"),
            "pairing-code rate limiting has not been implemented",
        )
        now = [100.0]
        limiter = service.PairingAttemptLimiter(
            clock=lambda: now[0], limit=5, window_seconds=60
        )
        for _ in range(5):
            self.assertTrue(limiter.allow("192.168.1.20"))
            limiter.record_failure("192.168.1.20")
        self.assertFalse(limiter.allow("192.168.1.20"))
        limiter.record_success("192.168.1.20")
        self.assertTrue(limiter.allow("192.168.1.20"))
        for _ in range(5):
            limiter.record_failure("192.168.1.20")
        now[0] += 61
        self.assertTrue(limiter.allow("192.168.1.20"))

    def test_attempts_are_isolated_per_address_and_tracking_is_bounded(self):
        service = load_service(self)
        self.assertTrue(hasattr(service, "PairingAttemptLimiter"))
        limiter = service.PairingAttemptLimiter(
            clock=lambda: 100.0, limit=2, window_seconds=60, max_clients=2
        )
        limiter.record_failure("192.168.1.20")
        self.assertTrue(limiter.allow("192.168.1.21"))
        limiter.record_failure("192.168.1.22")
        limiter.record_failure("192.168.1.23")
        self.assertLessEqual(len(limiter._attempts), 2)


class PairingQrPayloadTests(unittest.TestCase):
    def test_qr_payload_contains_short_lived_pairing_details_but_never_a_bearer_token(self):
        service = load_service(self)
        self.assertTrue(hasattr(service, "pairing_qr_payload"))

        payload = json.loads(
            service.pairing_qr_payload(
                "https://192.168.1.20:47652",
                "640218",
                "AB" * 32,
                "robot_1",
            )
        )

        self.assertEqual(payload["api_version"], 1)
        self.assertEqual(payload["pair_code"], "640218")
        self.assertEqual(payload["fingerprint"], "AB" * 32)
        self.assertNotIn("access_token", payload)


def _pump_until_stopped(server, stop_event):
    while not stop_event.is_set():
        server.process_pending()
        time.sleep(0.01)


if __name__ == "__main__":
    unittest.main()
