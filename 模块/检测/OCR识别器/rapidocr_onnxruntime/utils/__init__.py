# -*- encoding: utf-8 -*-
# @Author: SWHL
# @Contact: liekkaskono@163.com
from pathlib import Path
from typing import Dict, Union

import yaml

from .infer_engine import OrtInferSession
from .logger import get_logger
from .parse_parameters import UpdateParameters, init_args, update_model_path
from .process_img import add_round_letterbox, increase_min_side, reduce_max_side


def read_yaml(yaml_path: Union[str, Path]) -> Dict[str, Dict]:
    with open(yaml_path, "rb") as f:
        data = yaml.load(f, Loader=yaml.Loader)
    return data


def __getattr__(name):
    """仅在需要文件加载或可视化时才导入 Pillow 相关模块。"""
    if name in {"LoadImage", "LoadImageError"}:
        from .load_image import LoadImage, LoadImageError

        return {"LoadImage": LoadImage, "LoadImageError": LoadImageError}[name]
    if name == "VisRes":
        from .vis_res import VisRes

        return VisRes
    raise AttributeError(name)
