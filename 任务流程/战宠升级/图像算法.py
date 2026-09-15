import cv2
import numpy as np


def 是否包含指定颜色_HSV(图像: np.ndarray, 目标RGB: tuple,
                         色差H=10, 色差S=100, 色差V=100,
                         最少像素数=1000, 是否可视化=False) -> bool:
    "H (色相),S (饱和度),V (亮度)表示这三者的偏移的容忍程度"

    # 将图像转换为 HSV
    hsv图像 = cv2.cvtColor(图像, cv2.COLOR_BGR2HSV)

    # RGB → HSV（先转 BGR 再转 HSV）
    目标色_BGR = np.uint8([[list(reversed(目标RGB))]])  # RGB -> BGR
    目标色_HSV = cv2.cvtColor(目标色_BGR, cv2.COLOR_BGR2HSV)[0][0]
    h, s, v = map(int, 目标色_HSV)  # ⚠️ 转成 int 防止溢出

    # 定义 HSV 范围上下限
    下限 = np.array([max(0, h - 色差H), max(0, s - 色差S), max(0, v - 色差V)])
    上限 = np.array([min(179, h + 色差H), min(255, s + 色差S), min(255, v + 色差V)])

    # 掩码提取
    掩码 = cv2.inRange(hsv图像, 下限, 上限)
    匹配像素数 = cv2.countNonZero(掩码)

    # print(f"目标HSV: {目标色_HSV}  匹配像素数: {匹配像素数}")

    if 是否可视化:
        cv2.imshow("原图", 图像)
        cv2.imshow("匹配掩码", 掩码)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    return 匹配像素数 >= 最少像素数

def 从内部点获取黑框坐标(
    屏幕图像,
    内部点x,
    内部点y,
    半径=150,
    调试=False
):
    图高, 图宽 = 屏幕图像.shape[:2]

    def 显示(窗口名, 图像):
        if 调试:
            cv2.imshow(窗口名, 图像)
            cv2.waitKey(0)
            cv2.destroyWindow(窗口名)

    # ---------- 1. 计算 ROI ----------
    左 = max(内部点x - 半径, 0)
    上 = max(内部点y - 半径, 0)
    右 = min(内部点x + 半径, 图宽)
    下 = min(内部点y + 半径, 图高)

    ROI图像 = 屏幕图像[上:下, 左:右].copy()

    if 调试:
        标记ROI = ROI图像.copy()
        cv2.circle(
            标记ROI,
            (内部点x - 左, 内部点y - 上),
            4,
            (0, 0, 255),
            -1
        )
        显示("1_ROI（红点=内部点）", 标记ROI)

    # ---------- 2. 灰度 ----------
    灰度图 = cv2.cvtColor(ROI图像, cv2.COLOR_BGR2GRAY)
    显示("2_灰度图", 灰度图)

    # ---------- 3. 二值化 ----------
    二值阈值 = 150
    _, 二值图 = cv2.threshold(
        灰度图,
        二值阈值,
        255,
        cv2.THRESH_BINARY_INV
    )
    显示("3_二值化结果", 二值图)

    # ---------- 4. 查找轮廓 ----------
    轮廓列表, _ = cv2.findContours(
        二值图,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    if 调试:
        轮廓可视化 = ROI图像.copy()
        cv2.drawContours(轮廓可视化, 轮廓列表, -1, (0, 255, 0), 1)
        cv2.circle(
            轮廓可视化,
            (内部点x - 左, 内部点y - 上),
            4,
            (0, 0, 255),
            -1
        )
        显示("4_轮廓（绿=轮廓 红=内部点）", 轮廓可视化)

    # ---------- 5. 找包含内部点的轮廓 ----------
    for 轮廓 in 轮廓列表:
        是否包含 = cv2.pointPolygonTest(
            轮廓,
            (内部点x - 左, 内部点y - 上),
            False
        )

        if 是否包含 >= 0:
            rx, ry, rw, rh = cv2.boundingRect(轮廓)

            左上角 = (左 + rx, 上 + ry)
            右下角 = (左 + rx + rw, 上 + ry + rh)

            if 调试:
                标记全图 = 屏幕图像.copy()
                cv2.rectangle(
                    标记全图,
                    左上角,
                    右下角,
                    (0, 0, 255),
                    2
                )
                显示("5_最终结果（红框）", 标记全图)

            return 左上角, 右下角

    return None



if __name__ == "__main__":

    屏幕图像 = cv2.imread("img.png")

    结果 = 从内部点获取黑框坐标(
        屏幕图像,
        内部点x=290,
        内部点y=426,
        半径=120,
        调试=True
    )

    print("结果:", 结果)
