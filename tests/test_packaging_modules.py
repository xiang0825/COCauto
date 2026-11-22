"""确保延迟导入的世界切换任务不会从 Windows 打包版中消失。"""

import tempfile
import unittest
from pathlib import Path

from scripts import verify_packaged_modules

from PyInstaller.utils.hooks import collect_submodules


class 打包模块测试(unittest.TestCase):
    def test_世界切换任务都被自动收集(self):
        模块 = set(collect_submodules("任务流程"))
        self.assertIn("任务流程.世界跳转.到主世界任务", 模块)
        self.assertIn("任务流程.世界跳转.到夜世界任务", 模块)

    def test_手机控制服务的延迟模块会被自动收集(self):
        模块 = set(collect_submodules("服务"))
        self.assertIn("服务.局域网控制服务", 模块)
        self.assertIn("服务.桌面手机控制桥", 模块)

    def test_机器人主线程是必需的打包模块(self):
        with tempfile.TemporaryDirectory(prefix="coc-package-entry-") as 临时目录:
            入口源码 = Path(临时目录) / "自动化机器人.py"
            入口源码.write_text("value = 1\n", encoding="utf-8")
            获取必需模块 = getattr(
                verify_packaged_modules,
                "所需打包模块",
                None,
            )
            self.assertTrue(callable(获取必需模块), "发布校验器还没有声明必需入口模块")
            self.assertEqual(
                获取必需模块(入口源码),
                {
                    "线程.自动化机器人",
                    "服务.局域网控制服务",
                    "服务.桌面手机控制桥",
                    "界面.手机控制面板",
                },
            )

    def test_缺失启动入口或运行时钩子会被报告(self):
        检查缺失 = getattr(
            verify_packaged_modules,
            "缺失入口脚本",
            None,
        )
        self.assertTrue(callable(检查缺失), "发布校验器还没有检查必需的启动脚本")
        self.assertEqual(检查缺失({"UI入口"}), {"打包运行时"})
        self.assertEqual(检查缺失({"UI入口", "打包运行时"}), set())

    def test_代码签名忽略源码路径但识别行为变化(self):
        签名 = getattr(verify_packaged_modules, "计算代码签名", None)
        self.assertTrue(callable(签名), "发布校验器还没有代码签名功能")
        第一份 = compile("def 运行(x):\n    return x + 1\n", "旧路径.py", "exec")
        同代码不同路径 = compile("def 运行(x):\n    return x + 1\n", "新路径.py", "exec")
        改过的代码 = compile("def 运行(x):\n    return x + 2\n", "旧路径.py", "exec")

        self.assertEqual(签名(第一份), 签名(同代码不同路径))
        self.assertNotEqual(签名(第一份), 签名(改过的代码))

    def test_模块名能解析到普通模块和包入口源码(self):
        with tempfile.TemporaryDirectory(prefix="coc-package-source-") as 临时目录:
            根目录 = Path(临时目录)
            普通模块 = 根目录 / "pkg" / "task.py"
            包入口 = 根目录 / "pkg" / "nested" / "__init__.py"
            普通模块.parent.mkdir(parents=True)
            普通模块.write_text("value = 1\n", encoding="utf-8")
            包入口.parent.mkdir()
            包入口.write_text("value = 2\n", encoding="utf-8")

            解析路径 = getattr(
                verify_packaged_modules,
                "解析源码模块路径",
                None,
            )
            self.assertTrue(callable(解析路径), "发布校验器还没有源码路径解析")
            self.assertEqual(
                解析路径(根目录, "pkg.task"),
                普通模块,
            )
            self.assertEqual(
                解析路径(根目录, "pkg.nested"),
                包入口,
            )

    def test_源码包内模块包含非延迟导入的机器人入口(self):
        with tempfile.TemporaryDirectory(prefix="coc-package-source-") as 临时目录:
            根目录 = Path(临时目录)
            入口 = 根目录 / "线程" / "自动化机器人.py"
            任务 = 根目录 / "任务流程" / "基础任务框架.py"
            入口.parent.mkdir(parents=True)
            入口.write_text("value = 1\n", encoding="utf-8")
            任务.parent.mkdir(parents=True)
            任务.write_text("value = 2\n", encoding="utf-8")

            获取项目模块 = getattr(
                verify_packaged_modules,
                "项目源码包内模块",
                None,
            )
            self.assertTrue(callable(获取项目模块), "发布校验器还没有扫描项目源码模块")
            self.assertEqual(
                获取项目模块(
                    根目录,
                    {
                        "线程.自动化机器人",
                        "任务流程.基础任务框架",
                        "numpy.core",
                    },
                ),
                {"线程.自动化机器人", "任务流程.基础任务框架"},
            )

    def test_启动脚本和运行时钩子也纳入源码一致性检查(self):
        with tempfile.TemporaryDirectory(prefix="coc-package-source-") as 临时目录:
            根目录 = Path(临时目录)
            for 相对路径 in (
                "线程/自动化机器人.py",
                "UI入口.py",
                "打包运行时.py",
            ):
                源码 = 根目录 / 相对路径
                源码.parent.mkdir(parents=True, exist_ok=True)
                源码.write_text("value = 1\n", encoding="utf-8")

            获取归档模块 = getattr(
                verify_packaged_modules,
                "项目归档源码模块",
                None,
            )
            self.assertTrue(callable(获取归档模块), "发布校验器还没有检查启动归档代码")
            self.assertEqual(
                获取归档模块(
                    根目录,
                    {"线程.自动化机器人", "numpy.core"},
                    {"UI入口", "打包运行时", "pyi_rth_inspect"},
                ),
                {"线程.自动化机器人", "UI入口", "打包运行时"},
            )

    def test_打包模块代码必须和当前源码一致(self):
        with tempfile.TemporaryDirectory(prefix="coc-package-source-") as 临时目录:
            源码 = Path(临时目录) / "task.py"
            源码.write_text("def 运行():\n    return 'current'\n", encoding="utf-8")
            打包代码 = compile(
                "def 运行():\n    return 'current'\n",
                "task.py",
                "exec",
            )
            旧打包代码 = compile(
                "def 运行():\n    return 'old'\n",
                "task.py",
                "exec",
            )

            源码匹配 = getattr(verify_packaged_modules, "模块源码匹配", None)
            self.assertTrue(callable(源码匹配), "发布校验器还没有源码一致性检查")
            self.assertTrue(源码匹配(源码, 打包代码))
            self.assertFalse(源码匹配(源码, 旧打包代码))

    def test_从_internal运行时dll读取python版本(self):
        with tempfile.TemporaryDirectory(prefix="coc-package-runtime-") as 临时目录:
            发布目录 = Path(临时目录)
            内部目录 = 发布目录 / "_internal"
            内部目录.mkdir()
            (内部目录 / "python312.dll").write_bytes(b"runtime")
            exe = 发布目录 / "部落冲突.exe"
            exe.write_bytes(b"placeholder")

            读取版本 = getattr(verify_packaged_modules, "读取包内Python版本", None)
            self.assertTrue(callable(读取版本), "发布校验器还没有运行时版本检查")
            self.assertEqual(
                读取版本(exe),
                (3, 12),
            )

            校验版本 = getattr(verify_packaged_modules, "校验解释器版本", None)
            self.assertTrue(callable(校验版本), "发布校验器还没有解释器版本匹配检查")
            self.assertFalse(校验版本(exe, (3, 11))[0])
            self.assertTrue(校验版本(exe, (3, 12))[0])


if __name__ == "__main__":
    unittest.main()
