import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'pairing_invitation.dart';

class AgentApiException implements Exception {
  const AgentApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class AgentSession {
  const AgentSession({
    required this.endpoint,
    required this.fingerprint,
    required this.robotId,
    required this.planFingerprint,
    required this.accessToken,
  });

  final Uri endpoint;
  final String fingerprint;
  final String robotId;
  final String planFingerprint;
  final String accessToken;

  Map<String, Object?> toJson() => {
    'api_version': PairingInvitation.currentApiVersion,
    'endpoint': endpoint.toString(),
    'fingerprint': fingerprint,
    'robot_id': robotId,
    'plan_fingerprint': planFingerprint,
    'access_token': accessToken,
  };

  factory AgentSession.fromJson(Object? value) {
    if (value is! Map<String, dynamic> ||
        value['api_version'] != PairingInvitation.currentApiVersion ||
        value.keys.toSet().difference({
          'api_version',
          'endpoint',
          'fingerprint',
          'robot_id',
          'plan_fingerprint',
          'access_token',
        }).isNotEmpty) {
      throw const FormatException('保存的桌面会话无效');
    }
    final endpointValue = value['endpoint'];
    final endpoint = endpointValue is String
        ? Uri.tryParse(endpointValue)
        : null;
    final fingerprintValue = value['fingerprint'];
    final fingerprint = fingerprintValue is String
        ? fingerprintValue.replaceAll(':', '').toUpperCase()
        : '';
    final robotId = value['robot_id'];
    final planFingerprintValue = value['plan_fingerprint'];
    final planFingerprint = planFingerprintValue is String
        ? planFingerprintValue.toUpperCase()
        : '';
    final accessToken = value['access_token'];

    if (endpoint == null ||
        !PairingInvitation.isAllowedEndpoint(endpoint) ||
        !RegExp(r'^[0-9A-F]{64}$').hasMatch(fingerprint) ||
        robotId is! String ||
        robotId.isEmpty ||
        robotId.length > 128 ||
        !RegExp(r'^[0-9A-F]{64}$').hasMatch(planFingerprint) ||
        accessToken is! String ||
        accessToken.length < 32 ||
        accessToken.length > 256) {
      throw const FormatException('保存的桌面会话无效');
    }
    return AgentSession(
      endpoint: endpoint,
      fingerprint: fingerprint,
      robotId: robotId,
      planFingerprint: planFingerprint,
      accessToken: accessToken,
    );
  }
}

abstract interface class AgentSessionStore {
  Future<AgentSession?> read();
  Future<void> save(AgentSession session);
  Future<void> clear();
}

/// Stores the revocable agent token only in Android Keystore-backed storage.
class SecureAgentSessionStore implements AgentSessionStore {
  SecureAgentSessionStore({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

  static const String _key = 'cocauto.agent_session.v1';
  final FlutterSecureStorage _storage;

  @override
  Future<AgentSession?> read() async {
    final raw = await _storage.read(key: _key);
    if (raw == null) return null;
    try {
      return AgentSession.fromJson(jsonDecode(raw));
    } on FormatException {
      await clear();
      return null;
    } on TypeError {
      await clear();
      return null;
    }
  }

  @override
  Future<void> save(AgentSession session) =>
      _storage.write(key: _key, value: jsonEncode(session.toJson()));

  @override
  Future<void> clear() => _storage.delete(key: _key);
}

class AgentResponse {
  const AgentResponse(this.statusCode, this.body);

  final int statusCode;
  final Map<String, Object?> body;
}

abstract interface class AgentTransport {
  Future<AgentResponse> send(
    String method,
    Uri uri, {
    Map<String, String> headers = const {},
    Map<String, Object?>? body,
  });

  Future<void> close();
}

/// HTTPS transport that trusts only the certificate fingerprint in the QR.
///
/// System roots are disabled so a normally trusted but wrong certificate
/// cannot bypass the QR pin. Redirects are never followed.
class PinnedAgentTransport implements AgentTransport {
  PinnedAgentTransport({required Uri endpoint, required String fingerprint})
    : _endpoint = endpoint,
      _fingerprint = fingerprint.replaceAll(':', '').toUpperCase() {
    if (!PairingInvitation.isAllowedEndpoint(endpoint) ||
        !RegExp(r'^[0-9A-F]{64}$').hasMatch(_fingerprint)) {
      throw const FormatException('桌面 TLS 连接参数无效');
    }
    _client = HttpClient(context: SecurityContext(withTrustedRoots: false))
      ..connectionTimeout = const Duration(seconds: 4)
      ..badCertificateCallback = (certificate, host, port) =>
          host.toLowerCase() == _endpoint.host.toLowerCase() &&
          port == _endpoint.port &&
          certificateMatchesPin(certificate.der, _fingerprint);
  }

  static const int _maxResponseBytes = 256 * 1024;
  static const Duration _requestTimeout = Duration(seconds: 7);

  final Uri _endpoint;
  final String _fingerprint;
  late final HttpClient _client;
  bool _closed = false;

  static bool certificateMatchesPin(List<int> der, String expectedFingerprint) {
    final expected = expectedFingerprint.replaceAll(':', '').toUpperCase();
    if (!RegExp(r'^[0-9A-F]{64}$').hasMatch(expected)) return false;
    final actual = sha256.convert(der).toString().toUpperCase();
    return actual == expected;
  }

  @override
  Future<AgentResponse> send(
    String method,
    Uri uri, {
    Map<String, String> headers = const {},
    Map<String, Object?>? body,
  }) async {
    if (_closed) throw const AgentApiException('桌面连接已关闭');
    if (uri.scheme != 'https' ||
        uri.host.toLowerCase() != _endpoint.host.toLowerCase() ||
        uri.port != _endpoint.port ||
        uri.userInfo.isNotEmpty ||
        uri.hasFragment) {
      throw const AgentApiException('拒绝向未配对的桌面地址发送请求');
    }

    try {
      final request = await _client
          .openUrl(method, uri)
          .timeout(_requestTimeout);
      request
        ..followRedirects = false
        ..maxRedirects = 0
        ..headers.set(HttpHeaders.acceptHeader, 'application/json')
        ..headers.set(HttpHeaders.cacheControlHeader, 'no-store');
      for (final entry in headers.entries) {
        request.headers.set(entry.key, entry.value);
      }
      if (body != null) {
        request.headers.contentType = ContentType.json;
        request.write(jsonEncode(body));
      }
      final response = await request.close().timeout(_requestTimeout);
      if (response.isRedirect) {
        await response.drain<void>();
        throw const AgentApiException('桌面控制端拒绝重定向');
      }
      final bytes = BytesBuilder(copy: false);
      await for (final chunk in response.timeout(_requestTimeout)) {
        if (bytes.length + chunk.length > _maxResponseBytes) {
          throw const AgentApiException('桌面响应超过允许大小');
        }
        bytes.add(chunk);
      }
      final Object? decoded;
      try {
        decoded = jsonDecode(utf8.decode(bytes.takeBytes()));
      } on FormatException {
        throw const AgentApiException('桌面响应不是有效 JSON');
      }
      if (decoded is! Map<String, dynamic>) {
        throw const AgentApiException('桌面响应格式无效');
      }
      return AgentResponse(response.statusCode, decoded);
    } on AgentApiException {
      rethrow;
    } on SocketException {
      throw const AgentApiException('无法连接桌面控制端；请检查电脑和局域网');
    } on HandshakeException {
      throw const AgentApiException('桌面 TLS 证书校验失败');
    } on HttpException {
      throw const AgentApiException('桌面连接中断');
    } on TimeoutException {
      throw const AgentApiException('桌面响应超时');
    } on FormatException {
      throw const AgentApiException('桌面响应编码无效');
    }
  }

  @override
  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _client.close(force: true);
  }
}

enum AgentCommand { start, pause, stop }

class AgentSnapshot {
  const AgentSnapshot({
    required this.robotId,
    required this.revision,
    required this.state,
    required this.stopReason,
    required this.selectedTasks,
    required this.version,
    required this.adbConnected,
    required this.adbState,
    required this.gameInstalled,
    required this.gameState,
    required this.lastStep,
  });

  final String robotId;
  final int revision;
  final String state;
  final String stopReason;
  final List<String> selectedTasks;
  final String version;
  final bool adbConnected;
  final String adbState;
  final bool? gameInstalled;
  final String gameState;
  final String lastStep;

  factory AgentSnapshot.fromJson(Map<String, Object?> value) {
    final tasks = value['selected_tasks'];
    final installed = value['game_installed'];
    final revision = value['revision'];
    if (value['api_version'] != PairingInvitation.currentApiVersion ||
        value['robot_id'] is! String ||
        revision is! int ||
        revision < 0 ||
        value['state'] is! String ||
        value['stop_reason'] is! String ||
        tasks is! List ||
        tasks.any((task) => task is! String) ||
        value['version'] is! String ||
        value['adb_connected'] is! bool ||
        value['adb_state'] is! String ||
        (installed != null && installed is! bool) ||
        value['game_state'] is! String ||
        value['last_step'] is! String) {
      throw const AgentApiException('桌面状态数据不完整');
    }
    return AgentSnapshot(
      robotId: value['robot_id']! as String,
      revision: revision,
      state: value['state']! as String,
      stopReason: value['stop_reason']! as String,
      selectedTasks: List<String>.unmodifiable(tasks.cast<String>()),
      version: value['version']! as String,
      adbConnected: value['adb_connected']! as bool,
      adbState: value['adb_state']! as String,
      gameInstalled: installed as bool?,
      gameState: value['game_state']! as String,
      lastStep: value['last_step']! as String,
    );
  }
}

class AgentLog {
  const AgentLog({
    required this.time,
    required this.level,
    required this.message,
  });

  final double time;
  final String level;
  final String message;

  factory AgentLog.fromJson(Object? value) {
    if (value is! Map<String, dynamic> ||
        value['time'] is! num ||
        value['level'] is! String ||
        value['message'] is! String) {
      throw const AgentApiException('桌面日志数据无效');
    }
    return AgentLog(
      time: (value['time'] as num).toDouble(),
      level: value['level']! as String,
      message: value['message']! as String,
    );
  }
}

class AgentControlResult {
  const AgentControlResult({required this.status, this.state, this.revision});

  final String status;
  final String? state;
  final int? revision;
}

class AgentApiClient {
  AgentApiClient({required this.session, AgentTransport? transport})
    : _transport =
          transport ??
          PinnedAgentTransport(
            endpoint: session.endpoint,
            fingerprint: session.fingerprint,
          );

  static const String _apiRoot = '/v1';
  static const Set<int> _controlStatuses = {200, 202, 409, 429, 503};

  final AgentSession session;
  final AgentTransport _transport;

  static Future<AgentSession> pair({
    required PairingInvitation invitation,
    required String clientId,
    required AgentSessionStore store,
    AgentTransport? transport,
  }) async {
    final activeTransport =
        transport ??
        PinnedAgentTransport(
          endpoint: invitation.endpoint,
          fingerprint: invitation.fingerprint,
        );
    try {
      final response = await activeTransport.send(
        'POST',
        invitation.endpoint.replace(path: '$_apiRoot/pair'),
        body: {'code': invitation.pairCode, 'client_id': clientId},
      );
      if (response.statusCode != 200) {
        throw AgentApiException(
          _errorMessage(response),
          statusCode: response.statusCode,
        );
      }
      final body = response.body;
      final apiVersion = body['api_version'];
      final token = body['access_token'];
      final tokenType = body['token_type'];
      final robotId = body['robot_id'];
      final plan = body['plan_fingerprint'];
      final certificate = body['certificate_fingerprint'];
      final normalizedCertificate = certificate is String
          ? certificate.replaceAll(':', '').toUpperCase()
          : '';
      final normalizedPlan = plan is String ? plan.toUpperCase() : '';
      if (apiVersion != PairingInvitation.currentApiVersion ||
          tokenType != 'Bearer' ||
          token is! String ||
          token.length < 32 ||
          token.length > 256 ||
          robotId != invitation.robotId ||
          !RegExp(r'^[0-9A-F]{64}$').hasMatch(normalizedPlan) ||
          normalizedCertificate != invitation.fingerprint) {
        throw const AgentApiException('桌面配对响应与二维码绑定信息不一致');
      }
      final session = AgentSession(
        endpoint: invitation.endpoint,
        fingerprint: invitation.fingerprint,
        robotId: invitation.robotId,
        planFingerprint: normalizedPlan,
        accessToken: token,
      );
      await store.save(session);
      return session;
    } on AgentApiException {
      rethrow;
    } catch (_) {
      throw const AgentApiException('配对失败；请确认配对码未过期且电脑在线');
    } finally {
      await activeTransport.close();
    }
  }

  Future<AgentSnapshot> status() async {
    final response = await _request('GET', '$_apiRoot/status');
    _expectStatus(response, {200});
    final snapshot = AgentSnapshot.fromJson(response.body);
    if (snapshot.robotId != session.robotId ||
        response.body['plan_fingerprint'] != session.planFingerprint) {
      throw const AgentApiException('桌面机器人或已保存任务计划已变化，请重新配对');
    }
    return snapshot;
  }

  Future<List<AgentLog>> logs({double after = 0, int limit = 30}) async {
    if (!after.isFinite || after < 0) {
      throw const AgentApiException('日志游标无效');
    }
    final safeLimit = limit.clamp(1, 100);
    final uri = session.endpoint.replace(
      path: '$_apiRoot/logs',
      queryParameters: {'after': after.toString(), 'limit': '$safeLimit'},
    );
    final response = await _request(
      'GET',
      uri.path,
      query: uri.queryParameters,
    );
    _expectStatus(response, {200});
    if (response.body['robot_id'] != session.robotId ||
        response.body['api_version'] != PairingInvitation.currentApiVersion) {
      throw const AgentApiException('桌面日志不属于当前配对机器人');
    }
    final entries = response.body['logs'];
    if (entries is! List) throw const AgentApiException('桌面日志格式无效');
    return List<AgentLog>.unmodifiable(entries.map(AgentLog.fromJson));
  }

  Future<AgentControlResult> control({
    required AgentCommand command,
    required int revision,
    required String requestId,
  }) async {
    if (revision < 0 || requestId.isEmpty || requestId.length > 128) {
      throw const AgentApiException('控制请求参数无效');
    }
    final response = await _request(
      'POST',
      '$_apiRoot/control',
      body: {
        'command': command.name,
        'revision': revision,
        'request_id': requestId,
      },
    );
    _expectStatus(response, _controlStatuses);
    final status = response.body['status'];
    if (status is! String) throw const AgentApiException('桌面控制响应无效');
    final state = response.body['state'];
    final nextRevision = response.body['revision'];
    if ((state != null && state is! String) ||
        (nextRevision != null && nextRevision is! int)) {
      throw const AgentApiException('桌面控制响应无效');
    }
    return AgentControlResult(
      status: status,
      state: state as String?,
      revision: nextRevision as int?,
    );
  }

  Future<void> unpair() async {
    final response = await _request('POST', '$_apiRoot/unpair', body: const {});
    _expectStatus(response, {200});
    if (response.body['status'] != 'unpaired') {
      throw const AgentApiException('桌面未确认解除配对');
    }
  }

  Future<void> close() => _transport.close();

  Future<AgentResponse> _request(
    String method,
    String path, {
    Map<String, Object?>? body,
    Map<String, String>? query,
  }) => _transport.send(
    method,
    session.endpoint.replace(path: path, queryParameters: query),
    headers: {'Authorization': 'Bearer ${session.accessToken}'},
    body: body,
  );

  static void _expectStatus(AgentResponse response, Set<int> expected) {
    if (!expected.contains(response.statusCode)) {
      throw AgentApiException(
        _errorMessage(response),
        statusCode: response.statusCode,
      );
    }
  }

  static String _errorMessage(AgentResponse response) {
    final error = response.body['error'];
    if (error is String && error.isNotEmpty) return error;
    return switch (response.statusCode) {
      401 => '手机授权已失效，请重新配对',
      409 => '桌面状态已变化，请先刷新再操作',
      429 => '桌面控制请求过多，请稍后重试',
      503 => '桌面暂时无法执行该操作',
      _ => '桌面请求失败（${response.statusCode}）',
    };
  }
}

String createSecureRequestId() {
  final random = Random.secure();
  return List<int>.generate(
    16,
    (_) => random.nextInt(256),
  ).map((byte) => byte.toRadixString(16).padLeft(2, '0')).join();
}
