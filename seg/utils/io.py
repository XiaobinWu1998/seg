import json
import orjson
from os.path import join as opj
from os.path import exists as ope
import natsort
import os
from .typing import Sequence
import numpy as np
import cv2
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

IMAGE_POSTFIX: [Sequence[str]] = ["PNG", "JPEG", "JPG", "BMP", "PPM", "TIF", "PGM", "TIFF", "BMP"]

def ls_folder(folder, postfix=None, use_sort=True):
    """
    列出输入folder下面的所有文件目录
    """
    os_sorted = natsort.os_sorted if use_sort else lambda x, *args, **kwargs: x
    if os.path.exists(folder):
        if postfix is None:
            return os_sorted([os.path.join(folder, f) for f in os.listdir(folder)])
        else:
            if isinstance(postfix, str):
                postfix = [postfix.upper()]
            else:
                postfix = [p.upper() for p in postfix]
            return os_sorted([os.path.join(folder, f) for f in os.listdir(folder) if f[f.rfind(".")+1:].upper() in postfix])
    else:
        return []


# def load_json(json_path):
#     if ope(json_path):
#         with open(json_path, 'r') as f:
#             json_info = json.load(f)
#         return json_info
#     else:
#         raise FileNotFoundError(f"json file {json_path} not found")

def load_json(json_path):
    if ope(json_path):
        with open(json_path, 'r') as f:
            json_info = orjson.loads(f.read())
        return json_info
    else:
        raise FileNotFoundError(f"json file {json_path} not found")

def save_json(json_dict, json_path):
    with open(json_path, 'w') as f:
        json.dump(json_dict, f, indent=4)


def annotation2mask(annotation: dict, class2label_dict: dict, min_pixel=2):
    """
    将json文件读取的标注信息转化成mask.
    mask： 掩码图片
    label_names: 字典信息， key为标签的名字 value为标签的索引
    min_pixel:
    """
    shapes = annotation["shapes"]
    # shapes = sorted(shapes, key=lambda x: x['label'])
    width, height = int(annotation["width"]), int(annotation["height"])
    mask = np.zeros((height, width), dtype=np.uint8)
    for k, shape in shapes.items():
        if not isinstance(shape, dict):
            raise TypeError("annotation must be a dict, bug got {}".format(type(shape)))

        tmp_points = np.int0((shape["points"]))
        points = np.zeros((len(tmp_points)//2, 2), dtype=np.int32)
        points[:, 0] = tmp_points[0::2]
        points[:, 1] = tmp_points[1::2]
        if len(points) <=2: continue
        if cv2.contourArea(points) < min_pixel: continue  # 若小于最低像素，则不进行显示
        index = class2label_dict.get(shape["label"], None)
        if index is None: continue
        mask = cv2.fillPoly(mask,[points], index)
        holes = shape.get("holes", [])
        if holes is not None:
            for hole in holes:
                points = np.array(hole, dtype=np.int0)
                mask = cv2.fillPoly(mask, [points], 0)

    return mask

def read_image(ip:str, mode:str="BGR"):
    if not ope(ip):
        raise FileNotFoundError(f"image file {ip} not found")
    if ip.split('.')[-1].upper() not in IMAGE_POSTFIX:
        raise TypeError(f"{ip} ends with {ip.split('.')[-1].upper()} not supported in {IMAGE_POSTFIX}")
    image = cv2.imread(ip)
    if mode.upper() == "RGB":
        image = image[..., ::-1]

    return image


def map_execute(map_func, args, max_workers=15):
    """
    多进程任务处理功能：
    map_func: 要处理的函数
    map_args_list, 要处理的函数输入的参数
    num_mp: 多进程的数量
    use_log: 输出信息的log函数
    msg: 输出信息的内容的格式化字符，里面必须要有 {}/{},来记录进度
    """
    if max_workers == 0:
        result = [map_func(*arg) for arg in zip(*args)]
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            func_iter = pool.map(map_func, *args)
            result = [r for r in func_iter]
    return result

def async_execute(map_func, args, max_workers=15):
    """
    多线程分批处理数据：
    map_func: 要处理的函数
    map_args_list, 要处理的函数输入的参数
    num_mp: 开多少个线程进行处理
    log_info: 打印日志新的函数
    msg: 打印日志的信息说明
    """

    t = ThreadPoolExecutor(max_workers=max_workers)
    result = []
    func_iter = t.map(map_func, *args)

    for i, r in enumerate(func_iter):
        result.append(r)
    t.shutdown(wait=True)
    return result
