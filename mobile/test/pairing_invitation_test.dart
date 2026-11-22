import 'dart:convert';

import 'package:cocauto/src/pairing_invitation.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('PairingInvitation.parse', () {
    test(
      'parses the desktop QR contract and normalizes the certificate pin',
      () {
        final invitation = PairingInvitation.parse(
          jsonEncode({
            'api_version': 1,
            'endpoint': 'https://192.168.1.23:47652',
            'pair_code': '004218',
            'fingerprint': List.filled(32, 'ab').join(':'),
            'robot_id': 'robot_1',
          }),
        );

        expect(invitation.apiVersion, 1);
        expect(invitation.endpoint.host, '192.168.1.23');
        expect(invitation.endpoint.port, 47652);
        expect(invitation.pairCode, '004218');
        expect(invitation.fingerprint, _fingerprint('AB'));
        expect(invitation.robotId, 'robot_1');
      },
    );

    test('accepts a private IPv6 ULA endpoint', () {
      final invitation = PairingInvitation.parse(
        jsonEncode({
          'api_version': 1,
          'endpoint': 'https://[fd12:3456:789a::23]:47652',
          'pair_code': '123456',
          'fingerprint': _fingerprint('cd'),
          'robot_id': 'robot_1',
        }),
      );

      expect(invitation.endpoint.host, 'fd12:3456:789a::23');
    });

    for (final invalid in [
      {'endpoint': 'http://192.168.1.23:47652'},
      {'endpoint': 'https://example.com:47652'},
      {'endpoint': 'https://8.8.8.8:47652'},
      {'endpoint': 'https://127.0.0.1:47652'},
      {'endpoint': 'https://user@192.168.1.23:47652'},
      {'endpoint': 'https://192.168.1.23:47652/other'},
      {'endpoint': 'https://192.168.1.23:47652?redirect=1'},
      {'endpoint': 'https://192.168.1.23:47652#fragment'},
      {'pair_code': '１２３４５６'},
      {'pair_code': '12345'},
      {'fingerprint': _fingerprint('GG')},
      {'fingerprint': List.filled(31, 'AB').join()},
      {'api_version': 2},
      {'robot_id': '   '},
    ]) {
      test('rejects invalid invitation field ${invalid.keys.single}', () {
        final payload = <String, Object>{
          'api_version': 1,
          'endpoint': 'https://192.168.1.23:47652',
          'pair_code': '123456',
          'fingerprint': _fingerprint('AB'),
          'robot_id': 'robot_1',
          ...invalid,
        };

        expect(
          () => PairingInvitation.parse(jsonEncode(payload)),
          throwsFormatException,
        );
      });
    }

    test('rejects extra fields so protocol versions cannot be misread', () {
      final payload = jsonDecode(_validPayload()) as Map<String, dynamic>;
      payload['access_token'] = 'unexpected-secret';

      expect(
        () => PairingInvitation.parse(jsonEncode(payload)),
        throwsFormatException,
      );
    });

    test('rejects malformed and oversized input', () {
      expect(() => PairingInvitation.parse('{'), throwsFormatException);
      expect(() => PairingInvitation.parse(' ' * 8193), throwsFormatException);
    });
  });
}

String _validPayload() => jsonEncode({
  'api_version': 1,
  'endpoint': 'https://192.168.1.23:47652',
  'pair_code': '123456',
  'fingerprint': _fingerprint('AB'),
  'robot_id': 'robot_1',
});

String _fingerprint(String bytePair) => List.filled(32, bytePair).join();
