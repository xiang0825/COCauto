import 'package:flutter/services.dart';

abstract interface class PhoneGameLauncher {
  Future<bool> isInstalled();
  Future<String> appVersion();
  Future<void> launch();
}

class PlatformPhoneGameLauncher implements PhoneGameLauncher {
  static const MethodChannel _channel = MethodChannel(
    'com.xiang0825.cocauto/game',
  );

  @override
  Future<bool> isInstalled() async =>
      await _channel.invokeMethod<bool>('isGameInstalled') ?? false;

  @override
  Future<String> appVersion() async =>
      await _channel.invokeMethod<String>('appVersion') ?? '未知版本';

  @override
  Future<void> launch() async {
    final launched = await _channel.invokeMethod<bool>('launchGame') ?? false;
    if (!launched) throw PlatformException(code: 'game_not_installed');
  }
}
