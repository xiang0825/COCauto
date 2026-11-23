"""应用服务层（日志模型、任务计划、控制器）、异常体系与心跳缓存测试。"""
import os
import queue
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from 核心.异常 import (
    ADB异常, 可恢复任务异常, 战斗安全异常, 是否禁止自动恢复, 机器人停止请求, 文本命中安全锁,
)
from 应用 import 任务计划 as 计划
from 应用.控制器 import 应用控制器
from 应用.日志模型 import 日志条目, 日志聚合器, 合并连续重复, 推断级别, 是否重点
from 数据库.任务数据库 import 任务数据库, 机器人设置


class 异常体系测试(unittest.TestCase):
    def test_停止请求仍被旧SystemExit护栏放行(self):
        with self.assertRaises(SystemExit):
            raise 机器人停止请求("停止")

    def test_类型优先于文本(self):
        self.assertTrue(是否禁止自动恢复(ADB异常("任意")))
        self.assertTrue(是否禁止自动恢复(战斗安全异常("x")))
        # 即使文本里含“战斗”，显式声明可恢复的异常也允许恢复。
        self.assertFalse(是否禁止自动恢复(可恢复任务异常("战斗入口暂时找不到")))

    def test_旧异常按关键字兜底且未知默认可交给上层(self):
        self.assertTrue(是否禁止自动恢复(RuntimeError("截图超时")))
        self.assertFalse(是否禁止自动恢复(ValueError("配置错误")))
        self.assertTrue(文本命中安全锁("机器人 robot_1 无心跳"))
        self.assertTrue(是否禁止自动恢复(None))

    def test_ADB错误和图像获取失败属于安全锁(self):
        from 模块.ADB设备操作类 import ADB错误
        from 核心.核心异常们 import 图像获取失败

        self.assertIsInstance(ADB错误("x"), RuntimeError)
        self.assertTrue(是否禁止自动恢复(ADB错误("x")))
        self.assertTrue(是否禁止自动恢复(图像获取失败("x")))
        self.assertEqual(str(图像获取失败("断开")), "发生了：断开")


class 心跳缓存测试(unittest.TestCase):
    def test_最后日志读缓存且多个实例共享(self):
        目录 = tempfile.mkdtemp()
        路径 = os.path.join(目录, "t.db")
        写 = 任务数据库(路径)
        读 = 任务数据库(路径)
        self.assertIsNone(读.读取最后日志("r1"))
        写.记录日志("r1", "第一条", 100.0)
        写.记录日志("r1", "第二条", 200.0)
        with mock.patch.object(读, "_获取连接", side_effect=AssertionError("不应查询数据库")):
            日志 = 读.读取最后日志("r1")
        self.assertEqual((日志.日志内容, 日志.下次超时), ("第二条", 200.0))

    def test_不同数据库文件互不影响(self):
        甲 = 任务数据库(os.path.join(tempfile.mkdtemp(), "a.db"))
        乙 = 任务数据库(os.path.join(tempfile.mkdtemp(), "b.db"))
        甲.记录日志("r1", "甲", 1.0)
        self.assertIsNone(乙.读取最后日志("r1"))


class 日志模型测试(unittest.TestCase):
    def test_级别与重点判断(self):
        self.assertEqual(推断级别("[错误] x"), "错误")
        self.assertEqual(推断级别("资源不足"), "警告")
        self.assertEqual(推断级别("普通"), "正常")
        self.assertTrue(是否重点("[12:00:00] 进攻完成", "正常"))
        self.assertFalse(是否重点("页面识别：页面=主世界", "正常"))

    def test_连续重复折叠(self):
        条目 = [日志条目(100 + 序号, "r1", "[10:00:00] 等待回营") for 序号 in range(3)]
        结果 = 合并连续重复(条目)
        self.assertEqual(len(结果), 1)
        self.assertEqual(结果[0].重复次数, 3)
        self.assertEqual(结果[0].内容, "等待回营")

    def test_聚合器合并实时与历史并去重(self):
        队列 = queue.Queue()
        历史 = [SimpleNamespace(记录时间=100.0, 日志内容="进攻完成")]
        聚合器 = 日志聚合器(队列, 读取历史=lambda _标志, _起始: 历史, 获取机器人列表=lambda: ["r1"])
        队列.put({"内容": "[10:00:00] 进攻完成", "机器人ID": "r1", "记录时间": 100.0})
        队列.put({"内容": "资源不足，跳过", "机器人ID": "r1", "级别": "警告", "记录时间": 101.0})
        self.assertTrue(聚合器.消费实时队列())
        self.assertTrue(聚合器.同步历史())
        结果 = 聚合器.渲染("全部")
        self.assertEqual(结果.总数量, 2)
        self.assertEqual(结果.异常数量, 1)
        self.assertEqual(len(聚合器.渲染("异常").条目), 1)

    def test_清空只隐藏显示(self):
        聚合器 = 日志聚合器(None)
        聚合器.记录操作("旧操作")
        聚合器.清空显示()
        time.sleep(0.01)
        聚合器.记录操作("新操作")
        self.assertEqual([项.内容 for 项 in 聚合器.渲染("全部").条目], ["[操作] 新操作"])

    def test_按机器人筛选保留系统消息(self):
        队列 = queue.Queue()
        聚合器 = 日志聚合器(队列)
        for 标志 in ("r1", "r2"):
            队列.put({"内容": f"{标志} 启动", "机器人ID": 标志, "记录时间": time.time()})
        聚合器.消费实时队列()
        聚合器.记录操作("保存设置")
        内容 = [项.机器人ID for 项 in 聚合器.渲染("全部", "r1").条目]
        self.assertEqual(sorted(内容), ["r1", "系统"])

    def test_实时队列每次有上限(self):
        队列 = queue.Queue()
        for 序号 in range(50):
            队列.put({"内容": str(序号), "机器人ID": "r1"})
        聚合器 = 日志聚合器(队列)
        聚合器.消费实时队列(上限=10)
        self.assertEqual(队列.qsize(), 40)


class MAA日志样式测试(unittest.TestCase):
    def test_展示级别与文本(self):
        from 应用.日志模型 import 展示文本, 展示级别

        self.assertEqual(展示级别("完成任务：刷墙"), "成功")
        self.assertEqual(展示级别("[警告] 任务未完成：刷墙"), "警告")
        self.assertEqual(展示级别("[错误] 模拟器中没有安装部落冲突"), "错误")
        self.assertEqual(展示级别("[操作] 开始"), "次要")
        self.assertEqual(展示级别("开始任务：刷墙"), "正常")
        self.assertEqual(展示文本("[12:00:00] [警告] 资源不足"), "资源不足")
        self.assertEqual(展示文本("[操作] 开始"), "开始")

    def test_任务开始结束属于重点日志(self):
        self.assertTrue(是否重点("开始任务：主世界刷资源"))
        self.assertTrue(是否重点("完成任务：启动游戏"))


class 任务计划模型测试(unittest.TestCase):
    def test_数值字段校验范围并拒绝非法值(self):
        字段 = 计划.参数字段("x", "资源边缘比例", "float", 最小值=0, 最大值=1)
        self.assertEqual(字段.解析(" 0.5 "), 0.5)
        for 非法 in ("1.5", "-1", "abc", ""):
            with self.assertRaises(ValueError):
                字段.解析(非法)
        self.assertEqual(计划.参数字段("x", "金币", "int").解析("1,000,000"), 1_000_000)

    def test_列表字段支持多种分隔符(self):
        字段 = 计划.参数字段("x", "目标", "list")
        self.assertEqual(字段.解析("弓箭塔、加农炮,迫击炮\n法师塔；"), ["弓箭塔", "加农炮", "迫击炮", "法师塔"])

    def test_应用参数全部校验通过才写入(self):
        设置 = 机器人设置()
        原值 = 设置.欲进攻的最小资源
        with self.assertRaises(ValueError):
            计划.应用参数(设置, "main_resource", {
                "欲进攻的最小资源": "999", "欲进攻资源建筑靠近地图边缘最小比例": "9",
            })
        self.assertEqual(设置.欲进攻的最小资源, 原值)
        计划.应用参数(设置, "main_resource", {"欲进攻的最小资源": "999"})
        self.assertEqual(设置.欲进攻的最小资源, 999)

    def test_每个参数字段都存在于机器人设置(self):
        已知 = set(机器人设置.__dataclass_fields__)
        for 字段 in 计划.所有参数字段():
            self.assertIn(字段.字段, 已知)

    def test_关闭目标类任务会清空目标且移动顺序(self):
        设置 = 机器人设置()
        设置.欲升级的英雄或建筑 = ["弓箭塔"]
        计划.设置任务开关(设置, "hero", False)
        self.assertEqual(设置.欲升级的英雄或建筑, [])
        计划.设置任务开关(设置, "wall", True)
        self.assertTrue(设置.开启刷墙)
        self.assertTrue(计划.移动任务(设置, "wall", -1))
        self.assertLess(设置.任务计划顺序.index("wall"), 设置.任务计划顺序.index("night_resource"))
        self.assertFalse(计划.移动任务(设置, 设置.任务计划顺序[0], -1))


class 控制器测试(unittest.TestCase):
    def setUp(self):
        self.数据库 = 任务数据库(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.池 = {}

        def 创建机器人(机器人标志, 初始设置=None):
            self.池[机器人标志] = SimpleNamespace(
                机器人标志=机器人标志, 当前状态="已停止", 停止原因="未启动",
                停止=mock.Mock(), 暂停=mock.Mock(), 继续=mock.Mock(),
            )

        self.监控中心 = SimpleNamespace(
            机器人池=self.池, 数据库=self.数据库, 创建机器人=创建机器人,
            启动机器人=mock.Mock(), 关闭=mock.Mock(),
        )
        self.控制器 = 应用控制器(self.监控中心)

    def test_没有配置时创建唯一默认实例(self):
        self.assertEqual(self.控制器.准备(), "robot_1")
        self.assertEqual(list(self.池), ["robot_1"])
        self.assertEqual(list(self.数据库.查询所有机器人设置()), ["robot_1"])

    def test_旧版多份配置时选最近运行过的那份且不删除其它(self):
        from 应用.控制器 import 选择主实例ID

        for 标志 in ("robot_1", "小号", "主号"):
            self.数据库.保存机器人设置(标志, 机器人设置())
        self.assertEqual(选择主实例ID(self.数据库), "robot_1")
        self.数据库.记录日志("小号", "旧日志", 0)
        self.数据库.记录日志("主号", "新日志", 0)
        self.assertEqual(self.控制器.准备(), "主号")
        self.assertEqual(list(self.池), ["主号"])
        self.assertEqual(len(self.数据库.查询所有机器人设置()), 3)

    def test_没有日志时按名称选择(self):
        from 应用.控制器 import 选择主实例ID

        for 标志 in ("b", "a"):
            self.数据库.保存机器人设置(标志, 机器人设置())
        self.assertEqual(选择主实例ID(self.数据库), "a")

    def test_快照包含已选任务与设备状态(self):
        self.控制器.准备()
        设置 = self.控制器.获取设置()
        设置.是否刷主世界 = True
        设置.ADB设备序列号 = "emulator-5554"
        设置.ADB已确认模拟器 = True
        self.控制器.保存设置(设置)
        self.数据库.记录日志("robot_1", "进攻完成", 0)
        快照 = self.控制器.快照()
        self.assertIn("主世界刷资源", 快照.已选任务)
        self.assertEqual(快照.设备描述, "已确认 · emulator-5554")
        self.assertEqual(快照.最近日志, "进攻完成")
        self.assertEqual(快照.状态, "已停止")

    def test_未准备时不能开始(self):
        with self.assertRaises(RuntimeError):
            self.控制器.启动()
        self.assertFalse(self.控制器.开始或继续())


if __name__ == "__main__":
    unittest.main()
