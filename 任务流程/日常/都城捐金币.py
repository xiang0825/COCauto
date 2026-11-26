"""C1. 把都城金币捐到都城（任务键 capital_donate）—— 骨架，必须实机校准后才运行。

流程：主页点都城入口 → OCR 确认都城页 → OCR 读都城金币余额，低于「捐献起点」
不捐 → 点 JSON 指定的捐献目标（正在升级的都城建筑）→ OCR 找「捐献」按钮 →
确认捐献弹窗 → 确认按钮附近必须匹配到都城金币图标、且无宝石图标/危险词才点 →
点「返回」回主世界（调度器随后再确认主世界主页）。

护栏：
- 资源/日常/都城.json calibrated 不是 true，或没有配置都城金币图标模板 → 拒绝运行。
- 只用都城金币：确认按钮区域必须匹配到都城金币图标；出现宝石图标或
  「宝石/购买/跳过/重置/加速」等文字一律拒绝点击。
- 任何一步页面未确认：已进入都城时标记页面不可信（安全待命），不乱点。
"""
from __future__ import annotations

import time

from 任务流程.日常 import 日常公共

任务键 = "capital_donate"

默认参数 = {
    "calibrated": False,
    "点击后等待毫秒": 1500,
    # 主页上都城入口（800x600）；未校准时为占位。
    "都城入口": [0, 0],
    "都城页确认区域": [200, 0, 600, 80],
    "都城页关键词": ["都城", "部落都城"],
    "都城金币余额区域": [600, 0, 800, 60],
    # 正在升级、要捐献的都城建筑（地图上的点）。
    "捐献目标点": [0, 0],
    "捐献按钮区域": [200, 450, 600, 600],
    "捐献按钮关键词": ["捐献", "贡献"],
    "捐献弹窗确认区域": [200, 60, 600, 160],
    "捐献弹窗关键词": ["捐献", "贡献"],
    "确认捐献按钮区域": [250, 380, 550, 520],
    "确认捐献按钮关键词": ["捐献", "贡献", "确定"],
    # 资源/ 下的都城金币图标模板，例如 "日常/都城模板/都城金币.png"；为空则拒绝运行。
    "都城金币图标模板": "",
    "都城金币图标阈值": 0.80,
    # 捐献弹窗外的空白处（点它关闭弹窗）；[0, 0] 表示未配置。
    "关闭捐献弹窗点": [0, 0],
    "返回按钮区域": [0, 500, 200, 600],
    "返回按钮关键词": ["返回", "回家"],
}


def 读取参数() -> dict:
    return 日常公共.加载日常参数("都城", 默认参数)


class 都城导航(日常公共.日常面板任务基类):
    """C1/C2 共用：从主世界主页进入都城、从都城返回主世界。

    需要参数键：都城入口、都城页确认区域、都城页关键词、返回按钮区域、返回按钮关键词。
    """

    def 进入都城(self) -> str:
        """返回 "已进入" / "跳过"（未配置、护栏拒绝或点击未被接受，未离开主页）/ "失败"。"""
        图 = self.截图()
        x, y = self.参数["都城入口"]
        if (x, y) == (0, 0):
            self.日志("都城入口坐标未配置，跳过")
            return "跳过"
        if not self.点击前护栏(图, 日常公共.扩展区域((x, y), 40, 40), "都城入口"):
            return "跳过"
        if not self.点击(x, y, "进入都城"):
            return "跳过"
        if not self.都城页在(self.截图()):
            self.日志("点了都城入口但未确认都城页，停止并保留画面")
            return "失败"
        self.已进入都城 = True
        return "已进入"

    def 都城页在(self, 图) -> bool:
        return self.区域有关键词(图, self.参数["都城页确认区域"], self.参数["都城页关键词"]) is not None

    def _返回(self) -> bool:
        图 = self.截图()
        按钮 = self.区域有关键词(图, self.参数["返回按钮区域"], self.参数["返回按钮关键词"])
        if 按钮 is None or 按钮[1] is None:
            self.日志("没找到返回按钮，保留画面")
            return False
        if not self.点击前护栏(图, 日常公共.扩展区域(按钮[1], 50, 22), "返回按钮"):
            return False
        if not self.点击(*按钮[1], "返回主世界"):
            return False
        self.已进入都城 = False
        return True


class 都城捐金币任务(都城导航):
    日志前缀 = "都城捐金币"

    def __init__(self, 上下文, 参数: dict | None = None):
        self.上下文 = 上下文
        self.数据库 = 上下文.数据库
        self.机器人标志 = 上下文.机器人标志
        self.参数 = 参数 if 参数 is not None else 读取参数()
        self.已进入都城 = False
        self.已捐献 = False

    def 可以运行(self) -> bool:
        if not 日常公共.已校准(self.参数):
            self.日志(
                "资源/日常/都城.json 尚未实机校准（calibrated=false），拒绝运行；"
                "请先截都城页/捐献弹窗校准坐标后再开启"
            )
            日常公共.请求等待(self.上下文, 3600, "都城未校准")
            return False
        if not str(self.参数.get("都城金币图标模板") or "").strip() or self._金币模板() is None:
            self.日志("未配置或找不到都城金币图标模板，无法确认只用都城金币，拒绝运行")
            日常公共.请求等待(self.上下文, 3600, "都城金币模板缺失")
            return False
        记录 = 日常公共.今日记录(self.数据库, self.机器人标志, 任务键)
        剩余 = 日常公共.冷却剩余秒(记录)
        if 剩余 > 0:
            日常公共.请求等待(self.上下文, 剩余, "都城捐献检查间隔")
            return False
        return True

    def _金币模板(self):
        路径 = str(self.参数.get("都城金币图标模板") or "").strip()
        return 日常公共.读取图片(路径) if 路径 else None

    def 执行(self) -> bool:
        if not self.可以运行():
            return True
        try:
            结果 = self._流程()
        except Exception as 异常:
            self.日志(f"异常：{异常}")
            结果 = False
        if self.已停止():
            # 停止后不再发任何点击，也不记完成，保留画面。
            return True
        if not 结果:
            self.上下文.页面恢复失败 = True
            return False
        self.记录完成()
        return True

    # ------------------------------------------------------------ 流程
    def _流程(self) -> bool:
        """True=完成或安全跳过（且已回到都城外或从未进入）。"""
        进入 = self.进入都城()
        if 进入 != "已进入":
            return 进入 == "跳过"
        图 = self.截图()
        余额 = self._读余额(图)
        起点 = int(getattr(self.上下文.设置, "都城金币捐献起点", 0) or 0)
        if 余额 is None:
            self.日志("都城金币余额读不出来，本轮不捐")
        elif 余额 <= 0 or 余额 < 起点:
            self.日志(f"都城金币 {余额} 未达到捐献起点 {起点}，不捐")
        else:
            if not self._捐献(余额):
                return False
        return self._返回()

    def _读余额(self, 图) -> int | None:
        for 文本, _ in self.OCR或空(图, self.参数["都城金币余额区域"]):
            数量 = 日常公共.解析数量(文本)
            if 数量 is not None:
                return 数量
        return None

    def _捐献(self, 余额: int) -> bool:
        """False 仅表示页面不可信。"""
        x, y = self.参数["捐献目标点"]
        if (x, y) == (0, 0):
            self.日志("捐献目标点未配置，不捐")
            return True
        图 = self.截图()
        if not self.点击前护栏(图, 日常公共.扩展区域((x, y), 40, 40), "捐献目标"):
            return True
        if not self.点击(x, y, "选中捐献目标"):
            return True
        图 = self.截图()
        按钮 = self.区域有关键词(图, self.参数["捐献按钮区域"], self.参数["捐献按钮关键词"])
        if 按钮 is None or 按钮[1] is None:
            self.日志("没找到捐献按钮（目标可能未在升级），不捐")
            return True
        if 日常公共.含危险词(按钮[0]) or not self.点击前护栏(图, 日常公共.扩展区域(按钮[1], 60, 22), "捐献按钮"):
            return True
        if not self.点击(*按钮[1], "打开捐献弹窗"):
            return True
        图 = self.截图()
        if not self.区域有关键词(图, self.参数["捐献弹窗确认区域"], self.参数["捐献弹窗关键词"]):
            self.日志("未确认捐献弹窗，停止并保留画面")
            return False
        确认区 = tuple(self.参数["确认捐献按钮区域"])
        确认 = self.区域有关键词(图, 确认区, self.参数["确认捐献按钮关键词"])
        if 确认 is None or 确认[1] is None:
            self.日志("捐献弹窗里没找到确认按钮，不捐")
            return self._关闭弹窗()
        if 日常公共.匹配模板(图, self._金币模板(), 确认区, float(self.参数["都城金币图标阈值"]),
                        缩放=(0.8, 1.0, 1.2)) is None:
            self.日志("确认按钮附近没有都城金币图标，无法确认只用都城金币，拒绝点击")
            return self._关闭弹窗()
        if 日常公共.含危险词(确认[0]) or not self.点击前护栏(图, 确认区, "确认捐献"):
            return self._关闭弹窗()
        if not self.点击(*确认[1], "确认捐献"):
            return self._关闭弹窗()
        self.已捐献 = True
        self.日志(f"已捐献都城金币（捐前余额 {余额}）")
        return True

    def _关闭弹窗(self) -> bool:
        """放弃捐献：点 JSON 指定的弹窗外空白处；未配置时视为页面不可信。"""
        self.日志("放弃本次捐献")
        x, y = self.参数.get("关闭捐献弹窗点", [0, 0])
        if (x, y) == (0, 0):
            self.日志("未配置关闭捐献弹窗点，保留画面")
            return False
        return self.安全关闭(
            (x, y), self.参数["捐献弹窗确认区域"], self.参数["捐献弹窗关键词"], "关闭捐献弹窗",
        )

    def 记录完成(self) -> None:
        间隔 = max(30, int(getattr(self.上下文.设置, "都城捐献检查间隔分钟", 360) or 360)) * 60
        记录 = 日常公共.今日记录(self.数据库, self.机器人标志, 任务键)
        记录["今日捐献次数"] = int(记录.get("今日捐献次数", 0)) + (1 if self.已捐献 else 0)
        记录["下次检查时间"] = time.time() + 间隔
        日常公共.写入任务记录(self.数据库, self.机器人标志, 任务键, 记录)
        日常公共.请求等待(self.上下文, 间隔, "都城捐献检查间隔")
