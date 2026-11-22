import 'package:cocauto/main.dart';
import 'package:cocauto/src/agent_api.dart';
import 'package:cocauto/src/pairing_screen.dart';
import 'package:cocauto/src/phone_game_launcher.dart';
import 'package:cocauto/src/release_checker.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('unpaired home explains pairing and exposes no robot controls', (
    tester,
  ) async {
    await tester.pumpWidget(
      MainApp(
        sessionStore: _MemoryStore(),
        gameLauncher: _FakeGameLauncher(),
        releaseChecker: _NoUpdates(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('尚未连接桌面控制端'), findsOneWidget);
    expect(find.text('扫描桌面配对码'), findsOneWidget);
    expect(find.byKey(const ValueKey('start-control')), findsNothing);
    expect(find.byKey(const ValueKey('pause-control')), findsNothing);
    expect(find.byKey(const ValueKey('stop-control')), findsNothing);
  });

  testWidgets('scan action opens pairing instructions', (tester) async {
    await tester.pumpWidget(
      MainApp(
        sessionStore: _MemoryStore(),
        gameLauncher: _FakeGameLauncher(),
        releaseChecker: _NoUpdates(),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('scan-pairing')));
    await tester.pumpAndSettle();

    expect(find.text('扫描电脑上的配对二维码'), findsOneWidget);
    expect(find.byKey(const ValueKey('pairing-instructions')), findsOneWidget);
  });

  testWidgets(
    'paired dashboard shows selected tasks and controls the saved plan',
    (tester) async {
      tester.view.physicalSize = const Size(900, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final session = _testSession();
      final transport = _DashboardTransport();
      final launcher = _FakeGameLauncher();
      await tester.pumpWidget(
        MainApp(
          sessionStore: _MemoryStore(session),
          clientFactory: (value) =>
              AgentApiClient(session: value, transport: transport),
          gameLauncher: launcher,
          releaseChecker: _NoUpdates(),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('已连接桌面控制端'), findsOneWidget);
      expect(find.text('主世界刷资源'), findsOneWidget);
      expect(find.byKey(const ValueKey('start-control')), findsOneWidget);
      expect(
        tester
            .widget<OutlinedButton>(find.byKey(const ValueKey('pause-control')))
            .onPressed,
        isNull,
      );

      await tester.tap(find.byKey(const ValueKey('start-control')));
      await tester.pumpAndSettle();

      final homeMessage = tester
          .widgetList<Text>(find.byKey(const ValueKey('home-message')))
          .map((widget) => widget.data)
          .join();
      expect(
        find.text('机器人：运行中'),
        findsOneWidget,
        reason:
            'message=$homeMessage requests=${transport.requests.map((r) => '${r.method} ${r.uri.path} ${r.body}').join('; ')}',
      );
      expect(
        transport.requests.any(
          (request) =>
              request.method == 'POST' &&
              request.uri.path == '/v1/control' &&
              request.body?['command'] == 'start',
        ),
        isTrue,
      );

      await tester.tap(find.byKey(const ValueKey('launch-phone-game')));
      await tester.pumpAndSettle();
      expect(launcher.launchCount, 1);
    },
  );

  testWidgets('stale desktop state disables robot controls until refreshed', (
    tester,
  ) async {
    final transport = _DashboardTransport();
    await tester.pumpWidget(
      MainApp(
        sessionStore: _MemoryStore(_testSession()),
        clientFactory: (session) =>
            AgentApiClient(session: session, transport: transport),
        gameLauncher: _FakeGameLauncher(),
        releaseChecker: _NoUpdates(),
      ),
    );
    await tester.pumpAndSettle();
    transport.statusOffline = true;
    await tester.tap(find.byKey(const ValueKey('refresh-status')));
    await tester.pumpAndSettle();

    expect(find.text('桌面连接已过期'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(find.byKey(const ValueKey('start-control')))
          .onPressed,
      isNull,
    );
  });

  testWidgets('an empty saved task plan cannot be started from the phone', (
    tester,
  ) async {
    final transport = _DashboardTransport(selectedTasks: const []);
    await tester.pumpWidget(
      MainApp(
        sessionStore: _MemoryStore(_testSession()),
        clientFactory: (session) =>
            AgentApiClient(session: session, transport: transport),
        gameLauncher: _FakeGameLauncher(),
        releaseChecker: _NoUpdates(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('当前没有选中的任务。'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(find.byKey(const ValueKey('start-control')))
          .onPressed,
      isNull,
    );
  });

  testWidgets(
    'pairing can use manual paste and keeps camera permission optional',
    (tester) async {
      var received = '';
      await tester.pumpWidget(
        MaterialApp(
          home: PairingScreen(
            onPairingData: (payload) async {
              received = payload;
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('manual-pairing')));
      await tester.pumpAndSettle();
      const payload =
          '{"api_version":1,"endpoint":"https://192.168.1.20:47652","pair_code":"123456","fingerprint":"$_testFingerprint","robot_id":"robot_1"}';
      await tester.enterText(
        find.byKey(const ValueKey('pairing-payload')),
        payload,
      );
      await tester.tap(find.byKey(const ValueKey('submit-pairing')));
      await tester.pumpAndSettle();

      expect(received, payload);
      expect(find.text('配对成功。'), findsOneWidget);
    },
  );

  testWidgets(
    'new release notice is visible and only offers a user-opened page',
    (tester) async {
      await tester.pumpWidget(
        MainApp(
          sessionStore: _MemoryStore(),
          gameLauncher: _FakeGameLauncher(),
          releaseChecker: _NewRelease(),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byKey(const ValueKey('app-version')), findsOneWidget);
      expect(find.text('2026.11.23-rc118'), findsOneWidget);
      expect(find.text('发现新版本 v2026.11.23-rc118'), findsOneWidget);
      expect(find.byKey(const ValueKey('open-update-page')), findsOneWidget);
    },
  );
}

const _testFingerprint =
    'ABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABABAB';

AgentSession _testSession() => AgentSession(
  endpoint: Uri.parse('https://192.168.1.20:47652'),
  fingerprint: List.filled(32, 'AB').join(),
  robotId: 'robot_1',
  planFingerprint: List.filled(32, 'CD').join(),
  accessToken: 'a-long-random-access-token-for-test-1234567890',
);

class _MemoryStore implements AgentSessionStore {
  _MemoryStore([this.session]);
  AgentSession? session;

  @override
  Future<void> clear() async {
    session = null;
  }

  @override
  Future<AgentSession?> read() async => session;

  @override
  Future<void> save(AgentSession value) async {
    session = value;
  }
}

class _FakeGameLauncher implements PhoneGameLauncher {
  int launchCount = 0;

  @override
  Future<bool> isInstalled() async => true;

  @override
  Future<String> appVersion() async => '2026.11.23-rc118';

  @override
  Future<void> launch() async {
    launchCount++;
  }
}

class _NoUpdates implements ReleaseChecker {
  @override
  Future<AvailableRelease?> check(String currentVersion) async => null;
}

class _NewRelease implements ReleaseChecker {
  @override
  Future<AvailableRelease?> check(String currentVersion) async =>
      AvailableRelease(
        version: 'v2026.11.23-rc118',
        page: Uri.parse(
          'https://github.com/xiang0825/COCauto/releases/tag/v2026.11.23-rc118',
        ),
        notes: '更新说明',
      );
}

class _DashboardTransport implements AgentTransport {
  _DashboardTransport({this.selectedTasks = const ['main_resource']});

  final List<_Request> requests = [];
  final List<String> selectedTasks;
  final String adbState = '最近已连接';
  bool running = false;
  bool statusOffline = false;

  @override
  Future<AgentResponse> send(
    String method,
    Uri uri, {
    Map<String, String> headers = const {},
    Map<String, Object?>? body,
  }) async {
    requests.add(_Request(method, uri, body));
    if (uri.path == '/v1/control') {
      running = body?['command'] == 'start';
      return AgentResponse(200, {
        'status': 'applied',
        'state': running ? '运行中' : '已停止',
        'revision': 10,
      });
    }
    if (uri.path == '/v1/status') {
      if (statusOffline) {
        return AgentResponse(503, {'error': 'offline'});
      }
      return AgentResponse(200, {
        'api_version': 1,
        'robot_id': 'robot_1',
        'plan_fingerprint': List.filled(32, 'CD').join(),
        'revision': running ? 10 : 9,
        'state': running ? '运行中' : '已停止',
        'stop_reason': '',
        'selected_tasks': selectedTasks,
        'version': 'rc116',
        'adb_connected': true,
        'adb_state': adbState,
        'game_installed': true,
        'game_state': 'CoC 前台已确认',
        'last_step': '等待下一步',
      });
    }
    if (uri.path == '/v1/logs') {
      return AgentResponse(200, {
        'api_version': 1,
        'robot_id': 'robot_1',
        'logs': [
          {'time': 1000, 'level': 'info', 'message': '机器人已连接'},
        ],
      });
    }
    return AgentResponse(404, {'error': 'not found'});
  }

  @override
  Future<void> close() async {}
}

class _Request {
  const _Request(this.method, this.uri, this.body);
  final String method;
  final Uri uri;
  final Map<String, Object?>? body;
}
