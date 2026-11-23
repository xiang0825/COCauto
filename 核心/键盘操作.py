"""按键输入：把任务层的按键名转换成 Android ``input keyevent``。

只通过 ADB 发送；不向 Windows 窗口发送键盘消息，也不读取真实键盘。
"""


class 键盘控制器:
    # 这些是 Windows/电视遥控器功能键，映射到 Android 后并不是游戏内
    # 操作，部分模拟器会把它们交给桌面或系统应用处理，必须直接丢弃。
    _ADB禁止系统功能键 = {
        "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
        "home", "win", "option", "print",
    }

    def __init__(self, 设备):
        if not hasattr(设备, "按键"):
            raise TypeError("键盘控制器只能绑定 ADB 设备（需要 按键 接口）")
        self._设备 = 设备

    def _禁止(self, 按键码) -> bool:
        return isinstance(按键码, str) and 按键码.lower() in self._ADB禁止系统功能键

    def 按键按下(self, 按键码):
        if self._禁止(按键码):
            return False
        return self._设备.按键(self._转换ADB按键码(按键码))

    def 按键抬起(self, 按键码):
        # Android keyevent 是一次完整按压，没有单独的抬起。
        return True

    def 按键按压(self, 按键码):
        if self._禁止(按键码):
            return False
        return self._设备.按键(self._转换ADB按键码(按键码))

    def 按字符按压(self, 字符码):
        return self.按键按压(str(字符码).lower())

    @staticmethod
    def _转换ADB按键码(按键码):
        """按键名转 Android input keyevent 键值。"""
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
