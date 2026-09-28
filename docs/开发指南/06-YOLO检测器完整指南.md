# YOLO检测器完整指南

> 本教程详细讲解如何使用YOLO检测器，从数据集收集、标注、训练到部署的完整流程。

## ⚠️ 重要说明：项目自带检测器的能力范围

**项目自带的YOLO检测器（`模块/检测/YOLO检测器/模型/best.onnx`）只能检测以下4种目标：**

| 类别 | 说明 |
|------|------|
| 金矿 | 金矿采集器 |
| 金库 | 金币存储建筑 |
| 圣水采集器 | 圣水采集建筑 |
| 圣水瓶 | 圣水存储建筑 |

**如果你需要检测其他目标**（如大本营、城墙、兵种等），**必须自己收集数据并训练模型**。本文档将详细指导你完成这一过程。

---

## 🎯 适合人群

- ✅ 需要识别游戏中的**自带模型不支持的目标**（如建筑、兵种等）
- ✅ 有一定Python基础
- ✅ 了解机器学习基本概念（可选）

## 📚 目录

1. [YOLO简介](#1️⃣-yolo简介)
2. [环境准备](#2️⃣-环境准备)
3. [数据集收集](#3️⃣-数据集收集)
4. [数据标注](#4️⃣-数据标注)
5. [模型训练](#5️⃣-模型训练)
6. [模型测试](#6️⃣-模型测试)
7. [导出ONNX模型](#7️⃣-导出onnx模型)
8. [在项目中使用](#8️⃣-在项目中使用)
9. [进阶技巧](#9️⃣-进阶技巧)
10. [常见问题](#🐛-常见问题)

---

## 1️⃣ YOLO简介

### 什么是YOLO？

**YOLO**（You Only Look Once）是一种实时目标检测算法，能够：
- 识别图像中的物体
- 标出物体的位置（边界框）
- 给出物体的类别和置信度

### 项目中的两种实现

| 实现 | 位置 | 版本 | 用途 | 状态 |
|------|------|------|------|------|
| **主检测器** | `模块/检测/YOLO检测器/` | YOLOv5 | 通用目标检测（金矿、圣水等） | ✅ 推荐 |
**重要通知**：
- 统一使用主检测器，避免任务各自加载重复模型
- 新开发的检测任务请复用线程安全检测器

### 主检测器特点

```python
# 模块/检测/YOLO检测器/yolo.py - 线程安全YOLO检测器

from 模块.检测 import 线程安全YOLO检测器

# 自动使用单例模式，多线程安全
检测器 = 线程安全YOLO检测器()

# 检测图像
结果 = 检测器.检测(图像)
# 返回格式：
# [
#     {
#         "类别名称": "金矿",
#         "裁剪坐标": [x1, y1, x2, y2],
#         "置信度": 0.95
#     },
#     ...
# ]
```

**⚠️ 默认模型仅支持以下4个类别**：`["金矿", "金库", "圣水采集器", "圣水瓶"]`

如需检测其他类别，请按照本文档后续步骤训练自己的模型。

---

## 2️⃣ 环境准备

### 运行环境 vs 训练环境

| 环境 | 用途 | 依赖 |
|------|------|------|
| **运行环境** | 使用已训练的模型检测 | `onnxruntime`, `opencv-python`, `numpy`, `pillow`（项目已自带） |
| **训练环境** | 训练自己的模型 | 需要克隆 YOLOv5 仓库并安装依赖 |

**如果你只是使用项目自带的检测器**，无需安装任何额外依赖，项目的 `requirements.txt` 已包含所有必要的库。

**如果你需要训练自己的模型**，请按以下步骤安装：

### 安装训练环境依赖

```bash
# 1. 克隆官方 YOLOv5 仓库
git clone https://github.com/ultralytics/yolov5.git
cd yolov5

# 2. 安装依赖（会自动安装 PyTorch 等）
pip install -r requirements.txt

# 3. 验证安装
python detect.py --weights yolov5s.pt --source data/images

# 4. 安装标注工具（在项目根目录执行）
pip install labelImg
```

### GPU支持（推荐，大幅加速训练）

YOLOv5 的 `requirements.txt` 默认安装 CPU 版本的 PyTorch。如果你有 NVIDIA 显卡，建议手动安装 CUDA 版本：

```bash
# 先卸载 CPU 版本
pip uninstall torch torchvision torchaudio

# 安装 CUDA 版本（以 CUDA 11.8 为例）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 验证 GPU 是否可用
python -c "import torch; print(f'CUDA可用: {torch.cuda.is_available()}')"
```

**注意**：
- 训练时使用 GPU 比 CPU 快 10-50 倍
- 如果没有 GPU，训练时间会非常长，建议使用云 GPU 服务（如 Google Colab）
- CUDA 版本需要与你的 NVIDIA 驱动版本兼容

---

## 3️⃣ 数据集收集

### 方法1：在搜索敌人时自动采集（推荐）

**这是最高效的采集方式**！在正常游戏流程中自动收集敌人村庄的截图，可以获得大量多样化的建筑样本。

**步骤**：在你的搜索敌人任务中添加采集代码

```python
# 在任务流程中添加采集代码示例

from 任务流程.基础任务框架 import 基础任务
import cv2
import time
from pathlib import Path

class 搜索敌人并采集数据(基础任务):
    """在搜索敌人时自动采集训练数据"""

    def __init__(self, 上下文):
        super().__init__(上下文)
        # 创建数据集目录
        self.数据集目录 = Path("dataset/raw")
        self.数据集目录.mkdir(parents=True, exist_ok=True)
        self.采集计数 = 0

    def 执行(self) -> bool:
        try:
            上下文 = self.上下文

            # 1. 进入搜索界面
            # ... 你的进入搜索逻辑 ...

            # 2. 循环搜索敌人
            for i in range(100):  # 搜索100个敌人
                上下文.置脚本状态(f"搜索第 {i+1} 个敌人")

                # 点击搜索按钮
                # 上下文.点击(搜索按钮x, 搜索按钮y, 1000)

                # 等待加载完成
                上下文.脚本延时(2000)

                # === 关键：采集敌人村庄截图 ===
                self.采集当前画面()

                # 点击下一个（继续搜索）
                # 上下文.点击(下一个按钮x, 下一个按钮y, 500)

            return True

        except Exception as e:
            self.异常处理(e)
            return False

    def 采集当前画面(self):
        """采集当前屏幕并保存"""
        上下文 = self.上下文

        # 截取游戏画面
        屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)

        # 生成唯一文件名（时间戳 + 计数）
        时间戳 = int(time.time() * 1000)
        文件名 = self.数据集目录 / f"enemy_{时间戳}_{self.采集计数:05d}.png"

        # 保存图像
        cv2.imwrite(str(文件名), 屏幕图像)

        self.采集计数 += 1
        上下文.置脚本状态(f"已采集 {self.采集计数} 张图像")
```

**优点**：
- ✅ 自动化采集，无需人工操作
- ✅ 图像多样性高（不同玩家的村庄布局不同）
- ✅ 可以在挂机时顺便采集
- ✅ 一次运行可采集数百张图像

**技巧**：
- 在不同时间段运行，获取不同光照效果
- 在不同大本等级段搜索，获取不同建筑
- 每次搜索后等待2-3秒再截图，确保画面加载完成

### 方法2：手动截图

**步骤**：

1. **启动游戏并进入目标场景**
   ```python
   # 使用项目的截图功能
   from 核心.op import op类

   op = op类()  # 参考测试脚本的初始化方式

   # 截取当前屏幕
   图像 = op.获取屏幕图像cv(0, 0, 800, 600)

   # 保存
   import cv2
   cv2.imwrite(f"dataset/raw/image_{i}.png", 图像)
   ```

2. **创建数据集目录**
   ```bash
   mkdir -p dataset/images/train
   mkdir -p dataset/images/val
   mkdir -p dataset/labels/train
   mkdir -p dataset/labels/val
   ```

3. **收集多样化的数据**
   - 不同场景（主界面、进攻界面、村庄）
   - 不同时间（白天、夜晚）
   - 不同状态（建筑升级中、完成）
   - 不同角度（如果有）
   - **数量建议**：
     - 最少：每个类别50张
     - 推荐：每个类别200-500张
     - 最佳：每个类别1000+张

### 方法3：定时自动采集脚本

```python
# 自动采集数据集.py

import cv2
import time
from 核心.op import op类

def 自动采集数据集(总数量=1000, 间隔秒=2):
    """自动截图收集数据集"""
    op = op类(0)

    print(f"将收集 {总数量} 张图像，每 {间隔秒} 秒一张")
    print("请切换到游戏画面...")
    time.sleep(5)

    for i in range(总数量):
        try:
            # 截图
            图像 = op.获取屏幕图像cv(0, 0, 800, 600)

            # 保存
            文件名 = f"dataset/raw/image_{i:05d}.png"
            cv2.imwrite(文件名, 图像)

            print(f"[{i+1}/{总数量}] 已保存: {文件名}")

            # 等待
            time.sleep(间隔秒)

        except KeyboardInterrupt:
            print("\n采集中断")
            break
        except Exception as e:
            print(f"错误: {e}")

    print(f"\n采集完成！共 {i+1} 张图像")

if __name__ == "__main__":
    自动采集数据集(总数量=500, 间隔秒=3)
```

### 数据清洗

**删除无效图像**：
- 模糊的
- 加载中的
- 弹窗遮挡的
- 目标不清晰的

**技巧**：使用Python快速筛选

```python
import cv2
from pathlib import Path

# 显示所有图像，按键删除
for 图像路径 in Path("dataset/raw").glob("*.png"):
    图像 = cv2.imread(str(图像路径))
    cv2.imshow("检查图像（按D删除，按空格继续）", 图像)

    键 = cv2.waitKey(0)
    if 键 == ord('d'):  # 删除
        图像路径.unlink()
        print(f"已删除: {图像路径.name}")

cv2.destroyAllWindows()
```

---

## 4️⃣ 数据标注

### 使用LabelImg标注

**1. 安装并启动**

```bash
pip install labelImg
labelImg
```

**2. 配置LabelImg**

- **Open Dir**：选择 `dataset/images/train`
- **Change Save Dir**：选择 `dataset/labels/train`
- **View → Auto Save mode**：开启自动保存
- 快捷键：
  - `W`：创建框
  - `D`：下一张
  - `A`：上一张
  - `Del`：删除框

**3. 标注步骤**

1. 点击 **Create RectBox**（或按 `W`）
2. 在目标周围拖动鼠标框选
3. 输入类别名称（如 `金矿`）
4. 重复步骤1-3标注所有目标
5. 按 `D` 保存并下一张

**4. 标注规范**

```
✅ 正确标注：
┌─────────┐
│  金矿   │  <- 框紧贴目标边缘
└─────────┘

❌ 错误标注：
┌──────────────┐
│              │  <- 框太大，包含背景
│    金矿      │
└──────────────┘

❌ 错误标注：
┌────┐
│金矿│  <- 框太小，目标被裁剪
└────┘
```

**5. 类别命名规则**

- 使用**中文**（与代码一致）
- 避免空格和特殊字符
- 保持一致性

**示例类别**：
```
金矿
金库
圣水采集器
圣水瓶
大本营
城墙
```

### 标注文件格式

LabelImg生成的YOLO格式标注文件（.txt）：

```
# dataset/labels/train/image_00001.txt

0 0.5 0.3 0.15 0.2
1 0.7 0.6 0.12 0.18
# ↑ ↑   ↑   ↑    ↑
# 类别索引 中心x 中心y 宽度 高度（归一化0-1）
```

### 数据集划分

```python
# 划分训练集和验证集.py

import shutil
from pathlib import Path
import random

def 划分数据集(源目录, 训练集比例=0.8):
    """将数据集划分为训练集和验证集"""

    源目录 = Path(源目录)
    图像列表 = list(源目录.glob("*.png")) + list(源目录.glob("*.jpg"))

    # 打乱顺序
    random.shuffle(图像列表)

    # 计算划分点
    训练数量 = int(len(图像列表) * 训练集比例)

    # 创建目标目录
    训练图像目录 = Path("dataset/images/train")
    验证图像目录 = Path("dataset/images/val")
    训练标签目录 = Path("dataset/labels/train")
    验证标签目录 = Path("dataset/labels/val")

    for 目录 in [训练图像目录, 验证图像目录, 训练标签目录, 验证标签目录]:
        目录.mkdir(parents=True, exist_ok=True)

    # 复制文件
    for i, 图像路径 in enumerate(图像列表):
        标签路径 = 图像路径.with_suffix('.txt')

        if not 标签路径.exists():
            print(f"警告: 缺少标签文件 {标签路径}")
            continue

        # 判断是训练集还是验证集
        if i < 训练数量:
            shutil.copy(图像路径, 训练图像目录)
            shutil.copy(标签路径, 训练标签目录)
        else:
            shutil.copy(图像路径, 验证图像目录)
            shutil.copy(标签路径, 验证标签目录)

    print(f"划分完成:")
    print(f"  训练集: {训练数量} 张")
    print(f"  验证集: {len(图像列表) - 训练数量} 张")

if __name__ == "__main__":
    划分数据集("dataset/raw", 训练集比例=0.8)
```

---

## 5️⃣ 模型训练

### 创建数据集配置文件

```yaml
# dataset/coc_dataset.yaml

path: ./dataset  # 数据集根目录
train: images/train  # 训练集图像目录
val: images/val  # 验证集图像目录

# 类别数量
nc: 4

# 类别名称（按索引顺序）
names:
  0: 金矿
  1: 金库
  2: 圣水采集器
  3: 圣水瓶
```

### 训练脚本

**方法1：使用命令行训练（推荐）**

```bash
# 进入 YOLOv5 目录
cd yolov5

# 开始训练
python train.py \
    --data ../dataset/coc_dataset.yaml \
    --weights yolov5s.pt \
    --epochs 100 \
    --batch-size 16 \
    --img 640 \
    --device 0 \
    --project ../runs/train \
    --name coc_detect

# 参数说明：
# --data: 数据集配置文件路径
# --weights: 预训练模型（yolov5n/s/m/l/x.pt）
# --epochs: 训练轮数
# --batch-size: 批次大小（根据显存调整）
# --img: 输入图像大小
# --device: 0=GPU, cpu=CPU
# --project: 输出目录
# --name: 实验名称
```

**方法2：使用 Python 脚本训练**

```python
# train_yolo.py
# 在 yolov5 目录下运行

import subprocess
import sys

def 训练模型(
    数据集配置="../dataset/coc_dataset.yaml",
    预训练模型="yolov5s.pt",  # n(nano) < s < m < l < x
    训练轮数=100,
    图像大小=640,
    批次大小=16,
    设备="0"  # "0"=GPU, "cpu"=CPU
):
    """使用 YOLOv5 train.py 训练模型"""

    命令 = [
        sys.executable, "train.py",
        "--data", 数据集配置,
        "--weights", 预训练模型,
        "--epochs", str(训练轮数),
        "--batch-size", str(批次大小),
        "--img", str(图像大小),
        "--device", 设备,
        "--project", "../runs/train",
        "--name", "coc_detect",
        "--cache",  # 缓存图像加速训练
    ]

    print(f"执行命令: {' '.join(命令)}")
    subprocess.run(命令, check=True)

    print("\n训练完成！")
    print(f"最佳模型: runs/train/coc_detect/weights/best.pt")

if __name__ == "__main__":
    训练模型(
        数据集配置="../dataset/coc_dataset.yaml",
        预训练模型="yolov5s.pt",
        训练轮数=100,
        批次大小=16
    )
```

### 训练参数说明

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `epochs` | 训练轮数 | 100-300 |
| `imgsz` | 图像大小 | 640（项目固定） |
| `batch` | 批次大小 | 16（GPU 8GB）<br>8（GPU 4GB）<br>-1（自动） |
| `device` | 设备 | "0"（GPU）<br>"cpu"（CPU） |
| `patience` | 早停耐心值 | 50 |
| `optimizer` | 优化器 | SGD（推荐）<br>Adam |

### 模型选择

| 模型 | 大小 | 速度 | 精度 | 推荐场景 |
|------|------|------|------|----------|
| YOLOv5n | 最小 | 最快 | 低 | 实时性要求高 |
| YOLOv5s | 小 | 快 | 中 | **推荐** |
| YOLOv5m | 中 | 中 | 高 | 精度要求高 |
| YOLOv5l | 大 | 慢 | 很高 | 离线分析 |
| YOLOv5x | 最大 | 最慢 | 最高 | 最高精度需求 |

### 监控训练过程

训练中会生成以下文件：

```
runs/train/coc_detect/
├── weights/
│   ├── best.pt        # 最佳模型（验证集最优）
│   └── last.pt        # 最后一轮模型
├── results.png        # 训练曲线图
├── confusion_matrix.png  # 混淆矩阵
├── F1_curve.png       # F1曲线
├── PR_curve.png       # 精确率-召回率曲线
└── train_batch*.jpg   # 训练批次示例

```

**关键指标**：
- **mAP50**：平均精度（IoU=0.5），越高越好
- **mAP50-95**：平均精度（IoU=0.5-0.95），越高越好
- **Precision**：精确率，越高越好
- **Recall**：召回率，越高越好

---

## 6️⃣ 模型测试

### 验证模型性能

```bash
# 在 yolov5 目录下运行
cd yolov5

# 在验证集上测试
python val.py \
    --data ../dataset/coc_dataset.yaml \
    --weights ../runs/train/coc_detect/weights/best.pt \
    --img 640 \
    --batch-size 16 \
    --conf-thres 0.25 \
    --iou-thres 0.45 \
    --device 0

# 输出会显示 mAP50、mAP50-95、Precision、Recall 等指标
```

### 单张图像测试

```bash
# 检测单张图像
python detect.py \
    --weights ../runs/train/coc_detect/weights/best.pt \
    --source test_image.png \
    --img 640 \
    --conf-thres 0.25 \
    --save-txt \
    --save-conf \
    --project ../runs/detect \
    --name test

# 结果保存在 runs/detect/test/ 目录
```

### 批量测试

```bash
# 测试整个目录
python detect.py \
    --weights ../runs/train/coc_detect/weights/best.pt \
    --source ../dataset/images/val \
    --img 640 \
    --conf-thres 0.25 \
    --project ../runs/detect \
    --name val_results
```

### Python 代码测试

```python
# 在 yolov5 目录下运行
import torch

# 加载模型
模型 = torch.hub.load('.', 'custom',
                       path='../runs/train/coc_detect/weights/best.pt',
                       source='local')

# 推理
结果 = 模型('test_image.png')

# 打印结果
结果.print()

# 保存结果图像
结果.save()

# 获取检测框数据
检测数据 = 结果.pandas().xyxy[0]
print(检测数据)
```

---

## 7️⃣ 导出ONNX模型

### 为什么导出ONNX？

- ✅ 跨平台兼容性
- ✅ 更快的推理速度
- ✅ 不依赖PyTorch
- ✅ 项目使用ONNX Runtime

### 导出命令

```bash
# 在 yolov5 目录下运行
cd yolov5

# 导出 ONNX 模型
python export.py \
    --weights ../runs/train/coc_detect/weights/best.pt \
    --img 640 \
    --batch-size 1 \
    --include onnx \
    --simplify \
    --opset 12

# 导出的 ONNX 文件会保存在 weights 同目录下
# 即：runs/train/coc_detect/weights/best.onnx
```

### 复制到项目目录

```bash
# 备份原模型
mv ../模块/检测/YOLO检测器/模型/best.onnx ../模块/检测/YOLO检测器/模型/best.onnx.bak

# 复制新模型
cp ../runs/train/coc_detect/weights/best.onnx ../模块/检测/YOLO检测器/模型/best.onnx
```

### 验证ONNX模型

```python
import onnxruntime as ort
import numpy as np
import cv2

# 加载ONNX模型
会话 = ort.InferenceSession("模块/检测/YOLO检测器/模型/best.onnx")

# 准备输入
图像 = cv2.imread("test.png")
图像 = cv2.resize(图像, (640, 640))
图像 = 图像.transpose(2, 0, 1).astype(np.float32) / 255.0
输入张量 = np.expand_dims(图像, 0)

# 推理
输入名 = 会话.get_inputs()[0].name
输出 = 会话.run(None, {输入名: 输入张量})

print("ONNX模型运行正常！")
print(f"输出形状: {输出[0].shape}")
```

---

## 8️⃣ 在项目中使用

### 替换默认模型

训练完成后，你需要用自己的模型替换项目默认模型。

**方法1：替换默认模型文件（推荐）**

```bash
# 备份原模型
mv 模块/检测/YOLO检测器/模型/best.onnx 模块/检测/YOLO检测器/模型/best.onnx.bak

# 复制你的模型
cp your_model.onnx 模块/检测/YOLO检测器/模型/best.onnx
```

然后修改 `模块/检测/YOLO检测器/yolo.py` 第340行的类别列表：

```python
# 修改默认类别列表为你的类别
if 类别列表 is None:
    类别列表 = ["你的类别1", "你的类别2", "你的类别3"]  # 修改为你训练的类别
```

**方法2：使用自定义路径（不影响默认模型）**

```python
from 模块.检测 import 线程安全YOLO检测器

# 使用自定义模型路径和类别
检测器 = 线程安全YOLO检测器(
    模型路径="path/to/your_model.onnx",
    类别列表=["类别1", "类别2", "类别3"]
)
```

### 方法1：使用主检测器（推荐）

**步骤1：放置模型文件**

```bash
# 将导出的ONNX模型复制到指定位置
cp best.onnx 模块/检测/YOLO检测器/模型/best.onnx
```

**步骤2：更新类别列表**

编辑 `模块/检测/YOLO检测器/yolo.py:340`：

```python
# 修改默认类别列表
if 类别列表 is None:
    类别列表 = ["金矿", "金库", "圣水采集器", "圣水瓶"]  # 你的类别
```

**步骤3：在任务中使用**

```python
from 任务流程.基础任务框架 import 基础任务

class 检测建筑任务(基础任务):
    def 执行(self) -> bool:
        try:
            上下文 = self.上下文

            # 1. 截取屏幕
            屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)

            # 2. YOLO检测（self.检测器已预初始化）
            检测结果 = self.检测器.检测(屏幕图像)

            # 3. 处理结果
            for 目标 in 检测结果:
                类别 = 目标["类别名称"]
                坐标 = 目标["裁剪坐标"]  # [x1, y1, x2, y2]
                置信度 = 目标["置信度"]

                上下文.置脚本状态(f"检测到: {类别}, 置信度: {置信度:.2f}")

                # 计算中心点
                中心x = (坐标[0] + 坐标[2]) // 2
                中心y = (坐标[1] + 坐标[3]) // 2

                # 点击目标
                if 类别 == "金矿" and 置信度 > 0.7:
                    上下文.点击(中心x, 中心y, 500)

            return True

        except Exception as e:
            self.异常处理(e)
            return False
```

### 方法2：自定义检测器（高级）

如果需要使用不同的模型路径或类别列表：

```python
from 模块.检测 import 线程安全YOLO检测器

class 自定义检测任务(基础任务):
    def __init__(self, 上下文):
        super().__init__(上下文)

        # 使用自定义模型
        self.自定义检测器 = 线程安全YOLO检测器(
            模型路径="path/to/custom_model.onnx",
            类别列表=["类别1", "类别2", "类别3"]
        )

    def 执行(self) -> bool:
        # 使用自定义检测器
        结果 = self.自定义检测器.检测(图像)
        # ...
```

### 完整示例：自动收集资源

```python
from 任务流程.基础任务框架 import 基础任务

class 自动收集资源(基础任务):
    """使用YOLO检测并收集资源建筑"""

    def 执行(self) -> bool:
        try:
            上下文 = self.上下文
            上下文.置脚本状态("开始收集资源...")

            # 1. 返回主界面
            self.返回主界面()

            # 2. 检测资源建筑
            资源列表 = self.检测资源建筑()

            if not 资源列表:
                上下文.置脚本状态("未检测到可收集的资源")
                return True

            上下文.置脚本状态(f"检测到 {len(资源列表)} 个资源建筑")

            # 3. 逐个收集
            收集数量 = 0
            for 资源 in 资源列表:
                if self.收集单个资源(资源):
                    收集数量 += 1
                    上下文.脚本延时(500)

            上下文.置脚本状态(f"收集完成，共 {收集数量} 个")
            return True

        except Exception as e:
            self.异常处理(e)
            return False

    def 检测资源建筑(self):
        """检测所有资源建筑"""
        上下文 = self.上下文

        # 截取主界面
        屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)

        # YOLO检测
        检测结果 = self.检测器.检测(屏幕图像)

        # 过滤资源建筑
        资源类型 = ["金矿", "圣水采集器"]
        资源列表 = []

        for 目标 in 检测结果:
            if 目标["类别名称"] in 资源类型:
                # 过滤低置信度
                if 目标["置信度"] >= 0.6:
                    资源列表.append(目标)

        # 按置信度排序
        资源列表.sort(key=lambda x: x["置信度"], reverse=True)

        return 资源列表

    def 收集单个资源(self, 资源):
        """点击收集单个资源"""
        上下文 = self.上下文

        # 计算中心点
        坐标 = 资源["裁剪坐标"]
        中心x = (坐标[0] + 坐标[2]) // 2
        中心y = (坐标[1] + 坐标[3]) // 2

        # 点击资源建筑
        上下文.点击(中心x, 中心y, 800)

        # 检测收集按钮
        屏幕图像 = 上下文.op.获取屏幕图像cv(0, 0, 800, 600)
        是否匹配, (按钮x, 按钮y), _ = self.模板识别.执行匹配(
            屏幕图像, "收集按钮.bmp", 0.9
        )

        if 是否匹配:
            上下文.点击(按钮x, 按钮y, 500)
            上下文.置脚本状态(f"收集 {资源['类别名称']}")
            return True

        return False

    def 返回主界面(self):
        """返回到主界面"""
        # ... 实现返回逻辑
        pass
```

---

## 9️⃣ 进阶技巧

### 1. 提高检测精度

**数据增强**（在 YOLOv5 训练时使用 hyp.yaml 配置）：

```bash
# 训练时使用自定义超参数
python train.py \
    --data ../dataset/coc_dataset.yaml \
    --weights yolov5s.pt \
    --epochs 100 \
    --hyp data/hyps/hyp.scratch-high.yaml  # 使用高数据增强配置
```

常用数据增强参数（在 hyp.yaml 中配置）：
- `mosaic: 1.0` - Mosaic 增强
- `mixup: 0.1` - Mixup 增强
- `hsv_h: 0.015` - 色调变化
- `hsv_s: 0.7` - 饱和度变化
- `hsv_v: 0.4` - 明度变化
- `translate: 0.1` - 平移
- `scale: 0.5` - 缩放
- `fliplr: 0.5` - 左右翻转

**多模型集成**：

```python
from 模块.检测 import 线程安全YOLO检测器

class 集成检测(基础任务):
    def __init__(self, 上下文):
        super().__init__(上下文)

        # 加载多个模型
        self.模型1 = 线程安全YOLO检测器("model1.onnx", 类别)
        self.模型2 = 线程安全YOLO检测器("model2.onnx", 类别)

    def 检测(self, 图像):
        # 两个模型都检测
        结果1 = self.模型1.检测(图像)
        结果2 = self.模型2.检测(图像)

        # 合并结果（投票或平均置信度）
        # ...
```

### 2. 优化推理速度

**使用 TensorRT（NVIDIA GPU）**：

```bash
# 在 yolov5 目录下导出 TensorRT 引擎
python export.py \
    --weights ../runs/train/coc_detect/weights/best.pt \
    --include engine \
    --device 0 \
    --half  # 使用 FP16 加速
```

**使用更小的模型**：

```bash
# 使用 yolov5n（nano）而不是 yolov5s
python train.py --weights yolov5n.pt ...
```

### 3. 处理小目标

**过滤策略**：

```python
def 过滤小目标(检测结果, 最小宽度=20, 最小高度=20, 最小面积=400):
    """过滤掉太小的目标"""
    有效结果 = []

    for 目标 in 检测结果:
        坐标 = 目标["裁剪坐标"]
        宽度 = 坐标[2] - 坐标[0]
        高度 = 坐标[3] - 坐标[1]
        面积 = 宽度 * 高度

        if 宽度 >= 最小宽度 and 高度 >= 最小高度 and 面积 >= 最小面积:
            有效结果.append(目标)

    return 有效结果
```

**训练时增加小目标样本**：

- 收集更多小目标的图像
- 使用更高分辨率的训练数据

### 4. 降低误检

**提高置信度阈值**：

```python
# 只保留高置信度的结果
检测结果 = [目标 for 目标 in 检测结果 if 目标["置信度"] >= 0.7]
```

**二次确认**：

```python
def 二次确认检测(self, 目标):
    """使用模板匹配二次确认YOLO检测结果"""
    坐标 = 目标["裁剪坐标"]

    # 截取检测区域
    区域图像 = self.上下文.op.获取屏幕图像cv(
        坐标[0], 坐标[1],
        坐标[2] - 坐标[0],
        坐标[3] - 坐标[1]
    )

    # 模板匹配确认
    是否匹配, _, _ = self.模板识别.执行匹配(区域图像, "确认模板.bmp", 0.8)

    return 是否匹配
```

---

## 🐛 常见问题

### 问题0：为什么默认模型只能检测4种类别？

**解答**：

项目自带的 `best.onnx` 模型是使用特定数据集训练的，该数据集只包含4种资源建筑：
- 金矿
- 金库
- 圣水采集器
- 圣水瓶

YOLO模型只能检测**训练时包含的类别**。如果你需要检测其他目标（如大本营、城墙、兵种等），必须：

1. 收集包含这些目标的图像
2. 标注这些目标
3. 训练自己的模型
4. 替换或新增模型文件

这就是本文档存在的意义 —— 教你如何训练自己的检测模型。

### 问题1：训练时显存不足

**错误信息**：
```
CUDA out of memory
```

**解决方案**：
```bash
# 1. 减小批次大小
python train.py --batch-size 8 ...  # 或 4、2

# 2. 使用更小的模型
python train.py --weights yolov5n.pt ...  # nano 模型

# 3. 减小图像大小（不推荐，项目固定640）
python train.py --img 416 ...

# 4. 使用 CPU 训练（极慢）
python train.py --device cpu ...
```

### 问题2：检测结果不准确

**原因分析**：
- 训练数据不足
- 数据质量差（模糊、遮挡）
- 训练轮数不够
- 类别不平衡
- **使用默认模型检测不支持的类别**（默认模型只支持：金矿、金库、圣水采集器、圣水瓶）

**解决方案**：
```bash
# 1. 确认你需要检测的类别是否在默认模型支持范围内
# 默认支持：["金矿", "金库", "圣水采集器", "圣水瓶"]
# 如需检测其他类别，必须训练自己的模型

# 2. 增加训练数据（每个类别至少200张）

# 3. 提高数据质量（删除模糊、遮挡的图像）

# 4. 增加训练轮数
python train.py --epochs 200 ...

# 5. 平衡各类别样本数量
```

### 问题3：ONNX导出失败

**错误信息**：
```
ONNX export failed
```

**解决方案**：
```bash
# 更新依赖
pip install --upgrade onnx onnxruntime

# 或指定 opset 版本
python export.py --weights best.pt --include onnx --opset 11
```

### 问题4：推理速度慢

**解决方案**：

1. **使用GPU推理**
   ```python
   # 确保ONNX Runtime使用GPU
   providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
   会话 = ort.InferenceSession(模型路径, providers=providers)
   ```

2. **使用更小的模型**
   ```bash
   # 训练时使用 yolov5n（nano）
   python train.py --weights yolov5n.pt ...
   ```

3. **使用TensorRT**
   ```bash
   python export.py --weights best.pt --include engine --device 0 --half
   ```

### 问题5：训练中断后恢复

```bash
# 从最后一次保存的权重继续训练
python train.py --resume ../runs/train/coc_detect/weights/last.pt
```

---

## 📚 相关资源

### 官方文档

- [Ultralytics YOLOv5](https://github.com/ultralytics/yolov5)
- [Ultralytics Docs](https://docs.ultralytics.com/)
- [ONNX Runtime](https://onnxruntime.ai/)

### 标注工具

- [LabelImg](https://github.com/heartexlabs/labelImg)
- [Roboflow](https://roboflow.com/) - 在线标注和数据增强
- [CVAT](https://github.com/opencv/cvat) - 专业标注工具

### 相关文档

- [任务开发进阶](./03-任务开发进阶.md) - 使用YOLO的基础教程
- [任务开发API](../核心文档/任务开发API.md) - 完整API参考

---

## 🔗 下一步

- **数据收集**：开始收集你的训练数据
- **模型训练**：训练你的第一个模型
- **部署使用**：在项目中使用训练好的模型

---

**提示**：本教程覆盖了从零到部署的完整流程。如果遇到问题，请在 [Issues](https://github.com/xiang0825/COCauto/issues) 中反馈！

**最后更新**：2026-02-07
