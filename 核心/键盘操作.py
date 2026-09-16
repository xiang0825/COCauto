import win32api
import win32con
import win32gui
import time

class 键盘控制器:
    # 这些是 Windows/电视遥控器功能键，映射到 Android 后并不是游戏内
    # 的缩放操作，部分模拟器会把它们交给桌面或系统应用处理。ADB 模式
    # 下必须直接丢弃，不能把 Windows 的 F5 等按键码发送进模拟器。
    _ADB禁止系统功能键 = {
        "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
        "home", "win", "option", "print",
    }

    def __init__(self,窗口句柄=None , 模式='Windows消息模式',):
        self._adb设备 = None
        self._窗口句柄 = None
        self._模式 = 0
        self._按键映射 = {
            '1': 49, '2': 50, '3': 51, '4': 52, '5': 53, '6': 54, '7': 55, '8': 56, '9': 57, '0': 48,
            '-': 189, '=': 187, 'back': 8, 'a': 65, 'b': 66, 'c': 67, 'd': 68, 'e': 69, 'f': 70, 'g': 71, 'h': 72, 'i': 73,
            'j': 74, 'k': 75, 'l': 76, 'm': 77, 'n': 78, 'o': 79, 'p': 80, 'q': 81, 'r': 82, 's': 83, 't': 84, 'u': 85,
            'v': 86, 'w': 87, 'x': 88, 'y': 89, 'z': 90, 'ctrl': 17, 'alt': 18, 'shift': 16, 'win': 91, 'space': 32,
            'cap': 20, 'tab': 9, '~': 192, 'esc': 27, 'enter': 13, 'up': 38, 'down': 40, 'left': 37, 'right': 39,
            'option': 93, 'print': 44, 'delete': 46, 'home': 36, 'end': 35, 'pgup': 33, 'pgdn': 34, 'f1': 112, 'f2': 113,
            'f3': 114, 'f4': 115, 'f5': 116, 'f6': 117, 'f7': 118, 'f8': 119, 'f9': 120, 'f10': 121, 'f11': 122, 'f12': 123,
            '[': 219, ']': 221, '\\': 220, ';': 186, "'": 222, ',': 188, '.': 190, '/': 191
        }
        if hasattr(窗口句柄, '按键'):
            self._adb设备 = 窗口句柄
            self._窗口句柄 = None
            self._模式 = 'ADB模式'
        else:
            self.绑定(窗口句柄 , 模式)

    def 绑定(self, 窗口句柄, 模式):
        if hasattr(窗口句柄, '按键'):
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

    def 获取按键状态(self, 按键码):
        按键码 = self._按键映射.get(按键码.lower(), ord(按键码.upper())) if isinstance(按键码, str) else 按键码
        return 0x8000 & win32api.GetAsyncKeyState(按键码)

    def 按键按下(self, 按键码):
        if self._adb设备 is not None:
            if isinstance(按键码, str) and 按键码.lower() in self._ADB禁止系统功能键:
                return False
            return self._adb设备.按键(self._转换ADB按键码(按键码))
        按键码 = self._按键映射.get(按键码.lower(), ord(按键码.upper())) if isinstance(按键码, str) else 按键码
        返回值 = 0
        if self._模式 == '普通模式':
            输入 = win32api.INPUT(type=win32con.INPUT_KEYBOARD, ki=win32api.KEYBDINPUT(wVk=按键码, dwFlags=0))
            返回值 = win32api.SendInput(1, [输入], win32api.sizeof(输入))
        elif self._模式 == '普通模式2':
            输入 = win32api.INPUT(type=win32con.INPUT_KEYBOARD, ki=win32api.KEYBDINPUT(wVk=0, wScan=win32api.MapVirtualKey(按键码, win32con.MAPVK_VK_TO_VSC), dwFlags=win32con.KEYEVENTF_SCANCODE))
            返回值 = win32api.SendInput(1, [输入], win32api.sizeof(输入))
        elif self._模式 == 'Windows消息模式':
            扫描码 = win32api.MapVirtualKey(按键码, 0)
            按键数据 = 1 | (扫描码 << 16)
            返回值 = win32gui.SendMessageTimeout(self._窗口句柄, win32con.WM_KEYDOWN, 按键码, 按键数据, win32con.SMTO_BLOCK, 2000)
        return 返回值

    def 按键抬起(self, 按键码):
        if self._adb设备 is not None:
            return True
        按键码 = self._按键映射.get(按键码.lower(), ord(按键码.upper())) if isinstance(按键码, str) else 按键码
        返回值 = 0
        if self._模式 == '普通模式':
            输入 = win32api.INPUT(type=win32con.INPUT_KEYBOARD, ki=win32api.KEYBDINPUT(wVk=按键码, dwFlags=win32con.KEYEVENTF_KEYUP))
            返回值 = win32api.SendInput(1, [输入], win32api.sizeof(输入))
        elif self._模式 == '普通模式2':
            输入 = win32api.INPUT(type=win32con.INPUT_KEYBOARD, ki=win32api.KEYBDINPUT(wVk=0, wScan=win32api.MapVirtualKey(按键码, win32con.MAPVK_VK_TO_VSC), dwFlags=win32con.KEYEVENTF_SCANCODE | win32con.KEYEVENTF_KEYUP))
            返回值 = win32api.SendInput(1, [输入], win32api.sizeof(输入))
        elif self._模式 == 'Windows消息模式':
            扫描码 = win32api.MapVirtualKey(按键码, 0)
            按键数据 = 1 | (扫描码 << 16) | (3 << 30)
            返回值 = win32gui.SendMessageTimeout(self._窗口句柄, win32con.WM_KEYUP, 按键码, 按键数据, win32con.SMTO_BLOCK, 2000)
        return 返回值

    def 等待按键(self, 按键码, 超时时间):
        按键码 = self._按键映射.get(按键码.lower(), ord(按键码.upper())) if isinstance(按键码, str) else 按键码
        截止时间 = win32api.GetTickCount64() + 超时时间
        while win32api.GetTickCount64() < 截止时间:
            if self.获取按键状态(按键码):
                return 1
            time.sleep(0.001)
        return 0

    def 按键按压(self, 按键码):
        if self._adb设备 is not None:
            return self._adb设备.按键(self._转换ADB按键码(按键码))
        self.按键按下(按键码)
        if self._模式 == '普通模式':
            time.sleep(0.05)
        elif self._模式 == '普通模式2':
            time.sleep(0.05)
        elif self._模式 == 'Windows消息模式':
            time.sleep(0.05)
        return self.按键抬起(按键码)

    def 按字符按压(self, 字符码):
        字符码 = 字符码.lower()
        if self._adb设备 is not None:
            if 字符码 in self._ADB禁止系统功能键:
                return False
            return self._adb设备.按键(self._转换ADB按键码(字符码))
        按键码 = self._按键映射.get(字符码, ord(字符码[0]))
        return self.按键按压(按键码)

    @staticmethod
    def _转换ADB按键码(按键码):
        """Windows 虚拟键名转 Android input keyevent 键值。"""
        if isinstance(按键码, int):
            return 按键码
        名称 = str(按键码).lower()
        固定键 = {
            'esc': 4, 'back': 4, 'enter': 66, 'space': 62, 'tab': 61,
            'up': 19, 'down': 20, 'left': 21, 'right': 22,
            'delete': 67, 'backspace': 67, 'home': 3, 'f1': 131, 'f2': 132,
            'f3': 133, 'f4': 134, 'f5': 135, 'f6': 136, 'f7': 137, 'f8': 138,
            'f9': 139, 'f10': 140, 'f11': 141, 'f12': 142,
        }
        if 名称 in 固定键:
            return 固定键[名称]
        if len(名称) == 1 and '0' <= 名称 <= '9':
            return 7 + int(名称)
        if len(名称) == 1 and 'a' <= 名称 <= 'z':
            return 29 + ord(名称) - ord('a')
        raise ValueError(f"ADB 输入不支持按键：{按键码}")


# 使用示例
# 键盘控制 = 键盘控制()
# 键盘控制.绑定(1574814, 'Windows消息模式')
# 键盘控制.按字符按压('f5')
