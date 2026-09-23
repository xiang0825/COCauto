import random
import time
import cv2
import numpy as np

from 任务流程.基础任务框架 import 任务上下文, 基础任务
from 任务流程.夜世界.夜世界打鱼.夜世界基础任务类 import 夜世界基础任务
from 任务流程.建筑升级.升级普通建筑 import 提取建议升级建筑, 提取建议升级建筑名称


class 资源不足错误(Exception):
    """资源不足异常"""

    def __init__(self, 错误信息):
        super().__init__(错误信息)
        self.错误信息 = 错误信息

    def __str__(self):
        return f"发生了：{self.错误信息}"

from enum import Enum

class 建筑查找模式(Enum):
    指定建筑 = "指定建筑"
    建议升级中的第一个可用建筑 = "建议升级"

class 寻找建筑(夜世界基础任务):
    """自动检测并升级城墙"""

    # MuMu 当前 1280×720 主世界画面中，建筑/工人入口中心约为
    # (420,40)；任务逻辑画布为 800×600，因此统一使用映射后的
    # 参考坐标 (262,33)。旧值 (353,13) 会点到英雄栏/顶部空白，
    # 建筑任务随后 OCR 为空，甚至可能把后续返回动作误判为退出。
    建筑入口参考坐标 = (262, 33)
    英雄入口参考坐标 = (356, 33)
    英雄名称别名 = {
        "野蛮人之王": ("野蛮人之王", "野蠻人之王"),
        "弓箭女皇": ("弓箭女皇", "弓箭女皇"),
        "亡灵王子": ("亡灵王子", "亡靈王子"),
        "飞盾战神": ("飞盾战神", "飛盾戰神"),
        "大守护者": ("大守护者", "大守護者"),
        "飞龙公爵": ("飞龙公爵", "飛龍公爵"),
    }
    英雄OCR关键词 = {
        # 国际服当前 RapidOCR 实测会把“野蠻人之王”漏识别为“野人之王”。
        "野蛮人之王": ("野", "人", "王"),
        "弓箭女皇": ("弓", "箭", "女", "皇"),
        "亡灵王子": ("亡", "灵", "王", "子"),
        "飞盾战神": ("飞", "盾", "战", "神"),
        "大守护者": ("大", "守", "护", "者"),
        "飞龙公爵": ("飞", "龙", "公", "爵"),
    }
    英雄名称集合 = frozenset(英雄名称别名)

    默认颜色阈值 = {'色差H': 10, '色差S': 10, '色差V': 10, '最少像素数': 150}

    def __init__(
        self,
        上下文: '任务上下文',
        建筑名称: str | list | None = None,
        查找模式: 建筑查找模式 = 建筑查找模式.指定建筑,
        排除建筑名称: list[str] | set[str] | None = None,
    ):
        super().__init__(上下文)
        self.查找模式 = 查找模式
        self.排除建筑名称 = set(排除建筑名称 or ())
        self.开始时间 = None
        self.当前建筑: str | None = None  # 新增实例变量，用于保存找到的建筑，然后升级建筑任务读取这个变量，用于根据不同的建筑类型执行升级操作
        self.安全跳过 = False


        if 查找模式 == 建筑查找模式.指定建筑:
            # 支持单个建筑名称或多个建筑名称
            if isinstance(建筑名称, str):
                self.建筑列表 = [建筑名称]
            elif isinstance(建筑名称, list):
                self.建筑列表 = 建筑名称
            else:
                raise TypeError("建筑名称必须是字符串或字符串列表")

        elif 查找模式 == 建筑查找模式.建议升级中的第一个可用建筑:
            if 建筑名称 is not None:
                raise ValueError("建议升级模式下，不允许传入建筑名称")

            self.建筑列表 = []  # 由 OCR 决定

        else:
            raise ValueError(f"未知的查找模式: {查找模式}")


    # ---------------------- 主入口 ----------------------
    def 执行(self) -> bool:
        """任务执行入口"""
        try:

            if self.查找模式 == 建筑查找模式.指定建筑:
                # 英雄不在普通建筑入口的建议列表里。国际服当前 UI
                # 需要从顶部英雄状态入口打开“英雄殿堂”，再在其可滚动
                # 列表中选择目标；混合配置时先尝试英雄，找不到再回到
                # 普通建筑入口，避免把英雄名称永远交给错误的 OCR 页面。
                英雄列表 = [
                    名称 for 名称 in self.建筑列表
                    if 名称 in self.英雄名称集合
                ]
                普通建筑列表 = [
                    名称 for 名称 in self.建筑列表
                    if 名称 not in self.英雄名称集合
                ]
                if 英雄列表:
                    if self._寻找指定英雄(英雄列表):
                        return True
                    if not 普通建筑列表:
                        self.安全跳过 = True
                        return False
                    self.建筑列表 = 普通建筑列表
                return self.找建筑循环()
            elif self.查找模式 == 建筑查找模式.建议升级中的第一个可用建筑:
                self.上下文.置脚本状态(f"开始寻找建议升级中的建筑")

                if not self.打开建筑页面(划到底部=False):
                    return False
                ocr结果 = self.执行OCR识别((219, 57, 595, 398))

                # MuMu 当前繁体中文建筑名（如“頭號殺手”“攻城載車”）
                # 的 OCR 置信度约 0.75~0.79，标题和金额反而更高。
                # 仍限制在“建议升级”区间并经过看起来像建筑的过滤，
                # 将名称阈值降到 0.70，避免真实可升级项被当成空列表。
                self.建筑列表 = 提取建议升级建筑名称(
                    ocr结果, 最低置信度=0.70
                )
                if self.建筑列表 is None:
                    self.上下文.置脚本状态(f"警告，无法确定建议升级列表中的建筑,ocr结果为"+ocr结果.__str__())
                    return False

                self.上下文.置脚本状态(f"建议升级{', '.join(self.建筑列表)}")

                选中成功 = self.尝试选中指定建筑(
                    提取建议升级建筑(ocr结果, 最低置信度=0.70)
                )
                if not 选中成功 and not getattr(
                    self.上下文, "页面恢复失败", False
                ):
                    # 建议列表可能包含研究/装备等非普通建筑，或者候选
                    # 已在升级中、资源不足。这里没有任何可安全提交的
                    # 目标时，不能让上层 while 重新打开同一列表，形成
                    # 高频 OCR/点击循环；把本轮明确收敛为安全跳过，
                    # 由调度器按检查间隔退避后再检查。
                    self.安全跳过 = True
                    self.上下文.置脚本状态(
                        "建议升级列表本轮没有可安全提交的普通建筑，"
                        "安全跳过并等待下次检查"
                    )
                return 选中成功

        except 资源不足错误 as e:
            self.上下文.置脚本状态(str(e))
            return False
        except Exception as e:
            self.异常处理(e)
            return False

    @staticmethod
    def _规范英雄文本(文本: str) -> str:
        """统一国际服繁体 OCR 与配置中的简体英雄名称。"""
        文本 = str(文本 or "").replace(" ", "").replace("\n", "")
        翻译 = str.maketrans({
            "蠻": "蛮", "靈": "灵", "飛": "飞", "戰": "战",
            "守": "守", "護": "护", "龍": "龙",
        })
        return 文本.translate(翻译)

    @classmethod
    def _英雄文本匹配(cls, 目标: str, 文本: str) -> bool:
        """兼容少量可证明的英雄名漏字 OCR，不放宽到任意模糊匹配。"""
        规范文本 = cls._规范英雄文本(文本)
        if any(
            cls._规范英雄文本(别名) in 规范文本
            for 别名 in cls.英雄名称别名.get(目标, (目标,))
        ):
            return True
        关键词 = cls.英雄OCR关键词.get(目标, ())
        return bool(关键词) and all(字符 in 规范文本 for 字符 in 关键词)

    def _寻找指定英雄(self, 英雄列表: list[str]) -> bool:
        """从英雄殿堂列表定位目标英雄，不把地图当成可滚动面板。"""
        self.上下文.置脚本状态(
            f"开始寻找英雄: {', '.join(英雄列表)}"
        )
        # 调度器在进入建筑/英雄任务前已经确认主世界主页。英雄殿堂会
        # 记住上次的滚动位置，不能用“面板 OCR 是否命中”决定是否点击：
        # 深层列表没有标题时会被误判为未打开，重复点击反而会把面板关掉。
        if self.上下文.点击(*self.英雄入口参考坐标, 延时=1000) is False:
            self.上下文.页面恢复失败 = True
            self.上下文.置脚本状态("英雄入口点击被安全层拒绝，停止英雄升级扫描")
            return False
        self.上下文.脚本延时(350)
        try:
            英雄殿堂已打开 = self._英雄殿堂已打开()
        except Exception as 异常:
            英雄殿堂已打开 = False
            self.上下文.置脚本状态(f"英雄殿堂打开状态识别失败：{异常}")
        if not 英雄殿堂已打开:
            # 顶部英雄入口属于窄按钮，普通点击的随机偏移可能落在
            # 主世界地图或其它状态图标上。未确认面板时绝不能直接拖动，
            # 否则会把滑动手势发送到村庄并选中墙体/建筑。只重试一次
            # 精确入口点击，仍然要求 OCR 确认英雄殿堂后才允许滚动。
            self.上下文.置脚本状态(
                "英雄入口点击后未确认英雄殿堂，重试一次精确入口；禁止在主世界拖动"
            )
            if self.上下文.点击(
                *self.英雄入口参考坐标,
                延时=700,
                是否精确点击=True,
            ) is False:
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态(
                    "英雄殿堂精确入口点击被安全层拒绝，停止英雄升级扫描"
                )
                return False
            self.上下文.脚本延时(350)
            try:
                英雄殿堂已打开 = self._英雄殿堂已打开()
            except Exception:
                英雄殿堂已打开 = False
        if not 英雄殿堂已打开:
            self.上下文.页面恢复失败 = True
            self.上下文.置脚本状态(
                "两次点击后仍未确认英雄殿堂，停止英雄升级并禁止地图滑动"
            )
            return False
        self.建筑列表 = 英雄列表
        for 轮次 in range(10):
            self.上下文.脚本延时(700)
            ocr结果 = self.执行OCR识别((260, 55, 565, 500))
            可见名称 = []
            for 项 in ocr结果:
                if isinstance(项, (list, tuple)) and len(项) > 1:
                    文本 = str(项[1])
                    if any(
                        self._英雄文本匹配(名称, 文本)
                        for 名称 in 英雄列表
                    ):
                        可见名称.append(文本)
            self.上下文.置脚本状态(
                f"英雄殿堂当前可见: {', '.join(可见名称)}"
            )
            if self._尝试选中指定英雄(ocr结果, 英雄列表):
                self.上下文.脚本延时(1000)
                return True
            if 轮次 == 0:
                # 国际服会记住上次英雄列表滚动位置，但大多数情况下目标
                # 已经在首次画面中。先做一次 OCR 再回顶部，避免 MuMu 的
                # 多次 display 专属滑动和前台护栏把任务卡在“识别中”。
                self._重置英雄殿堂滚动位置()
                continue
            self._滑动英雄殿堂()

        self._关闭英雄殿堂()
        self.上下文.置脚本状态(
            f"未找到可升级英雄: {', '.join(英雄列表)}"
        )
        return False

    def _重置英雄殿堂滚动位置(self):
        """把记忆中的英雄列表位置安全拖回顶部。"""
        鼠标 = self.上下文.鼠标
        # 面板高度约为逻辑画布的 y=80..460；向下拖动只会回到列表
        # 顶部，不会触及主世界地图或任何资源/宝石按钮。
        for _ in range(4):
            鼠标.移动到(360, 150)
            鼠标.左键按下()
            for _ in range(32):
                鼠标.移动相对位置(0, 8)
                self.上下文.脚本延时(5)
            鼠标.左键抬起()
            self.上下文.脚本延时(180)

    def _英雄殿堂已打开(self) -> bool:
        """仅用英雄殿堂标题/英雄卡片确认页面，避免主世界误判。"""
        try:
            ocr结果 = self.执行OCR识别((260, 55, 565, 500))
        except Exception:
            return False
        文本 = "".join(
            str(项[1]) for 项 in ocr结果
            if isinstance(项, (list, tuple)) and len(项) > 1
        )
        规范文本 = self._规范英雄文本(文本)
        if "英雄殿堂" in 规范文本:
            return True
        可见英雄 = any(
            名称 in 规范文本 for 名称 in self.英雄名称集合
        )
        return 可见英雄 and ("升级中" in 规范文本 or "可使用" in 规范文本)

    def _尝试选中指定英雄(self, ocr结果, 英雄列表: list[str]) -> bool:
        """用英雄面板的 OCR 区域坐标点击目标行。"""
        for 识别项 in ocr结果:
            if not isinstance(识别项, (list, tuple)) or len(识别项) < 2:
                continue
            文本 = str(识别项[1])
            规范文本 = self._规范英雄文本(文本)
            目标 = next(
                (
                    名称 for 名称 in 英雄列表
                    if self._英雄文本匹配(名称, 文本)
                ),
                None,
            )
            if not 目标:
                continue
            try:
                x1, y1, x2, y2 = self._解析英雄坐标(识别项[0])
            except Exception as 异常:
                self.上下文.置脚本状态(f"英雄 OCR 坐标解析失败: {异常}")
                continue
            if not self.检查升级条件(x1, y1, x2, y2):
                self.上下文.置脚本状态(f"{目标}，不够资源升级，继续寻找")
                continue
            self.上下文.置脚本状态(f"找到目标英雄: {目标}, 尝试选中升级")
            self.当前建筑 = 目标
            return self.选中建筑(x1, y1, x2, y2)
        return False

    @staticmethod
    def _解析英雄坐标(坐标列表):
        if not 坐标列表 or any(len(点) < 2 for 点 in 坐标列表):
            raise ValueError("英雄 OCR 坐标为空或格式无效")
        所有x = [点[0] for 点 in 坐标列表]
        所有y = [点[1] for 点 in 坐标列表]
        左上x = int(min(所有x)) + 260
        左上y = int(min(所有y)) + 55
        右下x = int(max(所有x)) + 260
        右下y = int(max(所有y)) + 55
        if 右下x <= 左上x or 右下y <= 左上y:
            raise ValueError(f"英雄 OCR 坐标范围无效: {坐标列表}")
        return 左上x, 左上y, 右下x, 右下y

    def _滑动英雄殿堂(self):
        """只在英雄弹窗内部做短距离滑动，不触碰主世界地图。"""
        鼠标 = self.上下文.鼠标
        鼠标.移动到(360, 420)
        鼠标.左键按下()
        for _ in range(40):
            鼠标.移动相对位置(0, -7)
            self.上下文.脚本延时(5)
        鼠标.左键抬起()
        self.上下文.脚本延时(900)

    def _关闭英雄殿堂(self):
        # 这里由本任务自己打开过英雄殿堂，直接点击同一入口关闭，
        # 不再依赖深层列表是否还能 OCR 出标题。
        if self.上下文.点击(*self.英雄入口参考坐标, 延时=700) is False:
            self.上下文.页面恢复失败 = True
            self.上下文.置脚本状态("关闭英雄殿堂入口点击被安全层拒绝，停止后续操作")
            return False
        # 测试服关闭英雄殿堂后偶尔会露出“升级中/建议升级”主世界
        # 浮层；它不是主世界主页的可操作状态。右侧林地是已验证的
        # 安全空白点，用于清除浮层，禁止发送 ESC/BACK。
        self.上下文.脚本延时(350)
        if self.上下文.点击(700, 300, 延时=500, 是否精确点击=True) is False:
            self.上下文.页面恢复失败 = True
            self.上下文.置脚本状态("清除英雄殿堂浮层点击被安全层拒绝，停止后续操作")
            return False
        return True






    # ---------------------- 主流程循环 ----------------------
    def 找建筑循环(self) -> bool:
        """寻找并尝试升级建筑的主循环,成功返回真,失败返回假"""
        self.上下文.置脚本状态(f"开始寻找建筑: {', '.join(self.建筑列表)}")
        if not self.打开建筑页面():
            return False
        self.开始时间 = time.time()
        随机半径 = random.randint(0, 5)

        while True:
            停止事件 = getattr(self.上下文, "停止事件", None)
            if 停止事件 is not None and 停止事件.is_set():
                # 外部停止时不能再做 OCR 或地图滑动；否则关闭窗口/停止
                # 期间仍会继续向当前游戏页发送手势，表现为任务卡住或
                # 停止后画面继续移动。标记为安全跳过，避免调度器把
                # 正常的外部停止写成建筑升级失败。
                self.安全跳过 = True
                self.上下文.置脚本状态(
                    "收到停止请求，停止建筑扫描；禁止继续OCR、滑动或点击"
                )
                return False
            self.上下文.脚本延时(1500)
            if 停止事件 is not None and 停止事件.is_set():
                self.安全跳过 = True
                self.上下文.置脚本状态(
                    "建筑扫描延时结束时收到停止请求，禁止继续读取当前页面"
                )
                return False
            ocr结果 = self.执行OCR识别((219, 57, 595, 398))

            建筑列表 = []

            for 项 in ocr结果:
                文本 = 项[1]
                # 排除数字，只保留含有中文字符的，或者你也可以自己定义建筑关键词列表
                if any('\u4e00' <= c <= '\u9fff' for c in 文本):
                    建筑列表.append(文本)

            self.上下文.置脚本状态(f"前可见建筑: {', '.join(建筑列表[:])}")

            # 根据 OCR 结果，如果包含要查找的建筑,那么尝试选中建筑
            if ocr结果 and self.尝试选中指定建筑(ocr结果):
                self.上下文.脚本延时(1500)
                return True

            if "升级中" in str(ocr结果):
                self.上下文.置脚本状态("到顶了")
                break

            if time.time() - self.开始时间 > 120:
                raise RuntimeError(f"找建筑超时: {', '.join(self.建筑列表)}")

            if 停止事件 is not None and 停止事件.is_set():
                self.安全跳过 = True
                self.上下文.置脚本状态(
                    "建筑扫描OCR后收到停止请求，禁止继续滑动当前页面"
                )
                return False
            self.滑动屏幕(随机半径)
            self.上下文.置脚本状态(f"滑动屏幕，继续查找")

        self.关闭建筑页面()
        self.上下文.置脚本状态(f"未找到可升级的建筑: {', '.join(self.建筑列表)}")
        self.安全跳过 = True
        return False

    # ---------------------- 界面操作 ----------------------
    def 打开建筑页面(self,划到底部=True):
        """点击进入建筑界面并模拟滑动"""
        # 建筑升级任务在机器人调度器中已经先确认回到主世界。
        # ``是否刷主世界`` 只是资源任务开关，不代表当前所在世界；
        # 关闭刷资源但单独启用建筑升级时，仍必须点击主世界的工人/建筑入口。
        x, y = self.建筑入口参考坐标
        if not self._建筑升级面板已打开():
            if self.上下文.点击(x, y, 延时=1000) is False:
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态("建筑升级入口点击被安全层拒绝，停止建筑扫描")
                return False
        else:
            self.上下文.置脚本状态("已检测到建筑升级面板，复用当前页面，跳过重复点击入口")
        if 划到底部:
            self.滑动到建筑栏底部()
        return True

    def _建筑升级面板已打开(self) -> bool:
        """判断建筑升级面板是否已经打开，避免重复点击入口把面板关闭。

        建筑任务可能在上一轮停止、升级详情弹窗或用户手动打开面板后
        重新启动。入口按钮是开关式点击，不能无条件再点一次；只使用
        面板 OCR 特征做预检，识别失败时才按正常流程打开。
        """
        try:
            OCR结果 = self.执行OCR识别((219, 57, 595, 398))
        except Exception:
            return False
        文本 = " ".join(str(项[1]) for 项 in OCR结果 if isinstance(项, (list, tuple)) and len(项) > 1)
        文本 = 文本.replace(" ", "").replace("\n", "")
        建议区标题 = (
            "建议升级" in 文本,
            "建議升級" in 文本,
            "建升级" in 文本,
            "建升級" in 文本,
            "建筑升级" in 文本,
            "建築升級" in 文本,
        )
        if any(建议区标题):
            return True
        # 只有在同时出现“升级中”和面板里的“可使用”时才接受
        # 旧面板状态；主世界建筑自身的计时标签不能单独触发复用。
        return "升级中" in 文本 and ("可使用" in 文本 or "可用" in 文本)

    def 关闭建筑页面(self):
        """关闭建筑界面"""
        try:
            if self.上下文.点击(*self.建筑入口参考坐标, 延时=1000) is False:
                self.上下文.页面恢复失败 = True
                self.上下文.置脚本状态(
                    "关闭建筑升级页面点击被安全层拒绝，停止后续建筑操作"
                )
                return False
            return True
        except Exception as 异常:
            self.上下文.页面恢复失败 = True
            self.上下文.置脚本状态(f"关闭建筑升级页面失败：{异常}，停止后续建筑操作")
            return False

    def 滑动到建筑栏底部(self):
        """模拟进入建筑界面的滑动动作"""
        self.上下文.鼠标.移动到(399, 116)
        self.上下文.鼠标.左键按下()
        for _ in range(150):
            self.上下文.鼠标.移动相对位置(0, random.randint(-10, -5))
            self.上下文.脚本延时(5)
        self.上下文.鼠标.左键抬起()

    def 滑动屏幕(self, 随机半径: int):
        """模拟屏幕滑动寻找建筑"""
        # 同上：该查找器只服务主世界建筑升级，不能用资源任务开关
        # 推断坐标，否则关闭刷资源时会在错误位置滑动并选中地图对象。
        x = 399
        start_x = x + 随机半径
        start_y = 116 + 随机半径

        self.上下文.鼠标.移动到(start_x, start_y)
        self.上下文.鼠标.左键按下()
        for _ in range(10):
            self.上下文.鼠标.移动相对位置(0, random.randint(7, 12))
            self.上下文.脚本延时(5)
        self.上下文.鼠标.左键抬起()
        self.上下文.脚本延时(random.randint(1000, 1500))

    # ---------------------- OCR处理 ----------------------
    def 尝试选中指定建筑(self, ocr结果) -> bool:
        """判断ocr结果中是否有指定建筑，有则选中，没有则直接返回"""
        """判断 OCR 结果中是否有指定建筑列表里的建筑"""
        for 识别项 in ocr结果:
            文本内容 = 识别项[1]
            # 只要 OCR 文本匹配建筑列表中的任意一个就选中
            if not any(建筑 in 文本内容 for 建筑 in self.建筑列表):
                continue
            if any(已提交 in 文本内容 for 已提交 in self.排除建筑名称):
                self.上下文.置脚本状态(
                    f"跳过本轮已提交的建筑候选：{文本内容}"
                )
                continue

            try:
                x1, y1, x2, y2 = self.解析坐标(识别项[0])
            except Exception as e:
                self.上下文.置脚本状态(f"坐标解析失败: {str(e)}")
                continue

            if not self.检查升级条件(x1, y1, x2, y2):
                self.上下文.置脚本状态(f"{str(文本内容)}，不够资源升级，继续寻找")
                continue

            self.上下文.置脚本状态(f"找到目标建筑: {str(文本内容)}, 尝试选中升级")
            self.当前建筑=文本内容
            return self.选中建筑(x1, y1, x2, y2)

        return False

    def 解析坐标(self, 坐标列表):
        """解析OCR坐标"""
        if not 坐标列表 or any(len(点) < 2 for 点 in 坐标列表):
            raise ValueError("OCR坐标为空或格式无效")
        所有x = [点[0] for 点 in 坐标列表]
        所有y = [点[1] for 点 in 坐标列表]
        左上x = int(min(所有x)) + 219
        左上y = int(min(所有y)) + 57
        # 右边界必须跟随 OCR 框的实际位置。写死为 595 会把屏幕右侧
        # 的建筑裁掉，随后点击到错误区域或一直重复扫描。
        右下x = int(max(所有x)) + 219
        右下y = int(max(所有y)) + 57
        if 右下x <= 左上x or 右下y <= 左上y:
            raise ValueError(f"OCR坐标范围无效: {坐标列表}")
        return 左上x, 左上y, 右下x, 右下y

    # ---------------------- 升级检查与点击 ----------------------
    def 检查升级条件(self, x1, y1, x2, y2) -> bool:
        """检查资源是否足够"""
        区域图像 = self.上下文.op.获取屏幕图像cv(x1, y1, x2, y2)
        if self.是否包含指定颜色_HSV(区域图像, (250, 135, 124), **self.默认颜色阈值):
            return False
        else:
            return True

    def 选中建筑(self, x1, y1, x2, y2) -> bool:
        """执行升级操作"""
        中心x = (x1 + x2) // 2 + random.randint(-5, 5)
        中心y = (y1 + y2) // 2 + random.randint(-5, 5)
        if self.上下文.点击(中心x, 中心y, 延时=1500) is False:
            self.上下文.置脚本状态("建筑候选点击被安全层拒绝，停止当前升级目标")
            self.上下文.页面恢复失败 = True
            return False
        return True

    # ---------------------- 工具函数 ----------------------
    @staticmethod
    def 是否包含指定颜色_HSV(图像: np.ndarray, 目标RGB: tuple,
                             色差H=10, 色差S=100, 色差V=100,
                             最少像素数=1000, 是否可视化=False) -> bool:
        """判断图像中是否包含指定颜色块"""
        hsv图像 = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)
        目标色_BGR = np.uint8([[list(reversed(目标RGB))]])
        目标色_HSV = cv2.cvtColor(目标色_BGR, cv2.COLOR_BGR2HSV)[0][0]
        h, s, v = map(int, 目标色_HSV)

        下限 = np.array([max(0, h - 色差H), max(0, s - 色差S), max(0, v - 色差V)])
        上限 = np.array([min(179, h + 色差H), min(255, s + 色差S), min(255, v + 色差V)])
        掩码 = cv2.inRange(hsv图像, 下限, 上限)
        匹配像素数 = cv2.countNonZero(掩码)

        if 是否可视化:
            cv2.imshow("原图", 图像)
            cv2.imshow("匹配掩码", 掩码)
            cv2.waitKey(0)
            cv2.destroyAllWindows()

        return 匹配像素数 >= 最少像素数
