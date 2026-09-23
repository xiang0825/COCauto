import unittest

from 工具包.工具函数 import 是否家乡资源打满, 是否夜世界资源打满


class 资源打满判断测试(unittest.TestCase):
    def test_主世界允许OCR在容量末尾有小偏差(self):
        self.assertTrue(是否家乡资源打满({
            "金币": 20_000_634,
            "圣水": 20_010_071,
            "黑油": 362_905,
            "识别成功": True,
        }))

    def test_低本黑油为零不阻塞打满判断(self):
        self.assertTrue(是否家乡资源打满({
            "金币": 1_000_000,
            "圣水": 1_000_000,
            "黑油": 0,
        }))

    def test_识别失败或中间值不能误判已满(self):
        self.assertFalse(是否家乡资源打满({
            "金币": 20_000_000,
            "圣水": 20_000_000,
            "黑油": 0,
            "识别成功": False,
        }))
        self.assertFalse(是否家乡资源打满({
            "金币": 19_000_000,
            "圣水": 20_000_000,
            "黑油": 0,
        }))

    def test_夜世界仍需同时确认两种资源(self):
        self.assertFalse(是否夜世界资源打满({
            "金币": 20_000_000,
            "圣水": 19_000_000,
        }))
        self.assertTrue(是否夜世界资源打满({
            "金币": 20_000_634,
            "圣水": 20_010_071,
        }))


if __name__ == "__main__":
    unittest.main()
