import 'dart:collection';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:cocauto/src/agent_api.dart';
import 'package:cocauto/src/pairing_invitation.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('TLS pin compares the SHA-256 digest of the full certificate DER', () {
    final der = utf8.encode('certificate-der-bytes');
    final pin = sha256.convert(der).toString().toUpperCase();

    expect(PinnedAgentTransport.certificateMatchesPin(der, pin), isTrue);
    expect(
      PinnedAgentTransport.certificateMatchesPin(der, _fingerprint('00')),
      isFalse,
    );
  });

  group('AgentApiClient pairing', () {
    test('exchanges one-time code and stores only verified session', () async {
      final transport = _FakeTransport([
        AgentResponse(200, {
          'api_version': 1,
          'access_token': 'a-long-random-access-token-for-test-1234567890',
          'token_type': 'Bearer',
          'robot_id': 'robot_1',
          'plan_fingerprint': _fingerprint('CD'),
          'certificate_fingerprint': _fingerprint('AB'),
        }),
      ]);
      final store = _MemorySessionStore();

      final session = await AgentApiClient.pair(
        invitation: _invitation(),
        clientId: 'phone-test',
        store: store,
        transport: transport,
      );

      expect(session, store.saved);
      expect(session.robotId, 'robot_1');
      expect(session.planFingerprint, _fingerprint('CD'));
      expect(transport.calls.single.method, 'POST');
      expect(transport.calls.single.uri.path, '/v1/pair');
      expect(transport.calls.single.headers, isEmpty);
      expect(transport.calls.single.body, {
        'code': '004218',
        'client_id': 'phone-test',
      });
    });

    test(
      'rejects a server certificate fingerprint mismatch without saving',
      () async {
        final transport = _FakeTransport([
          AgentResponse(200, {
            'api_version': 1,
            'access_token': 'a-long-random-access-token-for-test-1234567890',
            'token_type': 'Bearer',
            'robot_id': 'robot_1',
            'plan_fingerprint': _fingerprint('CD'),
            'certificate_fingerprint': _fingerprint('EF'),
          }),
        ]);
        final store = _MemorySessionStore();

        await expectLater(
          AgentApiClient.pair(
            invitation: _invitation(),
            clientId: 'phone-test',
            store: store,
            transport: transport,
          ),
          throwsA(isA<AgentApiException>()),
        );
        expect(store.saved, isNull);
      },
    );

    test('rejects a response bound to another robot', () async {
      final transport = _FakeTransport([
        AgentResponse(200, {
          'api_version': 1,
          'access_token': 'a-long-random-access-token-for-test-1234567890',
          'token_type': 'Bearer',
          'robot_id': 'robot_2',
          'plan_fingerprint': _fingerprint('CD'),
          'certificate_fingerprint': _fingerprint('AB'),
        }),
      ]);

      await expectLater(
        AgentApiClient.pair(
          invitation: _invitation(),
          clientId: 'phone-test',
          store: _MemorySessionStore(),
          transport: transport,
        ),
        throwsA(isA<AgentApiException>()),
      );
    });
  });

  group('AgentApiClient authenticated controls', () {
    test('reads selected task and state only from the bound robot', () async {
      final transport = _FakeTransport([
        AgentResponse(200, {
          'api_version': 1,
          'robot_id': 'robot_1',
          'plan_fingerprint': _fingerprint('CD'),
          'revision': 9,
          'state': '已停止',
          'stop_reason': '手动停止',
          'selected_tasks': ['main_resource'],
          'version': 'rc116',
          'adb_connected': true,
          'adb_state': '最近已连接',
          'game_installed': true,
          'game_state': 'CoC 前台已确认',
          'last_step': '等待战斗结算',
        }),
      ]);
      final client = AgentApiClient(session: _session(), transport: transport);

      final snapshot = await client.status();

      expect(snapshot.revision, 9);
      expect(snapshot.selectedTasks, ['main_resource']);
      expect(snapshot.stopReason, '手动停止');
      expect(transport.calls.single.uri.path, '/v1/status');
      expect(
        transport.calls.single.headers['Authorization'],
        'Bearer a-long-random-access-token-for-test-1234567890',
      );
    });

    test(
      'rejects a changed desktop task plan and does not expose its data',
      () async {
        final transport = _FakeTransport([
          AgentResponse(200, {
            'api_version': 1,
            'robot_id': 'robot_1',
            'plan_fingerprint': _fingerprint('EE'),
            'revision': 10,
            'state': '运行中',
            'selected_tasks': ['main_resource'],
          }),
        ]);
        final client = AgentApiClient(
          session: _session(),
          transport: transport,
        );

        await expectLater(client.status(), throwsA(isA<AgentApiException>()));
      },
    );

    test(
      'sends an idempotent control request with the observed revision',
      () async {
        final transport = _FakeTransport([
          AgentResponse(200, {
            'status': 'applied',
            'state': '运行中',
            'revision': 10,
          }),
        ]);
        final client = AgentApiClient(
          session: _session(),
          transport: transport,
        );

        final result = await client.control(
          command: AgentCommand.start,
          revision: 9,
          requestId: 'request-9',
        );

        expect(result.status, 'applied');
        expect(transport.calls.single.uri.path, '/v1/control');
        expect(transport.calls.single.body, {
          'command': 'start',
          'revision': 9,
          'request_id': 'request-9',
        });
      },
    );

    test('does not hide stale revisions as successful starts', () async {
      final transport = _FakeTransport([
        AgentResponse(409, {'status': 'stale', 'revision': 10}),
      ]);
      final client = AgentApiClient(session: _session(), transport: transport);

      final result = await client.control(
        command: AgentCommand.start,
        revision: 9,
        requestId: 'request-9',
      );

      expect(result.status, 'stale');
    });
  });
}

PairingInvitation _invitation() => PairingInvitation.parse(
  jsonEncode({
    'api_version': 1,
    'endpoint': 'https://192.168.1.23:47652',
    'pair_code': '004218',
    'fingerprint': _fingerprint('AB'),
    'robot_id': 'robot_1',
  }),
);

AgentSession _session() => AgentSession(
  endpoint: Uri.parse('https://192.168.1.23:47652'),
  fingerprint: _fingerprint('AB'),
  robotId: 'robot_1',
  planFingerprint: _fingerprint('CD'),
  accessToken: 'a-long-random-access-token-for-test-1234567890',
);

String _fingerprint(String bytePair) => List.filled(32, bytePair).join();

class _MemorySessionStore implements AgentSessionStore {
  AgentSession? saved;

  @override
  Future<AgentSession?> read() async => saved;

  @override
  Future<void> save(AgentSession session) async => saved = session;

  @override
  Future<void> clear() async => saved = null;
}

class _FakeTransport implements AgentTransport {
  _FakeTransport(List<AgentResponse> responses)
    : _responses = Queue.of(responses);

  final Queue<AgentResponse> _responses;
  final List<_RequestRecord> calls = [];

  @override
  Future<AgentResponse> send(
    String method,
    Uri uri, {
    Map<String, String> headers = const {},
    Map<String, Object?>? body,
  }) async {
    calls.add(_RequestRecord(method, uri, headers, body));
    return _responses.removeFirst();
  }

  @override
  Future<void> close() async {}
}

class _RequestRecord {
  const _RequestRecord(this.method, this.uri, this.headers, this.body);

  final String method;
  final Uri uri;
  final Map<String, String> headers;
  final Map<String, Object?>? body;
}
