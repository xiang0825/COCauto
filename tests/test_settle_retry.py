"""结算页动画导致字段不完整时的补拍与安全回营（rc147）。"""
import unittest
import unittest.mock
from types import SimpleNamespace

from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务


class _屏幕:
    def __init__(self):
        self.次数 = 0

    def 获取屏幕图像cv(self, *_区域, **_参数):
        self.次数 += 1
        return object()


class _上下文:
    def __init__(self, 页面="战斗结算", 可信度=0.85):
        self.op = _屏幕()
        self.状态 = []
        self.页面 = 页面
        self.可信度 = 可信度
        self.视觉点 = None

    def 脚本延时(self, _毫秒):
        pass

    def 置脚本状态(self, 文本, *参数, **关键字参数):
        self.状态.append(文本)

    def _获取点击页面识别器(self):
        上下文 = self

        class 识别器:
            def 识别(self, _图, 战斗中=False):
                return SimpleNamespace(页面=上下文.页面, 可信度=上下文.可信度)

            def 定位结算回营按钮(self, _图, **_参数):
                return 上下文.视觉点

        return 识别器()


def _任务(匹配点=(400, 515), 命中=True):
    任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
    任务.模板识别 = SimpleNamespace(
        执行匹配=lambda *_a, **_k: (命中, 匹配点, None)
    )
    任务._画面仍在战斗 = lambda *_a: False
    任务._本场统计已写入 = False
    return 任务


class 结算补拍测试(unittest.TestCase):
    def test_动画结束后补拍成功即记录(self):
        任务 = _任务()
        结果 = iter([False, True])
        任务.记录战斗结果 = unittest.mock.Mock(side_effect=lambda *a: next(结果))
        上下文 = _上下文()
        self.assertTrue(任务._结算动画后补记或安全回营(上下文, (400, 515), (0, 0, 800, 600), True))
        self.assertEqual(任务.记录战斗结果.call_count, 2)

    def test_已写入统计后不重复记录但两帧确认可安全回营(self):
        任务 = _任务()
        任务._本场统计已写入 = True
        任务.记录战斗结果 = unittest.mock.Mock(return_value=False)
        上下文 = _上下文()
        self.assertTrue(任务._结算动画后补记或安全回营(上下文, (400, 515), (0, 0, 800, 600), True))
        任务.记录战斗结果.assert_not_called()
        self.assertTrue(any("不计入" in 文本 for 文本 in 上下文.状态))

    def test_补拍仍不完整且页面不是结算页时保持等待(self):
        任务 = _任务()
        任务.记录战斗结果 = unittest.mock.Mock(return_value=False)
        上下文 = _上下文(页面="战斗中")
        self.assertFalse(任务._结算动画后补记或安全回营(上下文, (400, 515), (0, 0, 800, 600), True))

    def test_回营按钮位置跳变不回营(self):
        任务 = _任务(匹配点=(600, 300))
        任务.记录战斗结果 = unittest.mock.Mock(return_value=False)
        上下文 = _上下文()
        self.assertFalse(任务._结算动画后补记或安全回营(上下文, (400, 515), (0, 0, 800, 600), True))

    def test_模板未命中时可用页级视觉定位点(self):
        任务 = _任务(命中=False)
        任务.记录战斗结果 = unittest.mock.Mock(return_value=False)
        上下文 = _上下文()
        上下文.视觉点 = (95, 470)
        self.assertTrue(任务._两帧确认结算页可回营(上下文, (100, 475), (0, 0, 800, 600)))
        上下文.视觉点 = None
        self.assertFalse(任务._两帧确认结算页可回营(上下文, (100, 475), (0, 0, 800, 600)))

    def test_仍在战斗时不回营(self):
        任务 = _任务()
        任务._画面仍在战斗 = lambda *_a: True
        任务.记录战斗结果 = unittest.mock.Mock(return_value=False)
        上下文 = _上下文()
        self.assertFalse(任务._结算动画后补记或安全回营(上下文, (400, 515), (0, 0, 800, 600), True))
        任务.记录战斗结果.assert_not_called()

    def test_毁率标签也能提取摧毁率(self):
        提取 = 等待战斗结束并回营任务.从OCR结果提取摧毁率
        框1 = [[280, 190], [320, 190], [320, 210], [280, 210]]
        框2 = [[340, 190], [380, 190], [380, 210], [340, 210]]
        框3 = [[100, 20], [200, 20], [200, 40], [100, 40]]
        self.assertEqual(提取([(框3, "1234567"), (框1, "毁率"), (框2, "72")]), 72)
        self.assertEqual(提取([(框1, "毁率31000000100%")]), 100)
        self.assertIsNone(提取([(框1, "毁率3100000056%")]))


if __name__ == "__main__":
    unittest.main()
