"""触控输入：把任务层的“鼠标”调用转换成 ADB 触控。

本程序只通过 ADB 操作模拟器，不向 Windows 窗口发送鼠标消息，也不
移动真实鼠标。``鼠标控制器`` 这个名字保留给任务代码，实际都是触控：

- 左键点击 → tap
- 左键按下 + 移动 + 左键抬起 → 未移动时 tap，移动过则 swipe
- 连续点击 / 长按 → 设备提供的批量触控和长按
"""
import threading
import time


_锁初始化锁 = threading.Lock()


class 鼠标控制器:
    def __init__(self, 设备):
        if not (hasattr(设备, "触控") and hasattr(设备, "滑动")):
            raise TypeError("鼠标控制器只能绑定 ADB 设备（需要 触控/滑动 接口）")
        self._设备 = 设备
        self._锁 = threading.RLock()
        self._x = 0
        self._y = 0
        self._按下起点 = None
        self._有移动 = False
        self._按下时间 = 0.0
        # 由任务上下文注入；返回 True 表示当前输入必须被阻断。
        self._安全点击检查回调 = None

    def _获取锁(self) -> threading.RLock:
        锁 = getattr(self, "_锁", None)
        if 锁 is None:
            with _锁初始化锁:
                锁 = getattr(self, "_锁", None)
                if 锁 is None:
                    锁 = threading.RLock()
                    self._锁 = 锁
        return 锁

    # ------------------------------------------------------------ 安全
    def _允许鼠标按下(self):
        回调 = getattr(self, "_安全点击检查回调", None)
        if not callable(回调):
            return True
        try:
            return not bool(回调())
        except Exception:
            # 无法确认页面时宁可不点击，避免误触宝石确认按钮。
            return False

    # ------------------------------------------------------------ 位置
    def 移动到(self, x, y):
        with self._获取锁():
            self._x, self._y = int(x), int(y)
            if self._按下起点 is not None:
                self._有移动 = self._有移动 or (self._x, self._y) != self._按下起点
            return 1

    def 移动相对位置(self, rx, ry):
        with self._获取锁():
            self._x += int(rx)
            self._y += int(ry)
            if self._按下起点 is not None:
                self._有移动 = True
            return 1

    # ------------------------------------------------------------ 点击
    def _左键点击内部(self):
        return self._设备.触控(self._x, self._y)

    def 左键点击(self):
        with self._获取锁():
            if not self._允许鼠标按下():
                return False
            return self._左键点击内部()

    def 连续点击(self, x, y, 次数=1, 间隔毫秒=0, 是否精确点击=True):
        """连续点击同一点；优先复用设备的一次 shell 会话。"""
        次数 = max(0, min(32, int(次数)))
        if 次数 == 0:
            return True
        with self._获取锁():
            if not self._允许鼠标按下():
                return False
            if hasattr(self._设备, "连续触控"):
                return self._设备.连续触控([(int(x), int(y))] * 次数, 间隔毫秒=间隔毫秒)
            for 序号 in range(次数):
                self.移动到(x, y)
                if not self._左键点击内部():
                    return False
                if 序号 < 次数 - 1 and 间隔毫秒 > 0:
                    time.sleep(max(0, int(间隔毫秒)) / 1000)
            return True

    def 连续点击多点(self, 位置列表, 间隔毫秒=0, 是否精确点击=True):
        """在一批已经预检通过的坐标上连续点击（战斗部署专用）。

        先执行一次安全页面检查，再把已通过边界/红色禁区预检的点交给
        设备一次发送。调用方仍需在每批前确认处于战斗页。
        """
        try:
            点位 = [(int(点[0]), int(点[1])) for 点 in 位置列表]
        except (TypeError, ValueError, IndexError):
            return False
        点位 = 点位[:32]
        if not 点位:
            return True
        with self._获取锁():
            if not self._允许鼠标按下():
                return False
            if hasattr(self._设备, "连续触控"):
                return bool(self._设备.连续触控(点位, 间隔毫秒=间隔毫秒))
            for 序号, (x, y) in enumerate(点位):
                self.移动到(x, y)
                if not self._左键点击内部():
                    return False
                if 序号 < len(点位) - 1 and 间隔毫秒 > 0:
                    time.sleep(max(0, int(间隔毫秒)) / 1000)
            return True

    def 长按(self, x, y, 时长毫秒=220, 是否精确点击=True):
        """同点长按；设备使用 input swipe 保持触点。"""
        x, y = int(x), int(y)
        with self._获取锁():
            if not self._允许鼠标按下():
                return False
            self.移动到(x, y)
            if hasattr(self._设备, "长按触控"):
                return self._设备.长按触控(x, y, 时长毫秒=时长毫秒)
            self._左键按下内部()
            time.sleep(max(0, int(时长毫秒)) / 1000)
            return bool(self.左键抬起())

    # ------------------------------------------------------------ 拖动
    def _左键按下内部(self):
        self._按下起点 = (self._x, self._y)
        self._有移动 = False
        self._按下时间 = time.monotonic()
        return 1

    def 左键按下(self):
        with self._获取锁():
            if not self._允许鼠标按下():
                return False
            return self._左键按下内部()

    def 左键抬起(self):
        with self._获取锁():
            起点 = self._按下起点
            self._按下起点 = None
            if 起点 is None:
                return 1
            if not self._有移动:
                return self._设备.触控(self._x, self._y)
            时长 = max(40, min(1500, int((time.monotonic() - self._按下时间) * 1000)))
            return self._设备.滑动(起点, (self._x, self._y), 时长)
