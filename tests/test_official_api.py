"""官方 API 账号数据：名称映射、满级判断和升级任务跳过逻辑（不访问网络）。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from 数据库.任务数据库 import 机器人设置, 任务数据库
from 应用 import 任务计划 as 计划
from 服务 import 官方API
from 线程.自动化机器人 import 自动化机器人

样例玩家 = {
    "tag": "#ABC", "name": "测试", "townHallLevel": 17,
    "heroes": [
        {"name": "Barbarian King", "level": 95, "maxLevel": 95, "village": "home"},
        {"name": "Archer Queen", "level": 90, "maxLevel": 95, "village": "home"},
        {"name": "Battle Machine", "level": 35, "maxLevel": 35, "village": "builderBase"},
    ],
    "troops": [
        {"name": "Barbarian", "level": 12, "maxLevel": 12, "village": "home"},
        {"name": "Hog Rider", "level": 13, "maxLevel": 14, "village": "home"},
        {"name": "Baby Dragon", "level": 20, "maxLevel": 20, "village": "builderBase"},
        {"name": "Rocket Balloon", "level": 1, "maxLevel": 10, "village": "home",
         "superTroopIsActive": True},
        {"name": "Unicorn", "level": 10, "maxLevel": 10, "village": "home"},
        {"name": "Phoenix", "level": 3, "maxLevel": 10, "village": "home"},
    ],
    "spells": [
        {"name": "Healing Spell", "level": 11, "maxLevel": 11, "village": "home"},
        {"name": "Poison Spell", "level": 10, "maxLevel": 12, "village": "home"},
    ],
}


class 账号摘要测试(unittest.TestCase):
    def setUp(self):
        self.摘要 = 官方API.整理账号摘要(样例玩家)

    def test_英文名映射为设置里的游戏内中文名(self):
        self.assertEqual(self.摘要.英雄["野蛮人之王"], (95, 95))
        self.assertEqual(self.摘要.研究["疗伤法术"], (11, 11))
        self.assertEqual(self.摘要.研究["伤害药水法术"], (10, 12))
        self.assertEqual(self.摘要.战宠["独角"], (10, 10))
        self.assertNotIn("战争机器", self.摘要.英雄)  # 夜世界英雄不计入
        self.assertEqual(self.摘要.已激活超级兵种, ["Rocket Balloon"])

    def test_满级判断区分已知与未知(self):
        self.assertIs(self.摘要.是否满级("研究", "野蛮人"), True)
        self.assertIs(self.摘要.是否满级("研究", "野猪骑士"), False)
        self.assertIsNone(self.摘要.是否满级("研究", "不存在的兵种"))
        self.assertEqual(self.摘要.未满级("战宠"), ["凤凰"])

    def test_映射名称都在设置选项里(self):
        元数据 = 机器人设置.__dataclass_fields__
        研究选项 = set(元数据["欲升级的兵种或法术"].metadata["选项"])
        战宠选项 = set(元数据["欲升级的战宠"].metadata["选项"])
        英雄选项 = set(元数据["欲升级的英雄或建筑"].metadata["默认选项"])
        self.assertLessEqual(set(官方API.研究名称.values()), 研究选项)
        self.assertLessEqual(set(官方API.战宠名称.values()), 战宠选项)
        self.assertLessEqual(set(官方API.英雄名称.values()), 英雄选项)

    def test_标签规范化(self):
        self.assertEqual(官方API.规范化标签(" abc123 "), "#ABC123")
        self.assertEqual(官方API.规范化标签("#2pp"), "#2PP")
        self.assertEqual(官方API.规范化标签("#qo"), "#Q0")

    def test_令牌含非法字符时给出明确错误且不发请求(self):
        with patch("urllib.request.urlopen") as 请求:
            for 坏令牌 in ("无效令牌", "abc def", "abc\ndef", "ａｂｃ"):
                with self.assertRaises(官方API.官方API错误) as 上下文:
                    官方API.获取玩家(坏令牌, "#ABC")
                self.assertIn("非法字符", str(上下文.exception))
        请求.assert_not_called()

    def test_摘要可以序列化存库(self):
        import json
        json.dumps(self.摘要.转为字典(), ensure_ascii=False)
        self.assertIn("未满级研究 2 项（野猪骑士、伤害药水法术）", self.摘要.日志文本())


class 升级跳过测试(unittest.TestCase):
    def _机器人(self, **设置项):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "测试"
        设置 = 机器人设置(官方API令牌="t", 玩家标签="#ABC", **设置项)
        机器人.数据库 = SimpleNamespace(获取机器人设置=Mock(return_value=设置))
        上下文 = SimpleNamespace(
            置脚本状态=Mock(), 数据库=SimpleNamespace(更新状态=Mock()),
            请求任务计划等待=Mock(),
        )
        return 机器人, 上下文

    def test_研究目标已满级时跳过并请求等待(self):
        机器人, 上下文 = self._机器人(欲升级的兵种或法术="野蛮人")
        with patch.object(官方API, "获取玩家", return_value=样例玩家):
            self.assertTrue(机器人._官方数据显示已满级("research", 上下文))
        上下文.请求任务计划等待.assert_called_once()
        上下文.数据库.更新状态.assert_called_once()

    def test_研究目标未满级时照常执行(self):
        机器人, 上下文 = self._机器人(欲升级的兵种或法术="野猪骑士")
        with patch.object(官方API, "获取玩家", return_value=样例玩家):
            self.assertFalse(机器人._官方数据显示已满级("research", 上下文))

    def test_英雄列表含未满级或建筑时不跳过(self):
        机器人, 上下文 = self._机器人(欲升级的英雄或建筑=["野蛮人之王", "弓箭女皇"])
        with patch.object(官方API, "获取玩家", return_value=样例玩家):
            self.assertFalse(机器人._官方数据显示已满级("hero", 上下文))
        机器人, 上下文 = self._机器人(欲升级的英雄或建筑=["野蛮人之王", "加农炮"])
        with patch.object(官方API, "获取玩家", return_value=样例玩家):
            self.assertFalse(机器人._官方数据显示已满级("hero", 上下文))
        机器人, 上下文 = self._机器人(欲升级的英雄或建筑=["野蛮人之王"])
        with patch.object(官方API, "获取玩家", return_value=样例玩家):
            self.assertTrue(机器人._官方数据显示已满级("hero", 上下文))

    def test_战宠满级跳过(self):
        机器人, 上下文 = self._机器人(欲升级的战宠="独角")
        with patch.object(官方API, "获取玩家", return_value=样例玩家):
            self.assertTrue(机器人._官方数据显示已满级("pet", 上下文))

    def test_同步失败按原流程执行(self):
        机器人, 上下文 = self._机器人(欲升级的兵种或法术="野蛮人")
        with patch.object(官方API, "获取玩家", side_effect=官方API.官方API错误(403, "accessDenied")):
            self.assertFalse(机器人._官方数据显示已满级("research", 上下文))
        self.assertIn("同步失败", 上下文.置脚本状态.call_args[0][0])

    def test_未配置时不访问网络(self):
        机器人 = 自动化机器人.__new__(自动化机器人)
        机器人.机器人标志 = "测试"
        机器人.数据库 = SimpleNamespace(获取机器人设置=Mock(return_value=机器人设置(欲升级的兵种或法术="野蛮人")))
        with patch.object(官方API, "获取玩家") as 获取:
            self.assertFalse(机器人._官方数据显示已满级("research", SimpleNamespace(置脚本状态=Mock())))
        获取.assert_not_called()

    def test_同步结果在间隔内复用(self):
        机器人, 上下文 = self._机器人(欲升级的兵种或法术="野猪骑士")
        with patch.object(官方API, "获取玩家", return_value=样例玩家) as 获取:
            机器人._官方数据显示已满级("research", 上下文)
            机器人._官方数据显示已满级("research", 上下文)
        self.assertEqual(获取.call_count, 1)

    def test_建筑任务不受影响(self):
        机器人, 上下文 = self._机器人()
        with patch.object(官方API, "获取玩家") as 获取:
            self.assertFalse(机器人._官方数据显示已满级("building", 上下文))
        获取.assert_not_called()


class 设置与界面测试(unittest.TestCase):
    def test_参数页校验同步间隔(self):
        设置 = 机器人设置()
        计划.应用参数(设置, "official_api", {
            "官方API令牌": " abc ", "玩家标签": "#ABC", "官方数据同步间隔分钟": "60",
        })
        self.assertEqual((设置.官方API令牌, 设置.玩家标签, 设置.官方数据同步间隔分钟), ("abc", "#ABC", 60))
        with self.assertRaises(ValueError):
            计划.应用参数(设置, "official_api", {"官方数据同步间隔分钟": "1"})
        self.assertIn("official_api", 计划.全局配置键)

    def test_旧配置缺少新字段也能加载(self):
        规范化 = 任务数据库._规范化机器人设置JSON({"开启刷墙": True})
        设置 = 机器人设置(**规范化)
        self.assertEqual(设置.官方API令牌, "")
        self.assertEqual(设置.官方数据同步间隔分钟, 30)


if __name__ == "__main__":
    unittest.main()
