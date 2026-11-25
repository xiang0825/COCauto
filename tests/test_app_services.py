"""应用层底座服务（战报服务、预设服务、现场图服务）单元测试。"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from 应用.战报服务 import 战报服务, 生成每日战报
from 应用.现场图服务 import 现场图服务, 解析截图文件名时间
from 应用.预设服务 import 预设服务
from 数据库.任务数据库 import 任务数据库, 机器人设置


def _本地时间戳(年: int, 月: int, 日: int, 时: int, 分: int = 0, 秒: int = 0) -> float:
    return datetime(年, 月, 日, 时, 分, 秒).timestamp()


class 战报服务测试(unittest.TestCase):
    def setUp(self):
        self._临时目录 = tempfile.TemporaryDirectory(prefix="coc-report-svc-")
        self.addCleanup(self._临时目录.cleanup)
        self.数据库路径 = Path(self._临时目录.name) / "任务系统.db"
        self.数据库 = 任务数据库(self.数据库路径)
        self.基准时间 = _本地时间戳(2026, 11, 25, 16, 30, 0)

    def _写入日志(self, 机器人ID: str, 时间戳: float, 内容: str):
        with self.数据库._获取连接() as conn:
            conn.execute(
                "INSERT INTO 任务日志 (机器人标志, 日志内容, 记录时间, 下次超时) VALUES (?, ?, ?, ?)",
                (机器人ID, 内容, 时间戳, 时间戳 + 60),
            )
            conn.commit()

    def _写入状态(self, 机器人ID: str, 时间戳: float, 类型: str, 值: object):
        文本 = 值 if isinstance(值, str) else json.dumps(值, ensure_ascii=False)
        with self.数据库._获取连接() as conn:
            conn.execute(
                "INSERT INTO 运行时状态 (机器人标志, 记录时间, 状态类型, 状态值) VALUES (?, ?, ?, ?)",
                (机器人ID, 时间戳, 类型, 文本),
            )
            conn.commit()

    def test_空数据库与不存在路径安全返回零值且不建库(self):
        缺失路径 = Path(self._临时目录.name) / "不存在.db"
        缺失战报 = 战报服务(缺失路径).生成战报("robot_1", 当前时间=self.基准时间)
        self.assertFalse(缺失路径.exists())
        self.assertEqual(缺失战报.今日.总场次, 0)
        self.assertIsNone(缺失战报.今日.胜率)
        self.assertIsNone(缺失战报.今日.平均摧毁率)
        self.assertIsNone(缺失战报.今日.平均搜敌次数)
        self.assertEqual(len(缺失战报.今日分小时), 24)

        空战报 = 生成每日战报(self.数据库, "robot_1", 当前时间=self.基准时间)
        self.assertEqual(空战报.今日.日期, "2026-11-25")
        self.assertEqual(空战报.昨日.日期, "2026-11-24")
        self.assertEqual(空战报.今日.总场次, 0)
        self.assertEqual(空战报.昨日.总场次, 0)
        self.assertEqual(空战报.今日.每小时场次, 0.0)
        self.assertEqual([项.小时 for 项 in 空战报.今日分小时], list(range(24)))

    def test_今日与昨日汇总及分小时效率与去重统计(self):
        # 今日 09 点：1 胜（日志 + 战斗学习 + 战斗资源分析，应去重只算 1 场）
        t1 = _本地时间戳(2026, 11, 25, 9, 10, 0)
        self._写入日志("robot_1", t1 - 30, "搜索次数[1] 金币[100000]")
        self._写入日志("robot_1", t1 - 20, "搜索次数[4] 金币[800000]")
        self._写入日志("robot_1", t1 - 15, "成功找到敌人")
        self._写入日志(
            "robot_1",
            t1,
            "战斗结果：胜利；星数：2；摧毁率：72%；当前胜率：100.0%；英雄技能：无英雄；ok",
        )
        self._写入日志(
            "robot_1",
            t1 + 12,
            "本场资源净变化：金币 +500000，圣水 +400000，黑油 +4500",
        )
        # 同一场对应的战斗资源分析快照不应重复叠加掠夺
        self._写入状态(
            "robot_1",
            t1 + 13,
            "战斗资源分析",
            {"本场净变化": {"金币": 500000, "圣水": 400000, "黑油": 4500}},
        )

        # 今日 14 点：1 负 + 1 胜（第二场仅写入战斗学习与战斗资源分析，模拟日志轮转后仍可统计）
        t2 = _本地时间戳(2026, 11, 25, 14, 5, 0)
        self._写入日志("robot_1", t2 - 10, "搜索次数[2] 金币[500000]")
        self._写入日志("robot_1", t2, "战斗结果：失败；星数：0；摧毁率：38%")
        self._写入日志(
            "robot_1",
            t2 + 10,
            "本场资源净变化：金币 +120000，圣水 -5000，黑油 +1000",
        )

        t3 = _本地时间戳(2026, 11, 25, 14, 40, 0)
        self._写入状态(
            "robot_1",
            t3 + 10,
            "战斗资源分析",
            {"本场净变化": {"金币": 600000, "圣水": 550000, "黑油": 5500}},
        )

        # 昨日 22 点：1 胜（写入战斗学习 + 战斗资源分析，且保留在同一个滚动快照里）
        y1 = _本地时间戳(2026, 11, 24, 22, 15, 0)
        self._写入日志("robot_1", y1 - 25, "黑水优先筛选：候选[6]黑油[5000]")
        self._写入日志("robot_1", y1 - 10, "成功找到敌人")
        self._写入状态(
            "robot_1",
            y1 + 15,
            "战斗资源分析",
            {"本场净变化": {"金币": 300000, "圣水": 200000, "黑油": 8000}},
        )
        self._写入状态(
            "robot_1",
            t3,
            "战斗学习",
            {
                "近期": [
                    {"结果": "胜利", "星数": 2, "摧毁率": 72, "时间": int(t1 + 2)},
                    {"结果": "胜利", "星数": 3, "摧毁率": 100, "时间": int(t3)},
                    {"结果": "胜利", "星数": 1, "摧毁率": 54, "时间": int(y1)},
                ]
            },
        )
        # 其他机器人的数据不可混入 robot_1
        self._写入日志("robot_2", t1, "战斗结果：胜利；星数：3；摧毁率：100%")

        战报 = 战报服务(self.数据库).生成战报("robot_1", 当前时间=self.基准时间)
        今日 = 战报.今日
        昨日 = 战报.昨日

        self.assertEqual(今日.总场次, 3)
        self.assertEqual(今日.胜场, 2)
        self.assertEqual(今日.负场, 1)
        self.assertEqual(今日.胜率, 66.7)
        self.assertEqual(今日.平均摧毁率, 70.0)  # (72 + 38 + 100) / 3
        self.assertEqual(今日.总掠夺金币, 1_220_000)
        self.assertEqual(今日.总掠夺圣水, 950_000)  # 负净变化 -5000 钳位为 0
        self.assertEqual(今日.总掠夺黑油, 11_000)
        self.assertEqual(今日.活跃小时数, 2)  # 9时与14时
        self.assertEqual(今日.每小时场次, 1.5)
        self.assertEqual(今日.每小时金币, 610_000.0)
        self.assertEqual(今日.平均搜敌次数, 3.0)  # (4 + 2) / 2
        self.assertEqual(今日.搜敌样本数, 2)

        self.assertEqual(战报.今日分小时[9].场次, 1)
        self.assertEqual(战报.今日分小时[9].胜场, 1)
        self.assertEqual(战报.今日分小时[9].金币, 500_000)
        self.assertEqual(战报.今日分小时[14].场次, 2)
        self.assertEqual(战报.今日分小时[14].胜场, 1)
        self.assertEqual(战报.今日分小时[14].金币, 720_000)
        self.assertEqual(战报.今日分小时[14].黑油, 6_500)
        self.assertEqual(战报.今日分小时[0].场次, 0)

        self.assertEqual(昨日.总场次, 1)
        self.assertEqual(昨日.胜场, 1)
        self.assertEqual(昨日.胜率, 100.0)
        self.assertEqual(昨日.平均摧毁率, 54.0)
        self.assertEqual(昨日.总掠夺金币, 300_000)
        self.assertEqual(昨日.总掠夺圣水, 200_000)
        self.assertEqual(昨日.总掠夺黑油, 8_000)
        self.assertEqual(昨日.平均搜敌次数, 6.0)

        字典 = 战报.to_dict()
        self.assertEqual(len(字典["今日分小时"]), 24)
        self.assertEqual(字典["今日"]["总场次"], 3)

    def test_兼容老记录缺失字段与损坏JSON(self):
        t = _本地时间戳(2026, 11, 25, 11, 0, 0)
        self._写入日志("robot_1", t, "战斗结果：未知；星数：待识别；摧毁率：待识别%")
        self._写入状态("robot_1", t + 5, "战斗资源分析", "{损坏json")
        self._写入状态("robot_1", t + 8, "战斗资源分析", {"目标战利品": {"金币": 100}})
        self._写入状态("robot_1", t + 10, "战斗学习", {"近期": [{"结果": None}]})

        战报 = 战报服务(self.数据库).生成战报("robot_1", 当前时间=self.基准时间)
        self.assertEqual(战报.今日.总场次, 1)
        self.assertEqual(战报.今日.未知结果场次, 1)
        self.assertIsNone(战报.今日.胜率)
        self.assertIsNone(战报.今日.平均摧毁率)
        self.assertEqual(战报.今日.总掠夺金币, 0)


class 预设服务测试(unittest.TestCase):
    def setUp(self):
        self._临时目录 = tempfile.TemporaryDirectory(prefix="coc-preset-svc-")
        self.addCleanup(self._临时目录.cleanup)
        self.数据库 = 任务数据库(Path(self._临时目录.name) / "任务系统.db")
        self.服务 = 预设服务(self.数据库)

    def test_三套内置预设字段均合法且语义正确(self):
        所有预设 = self.服务.获取预设列表()
        名称列表 = [p.名称 for p in 所有预设]
        self.assertEqual(名称列表[:3], ["隐哥冲黑油", "冲部落竞赛", "日常均衡刷墙"])

        合法字段 = set(机器人设置.__dataclass_fields__)
        for 方案 in 所有预设:
            self.assertTrue(方案.内置)
            self.assertTrue(set(方案.参数).issubset(合法字段))

        # 逐一套用并核对核心策略
        self.服务.应用预设("robot_1", "隐哥冲黑油")
        s1 = self.数据库.获取机器人设置("robot_1")
        self.assertEqual(s1.战利品优先级, "黑水")
        self.assertTrue(s1.是否刷主世界)
        self.assertEqual(s1.阵容预设, "隐秘哥布林刷资源")
        self.assertEqual(s1.黑水优先最低黑油, 11000)

        self.服务.应用预设("robot_1", "冲部落竞赛")
        s2 = self.数据库.获取机器人设置("robot_1")
        self.assertTrue(s2.是否部落竞赛接任务)
        self.assertEqual(s2.资源打满后动作, "继续打鱼")

        self.服务.应用预设("robot_1", "日常均衡刷墙")
        s3 = self.数据库.获取机器人设置("robot_1")
        self.assertEqual(s3.战利品优先级, "均衡")
        self.assertTrue(s3.开启刷墙)
        self.assertGreaterEqual(s3.刷墙起始金币, 10_000_000)
        self.assertEqual(s3.资源打满后动作, "待机")

    def test_差异预览_应用备份与一键撤销回退(self):
        初始 = 机器人设置(
            ADB设备序列号="emulator-5554",
            ADB已确认模拟器=True,
            欲进攻的最小资源=888_888,
            战利品优先级="金币",
            开启刷墙=False,
        )
        self.数据库.保存机器人设置("robot_1", 初始)

        差异 = self.服务.预览差异("robot_1", "隐哥冲黑油")
        self.assertTrue(差异.是否有变更)
        变更字段映射 = {项.字段: 项 for 项 in 差异.变更项}
        self.assertIn("战利品优先级", 变更字段映射)
        self.assertEqual(变更字段映射["战利品优先级"].当前值, "金币")
        self.assertEqual(变更字段映射["战利品优先级"].目标值, "黑水")
        self.assertNotIn("ADB设备序列号", 变更字段映射)
        # 预览不会修改数据库
        self.assertEqual(self.数据库.获取机器人设置("robot_1").战利品优先级, "金币")

        # 应用预设并自动备份
        self.assertFalse(self.服务.是否有回退快照("robot_1"))
        结果 = self.服务.应用预设("robot_1", "隐哥冲黑油")
        self.assertTrue(结果.成功)
        self.assertTrue(结果.已备份)
        self.assertTrue(self.服务.是否有回退快照("robot_1"))

        应用后 = self.数据库.获取机器人设置("robot_1")
        self.assertEqual(应用后.战利品优先级, "黑水")
        self.assertEqual(应用后.欲进攻的最小资源, 500_000)
        # 设备连接配置不被覆盖
        self.assertEqual(应用后.ADB设备序列号, "emulator-5554")
        self.assertTrue(应用后.ADB已确认模拟器)

        # 再切换一次，验证可连续回退
        self.服务.应用预设("robot_1", "冲部落竞赛")
        self.assertTrue(self.数据库.获取机器人设置("robot_1").是否部落竞赛接任务)

        回退1 = self.服务.回退预设("robot_1")
        self.assertTrue(回退1.成功)
        self.assertEqual(回退1.原预设名称, "冲部落竞赛")
        self.assertEqual(self.数据库.获取机器人设置("robot_1").战利品优先级, "黑水")

        回退2 = self.服务.回退预设("robot_1")
        self.assertTrue(回退2.成功)
        self.assertEqual(回退2.原预设名称, "隐哥冲黑油")
        恢复后 = self.数据库.获取机器人设置("robot_1")
        self.assertEqual(恢复后.欲进攻的最小资源, 888_888)
        self.assertEqual(恢复后.战利品优先级, "金币")
        self.assertFalse(self.服务.是否有回退快照("robot_1"))

        空回退 = self.服务.回退预设("robot_1")
        self.assertFalse(空回退.成功)

    def test_自定义预设持久化与JSON导入导出且无删除接口(self):
        当前 = 机器人设置(
            ADB设备序列号="127.0.0.1:7555",
            官方API令牌="secret-token",
            欲进攻的最小资源=1_234_567,
            开启刷墙=True,
            刷墙起始金币=9_000_000,
        )
        self.数据库.保存机器人设置("robot_1", 当前)

        已保存 = self.服务.保存当前为预设("robot_1", "夜猫高本配置", "夜间高阈值刷墙")
        self.assertFalse(已保存.内置)
        self.assertNotIn("ADB设备序列号", 已保存.参数)
        self.assertNotIn("官方API令牌", 已保存.参数)

        # 用新的服务实例重新读取，验证数据库持久化
        新服务 = 预设服务(self.数据库)
        读取到 = 新服务.获取预设("夜猫高本配置")
        self.assertEqual(读取到.参数["欲进攻的最小资源"], 1_234_567)
        self.assertEqual(读取到.参数["刷墙起始金币"], 9_000_000)

        # JSON 导出与导入
        导出文本 = 新服务.导出预设JSON("夜猫高本配置")
        导入后 = 新服务.导入预设JSON(导出文本, 覆盖名称="导入的夜猫配置")
        self.assertEqual(导入后.名称, "导入的夜猫配置")
        self.assertEqual(导入后.参数["欲进攻的最小资源"], 1_234_567)

        # 写文件导出仅创建文件，不提供删除接口
        目标文件 = Path(self._临时目录.name) / "presets" / "export.json"
        写入路径 = 新服务.写入预设JSON文件("隐哥冲黑油", 目标文件)
        self.assertTrue(写入路径.is_file())
        self.assertIn("隐哥冲黑油", 写入路径.read_text(encoding="utf-8"))
        for 属性名 in dir(新服务):
            self.assertNotIn("删除", 属性名)
            self.assertNotIn("delete", 属性名.lower())
            self.assertNotIn("remove", 属性名.lower())

        # 非法输入与保护内置预设
        with self.assertRaises(ValueError):
            新服务.保存当前为预设("robot_1", "隐哥冲黑油")
        with self.assertRaises(ValueError):
            新服务.导入预设JSON("{bad json")
        with self.assertRaises(ValueError):
            新服务.导入预设JSON('{"名称":"空","参数":{}}')


class 现场图服务测试(unittest.TestCase):
    def setUp(self):
        self._临时目录 = tempfile.TemporaryDirectory(prefix="coc-shot-svc-")
        self.addCleanup(self._临时目录.cleanup)
        self.数据集根 = Path(self._临时目录.name) / "数据集"

    def test_目录不存在时安全返回空列表且不创建目录(self):
        服务 = 现场图服务(self.数据集根)
        self.assertEqual(服务.扫描全部(), [])
        self.assertEqual(服务.获取最近截图(10), [])
        self.assertIsNone(服务.查找关联截图(time.time()))
        self.assertIsNone(服务.关联日志截图路径(time.time()))
        self.assertEqual(服务.批量关联日志([100.0, 200.0]), {})
        self.assertFalse(self.数据集根.exists())

    def test_解析文件名时间戳与按日志时间窗口反查且不删文件(self):
        待命目录 = self.数据集根 / "待命现场"
        复盘目录 = self.数据集根 / "低星复盘"
        待命目录.mkdir(parents=True)
        复盘目录.mkdir(parents=True)

        t1 = _本地时间戳(2026, 11, 25, 10, 0, 0)
        t2 = _本地时间戳(2026, 11, 25, 10, 5, 0)
        t3 = _本地时间戳(2026, 11, 25, 10, 10, 0)

        图1 = 待命目录 / "standby_20261125_100000_250_0001.png"
        图2 = 复盘目录 / "lowstar_20261125_100500.png"
        图3 = 待命目录 / "note_without_ts.jpg"
        非图片 = 待命目录 / "ignore.txt"

        图1.write_bytes(b"png-data-1")
        图2.write_bytes(b"png-data-22")
        图3.write_bytes(b"jpg-data-333")
        非图片.write_text("not an image", encoding="utf-8")
        os.utime(图3, (t3, t3))

        self.assertAlmostEqual(
            解析截图文件名时间(图1.name), t1 + 0.25, places=2
        )
        self.assertAlmostEqual(
            解析截图文件名时间(图2.name), t2, places=2
        )
        self.assertIsNone(解析截图文件名时间("note_without_ts.jpg"))

        服务 = 现场图服务(self.数据集根)
        最近 = 服务.获取最近截图(10)
        self.assertEqual(len(最近), 3)
        self.assertEqual([项.文件名 for 项 in 最近], [图3.name, 图2.name, 图1.name])
        self.assertEqual(最近[0].时间来源, "文件修改时间")
        self.assertEqual(最近[1].分类, "低星复盘")
        self.assertEqual(最近[2].分类, "待命现场")
        self.assertEqual(最近[2].文件大小, len(b"png-data-1"))

        # ±60 秒内反查最近一张
        匹配1 = 服务.查找关联截图(t1 + 20, 窗口秒=60)
        self.assertIsNotNone(匹配1)
        self.assertEqual(匹配1.文件路径, str(图1.resolve()))
        self.assertEqual(服务.关联日志截图路径(t2 - 15, 窗口秒=60), str(图2.resolve()))
        # 超出窗口返回 None
        self.assertIsNone(服务.查找关联截图(t1 + 120, 窗口秒=60))
        # 按分类筛选
        self.assertEqual(len(服务.获取最近截图(10, 分类="低星复盘")), 1)
        # 批量匹配
        批量 = 服务.批量关联日志([t1 + 5, t2 - 5, t1 + 180], 窗口秒=60)
        self.assertEqual(set(批量), {t1 + 5, t2 - 5})
        self.assertEqual(批量[t1 + 5].文件名, 图1.name)
        self.assertEqual(批量[t2 - 5].文件名, 图2.name)

        # 验证纯只读，未删除任何文件
        self.assertTrue(图1.is_file())
        self.assertTrue(图2.is_file())
        self.assertTrue(图3.is_file())
        self.assertTrue(非图片.is_file())


if __name__ == "__main__":
    unittest.main()
