import win32api
import win32con
import win32gui
import time


import win32api
import win32con
import win32gui
import time

class 鼠标控制器:
    def __init__(self, 窗口句柄=None , 模式='Windows消息模式', 每英寸点数=1,):
        self._每英寸点数 = 每英寸点数
        self._模式 = 模式
        self._窗口句柄 = 窗口句柄
        self._x = 0
        self._y = 0
        self._adb设备 = None
        self._adb按下起点 = None
        self._adb有移动 = False
        self._adb按下时间 = 0.0
        # 由任务上下文注入；返回 True 表示当前输入必须被阻断。
        self._安全点击检查回调 = None
        if hasattr(窗口句柄, '触控') and hasattr(窗口句柄, '滑动'):
            self._adb设备 = 窗口句柄
            self._模式 = 'ADB模式'

    def 移动到(self, x, y):
        if self._adb设备 is not None:
            self._x, self._y = int(x), int(y)
            if self._adb按下起点 is not None:
                self._adb有移动 = self._adb有移动 or (self._x, self._y) != self._adb按下起点
            return 1
        x *= self._每英寸点数
        y *= self._每英寸点数
        返回值 = 0

        if self._模式 == '普通模式':
            if self._窗口句柄:
                点 = win32gui.ClientToScreen(self._窗口句柄, (x, y))
                x, y = 点[0], 点[1]

            屏幕宽度值 = win32api.GetSystemMetrics(win32con.SM_CXSCREEN) - 1
            屏幕高度值 = win32api.GetSystemMetrics(win32con.SM_CYSCREEN) - 1
            fx = x * (65535.0 / 屏幕宽度值)
            fy = y * (65535.0 / 屏幕高度值)

            win32api.mouse_event(win32con.MOUSEEVENTF_MOVE | win32con.MOUSEEVENTF_ABSOLUTE, int(fx), int(fy))
            返回值 = 1

        elif self._模式 == 'Windows消息模式':
            返回值 = win32gui.SendMessageTimeout(self._窗口句柄, win32con.WM_MOUSEMOVE, 0, win32api.MAKELONG(x, y),
                                                 win32con.SMTO_BLOCK, 2000)

        self._x, self._y = x, y
        return 返回值

    def _允许鼠标按下(self):
        回调 = getattr(self, "_安全点击检查回调", None)
        if not callable(回调):
            return True
        try:
            return not bool(回调())
        except Exception:
            # 无法确认页面时宁可不点击，避免误触宝石确认按钮。
            return False

    def _左键点击内部(self):
        if self._adb设备 is not None:
            return self._adb设备.触控(self._x, self._y)
        返回值, 返回值2 = 0, 0

        if self._模式 == '普通模式':
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.01)  # 鼠标普通延迟
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            返回值, 返回值2 = 1, 1

        elif self._模式 == 'Windows消息模式':
            返回值 = win32gui.SendMessageTimeout(self._窗口句柄, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON,
                                                 win32api.MAKELONG(self._x, self._y), win32con.SMTO_BLOCK, 2000)
            time.sleep(0.01)  # 鼠标Windows延迟
            返回值2 = win32gui.SendMessageTimeout(self._窗口句柄, win32con.WM_LBUTTONUP, 0,
                                                  win32api.MAKELONG(self._x, self._y), win32con.SMTO_BLOCK, 2000)

        return 返回值 and 返回值2

    def 左键点击(self):
        if not self._允许鼠标按下():
            return False
        return self._左键点击内部()

    def 连续点击(self, x, y, 次数=1, 间隔毫秒=0, 是否精确点击=True):
        """连续点击同一点；ADB 模式优先复用一次 shell 会话。"""
        次数 = max(0, min(32, int(次数)))
        if 次数 == 0:
            return True
        if not self._允许鼠标按下():
            return False
        if self._adb设备 is not None and hasattr(self._adb设备, '连续触控'):
            return self._adb设备.连续触控(
                [(int(x), int(y))] * 次数,
                间隔毫秒=间隔毫秒,
            )

        for 序号 in range(次数):
            self.移动到(int(x), int(y))
            if not self._左键点击内部():
                return False
            if 序号 < 次数 - 1 and 间隔毫秒 > 0:
                time.sleep(max(0, int(间隔毫秒)) / 1000)
        return True

    def 长按(self, x, y, 时长毫秒=220, 是否精确点击=True):
        """执行同点长按；ADB 模式使用 input swipe 保持触点。"""
        x, y = int(x), int(y)
        if not self._允许鼠标按下():
            return False
        self.移动到(x, y)
        if self._adb设备 is not None and hasattr(self._adb设备, '长按触控'):
            return self._adb设备.长按触控(x, y, 时长毫秒=时长毫秒)
        self._左键按下内部()
        time.sleep(max(0, int(时长毫秒)) / 1000)
        return bool(self.左键抬起())

    def 绑定(self, 窗口句柄, 模式='Windows消息模式'):
        if hasattr(窗口句柄, '触控') and hasattr(窗口句柄, '滑动'):
            self._adb设备 = 窗口句柄
            self._窗口句柄 = None
            self._模式 = 'ADB模式'
            return 1
        if not win32gui.IsWindow(窗口句柄):
            return 0
        self._adb设备 = None
        self._窗口句柄 = 窗口句柄
        self._模式 = 模式
        return 1

    def 解除绑定(self):
        self._窗口句柄 = None
        self._adb设备 = None
        self._模式 = 0
        return 1

    def 移动相对位置(self, rx, ry):
        if self._adb设备 is not None:
            self._x += int(rx)
            self._y += int(ry)
            if self._adb按下起点 is not None:
                self._adb有移动 = True
            return 1
        if self._模式 == '普通模式':
            self._x += rx
            self._y += ry

            输入 = win32api.INPUT()
            输入.type = win32con.INPUT_MOUSE
            输入.mi = win32api.MOUSEINPUT(dx=rx, dy=ry, dwFlags=win32con.MOUSEEVENTF_MOVE)
            return win32api.SendInput(1, [输入], win32api.sizeof(输入)) > 0
        return self.移动到(self._x + rx, self._y + ry)

    def _左键按下内部(self):
        if self._adb设备 is not None:
            self._adb按下起点 = (self._x, self._y)
            self._adb有移动 = False
            self._adb按下时间 = time.monotonic()
            return 1
        if self._模式 == '普通模式':
            输入 = win32api.INPUT()
            输入.type = win32con.INPUT_MOUSE
            输入.mi = win32api.MOUSEINPUT(dwFlags=win32con.MOUSEEVENTF_LEFTDOWN)
            return win32api.SendInput(1, [输入], win32api.sizeof(输入)) > 0
        return win32gui.SendMessageTimeout(self._窗口句柄, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON,
                                           win32api.MAKELONG(self._x, self._y), win32con.SMTO_BLOCK, 2000)

    def 左键按下(self):
        if not self._允许鼠标按下():
            return False
        return self._左键按下内部()

    def 左键抬起(self):
        if self._adb设备 is not None:
            起点 = self._adb按下起点
            self._adb按下起点 = None
            if 起点 is None:
                return 1
            if not self._adb有移动:
                return self._adb设备.触控(self._x, self._y)
            时长 = max(40, min(1500, int((time.monotonic() - self._adb按下时间) * 1000)))
            return self._adb设备.滑动(起点, (self._x, self._y), 时长)
        if self._模式 == '普通模式':
            输入 = win32api.INPUT()
            输入.type = win32con.INPUT_MOUSE
            输入.mi = win32api.MOUSEINPUT(dwFlags=win32con.MOUSEEVENTF_LEFTUP)
            return win32api.SendInput(1, [输入], win32api.sizeof(输入)) > 0
        return win32gui.SendMessageTimeout(self._窗口句柄, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON,
                                           win32api.MAKELONG(self._x, self._y), win32con.SMTO_BLOCK, 2000)



# 使用示例
# 鼠标控制 = 鼠标控制器(67174)
# 鼠标控制.移动到(376,273)
# 鼠标控制.左键点击()
# time.sleep(1)
# 鼠标控制.移动到(376, 376)
# 鼠标控制.左键按下()
# for _ in range(30):
#     鼠标控制.移动相对位置(0,-3)
#     time.sleep(0.08)
# 鼠标控制.左键抬起()
# # 鼠标控制.左键点击()

#
#

# op.Delay(500)
# op.MoveTo(467, 363)
# op.LeftDown()
# for _ in range(30):
#     op.MoveR(0, -3)
#     op.Delay(5)
# op.LeftUp()
# op.Delay(2000)
# class 鼠标控制器:
#     def __init__(self, 窗口句柄=None , 模式='Windows消息模式', 每英寸点数=1,):
#         self._每英寸点数 = 每英寸点数
#         self._模式 = 模式
#         self._窗口句柄 = 窗口句柄
#         self._x = 0
#         self._y = 0
#
#     def 绑定(self, 窗口句柄, 模式):
#         if not win32gui.IsWindow(窗口句柄):
#             return 0
#         self._窗口句柄 = 窗口句柄
#         self._模式 = 模式
#         return 1
#
#     def 解除绑定(self):
#         self._窗口句柄 = None
#         self._模式 = 'Windows消息模式'
#         return 1
#
#     def 移动到(self, x, y):
#         x *= self._每英寸点数
#         y *= self._每英寸点数
#         返回值 = 0
#
#         if self._模式 == '普通模式':
#             if self._窗口句柄:
#                 点 = win32gui.ClientToScreen(self._窗口句柄, (x, y))
#                 x, y = 点[0], 点[1]
#
#             屏幕宽度值 = win32api.GetSystemMetrics(win32con.SM_CXSCREEN) - 1
#             屏幕高度值 = win32api.GetSystemMetrics(win32con.SM_CYSCREEN) - 1
#             fx = x * (65535.0 / 屏幕宽度值)
#             fy = y * (65535.0 / 屏幕高度值)
#
#             win32api.mouse_event(win32con.MOUSEEVENTF_MOVE | win32con.MOUSEEVENTF_ABSOLUTE, int(fx), int(fy))
#             返回值 = 1
#
#         elif self._模式 == 'Windows消息模式':
#             返回值 = win32gui.SendMessageTimeout(self._窗口句柄, win32con.WM_MOUSEMOVE, 0, win32api.MAKELONG(x, y),
#                                                  win32con.SMTO_BLOCK, 2000)
#
#         self._x, self._y = x, y
#         return 返回值
#
#     def 左键点击(self):
#         返回值, 返回值2 = 0, 0
#
#         if self._模式 == '普通模式':
#             win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
#             time.sleep(0.01)  # 鼠标普通延迟
#             win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
#             返回值, 返回值2 = 1, 1
#
#         elif self._模式 == 'Windows消息模式':
#             返回值 = win32gui.SendMessageTimeout(self._窗口句柄, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON,
#                                                  win32api.MAKELONG(self._x, self._y), win32con.SMTO_BLOCK, 2000)
#             time.sleep(0.01)  # 鼠标Windows延迟
#             返回值2 = win32gui.SendMessageTimeout(self._窗口句柄, win32con.WM_LBUTTONUP, 0,
#                                                   win32api.MAKELONG(self._x, self._y), win32con.SMTO_BLOCK, 2000)
#
#         return 返回值 and 返回值2

#
# # 使用示例
# 鼠标控制 = 鼠标控制器(198252)
# 鼠标控制.移动到(225, 148)
# 鼠标控制.左键点击()
