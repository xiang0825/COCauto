import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.升级城墙 import 城墙升级任务


class 刷墙识别测试(unittest.TestCase):
    def setUp(self):
        self.任务 = 城墙升级任务.__new__(城墙升级任务)

    def test_OCR坐标使用真实包围框而不是固定右边界(self):
        坐标 = self.任务.解析OCR坐标(
            [[20, 30], [84, 30], [84, 58], [20, 58]]
        )
        self.assertEqual(坐标, (20, 30, 84, 58))

    def test_墙体关键词兼容中英文(self):
        for 文本 in ("城墙", "城牆", "围墙", "围牆", "Wall", "WALLS"):
            with self.subTest(文本=文本):
                self.assertTrue(self.任务.文本是否城墙(文本))
        self.assertFalse(self.任务.文本是否城墙("防御塔"))

    def test_候选墙段点位限制在地图搜索区域(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        图像[:] = (50, 155, 45)
        # 模拟一条等距视角下的金色墙线和相邻灰色墙线。
        cv2.line(图像, (110, 180), (390, 360), (0, 190, 255), 8)
        cv2.line(图像, (420, 360), (650, 220), (80, 80, 95), 8)

        候选点 = self.任务.生成城墙候选点(图像)

        self.assertTrue(候选点)
        左, 上, 右, 下 = self.任务.墙体搜索区域
        self.assertTrue(all(左 <= x < 右 and 上 <= y < 下 for x, y in 候选点))

    def test_候选墙段按空间网格覆盖避免前十二点挤在同一处(self):
        图像 = np.zeros((600, 800, 3), dtype=np.uint8)
        图像[:] = (50, 155, 45)
        # 用分散的斜墙线模拟镜头拉远后村庄四个区域的墙段；
        # 结果不应只保留分数最高的单一区域。
        for 起点, 终点 in [
            ((100, 100), (260, 200)),
            ((300, 220), (460, 320)),
            ((500, 350), (680, 480)),
            ((150, 450), (350, 550)),
            ((500, 100), (700, 200)),
        ]:
            cv2.line(图像, 起点, 终点, (0, 190, 255), 8)

        候选点 = self.任务.生成城墙候选点(图像)
        网格 = {
            (min(3, max(0, x * 4 // 800)), min(2, max(0, y * 3 // 600)))
            for x, y in 候选点
        }
        self.assertGreaterEqual(len(网格), 4)

    def test_墙体面板快速筛选只关注底部变化(self):
        原图 = np.zeros((600, 800, 3), dtype=np.uint8)
        self.assertFalse(self.任务._选择面板明显变化(原图, 原图.copy()))

        面板图 = 原图.copy()
        面板图[410:590, 100:700] = 180
        self.assertTrue(self.任务._选择面板明显变化(原图, 面板图))

        顶部变化图 = 原图.copy()
        顶部变化图[0:300, :] = 255
        self.assertFalse(self.任务._选择面板明显变化(原图, 顶部变化图))

    def test_断线弹窗主体和文字可被兜底识别且不会误点回营(self):
        画面 = np.full((600, 800, 3), (10, 18, 22), dtype=np.uint8)
        # 模拟测试服中央深色弹窗；底部额外放置战斗结算页绿色“回营”按钮。
        cv2.rectangle(画面, (164, 180), (635, 423), (32, 26, 29), -1)
        cv2.rectangle(画面, (334, 483), (467, 538), (0, 180, 0), -1)
        cv2.rectangle(画面, (201, 218), (304, 244), (220, 220, 220), -1)
        cv2.rectangle(画面, (201, 270), (580, 294), (220, 220, 220), -1)
        cv2.rectangle(画面, (201, 306), (232, 328), (220, 220, 220), -1)
        cv2.rectangle(画面, (201, 368), (325, 389), (220, 220, 220), -1)
        是否断线, 坐标 = self.任务._检测断线弹窗(画面)
        self.assertTrue(是否断线)
        self.assertGreaterEqual(坐标[0], 201)
        self.assertLessEqual(坐标[0], 325)
        self.assertGreaterEqual(坐标[1], 368)
        self.assertLessEqual(坐标[1], 389)

        仅结算页 = np.full((600, 800, 3), (10, 18, 22), dtype=np.uint8)
        cv2.rectangle(仅结算页, (334, 483), (467, 538), (0, 180, 0), -1)
        无弹窗, _ = self.任务._检测断线弹窗(仅结算页)
        self.assertFalse(无弹窗)

    def test_点击候选点后必须先确认城墙才执行升级(self):
        self.任务.执行升级 = Mock(return_value=True)
        上下文 = SimpleNamespace(置脚本状态=Mock())
        OCR结果 = [([[180, 450], [230, 450], [230, 470], [180, 470]], "城墙", 0.98)]

        self.assertTrue(self.任务.处理已选中的城墙(上下文, OCR结果, (205, 460)))
        参数 = self.任务.执行升级.call_args
        self.assertEqual(参数.args[:5], (上下文, 195, 450, 215, 470))
        self.assertEqual(参数.kwargs, {"已选中": True, "OCR结果": OCR结果})

    def test_非城墙候选不会误触发升级(self):
        self.任务.执行升级 = Mock(return_value=True)
        上下文 = SimpleNamespace(置脚本状态=Mock())
        OCR结果 = [([[180, 450], [230, 450], [230, 470], [180, 470]], "加农炮", 0.98)]

        self.assertFalse(self.任务.处理已选中的城墙(上下文, OCR结果, (205, 460)))
        self.任务.执行升级.assert_not_called()

    def test_非城墙候选会安全取消选中面板而不是发送返回键(self):
        上下文 = SimpleNamespace(
            点击=Mock(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )

        self.assertTrue(self.任务._安全关闭非城墙选中面板(上下文))
        上下文.点击.assert_called_once_with(90, 80, 延时=220, 是否精确点击=True)
        self.assertTrue(any(
            "安全取消选中面板" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_安全取消点击被输入层拒绝时停止扫描(self):
        上下文 = SimpleNamespace(
            点击=Mock(return_value=False),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            页面恢复失败=False,
        )

        self.assertFalse(self.任务._安全关闭非城墙选中面板(上下文))
        self.assertTrue(上下文.页面恢复失败)
        self.assertFalse(any(
            "安全取消选中面板" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_断线重载按钮被输入层拒绝时停止扫描(self):
        上下文 = SimpleNamespace(
            点击已确认安全按钮=Mock(return_value=False),
            脚本延时=Mock(),
            置脚本状态=Mock(),
            页面恢复失败=False,
        )

        self.assertFalse(self.任务._安全重载断线弹窗(上下文, 400, 380))
        上下文.点击已确认安全按钮.assert_called_once_with(400, 380, 延时=180)
        上下文.脚本延时.assert_not_called()
        self.assertTrue(上下文.页面恢复失败)
        self.assertTrue(any(
            "输入被拒绝" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_进入城墙画面失败时不继续截图或资源操作(self):
        上下文 = SimpleNamespace(
            页面恢复失败=False,
            置脚本状态=Mock(),
        )
        self.任务.上下文 = 上下文
        self.任务.进入城墙界面 = Mock(return_value=False)

        self.assertFalse(self.任务.刷一次墙())
        self.assertTrue(上下文.页面恢复失败)

    def test_刷墙任务读取上下文停止事件(self):
        上下文 = SimpleNamespace(
            停止事件=threading.Event(),
            置脚本状态=Mock(),
        )
        上下文.停止事件.set()
        self.任务.上下文 = 上下文
        self.任务.检查功能开启 = Mock(return_value=True)
        self.任务.刷一次墙 = Mock()

        self.assertTrue(self.任务.执行())
        self.任务.刷一次墙.assert_not_called()

    def test_能从墙体面板读取两种资源费用(self):
        OCR结果 = [
            ([[411, 425], [471, 425], [471, 441], [411, 441]], "So00000", 0.80),
            ([[500, 425], [559, 425], [559, 441], [500, 441]], "5000000", 0.80),
        ]
        self.assertEqual(self.任务.解析城墙升级费用(OCR结果), (5000000, 5000000))
        变形OCR结果 = [
            ([[411, 425], [471, 425], [471, 441], [411, 441]], "000000S", 0.80),
        ]
        self.assertEqual(self.任务.解析城墙升级费用(变形OCR结果), (5000000, None))

    def test_刷墙升级始终使用主世界资源模板(self):
        金币模板, 圣水模板 = self.任务.获取城墙升级资源模板()

        self.assertIn("升级建筑的金币小图标1.bmp", 金币模板)
        self.assertIn("升级建筑的圣水小图标1.bmp", 圣水模板)
        self.assertNotIn("夜.bmp", 金币模板)
        self.assertNotIn("夜.bmp", 圣水模板)

    def test_实机放大升级卡片使用OCR回退定位资源按钮(self):
        """小图标模板失配时，仍应只返回两张资源升级卡片的安全点。"""
        self.任务.模板识别 = Mock()
        self.任务.模板识别.执行匹配 = Mock(return_value=(False, (0, 0), 0.0))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))
            ),
            置脚本状态=Mock(),
        )
        OCR结果 = [
            ([[413, 425], [471, 425], [471, 441], [413, 441]], "5000000", 0.95),
            ([[501, 425], [558, 425], [558, 441], [501, 441]], "5O00000", 0.95),
            ([[433, 490], [458, 490], [458, 511], [433, 511]], "升极", 0.95),
            ([[523, 494], [545, 494], [545, 506], [523, 506]], "升级", 0.95),
        ]

        结果 = self.任务.识别城墙升级资源按钮(上下文, OCR结果=OCR结果)

        self.assertTrue(结果["金币"])
        self.assertTrue(结果["圣水"])
        self.assertEqual(结果["金币点击点"], (445, 500))
        self.assertEqual(结果["圣水点击点"], (534, 500))
        self.assertTrue(any("OCR兼容回退" in 调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list))

    def test_实机费用框横跨旧分界线时仍能定位两张升级卡片(self):
        """当前 MuMu 墙体面板的左侧费用框 x=457..515 会跨过旧的485线。"""
        self.任务.模板识别 = Mock()
        self.任务.模板识别.执行匹配 = Mock(return_value=(False, (0, 0), 0.0))
        上下文 = SimpleNamespace(
            op=SimpleNamespace(
                获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))
            ),
            置脚本状态=Mock(),
        )
        OCR结果 = [
            ([[457, 425], [515, 425], [515, 441], [457, 441]], "5000000", 0.95),
            ([[545, 425], [602, 425], [602, 441], [545, 441]], "5000000", 0.95),
            ([[477, 490], [503, 490], [503, 511], [477, 511]], "升级", 0.95),
            ([[564, 490], [593, 490], [593, 512], [564, 512]], "升级", 0.95),
        ]

        结果 = self.任务.识别城墙升级资源按钮(上下文, OCR结果=OCR结果)

        self.assertTrue(结果["金币"])
        self.assertTrue(结果["圣水"])
        self.assertEqual(结果["金币点击点"], (490, 500))
        self.assertEqual(结果["圣水点击点"], (578, 501))

    def test_确认框中文OCR近形字时按右下资源费用定位确认(self):
        OCR结果 = [
            ([[336, 40], [458, 40], [458, 58], [336, 58]], "将城瘤开至17级？", 0.80),
            ([[508, 523], [590, 523], [590, 544], [508, 544]], "5000 000", 0.91),
        ]
        self.assertIn("将城墙升至", self.任务._规范城墙升级确认标题("将城瘤开至17级？"))
        self.assertEqual(self.任务.定位城墙升级确认资源按钮(OCR结果), (549, 505))

    def test_测试服漏识别墙字和繁体确认仍识别确认框(self):
        标题 = self.任务._规范城墙升级确认标题("將城升至17级？")
        self.assertIn("将城墙升至", 标题)
        # “確認”经常只剩单字“確”，应由费用回退定位按钮，不能走未知成功分支。
        OCR结果 = [
            ([[336, 40], [458, 40], [458, 58], [336, 58]], "將城升至17级？", 0.87),
            ([[570, 465], [598, 465], [598, 483], [570, 483]], "確", 0.95),
            ([[508, 523], [590, 523], [590, 544], [508, 544]], "5000 000", 0.91),
        ]
        self.assertEqual(self.任务.定位城墙升级确认资源按钮(OCR结果), (549, 505))

    def test_确认证据不足绝不报告城墙已提交(self):
        上下文 = SimpleNamespace(置脚本状态=Mock())
        self.任务.执行OCR识别 = Mock(return_value=[
            ([[100, 100], [180, 100], [180, 120], [100, 120]], "普通页面", 0.95),
        ])
        self.assertFalse(self.任务.确认城墙升级提交(上下文))
        self.assertTrue(any(
            "证据不足" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))

    def test_确认框定位不到标题时不应把资源栏当确认按钮(self):
        OCR结果 = [
            ([[700, 80], [760, 80], [760, 100], [700, 100]], "5000000", 0.99),
        ]
        self.assertIsNone(self.任务.定位城墙升级确认资源按钮(OCR结果))

    def test_资源不足只返回主世界且不点击宝石或商店(self):
        键盘 = Mock()
        上下文 = SimpleNamespace(
            键盘=键盘,
            点击=Mock(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )

        self.任务._标记资源不足并返回主世界(上下文, "金币不足")

        self.assertTrue(上下文.刷墙需要资源)
        键盘.按字符按压.assert_not_called()
        上下文.点击.assert_called_once_with(90, 80, 延时=350, 是否精确点击=True)
        日志 = " ".join(调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list)
        self.assertIn("禁止使用宝石", 日志)
        self.assertIn("禁止进入商店", 日志)

    def test_未确认城墙面板绝不发送返回键(self):
        键盘 = Mock()
        上下文 = SimpleNamespace(
            键盘=键盘,
            op=SimpleNamespace(获取屏幕图像cv=Mock(return_value=np.zeros((600, 800, 3), dtype=np.uint8))),
            点击=Mock(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        self.任务.执行OCR识别 = Mock(return_value=[])

        self.任务._标记资源不足并返回主世界(上下文, "费用未知")

        键盘.按字符按压.assert_not_called()
        上下文.点击.assert_called_once_with(90, 80, 延时=350, 是否精确点击=True)
        日志 = " ".join(调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list)
        self.assertNotIn("发送ESC", 日志)

    def test_资源不足时没有安全可点击资源(self):
        self.assertIsNone(
            self.任务.选择可安全使用的升级资源(
                1_000_000,
                2_000_000,
                5_000_000,
                5_000_000,
                True,
                True,
            )
        )
        self.assertEqual(
            self.任务.选择可安全使用的升级资源(
                6_000_000,
                2_000_000,
                5_000_000,
                5_000_000,
                True,
                True,
            ),
            "金币",
        )

    def test_缺少家乡资源状态时返回未知而不是零(self):
        状态 = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            机器人标志="robot_1",
            数据库=SimpleNamespace(获取最新完整状态=Mock(return_value=状态)),
        )

        self.assertEqual(self.任务.获取当前墙体资源(上下文), (None, None))

    def test_资源未知时执行升级不点击任何入口(self):
        状态 = SimpleNamespace(状态数据={})
        上下文 = SimpleNamespace(
            机器人标志="robot_1",
            数据库=SimpleNamespace(获取最新完整状态=Mock(return_value=状态)),
            点击=Mock(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )

        self.assertFalse(
            self.任务.执行升级(
                上下文,
                0,
                0,
                10,
                10,
                已选中=True,
                OCR结果=[],
            )
        )
        上下文.点击.assert_not_called()
        状态文本 = " ".join(调用.args[0] for 调用 in 上下文.置脚本状态.call_args_list)
        self.assertIn("禁止点击城墙升级入口", 状态文本)

    def test_执行升级资源不足不会点击资源入口(self):
        状态 = SimpleNamespace(
            状态数据={"家乡资源": {"金币": 1_000_000, "圣水": 2_000_000}}
        )
        上下文 = SimpleNamespace(
            机器人标志="robot_1",
            数据库=SimpleNamespace(获取最新完整状态=Mock(return_value=状态)),
            键盘=Mock(),
            点击=Mock(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        self.任务.识别城墙升级资源按钮 = Mock(return_value={
            "金币": True,
            "金币点击点": (447, 484),
            "圣水": True,
            "圣水点击点": (534, 484),
        })
        self.任务.确认城墙升级提交 = Mock()
        OCR结果 = [
            ([[411, 450], [471, 450], [471, 464], [411, 464]], "5000000", 0.80),
            ([[500, 450], [559, 450], [559, 464], [500, 464]], "5000000", 0.80),
        ]

        self.assertFalse(
            self.任务.执行升级(
                上下文,
                0,
                0,
                10,
                10,
                已选中=True,
                OCR结果=OCR结果,
            )
        )
        self.assertTrue(上下文.刷墙需要资源)
        上下文.点击.assert_called_once_with(90, 80, 延时=350, 是否精确点击=True)
        self.任务.确认城墙升级提交.assert_not_called()

    def test_能读取墙体等级并识别资源不足(self):
        OCR结果 = [
            ([[250, 416], [390, 416], [390, 443], [250, 443]], "城墙（16级-）", 0.95),
            ([[411, 450], [471, 450], [471, 464], [411, 464]], "5000000", 0.80),
            ([[500, 450], [559, 450], [559, 464], [500, 464]], "5000000", 0.80),
            ([[420, 498], [470, 498], [470, 515], [420, 515]], "升级", 0.95),
        ]

        self.assertEqual(self.任务.解析城墙等级(OCR结果), 16)
        状态 = self.任务.解析城墙状态(OCR结果, 当前金币=3_000_000, 当前圣水=4_000_000)
        self.assertEqual(状态["状态"], "资源不足")

    def test_主世界建造文字没有城墙标题时不得判定为可升级(self):
        # 实机失败帧中的“建造和升级”来自主世界底部入口，不是墙体面板。
        OCR结果 = [
            ([[120, 313], [260, 313], [260, 335], [120, 335]], "建造和升级", 0.95),
            ([[121, 374], [160, 374], [160, 390], [121, 390]], "5.90", 0.80),
            ([[120, 399], [165, 399], [165, 415], [120, 415]], "20.90", 0.80),
        ]
        状态 = self.任务.解析城墙状态(
            OCR结果, 当前金币=99_000_000, 当前圣水=99_000_000
        )
        self.assertEqual(状态["状态"], "待确认")

    def test_升级入口未稳定时刷新OCR但不重复点击墙段(self):
        状态 = SimpleNamespace(
            状态数据={"家乡资源": {"金币": 10_000_000, "圣水": 10_000_000}}
        )
        上下文 = SimpleNamespace(
            机器人标志="robot_1",
            数据库=SimpleNamespace(获取最新完整状态=Mock(return_value=状态)),
            点击=Mock(),
            脚本延时=Mock(),
            置脚本状态=Mock(),
        )
        OCR结果 = [
            ([[250, 416], [390, 416], [390, 443], [250, 443]], "城墙（16级）", 0.95),
            ([[411, 450], [471, 450], [471, 464], [411, 464]], "5000000", 0.80),
            ([[500, 450], [559, 450], [559, 464], [500, 464]], "5000000", 0.80),
            ([[420, 498], [470, 498], [470, 515], [420, 515]], "升级", 0.95),
        ]
        无按钮 = {"金币": False, "金币点击点": (0, 0), "圣水": False, "圣水点击点": (0, 0)}
        有按钮 = {"金币": True, "金币点击点": (447, 484), "圣水": True, "圣水点击点": (534, 484)}
        self.任务.识别城墙升级资源按钮 = Mock(side_effect=[无按钮, 有按钮])
        self.任务.执行OCR识别 = Mock(return_value=OCR结果)
        self.任务.确认城墙升级提交 = Mock(return_value=True)

        self.assertTrue(
            self.任务.执行升级(
                上下文, 0, 0, 10, 10, 已选中=True, OCR结果=OCR结果
            )
        )
        self.assertEqual(self.任务.识别城墙升级资源按钮.call_count, 2)
        上下文.点击.assert_called_once_with(447, 484, 延时=1000)

    def test_满级墙体不会进入升级候选(self):
        OCR结果 = [
            ([[250, 416], [390, 416], [390, 443], [250, 443]], "城墙（16级-）", 0.95),
            ([[420, 498], [470, 498], [470, 515], [420, 515]], "已满级", 0.95),
        ]
        状态 = self.任务.解析城墙状态(OCR结果, 当前金币=99_000_000, 当前圣水=99_000_000)
        self.assertEqual(状态["状态"], "已满级")

    def test_最低等级墙优先且资源不足不能跳到高等级(self):
        墙体记录 = [
            {"坐标": [500, 300], "等级": 16, "状态": "可升级"},
            {"坐标": [300, 300], "等级": 14, "状态": "资源不足"},
            {"坐标": [200, 300], "等级": 13, "状态": "已满级"},
        ]
        候选 = self.任务.选择最低等级墙段(墙体记录)
        self.assertEqual([记录["等级"] for 记录 in 候选], [14, 16])

    def test_能从升级确认框定位确认按钮(self):
        OCR结果 = [
            ([[328, 68], [468, 68], [468, 90], [328, 90]], "将城墙升至17级？", 0.95),
            ([[570, 465], [598, 465], [598, 483], [570, 483]], "确认", 0.95),
        ]
        self.assertEqual(self.任务.定位城墙升级确认按钮(OCR结果), (584, 474))

    def test_确认框消失后才报告升级提交成功(self):
        确认OCR = [
            ([[328, 68], [468, 68], [468, 90], [328, 90]], "将城墙升至17级？", 0.95),
            ([[570, 465], [598, 465], [598, 483], [570, 483]], "确认", 0.95),
        ]
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(),
            脚本延时=Mock(),
        )
        # 点击后需要连续两帧都没有确认页证据，才允许报告提交成功。
        self.任务.执行OCR识别 = Mock(side_effect=[确认OCR, [], []])
        self.assertTrue(self.任务.确认城墙升级提交(上下文))
        上下文.点击.assert_called_once_with(584, 474, 延时=650, 是否精确点击=True)

    def test_确认框仍在或宝石覆盖层出现时不报告升级成功(self):
        确认OCR = [
            ([[328, 68], [468, 68], [468, 90], [328, 90]], "將城牆升至17級？", 0.95),
            ([[508, 523], [590, 523], [590, 544], [508, 544]], "5000 000", 0.91),
        ]
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(),
            脚本延时=Mock(),
            检查宝石商店危险页面=Mock(side_effect=[True, False, False]),
        )
        self.任务.执行OCR识别 = Mock(side_effect=[确认OCR, 确认OCR, 确认OCR, 确认OCR])

        self.assertFalse(self.任务.确认城墙升级提交(上下文))
        上下文.点击.assert_called_once_with(549, 505, 延时=650, 是否精确点击=True)
        # 确认页仍然存在时，不能把确认页里的资源图标交给通用宝石模板；
        # 否则实机会误判并发送 ESC，留下未提交的确认框。
        上下文.检查宝石商店危险页面.assert_not_called()
        self.assertEqual(self.任务.执行OCR识别.call_count, 4)

    def test_确认后出现宝石提示先安全退出不被底层标题遮蔽(self):
        确认OCR = [
            ([[328, 68], [468, 68], [468, 90], [328, 90]], "将城墙升至17级？", 0.95),
            ([[508, 523], [590, 523], [590, 544], [508, 544]], "5000 000", 0.91),
        ]
        宝石提示OCR = [
            ([[328, 68], [468, 68], [468, 90], [328, 90]], "将城墙升至17级？", 0.95),
            ([[620, 230], [760, 230], [760, 260], [620, 260]], "使用寶石立即完成", 0.95),
        ]
        上下文 = SimpleNamespace(
            置脚本状态=Mock(),
            点击=Mock(),
            脚本延时=Mock(),
            检查宝石商店危险页面=Mock(return_value=True),
        )
        self.任务.执行OCR识别 = Mock(side_effect=[确认OCR, 宝石提示OCR])

        self.assertFalse(self.任务.确认城墙升级提交(上下文))
        上下文.点击.assert_called_once_with(549, 505, 延时=650, 是否精确点击=True)
        上下文.检查宝石商店危险页面.assert_called_once_with(强制=True)
        self.assertTrue(any(
            "禁止使用宝石" in 调用.args[0]
            for 调用 in 上下文.置脚本状态.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()
