import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from 任务流程.兵种或法术升级.打开研究面板 import 打开研究面板任务
from 任务流程.兵种或法术升级.打开要升级的兵种或法术 import 打开要升级的兵种或法术任务
from 任务流程.兵种或法术升级.完成兵种或法术升级 import 完成兵种或法术升级任务
from 任务流程.战宠升级.完成宠物升级 import 完成宠物升级任务


class 研究面板OCR护栏测试(unittest.TestCase):
    def test_遍历OCR结果提取合法研究槽位(self):
        结果 = 打开研究面板任务.解析实验室计数([
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "1", 0.99),
            ([[0, 0], [30, 0], [30, 12], [0, 12]], "1/2", 0.88),
        ])
        self.assertEqual(结果, (1, 2))

    def test_单个数字不会再触发解包异常(self):
        with self.assertRaises(ValueError):
            打开研究面板任务.解析实验室计数([
                ([[0, 0], [10, 0], [10, 10], [0, 10]], "1", 0.99),
            ])

    def test_窄区域只有单数字时使用顶部宽区域回退(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.执行OCR识别 = Mock(side_effect=[
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "1", 0.99)],
            [([[20, 10], [55, 10], [55, 32], [20, 32]], "2/2", 0.90)],
        ])
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())

        self.assertTrue(任务._检查实验室是否空闲())
        self.assertEqual(
            任务.执行OCR识别.call_args_list[1].args[0],
            (240, 0, 380, 80),
        )
        self.assertTrue(any(
            "顶部宽区域回退" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_研究目标漏识别时关闭已打开的研究面板(self):
        任务 = 打开要升级的兵种或法术任务.__new__(打开要升级的兵种或法术任务)
        任务.欲升级的兵种或法术 = "雷电法术"
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(),
        )
        任务.执行OCR识别 = Mock(return_value=[])

        self.assertFalse(任务.尝试点击目标兵种或法术())
        任务.上下文.点击.assert_called_once_with(
            668, 32, 是否精确点击=True
        )

    def test_研究目标页面异常交给统一异常处理器(self):
        任务 = 打开要升级的兵种或法术任务.__new__(打开要升级的兵种或法术任务)
        任务.欲升级的兵种或法术 = "雷电法术"
        任务.上下文 = SimpleNamespace()
        任务.执行OCR识别 = Mock(return_value=[])
        任务.当前界面是否存在目标兵种或法术 = Mock(
            side_effect=RuntimeError("测试页面异常")
        )
        任务.异常处理 = Mock()

        self.assertFalse(任务.执行())
        任务.异常处理.assert_called_once()

    def test_未识别实验室研究标签时不发送错误入口点击(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(return_value=False),
        )
        任务._检查实验室是否空闲 = Mock(return_value=True)
        任务._查找实验室标签候选 = Mock(return_value=[])

        self.assertFalse(任务.执行())
        任务.上下文.点击.assert_not_called()

    def test_OCR漏检时不使用固定候选点(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(return_value=True),
        )
        任务._检查实验室是否空闲 = Mock(return_value=True)
        任务._查找实验室标签候选 = Mock(return_value=[])
        任务.最大入口等待秒 = 0.01

        self.assertFalse(任务.执行())
        任务.上下文.点击.assert_not_called()

    def test_候选点未确认实验室时不会点击研究按钮(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
        )
        任务._检查实验室是否空闲 = Mock(return_value=True)
        任务._查找实验室标签候选 = Mock(side_effect=[
            [(455, 352, 0.99, "研究")],
            [],
        ])
        任务._选中后是否为实验室 = Mock(return_value=False)
        任务.最大入口等待秒 = 0.01

        self.assertFalse(任务.执行())
        # 只允许尝试候选建筑和取消选中，绝不能把普通建筑当研究按钮。
        self.assertEqual(任务.上下文.点击.call_count, 7 * 2)
        任务._查找选中实验室研究按钮 = Mock()
        任务._查找选中实验室研究按钮.assert_not_called()

    def test_确认实验室后才点击研究按钮并确认面板(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
        )
        任务._检查实验室是否空闲 = Mock(return_value=True)
        任务._查找实验室标签候选 = Mock(return_value=[(455, 352, 0.99, "研究")])
        任务._选中后是否为实验室 = Mock(return_value=True)
        任务._查找选中实验室研究按钮 = Mock(return_value=(490, 470))
        任务._获取全屏画面 = Mock(return_value=None)
        任务._研究面板已确认 = Mock(return_value=True)
        任务.最大入口等待秒 = 0.01

        self.assertTrue(任务.执行())
        self.assertEqual(
            任务.上下文.点击.call_args_list,
            [
                unittest.mock.call(455, 365, 是否精确点击=True),
                unittest.mock.call(490, 470, 是否精确点击=True),
            ],
        )

    def test_研究目标点击被拒绝时关闭研究面板(self):
        任务 = 打开要升级的兵种或法术任务.__new__(打开要升级的兵种或法术任务)
        任务.欲升级的兵种或法术 = "雷电法术"
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(return_value=False),
            安全返回键=Mock(return_value=True),
        )
        任务.执行OCR识别 = Mock(return_value=[
            ([[120, 120], [220, 120], [220, 145], [120, 145]], "雷电法术", 0.99),
        ])
        任务._检测资源不足 = Mock(return_value=False)
        任务._执行点击 = Mock(return_value=False)
        任务.关闭研究面板 = Mock()

        self.assertFalse(任务.尝试点击目标兵种或法术())
        任务.关闭研究面板.assert_called_once_with()

    def test_关闭研究面板被拒绝时标记页面恢复失败(self):
        任务 = 打开要升级的兵种或法术任务.__new__(打开要升级的兵种或法术任务)
        任务.上下文 = SimpleNamespace(
            点击=Mock(return_value=False),
            置脚本状态=Mock(),
            页面恢复失败=False,
        )

        self.assertFalse(任务.关闭研究面板())
        self.assertTrue(任务.上下文.页面恢复失败)
        self.assertTrue(any(
            "关闭研究面板" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_战宠确认按钮漏识别时关闭升级面板(self):
        任务 = 完成宠物升级任务.__new__(完成宠物升级任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            置脚本状态=Mock(),
            安全返回键=Mock(return_value=True),
        )
        任务.执行OCR识别 = Mock(return_value=[])

        with patch(
            "任务流程.战宠升级.完成宠物升级.是否包含指定颜色_HSV",
            return_value=False,
        ):
            self.assertFalse(任务.执行())

        self.assertEqual(任务.上下文.安全返回键.call_count, 2)
        self.assertTrue(any(
            "未找到确认按钮" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_研究升级确认按钮点击被拒绝时不能报告成功(self):
        任务 = 完成兵种或法术升级任务.__new__(完成兵种或法术升级任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            置脚本状态=Mock(),
            点击=Mock(return_value=False),
            安全返回键=Mock(return_value=True),
        )
        任务.执行OCR识别 = Mock(return_value=[([], "确认", 0.99)])

        with patch(
            "任务流程.兵种或法术升级.完成兵种或法术升级.是否包含指定颜色_HSV",
            return_value=False,
        ):
            self.assertFalse(任务.执行())

        任务.上下文.点击.assert_called_once_with(*任务.确认按钮点击坐标)
        self.assertTrue(any(
            "未能安全点击" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_战宠升级确认按钮点击被拒绝时不能报告成功(self):
        任务 = 完成宠物升级任务.__new__(完成宠物升级任务)
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=object())),
            置脚本状态=Mock(),
            点击=Mock(return_value=False),
            安全返回键=Mock(return_value=True),
        )
        任务.执行OCR识别 = Mock(return_value=[([], "确认", 0.99)])

        with patch(
            "任务流程.战宠升级.完成宠物升级.是否包含指定颜色_HSV",
            return_value=False,
        ):
            self.assertFalse(任务.执行())

        任务.上下文.点击.assert_called_once_with(577, 492)
        self.assertTrue(any(
            "未能安全点击" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()
