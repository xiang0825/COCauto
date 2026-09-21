from 任务流程.基础任务框架 import 任务上下文
from 任务流程.夜世界.夜世界打鱼.夜世界基础任务类 import 夜世界基础任务


class 打开进攻页面(夜世界基础任务):
    def __init__(self ,上下文: '任务上下文'):
        super().__init__(上下文)


    def 执行(self) -> bool:

        try:
            self.上下文.点击(58, 536, 700)  # 点击进攻
            if not self.是否出现开始进攻():
                raise RuntimeError("打开进攻页面失败")

            while self.是否出现进攻需要等待():
                self.上下文.置脚本状态("出现进攻需要等待页面,等待倒计时结束中……")
                self.上下文.脚本延时(500)

            # 夜世界按钮在不同语言包/缩放下文字和中心都会变化。先从
            # OCR 找按钮中心，找不到时才使用经过实机确认的参考坐标。
            # 这里不能直接复用旧的固定 y=380：繁体客户端的按钮中心约
            # 为 (600,397)，点击偏上会落在按钮外沿，后续就会一直等战斗。
            立即寻找点 = self._查找立即寻找按钮中心()
            if 立即寻找点 is None:
                立即寻找点 = (600, 397)
                self.上下文.置脚本状态(
                    "未从OCR定位立即寻找按钮，使用安全参考坐标600,397"
                )
            else:
                self.上下文.置脚本状态(
                    f"OCR定位立即寻找按钮：{立即寻找点[0]},{立即寻找点[1]}"
                )
            self.上下文.点击(*立即寻找点, 延时=700, 是否精确点击=True)

            return True

        except RuntimeError as e:
            self.异常处理(e)
            return False
    def 是否出现开始进攻(self):
        """确认夜世界的开始进攻面板。

        官方客户端的中文资源可能返回简体“开始进攻”，也可能返回
        繁体“開始進攻”。原先只依赖简体模板，在繁体 MuMu 实机上模板
        分数不足，导致刚打开页面就被误判失败。
        """
        是否匹配, (x, y)= self.是否出现图片( "夜世界_开始进攻.bmp")
        if 是否匹配:
            return True

        # 模板对字体、语言、缩放比较敏感；标题 OCR 只取面板上方区域，
        # 不会把主世界资源栏的文字当成开始进攻标题。
        OCR结果 = self.执行OCR识别((180, 25, 620, 190))
        if self._OCR包含文本(OCR结果, ("开始进攻", "開始進攻")):
            self.上下文.置脚本状态("OCR确认开始进攻面板（兼容简体/繁体）")
            return True
        return False

    def _查找立即寻找按钮中心(self):
        """返回“立即寻找/立即尋找”按钮的 800x600 逻辑坐标。"""
        区域 = (430, 320, 760, 520)
        OCR结果 = self.执行OCR识别(区域)
        for 项 in OCR结果 or []:
            if len(项) < 2:
                continue
            文本 = str(项[1]).replace(" ", "").replace("\n", "")
            # “立即”是按钮的稳定部分；允许 RapidOCR 把“找/尋”读错，
            # 但必须在按钮区域内并且具备可解析文本框。
            if "立即" not in 文本:
                continue
            try:
                框 = 项[0]
                点列表 = [(float(点[0]), float(点[1])) for 点 in 框]
                if len(点列表) < 2:
                    continue
                x = int(round(sum(点[0] for 点 in 点列表) / len(点列表)))
                y = int(round(sum(点[1] for 点 in 点列表) / len(点列表)))
                # OCR 返回的是裁剪区域内坐标，必须补回区域左上角。
                x += 区域[0]
                y += 区域[1]
                if y < 350 or not (480 <= x <= 700):
                    continue
                return x, y
            except (TypeError, ValueError, IndexError):
                continue
        return None

    @staticmethod
    def _OCR包含文本(识别结果, 目标文本) -> bool:
        for 项 in 识别结果 or []:
            if len(项) < 2:
                continue
            文本 = str(项[1]).replace(" ", "").replace("\n", "")
            if any(str(目标).replace(" ", "") in 文本 for 目标 in 目标文本):
                return True
        return False


    def 是否出现进攻需要等待(self):
        """验证是否已开始战斗"""
        是否匹配, (x, y)= self.是否出现图片( "夜世界_进攻需要等待.bmp|夜世界_进攻需要等待[1].bmp")
        return bool(是否匹配)

