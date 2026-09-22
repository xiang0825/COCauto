import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from 模块.检测.模板匹配器 import 模板匹配引擎


class 模板资源路径测试(unittest.TestCase):
    def test_打包目录缺失图片时回退到exe旁_internal(self):
        with tempfile.TemporaryDirectory() as 临时目录:
            根目录 = Path(临时目录)
            解包目录 = 根目录 / "旧解包目录"
            程序目录 = 根目录 / "程序"
            (程序目录 / "_internal" / "img").mkdir(parents=True)

            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "_MEIPASS", str(解包目录), create=True), \
                 patch.object(sys, "executable", str(程序目录 / "部落冲突.exe")):
                引擎 = object.__new__(模板匹配引擎)
                self.assertEqual(
                    引擎.获取资源目录(),
                    (程序目录 / "_internal").resolve(),
                )

    def test_源码运行不依赖当前工作目录(self):
        引擎 = object.__new__(模板匹配引擎)
        资源目录 = 引擎.获取资源目录()
        self.assertTrue((资源目录 / "img").is_dir())


if __name__ == "__main__":
    unittest.main()
