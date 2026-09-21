import unittest

from 模块.ADB设备操作类 import ADB设备操作类


class MuMu缩放手势测试(unittest.TestCase):
    def test_按display映射找到对应触摸event(self):
        输入状态 = """
Event Hub State:
    27: Xiaomi Touchscreen
      Path: /dev/input/event16
Input Reader State:
  Device 28: Xiaomi Touchscreen
    EventHub Devices: [ 27 ]
      Viewport INTERNAL: displayId=7, uniqueId=local:test
  Device 3: Xiaomi Touchscreen
    EventHub Devices: [ 4 ]
      Viewport INTERNAL: displayId=0, uniqueId=local:test2
"""
        self.assertEqual(
            ADB设备操作类._解析MuMu触摸事件设备(输入状态, "7"),
            "/dev/input/event16",
        )

    def test_生成的是双指向内捏合而不是单指滑动(self):
        脚本 = ADB设备操作类._生成MuMu缩放脚本(
            "/dev/input/event16", 720, 1280, 1280, 720, 1
        )
        self.assertIn("sendevent /dev/input/event16 3 47 0", 脚本)
        self.assertIn("sendevent /dev/input/event16 3 47 1", 脚本)
        self.assertIn("sendevent /dev/input/event16 3 57 100", 脚本)
        self.assertIn("sendevent /dev/input/event16 3 57 101", 脚本)
        self.assertNotIn("input keyevent 135", 脚本)


if __name__ == "__main__":
    unittest.main()
