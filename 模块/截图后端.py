"""MAA 风格的截图后端调度、自动测速择优与失败自动回退。

本模块保持惰性导入 ``cv2`` 与 ``numpy``，确保控制台启动阶段不提前加载重型图像依赖。
所有解码路径统一输出与 ``ADB设备操作类.获取屏幕图像cv()`` 一致的 BGR ``uint8``
``numpy.ndarray``（shape 为 ``(高, 宽, 3)``）。
"""
from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass

BACKEND_MUMU_IPC = "mumu_ipc"
BACKEND_ADB_RAW = "adb_raw"
BACKEND_ADB_RAW_GZIP = "adb_raw_gzip"
BACKEND_ADB_PNG = "adb_png"

默认ADB候选顺序: tuple[str, ...] = (
    BACKEND_ADB_RAW,
    BACKEND_ADB_RAW_GZIP,
    BACKEND_ADB_PNG,
)

默认后端优先级: dict[str, int] = {
    BACKEND_MUMU_IPC: 0,
    BACKEND_ADB_RAW: 1,
    BACKEND_ADB_RAW_GZIP: 2,
    BACKEND_ADB_PNG: 3,
}

后端中文名称: dict[str, str] = {
    BACKEND_MUMU_IPC: "MuMu渲染器高速截图",
    BACKEND_ADB_RAW: "ADB原始像素(screencap)",
    BACKEND_ADB_RAW_GZIP: "ADB压缩原始像素(screencap|gzip)",
    BACKEND_ADB_PNG: "ADB PNG截图(screencap -p)",
}

PNG签名 = b"\x89PNG\r\n\x1a\n"
GZIP签名 = b"\x1f\x8b\x08"
最大原始字节数 = 20 * 1024 * 1024
最大解压字节数 = 64 * 1024 * 1024
诊断前缀最大扫描字节 = 4096


@dataclass(frozen=True)
class 后端测速结果:
    后端: str
    可用: bool
    最短耗时ms: float
    平均耗时ms: float
    分辨率: tuple[int, int] | None = None
    原因: str = ""


@dataclass(frozen=True)
class 截图测速报告:
    首选后端: str | None
    可用后端顺序: tuple[str, ...]
    结果列表: tuple[后端测速结果, ...]
    总耗时ms: float

    def 摘要文本(self) -> str:
        可用按序 = sorted(
            (项 for 项 in self.结果列表 if 项.可用),
            key=lambda 项: (
                项.平均耗时ms,
                项.最短耗时ms,
                默认后端优先级.get(项.后端, 99),
            ),
        )
        可用片段 = [
            f"{项.后端}({项.平均耗时ms:.1f}ms)"
            for 项 in 可用按序
        ]
        淘汰片段 = [
            f"{项.后端}({项.原因 or '不可用'})"
            for 项 in self.结果列表
            if not 项.可用
        ]
        首选描述 = self.首选后端 or "无"
        文本 = f"[截图测速] 已选最快通道：{首选描述}"
        if 可用片段:
            文本 += f"；可用：{' > '.join(可用片段)}"
        if 淘汰片段:
            文本 += f"；淘汰：{', '.join(淘汰片段)}"
        文本 += f"（总测速耗时 {self.总耗时ms:.1f}ms）"
        return 文本


def 构造ADB截图命令参数(后端: str, 显示ID: str | None = None) -> list[str]:
    """构造指定 ADB 截图后端的命令参数；MuMu 多显必须明确绑定数字 display ID。"""
    显示串 = str(显示ID).strip() if 显示ID is not None else ""
    if 显示串 and not re.fullmatch(r"\d+", 显示串):
        raise ValueError(f"非法的截图显示 ID：{显示串!r}")

    if 后端 == BACKEND_ADB_RAW:
        参数 = ["exec-out", "screencap"]
        if 显示串:
            参数.extend(["-d", 显示串])
        return 参数

    if 后端 == BACKEND_ADB_RAW_GZIP:
        if 显示串:
            return ["exec-out", f"screencap -d {显示串} | gzip -1"]
        return ["exec-out", "screencap | gzip -1"]

    if 后端 == BACKEND_ADB_PNG:
        参数 = ["exec-out", "screencap"]
        if 显示串:
            参数.extend(["-d", 显示串])
        参数.append("-p")
        return 参数

    raise ValueError(f"未知的 ADB 截图后端：{后端!r}")


def 解码PNG截图(数据: bytes):
    """解码 PNG 字节流（兼容前面附带的 adb 警告文本），返回 BGR ndarray 或 None。"""
    if not 数据 or len(数据) > 最大原始字节数:
        return None
    起点 = 数据.find(PNG签名)
    if 起点 < 0:
        return None
    import cv2
    import numpy as np

    数组 = np.frombuffer(数据[起点:], dtype=np.uint8)
    图像 = cv2.imdecode(数组, cv2.IMREAD_COLOR)
    if 图像 is None or getattr(图像, "size", 0) == 0:
        return None
    return 图像


def 解码原始截图(数据: bytes):
    """解析 ``screencap``（不带 -p）的原始像素，返回 BGR ndarray 或 None。

    数据格式：头部 宽、高、像素格式（各 4 字节小端），Android 12 起还多一个
    4 字节色彩空间，之后是 宽×高×每像素字节。头部前面可能混有 adb 打印的诊断
    文本，因此在开头一小段里寻找能让总长度严格对上的位置；找不到返回 None。
    """
    if not 数据 or len(数据) > 最大解压字节数:
        return None
    import cv2
    import numpy as np

    # 1=RGBA_8888, 2=RGBX_8888, 3=RGB_888, 4=RGB_565, 5=BGRA_8888
    转换映射 = {
        1: (4, cv2.COLOR_RGBA2BGR),
        2: (4, cv2.COLOR_RGBA2BGR),
        3: (3, cv2.COLOR_RGB2BGR),
        4: (2, cv2.COLOR_BGR5652BGR),
        5: (4, cv2.COLOR_BGRA2BGR),
    }
    总长 = len(数据)
    上限 = min(总长 - 12, 诊断前缀最大扫描字节) if 总长 > 12 else 0
    for 起点 in range(0, 上限):
        宽, 高, 格式 = struct.unpack_from("<III", 数据, 起点)
        if not (1 <= 宽 <= 8192 and 1 <= 高 <= 8192) or 格式 not in 转换映射:
            continue
        每像素字节, 转换码 = 转换映射[格式]
        for 头长 in (16, 12):
            if 总长 - 起点 - 头长 == 宽 * 高 * 每像素字节:
                像素 = np.frombuffer(
                    数据,
                    dtype=np.uint8,
                    offset=起点 + 头长,
                ).reshape(高, 宽, 每像素字节)
                return cv2.cvtColor(像素, 转换码)
    return None


def 解码Gzip原始截图(数据: bytes):
    """解压 ``screencap | gzip -1`` 输出并解析原始像素，返回 BGR ndarray 或 None。"""
    if not 数据 or len(数据) > 最大原始字节数:
        return None
    起点 = 数据.find(GZIP签名, 0, min(len(数据), 诊断前缀最大扫描字节 + len(GZIP签名)))
    if 起点 < 0:
        return None
    try:
        解压器 = zlib.decompressobj(16 + zlib.MAX_WBITS)
        解压数据 = 解压器.decompress(数据[起点:], 最大解压字节数 + 1)
        if len(解压数据) > 最大解压字节数 or 解压器.unconsumed_tail:
            return None
        尾部 = 解压器.flush()
        if 尾部:
            if len(解压数据) + len(尾部) > 最大解压字节数:
                return None
            解压数据 = 解压数据 + 尾部
        if not 解压器.eof:
            return None
    except zlib.error:
        return None
    if not 解压数据:
        return None
    图像 = 解码原始截图(解压数据)
    if 图像 is not None:
        return 图像
    return 解码PNG截图(解压数据)


def 校验截图帧(
    图像,
    期望尺寸: tuple[int, int] | None = None,
    *,
    允许全黑: bool = False,
) -> tuple[bool, str]:
    """校验截图是否为合法 BGR uint8 图像、非空、非全黑且尺寸一致。"""
    if 图像 is None:
        return False, "空帧"
    import numpy as np

    if not isinstance(图像, np.ndarray):
        return False, "图像类型不是 ndarray"
    if 图像.ndim != 3 or 图像.shape[2] != 3:
        return False, f"通道/维度异常: {getattr(图像, 'shape', None)}"
    if 图像.dtype != np.uint8:
        return False, f"像素类型异常: {图像.dtype}"
    高, 宽 = int(图像.shape[0]), int(图像.shape[1])
    if 宽 <= 0 or 高 <= 0 or 图像.size == 0:
        return False, f"尺寸为空: {宽}x{高}"
    if 期望尺寸 is not None and (宽, 高) != (int(期望尺寸[0]), int(期望尺寸[1])):
        return False, f"尺寸不一致: 期望{期望尺寸[0]}x{期望尺寸[1]}，实际{宽}x{高}"
    if not 允许全黑:
        # 先抽样快速判定，全黑时再做全图确认，兼顾测速与运行期开销。
        if int(图像[::4, ::4].max()) == 0 and int(图像.max()) == 0:
            return False, "画面全黑"
    return True, ""


def 画面像素一致(画面A, 画面B, *, 最大平均差异: float = 12.0) -> bool:
    """检查两张截图是否分辨率一致且画面内容匹配（容忍轻微动画抖动）。"""
    if 画面A is None or 画面B is None:
        return False
    if getattr(画面A, "shape", None) != getattr(画面B, "shape", None):
        return False
    import numpy as np

    差异 = float(np.abs(画面A.astype(np.int16) - 画面B.astype(np.int16)).mean())
    return 差异 < float(最大平均差异)
