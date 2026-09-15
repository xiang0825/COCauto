import time

from 模块.检测.OCR识别器.rapidocr_onnxruntime import RapidOCR
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from 模块.检测.OCR识别器 import 安全OCR引擎

def draw_ocr_results(image_path, result):
    # 读取图片
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"图片 {image_path} 不存在或无法读取！")

    # 转换BGR为RGB
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img)
    draw = ImageDraw.Draw(pil_img)

    try:
        font = ImageFont.truetype("simhei.ttf", 20)
    except:
        font = ImageFont.load_default()

    for item in result:
        if isinstance(item, list) and len(item) == 3:
            box, text, score = item
            box = np.array(box, dtype=np.int32).reshape(-1, 2)
            # 绘制文本框
            cv2.polylines(img, [box], isClosed=True, color=(0, 255, 0), thickness=2)
            # 绘制文本
            draw.text((box[0][0], box[0][1] - 25),
                     f"{text} ({score:.2f})",
                     font=font,
                     fill=(255, 0, 0))

    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    cv2.imwrite("./vis_result.jpg", img)
    print("可视化结果已保存至 vis_result.jpg")

# 正确用法
#engine = RapidOCR()
engine=安全OCR引擎()
engine2=安全OCR引擎()

# 判断是不是单例模式
print(engine2,engine)

img_path = r"img.png"

# 方式1：直接传入图片路径
result, elapse = engine(img_path)

耗时开始时间 = time.time()
# 方式2：传入OpenCV图像
img = cv2.imread(img_path)

result, elapse = engine(img)
print("识别结果:", result)
print(耗时开始时间 -time.time())
# 可视化结果
draw_ocr_results(img_path, result)