import importlib
import unittest
from unittest.mock import patch


class 控制台版本显示测试(unittest.TestCase):
    def setUp(self):
        self.入口 = importlib.import_module("UI入口")

    def test_副标题显示打包版本(self):
        with patch("工具包.版本管理.获取本地版本号", return_value="rc81"):
            self.assertEqual(self.入口.生成控制台副标题(), "部落冲突控制台 · 版本：rc81")

    def test_版本读取失败时显示本地版(self):
        with patch("工具包.版本管理.获取本地版本号", side_effect=OSError("版本文件不可读")):
            self.assertEqual(self.入口.生成控制台副标题(), "部落冲突控制台 · 版本：本地版")

    def test_空版本号显示本地版(self):
        with patch("工具包.版本管理.获取本地版本号", return_value="  "):
            self.assertEqual(self.入口.读取版本号(), "本地版")


if __name__ == "__main__":
    unittest.main()
