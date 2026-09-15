import unittest

from 任务流程.主世界打鱼.等待战斗结束并回营 import 等待战斗结束并回营任务


class _匹配器:
    def 执行匹配(self, _图像, 模板路径, **_参数):
        if "家乡进攻图标" in 模板路径:
            return True, (0, 0), None
        return True, (120, 130), None


class _屏幕:
    def 获取屏幕图像cv(self, *_区域):
        return object()


class _数据库:
    def 获取机器人设置(self, _机器人标志):
        return type("设置", (), {"是否试战统计胜率": False})()


class _上下文:
    op = _屏幕()
    数据库 = _数据库()
    机器人标志 = "测试机器人"

    def __init__(self):
        self.点击记录 = []
        self.状态 = []

    def 点击(self, x, y, *参数, **关键字参数):
        self.点击记录.append((x, y))

    def 脚本延时(self, _毫秒):
        pass

    def 置脚本状态(self, 文本, *参数, **关键字参数):
        self.状态.append(文本)


class 回营状态机测试(unittest.TestCase):
    def test_OCR胜负结果不能把未知当胜利(self):
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("胜利！"), "胜利")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("战斗失败"), "失败")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本判断战斗结果("结束战斗"), "未知")
        self.assertEqual(等待战斗结束并回营任务.从OCR文本提取摧毁率("摧毁率 67%"), 67)
        self.assertIsNone(等待战斗结束并回营任务.识别星数(None, "结束战斗"))
        self.assertIsNone(等待战斗结束并回营任务.校正星数("失败", 3, 49))
        self.assertIsNone(等待战斗结束并回营任务.校正星数("胜利", 3, 99))
        self.assertEqual(等待战斗结束并回营任务.校正星数("胜利", 3, 100), 3)
        self.assertIn("未识别战斗结果", 等待战斗结束并回营任务.生成战斗诊断("未知", None, None, {}))

    def test_点击回营后必须确认主界面(self):
        任务 = 等待战斗结束并回营任务.__new__(等待战斗结束并回营任务)
        任务.模板识别 = _匹配器()
        上下文 = _上下文()

        结果 = 任务.等待回营地按钮出现(上下文)

        self.assertTrue(结果)
        self.assertEqual(上下文.点击记录, [(120, 130)])
        self.assertIn("已确认回到主界面，可进入下一场", 上下文.状态)


if __name__ == "__main__":
    unittest.main()
