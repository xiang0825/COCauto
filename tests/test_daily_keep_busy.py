"""D. 实验室和工人不闲（keep_busy）：优先级研究、工人段、冷却与注册。"""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from 任务流程.日常 import 日常公共
from 任务流程.日常.保持不闲 import 保持不闲任务, 规范目标列表
from 数据库.任务数据库 import 任务计划定义映射, 机器人设置, 规范化任务计划顺序


class 假数据库:
    def __init__(self):
        self.状态 = {}

    def 获取最新完整状态(self, 标志):
        return SimpleNamespace(状态数据=dict(self.状态))

    def 更新状态(self, 标志, 类型, 数据):
        self.状态[类型] = 数据


def 构造上下文(**设置项):
    设置 = 机器人设置(**设置项)
    return SimpleNamespace(
        机器人标志="测试", 数据库=假数据库(), 设置=设置,
        置脚本状态=Mock(), 页面恢复失败=False,
        停止事件=SimpleNamespace(is_set=lambda: False),
        任务计划等待秒=5.0,
    )


def 构造任务(上下文, 面板结果=True, 目标结果=None, 确认结果=None):
    """目标结果/确认结果：{目标: (成功, 失败原因)} / {目标: 成功}。"""
    目标结果 = 目标结果 or {}
    确认结果 = 确认结果 or {}
    记录 = {"面板": 0, "目标": [], "确认": []}

    class 面板:
        def __init__(self, 上下文):
            pass

        def 执行(self):
            记录["面板"] += 1
            return 面板结果

    class 目标:
        def __init__(self, 上下文, 名称):
            self.名称 = 名称
            self.失败原因 = None

        def 执行(self):
            记录["目标"].append(self.名称)
            成功, 原因 = 目标结果.get(self.名称, (True, None))
            self.失败原因 = 原因
            return 成功


    class 确认:
        def __init__(self, 上下文):
            pass

        def 执行(self):
            名称 = 记录["目标"][-1]
            记录["确认"].append(名称)
            return 确认结果.get(名称, True)

    任务 = 保持不闲任务.__new__(保持不闲任务)
    任务.上下文 = 上下文
    任务.数据库 = 上下文.数据库
    任务.机器人标志 = 上下文.机器人标志
    任务.本轮已提交研究 = None
    任务.研究面板任务类, 任务.目标任务类, 任务.确认任务类 = 面板, 目标, 确认
    return 任务, 记录


class 研究优先级测试(unittest.TestCase):
    def test_未配置研究优先级时跳过且不打开面板(self):
        上下文 = 构造上下文()
        任务, 记录 = 构造任务(上下文)
        self.assertTrue(任务.执行研究段())
        self.assertEqual(记录["面板"], 0)

    def test_资源不足时试下一个直到提交成功(self):
        上下文 = 构造上下文(不闲研究优先级=["雷电法术", "气球兵", "飞龙"])
        任务, 记录 = 构造任务(上下文, 目标结果={"雷电法术": (False, "资源不足")})
        self.assertTrue(任务.执行研究段())
        self.assertEqual(记录["目标"], ["雷电法术", "气球兵"])
        self.assertEqual(记录["确认"], ["气球兵"])
        self.assertEqual(任务.本轮已提交研究, "气球兵")

    def test_确认页资源不足也试下一个(self):
        上下文 = 构造上下文(不闲研究优先级=["雷电法术", "气球兵"])
        任务, 记录 = 构造任务(上下文, 确认结果={"雷电法术": False})
        self.assertTrue(任务.执行研究段())
        self.assertEqual(记录["确认"], ["雷电法术", "气球兵"])
        self.assertEqual(任务.本轮已提交研究, "气球兵")

    def test_实验室忙时整段停止(self):
        上下文 = 构造上下文(不闲研究优先级=["雷电法术", "气球兵"])
        任务, 记录 = 构造任务(上下文, 目标结果={"雷电法术": (False, "实验室忙")})
        self.assertTrue(任务.执行研究段())
        self.assertEqual(记录["目标"], ["雷电法术"])
        self.assertEqual(记录["确认"], [])

    def test_研究面板打不开时安全跳过(self):
        上下文 = 构造上下文(不闲研究优先级=["雷电法术", "气球兵"])
        任务, 记录 = 构造任务(上下文, 面板结果=False)
        self.assertTrue(任务.执行研究段())
        self.assertEqual(记录["面板"], 1)
        self.assertEqual(记录["目标"], [])

    def test_点击异常时返回失败且不继续(self):
        上下文 = 构造上下文(不闲研究优先级=["雷电法术", "气球兵"])
        任务, 记录 = 构造任务(上下文, 目标结果={"雷电法术": (False, "点击失败")})
        self.assertFalse(任务.执行研究段())
        self.assertEqual(记录["目标"], ["雷电法术"])

    def test_页面恢复失败时返回失败(self):
        上下文 = 构造上下文(不闲研究优先级=["雷电法术", "气球兵"])
        任务, 记录 = 构造任务(上下文, 目标结果={"雷电法术": (False, "资源不足")})
        原执行 = 任务.目标任务类.执行

        def 执行并标记(self_):
            上下文.页面恢复失败 = True
            return 原执行(self_)

        任务.目标任务类.执行 = 执行并标记
        self.assertFalse(任务.执行研究段())

    def test_全部不可用时返回成功不提交(self):
        上下文 = 构造上下文(不闲研究优先级=["雷电法术", "气球兵"])
        任务, 记录 = 构造任务(上下文, 目标结果={
            "雷电法术": (False, "未找到"), "气球兵": (False, "资源不足"),
        })
        self.assertTrue(任务.执行研究段())
        self.assertIsNone(任务.本轮已提交研究)


class 工人段测试(unittest.TestCase):
    def test_使用不闲优先级覆盖且不改设置(self):
        上下文 = 构造上下文(不闲建筑优先级=["弓箭女皇", "加农炮"], 不闲建筑使用建议兜底=False,
                       欲升级的英雄或建筑=["野蛮人之王"])
        调用 = {}

        class 假建筑任务:
            def __init__(self, 上下文, 指定建筑覆盖=None, 启用建议覆盖=None):
                调用.update(指定=指定建筑覆盖, 建议=启用建议覆盖)

            def 执行(self):
                return True

        任务, _ = 构造任务(上下文)
        任务.建筑任务类 = 假建筑任务
        上下文._建筑英雄升级本轮已执行 = True
        self.assertTrue(任务.执行工人段())
        self.assertEqual(调用, {"指定": ["弓箭女皇", "加农炮"], "建议": False})
        self.assertFalse(上下文._建筑英雄升级本轮已执行)
        self.assertEqual(上下文.设置.欲升级的英雄或建筑, ["野蛮人之王"])

    def test_无优先级且关闭兜底时跳过(self):
        上下文 = 构造上下文(不闲建筑使用建议兜底=False)
        任务, _ = 构造任务(上下文)
        任务.建筑任务类 = Mock(side_effect=AssertionError("不应调用"))
        self.assertTrue(任务.执行工人段())

    def test_建筑任务失败如实返回(self):
        上下文 = 构造上下文()
        任务, _ = 构造任务(上下文)
        任务.建筑任务类 = lambda *a, **k: SimpleNamespace(执行=lambda: False)
        self.assertFalse(任务.执行工人段())


class 建筑任务覆盖参数测试(unittest.TestCase):
    def test_覆盖参数生效(self):
        from 任务流程.建筑升级 import 建筑升级任务

        上下文 = 构造上下文(欲升级的英雄或建筑=[], 是否升级建议升级的建筑=False)
        上下文.获取模板识别器 = lambda: None
        任务 = 建筑升级任务(上下文, 指定建筑覆盖=["加农炮"], 启用建议覆盖=True)
        self.assertEqual(任务._指定建筑覆盖, ["加农炮"])
        self.assertTrue(任务._启用建议覆盖)
        默认 = 建筑升级任务(上下文)
        self.assertIsNone(默认._指定建筑覆盖)
        self.assertIsNone(默认._启用建议覆盖)


class 冷却测试(unittest.TestCase):
    def test_完成后记录冷却并在冷却中跳过(self):
        上下文 = 构造上下文(不闲检查间隔分钟=30)
        上下文.请求任务计划等待 = Mock()
        任务, 记录 = 构造任务(上下文)
        self.assertFalse(任务.冷却中())
        任务.记录完成()
        self.assertTrue(任务.冷却中())
        秒数 = 上下文.请求任务计划等待.call_args_list[-1].args[0]
        self.assertGreater(秒数, 1700)
        self.assertLessEqual(秒数, 1800)

    def test_执行入口冷却中不点击(self):
        上下文 = 构造上下文(不闲研究优先级=["雷电法术"])
        日常公共.写入任务记录(上下文.数据库, "测试", "keep_busy", {"下次检查时间": time.time() + 600})
        任务, 记录 = 构造任务(上下文)
        self.assertTrue(任务.执行())
        self.assertEqual(记录["面板"], 0)


class 注册与设置测试(unittest.TestCase):
    def test_默认关闭且已注册(self):
        设置 = 机器人设置()
        self.assertFalse(设置.是否保持实验室工人不闲)
        self.assertIn("keep_busy", 任务计划定义映射)
        self.assertIn("keep_busy", 规范化任务计划顺序(["main_resource"]))

    def test_优先级列表清洗与间隔夹取(self):
        设置 = 机器人设置(不闲研究优先级=[" 雷电法术", "雷电法术", "", "气球兵"],
                    不闲建筑优先级="坏值", 不闲检查间隔分钟=1)
        self.assertEqual(设置.不闲研究优先级, ["雷电法术", "气球兵"])
        self.assertEqual(设置.不闲建筑优先级, [])
        self.assertEqual(设置.不闲检查间隔分钟, 10)

    def test_参数页可解析优先级顺序(self):
        from 应用 import 任务计划 as 计划

        设置 = 机器人设置()
        计划.应用参数(设置, "keep_busy", {"不闲研究优先级": "飞龙，雷电法术\n气球兵", "不闲检查间隔分钟": "45"})
        self.assertEqual(设置.不闲研究优先级, ["飞龙", "雷电法术", "气球兵"])
        self.assertEqual(设置.不闲检查间隔分钟, 45)

    def test_规范目标列表(self):
        self.assertEqual(规范目标列表("雷电法术"), ["雷电法术"])
        self.assertEqual(规范目标列表(["a", "a", " ", "b"]), ["a", "b"])


class 研究目标失败原因测试(unittest.TestCase):
    def test_研究中设置实验室忙(self):
        from 任务流程.兵种或法术升级.打开要升级的兵种或法术 import 打开要升级的兵种或法术任务

        任务 = 打开要升级的兵种或法术任务.__new__(打开要升级的兵种或法术任务)
        任务.欲升级的兵种或法术 = "雷电法术"
        任务.失败原因 = None
        任务.上下文 = SimpleNamespace(置脚本状态=Mock(), 点击=Mock(return_value=True), 脚本延时=Mock())
        任务.执行OCR识别 = Mock(return_value=[([[0, 0], [1, 0], [1, 1], [0, 1]], "升级中", 0.9)])
        self.assertFalse(任务.执行())
        self.assertEqual(任务.失败原因, "实验室忙")

    def test_未定位目标设置未找到(self):
        from 任务流程.兵种或法术升级.打开要升级的兵种或法术 import 打开要升级的兵种或法术任务

        任务 = 打开要升级的兵种或法术任务.__new__(打开要升级的兵种或法术任务)
        任务.欲升级的兵种或法术 = "雷电法术"
        任务.失败原因 = None
        任务.上下文 = SimpleNamespace(置脚本状态=Mock(), 点击=Mock(return_value=True), 脚本延时=Mock())
        任务.执行OCR识别 = Mock(return_value=[])
        self.assertFalse(任务.尝试点击目标兵种或法术())
        self.assertEqual(任务.失败原因, "未找到")


class 日常公共测试(unittest.TestCase):
    def test_JSON覆盖与类型校验(self):
        with tempfile.TemporaryDirectory() as 目录:
            路径 = Path(目录) / "x.json"
            路径.write_text('{"calibrated": true, "次数": "坏", "区域": [1,2,3,4], "_注释": 1}', encoding="utf-8")
            参数 = 日常公共.加载日常参数("x", {"calibrated": False, "次数": 3, "区域": [0, 0, 1, 1]}, 路径)
        self.assertTrue(日常公共.已校准(参数))
        self.assertEqual(参数["次数"], 3)
        self.assertEqual(参数["区域"], [1, 2, 3, 4])
        self.assertNotIn("_注释", 参数)

    def test_缺文件用默认值且未校准(self):
        参数 = 日常公共.加载日常参数("不存在的文件xyz", {"calibrated": False})
        self.assertFalse(日常公共.已校准(参数))

    def test_危险词(self):
        for 文本 in ("花费50宝石", "立即完成", "購買", "跳过", "重置", "加速建筑"):
            self.assertTrue(日常公共.含危险词(文本), 文本)
        for 文本 in ("捐献", "增援", "立即寻找", "进攻"):
            self.assertFalse(日常公共.含危险词(文本), 文本)

    def test_今日记录跨日清零(self):
        数据库 = 假数据库()
        日常公共.写入任务记录(数据库, "t", "k", {"日期": "2000-01-01", "次数": 3, "下次检查时间": 9})
        记录 = 日常公共.今日记录(数据库, "t", "k")
        self.assertNotIn("次数", 记录)
        self.assertEqual(记录["下次检查时间"], 9)


if __name__ == "__main__":
    unittest.main()
