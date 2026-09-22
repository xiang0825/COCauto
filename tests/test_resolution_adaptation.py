import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.检查图像 import 检查图像任务
from 模块.ADB设备操作类 import ADB设备操作类


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

    def test_参考截图区域在宽屏上映射并缩放回统一画布(self):
        设备 = ADB设备操作类.__new__(ADB设备操作类)
        设备.参考宽度 = 800
        设备.参考高度 = 600
        # 用横向渐变验证不是简单裁剪左上角：参考右边界应对应物理
        # 1280 的右边界，返回尺寸仍然是任务使用的 800×600。
        画面 = np.zeros((720, 1280, 3), dtype=np.uint8)
        画面[:, :, 0] = np.arange(1280, dtype=np.uint8)[None, :]
        编码成功, 编码图 = cv2.imencode(".png", 画面)
        self.assertTrue(编码成功)
        # 覆盖 ADB 截图依赖，实际调用公共截图方法，验证最终区域映射逻辑。
        设备._验证目标 = lambda: None
        设备._检查主机内存预算 = lambda: None
        设备._截图重试上限 = 1
        设备._是MuMu连接 = lambda: False
        设备.执行 = lambda *args, **kwargs: 编码图.tobytes()
        结果 = 设备.获取屏幕图像cv(0, 0, 800, 600)
        self.assertEqual(结果.shape[:2], (600, 800))
        self.assertGreater(int(结果[:, -1, 0].mean()), 200)


if __name__ == "__main__":
    unittest.main()
