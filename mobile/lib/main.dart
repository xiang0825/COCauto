import 'package:material_ui/material_ui.dart';

import 'src/agent_api.dart';
import 'src/pairing_home.dart';
import 'src/phone_game_launcher.dart';
import 'src/release_checker.dart';

void main() => runApp(const MainApp());

class MainApp extends StatelessWidget {
  const MainApp({
    super.key,
    this.sessionStore,
    this.clientFactory,
    this.gameLauncher,
    this.releaseChecker,
  });

  final AgentSessionStore? sessionStore;
  final AgentClientFactory? clientFactory;
  final PhoneGameLauncher? gameLauncher;
  final ReleaseChecker? releaseChecker;

  @override
  Widget build(BuildContext context) {
    const ink = Color(0xFF17212B);
    const green = Color(0xFF2C8A68);
    return MaterialApp(
      title: 'CoCauto',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: green,
          brightness: Brightness.light,
          surface: const Color(0xFFF5F7F6),
        ),
        scaffoldBackgroundColor: const Color(0xFFF5F7F6),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFFF5F7F6),
          foregroundColor: ink,
          centerTitle: false,
          elevation: 0,
        ),
        useMaterial3: true,
      ),
      home: PairingHome(
        sessionStore: sessionStore,
        clientFactory: clientFactory,
        gameLauncher: gameLauncher,
        releaseChecker: releaseChecker,
      ),
    );
  }
}
