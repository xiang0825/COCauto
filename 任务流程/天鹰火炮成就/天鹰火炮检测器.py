"""
天鹰火炮检测器模块 - 基于YOLO v8 ONNX模型的单类别目标检测
"""
import os
from pathlib import Path
from typing import List

import cv2
import numpy as np
import onnxruntime as ort


class 天鹰火炮检测器:
    """专门用于检测天鹰火炮的ONNX模型检测器（支持单类别YOLOv8）"""

    def __init__(self, 模型路径: str = None):
        if 模型路径 is None:
            模型目录 = Path(__file__).parent / "模型"
            # 优先使用ONNX，不存在则自动转换PT
            onnx路径 = 模型目录 / "best.onnx"
            if onnx路径.exists():
                模型路径 = str(onnx路径)
            else:
                pt路径 = 模型目录 / "best.pt"
                if pt路径.exists():
                    模型路径 = self._转换模型(pt路径)
                else:
                    raise FileNotFoundError(
                        f"模型文件不存在，请将 best.pt 或 best.onnx 放置到: {模型目录}"
                    )

        if not os.path.exists(模型路径):
            raise FileNotFoundError(f"模型文件不存在: {模型路径}")

        # 设置ONNX Runtime提供者
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        try:
            self.会话 = ort.InferenceSession(模型路径, providers=providers)
        except:
            self.会话 = ort.InferenceSession(模型路径)  # 不使用GPU

        # 获取输入输出信息
        self.输入名称 = self.会话.get_inputs()[0].name
        self.输出名称 = self.会话.get_outputs()[0].name

        # 获取输入尺寸
        输入形状 = self.会话.get_inputs()[0].shape
        if len(输入形状) == 4:
            self.模型尺寸 = 输入形状[2]  # NCHW格式中的H/W
        else:
            self.模型尺寸 = 640  # 默认值

    def _转换模型(self, pt文件: Path) -> str:
        """自动将PT模型转换为ONNX"""
        onnx文件 = pt文件.with_suffix('.onnx')

        try:
            from ultralytics import YOLO
            模型 = YOLO(str(pt文件))
            模型.export(format="onnx", imgsz=640, simplify=True)
            return str(onnx文件)
        except Exception as e:
            raise RuntimeError(f"模型转换失败: {e}，请手动转换或提供ONNX文件")

    def 预处理(self, 图像: np.ndarray):
        """预处理图像 - 保持长宽比的填充缩放"""
        if 图像 is None or len(图像.shape) != 3:
            raise ValueError("输入图像无效")

        原始高, 原始宽 = 图像.shape[:2]

        # 计算缩放比例
        缩放比例 = min(self.模型尺寸 / 原始宽, self.模型尺寸 / 原始高)

        # 计算新尺寸
        新宽 = int(原始宽 * 缩放比例)
        新高 = int(原始高 * 缩放比例)

        # 缩放图像
        if 缩放比例 != 1.0:
            缩放图 = cv2.resize(图像, (新宽, 新高))
        else:
            缩放图 = 图像.copy()

        # 创建填充后的正方形图像
        处理图 = np.full((self.模型尺寸, self.模型尺寸, 3), 114, dtype=np.uint8)
        x偏移 = (self.模型尺寸 - 新宽) // 2
        y偏移 = (self.模型尺寸 - 新高) // 2
        处理图[y偏移:y偏移+新高, x偏移:x偏移+新宽] = 缩放图

        # 转换为模型输入格式
        blob = 处理图.astype(np.float32) / 255.0  # 归一化
        blob = blob.transpose(2, 0, 1)  # HWC -> CHW
        blob = np.expand_dims(blob, axis=0)  # 添加batch维度

        return blob, 缩放比例, (x偏移, y偏移), (原始宽, 原始高)

    def 解析输出_yolov8_single_class(self, 输出数据: np.ndarray, 置信度阈值: float = 0.25):
        """解析单类别YOLOv8输出格式 [1, 5, 8400]"""
        检测结果 = []

        # 输出格式: [1, 5, 8400]
        # 5 = [x_center, y_center, width, height, confidence]
        数据 = 输出数据[0]  # 移除batch维度 [5, 8400]

        预测框数量 = 数据.shape[1]

        for i in range(预测框数量):
            # 提取数据
            x_中心 = 数据[0, i]
            y_中心 = 数据[1, i]
            宽 = 数据[2, i]
            高 = 数据[3, i]
            置信度 = 数据[4, i]

            # 过滤低置信度
            if 置信度 < 置信度阈值:
                continue

            # 转换为角点坐标
            x1 = x_中心 - 宽 / 2
            y1 = y_中心 - 高 / 2
            x2 = x_中心 + 宽 / 2
            y2 = y_中心 + 高 / 2

            # 确保坐标有效
            if x2 <= x1 or y2 <= y1:
                continue

            检测结果.append({
                'x1': float(x1),
                'y1': float(y1),
                'x2': float(x2),
                'y2': float(y2),
                '置信度': float(置信度),
                '类别': 0  # 单类别
            })

        return 检测结果

    def 解析输出(self, 输出数据: np.ndarray, 置信度阈值: float = 0.25):
        """自动判断并解析输出格式"""
        输出形状 = 输出数据.shape

        if len(输出形状) == 3:
            if 输出形状[1] == 5:  # 单类别YOLOv8 [1, 5, 8400]
                return self.解析输出_yolov8_single_class(输出数据, 置信度阈值)
            elif 输出形状[1] == 84:  # 多类别YOLOv8
                return self.解析输出_yolov8_single_class(输出数据, 置信度阈值)

        return []

    def 检测(self, 图像: np.ndarray, 置信度阈值: float = 0.25) -> List[dict]:
        """检测天鹰火炮"""
        if 图像 is None or len(图像.shape) != 3:
            return []

        try:
            # 预处理
            输入张量, 缩放比例, 填充偏移, 原始尺寸 = self.预处理(图像)

            # 推理
            输出 = self.会话.run([self.输出名称], {self.输入名称: 输入张量})[0]

            # 解析输出
            原始结果 = self.解析输出(输出, 置信度阈值)

            if len(原始结果) > 0:
                原始结果.sort(key=lambda x: x['置信度'], reverse=True)

            # 转换坐标到原始图像
            原始宽, 原始高 = 原始尺寸
            x偏移, y偏移 = 填充偏移
            最终结果 = []

            for i, 结果 in enumerate(原始结果):
                # 去除填充，转换回原始坐标
                x1 = (结果['x1'] - x偏移) / 缩放比例
                y1 = (结果['y1'] - y偏移) / 缩放比例
                x2 = (结果['x2'] - x偏移) / 缩放比例
                y2 = (结果['y2'] - y偏移) / 缩放比例

                # 确保坐标在范围内
                x1 = int(max(0, min(x1, 原始宽 - 1)))
                y1 = int(max(0, min(y1, 原始高 - 1)))
                x2 = int(max(0, min(x2, 原始宽 - 1)))
                y2 = int(max(0, min(y2, 原始高 - 1)))

                # 确保有效矩形
                if x2 > x1 and y2 > y1 and 结果['置信度'] >= 置信度阈值:
                    # 计算中心点
                    中心x = (x1 + x2) // 2
                    中心y = (y1 + y2) // 2
                    宽度 = x2 - x1
                    高度 = y2 - y1

                    最终结果.append({
                        '坐标': [x1, y1, x2, y2],
                        '中心': [中心x, 中心y],
                        '置信度': 结果['置信度'],
                        '类别': '天鹰火炮',
                        '宽度': 宽度,
                        '高度': 高度,
                        '面积': 宽度 * 高度
                    })

            return 最终结果

        except Exception as e:
            return []
