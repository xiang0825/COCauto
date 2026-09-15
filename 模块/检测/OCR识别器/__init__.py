import threading
from functools import wraps

import cv2
import threading
from functools import wraps
from queue import Queue
from concurrent.futures import ThreadPoolExecutor
from 工具包.工具函数 import 打印运行耗时
from .rapidocr_onnxruntime.main import RapidOCR
#

def 线程安全单例(原始类):
    """
    单例模式装饰器（线程安全版）
    功能：
    1. 保证被装饰的类全局只有一个实例
    2. 所有方法调用自动加锁保证线程安全
    """
    实例容器 = {}
    实例锁 = threading.Lock()  # 控制实例创建的锁

    @wraps(原始类)
    def 包装类(*参数, **配置参数):
        # 双重检查锁定模式（提升性能）
        if 原始类 not in 实例容器:
            with 实例锁:
                if 原始类 not in 实例容器:
                    print(f"创建 {原始类.__name__} 唯一实例")
                    实例容器[原始类] = 原始类(*参数, **配置参数)
        return 实例容器[原始类]

    return 包装类


@线程安全单例
class 安全OCR引擎:
    """RapidOCR的线程安全代理类"""

    def __init__(self, 配置文件路径=None, **配置参数):
        self._操作锁 = threading.Lock()  # 实例方法调用锁
        self._原始引擎 = RapidOCR(配置文件路径, **配置参数)  # 真正的OCR引擎

    def __call__(self, *输入参数, **动态参数):
        """代理所有方法调用并自动加锁"""
        with self._操作锁:

            return self._原始引擎(*输入参数, **动态参数)

    def __getattr__(self, 属性名):
        """转发其他属性访问到原始引擎"""
        return getattr(self._原始引擎, 属性名)


# 使用示例
if __name__ == "__main__":
    # 第一次创建实例
    引擎1 = 安全OCR引擎(配置文件路径="配置.yaml")

    # 第二次获取的是同一个实例
    引擎2 = 安全OCR引擎()
    print(f"是否是同一个实例: {引擎1 is 引擎2}")  # 输出 True

    # 线程安全调用
    识别结果 = 引擎1("图片.jpg")
    print(识别结果)

# def 线程安全单例(原始类):
#     """增强型单例装饰器，支持实例池"""
#     实例容器 = {}
#     实例锁 = threading.Lock()
#
#     @wraps(原始类)
#     def 包装类(*参数, **配置参数):
#         if 原始类 not in 实例容器:
#             with 实例锁:
#                 if 原始类 not in 实例容器:
#                     实例容器[原始类] = 原始类(*参数, **配置参数)
#         return 实例容器[原始类]
#
#     return 包装类
#
#
# @线程安全单例
# class 安全OCR引擎:
#     """支持并发的OCR引擎池"""
#
#     def __init__(self, 工作线程数=4, **配置参数):
#         # 初始化引擎池
#         self.引擎池 = Queue()
#         self.锁 = threading.Lock()
#         self.执行器 = ThreadPoolExecutor(max_workers=工作线程数)
#
#         # 创建多个引擎实例
#         for _ in range(工作线程数):
#             self.引擎池.put(RapidOCR(**配置参数))
#
#     def __call__(self, 图像输入):
#         """提交OCR任务到线程池"""
#         未来对象 = self.执行器.submit(self._执行识别, 图像输入)
#         return 未来对象.result()  # 阻塞获取结果
#
#     def _执行识别(self, 图像输入):
#         """从池中获取引擎实例执行识别"""
#         # 获取引擎实例
#         with self.锁:
#             ocr_engine = self.引擎池.get()
#
#         try:
#             # 执行实际识别
#             return ocr_engine(图像输入)
#         finally:
#             # 归还实例到池
#             with self.锁:
#                 self.引擎池.put(ocr_engine)
#
#
# # 使用示例
# if __name__ == "__main__":
#     # 初始化引擎池（4个工作实例）
#     ocr_引擎 = 安全OCR引擎(
#         工作线程数=4,
#         #配置文件路径="配置.yaml"
#     )
#
#
#     # 并行识别示例
#     def 并行测试():
#         图像 = cv2.imread("OCR_Test.png")
#         结果1 = ocr_引擎(图像)  # 提交到线程池
#         结果2 = ocr_引擎(图像)
#         print(f"结果1: {结果1[0]}\n结果2: {结果2[0]}")
#
#
#     # 启动多个线程测试
#     threads = []
#     for _ in range(8):
#         t = threading.Thread(target=并行测试)
#         t.start()
#         threads.append(t)
#
#     for t in threads:
#         t.join()