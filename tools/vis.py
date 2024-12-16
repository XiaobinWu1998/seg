import argparse
import os

import numpy as np

os.environ['CUDA_VISIBLE_DEVICES'] = '0'
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../'))

import cv2
from seg.runners import TRTRunner
from seg.utils import file_to_config, save_json
from os.path import join as opj
from tqdm import tqdm
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cfg', type=str, default='/workspace/mycode/03-seg/seg/workdir/test/20241216_140322/20241216_140322_trt.json')
    # parser.add_argument('--cfg', type=str, default='C:\mycode\mycode\seg\config\\train_local.json')
    args = parser.parse_args()
    return args


def main():
    args = parse_args()
    cfg_path = args.cfg
    cfg = file_to_config(cfg_path)
    trt_runner = TRTRunner(cfg)


    root = '/data/wuxiaobin/datasets/Seg/Wire'
    # /data/wuxiaobin/datasets/Seg/Wire/train/0010c3f7-2f2e-4086-92be-63b30bda3262.jpg
    # /data/wuxiaobin/datasets/Seg/Wire/faf3fe26-14b9-4ca8-a949-dd64096f0b84.jpg
    for tvs in ['train', 'valid']:
        tvsd = opj(root, tvs)
        rd = opj(root+'vis', tvs)
        os.makedirs(rd, exist_ok=True)
        names = [i for i in sorted(os.listdir(tvsd)) if i.endswith('.jpg')]
        for name in tqdm(names):
            ip = opj(tvsd, name)
            rp = opj(rd, name)
            jp = opj(rd, name.replace('.jpg', '.json'))
            image = cv2.imread(ip)
            images = [image]
            image_copy = image.copy()
            result = trt_runner(images)
            save_json(result, jp)
            info_dict = result[0]
            for cls, item in info_dict.items():
                for idx, item_info in item.items():
                    contours, area, score = item_info['contour'], item_info['area'], item_info['score']

                    text = f"{cls}_{area}_{score}"
                    org = (int(contours[0][0]), int(contours[0][1]))
                    fontFace = cv2.FONT_HERSHEY_SIMPLEX
                    fontScale = 1
                    color = (255, 255, 255)  # BGR格式，白色
                    thickness = 2

                    contours = np.array(contours, dtype=np.int32)[:, None, :]
                    cv2.drawContours(image_copy, [contours], 0, (0, 0, 255), thickness=2)
                    cv2.putText(image_copy, text, org, fontFace, fontScale, color, thickness)

            cv2.imwrite(rp, np.hstack([image, image_copy]))


if __name__ == '__main__':
    main()