import 'dart:async';

import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import 'agent_api.dart';
import 'pairing_invitation.dart';
import 'pairing_screen.dart';
import 'phone_game_launcher.dart';
import 'release_checker.dart';

typedef AgentClientFactory = AgentApiClient Function(AgentSession session);

class PairingHome extends StatefulWidget {
  const PairingHome({
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
  State<PairingHome> createState() => _PairingHomeState();
}

class _PairingHomeState extends State<PairingHome> with WidgetsBindingObserver {
  static const _taskNames = {
    'main_resource': '主世界刷资源',
    'night_resource': '夜世界刷资源',
    'wall': '刷墙',
    'building': '建议建筑升级',
    'hero': '英雄或建筑升级',
    'pet': '战宠升级',
    'research': '兵种或法术研究',
  };

  late final AgentSessionStore _store;
  late final AgentClientFactory _clientFactory;
  late final PhoneGameLauncher _gameLauncher;
  late final ReleaseChecker _releaseChecker;
  AgentSession? _session;
  AgentApiClient? _client;
  AgentSnapshot? _snapshot;
  List<AgentLog> _logs = [];
  bool _restoring = true;
  bool _refreshing = false;
  bool _controlling = false;
  bool _checkingRelease = false;
  bool _stale = false;
  bool? _gameInstalled;
  String _appVersion = '读取中…';
  AvailableRelease? _availableRelease;
  String? _message;

  @override
  void initState() {
    super.initState();
    _store = widget.sessionStore ?? SecureAgentSessionStore();
    _clientFactory =
        widget.clientFactory ?? (session) => AgentApiClient(session: session);
    _gameLauncher = widget.gameLauncher ?? PlatformPhoneGameLauncher();
    _releaseChecker = widget.releaseChecker ?? GitHubReleaseChecker();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_restoreSession());
    unawaited(_loadPhoneInfo());
    unawaited(_checkForUpdate());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(_refresh());
      unawaited(_loadPhoneInfo());
      unawaited(_checkForUpdate());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    final client = _client;
    if (client != null) unawaited(client.close());
    super.dispose();
  }

  Future<void> _restoreSession() async {
    try {
      final session = await _store.read();
      if (!mounted) return;
      if (session != null) {
        _session = session;
        _client = _clientFactory(session);
        await _refresh();
      }
    } catch (_) {
      if (mounted) _message = '无法读取安全保存的桌面配对；请重新配对。';
    } finally {
      if (mounted) setState(() => _restoring = false);
    }
  }

  Future<void> _loadPhoneInfo() async {
    try {
      final installed = await _gameLauncher.isInstalled();
      final version = await _gameLauncher.appVersion();
      if (mounted) {
        setState(() {
          _gameInstalled = installed;
          _appVersion = version;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _gameInstalled = false);
    }
  }

  Future<void> _checkForUpdate() async {
    if (_checkingRelease) return;
    _checkingRelease = true;
    try {
      final version = await _gameLauncher.appVersion();
      final release = await _releaseChecker.check(version);
      if (mounted) {
        setState(() {
          _appVersion = version;
          _availableRelease = release;
        });
      }
    } catch (_) {
      // Update checks are optional and remain quiet when offline.
    } finally {
      _checkingRelease = false;
    }
  }

  Future<void> _openReleasePage() async {
    final page = _availableRelease?.page;
    if (page == null) return;
    try {
      final opened = await launchUrl(
        page,
        mode: LaunchMode.externalApplication,
      );
      if (!opened && mounted) setState(() => _message = '无法打开 GitHub 发布页面。');
    } catch (_) {
      if (mounted) setState(() => _message = '无法打开 GitHub 发布页面。');
    }
  }

  Future<void> _pair(String payload) async {
    final invitation = PairingInvitation.parse(payload);
    final session = await AgentApiClient.pair(
      invitation: invitation,
      clientId: createSecureRequestId(),
      store: _store,
    );
    final nextClient = _clientFactory(session);
    final previousClient = _client;
    if (!mounted) {
      await nextClient.close();
      return;
    }
    setState(() {
      _session = session;
      _client = nextClient;
      _snapshot = null;
      _logs = [];
      _stale = true;
      _message = null;
    });
    if (previousClient != null) await previousClient.close();
    await _refresh();
  }

  Future<void> _refresh() async {
    final client = _client;
    if (client == null || _refreshing) return;
    setState(() => _refreshing = true);
    try {
      final snapshot = await client.status();
      final after = _logs.isEmpty ? 0.0 : _logs.last.time;
      final newLogs = await client.logs(after: after, limit: 40);
      if (!mounted) return;
      setState(() {
        _snapshot = snapshot;
        _logs = [..._logs, ...newLogs].takeLast(30).toList();
        _stale = false;
        _message = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _stale = true;
        _message = error is AgentApiException
            ? error.message
            : '暂时无法连接桌面；请检查电脑和局域网。';
      });
    } finally {
      if (mounted) setState(() => _refreshing = false);
    }
  }

  Future<void> _sendControl(AgentCommand command) async {
    final client = _client;
    final snapshot = _snapshot;
    if (client == null || snapshot == null || _stale) return;
    setState(() => _controlling = true);
    try {
      final result = await client.control(
        command: command,
        revision: snapshot.revision,
        requestId: createSecureRequestId(),
      );
      if (!mounted) return;
      if (result.status == 'stale' || result.status == 'superseded') {
        await _refresh();
        if (mounted) {
          setState(() => _message = '桌面状态已变化；旧命令已拒绝，请确认刷新后的状态。');
        }
        return;
      }
      if (result.status == 'applied' || result.status == 'queued') {
        await _refresh();
        if (!mounted) return;
        setState(
          () => _message = result.status == 'queued'
              ? '命令已排队，正在等待桌面确认。'
              : '桌面已接受${_commandName(command)}命令。',
        );
        return;
      }
      setState(() => _message = '桌面暂时无法执行${_commandName(command)}命令。');
    } catch (error) {
      if (mounted) setState(() => _stale = true);
      await _refresh();
      if (mounted) {
        setState(
          () => _message = error is AgentApiException
              ? '${error.message}；命令未自动重试。'
              : '命令结果未知；已尝试刷新状态，命令未自动重试。',
        );
      }
    } finally {
      if (mounted) setState(() => _controlling = false);
    }
  }

  Future<void> _unpair() async {
    final client = _client;
    if (client == null) return;
    setState(() => _controlling = true);
    try {
      await client.unpair();
      await _store.clear();
      await client.close();
      if (!mounted) return;
      setState(() {
        _client = null;
        _session = null;
        _snapshot = null;
        _logs = [];
        _message = null;
      });
    } catch (error) {
      if (mounted) {
        setState(
          () => _message = error is AgentApiException
              ? error.message
              : '解除配对未完成；请检查电脑连接后重试。',
        );
      }
    } finally {
      if (mounted) setState(() => _controlling = false);
    }
  }

  Future<void> _launchGame() async {
    try {
      await _gameLauncher.launch();
      if (mounted) setState(() => _message = '已打开手机上的部落冲突。');
    } catch (_) {
      if (mounted) setState(() => _message = '没有找到可启动的部落冲突应用。');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('CoCauto'),
        actions: [
          IconButton(
            key: const ValueKey('refresh-status'),
            tooltip: '刷新状态',
            onPressed: _client == null || _refreshing ? null : _refresh,
            icon: _refreshing
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh),
          ),
          if (_client != null)
            IconButton(
              key: const ValueKey('unpair-control'),
              tooltip: '解除配对',
              onPressed: _controlling ? null : _unpair,
              icon: const Icon(Icons.link_off),
            ),
        ],
      ),
      body: SafeArea(
        child: _restoring
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
                children: [
                  Row(
                    children: [
                      const Expanded(
                        child: Text(
                          '手机控制台',
                          style: TextStyle(
                            color: Color(0xFF17212B),
                            fontSize: 27,
                            fontWeight: FontWeight.w700,
                            letterSpacing: -0.4,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        _appVersion,
                        key: const ValueKey('app-version'),
                        style: const TextStyle(
                          color: Color(0xFF64706A),
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 5),
                  const Text('启动手机游戏，查看并控制已保存的桌面任务计划。'),
                  const SizedBox(height: 18),
                  if (_session == null)
                    _buildUnpairedCard()
                  else
                    _buildAgentCard(),
                  const SizedBox(height: 14),
                  if (_availableRelease case final release?) ...[
                    _buildUpdateCard(release),
                    const SizedBox(height: 14),
                  ],
                  _buildPhoneGameCard(),
                  if (_session != null) ...[
                    const SizedBox(height: 14),
                    _buildTaskCard(),
                    const SizedBox(height: 14),
                    _buildControlCard(),
                    const SizedBox(height: 14),
                    _buildLogsCard(),
                  ],
                  if (_message case final message?) ...[
                    const SizedBox(height: 12),
                    Text(message, key: const ValueKey('home-message')),
                  ],
                ],
              ),
      ),
    );
  }

  Widget _buildUnpairedCard() => _card(
    color: Colors.white,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Row(
          children: [
            Icon(Icons.link_off, color: Color(0xFFB56A38)),
            SizedBox(width: 10),
            Text(
              '尚未连接桌面控制端',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
            ),
          ],
        ),
        const SizedBox(height: 10),
        const Text('在电脑的「手机控制」页面启动服务，然后扫描一次性配对码。'),
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            key: const ValueKey('scan-pairing'),
            onPressed: () => Navigator.of(context).push<bool>(
              MaterialPageRoute<bool>(
                builder: (_) => PairingScreen(onPairingData: _pair),
              ),
            ),
            icon: const Icon(Icons.qr_code_scanner),
            label: const Text('扫描桌面配对码'),
          ),
        ),
      ],
    ),
  );

  Widget _buildAgentCard() {
    final snapshot = _snapshot;
    final stale = _stale;
    return _card(
      color: stale ? const Color(0xFFFFF2E8) : const Color(0xFFEAF2EE),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                stale ? Icons.cloud_off : Icons.link,
                color: stale
                    ? const Color(0xFFB56A38)
                    : const Color(0xFF2C8A68),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  stale
                      ? '桌面连接已过期'
                      : snapshot == null
                      ? '正在连接桌面控制端'
                      : '已连接桌面控制端',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              Text(snapshot?.version ?? '读取中…'),
            ],
          ),
          if (snapshot != null) ...[
            const SizedBox(height: 10),
            Text('机器人：${snapshot.state}', key: const ValueKey('robot-state')),
            Text('设备：${snapshot.adbState}'),
            Text('游戏：${snapshot.gameState}'),
            if (snapshot.stopReason.isNotEmpty)
              Text('停止原因：${snapshot.stopReason}'),
          ] else if (_refreshing) ...[
            const SizedBox(height: 10),
            const Text('正在读取桌面状态…'),
          ] else ...[
            const SizedBox(height: 10),
            const Text('尚未收到桌面状态。点右上角刷新重试。'),
          ],
        ],
      ),
    );
  }

  Widget _buildPhoneGameCard() => _card(
    color: const Color(0xFFEAF2EE),
    child: Row(
      children: [
        const Icon(Icons.sports_esports_outlined, color: Color(0xFF2C8A68)),
        const SizedBox(width: 12),
        const Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('手机游戏', style: TextStyle(fontWeight: FontWeight.w600)),
              SizedBox(height: 4),
              Text('启动本机已安装的部落冲突。'),
            ],
          ),
        ),
        if (_gameInstalled == true)
          IconButton.filledTonal(
            key: const ValueKey('launch-phone-game'),
            tooltip: '启动部落冲突',
            onPressed: _launchGame,
            icon: const Icon(Icons.play_arrow),
          )
        else if (_gameInstalled == false)
          const Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.download_for_offline_outlined),
              SizedBox(width: 4),
              Text('未安装'),
            ],
          )
        else
          const SizedBox.square(
            dimension: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
      ],
    ),
  );

  Widget _buildUpdateCard(AvailableRelease release) => _card(
    color: const Color(0xFFEAF2EE),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.system_update_alt, color: Color(0xFF2C8A68)),
            const SizedBox(width: 9),
            Expanded(
              child: Text(
                '发现新版本 ${release.version}',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
          ],
        ),
        if (release.notes.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(
            release.notes.length > 240
                ? '${release.notes.substring(0, 240)}…'
                : release.notes,
            maxLines: 4,
            overflow: TextOverflow.ellipsis,
          ),
        ],
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton.icon(
            key: const ValueKey('open-update-page'),
            onPressed: _openReleasePage,
            icon: const Icon(Icons.open_in_new),
            label: const Text('查看更新'),
          ),
        ),
      ],
    ),
  );

  Widget _buildTaskCard() {
    final tasks = _snapshot?.selectedTasks ?? const <String>[];
    return _card(
      color: Colors.white,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('桌面已选任务', style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          if (tasks.isEmpty)
            const Text('当前没有选中的任务。')
          else
            for (final task in tasks)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(
                  children: [
                    const Icon(Icons.check_circle_outline, size: 18),
                    const SizedBox(width: 8),
                    Expanded(child: Text(_taskNames[task] ?? task)),
                  ],
                ),
              ),
          const SizedBox(height: 5),
          const Text('手机只控制这份已保存计划，不能在此切换任务。'),
        ],
      ),
    );
  }

  Widget _buildControlCard() {
    final snapshot = _snapshot;
    final state = snapshot?.state;
    final disabled = _controlling || _refreshing || _stale || snapshot == null;
    final canStart =
        !disabled &&
        snapshot.selectedTasks.isNotEmpty &&
        snapshot.adbState != '未配置' &&
        snapshot.adbState != '连接失败' &&
        (state == '已停止' || state == '暂停中');
    final canPause = !disabled && state == '运行中';
    final canStop = !disabled && state != null && state != '已停止';
    return _card(
      color: Colors.white,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('机器人控制', style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  key: const ValueKey('start-control'),
                  onPressed: canStart
                      ? () => _sendControl(AgentCommand.start)
                      : null,
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('开始'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton.icon(
                  key: const ValueKey('pause-control'),
                  onPressed: canPause
                      ? () => _sendControl(AgentCommand.pause)
                      : null,
                  icon: const Icon(Icons.pause),
                  label: const Text('暂停'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton.icon(
                  key: const ValueKey('stop-control'),
                  onPressed: canStop
                      ? () => _sendControl(AgentCommand.stop)
                      : null,
                  icon: const Icon(Icons.stop),
                  label: const Text('停止'),
                ),
              ),
            ],
          ),
          if (_controlling) ...[
            const SizedBox(height: 10),
            const LinearProgressIndicator(),
          ],
        ],
      ),
    );
  }

  Widget _buildLogsCard() => _card(
    color: Colors.white,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('最近日志', style: TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        if (_logs.isEmpty)
          const Text('暂无日志。')
        else
          for (final log in _logs.reversed.take(8))
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Text(
                log.message,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: log.level == 'error'
                      ? const Color(0xFFB3261E)
                      : const Color(0xFF17212B),
                ),
              ),
            ),
      ],
    ),
  );

  Widget _card({required Color color, required Widget child}) => Card(
    elevation: 0,
    color: color,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(18),
      side: const BorderSide(color: Color(0xFFE3E9E6)),
    ),
    child: Padding(padding: const EdgeInsets.all(18), child: child),
  );

  String _commandName(AgentCommand command) => switch (command) {
    AgentCommand.start => '开始',
    AgentCommand.pause => '暂停',
    AgentCommand.stop => '停止',
  };
}

extension<T> on List<T> {
  Iterable<T> takeLast(int count) => skip(length > count ? length - count : 0);
}
