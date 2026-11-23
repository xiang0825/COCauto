import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from 任务流程.基础任务框架 import 任务上下文
from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
from 任务流程.主世界打鱼.搜索页面识别 import 搜索页面识别器
from 任务流程.主世界打鱼 import 主世界打鱼任务


def 搜索画面():
    画面 = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.rectangle(画面, (665, 390), (792, 464), (0, 180, 245), -1)
    return 画面


class 搜索按钮护栏测试(unittest.TestCase):
    def test_搜索按钮失效后只读等待三帧主世界(self):
        主世界 = SimpleNamespace(页面="主世界主页", 世界="主世界", 可信度=0.78)
        上下文 = SimpleNamespace(
            停止事件=Event(),
            识别点击画面=Mock(return_value=主世界),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        with patch("任务流程.主世界打鱼.搜索敌人.time.monotonic", return_value=0.0):
            self.assertTrue(搜索目标敌人任务.等待搜索失效后自然回营(上下文))
        self.assertEqual(上下文.识别点击画面.call_count, 3)
        self.assertEqual(上下文.脚本延时.call_count, 2)

    def test_搜索失效时非主世界不得继续任务链(self):
        上下文 = SimpleNamespace(
            停止事件=Event(),
            识别点击画面=Mock(return_value=SimpleNamespace(
                页面="战斗中", 世界=None, 可信度=0.96
            )),
            置脚本状态=Mock(),
        )
        上下文.脚本延时 = Mock(side_effect=lambda _毫秒: 上下文.停止事件.set())
        with patch("任务流程.主世界打鱼.搜索敌人.time.monotonic", return_value=0.0):
            self.assertFalse(搜索目标敌人任务.等待搜索失效后自然回营(上下文))

    def test_自然回营后不再执行进攻和结算(self):
        上下文 = SimpleNamespace(置脚本状态=Mock())
        任务 = 主世界打鱼任务.__new__(主世界打鱼任务)
        任务.上下文 = 上下文
        with patch("任务流程.主世界打鱼.打开进攻页面任务") as 入口, \
             patch("任务流程.主世界打鱼.搜索目标敌人任务") as 搜索, \
             patch("任务流程.主世界打鱼.进攻任务") as 进攻, \
             patch("任务流程.主世界打鱼.等待战斗结束并回营任务") as 回营:
            入口.return_value.执行.return_value = True
            def 搜索后回营():
                上下文._搜索阶段自然回营 = True
                return True
            搜索.return_value.执行.side_effect = 搜索后回营
            self.assertTrue(任务.执行())
            进攻.return_value.执行.assert_not_called()
            回营.return_value.执行.assert_not_called()

    def test_偏左低分绿色地图只可暂作入口候选不可点击(self):
        画面 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.fillPoly(画面, [np.array([
            (585, 380), (693, 380), (693, 390),
            (615, 390), (615, 431), (585, 431),
        ])], (40, 190, 40))
        命中, 坐标, 依据, 分数 = 搜索页面识别器.查找下一个按钮(画面)
        self.assertTrue(命中)
        self.assertLess(坐标[0], 搜索页面识别器.点击安全最左x)
        self.assertFalse(搜索页面识别器.按钮证据可信(依据, 分数))

    def test_实机中等分橙色及文字模板可通过两帧复核(self):
        for 依据, 分数 in (("橙黄色按钮", 0.80), ("模板下一个.bmp", 0.64)):
            with self.subTest(依据=依据):
                画面 = 搜索画面()
                上下文 = SimpleNamespace(
                    op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=画面)),
                    _获取点击页面识别器=lambda: SimpleNamespace(
                        识别=lambda *_参数, **_关键字: SimpleNamespace(页面="战斗结算")
                    ),
                    获取模板识别器=lambda: None,
                    点击已确认安全按钮=Mock(return_value=True),
                    脚本延时=Mock(),
                    置脚本状态=Mock(),
                )
                with patch.object(
                    搜索页面识别器, "查找下一个按钮",
                    return_value=(True, (728, 428), 依据, 分数),
                ):
                    self.assertTrue(任务上下文.点击已确认搜索按钮(上下文, 728, 428))
                上下文.点击已确认安全按钮.assert_called_once()

    def test_入场弱候选后重试到可靠按钮(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.模板识别 = None
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=搜索画面())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            点击已确认搜索按钮=Mock(return_value=True),
        )
        with patch.object(
            搜索页面识别器, "查找下一个按钮",
            side_effect=[
                (True, (639, 406), "绿色按钮", 0.33),
                (True, (728, 428), "橙黄色按钮", 0.80),
            ],
        ):
            self.assertTrue(任务.点击下一个按钮(上下文))
        上下文.点击已确认搜索按钮.assert_called_once_with(728, 428)
        上下文.脚本延时.assert_called_once_with(600)

    def test_弱绿色候选持续存在也不盲点(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.模板识别 = None
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=搜索画面())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            点击已确认搜索按钮=Mock(return_value=True),
        )
        with patch.object(
            搜索页面识别器, "查找下一个按钮",
            return_value=(True, (639, 406), "绿色按钮", 0.33),
        ):
            self.assertFalse(任务.点击下一个按钮(上下文))
        上下文.点击已确认搜索按钮.assert_not_called()
        self.assertEqual(上下文.op.获取屏幕图像cv.call_count, 8)

    def test_等待搜索页不会把弱绿色候选报告为已确认(self):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.模板识别 = None
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=搜索画面())),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        with patch(
            "任务流程.主世界打鱼.搜索敌人.time.time",
            side_effect=(0.0, 0.0, 31.0),
        ), patch.object(
            搜索页面识别器,
            "查找下一个按钮",
            return_value=(True, (639, 406), "绿色按钮", 0.35),
        ):
            self.assertFalse(任务.等待下一个按钮出现(上下文))

        self.assertEqual(上下文.op.获取屏幕图像cv.call_count, 1)
        self.assertTrue(any(
            "等待下一个按钮超时" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_弱绿色候选不遮蔽可靠文字模板(self):
        with patch.object(
            搜索页面识别器, "_按颜色查找",
            return_value=(True, (639, 406), "绿色按钮", 0.33),
        ), patch.object(
            搜索页面识别器, "_按模板查找",
            return_value=(True, (731, 414), "模板下一个.bmp", 0.64),
        ):
            self.assertEqual(
                搜索页面识别器.查找下一个按钮(搜索画面()),
                (True, (731, 414), "模板下一个.bmp", 0.64),
            )

    def test_安全区外的橙色误候选不遮蔽下一步模板(self):
        with patch.object(
            搜索页面识别器, "_按颜色查找",
            return_value=(True, (656, 417), "橙黄色按钮", 0.70),
        ), patch.object(
            搜索页面识别器, "_按模板查找",
            return_value=(True, (731, 414), "模板下一个.bmp", 0.64),
        ):
            self.assertEqual(
                搜索页面识别器.查找下一个按钮(搜索画面(), object()),
                (True, (731, 414), "模板下一个.bmp", 0.64),
            )

    def test_两帧搜索按钮可覆盖过渡帧结算误报(self):
        画面 = 搜索画面()
        命中, 坐标, _, 分数 = 搜索页面识别器.查找下一个按钮(画面)
        self.assertTrue(命中)
        self.assertGreaterEqual(分数, 0.90)
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(side_effect=[画面, 画面])),
            _获取点击页面识别器=lambda: SimpleNamespace(
                识别=lambda *_参数, **_关键字: SimpleNamespace(页面="战斗结算")
            ),
            获取模板识别器=lambda: None,
            点击已确认安全按钮=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            _最近结算视觉时间=123.0,
            _战斗结束已确认=True,
            _最近点击页面结果=SimpleNamespace(页面="战斗结算"),
            _点击识别截图=画面,
        )

        self.assertTrue(任务上下文.点击已确认搜索按钮(上下文, *坐标))
        self.assertEqual(上下文.op.获取屏幕图像cv.call_count, 2)
        上下文.点击已确认安全按钮.assert_called_once_with(
            坐标[0], 坐标[1], 延时=500
        )
        self.assertEqual(上下文._最近结算视觉时间, 0.0)
        self.assertFalse(上下文._战斗结束已确认)

    def test_第二帧为断线弹窗时绝不点击(self):
        画面 = 搜索画面()
        坐标 = 搜索页面识别器.查找下一个按钮(画面)[1]
        页面 = iter(("战斗结算", "断线弹窗"))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(side_effect=[画面, 画面])),
            _获取点击页面识别器=lambda: SimpleNamespace(
                识别=lambda *_参数, **_关键字: SimpleNamespace(页面=next(页面))
            ),
            获取模板识别器=lambda: None,
            点击已确认安全按钮=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            _最近结算视觉时间=123.0,
        )

        self.assertFalse(任务上下文.点击已确认搜索按钮(上下文, *坐标))
        上下文.点击已确认安全按钮.assert_not_called()
        self.assertEqual(上下文._最近结算视觉时间, 123.0)

    def test_搜索按钮上覆盖真实卡片弹窗时绝不点击(self):
        画面 = 搜索画面()
        坐标 = 搜索页面识别器.查找下一个按钮(画面)[1]
        上下文 = SimpleNamespace(
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=画面)),
            _获取点击页面识别器=lambda: SimpleNamespace(
                识别=lambda *_参数, **_关键字: SimpleNamespace(页面="选择卡片弹窗")
            ),
            获取模板识别器=lambda: None,
            点击已确认安全按钮=Mock(return_value=True),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )

        self.assertFalse(任务上下文.点击已确认搜索按钮(上下文, *坐标))
        上下文.点击已确认安全按钮.assert_not_called()


class 高等级阵营筛选测试(unittest.TestCase):
    def _创建搜索任务(self, 玩法):
        任务 = 搜索目标敌人任务.__new__(搜索目标敌人任务)
        任务.上下文 = SimpleNamespace(
            设置=SimpleNamespace(
                是否采集进攻界面图像=False,
                是否自动配兵=True,
                自动配兵玩法=玩法,
            ),
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))),
            数据库=SimpleNamespace(
                获取机器人设置=lambda _标志: SimpleNamespace(
                    欲进攻的最小资源=100,
                    欲进攻资源建筑靠近地图边缘最小比例=0.5,
                )
            ),
            机器人标志="测试机器人",
            置脚本状态=Mock(),
        )
        任务.等待下一个按钮出现 = Mock(return_value=True)
        任务.识别当前资源 = Mock(return_value={
            "金币": 500_000,
            "圣水": 500_000,
            "黑油": 5_000,
            "战利品评分": 1_000_000,
        })
        任务.检测器 = SimpleNamespace(检测=Mock(return_value=[]))
        任务.计算资源易窃取评分 = Mock(return_value=(8.0, {
            "储存建筑数": 2,
            "高价值资源可达比例": 80.0,
        }))
        任务.打印状态信息 = Mock()
        任务.获取自适应资源筛选门槛 = Mock(return_value=(5.0, None, ""))
        任务.是否有足够资源建筑靠近边缘 = Mock(return_value=True)
        任务.已出现图片 = Mock(return_value=(True, (0, 0)))
        任务.点击下一个按钮 = Mock(return_value=True)
        return 任务

    def test_稳健三星遇到识别出的17本会跳过并继续搜索(self):
        任务 = self._创建搜索任务("稳健三星")

        结果 = 任务.执行单次搜索(任务.上下文, 搜索次数=1, 最小资源=100)

        self.assertFalse(结果)
        任务.点击下一个按钮.assert_called_once_with(任务.上下文)
        self.assertTrue(any(
            "17本" in 调用.args[0] and "跳过" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))

    def test_资源优先遇到高资源17本仍保留资源模式行为(self):
        任务 = self._创建搜索任务("资源优先")

        结果 = 任务.执行单次搜索(任务.上下文, 搜索次数=1, 最小资源=100)

        self.assertTrue(结果)
        任务.点击下一个按钮.assert_not_called()
        模板列表 = 任务.已出现图片.call_args.args[0]
        self.assertIn("避免_17本4.bmp", 模板列表)
        self.assertNotIn("避免_17本4bmp", 模板列表)

    def test_自适应筛选使用保守折算后的高价值可达比例(self):
        任务 = self._创建搜索任务("资源优先")
        任务.计算资源易窃取评分 = Mock(return_value=(7.4, {
            "储存建筑数": 6,
            "高价值资源可达比例": 66.8,
            "高价值资源可达折算": 58.0,
        }))
        任务.获取自适应资源筛选门槛 = Mock(return_value=(6.5, 0.70, "；测试门槛"))

        结果 = 任务.执行单次搜索(任务.上下文, 搜索次数=1, 最小资源=100)

        self.assertFalse(结果)
        任务.点击下一个按钮.assert_called_once_with(任务.上下文)
        任务.已出现图片.assert_not_called()

    def test_自适应折算可达率达到七成时允许继续评估资源门槛(self):
        任务 = self._创建搜索任务("资源优先")
        任务.计算资源易窃取评分 = Mock(return_value=(7.4, {
            "储存建筑数": 6,
            "高价值资源可达比例": 78.0,
            "高价值资源可达折算": 70.0,
        }))
        任务.获取自适应资源筛选门槛 = Mock(return_value=(6.5, 0.70, "；测试门槛"))

        结果 = 任务.执行单次搜索(任务.上下文, 搜索次数=1, 最小资源=100)

        self.assertTrue(结果)
        任务.点击下一个按钮.assert_not_called()

    def test_低表现期间黑油达标也不放宽七成可达率门槛(self):
        任务 = self._创建搜索任务("资源优先")
        任务.上下文.数据库.获取机器人设置 = Mock(return_value=SimpleNamespace(
            战利品优先级="黑水",
            欲进攻的最小资源=100,
            欲进攻资源建筑靠近地图边缘最小比例=0.5,
        ))
        任务.识别当前资源 = Mock(return_value={
            "金币": 500_000,
            "圣水": 500_000,
            "黑油": 16_834,
            "战利品评分": 1_000_000,
        })
        任务.计算资源易窃取评分 = Mock(return_value=(7.4, {
            "储存建筑数": 6,
            "高价值资源可达比例": 73.0,
            "高价值资源可达折算": 65.2,
        }))
        任务.获取自适应资源筛选门槛 = Mock(
            return_value=(6.5, 0.70, "；连续低表现筛选")
        )

        结果 = 任务.执行单次搜索(任务.上下文, 搜索次数=1, 最小资源=100)

        self.assertFalse(结果)
        任务.点击下一个按钮.assert_called_once_with(任务.上下文)
        self.assertTrue(any(
            "可达折算[65%]低于70%" in 调用.args[0]
            for 调用 in 任务.上下文.置脚本状态.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()
