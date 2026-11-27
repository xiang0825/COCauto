import functools
import time
import unicodedata

import cv2

import os
import subprocess

_夜世界大厅资源上限 = {
    # 建筑大师大厅自带金币/圣水容量 + 当前大厅可建造的两个储存罐容量。
    1: 50_000,
    2: 75_000,
    3: 350_000,
    4: 500_000,
    5: 2_100_000,
    6: 2_500_000,
    7: 3_500_000,
    8: 4_500_000,
    9: 5_500_000,
    10: 6_500_000,
}

def 打印运行耗时(函数):
    @functools.wraps(函数)
    def 包装器(*参数, **关键字参数):
        开始时间 = time.time()
        结果 = 函数(*参数, **关键字参数)
        结束时间 = time.time()
        耗时 = 结束时间 - 开始时间
        try:
            print(f"函数「{函数.__name__}」运行耗时：{耗时:.4f} 秒")
        except (UnicodeEncodeError, OSError):
            # Windows 以 cp1252 启动源码/调试进程时，中文耗时日志不能
            # 反过来让已经成功完成的 OCR 任务失败；换成 ASCII 备用日志。
            try:
                安全函数名 = str(函数.__name__).encode(
                    "ascii", "backslashreplace"
                ).decode("ascii")
                print(f"elapsed {安全函数名}: {耗时:.4f}s")
            except (UnicodeEncodeError, OSError):
                # 日志输出永远不能改变业务函数的返回结果。
                pass
        return 结果
    return 包装器


def 生成贝塞尔轨迹(起点, 控制点1, 控制点2, 终点, 步数=30):
    """生成三阶贝塞尔曲线路径"""
    轨迹 = []
    for i in range(步数 + 1):
        t = i / 步数
        x = (1 - t) ** 3 * 起点[0] + 3 * (1 - t) ** 2 * t * 控制点1[0] + 3 * (1 - t) * t ** 2 * 控制点2[
            0] + t ** 3 * 终点[0]
        y = (1 - t) ** 3 * 起点[1] + 3 * (1 - t) ** 2 * t * 控制点1[1] + 3 * (1 - t) * t ** 2 * 控制点2[
            1] + t ** 3 * 终点[1]
        轨迹.append((int(x), int(y)))
    return 轨迹

def 显示图像(屏幕图像):
    cv2.imshow("test",屏幕图像)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

def _资源识别容差(储存上限: int, 资源类型: str) -> int:
    # 低容量黑油仓也要按比例接近上限才算满；固定 3000 的误差会让
    # 100,000 容量在 97,000 就停刷，浪费剩余空间。OCR 容差下限设为500。
    最小绝对误差 = 15_000 if 资源类型 in {"金币", "圣水"} else 500
    return max(最小绝对误差, int(round(储存上限 * 0.005)))


def _资源接近已知上限(
    数值, 资源类型: str, 黑油储存上限=None, 候选上限=None, 最低绝对容差=None
) -> bool:
    """判断 OCR 数字是否落在常见容量附近；黑油必须使用账号的明确容量。

    资源栏 OCR 经常把容量末尾的数字读偏几百到几千，例如实机把
    20,000,000 读成 20,000,634。只检查字符串末尾 ``000`` 会漏掉这种
    正常情况，也会把任意中间值误当成已满。金币和圣水使用已确认档位；
    黑油按账号设置的储存上限判断，避免把碰巧接近整万的余额当作满仓。
    0、负数、未知黑油容量或无法转换的 OCR 结果都会返回 False。
    """
    try:
        数值 = int(float(str(数值).replace(",", "").strip()))
    except (TypeError, ValueError, OverflowError):
        return False
    if 数值 <= 0:
        return False

    if 资源类型 == "黑油":
        try:
            已知容量 = int(黑油储存上限)
        except (TypeError, ValueError, OverflowError):
            return False
        if 已知容量 <= 0:
            return False
        return abs(数值 - 已知容量) <= _资源识别容差(已知容量, 资源类型)

    if 资源类型 in {"金币", "圣水"}:
        if 候选上限 is None:
            # 只使用确认过的储存容量档位，而不是每 10 万都当成一个容量，
            # 否则 19,000,000 这种中间值也会被错误当成“已满”。新版实机
            # 资源栏已确认 31,000,000 容量；未观测到的中间档位不做猜测。
            候选上限 = (
                100_000, 200_000, 300_000, 500_000,
                1_000_000, 2_000_000, 4_000_000, 6_000_000,
                8_000_000, 10_000_000, 12_000_000, 14_000_000,
                16_000_000, 18_000_000, 20_000_000, 22_000_000,
                31_000_000,
            )
    最近上限 = min(候选上限, key=lambda 上限: abs(数值 - 上限))
    容差 = (
        max(最低绝对容差, int(round(最近上限 * 0.005)))
        if 最低绝对容差 is not None
        else _资源识别容差(最近上限, 资源类型)
    )
    return abs(数值 - 最近上限) <= 容差


def 是否家乡资源打满(
    资源字典: dict,
    历史峰值: dict | None = None,
    黑油储存上限=None,
) -> bool:
    """根据已确认资源判断主世界是否已达到容量。

    低本没有黑油储存时，黑油为 0 不应阻塞“已满”判断；但金币和圣水
    仍必须同时接近各自容量。识别失败的 0 不会被当成资源已满。
    """
    if not isinstance(资源字典, dict) or 资源字典.get("识别成功") is False:
        return False
    金币 = 资源字典.get("金币", 0)
    圣水 = 资源字典.get("圣水", 0)
    黑油 = 资源字典.get("黑油", 0)
    # 同一账号曾经实际持有更多、且接近已知储存容量的资源时，当前值
    # 不可能仍是容量。无法对应已知容量档位的历史值可能是 OCR 串行误读
    # （例如把 31,000,000 读成 411,067,075），不能永久阻止满仓识别。
    # 历史值只允许按资源识别本身的 OCR 容差浮动，避免 2% 的宽余量
    # 把较低的相邻黑油容量也当成已满。
    if isinstance(历史峰值, dict):
        for 类型 in ("金币", "圣水", "黑油"):
            try:
                历史值 = int(历史峰值.get(类型, 0))
                if (
                    _资源接近已知上限(历史值, 类型, 黑油储存上限)
                    and int(资源字典.get(类型, 0))
                    < 历史值 - _资源识别容差(历史值, 类型)
                ):
                    return False
            except (TypeError, ValueError, OverflowError):
                return False
    黑油已确认无储存 = str(黑油).strip() in {"0", "0.0", "0.00", ""}
    return (
        _资源接近已知上限(金币, "金币")
        and _资源接近已知上限(圣水, "圣水")
        and (
            黑油已确认无储存
            or _资源接近已知上限(黑油, "黑油", 黑油储存上限)
        )
    )



def 是否目标资源打满(
    资源字典: dict,
    战利品优先级: str,
    历史峰值: dict | None = None,
    黑油储存上限=None,
) -> bool:
    """按当前战利品优先级和账号容量设置判断目标资源是否已满。

    定向刷金币、圣水或黑水时，只需目标资源达到可确认容量即可待机；
    均衡或未知优先级继续采用原有的全资源判断，避免改变旧配置语义。
    """
    目标资源 = {
        "金币": ("金币", "金币"),
        "圣水": ("圣水", "圣水"),
        "黑水": ("黑油", "黑油"),
    }.get(str(战利品优先级 or "").strip())
    if 目标资源 is None:
        return 是否家乡资源打满(资源字典, 历史峰值, 黑油储存上限)
    if not isinstance(资源字典, dict) or 资源字典.get("识别成功") is False:
        return False

    字典键, 容量类型 = 目标资源
    当前值 = 资源字典.get(字典键, 0)
    if isinstance(历史峰值, dict):
        try:
            历史值 = int(历史峰值.get(字典键, 0))
            if (
                _资源接近已知上限(历史值, 容量类型, 黑油储存上限)
                and int(当前值) < 历史值 - _资源识别容差(历史值, 容量类型)
            ):
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    return _资源接近已知上限(当前值, 容量类型, 黑油储存上限)


def 是否夜世界资源打满(
    资源字典: dict, 模式: str = "夜世界", 等级=None
) -> bool:
    """根据 Builder Base 模式和可选大厅等级判断金币、圣水是否满仓。

    未提供大厅等级时，保留旧版主世界容量识别，并兼容各个已确认的
    Builder Hall 满级总容量；明确大厅等级时，只认该等级的总容量，避免
    把较低容量档位误判为较高大厅账号已满。
    """
    if not isinstance(资源字典, dict) or 资源字典.get("识别成功") is False:
        return False
    if str(模式 or "").strip().casefold() not in {
        "夜世界", "建筑大师", "builder base", "builder_base", "bb"
    }:
        return False

    if 等级 is None:
        if (
            _资源接近已知上限(资源字典.get("金币", 0), "金币")
            and _资源接近已知上限(资源字典.get("圣水", 0), "圣水")
        ):
            return True
        候选容量 = tuple(_夜世界大厅资源上限.values())
    else:
        try:
            等级文本 = str(等级).strip().upper()
            if 等级文本.startswith("BH"):
                等级文本 = 等级文本[2:].strip()
            建筑大师大厅等级 = int(等级文本)
        except (TypeError, ValueError, OverflowError):
            return False
        容量 = _夜世界大厅资源上限.get(建筑大师大厅等级)
        if 容量 is None:
            return False
        候选容量 = (容量,)

    return any(
        _资源接近已知上限(
            资源字典.get("金币", 0), "金币", 候选上限=(容量,),
            最低绝对容差=500,
        )
        and _资源接近已知上限(
            资源字典.get("圣水", 0), "圣水", 候选上限=(容量,),
            最低绝对容差=500,
        )
        for 容量 in 候选容量
    )

def 单行资源识别(ocr引擎, img, 允许完整识别=False, 最大值=None):
    """识别已裁剪好的单行资源数字。

    右上角资源图在调用前已经按行裁剪；再运行文字检测和方向分类会额外
    加载/执行两个 ONNX 模型，并在分页文件较小的设备上触发 bad allocation。
    这里直接交给文字识别模型，既更轻量也更符合输入形态。
    """
    高, 宽 = img.shape[:2]
    # 资源栏一行高度约 53px，但数字本身只有约 18px 高；直接把整行
    # 缩放会让识别模型把图标和背景一起当成文字。先裁掉上下空白和右侧
    # 资源图标，把数字放大到更接近模型训练尺寸。
    if 高 >= 35:
        # 资源栏三行的文字并不总位于每一行的上半部。当前 MuMu
        # 1280×720 映射到逻辑 800×600 后，圣水/黑油数字会贴近行底；
        # 旧的 12%~82% 裁剪会把“31 000 000”下半截切掉并读成 0。
        # 保留少量上下边界，仍由后续二值化和数字提取过滤图标噪声。
        上 = max(0, int(round(高 * 0.05)))
        下 = min(高, int(round(高 * 0.95)))
        img = img[上:下, :]
    if 宽 >= 180:
        # 旧的 82% 右边界会切掉最右一位：夜世界现场数字 3 020 459
        # 被裁成半个 9，OCR 因而读成 3 020 455。将边界移到数字末端之外，
        # 同时仍留在资源图标左侧，避免把图标噪声带进识别区域。
        img = img[:, int(round(宽 * 0.28)):int(round(宽 * 0.86))]
    img = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    灰度 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    二值图 = cv2.adaptiveThreshold(
        灰度,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        5
    )

    def 提取候选数字(结果):
        if not 结果:
            return []
        # OCR 偶尔会把资源图标或阴影识别成额外的一项；取最长的数字
        # 串，而不是固定使用 result[0]，提高不同主题/分辨率下的稳定性。
        候选 = []
        for 项 in 结果:
            # 完整 OCR 返回 [坐标, 文字, 置信度]；轻量单行模式返回
            # [文字, 置信度]。两种格式都只提取真正的文字字段。
            if len(项) >= 3:
                原始文本 = 项[1]
            elif len(项) >= 2 and isinstance(项[0], str):
                原始文本 = 项[0]
            else:
                continue
            # OCR 可能返回全角/圈号数字；先做兼容性归一化，再只保留
            # ASCII 数字，避免 str.isdigit() 接受“①”却无法 int() 转换。
            清理文本 = unicodedata.normalize("NFKC", str(原始文本))
            清理文本 = 清理文本.replace('O', '0').replace('o', '0').replace(' ', '')
            数字 = ''.join(字符 for 字符 in 清理文本 if 字符 in "0123456789")
            if 数字:
                候选.append(数字)
        return 候选

    def 提取数字(结果, 只取合法=False):
        候选 = 提取候选数字(结果)
        if 只取合法 and 最大值 is not None:
            候选 = [数字 for 数字 in 候选 if int(数字) <= 最大值]
        return max(候选, key=len) if 候选 else ""

    def 安全OCR(输入图, **参数):
        """兼容 OCR 返回 ``(结果, 其他)``、结果列表和空结果。"""
        OCR返回 = ocr引擎(输入图, **参数)
        if isinstance(OCR返回, tuple):
            return OCR返回[0] if OCR返回 else []
        return OCR返回 or []

    # 彩色原图保留浅色数字的边缘；二值图作为不同主题下的备用输入。
    轻量数字 = ""
    for 输入图 in (img, 二值图):
        result = 安全OCR(输入图, use_det=False, use_cls=False)
        数字 = 提取数字(result, 只取合法=最大值 is not None)
        if len(数字) > len(轻量数字):
            轻量数字 = 数字
        if len(数字) >= 7 and not 允许完整识别:
            return int(数字)
        if 数字:
            # 彩色输入已经得到一个短数字时，不再无条件执行第二次
            # 轻量推理；调用方若认为它是截断值，会显式开启完整 OCR。
            break

    # 仅在调用方确认轻量结果可能为 0/截断时启用检测模型。完整 OCR
    # 能处理“31 000 000”这类带空格的大数字，但不应在每一帧资源轮询中
    # 无条件执行，否则会放大 ONNX 内存峰值。
    if 允许完整识别:
        完整数字 = ""
        for 输入图 in (img, 二值图):
            result = 安全OCR(输入图, use_cls=False)
            数字 = 提取数字(result, 只取合法=最大值 is not None)
            if len(数字) > len(完整数字):
                完整数字 = 数字
            if 数字 and len(数字) >= 8:
                # 八位及以上已经覆盖当前主城常见的完整资源读数，
                # 不再读取备用二值图，避免把图标噪声拼到末尾。
                return int(数字)
        if len(完整数字) > len(轻量数字):
            轻量数字 = 完整数字
    if not 轻量数字:
        return 0
    if 最大值 is not None and int(轻量数字) > 最大值:
        return 0
    return int(轻量数字)
