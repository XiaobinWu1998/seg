import numpy as np
import torch
import cv2
from seg.export.converters import TRTModel
from seg.transforms.compose import Compose


class TRTRunner:
    def __init__(self, cfg):
        self.transform = Compose(cfg['transform'])
        self.shape_labels = sorted(cfg['shape_labels'])
        self._class_label_dict = self.get_class_label_dict()
        self._class_label_dict.update(dict(background=0))
        self.model = TRTModel(**cfg['trt'])

    def get_class_label_dict(self):
        return {name: i + 1 for i, name in enumerate(self.shape_labels)}  # background = 0

    def get_label_class_dict(self):
        return {cls: label for label, cls in self._class_label_dict.items()}

    @property
    def class2label(self):
        return self._class_label_dict

    def _preprocess(self, datas: list) -> torch.Tensor:
        '''

        Args:
            datas: list[np.array(H, W, 3)]

        Returns:
            images (torch.Tensor): [N, C, H, W]
        '''
        images, shapes = [], []
        for image in datas:
            shapes.append(image.shape[:2])
            data = {'image': image}
            image = self.transform(**data)['image']
            images.append(image.unsqueeze(0))
        images = torch.concat(images, dim=0)
        return images, shapes

    def _postprocess(self, model_probs, shapes):
        # TDDO 分割结果在哪里 resize
        probs = [cv2.resize(prob, shape[::-1]) for prob, shape in zip(model_probs, shapes)]
        preds = [np.argmax(prob, axis=-1) for prob in probs]
        probs = [np.max(prob, axis=-1) for prob in probs]
        result = []
        for pred, prob in zip(preds, probs):
            result_dict = {}
            for cls, label in self.class2label.items():
                if cls == 'background':
                    continue
                mask = (pred == label).astype(np.uint8)
                if np.sum(mask) == 0:
                    continue
                result_dict[cls] = {}
                contours, hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for idx, contour in enumerate(contours):
                    prob_mask = np.zeros_like(prob, dtype=np.uint8)
                    prob_mask = cv2.fillPoly(prob_mask, [contour[:, 0, :]], 1)
                    area = int(np.sum(prob_mask))
                    if area < 4:
                        continue
                    prob_map = prob_mask * prob
                    score = np.sum(prob_map) / area
                    int_contour = np.squeeze(contour).tolist()
                    result_dict[cls][idx] = {
                        "contour": int_contour,
                        "area": area,
                        "score": round(float(score), 4)
                    }
            result.append(result_dict)
        return result

    def __call__(self, images):
        images, shapes = self._preprocess(images)
        probs = self.model(images.cuda())[0].cpu().numpy().astype(np.float32).transpose(0, 2, 3, 1)
        result = self._postprocess(probs, shapes)
        return result
