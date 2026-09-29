"""确保延迟导入的世界切换任务不会从 Windows 打包版中消失。"""

import unittest

from PyInstaller.utils.hooks import collect_submodules


class 打包模块测试(unittest.TestCase):
    def test_世界切换任务都被自动收集(self):
        模块 = set(collect_submodules("任务流程"))
        self.assertIn("任务流程.世界跳转.到主世界任务", 模块)
        self.assertIn("任务流程.世界跳转.到夜世界任务", 模块)


if __name__ == "__main__":
    unittest.main()
