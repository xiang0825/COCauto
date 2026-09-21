# -*- encoding: utf-8 -*-
# @Author: SWHL
# @Contact: liekkaskono@163.com
from .main import RapidOCR


def main():
    """运行 RapidOCR 网络图片示例。

    示例模块被导入做全量健康检查时不应联网或创建推理引擎，
    因此把演示动作限制在直接运行脚本的场景。
    """
    engine = RapidOCR()
    img_url = "https://img1.baidu.com/it/u=3619974146,1266987475&fm=253&fmt=auto&app=138&f=JPEG?w=500&h=516"
    result = engine(img_url)
    print(result)
    result.vis("vis_result.jpg")


if __name__ == "__main__":
    main()
