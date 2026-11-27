"""对少量实机截图调用现有识别函数的离线回放回归。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from 模块.检测.OCR识别器 import 安全OCR引擎
from 模块.检测.页面识别器 import 页面识别器
from 模块.检测.模板匹配器 import 模板匹配引擎
from 任务流程.基础任务框架 import 任务上下文
from 任务流程.更新主世界账号资源状态 import 更新家乡资源状态任务
from 任务流程.夜世界.更新夜世界账号资源状态 import 更新夜世界资源状态任务
from 任务流程.夜世界.收集圣水车 import 收集圣水车任务
from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务
from 任务流程.活动.部落竞赛 import 部落竞赛任务, 加载配置, 识别任务类型, 规范文本


测试目录 = Path(__file__).resolve().parent
样本目录 = 测试目录 / "回放样本"
标注 = json.loads((样本目录 / "标注.json").read_text(encoding="utf-8"))
样本表 = {样本["id"]: 样本 for 样本 in 标注["样本"]}
结算样本ID = (
    "settle_20261125_061956",
    "settle_20261125_071950",
    "settle_20261125_081054",
)
竞赛页面样本ID = (
    "clan_walkthrough_home",
    "clan_walkthrough_activity_list",
    "clan_games_panel",
    "clan_games_gold_task",
    "clan_walkthrough_black_oil",
    "clan_walkthrough_builder_base",
    "clan_walkthrough_start_pending",
    "clan_walkthrough_active_task",
    "clan_walkthrough_gray_cards",
    "clan_walkthrough_reopened_detail",
    "clan_walkthrough_closed_reflow",
    "clan_walkthrough_page_two",
    "standby_20261125_clan_panel",
)
近期待命样本ID = (
    "standby_20261125_reward_chest",
    "standby_20261126_battle",
    "standby_20261126_elixir_cart",
    "standby_20261127_elixir_cart_empty",
)


def 读取截图(文件: Path) -> np.ndarray:
    数据 = np.fromfile(str(文件), dtype=np.uint8)
    图像 = cv2.imdecode(数据, cv2.IMREAD_COLOR)
    if 图像 is None:
        raise AssertionError(f"截图无法解码：{文件}")
    return 图像


def 读取样本(样本ID: str) -> np.ndarray:
    return 读取截图(样本目录 / 样本表[样本ID]["image"])


class 实机截图回放测试(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        根目录 = 测试目录.parent
        cls.页面识别器 = 页面识别器(
            模板匹配引擎(图片库路径=根目录 / "img")
        )
        cls.OCR引擎 = 安全OCR引擎()
        cls._结算OCR缓存 = None

    @classmethod
    def _结算OCR结果(cls):
        if cls._结算OCR缓存 is None:
            结果任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
            结果任务.ocr引擎 = cls.OCR引擎
            cls._结算OCR缓存 = {}
            for 样本ID in 结算样本ID:
                图像 = 读取样本(样本ID)
                OCR结果, 文本, 战斗结果, 摧毁率 = 结果任务.识别结算帧(图像)
                星数 = 结果任务.识别星数(图像, 文本)
                cls._结算OCR缓存[样本ID] = {
                    "OCR结果": OCR结果,
                    "文本": 文本,
                    "战斗结果": 战斗结果,
                    "摧毁率": 摧毁率,
                    "星数": 星数,
                }
        return cls._结算OCR缓存

    def _部落竞赛任务(self, 图像: np.ndarray) -> 部落竞赛任务:
        任务 = 部落竞赛任务.__new__(部落竞赛任务)
        任务._配置 = 加载配置()
        任务._模板缓存 = {}
        任务.ocr引擎 = self.OCR引擎
        操作 = SimpleNamespace(
            获取屏幕图像cv=lambda *args, **kwargs: 图像,
        )
        任务.上下文 = SimpleNamespace(
            op=操作,
            获取OCR引擎=lambda: self.OCR引擎,
            置脚本状态=lambda *args: None,
        )
        return 任务

    def test_现有主页和断线截图页面识别(self):
        根目录 = 测试目录.parent
        样本 = (
            ("coc_home_18_647_5.png", "主世界主页"),
            ("coc_idle_disconnect_18_647_5.png", "断线弹窗"),
        )
        for 文件名, 预期页面 in 样本:
            with self.subTest(文件=文件名):
                图像 = 读取截图(根目录 / "tests" / "fixtures" / 文件名)
                实际 = self.页面识别器.识别(图像)
                self.assertEqual(实际.页面, 预期页面, 实际.摘要())

    def test_结算页类型识别(self):
        for 样本ID in 结算样本ID:
            with self.subTest(样本=样本ID):
                实际 = self.页面识别器.识别(读取样本(样本ID))
                self.assertEqual(
                    实际.页面,
                    样本表[样本ID]["expected"]["page"],
                    实际.摘要(),
                )

    def test_非结算实机截图不误定位回营按钮(self):
        根目录 = 测试目录.parent
        非结算样本 = (
            读取截图(根目录 / "tests" / "fixtures" / "coc_home_18_647_5.png"),
            读取截图(根目录 / "tests" / "fixtures" / "coc_idle_disconnect_18_647_5.png"),
            读取截图(根目录 / "tests" / "fixtures" / "coc_army_config_live_ui.png"),
            读取样本("clan_games_panel"),
            读取样本("clan_games_gold_task"),
        )
        for 序号, 图像 in enumerate(非结算样本):
            with self.subTest(序号=序号):
                self.assertIsNone(self.页面识别器.定位结算回营按钮(图像))

    def test_部落竞赛截图主世界识别(self):
        for 样本ID in ("clan_games_panel", "clan_games_gold_task"):
            with self.subTest(样本=样本ID):
                结果 = self.页面识别器.世界识别.识别(读取样本(样本ID))
                self.assertEqual(
                    结果.当前世界,
                    样本表[样本ID]["expected"]["world"],
                    结果.摘要(),
                )

    def test_实机军队配置页有专属页面识别(self):
        根目录 = 测试目录.parent
        图像 = 读取截图(根目录 / "tests" / "fixtures" / "coc_army_config_live_ui.png")

        结果 = self.页面识别器.识别(图像, 战斗中=False)

        self.assertEqual(结果.页面, "军队配置页", 结果.摘要())

    def test_结算页资源OCR数值(self):
        资源任务 = 更新家乡资源状态任务.__new__(更新家乡资源状态任务)
        资源任务.ocr引擎 = self.OCR引擎
        for 样本ID in 结算样本ID:
            图像 = 读取样本(样本ID)
            操作 = SimpleNamespace(
                获取屏幕图像cv=lambda x1, y1, x2, y2, **kwargs: 图像[y1:y2, x1:x2]
            )
            上下文 = SimpleNamespace(
                op=操作,
                置脚本状态=lambda *args: None,
                脚本延时=lambda *args: None,
            )
            实际 = 资源任务.识别当前资源(上下文)
            预期 = 样本表[样本ID]["expected"]["resources"]
            with self.subTest(样本=样本ID):
                self.assertTrue(实际["识别成功"], 实际)
                self.assertEqual(
                    {键: 实际[键] for 键 in 预期},
                    预期,
                    f"{样本ID}：{实际}",
                )

    def test_结算页OCR摧毁率(self):
        结果 = self._结算OCR结果()
        for 样本ID in 结算样本ID:
            with self.subTest(样本=样本ID):
                预期 = 样本表[样本ID]["expected"]["settlement"]["摧毁率"]
                self.assertEqual(结果[样本ID]["摧毁率"], 预期, 结果[样本ID]["文本"])

    def test_部落竞赛面板和任务卡OCR(self):
        面板样本 = 样本表["clan_games_panel"]["expected"]
        面板图像 = 读取样本("clan_games_panel")
        面板任务 = self._部落竞赛任务(面板图像)
        面板 = 面板任务._识别竞赛面板()
        self.assertIsNotNone(面板, "标题、面板模板或关闭按钮未识别")
        关闭点 = 面板任务._匹配模板(面板图像, "关闭按钮")
        self.assertEqual(关闭点, tuple(面板样本["buttons"]["关闭"]))

        任务样本 = 样本表["clan_games_gold_task"]["expected"]
        详情图像 = 读取样本("clan_games_gold_task")
        详情任务 = self._部落竞赛任务(详情图像)
        详情 = 详情任务._识别详情()
        self.assertIsNotNone(详情, "任务开始按钮或详情文字未识别")
        self.assertEqual(详情["开始点"], tuple(任务样本["buttons"]["开始"]))
        实际文本 = 详情["文本"].replace(" ", "")
        self.assertIn("200000", 实际文本)
        self.assertIn("金", 实际文本)
        self.assertEqual(
            识别任务类型(详情["文本"], 详情任务.配置, ""),
            任务样本["clan_task_type"],
        )

    def test_进行中卡面无文案时只读打开任务详情取得比对文本(self):
        面板图像 = 读取样本("clan_walkthrough_gray_cards")
        详情图像 = 读取样本("clan_walkthrough_active_task")
        任务 = self._部落竞赛任务(面板图像)
        当前画面 = [面板图像]
        点击记录 = []
        任务.上下文.op.获取屏幕图像cv = lambda *args, **kwargs: 当前画面[0]
        任务._截止 = 10
        任务._时钟 = lambda: 0
        任务._日志 = lambda *args: None
        任务._延时 = lambda *args: None

        def 点击(位置, 说明):
            点击记录.append((tuple(位置), 说明))
            当前画面[0] = 详情图像 if 说明 == "进行中任务卡详情" else 面板图像
            return True

        任务._点击 = 点击
        项列表 = 任务._OCR(面板图像, 任务.配置["面板"]["卡片区ROI"])

        文本 = 任务._读取当前任务卡文本(项列表)

        self.assertIsNotNone(文本)
        self.assertIn("5000", 文本)
        self.assertTrue(任务._任务卡文本匹配(文本, 文本))
        self.assertEqual(
            点击记录,
            [((341, 165), "进行中任务卡详情"), ((160, 500), "空白处关闭详情")],
        )
        self.assertIs(当前画面[0], 面板图像)

    def test_进行中详情OCR只读到放字仍提取稳定目标(self):
        图像 = 读取样本("clan_walkthrough_active_task")
        任务 = self._部落竞赛任务(图像)
        点击记录 = []
        任务._日志 = lambda *args: None
        任务._延时 = lambda *args: None
        任务._点击 = lambda 位置, 说明: 点击记录.append((tuple(位置), 说明)) or True
        项列表 = 任务._OCR(图像, 任务._卡片区(扩展=60))

        文本 = 任务._读取当前任务卡文本(项列表)

        self.assertIn("5000", 文本)
        self.assertNotIn("300", 文本)
        self.assertTrue(任务._任务卡文本匹配(文本, 文本))
        self.assertEqual(点击记录, [((160, 500), "空白处关闭详情")])

    def test_实机宝箱领奖全屏页不被误判为主世界主页且可安全收起(self):
        根目录 = 测试目录.parent
        实机原图 = 读取截图(
            根目录 / "tests" / "fixtures" / "奖励宝箱" / "live_reward_screen_1280x720.png"
        )
        实机800 = cv2.resize(实机原图, (800, 600), interpolation=cv2.INTER_AREA)
        同款奖励页 = 读取截图(
            根目录 / "tests" / "fixtures" / "奖励宝箱" / "奖励页_繼續.png"
        )
        主页截图 = 读取截图(根目录 / "tests" / "fixtures" / "coc_home_18_647_5.png")

        for 名称, 图像 in (
            ("live_1280x720", 实机原图),
            ("live_800x600", 实机800),
            ("奖励页_繼續", 同款奖励页),
        ):
            with self.subTest(样本=名称):
                世界结果 = self.页面识别器.世界识别.识别(图像)
                self.assertIsNone(世界结果.当前世界, 世界结果.摘要())
                self.assertEqual(
                    self.页面识别器.世界识别._新版战斗入口分数(图像),
                    0.0,
                    世界结果.摘要(),
                )
                self.assertLess(
                    世界结果.主世界入口分数,
                    self.页面识别器.世界识别.主世界入口阈值,
                    世界结果.摘要(),
                )
                self.assertNotIn("新版战斗入口", 世界结果.摘要())

                页面结果 = self.页面识别器.识别(图像, 战斗中=False)
                self.assertEqual(页面结果.页面, "宝箱领奖页", 页面结果.摘要())
                self.assertIsNone(页面结果.世界, 页面结果.摘要())
                self.assertGreaterEqual(页面结果.可信度, 0.95)
                self.assertIsNone(self.页面识别器.定位结算回营按钮(图像))
                self.assertEqual(self.页面识别器.定位宝箱领奖继续按钮(图像), (392, 515))

        # 真实 OCR + 清理宝箱领奖页：确认“繼續”后点击底部居中按钮并复核回到主世界主页
        for 名称, 领奖图 in (("live_1280x720", 实机原图), ("live_800x600", 实机800)):
            with self.subTest(OCR清理=名称):
                点击记录 = []
                当前帧 = [领奖图]
                上下文 = 任务上下文.__new__(任务上下文)
                上下文._战斗中 = False
                上下文._内存保护已触发 = False
                上下文._宝箱领奖连续点击次数 = 0
                上下文.页面恢复失败 = False
                上下文.停止事件 = SimpleNamespace(is_set=lambda: False)
                上下文._获取点击页面识别器 = lambda: self.页面识别器
                上下文.获取模板识别器 = lambda: self.页面识别器.模板识别
                上下文.获取OCR引擎 = lambda: self.OCR引擎
                上下文.脚本延时 = lambda *_a, **_k: None
                上下文.置脚本状态 = lambda *_a, **_k: None

                def _截(*_a, **_k):
                    return 当前帧[0]

                def _安全点击(x, y, 延时=0):
                    点击记录.append((x, y))
                    当前帧[0] = 主页截图
                    return True

                上下文.op = SimpleNamespace(获取屏幕图像cv=_截)
                上下文.点击已确认安全按钮 = _安全点击
                self.assertTrue(上下文.清理宝箱领奖页(领奖图))
                self.assertEqual(点击记录, [(392, 515)])
                self.assertEqual(上下文._宝箱领奖连续点击次数, 0)
                self.assertFalse(上下文.页面恢复失败)

    def test_非宝箱领奖页实机与合成负例不误命中(self):
        根目录 = 测试目录.parent
        商店绿按钮 = np.full((600, 800, 3), (45, 45, 50), dtype=np.uint8)
        cv2.rectangle(商店绿按钮, (150, 120), (650, 440), (210, 205, 195), -1)
        cv2.rectangle(商店绿按钮, (349, 489), (453, 547), (70, 225, 100), -1)

        宝石弹窗 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(宝石弹窗, (365, 100), (740, 412), (220, 220, 220), -1)
        cv2.rectangle(宝石弹窗, (700, 108), (730, 150), (20, 20, 210), -1)
        cv2.rectangle(宝石弹窗, (340, 485), (460, 545), (60, 210, 80), -1)

        负例列表 = (
            ("coc_home", 读取截图(根目录 / "tests" / "fixtures" / "coc_home_18_647_5.png"), False),
            ("disconnect", 读取截图(根目录 / "tests" / "fixtures" / "coc_idle_disconnect_18_647_5.png"), False),
            ("army_config", 读取截图(根目录 / "tests" / "fixtures" / "coc_army_config_live_ui.png"), False),
            ("clan_games_panel", 读取样本("clan_games_panel"), False),
            ("clan_games_gold_task", 读取样本("clan_games_gold_task"), False),
            ("settle_061956", 读取样本("settle_20261125_061956"), False),
            ("chest_tap", 读取截图(根目录 / "tests" / "fixtures" / "奖励宝箱" / "宝箱页_4根.png"), False),
            ("shop_green", 商店绿按钮, False),
            ("gem_popup", 宝石弹窗, False),
            ("battle_wood_like", 读取截图(根目录 / "tests" / "fixtures" / "奖励宝箱" / "live_reward_screen_1280x720.png"), True),
        )
        for 名称, 图像, 战斗中 in 负例列表:
            with self.subTest(负例=名称, 战斗中=战斗中):
                结果 = self.页面识别器.识别(图像, 战斗中=战斗中)
                self.assertNotEqual(结果.页面, "宝箱领奖页", 结果.摘要())
                if not 战斗中:
                    self.assertIsNone(self.页面识别器.定位宝箱领奖继续按钮(图像))



    def test_活动列表与部落竞赛全套实机截图不误判为升级详情弹窗(self):
        for 样本ID in 竞赛页面样本ID:
            样本 = 样本表[样本ID]
            预期 = 样本["expected"]
            图像 = 读取样本(样本ID)
            with self.subTest(样本=样本ID):
                实际 = self.页面识别器.识别(图像, 战斗中=False)
                self.assertEqual(实际.页面, 预期["page"], 实际.摘要())
                if 预期.get("world") is not None:
                    self.assertEqual(实际.世界, 预期["world"], 实际.摘要())
                self.assertNotEqual(实际.页面, "升级详情弹窗", 实际.摘要())
                if 实际.页面 == "活动弹窗":
                    self.assertIsNotNone(
                        self.页面识别器.定位活动弹窗关闭按钮(图像)
                    )
                    self.assertIsNone(
                        self.页面识别器._升级详情弹窗关闭点(图像)
                    )
                elif 实际.页面 in {"部落竞赛面板", "部落竞赛任务详情"}:
                    self.assertIsNotNone(
                        self.页面识别器.定位部落竞赛关闭按钮(图像)
                    )
                    self.assertIsNone(
                        self.页面识别器._升级详情弹窗关闭点(图像)
                    )

    def test_部落竞赛实机详情存在且任务类型符合标注(self):
        for 样本ID in (
            "clan_games_gold_task",
            "clan_walkthrough_black_oil",
            "clan_walkthrough_builder_base",
            "clan_walkthrough_start_pending",
        ):
            样本 = 样本表[样本ID]
            预期 = 样本["expected"]
            图像 = 读取样本(样本ID)
            任务 = self._部落竞赛任务(图像)
            详情 = 任务._识别详情()
            with self.subTest(样本=样本ID):
                self.assertIsNotNone(详情)
                self.assertEqual(
                    识别任务类型(详情["文本"], 任务.配置, ""),
                    预期["clan_task_type"],
                    详情["文本"],
                )

    @unittest.expectedFailure
    def test_部落竞赛实机详情OCR保留可见目标文本(self):
        for 样本ID in ("clan_games_gold_task", "clan_walkthrough_black_oil"):
            样本 = 样本表[样本ID]
            预期 = 样本["expected"]
            详情 = self._部落竞赛任务(读取样本(样本ID))._识别详情()
            详情文本 = 详情["文本"] if 详情 is not None else ""
            with self.subTest(样本=样本ID):
                for 片段 in 预期["visible_text_fragments"]:
                    self.assertIn(
                        规范文本(片段),
                        规范文本(详情文本),
                        详情文本,
                    )

    def test_实机灰卡识别区分当前任务和锁定卡(self):
        样本 = 样本表["clan_walkthrough_gray_cards"]
        预期 = 样本["expected"]
        图像 = 读取样本("clan_walkthrough_gray_cards")
        任务 = self._部落竞赛任务(图像)

        self.assertTrue(任务._卡片已变灰(图像))
        self.assertFalse(任务._单卡已变灰(图像, tuple(预期["active_card"])))
        for 位置 in 预期["gray_cards"]:
            with self.subTest(灰卡=位置):
                self.assertTrue(任务._单卡已变灰(图像, tuple(位置)))

    def test_实机详情关闭和翻页后的页面状态(self):
        详情图 = 读取样本("clan_walkthrough_reopened_detail")
        已接任务图 = 读取样本("clan_walkthrough_active_task")
        面板图 = 读取样本("clan_walkthrough_closed_reflow")
        第二页图 = 读取样本("clan_walkthrough_page_two")
        第二页标注 = 样本表["clan_walkthrough_page_two"]["expected"]

        详情页 = self.页面识别器.识别(详情图, 战斗中=False)
        已接任务页 = self.页面识别器.识别(已接任务图, 战斗中=False)
        面板页 = self.页面识别器.识别(面板图, 战斗中=False)
        第二页 = self.页面识别器.识别(第二页图, 战斗中=False)
        self.assertEqual(详情页.页面, "部落竞赛任务详情", 详情页.摘要())
        self.assertEqual(已接任务页.页面, "部落竞赛任务详情", 已接任务页.摘要())
        self.assertEqual(面板页.页面, "部落竞赛面板", 面板页.摘要())
        self.assertEqual(第二页.页面, 第二页标注["page"], 第二页.摘要())
        self.assertEqual(第二页.世界, 第二页标注["world"], 第二页.摘要())
        self.assertEqual(第二页标注["page_index"], 2)

        详情 = self._部落竞赛任务(详情图)._识别详情()
        已接任务详情 = self._部落竞赛任务(已接任务图)._识别详情()
        关闭后详情 = self._部落竞赛任务(面板图)._识别详情()
        self.assertIsNotNone(详情)
        self.assertIsNone(详情["开始点"], 详情)
        self.assertIsNone(已接任务详情)
        self.assertIsNone(关闭后详情)

        面板任务 = self._部落竞赛任务(面板图)
        第二页任务 = self._部落竞赛任务(第二页图)
        面板指纹 = 面板任务._卡片区指纹(面板图)
        第二页指纹 = 第二页任务._卡片区指纹(第二页图)
        self.assertIsNotNone(面板指纹)
        self.assertIsNotNone(第二页指纹)
        self.assertFalse(
            面板任务._卡片区无变化(面板指纹, 第二页指纹),
            "第二页任务卡布局应与弹窗关闭后的第一页不同",
        )

    def test_近期待命实机截图不误判为结算或回营(self):
        for 样本ID in 近期待命样本ID:
            样本 = 样本表[样本ID]
            预期 = 样本["expected"]
            图像 = 读取样本(样本ID)
            with self.subTest(样本=样本ID):
                实际 = self.页面识别器.识别(图像, 战斗中=False)
                self.assertEqual(实际.页面, 预期["page"], 实际.摘要())
                if "return_button" in 预期:
                    self.assertIsNone(
                        self.页面识别器.定位结算回营按钮(图像)
                    )

    def test_rc158前序与待命实机帧回放为战斗而非奖励选择(self):
        """复放 21:17 现场连续帧，确认战斗 HUD 不再被误判为奖励页。"""
        回放目录 = 样本目录 / "进攻误判安全待命_20261126"
        截图列表 = sorted(回放目录.glob("前序_*.jpg"))
        截图列表.extend(
            (
                回放目录 / "当前_211737.png",
                回放目录 / "待命截图_211737.png",
            )
        )
        self.assertEqual(len(截图列表), 7)
        识别器 = 页面识别器(
            模板匹配引擎(图片库路径=测试目录.parent / "img")
        )
        for 图片路径 in 截图列表:
            with self.subTest(截图=图片路径.name):
                结果 = 识别器.识别(读取截图(图片路径), 战斗中=False)
                self.assertEqual(结果.页面, "战斗中", 结果.摘要())
                self.assertNotEqual(结果.页面, "战斗奖励选择", 结果.摘要())
    def test_夜世界圣水车实机截图分类与按钮护栏(self):
        样本 = 样本表["standby_20261126_elixir_cart"]
        预期 = 样本["expected"]
        图像 = 读取样本("standby_20261126_elixir_cart")
        页面 = self.页面识别器.识别(图像, 战斗中=False)
        按钮 = self.页面识别器.定位圣水车弹窗按钮(图像)

        self.assertEqual((页面.页面, 页面.世界), (预期["page"], 预期["world"]), 页面.摘要())
        self.assertIsNotNone(按钮)
        for 名称, (x, y) in 预期["buttons"].items():
            框 = 按钮[名称]
            self.assertTrue(框[0] <= x <= 框[2] and 框[1] <= y <= 框[3], (名称, 框))

        for x, y, 允许 in (
            (*预期["buttons"]["收集"], True),
            (*预期["buttons"]["关闭"], True),
            (610, 137, False),  # 圣水车列表行内的绿色升级按钮
            (760, 300, False),  # 背景商店入口
            (571, 339, False),  # 地图候选点
        ):
            上下文 = 任务上下文.__new__(任务上下文)
            上下文._战斗中 = False
            上下文.检查宝石商店危险页面 = lambda: False
            上下文._最近点击页面结果 = 页面
            上下文._点击识别截图 = 图像
            上下文.鼠标 = SimpleNamespace(_x=x, _y=y)
            上下文._获取点击页面识别器 = lambda: self.页面识别器
            上下文.置脚本状态 = lambda *_a, **_k: None
            self.assertEqual(
                上下文.输入前安全检查(),
                not 允许,
                f"点击({x},{y}) allowed={允许}",
            )

        # 仅有灰色升级标题栏与红色 X 的升级面板仍保持原先的封锁行为。
        升级面板 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(升级面板, (70, 20), (730, 580), (70, 80, 90), -1)
        cv2.rectangle(升级面板, (90, 30), (650, 80), (100, 100, 105), -1)
        cv2.rectangle(升级面板, (690, 20), (730, 70), (0, 0, 220), -1)
        cv2.line(升级面板, (698, 28), (722, 62), (245, 245, 245), 6)
        cv2.line(升级面板, (722, 28), (698, 62), (245, 245, 245), 6)
        升级页 = self.页面识别器.识别(升级面板, 战斗中=False)
        self.assertEqual(升级页.页面, "升级详情弹窗", 升级页.摘要())
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文.检查宝石商店危险页面 = lambda: False
        上下文._最近点击页面结果 = 升级页
        上下文._点击识别截图 = 升级面板
        上下文.关闭升级详情弹窗 = lambda *_a: False
        上下文.置脚本状态 = lambda *_a, **_k: None
        self.assertTrue(上下文.输入前安全检查())

    def test_夜世界圣水车截图资源OCR保留完整金币尾数(self):
        图像 = 读取样本("standby_20261126_elixir_cart")
        资源任务 = 更新夜世界资源状态任务.__new__(更新夜世界资源状态任务)
        资源任务.ocr引擎 = self.OCR引擎
        操作 = SimpleNamespace(
            获取屏幕图像cv=lambda x1, y1, x2, y2, **_kwargs: 图像[y1:y2, x1:x2]
        )
        上下文 = SimpleNamespace(op=操作, 置脚本状态=lambda *_a: None)

        实际 = 资源任务.识别当前资源(上下文)

        self.assertTrue(实际["识别成功"], 实际)
        self.assertEqual(
            {"金币": 实际["金币"], "圣水": 实际["圣水"]},
            样本表["standby_20261126_elixir_cart"]["expected"]["resources"],
            str(实际),
        )

    def test_夜世界空圣水车只允许关闭并拒绝收集点(self):
        图像列表 = (
            读取样本("standby_20261127_elixir_cart_empty"),
            读取截图(
                样本目录
                / "standby_20261127_114843_377_未知页面待命"
                / "当前.png"
            ),
        )
        for 图像 in 图像列表:
            with self.subTest(尺寸=图像.shape[:2]):
                页面 = self.页面识别器.识别(图像, 战斗中=False)
                按钮 = self.页面识别器.定位圣水车弹窗按钮(图像)

                self.assertEqual((页面.页面, 页面.世界), ("圣水车弹窗", "夜世界"), 页面.摘要())
                self.assertIsNotNone(按钮)
                self.assertTrue(按钮.get("空车"))
                self.assertIsNone(按钮.get("收集"))
                self.assertTrue(self._圣水车点击被拒绝(图像, 页面, (588, 507)))
                self.assertFalse(self._圣水车点击被拒绝(图像, 页面, (670, 60)))

        空车OCR, _ = self.OCR引擎(图像列表[0][150:390, 220:580])
        self.assertTrue(
            收集圣水车任务._是否圣水车为空文案(空车OCR),
            str([项[1] for 项 in 空车OCR or []]),
        )

    def _圣水车点击被拒绝(self, 图像, 页面, 坐标):
        上下文 = 任务上下文.__new__(任务上下文)
        上下文._战斗中 = False
        上下文.检查宝石商店危险页面 = lambda: False
        上下文._最近点击页面结果 = 页面
        上下文._点击识别截图 = 图像
        上下文.鼠标 = SimpleNamespace(_x=坐标[0], _y=坐标[1])
        上下文._获取点击页面识别器 = lambda: self.页面识别器
        上下文.置脚本状态 = lambda *_a, **_k: None
        return 上下文.输入前安全检查()

    def test_升级商店与宝石弹窗不被误认作空圣水车(self):
        升级面板 = np.zeros((600, 800, 3), dtype=np.uint8)
        cv2.rectangle(升级面板, (70, 20), (730, 580), (70, 80, 90), -1)
        cv2.rectangle(升级面板, (90, 30), (650, 80), (100, 100, 105), -1)
        cv2.rectangle(升级面板, (690, 20), (730, 70), (0, 0, 220), -1)
        cv2.line(升级面板, (698, 28), (722, 62), (245, 245, 245), 6)
        cv2.line(升级面板, (722, 28), (698, 62), (245, 245, 245), 6)

        def 商店或宝石面板(绿色按钮):
            图像 = np.zeros((600, 800, 3), dtype=np.uint8)
            cv2.rectangle(图像, (70, 20), (730, 580), (70, 80, 90), -1)
            cv2.rectangle(图像, (90, 30), (650, 80), (100, 100, 105), -1)
            cv2.rectangle(图像, (120, 457), (656, 553), (0, 120, 180), -1)
            cv2.rectangle(
                图像, (538, 478), (638, 532),
                (0, 210, 0) if 绿色按钮 else (140, 140, 140), -1,
            )
            cv2.circle(图像, (312, 514), 12, (180, 60, 220), -1)
            cv2.rectangle(图像, (690, 20), (730, 70), (0, 0, 220), -1)
            cv2.line(图像, (698, 28), (722, 62), (245, 245, 245), 6)
            cv2.line(图像, (722, 28), (698, 62), (245, 245, 245), 6)
            return 图像

        for 名称, 图像, 预期页 in (
            ("升级详情", 升级面板, "升级详情弹窗"),
            ("商店", 商店或宝石面板(False), None),
            ("宝石", 商店或宝石面板(True), None),
        ):
            with self.subTest(弹窗=名称):
                页面 = self.页面识别器.识别(图像, 战斗中=False)
                if 预期页 is not None:
                    self.assertEqual(页面.页面, 预期页, 页面.摘要())
                self.assertNotEqual(页面.页面, "圣水车弹窗", 页面.摘要())
                self.assertIsNone(self.页面识别器.定位圣水车弹窗按钮(图像))


def _添加页面识别回归用例(样本ID: str) -> None:
    def 检查(self):
        标注 = 样本表[样本ID]["expected"]
        实际 = self.页面识别器.识别(读取样本(样本ID))
        self.assertEqual(
            (实际.页面, 实际.世界),
            (标注["page"], 标注["world"]),
            实际.摘要(),
        )
        self.assertNotEqual(实际.页面, "升级详情弹窗", 实际.摘要())

    检查.__name__ = f"test_页面识别_{样本ID}"
    setattr(实机截图回放测试, 检查.__name__, 检查)


def _添加已知结算世界识别失败用例(样本ID: str) -> None:
    def 检查(self):
        预期 = 样本表[样本ID]["expected"]["world"]
        实际 = self.页面识别器.世界识别.识别(读取样本(样本ID))
        self.assertEqual(实际.当前世界, 预期, 实际.摘要())

    检查.__name__ = f"test_结算截图世界识别_{样本ID}"
    setattr(实机截图回放测试, 检查.__name__, 检查)


def _添加已知回营按钮定位失败用例(样本ID: str) -> None:
    def 检查(self):
        预期 = 样本表[样本ID]["expected"]["buttons"]["回营"]
        实际 = self.页面识别器.定位结算回营按钮(读取样本(样本ID))
        self.assertIsNotNone(实际, "没有定位到可见的绿色回营按钮")
        self.assertLessEqual(abs(实际[0] - 预期[0]), 8)
        self.assertLessEqual(abs(实际[1] - 预期[1]), 8)

    检查.__name__ = f"test_回营按钮定位_{样本ID}"
    setattr(实机截图回放测试, 检查.__name__, 检查)


def _添加星数回归用例(样本ID: str) -> None:
    def 检查(self):
        结果 = self._结算OCR结果()[样本ID]
        预期 = 样本表[样本ID]["expected"]["settlement"]["星数"]
        self.assertEqual(结果["星数"], 预期, 结果["文本"])

    检查.__name__ = f"test_结算星数识别_{样本ID}"
    setattr(实机截图回放测试, 检查.__name__, 检查)


for _样本ID in ("clan_games_panel", "clan_games_gold_task"):
    _添加页面识别回归用例(_样本ID)

for _样本ID in 结算样本ID:
    _添加已知结算世界识别失败用例(_样本ID)
    _添加已知回营按钮定位失败用例(_样本ID)
    _添加星数回归用例(_样本ID)
