import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from 任务流程.检查图像 import 检查图像任务


class 分辨率自适应测试(unittest.TestCase):
    def test_检查图像接受任意有效截图尺寸(self):
        日志 = []
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(
                    return_value=np.zeros((720, 1280, 3), dtype=np.uint8)
                )
            ),
            置脚本状态=日志.append,
        )
        任务 = 检查图像任务.__new__(检查图像任务)
        任务.上下文 = 上下文

        self.assertTrue(任务.执行())
        上下文.op.获取屏幕图像cv.assert_called_once_with(0, 0, 2000, 2000)
        self.assertIn("1280×720", 日志[0])


if __name__ == "__main__":
    unittest.main()
