from 任务流程.基础任务框架 import 任务上下文, 基础任务

class 升级按钮定位失败错误(Exception):
    """当英雄不可升级时抛出的异常"""
    def __init__(self):
        super().__init__(f"升级按钮定位失败")
        # self.英雄名称 = 英雄名称

    # def __str__(self):
    #     return f"英雄[{self.英雄名称}]不可升级"

class 升级普通建筑任务(基础任务):
    """自动检测并升级指定英雄"""

    # 当前国际服的资源升级按钮在逻辑画布约 x=450..530；右侧
    # x=535..620 是“立即完成/宝石”卡片。旧版本从 x=520 开始裁剪，
    # 会把真实的“升级”按钮排除，随后误判为资源不足并发送返回键。
    # 这里保留升级卡片主体，同时不覆盖右侧宝石入口。
    升级确认区域 = (440, 465, 535, 570)

    def __init__(self, 上下文: '任务上下文',要升级的建筑):
        super().__init__(上下文)
        # 升级相似度阈值
        self.相似度阈值 = 0.8
        self.要升级的建筑= 要升级的建筑

    def 执行(self) -> bool:
        """检查"""
        try:

            self.上下文.置脚本状态(f"正在尝试升级[{self.要升级的建筑}] ")

            # 建议升级列表可能仍保留已经占用工人的项目。该项目被选中后
            # 画面会显示“正在进行升级”和“立即完成”，其中的锤子图标是
            # 宝石入口，不是新的升级按钮；必须在第一次点击前直接跳过。
            if self._当前已在升级中():
                self.上下文.置脚本状态(
                    f"{self.要升级的建筑} 已在升级中，禁止点击立即完成/宝石入口"
                )
                关闭器 = getattr(self.上下文, "关闭升级详情弹窗", None)
                if callable(关闭器):
                    关闭器()
                else:
                    self.关闭建筑升级页面()
                return False
            if self._当前是英雄或研究详情():
                self.上下文.置脚本状态(
                    f"{self.要升级的建筑} 当前为英雄/研究详情卡，禁止普通建筑模板点击"
                )
                关闭器 = getattr(self.上下文, "关闭升级详情弹窗", None)
                if callable(关闭器):
                    关闭器()
                else:
                    self.关闭建筑升级页面()
                return False

            可升级, 坐标 = self.是否出现图片(
                "建筑升级界面锤子.bmp|建筑升级界面锤子[1].bmp",
                (0,0,800,600),
                self.相似度阈值
            )

            if 可升级:
                # 全屏锤子模板也可能命中英雄/研究详情卡上的图标。普通
                # 建筑只有在底部资源卡片出现明确“升级/升級”文字时才允许
                # 使用模板坐标；没有文字证据就停止，不能把研究或宝石卡
                # 当成升级入口。
                OCR升级坐标 = self._OCR定位升级按钮()
                if OCR升级坐标 is None:
                    self.上下文.置脚本状态(
                        "锤子模板命中但未找到底部资源升级文字，禁止误点研究/宝石入口"
                    )
                    关闭器 = getattr(self.上下文, "关闭升级详情弹窗", None)
                    if callable(关闭器):
                        关闭器()
                    else:
                        self.关闭建筑升级页面()
                    return False
                self.上下文.置脚本状态(f"定位到升级按钮")

                # 第一次点击只会进入升级/详情操作区，不能据此判定已经升级。
                x, y = OCR升级坐标
                self.上下文.点击(x, y, )

                # 资源不足时，详情页仍然会显示锤子图标，但确认按钮是灰色。
                # 先检查确认区的绿色可用状态，避免把打开详情页误报成成功。
                if not self._升级确认按钮可用():
                    self.上下文.置脚本状态("升级确认按钮不可用，可能资源不足或建筑已在升级")
                    self.关闭建筑升级页面()
                    return False

                确认点 = self._定位升级确认按钮()
                if 确认点 is None:
                    self.上下文.置脚本状态("未定位到绿色升级确认按钮，禁止点击宝石或其他入口")
                    self.关闭建筑升级页面()
                    return False
                self.上下文.点击(*确认点, 延时=1000, 是否精确点击=True)

                # 点击后再次验证：按钮仍在表示点击没有提交升级。
                if self._升级确认按钮可用():
                    self.上下文.置脚本状态("点击升级后确认按钮仍可用，未检测到升级提交")
                    self.关闭建筑升级页面()
                    return False

                return True
            else:
                # 新版国际服的升级卡片图标会随分辨率/主题缩放，旧锤子
                # 模板可能低于阈值；优先用底部卡片中的 OCR“升级”文字
                # 定位，仍然只允许点击明确的升级入口。
                OCR坐标 = self._OCR定位升级按钮()
                if OCR坐标 is None:
                    OCR坐标 = self._局部模板定位升级按钮()
                if OCR坐标 is None:
                    raise 升级按钮定位失败错误()
                self.上下文.置脚本状态(
                    f"升级入口定位成功{OCR坐标[0]},{OCR坐标[1]}"
                )
                self.上下文.点击(*OCR坐标)

                if not self._升级确认按钮可用():
                    self.上下文.置脚本状态("升级确认按钮不可用，可能资源不足或建筑已在升级")
                    self.关闭建筑升级页面()
                    return False

                确认点 = self._定位升级确认按钮()
                if 确认点 is None:
                    self.上下文.置脚本状态("未定位到绿色升级确认按钮，禁止点击宝石或其他入口")
                    self.关闭建筑升级页面()
                    return False
                self.上下文.点击(*确认点, 延时=1000, 是否精确点击=True)
                if self._升级确认按钮可用():
                    self.上下文.置脚本状态("点击升级后确认按钮仍可用，未检测到升级提交")
                    self.关闭建筑升级页面()
                    return False
                return True

        except 升级按钮定位失败错误 as e:
            # 统一处理不可升级情况：关闭页面 + 状态记录
            #self.关闭建筑升级页面()
            self.上下文.置脚本状态(str(e))
            return False

        except Exception as e:
            # 其他异常统一处理
            self.异常处理(e)
            return False

    def _升级确认按钮可用(self) -> bool:
        """检查普通建筑升级确认区是否呈现可点击的绿色按钮。"""
        return self._定位升级确认按钮() is not None

    def _当前已在升级中(self) -> bool:
        """识别已占用工人的详情面板，阻止把宝石按钮当升级按钮。"""
        try:
            OCR结果 = self.执行OCR识别((0, 0, 800, 600))
        except Exception:
            return False
        文本 = " ".join(
            str(项[1]) for 项 in OCR结果 or []
            if isinstance(项, (list, tuple)) and len(项) > 1
        ).replace(" ", "").replace("\n", "")
        return any(状态 in 文本 for 状态 in (
            "正在进行升级", "正在進行升級", "正在进行升級", "正在進行升级",
        ))

    def _当前是英雄或研究详情(self) -> bool:
        """识别英雄/研究详情卡，避免普通建筑锤子模板误命中。"""
        try:
            OCR结果 = self.执行OCR识别((0, 0, 800, 600))
        except Exception:
            return False
        文本 = " ".join(
            str(项[1]) for 项 in OCR结果 or []
            if isinstance(项, (list, tuple)) and len(项) > 1
        ).replace(" ", "").replace("\n", "")
        有研究 = "研究" in 文本 or "研究" in 文本
        有等待或等级 = any(状态 in 文本 for 状态 in (
            "等待", "等級", "等级", "級",
        ))
        return 有研究 and 有等待或等级

    def _定位升级确认按钮(self) -> tuple[int, int] | None:
        """只定位带“确认/確認”文字的资源升级按钮。

        不能再用绿色像素作为唯一证据：升级进行中页面的“立即完成”
        卡片、地图草地以及其他界面元素也可能是绿色。确认页的按钮文
        字位于固定的底部卡片区域，只有 OCR 明确读到确认字样时才允
        许返回坐标；因此宝石入口即使颜色相同也不会成为候选。
        """
        try:
            # 确认按钮文字很短，裁成 120x100 的小图后 RapidOCR 容易把
            # “確”识别成噪声；使用完整逻辑画面，再用坐标过滤卡片范围。
            OCR结果 = self.执行OCR识别((0, 0, 800, 600))
        except Exception:
            return None

        # 普通建筑的资源按钮显示“升级/升級”，位于左侧资源卡片；
        # 英雄/特殊建筑的绿色提交按钮显示“确认/確認”，位于右侧卡片。
        # 两个区域必须分开：英雄左侧灰色“战斗之锤”按钮不能被点，
        # 普通建筑右侧“立即完成/宝石”卡片也不能被点。
        资源升级文字 = {"升级", "升級"}
        资源确认文字 = {"确认", "確認", "確認", "确", "確", "确定", "確定"}
        全部文本 = " ".join(
            str(项[1]) for 项 in OCR结果 or []
            if isinstance(项, (list, tuple)) and len(项) > 1
        ).replace(" ", "").replace("\n", "")
        if any(状态 in 全部文本 for 状态 in (
            "正在进行升级", "正在進行升級", "正在进行升級", "正在進行升级",
        )):
            self.上下文.置脚本状态("检测到升级进行中面板，禁止定位其立即完成/宝石按钮")
            return None
        发现升级确认标题 = False
        for 识别项 in OCR结果 or []:
            if not isinstance(识别项, (list, tuple)) or len(识别项) < 2:
                continue
            框, 原始文本 = 识别项[0], str(识别项[1] or "")
            文本 = 原始文本.replace(" ", "").replace("\n", "")
            # 国际服字体下底部“確認”常被 RapidOCR 误识别成相近汉字，
            # 但顶部的“升至…？”标题更稳定；两者都只作为确认页证据，
            # 不会出现在升级进行中的“立即完成”页面。
            if "升至" in 文本 and ("?" in 文本 or "？" in 文本):
                try:
                    发现升级确认标题 = min(float(点[1]) for 点 in 框) <= 90
                except (TypeError, ValueError, IndexError):
                    发现升级确认标题 = False
            try:
                xs = [float(点[0]) for 点 in 框]
                ys = [float(点[1]) for 点 in 框]
                x = (min(xs) + max(xs)) / 2
                y = (min(ys) + max(ys)) / 2
            except (TypeError, ValueError, IndexError):
                continue
            if 文本 in 资源升级文字 and 440 <= x <= 535 and 465 <= y <= 570:
                return round(x), round(y)
            if 文本 in 资源确认文字 and 520 <= x <= 640 and 465 <= y <= 570:
                return round(x), round(y)
        if 发现升级确认标题:
            # OCR 把英雄确认按钮文字识别成噪声时，右侧绿色卡片的
            # 逻辑中心仍固定在约 (560,522)。普通建筑必须命中左侧
            # “升级”文字才允许点击，不在这里猜测按钮位置。
            return (560, 522)
        return None

    def _OCR定位升级按钮(self) -> tuple[int, int] | None:
        """在底部建筑操作卡片中定位“升级/升級”文本中心。

        只接受逻辑画布 y>=430 的短文本，排除顶部“升级中”、
        “立即完成”和升级列表标题，避免 OCR 文字误触其他入口。
        """
        try:
            OCR结果 = self.执行OCR识别((0, 0, 800, 600))
        except Exception:
            return None
        for 识别项 in OCR结果 or []:
            if not isinstance(识别项, (list, tuple)) or len(识别项) < 2:
                continue
            框, 文本 = 识别项[0], str(识别项[1] or "")
            文本 = 文本.replace(" ", "").replace("\n", "")
            if 文本 not in {"升级", "升級"}:
                continue
            try:
                xs = [float(点[0]) for 点 in 框]
                ys = [float(点[1]) for 点 in 框]
                if min(ys) < 430:
                    continue
                return (round((min(xs) + max(xs)) / 2), round((min(ys) + max(ys)) / 2))
            except (TypeError, ValueError, IndexError):
                continue
        return None

    def _局部模板定位升级按钮(self) -> tuple[int, int] | None:
        """在底部升级卡片区域用缩放模板定位升级图标。

        新版 UI 的卡片图标尺寸与旧模板略有差异；把搜索范围限制在
        主世界选中建筑后的升级卡片，避免把地图中相似的锤子/图标误当
        成升级入口。点击后仍必须通过绿色确认按钮复核。
        """
        try:
            区域 = (475, 405, 600, 535)
            图像 = self.上下文.op.获取屏幕图像cv(*区域)
            执行最佳匹配 = getattr(self.模板识别, "执行最佳匹配", None)
            if not callable(执行最佳匹配):
                return None
            分数, (x, y), _ = 执行最佳匹配(
                图像,
                "建筑升级界面锤子.bmp|建筑升级界面锤子[1].bmp",
            )
            if float(分数) < 0.64:
                return None
            self.上下文.置脚本状态(f"缩放模板定位升级图标，匹配度{分数:.2f}")
            return (区域[0] + int(x), 区域[1] + int(y))
        except Exception:
            return None

    def 关闭建筑升级页面(self):
        """关闭升级界面"""
        # 建筑详情/升级卡片没有稳定的关闭按钮；在已确认的主世界面板
        # 上点击地图空白处可以关闭卡片。不要用 Android BACK：CoC 在
        # 某些过渡帧会把 BACK 解释为“退出游戏”，出现“确认退出”弹窗，
        # 甚至可能在后续误操作中真正关闭游戏。
        点击 = getattr(self.上下文, "点击", None)
        if callable(点击):
            try:
                点击(680, 300, 延时=700, 是否精确点击=True)
                self.上下文.置脚本状态(
                    "建筑升级详情已通过主世界空白区域关闭，禁止发送退出游戏返回键"
                )
                return True
            except Exception as 异常:
                self.上下文.置脚本状态(f"建筑详情空白区域关闭失败：{异常}")
        安全返回键 = getattr(self.上下文, "安全返回键", None)
        if callable(安全返回键):
            # 本任务刚刚已通过建筑升级入口/确认卡片识别到游戏内面板，
            # 这里关闭的是已确认的游戏面板，不是未知页面；明确授权一次
            # 受限 BACK，避免安全层把正常收尾误判成危险返回。
            安全返回键("关闭建筑升级页面", 已确认可关闭面板=True)
        else:
            self.上下文.键盘.按字符按压("esc")




from typing import Sequence, List, Optional, Tuple


def 提取建议升级建筑名称(
        ocr结果: Sequence[Tuple[list, str, float]],
        最低置信度: float = 0.8,
        排除城墙: bool = True
) -> Optional[List[str]]:
    """
    从 OCR 识别结果中，提取“建议升级”与“其他升级”之间的建筑名称列表。

    处理流程：
    1. 按文本框的 y 坐标自上而下排序
    2. 定位“建议升级”起始位置与“其他升级”结束位置
    3. 过滤低置信度、非建筑文本
    4. 可选排除“城墙”

    :param ocr结果: OCR 识别结果序列，格式为 (坐标框, 文本, 置信度)
    :param 最低置信度: 建筑文本可接受的最低置信度阈值
    :param 排除城墙: 是否排除城墙
    :return: 建筑名称列表，若未找到有效建筑则返回 None
    """

    if not ocr结果:
        return None

    # 1. 按文本框顶部 y 坐标排序
    排序后结果 = sorted(
        ocr结果,
        key=lambda 项: min(点[1] for 点 in 项[0])
    )

    # 2. 定位“建议升级”和“其他升级”的索引
    起始索引, 结束索引 = _定位升级区间(排序后结果)
    if 起始索引 is None or 结束索引 is None:
        return None

    # 3. 提取建筑名称
    建筑名称列表: List[str] = []

    for _, 原始文本, 置信度 in 排序后结果[起始索引 + 1:结束索引]:
        文本 = 原始文本.strip()

        if 置信度 < 最低置信度:
            continue

        if not 看起来像建筑(文本):
            continue

        if 排除城墙 and "城墙" in 文本:
            continue

        建筑名称列表.append(文本)

    return 建筑名称列表 or None


from typing import List, Optional, Sequence, Tuple


def 提取建议升级建筑(
    ocr结果: Sequence[Tuple[list, str, float]],
    最低置信度: float = 0.8,
    排除城墙: bool = True
) -> Optional[List[Tuple[list, str, float]]]:
    """
    从 OCR 识别结果中，提取“建议升级”与“其他升级”之间的建筑条目。

    处理流程：
    1. 按文本框的 y 坐标进行自上而下排序
    2. 定位“建议升级”起始位置与“其他升级”结束位置
    3. 过滤低置信度、非建筑文本
    4. 可选排除“城墙”

    :param ocr结果: OCR 识别结果序列，格式为 (坐标框, 文本, 置信度)
    :param 最低置信度: 建筑文本可接受的最低置信度阈值
    :param 排除城墙: 是否在结果中排除“城墙”
    :return: 建筑条目列表，若未找到有效区间则返回 None
    """

    if not ocr结果:
        return None

    # 1. 按文本框顶部 y 坐标排序（从上到下）
    排序后结果 = sorted(
        ocr结果,
        key=lambda 项: min(点[1] for 点 in 项[0])
    )

    # 2. 定位区间边界
    起始索引, 结束索引 = _定位升级区间(排序后结果)
    if 起始索引 is None or 结束索引 is None:
        return None

    # 3. 提取并过滤建筑文本
    建筑列表: List[Tuple[list, str, float]] = []

    for 坐标框, 原始文本, 置信度 in 排序后结果[起始索引 + 1: 结束索引]:
        文本 = 原始文本.strip()

        if 置信度 < 最低置信度:
            continue

        if not 看起来像建筑(文本):
            continue

        if 排除城墙 and "城墙" in 文本:
            continue

        建筑列表.append((坐标框, 文本, 置信度))

    return 建筑列表 or None

from typing import Optional, Sequence, Tuple


def _定位升级区间(
    ocr结果: Sequence[Tuple[list, str, float]]
) -> Tuple[Optional[int], Optional[int]]:
    """
    在 OCR 结果中定位“建议升级”与“其他升级”文本所在的索引区间。

    :param ocr结果: 已按 y 坐标排序的 OCR 结果
    :return: (起始索引, 结束索引)，若未找到则为 (None, None)
    """

    起始索引: Optional[int] = None
    结束索引: Optional[int] = None

    for 索引, (_, 文本, _) in enumerate(ocr结果):
        # 国际服不同字体/语言包下，建议升级标题可能被 OCR 识别成
        # “建升级”“建議升級”或漏掉中间的“议”。这些都是同一段列表。
        标准文本 = str(文本 or "").replace(" ", "").replace("\n", "")
        是建议升级标题 = (
            "建议升级" in 标准文本
            or "建議升級" in 标准文本
            or "建升级" in 标准文本
            or "建升級" in 标准文本
        )
        if 是建议升级标题:
            起始索引 = 索引
        elif (
            起始索引 is not None
            and ("其他升级" in 标准文本 or "其他升級" in 标准文本)
        ):
            结束索引 = 索引
            break

    # 面板当前滚动位置可能只显示“建议升级”区的一部分，
    # “其他升级”标题暂时不在截图内。此时读取到当前 OCR 末尾，
    # 由名称/置信度过滤器排除金额和状态文本，不再把有效建筑误判为空。
    if 起始索引 is not None and 结束索引 is None:
        结束索引 = len(ocr结果)

    return 起始索引, 结束索引

import re


def 看起来像建筑(文本: str) -> bool:
    """
    判断一段文本是否“语义上可能是建筑名称”。

    过滤规则包括：
    - 长度过短
    - 纯数字 / 金额 / 时间
    - OCR 常见噪声词

    :param 文本: OCR 识别出的文本
    :return: 是否可能是建筑名称
    """

    文本 = 文本.strip()

    # 1. 长度过短（如单字噪声）
    if len(文本) < 2:
        return False

    # 2. 纯数字（价格、数量），包括空格、逗号、点
    if re.fullmatch(r"[\d\s.,]+", 文本):
        return False

    # 3. 时间描述
    if any(单位 in 文本 for 单位 in ("分钟", "秒")):
        return False

    # 4. 面板状态/操作标题，不是可点击的建筑名称。
    if 文本 in {
        "可使用", "可用", "升级中", "建升级", "建议升级", "建議升級",
        "其他升级", "其他升級", "移除", "信息", "資訊", "确认", "確定",
    }:
        return False

    # 5. 金额或数值格式（如 7.000 / 1,500）
    if re.fullmatch(r"[\d.,]+", 文本):
        return False

    # 6. OCR 已知噪声
    噪声词集合 = {"DRDDY", "批究"}
    if 文本 in 噪声词集合:
        return False

    return True
