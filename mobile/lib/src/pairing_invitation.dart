import 'dart:convert';
import 'dart:io';

/// A strictly validated, short-lived invitation emitted by the Windows agent.
///
/// The QR payload contains no access token. Its TLS fingerprint is the trust
/// anchor for the first pairing request, so hostnames and public IPs are not
/// accepted.
class PairingInvitation {
  const PairingInvitation._({
    required this.apiVersion,
    required this.endpoint,
    required this.pairCode,
    required this.fingerprint,
    required this.robotId,
  });

  static const int currentApiVersion = 1;
  static const int maxPayloadLength = 8192;
  static const Set<String> _requiredFields = {
    'api_version',
    'endpoint',
    'pair_code',
    'fingerprint',
    'robot_id',
  };

  final int apiVersion;
  final Uri endpoint;
  final String pairCode;
  final String fingerprint;
  final String robotId;

  factory PairingInvitation.parse(String payload) {
    if (payload.length > maxPayloadLength) {
      throw const FormatException('配对内容过长');
    }

    final Object? decoded;
    try {
      decoded = jsonDecode(payload);
    } on FormatException {
      throw const FormatException('配对内容不是有效 JSON');
    }
    if (decoded is! Map<String, dynamic> ||
        decoded.keys.toSet().difference(_requiredFields).isNotEmpty ||
        _requiredFields.difference(decoded.keys.toSet()).isNotEmpty) {
      throw const FormatException('配对内容字段与桌面协议不符');
    }

    final version = decoded['api_version'];
    if (version is! int || version != currentApiVersion) {
      throw const FormatException('桌面控制端 API 版本不受支持');
    }

    final endpointValue = decoded['endpoint'];
    if (endpointValue is! String) {
      throw const FormatException('桌面地址无效');
    }
    final endpoint = Uri.tryParse(endpointValue);
    if (endpoint == null || !isAllowedEndpoint(endpoint)) {
      throw const FormatException('桌面地址必须是本机私有网络的 HTTPS IP 地址');
    }

    final pairCode = decoded['pair_code'];
    if (pairCode is! String || !RegExp(r'^[0-9]{6}$').hasMatch(pairCode)) {
      throw const FormatException('配对码必须是六位 ASCII 数字');
    }

    final rawFingerprint = decoded['fingerprint'];
    if (rawFingerprint is! String) {
      throw const FormatException('TLS 证书指纹无效');
    }
    final fingerprint = rawFingerprint.replaceAll(':', '').toUpperCase();
    if (!RegExp(r'^[0-9A-F]{64}$').hasMatch(fingerprint)) {
      throw const FormatException('TLS 证书指纹必须是 SHA-256 十六进制值');
    }

    final robotId = decoded['robot_id'];
    if (robotId is! String ||
        robotId.isEmpty ||
        robotId != robotId.trim() ||
        robotId.length > 128 ||
        RegExp(r'[\x00-\x1F\x7F]').hasMatch(robotId)) {
      throw const FormatException('桌面机器人标识无效');
    }

    return PairingInvitation._(
      apiVersion: version,
      endpoint: endpoint,
      pairCode: pairCode,
      fingerprint: fingerprint,
      robotId: robotId,
    );
  }

  static bool isAllowedEndpoint(Uri uri) {
    if (uri.scheme.toLowerCase() != 'https' ||
        !uri.hasAuthority ||
        uri.userInfo.isNotEmpty ||
        !uri.hasPort ||
        uri.port < 1 ||
        uri.port > 65535 ||
        (uri.path.isNotEmpty && uri.path != '/') ||
        uri.hasQuery ||
        uri.hasFragment) {
      return false;
    }

    final address = InternetAddress.tryParse(uri.host);
    if (address == null || address.isLoopback || address.isLinkLocal) {
      return false;
    }
    final bytes = address.rawAddress;
    if (address.type == InternetAddressType.IPv4) {
      return bytes[0] == 10 ||
          (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) ||
          (bytes[0] == 192 && bytes[1] == 168);
    }
    if (address.type == InternetAddressType.IPv6) {
      // Unique-local IPv6 addresses are the private LAN range (fc00::/7).
      return (bytes[0] & 0xfe) == 0xfc;
    }
    return false;
  }
}
