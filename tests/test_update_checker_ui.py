import importlib
import queue
import unittest
from unittest.mock import patch

from 工具包.更新检查器 import 解析最新发布


class 假控件:
    def __init__(self):
        self.属性 = {}

    def configure(self, **属性):
        self.属性.update(属性)


class 更新检查界面测试(unittest.TestCase):
    def setUp(self):
        self.入口 = importlib.import_module("UI入口")
        self.界面 = self.入口.增强型机器人控制界面.__new__(
            self.入口.增强型机器人控制界面
        )
        self.界面._当前版本 = "rc114"
        self.界面._版本检查中 = False
        self.界面._版本检查结果队列 = queue.Queue()
        self.界面.更新检查按钮 = 假控件()
        self.界面.更新提示标签 = 假控件()

    def test_启动版本检查只创建后台线程不在Tk调用栈请求网络(self):
        已创建线程 = []

        class 假线程:
            def __init__(self, target, daemon, name):
                self.target = target
                self.daemon = daemon
                self.name = name
                已创建线程.append(self)

            def start(self):
                pass

        with patch("UI入口.threading.Thread", 假线程), patch(
            "UI入口.获取最新发布",
            side_effect=AssertionError("网络请求必须由后台线程执行"),
        ):
            self.界面._开始版本检查(手动=False)

        self.assertEqual(len(已创建线程), 1)
        self.assertTrue(已创建线程[0].daemon)
        self.assertTrue(self.界面._版本检查中)
        self.assertEqual(self.界面.更新检查按钮.属性["text"], "检查中…")

    def test_后台发现新版本后首页显示可点击的更新提示(self):
        发布 = 解析最新发布([{
            "tag_name": "v2026.11.19-rc115",
            "name": "rc115",
            "body": "new build",
            "html_url": "https://github.com/xiang0825/COCauto/releases/tag/v2026.11.19-rc115",
            "published_at": "2026-11-19T03:35:35Z",
            "draft": False,
            "prerelease": True,
        }])
        self.界面._版本检查结果队列.put((发布, False))

        self.界面._处理版本检查结果()

        self.assertEqual(
            self.界面.更新提示标签.属性["text"],
            "发现新版本 rc115 · 点击查看",
        )
        self.assertFalse(self.界面._版本检查中)

    def test_断网结果不显示错误弹窗且恢复手动检查按钮(self):
        self.界面._版本检查中 = True
        self.界面._版本检查结果队列.put((None, True))

        self.界面._处理版本检查结果()

        self.assertFalse(self.界面._版本检查中)
        self.assertEqual(self.界面.更新检查按钮.属性["state"], "normal")
        self.assertEqual(self.界面.更新提示标签.属性["text"], "")


if __name__ == "__main__":
    unittest.main()
