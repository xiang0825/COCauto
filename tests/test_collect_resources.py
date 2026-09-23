import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.收集资源 import 收集资源任务


class 资源收集输入测试(unittest.TestCase):
    def _任务(self, 检测结果):
        任务 = 收集资源任务.__new__(收集资源任务)
        任务.检测器 = SimpleNamespace(检测=Mock(return_value=检测结果))
        任务.上下文 = SimpleNamespace(
            游戏内拉远视距=Mock(),
            脚本延时=Mock(),
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=object())
            ),
            置脚本状态=Mock(),
            页面恢复失败=False,
        )
        return 任务

    def test_没有可收集目标时作为正常无操作完成(self):
        任务 = self._任务([])

        self.assertTrue(任务.执行())
        任务.上下文.置脚本状态.assert_not_called()

    def test_收集点击被拒绝时停止并标记页面失败(self):
        任务 = self._任务([{
            "类别名称": "金矿",
            "置信度": 0.95,
            "裁剪坐标": [100, 200, 140, 240],
        }])
        任务.上下文.点击 = Mock(return_value=False)

        self.assertFalse(任务.执行())
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_收集点击成功后返回完成(self):
        任务 = self._任务([{
            "类别名称": "圣水采集器",
            "置信度": 0.95,
            "裁剪坐标": [100, 200, 140, 240],
        }])
        任务.上下文.点击 = Mock(return_value=True)

        self.assertTrue(任务.执行())
        任务.上下文.点击.assert_called_once_with(120, 220, 1000)


if __name__ == "__main__":
    unittest.main()
