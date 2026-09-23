import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import cv2

from 任务流程.基础任务框架 import 任务上下文
from 任务流程.建筑升级.升级英雄 import 升级英雄任务
from 任务流程.建筑升级.升级普通建筑 import 升级普通建筑任务
from 任务流程.兵种或法术升级.完成兵种或法术升级 import 完成兵种或法术升级任务
from 任务流程.战宠升级.完成宠物升级 import 完成宠物升级任务
from 任务流程.战宠升级.寻找战宠小屋 import 寻找战宠小屋任务
from 任务流程.战宠升级.打开要升级的宠物 import 打开要升级的宠物任务


class 升级面板关闭安全测试(unittest.TestCase):
    def test_实机建筑详情面板只定位右上关闭而不定位立即完成(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        # 右上角红色 X 的实机缩小候选；底部文字由 OCR 结构授权。
        cv2.rectangle(图像, (765, 28), (775, 38), (0, 0, 220), -1)
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.获取OCR引擎 = Mock(return_value=Mock(return_value=(
            [
                ([[410, 588], [451, 588], [451, 614], [410, 614]], "取消", 0.99),
                ([[538, 588], [608, 588], [608, 611], [538, 611]], "立即完成", 0.99),
                ([[660, 590], [748, 590], [748, 608], [660, 608]], "加速建筑工人", 0.99),
            ],
            None,
        )))

        self.assertEqual(
            上下文._检测主世界建筑详情关闭点(图像),
            (770, 33),
        )

    def test_没有建筑详情文字时不定位右上红色控件(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(图像, (765, 28), (775, 38), (0, 0, 220), -1)
        上下文 = 任务上下文.__new__(任务上下文)
        上下文.获取OCR引擎 = Mock(return_value=Mock(return_value=([], None)))

        self.assertIsNone(上下文._检测主世界建筑详情关闭点(图像))
    def test_OCR识别升级中标题正在将英雄升至等级(self):
        OCR结果 = [
            (None, "正在将野璧人之王升至84级", 0.91),
            (None, "立即完成", 0.99),
            (None, "剩余时间：4天22小时", 0.90),
        ]

        self.assertTrue(任务上下文._OCR确认升级详情页(OCR结果))

    def test_OCR没有升级标题不授权关闭(self):
        OCR结果 = [
            (None, "英雄", 0.99),
            (None, "立即完成", 0.99),
            (None, "商店", 0.99),
        ]

        self.assertFalse(任务上下文._OCR确认升级详情页(OCR结果))

    def test_英雄面板关闭授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 升级英雄任务.__new__(升级英雄任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务.关闭英雄升级页面()

        返回.assert_called_once_with(
            "关闭英雄升级页面", 已确认可关闭面板=True
        )

    def test_英雄面板优先点主世界空白区域不发送返回键(self):
        点击 = Mock(return_value=True)
        返回 = Mock(return_value=True)
        任务 = 升级英雄任务.__new__(升级英雄任务)
        任务.上下文 = SimpleNamespace(点击=点击, 安全返回键=返回)

        self.assertTrue(任务.关闭英雄升级页面())
        点击.assert_called_once_with(700, 300, 延时=700, 是否精确点击=True)
        返回.assert_not_called()

    def test_研究面板关闭两次都授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 完成兵种或法术升级任务.__new__(完成兵种或法术升级任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务._关闭升级面板()

        self.assertEqual(返回.call_count, 2)
        for 调用, 说明 in zip(
            返回.call_args_list, ("关闭升级详情", "关闭研究面板")
        ):
            self.assertEqual(
                调用,
                unittest.mock.call(说明, 已确认可关闭面板=True),
            )

    def test_研究面板第二次关闭失败会向上返回失败(self):
        返回 = Mock(side_effect=[True, False])
        任务 = 完成兵种或法术升级任务.__new__(完成兵种或法术升级任务)
        任务.上下文 = SimpleNamespace(
            安全返回键=返回,
            置脚本状态=Mock(),
        )

        self.assertFalse(任务._关闭升级面板())

    def test_战宠升级面板关闭授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 完成宠物升级任务.__new__(完成宠物升级任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        self.assertTrue(任务._安全关闭面板("关闭战宠升级页面", "关闭战宠小屋"))
        self.assertEqual(返回.call_count, 2)
        self.assertTrue(all(
            调用.kwargs.get("已确认可关闭面板") is True
            for 调用 in 返回.call_args_list
        ))

    def test_战宠小屋关闭授权已确认面板(self):
        返回 = Mock(return_value=True)
        任务 = 打开要升级的宠物任务.__new__(打开要升级的宠物任务)
        任务.上下文 = SimpleNamespace(安全返回键=返回)

        任务.关闭战宠小屋页面()

        返回.assert_called_once_with(
            "关闭战宠小屋页面", 已确认可关闭面板=True
        )

    def test_缺少战宠关闭器时禁止原始ESC(self):
        键盘 = SimpleNamespace(按字符按压=Mock())
        状态 = Mock()
        任务 = 打开要升级的宠物任务.__new__(打开要升级的宠物任务)
        任务.上下文 = SimpleNamespace(键盘=键盘, 置脚本状态=状态)

        self.assertFalse(任务.关闭战宠小屋页面())
        键盘.按字符按压.assert_not_called()

    def test_缺少研究关闭器时禁止原始ESC(self):
        键盘 = SimpleNamespace(按字符按压=Mock())
        任务 = 完成兵种或法术升级任务.__new__(完成兵种或法术升级任务)
        任务.上下文 = SimpleNamespace(
            键盘=键盘,
            置脚本状态=Mock(),
        )

        任务._关闭升级面板()
        键盘.按字符按压.assert_not_called()

    def test_缺少英雄和建筑关闭器时禁止原始ESC(self):
        for 任务类 in (升级英雄任务, 升级普通建筑任务):
            键盘 = SimpleNamespace(按字符按压=Mock())
            任务 = 任务类.__new__(任务类)
            任务.上下文 = SimpleNamespace(
                键盘=键盘,
                置脚本状态=Mock(),
            )
            self.assertFalse(任务.关闭英雄升级页面() if 任务类 is 升级英雄任务 else 任务.关闭建筑升级页面())
            键盘.按字符按压.assert_not_called()

    def test_战宠小屋回到主世界后清理底层选中卡片(self):
        返回 = Mock(return_value=True)
        点击 = Mock(return_value=True)
        识别 = Mock(return_value=SimpleNamespace(页面="主世界主页", 世界="主世界"))
        任务 = 打开要升级的宠物任务.__new__(打开要升级的宠物任务)
        任务.上下文 = SimpleNamespace(
            安全返回键=返回,
            识别点击画面=识别,
            点击=点击,
            置脚本状态=Mock(),
        )

        self.assertTrue(任务.关闭战宠小屋页面())
        点击.assert_called_once_with(700, 300, 延时=700, 是否精确点击=True)

    def test_战宠小屋底层卡片清理被拒绝时停止后续操作(self):
        返回 = Mock(return_value=True)
        点击 = Mock(return_value=False)
        识别 = Mock(return_value=SimpleNamespace(页面="主世界主页", 世界="主世界"))
        任务 = 打开要升级的宠物任务.__new__(打开要升级的宠物任务)
        任务.上下文 = SimpleNamespace(
            安全返回键=返回,
            识别点击画面=识别,
            点击=点击,
            置脚本状态=Mock(),
            页面恢复失败=False,
        )

        self.assertFalse(任务.关闭战宠小屋页面())
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_战宠候选安全取消被拒绝时标记页面失败(self):
        任务 = 寻找战宠小屋任务.__new__(寻找战宠小屋任务)
        任务.上下文 = SimpleNamespace(
            识别点击画面=Mock(return_value=SimpleNamespace(页面="主世界主页")),
            点击=Mock(return_value=False),
            置脚本状态=Mock(),
            页面恢复失败=False,
        )

        self.assertFalse(任务._安全取消误候选面板())
        self.assertTrue(任务.上下文.页面恢复失败)

    def test_战宠小屋按钮使用面板区域和自适应阈值(self):
        任务 = 寻找战宠小屋任务.__new__(寻找战宠小屋任务)
        上下文 = SimpleNamespace(
            脚本延时=Mock(),
            点击=Mock(),
            置脚本状态=Mock(),
        )
        任务.上下文 = 上下文
        任务.是否出现图片 = Mock(return_value=(True, (489, 450)))

        self.assertTrue(任务._点击打开按钮())
        任务.是否出现图片.assert_called_once_with(
            "打开战宠小屋按钮.bmp|打开战宠小屋按钮1.bmp",
            区域=(400, 360, 580, 560),
            相似度阈值=0.55,
        )
        上下文.点击.assert_called_once_with(
            489, 450, 延时=350, 是否精确点击=True
        )

    def test_战宠小屋按钮输入被拒绝时停止并标记页面失败(self):
        任务 = 寻找战宠小屋任务.__new__(寻找战宠小屋任务)
        上下文 = SimpleNamespace(
            脚本延时=Mock(),
            点击=Mock(return_value=False),
            置脚本状态=Mock(),
            页面恢复失败=False,
        )
        任务.上下文 = 上下文
        任务.是否出现图片 = Mock(return_value=(True, (489, 450)))

        self.assertFalse(任务._点击打开按钮())
        self.assertTrue(上下文.页面恢复失败)

    def test_战宠小屋使用放大地图切片并还原参考坐标(self):
        任务 = 寻找战宠小屋任务.__new__(寻找战宠小屋任务)
        调用次数 = 0

        def 检测(图像):
            nonlocal 调用次数
            调用次数 += 1
            if 调用次数 == 1:
                return [{
                    "裁剪坐标": [300, 300, 360, 360],
                    "类别名称": "战宠小屋",
                    "置信度": 0.80,
                }]
            return []

        任务.战宠小屋检测器 = SimpleNamespace(检测=检测)
        任务.上下文 = SimpleNamespace(
            是否内存异常=lambda 异常: False,
            触发内存保护=Mock(),
            置脚本状态=Mock(),
        )

        结果 = 任务._检测放大地图区域(
            np.zeros((600, 800, 3), dtype=np.uint8)
        )

        self.assertEqual(调用次数, 4)
        self.assertEqual(结果[0]["裁剪坐标"], [320, 280, 360, 320])
        self.assertEqual(结果[0]["置信度"], 0.80)

    def test_战宠候选未打开小屋时安全清理误选中卡片(self):
        点击 = Mock(return_value=True)
        任务 = 寻找战宠小屋任务.__new__(寻找战宠小屋任务)
        任务.上下文 = SimpleNamespace(
            识别点击画面=Mock(return_value=SimpleNamespace(页面="主世界主页")),
            点击=点击,
            置脚本状态=Mock(),
        )

        self.assertTrue(任务._安全取消误候选面板())
        点击.assert_called_once_with(700, 300, 延时=500, 是否精确点击=True)


if __name__ == "__main__":
    unittest.main()
