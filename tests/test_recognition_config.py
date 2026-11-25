"""识别参数配置化：JSON 与代码默认值一致、查找顺序、类型校验、打包校验。"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from 工具包 import 识别参数 as 模块
from 工具包.识别参数 import 应用识别参数, 转换为默认类型

根 = Path(__file__).resolve().parents[1]


def _生成器():
    规格 = importlib.util.spec_from_file_location("生成识别参数", 根 / "scripts" / "生成识别参数.py")
    生成器 = importlib.util.module_from_spec(规格)
    规格.loader.exec_module(生成器)
    return 生成器


class JSON与代码默认值一致测试(unittest.TestCase):
    def test_四个参数文件都存在且值与代码默认值完全一致(self):
        生成器 = _生成器()
        期望 = 生成器.生成()
        self.assertEqual(sorted(期望), ["主页", "弹窗", "搜敌", "结算"])
        for 名称, 内容 in 期望.items():
            文件 = 根 / "资源" / "识别" / f"{名称}.json"
            self.assertTrue(文件.is_file(), 文件)
            self.assertEqual(json.loads(文件.read_text(encoding="utf-8")), 内容, 名称)

    def test_运行时类属性等于代码默认值(self):
        from 任务流程.主世界打鱼.搜索敌人 import 搜索目标敌人任务
        from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务
        from 模块.检测.页面识别器 import 页面识别器

        self.assertEqual(搜索目标敌人任务.资源易窃取最低评分, 5.0)
        self.assertEqual(搜索目标敌人任务.资源建筑类别, ("金矿", "金库", "圣水采集器", "圣水瓶"))
        self.assertIsInstance(搜索目标敌人任务.敌方单场金币上限, int)
        self.assertEqual(页面识别器.结算区域, (0, 350, 800, 600))
        self.assertEqual(等待战斗结束并回营任务.回营模板,
                         "回营1.bmp|回营.bmp|回营2.bmp|回营3.bmp|领取奖励.bmp|回营_领取奖励.bmp")
        for 类 in (搜索目标敌人任务, 等待战斗结束并回营任务, 页面识别器):
            默认 = 类._识别参数默认值
            for 键, 值 in 默认.items():
                if 键 != "_类":
                    self.assertEqual(getattr(类, 键), 值, f"{类.__name__}.{键}")
                    self.assertIs(type(getattr(类, 键)), type(值), f"{类.__name__}.{键}")

    def test_参数文件没有未知键(self):
        for 文件 in sorted((根 / "资源" / "识别").glob("*.json")):
            内容 = json.loads(文件.read_text(encoding="utf-8"))
            for 节, 参数 in 内容.items():
                if 节 == "说明":
                    continue
                self.assertIsInstance(参数, dict)
        正式文件 = ("主页.json", "搜敌.json", "结算.json", "弹窗.json")
        self.assertFalse([
            文本 for 文本 in 模块.问题记录
            if any(名 in 文本 for 名 in 正式文件) and ("不是已知参数" in 文本 or "类型" in 文本)
        ])

    def test_弹窗关键词仍按原逻辑工作(self):
        from 任务流程.基础任务框架 import 任务上下文

        活动 = [([[0, 0], [1, 0], [1, 1], [0, 1]], "活動"), ([[0, 0], [1, 0], [1, 1], [0, 1]], "剩餘時間 2天")]
        self.assertTrue(任务上下文._OCR确认主世界活动弹窗(活动))
        self.assertFalse(任务上下文._OCR确认主世界活动弹窗(活动[:1]))
        评分 = [
            ([[0, 100], [10, 100], [10, 110], [0, 110]], "喜欢部落衝突吗"),
            ([[0, 120], [10, 120], [10, 130], [0, 130]], "GooglePlay"),
            ([[300, 400], [340, 400], [340, 420], [300, 420]], "稍後"),
        ]
        self.assertEqual(任务上下文._定位官方评分弹窗稍后按钮(评分), (320, 410))
        评分[2] = ([[300, 200], [340, 200], [340, 220], [300, 220]], "稍後")
        self.assertIsNone(任务上下文._定位官方评分弹窗稍后按钮(评分))


class 覆盖与类型测试(unittest.TestCase):
    def setUp(self):
        模块.清空缓存()
        self.addCleanup(模块.清空缓存)
        self.目录 = Path(tempfile.mkdtemp(prefix="coc-recog-"))

    def _类(self):
        class 示例:
            阈值 = 0.80
            次数 = 3
            区域 = (0, 350, 800, 600)
            模板 = "a.bmp|b.bmp"
            权重 = {"金矿": 1.0}
        return 示例

    def _写(self, 内容):
        文件 = self.目录 / "资源" / "识别" / "示例.json"
        文件.parent.mkdir(parents=True, exist_ok=True)
        文件.write_text(json.dumps(内容, ensure_ascii=False), encoding="utf-8")
        return 文件

    def test_JSON覆盖并按默认类型转换(self):
        类 = self._类()
        文件 = self._写({"示例": {"阈值": 0.85, "次数": 4, "区域": [1, 2, 3, 4], "模板": "c.bmp", "权重": {"金矿": 2.0}}})
        已应用 = 应用识别参数(类, "示例", 路径=文件)
        self.assertEqual(len(已应用), 5)
        self.assertEqual(类.区域, (1, 2, 3, 4))
        self.assertIsInstance(类.区域, tuple)
        self.assertEqual(类.次数, 4)
        self.assertEqual(类.阈值, 0.85)

    def test_类型不符和未知键忽略保留默认(self):
        类 = self._类()
        文件 = self._写({"示例": {"次数": 2.5, "区域": "x", "阈值": "高", "不存在": 1}})
        self.assertEqual(应用识别参数(类, "示例", 路径=文件), {})
        self.assertEqual((类.次数, 类.区域, 类.阈值), (3, (0, 350, 800, 600), 0.80))

    def test_缺文件或坏JSON保留默认(self):
        类 = self._类()
        self.assertEqual(应用识别参数(类, "示例", 路径=self.目录 / "无.json"), {})
        坏 = self.目录 / "坏.json"
        坏.write_text("{不是json", encoding="utf-8")
        模块.清空缓存()
        self.assertEqual(应用识别参数(类, "示例", 路径=坏), {})
        self.assertEqual(类.阈值, 0.80)

    def test_打包后EXE同级目录优先于internal(self):
        exe目录 = self.目录 / "app"
        (exe目录 / "_internal" / "资源" / "识别").mkdir(parents=True)
        (exe目录 / "资源" / "识别").mkdir(parents=True)
        (exe目录 / "_internal" / "资源" / "识别" / "主页.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", str(exe目录 / "部落冲突.exe")), \
                mock.patch.object(sys, "_MEIPASS", str(exe目录 / "_internal"), create=True):
            self.assertEqual(模块.查找参数文件("主页"), (exe目录 / "_internal" / "资源" / "识别" / "主页.json").resolve())
            (exe目录 / "资源" / "识别" / "主页.json").write_text("{}", encoding="utf-8")
            self.assertEqual(模块.查找参数文件("主页"), (exe目录 / "资源" / "识别" / "主页.json").resolve())

    def test_类型转换细节(self):
        self.assertEqual(转换为默认类型(5, 6.0), (True, 6))
        self.assertEqual(转换为默认类型(5, True), (False, None))
        self.assertEqual(转换为默认类型(0.5, 1), (True, 1.0))
        self.assertEqual(转换为默认类型(((1, 2),), [[3, 4]]), (True, ((3, 4),)))


class 打包校验测试(unittest.TestCase):
    def test_发布包缺少或不一致的识别参数会被发现(self):
        from scripts import verify_packaged_modules as 校验

        临时 = Path(tempfile.mkdtemp(prefix="coc-recog-pkg-"))
        exe = 临时 / "部落冲突.exe"
        问题 = 校验.校验识别参数文件(exe, 根)
        self.assertEqual(len(问题), 4)
        目标 = 临时 / "_internal" / "资源" / "识别"
        目标.mkdir(parents=True)
        for 文件 in (根 / "资源" / "识别").glob("*.json"):
            (目标 / 文件.name).write_bytes(文件.read_bytes())
        self.assertEqual(校验.校验识别参数文件(exe, 根), [])
        (目标 / "结算.json").write_text("{}", encoding="utf-8")
        self.assertEqual(len(校验.校验识别参数文件(exe, 根)), 1)

    def test_spec收集资源目录下的json(self):
        文本 = (根 / "自动脚本.spec").read_text(encoding="utf-8")
        self.assertIn('收集数据文件("资源", 扩展名={".json", ".png", ".bmp"})', 文本)


if __name__ == "__main__":
    unittest.main()
