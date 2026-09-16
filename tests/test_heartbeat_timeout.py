import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 线程.自动化机器人 import 自动化机器人


class 心跳超时测试(unittest.TestCase):
    def _创建机器人(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "robot_1"
        机器人.停止事件 = threading.Event()
        机器人.数据库 = SimpleNamespace(
            读取最后日志=Mock(
                return_value=SimpleNamespace(
                    日志内容="仍在等待游戏主页识别",
                    记录时间=70.0,
                    下次超时=100.0,
                )
            )
        )
        return 机器人

    def test_心跳截止瞬间不会因提交竞态误重启(self):
        机器人 = self._创建机器人()

        with patch("线程.自动化机器人.time.time", return_value=101.0):
            self.assertEqual(机器人.检查超时(), (False, ""))

    def test_超过宽限后才判定无心跳(self):
        机器人 = self._创建机器人()

        with patch("线程.自动化机器人.time.time", return_value=106.0):
            超时, 原因 = 机器人.检查超时()

        self.assertTrue(超时)
        self.assertIn("含5秒宽限", 原因)


if __name__ == "__main__":
    unittest.main()
