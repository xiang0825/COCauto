"""rc154：启动时停在部落竞赛面板的安全关闭边界。"""

import pathlib
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from 任务流程.基础任务框架 import 任务上下文
from 任务流程.检测游戏登录状态 import 检测游戏登录状态任务
from 模块.检测.模板匹配器 import 模板匹配引擎
from 模块.检测.页面识别器 import 页面识别器

根目录 = pathlib.Path(__file__).resolve().parents[1]
竞赛目录 = 根目录 / "docs" / "实测" / "部落竞赛-2026-11-24"


def 读取截图(路径: pathlib.Path):
    if not 路径.exists():
        return None
    return cv2.imdecode(np.fromfile(str(路径), dtype=np.uint8), cv2.IMREAD_COLOR)


def OCR返回(*文字):
    return Mock(return_value=([([[0, 0], [1, 0], [1, 1], [0, 1]], 字, 0.95) for 字 in 文字], None))


def 页面(名称):
    return SimpleNamespace(页面=名称, 世界="主世界", 可信度=0.97)


def 构造上下文(页面序列, 关闭点=(709, 39), OCR=None, 帧数=None):
    上下文 = 任务上下文.__new__(任务上下文)
    上下文.停止事件 = threading.Event()
    上下文.置脚本状态 = Mock()
    上下文.脚本延时 = Mock()
    上下文.页面恢复失败 = False
    上下文._战斗中 = False
    帧 = np.zeros((600, 800, 3), dtype=np.uint8)
    上下文.op = SimpleNamespace(获取屏幕图像cv=Mock(return_value=帧))
    识别器 = Mock()
    识别器.识别.side_effect = [页面(名) for 名 in 页面序列]
    识别器.定位部落竞赛关闭按钮.return_value = 关闭点
    上下文._点击页面识别器 = 识别器
    上下文.获取OCR引擎 = Mock(return_value=OCR or OCR返回("部落競赛", "你的積分"))
    上下文._存在中央宝石危险模板 = Mock(return_value=(False, ""))
    上下文.点击已确认安全按钮 = Mock(return_value=True)
    return 上下文, 识别器, 帧


class 部落竞赛面板关闭器测试(unittest.TestCase):
    def test_两帧确认后只点一次右上角X并确认离开面板(self):
        上下文, _, 帧 = 构造上下文(["部落竞赛面板", "部落竞赛面板", "主世界主页"])
        self.assertTrue(上下文.清理部落竞赛面板(帧))
        上下文.点击已确认安全按钮.assert_called_once_with(709, 39, 延时=600)
        self.assertFalse(上下文.页面恢复失败)
        # 第一帧来自调用方，第二帧必须重新截图，点击后还要再截图复核。
        self.assertGreaterEqual(上下文.op.获取屏幕图像cv.call_count, 2)

    def test_新帧不再是竞赛面板时不点击(self):
        上下文, _, 帧 = 构造上下文(["部落竞赛面板", "主世界主页"])
        self.assertFalse(上下文.清理部落竞赛面板(帧))
        上下文.点击已确认安全按钮.assert_not_called()
        self.assertFalse(上下文.页面恢复失败)

    def test_危险字样一律不点(self):
        for 词 in ("宝石", "購買", "跳过", "重置", "加速"):
            with self.subTest(词=词):
                上下文, _, 帧 = 构造上下文(
                    ["部落竞赛面板", "部落竞赛面板"],
                    OCR=OCR返回("部落竞赛", f"{词}100"),
                )
                self.assertFalse(上下文.清理部落竞赛面板(帧))
                上下文.点击已确认安全按钮.assert_not_called()
                self.assertTrue(上下文.页面恢复失败)

    def test_中央宝石模板命中不点(self):
        上下文, _, 帧 = 构造上下文(["部落竞赛面板", "部落竞赛面板"])
        上下文._存在中央宝石危险模板 = Mock(return_value=(True, "宝石.bmp"))
        self.assertFalse(上下文.清理部落竞赛面板(帧))
        上下文.点击已确认安全按钮.assert_not_called()
        self.assertTrue(上下文._宝石保护已触发)

    def test_缺少竞赛标题OCR不点(self):
        上下文, _, 帧 = 构造上下文(
            ["部落竞赛面板", "部落竞赛面板"], OCR=OCR返回("活动", "剩余时间")
        )
        self.assertFalse(上下文.清理部落竞赛面板(帧))
        上下文.点击已确认安全按钮.assert_not_called()

    def test_停止事件置位时不点(self):
        上下文, 识别器, 帧 = 构造上下文(["部落竞赛面板", "部落竞赛面板"])
        上下文.停止事件.set()
        self.assertFalse(上下文.清理部落竞赛面板(帧))
        上下文.点击已确认安全按钮.assert_not_called()
        识别器.识别.assert_not_called()

    def test_复核期间停止事件置位也不点(self):
        上下文, _, 帧 = 构造上下文(["部落竞赛面板", "部落竞赛面板"])
        上下文.脚本延时 = Mock(side_effect=lambda *_: 上下文.停止事件.set())
        self.assertFalse(上下文.清理部落竞赛面板(帧))
        上下文.点击已确认安全按钮.assert_not_called()

    def test_两帧关闭点漂移不点(self):
        上下文, 识别器, 帧 = 构造上下文(["部落竞赛面板", "部落竞赛面板"])
        识别器.定位部落竞赛关闭按钮.side_effect = [(709, 39), (600, 300)]
        self.assertFalse(上下文.清理部落竞赛面板(帧))
        上下文.点击已确认安全按钮.assert_not_called()

    def test_部落竞赛流程自身操作面板时不接管(self):
        上下文, 识别器, 帧 = 构造上下文(["部落竞赛面板"])
        上下文._部落竞赛面板已确认 = True
        self.assertFalse(上下文.清理部落竞赛面板(帧))
        识别器.识别.assert_not_called()

    def test_点X后仍在面板则页面恢复失败(self):
        上下文, _, 帧 = 构造上下文(["部落竞赛面板"] * 7)
        self.assertFalse(上下文.清理部落竞赛面板(帧))
        上下文.点击已确认安全按钮.assert_called_once()
        self.assertTrue(上下文.页面恢复失败)


class 启动阶段竞赛面板测试(unittest.TestCase):
    def _任务(self, 清理结果):
        上下文 = SimpleNamespace(
            数据库=Mock(),
            机器人标志="robot_test",
            清理部落竞赛面板=Mock(return_value=清理结果),
            置脚本状态=Mock(),
            脚本延时=Mock(),
            页面恢复失败=False,
            停止事件=threading.Event(),
        )
        return 检测游戏登录状态任务(上下文), 上下文

    def test_关闭成功后继续主页确认不安全停止(self):
        任务, 上下文 = self._任务(True)
        屏幕 = np.zeros((600, 800, 3), dtype=np.uint8)
        self.assertTrue(任务._启动阶段处理部落竞赛面板(屏幕, 页面("部落竞赛面板")))
        上下文.清理部落竞赛面板.assert_called_once_with(屏幕)
        self.assertFalse(上下文.页面恢复失败)
        self.assertFalse(上下文.停止事件.is_set())

    def test_关闭失败才安全停止(self):
        任务, 上下文 = self._任务(False)
        self.assertTrue(任务._启动阶段处理部落竞赛面板(None, 页面("部落竞赛任务详情")))
        self.assertTrue(上下文.页面恢复失败)
        self.assertTrue(上下文.停止事件.is_set())

    def test_非竞赛页面不处理(self):
        任务, 上下文 = self._任务(True)
        self.assertFalse(任务._启动阶段处理部落竞赛面板(None, 页面("主世界主页")))
        上下文.清理部落竞赛面板.assert_not_called()

    def test_停止事件已置位不调用关闭器(self):
        任务, 上下文 = self._任务(True)
        上下文.停止事件.set()
        self.assertTrue(任务._启动阶段处理部落竞赛面板(None, 页面("部落竞赛面板")))
        上下文.清理部落竞赛面板.assert_not_called()


class 部落竞赛面板回放测试(unittest.TestCase):
    """用 2026-11-24 实测截图回放：面板 → 点 X → 主页。"""

    def test_实测竞赛面板截图回放关闭(self):
        面板 = 读取截图(竞赛目录 / "03_竞赛面板_个人积分.jpg")
        主页 = 读取截图(竞赛目录 / "01_主页_活动按钮.jpg")
        if 面板 is None or 主页 is None:
            self.skipTest("没有部落竞赛面板截图样本")
        from 模块.检测.OCR识别器 import 安全OCR引擎

        上下文 = 任务上下文.__new__(任务上下文)
        上下文.停止事件 = threading.Event()
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        上下文.页面恢复失败 = False
        上下文._战斗中 = False
        上下文._共享模板识别器 = 模板匹配引擎(图片库路径=根目录 / "img")
        上下文._点击页面识别器 = 页面识别器(上下文._共享模板识别器)
        上下文._共享OCR引擎 = 安全OCR引擎()
        上下文.标记模型使用 = Mock()
        帧序列 = [面板, 主页]
        上下文.op = SimpleNamespace(
            获取屏幕图像cv=Mock(side_effect=lambda *a, **k: 帧序列.pop(0) if len(帧序列) > 1 else 帧序列[0])
        )
        上下文.点击已确认安全按钮 = Mock(return_value=True)

        self.assertEqual(上下文._点击页面识别器.识别(面板, 战斗中=False).页面, "部落竞赛面板")
        self.assertTrue(上下文.清理部落竞赛面板(面板))
        上下文.点击已确认安全按钮.assert_called_once()
        x, y = 上下文.点击已确认安全按钮.call_args.args
        self.assertLess(abs(x - 709), 10)
        self.assertLess(abs(y - 39), 10)
        self.assertFalse(上下文.页面恢复失败)

    def test_实测任务详情截图也只点右上角X(self):
        详情 = 读取截图(竞赛目录 / "08_已接任务_放弃按钮_不点.jpg")
        主页 = 读取截图(竞赛目录 / "01_主页_活动按钮.jpg")
        if 详情 is None or 主页 is None:
            self.skipTest("没有部落竞赛任务详情截图样本")
        from 模块.检测.OCR识别器 import 安全OCR引擎

        上下文 = 任务上下文.__new__(任务上下文)
        上下文.停止事件 = threading.Event()
        上下文.置脚本状态 = Mock()
        上下文.脚本延时 = Mock()
        上下文.页面恢复失败 = False
        上下文._战斗中 = False
        上下文._共享模板识别器 = 模板匹配引擎(图片库路径=根目录 / "img")
        上下文._点击页面识别器 = 页面识别器(上下文._共享模板识别器)
        上下文._共享OCR引擎 = 安全OCR引擎()
        上下文.标记模型使用 = Mock()
        帧序列 = [详情, 主页]
        上下文.op = SimpleNamespace(
            获取屏幕图像cv=Mock(side_effect=lambda *a, **k: 帧序列.pop(0) if len(帧序列) > 1 else 帧序列[0])
        )
        上下文.点击已确认安全按钮 = Mock(return_value=True)

        self.assertTrue(上下文.清理部落竞赛面板(详情))
        x, y = 上下文.点击已确认安全按钮.call_args.args
        self.assertGreater(x, 640)
        self.assertLess(y, 110)


if __name__ == "__main__":
    unittest.main()
