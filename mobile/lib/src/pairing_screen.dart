import 'package:material_ui/material_ui.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

class PairingScreen extends StatefulWidget {
  const PairingScreen({super.key, this.onPairingData});

  final Future<void> Function(String payload)? onPairingData;

  @override
  State<PairingScreen> createState() => _PairingScreenState();
}

class _PairingScreenState extends State<PairingScreen> {
  final TextEditingController _payloadController = TextEditingController();
  late final MobileScannerController _scannerController;
  bool _scannerVisible = false;
  bool _handlingPayload = false;
  String? _message;

  @override
  void initState() {
    super.initState();
    _scannerController = MobileScannerController(autoStart: false);
  }

  @override
  void dispose() {
    _payloadController.dispose();
    _scannerController.dispose();
    super.dispose();
  }

  Future<void> _startScanner() async {
    setState(() {
      _scannerVisible = true;
      _message = null;
    });
    try {
      await _scannerController.start();
    } on MobileScannerException catch (error) {
      if (mounted) {
        setState(() {
          _message = error.errorCode == MobileScannerErrorCode.permissionDenied
              ? '需要允许相机权限才能扫描。也可以手动粘贴配对内容。'
              : '相机暂时无法启动，请改用手动输入。';
          _scannerVisible = false;
        });
      }
    }
  }

  Future<void> _onDetect(BarcodeCapture capture) async {
    if (_handlingPayload) return;
    final payload = capture.barcodes
        .map((barcode) => barcode.rawValue)
        .whereType<String>()
        .firstWhere((value) => value.trim().isNotEmpty, orElse: () => '');
    if (payload.isEmpty) return;
    _handlingPayload = true;
    await _scannerController.stop();
    if (!mounted) return;
    setState(() => _scannerVisible = false);
    await _submitPayload(payload);
    _handlingPayload = false;
  }

  Future<void> _submitPayload(String payload) async {
    if (widget.onPairingData == null) {
      setState(() => _message = '配对服务尚未连接，请稍后重试。');
      return;
    }
    setState(() => _message = '正在验证桌面控制端…');
    try {
      await widget.onPairingData!(payload);
      if (mounted) setState(() => _message = '配对成功。');
    } catch (_) {
      if (mounted) {
        setState(() => _message = '配对失败：请确认二维码有效，并且手机与电脑在同一局域网。');
      }
    }
  }

  Future<void> _submitManualPayload() async {
    final value = _payloadController.text.trim();
    if (value.isEmpty) {
      setState(() => _message = '请先粘贴电脑上显示的配对二维码内容。');
      return;
    }
    await _submitPayload(value);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('连接桌面控制端')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          children: [
            const Text(
              '扫描电脑上的配对二维码',
              style: TextStyle(fontSize: 23, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            const Text(
              '先在电脑的「手机控制」页面启动服务并生成配对码。配对码 5 分钟后失效，只能使用一次。',
              key: ValueKey('pairing-instructions'),
              style: TextStyle(height: 1.45),
            ),
            const SizedBox(height: 18),
            if (_scannerVisible)
              ClipRRect(
                borderRadius: BorderRadius.circular(18),
                child: SizedBox(
                  height: 300,
                  child: MobileScanner(
                    controller: _scannerController,
                    onDetect: _onDetect,
                  ),
                ),
              )
            else
              Container(
                height: 180,
                decoration: BoxDecoration(
                  color: const Color(0xFFEAF2EE),
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(color: const Color(0xFFDCE7E1)),
                ),
                child: const Center(
                  child: Icon(
                    Icons.qr_code_scanner,
                    size: 62,
                    color: Color(0xFF2C8A68),
                  ),
                ),
              ),
            const SizedBox(height: 14),
            FilledButton.icon(
              key: const ValueKey('start-camera-scan'),
              onPressed: _scannerVisible ? null : _startScanner,
              icon: const Icon(Icons.camera_alt_outlined),
              label: Text(_scannerVisible ? '正在扫描…' : '打开相机扫描'),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              key: const ValueKey('manual-pairing'),
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                isScrollControlled: true,
                builder: (context) => Padding(
                  padding: EdgeInsets.fromLTRB(
                    20,
                    20,
                    20,
                    MediaQuery.viewInsetsOf(context).bottom + 24,
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Text(
                        '手动粘贴配对内容',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        key: const ValueKey('pairing-payload'),
                        controller: _payloadController,
                        minLines: 2,
                        maxLines: 4,
                        decoration: const InputDecoration(
                          border: OutlineInputBorder(),
                          hintText: '粘贴电脑上的二维码文本',
                        ),
                      ),
                      const SizedBox(height: 12),
                      FilledButton(
                        key: const ValueKey('submit-pairing'),
                        onPressed: () async {
                          await _submitManualPayload();
                          if (context.mounted) Navigator.pop(context);
                        },
                        child: const Text('连接电脑'),
                      ),
                    ],
                  ),
                ),
              ),
              icon: const Icon(Icons.content_paste),
              label: const Text('手动粘贴配对内容'),
            ),
            if (_message case final message?) ...[
              const SizedBox(height: 12),
              Text(message, key: const ValueKey('pairing-message')),
            ],
          ],
        ),
      ),
    );
  }
}
