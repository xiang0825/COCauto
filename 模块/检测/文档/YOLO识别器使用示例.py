import cv2
from pathlib import Path

from 模块.检测.YOLO检测器 import 线程安全YOLO检测器, 显示检测结果

项目根 = Path(__file__).resolve().parents[3]
示例图片 = 项目根 / "示例图片.bmp"

检测器 = 线程安全YOLO检测器()
检测器1 = 线程安全YOLO检测器()
print(id(检测器1), id(检测器))
# 检测结果 = 检测器.检测(r"YOLO识别测试图片.bmp")
# print(检测结果)
#
# 显示检测结果(r"YOLO识别测试图片.bmp",检测结果,"C:/Windows/Fonts/msyh.ttc")
cv图像=cv2.imread(str(示例图片))
检测结果 = 检测器.检测(cv图像)
print(检测结果)

显示检测结果(str(示例图片),检测结果,"C:/Windows/Fonts/msyh.ttc")
