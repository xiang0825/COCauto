from PIL import Image, ImageDraw, ImageFont

def 显示检测结果(图片路径, 检测结果, 字体路径="msyh.ttc", 字体大小=10):
    """
    在图片上绘制检测结果并显示,用于调试程序使用

    参数:
        图片路径: 原始图片路径或PIL.Image对象
        检测结果: 包含检测框和类别信息的列表
        [{
            '裁剪坐标': [x1,y1,x2,y2],
            '类别名称': str,
            '置信度': float
        }, ...]
        字体路径: 中文字体路径
        字体大小: 标注文字大小
        是否展示: 是否弹出窗口显示结果

    返回:
        PIL.Image对象: 绘制了检测框的图片
    """
    # 打开图片
    if isinstance(图片路径, str):
        图片 = Image.open(图片路径)
    elif isinstance(图片路径, Image.Image):
        图片 = 图片路径.copy()
    else:
        raise ValueError("图片路径需要是文件路径或PIL.Image对象")

    # 准备绘图工具
    绘图工具 = ImageDraw.Draw(图片)

    # 加载字体
    try:
        字体 = ImageFont.truetype(字体路径, 字体大小)
    except:
        print(f"警告：无法加载字体{字体路径}，使用默认字体")
        字体 = ImageFont.load_default()

    for 目标 in 检测结果:
        # 解包坐标参数
        x1, y1, x2, y2 = 目标['裁剪坐标']
        类别名称 = 目标['类别名称']
        置信度 = 目标.get('置信度', 1.0)  # 兼容无置信度的情况

        # 绘制边界框（红色）
        边框颜色 = (255, 0, 0)
        绘图工具.rectangle([x1, y1, x2, y2], outline=边框颜色, width=3)

        # 准备标签文本
        文本内容 = f"{类别名称} {置信度:.2f}" if '置信度' in 目标 else 类别名称

        # 计算文本位置（框上方）
        文本位置 = (x1, y1 - 字体大小 - 5)  # 上移避免遮挡

        # 绘制文本背景（白色底+黑色边框）
        文本尺寸 = 绘图工具.textbbox((0, 0), 文本内容, font=字体)
        背景框 = [
            文本位置[0] - 2,
            文本位置[1] - 2,
            文本位置[0] + (文本尺寸[2] - 文本尺寸[0]) + 2,
            文本位置[1] + (文本尺寸[3] - 文本尺寸[1]) + 2
        ]
        绘图工具.rectangle(背景框, fill=(255, 255, 255), outline=(0, 0, 0))

        # 绘制文本（黑色）
        绘图工具.text(文本位置, 文本内容, fill=(0, 0, 0), font=字体)
    图片.show()