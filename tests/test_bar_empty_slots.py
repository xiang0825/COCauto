"""兵栏空位：军队只占前几格时，固定 9 格右侧的虚线空位不当成待探测法术。"""
import unittest
from types import SimpleNamespace

from 任务流程.主世界打鱼.进攻 import 进攻任务


class 兵栏空位测试(unittest.TestCase):
    # 实机 rc130 兵栏（雷龙/飞龙/弓箭手/攻城/飞龙公爵/闪电）识别到的 6 张卡
    卡片 = [(58, 493, 114, 594), (119, 493, 175, 594), (179, 493, 235, 594),
            (251, 493, 307, 594), (314, 493, 370, 594), (382, 493, 438, 594)]

    def test_最后一张卡右侧的固定格是空位(self):
        上下文 = SimpleNamespace(本场兵栏卡片=self.卡片)
        结果 = [进攻任务._是兵栏空位(上下文, 区域[0]) for _, 区域 in 进攻任务.可见兵栏格子]
        self.assertEqual(结果, [False] * 6 + [True] * 3)

    def test_认不出卡片时不判空位(self):
        self.assertFalse(进攻任务._是兵栏空位(SimpleNamespace(本场兵栏卡片=[]), 568))
        self.assertFalse(进攻任务._是兵栏空位(SimpleNamespace(), 568))


if __name__ == "__main__":
    unittest.main()
