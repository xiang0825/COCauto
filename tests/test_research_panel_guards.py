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
        任务.上下文.点击.assert_any_call(
            668, 32, 是否精确点击=True
        )

    def test_研究任务开始前清理中断遗留目标页(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            op=SimpleNamespace(),
            页面恢复失败=False,
            识别点击画面=Mock(
                return_value=SimpleNamespace(页面="主世界主页", 世界="主世界")
            ),
        )
        任务._执行局部放大OCR = Mock(side_effect=[
            [([[0, 0], [100, 0], [100, 30], [0, 30]],
              "請選選要升級的目標", 0.87)],
            [],
        ])

        self.assertTrue(任务._清理残留研究面板())
        self.assertEqual(
            任务.上下文.点击.call_args_list,
            [
                unittest.mock.call(668, 32, 是否精确点击=True),
                unittest.mock.call(100, 300, 是否精确点击=True),
            ],
        )
        self.assertFalse(任务.上下文._研究面板已确认)

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

    def test_拉远镜头后的下半区研究标签仍在搜索范围内(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务._执行局部放大OCR = Mock(return_value=[
            ([[980, 610], [1050, 610], [1050, 662], [980, 662]], "研究", 0.65),
        ])

        候选 = 任务._查找实验室标签候选()

        self.assertEqual(任务.建筑标签搜索区域, (200, 300, 700, 520))
        self.assertEqual(任务.局部OCR放大倍数, 4)
        self.assertEqual(len(候选), 1)
        self.assertAlmostEqual(候选[0][0], 453.75, delta=1.0)
        self.assertAlmostEqual(候选[0][1], 459.0, delta=1.0)

    def test_窄区域漏检时使用下半区回退OCR(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.上下文 = SimpleNamespace(置脚本状态=Mock())
        任务._执行局部放大OCR = Mock(side_effect=[
            [],
            [
                ([[1027, 977], [1092, 982], [1089, 1030], [1023, 1025]],
                 "研究", 0.95),
            ],
        ])

        候选 = 任务._查找实验室标签候选()

        self.assertEqual(
            任务._执行局部放大OCR.call_args_list[0].args[0],
            任务.建筑标签搜索区域,
        )
        self.assertEqual(
            任务._执行局部放大OCR.call_args_list[1].args[0],
            任务.建筑标签搜索回退区域,
        )
        self.assertEqual(
            任务._执行局部放大OCR.call_args_list[1].kwargs["颜色通道"],
            "蓝色",
        )
        self.assertEqual(len(候选), 1)
        self.assertAlmostEqual(候选[0][0], 424.625, delta=1.0)
        self.assertAlmostEqual(候选[0][1], 490.875, delta=1.0)
        任务.上下文.置脚本状态.assert_called_once()

    def test_研究标签常见OCR别名被规范化(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        结果 = 任务._查找放大文字(
            [
                ([[0, 0], [80, 0], [80, 30], [0, 30]], "环究", 0.51),
            ],
            (160, 240, 760, 570),
            ("研究",),
            最低置信度=0.45,
        )
        self.assertEqual(len(结果), 1)

    def test_普通升级按钮会拒绝背景研究字(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        结果 = [
            ([[466, 500], [530, 500], [530, 546], [466, 546]],
             "研究", 0.86),
            ([[533, 526], [629, 526], [629, 600], [533, 600]],
             "升级", 0.94),
        ]
        self.assertTrue(
            任务._结果存在普通升级按钮(
                结果,
                任务.研究按钮搜索区域,
            )
        )
        任务.上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock()),
        )
        任务._执行局部放大OCR = Mock(return_value=结果)
        self.assertIsNone(任务._查找选中实验室研究按钮())

    def test_研究入口先关闭残留普通建筑详情(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
            页面恢复失败=False,
        )
        任务._执行局部放大OCR = Mock(return_value=[
            ([[533, 526], [629, 526], [629, 600], [533, 600]],
             "升级", 0.94),
            ([[183, 523], [276, 523], [276, 596], [183, 596]],
             "資訊", 0.75),
        ])

        self.assertTrue(任务._清理普通建筑详情())
        任务.上下文.点击.assert_called_once_with(
            700, 300, 是否精确点击=True
        )

    def test_候选详情取消被拒绝时停止研究入口(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.上下文 = SimpleNamespace(
            点击=Mock(return_value=False),
            置脚本状态=Mock(),
        )

        self.assertFalse(任务._安全取消建筑选中())
        self.assertTrue(任务.上下文.页面恢复失败)
        任务.上下文.置脚本状态.assert_called()

    def test_研究目标页兼容OCR重复选择字(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务._执行局部放大OCR = Mock(return_value=[
            ([[0, 0], [100, 0], [100, 30], [0, 30]],
             "請選選要升級的目標", 0.87),
        ])

        self.assertTrue(任务._研究面板已确认())

    def test_实验室详情页不能冒充研究目标页(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务._执行局部放大OCR = Mock(return_value=[
            ([[0, 0], [100, 0], [100, 30], [0, 30]],
             "實驗室16級需等待", 0.99),
        ])

        self.assertFalse(任务._研究面板已确认())

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

    def test_研究按钮点击后未确认面板会取消实验室选中(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(return_value=True),
            脚本延时=Mock(),
        )
        任务.研究入口偏移候选 = ((0, 13),)
        任务.最大入口等待秒 = 0.01
        任务._查找实验室标签候选 = Mock(return_value=[(455, 352, 0.99, "研究")])
        任务._选中后是否为实验室 = Mock(return_value=True)
        任务._查找选中实验室研究按钮 = Mock(return_value=(490, 470))
        任务._获取全屏画面 = Mock(return_value=None)
        任务._研究面板已确认 = Mock(return_value=False)
        任务._安全取消建筑选中 = Mock(wraps=任务._安全取消建筑选中)

        self.assertFalse(任务._打开研究入口())
        任务._安全取消建筑选中.assert_called_once_with()
        任务.上下文.点击.assert_any_call(100, 300, 是否精确点击=True)
        self.assertTrue(any(
            "已取消实验室选中" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_研究按钮输入被拒绝也会取消实验室选中(self):
        任务 = 打开研究面板任务.__new__(打开研究面板任务)
        任务.上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(side_effect=[True, False, True]),
            脚本延时=Mock(),
        )
        任务.研究入口偏移候选 = ((0, 13),)
        任务.最大入口等待秒 = 0.01
        任务._查找实验室标签候选 = Mock(return_value=[(455, 352, 0.99, "研究")])
        任务._选中后是否为实验室 = Mock(return_value=True)
        任务._查找选中实验室研究按钮 = Mock(return_value=(490, 470))
        任务._获取全屏画面 = Mock(return_value=None)

        self.assertFalse(任务._打开研究入口())
        self.assertEqual(
            任务.上下文.点击.call_args_list,
            [
                unittest.mock.call(455, 365, 是否精确点击=True),
                unittest.mock.call(490, 470, 是否精确点击=True),
                unittest.mock.call(100, 300, 是否精确点击=True),
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
