import os
from torch.utils.data import Dataset
from seg.utils.io import IMAGE_POSTFIX, opj, ope, load_json, annotation2mask, read_image
from seg.transforms import Compose
from seg.loggers import build_logger
from .registry import DATASETS


@DATASETS.register_module()
class DPST(Dataset):
    def __init__(self,
                 root=None,
                 mode=None,
                 transform=None,
                 image_labels=[],
                 shape_labels=[],
                 logger=None,
                 ):
        assert ope(root), f"root: {root} not exist"
        self.root = root
        assert mode in ['train', 'valid', 'test'], f"mode must be 'train' or 'valid' or 'test'"
        self.mode = mode
        self.transform = transform
        self.image_labels = sorted(image_labels)
        self.shape_labels = sorted(shape_labels)
        self.logger = logger
        self._class_label_dict = self.get_class_label_dict()
        self._class_label_dict.update(dict(background=0))
        self._label_class_dict = self.get_label_class_dict()
        self.label_set = set()
        self.data_info = []
        self.load_data_paths()
        self.length = len(self.data_info)

    def __len__(self):
        return self.length

    def load_data_paths(self):
        self.logger.info(f"Loaded {self.mode} Dataset")
        data_dir = opj(self.root, self.mode)
        image_names = sorted([i for i in os.listdir(data_dir) if i.split('.')[-1].upper() in IMAGE_POSTFIX])
        for name in image_names:
            ip = opj(data_dir, name)
            jp = opj(data_dir, name.split('.')[0] + '.dpst')
            json_info = load_json(jp)
            label_set = self.parse_json_info(json_info)
            for label in label_set:
                self.label_set.add(label)
                if label not in self.shape_labels and label != 'background':
                    raise f"self.shape_labels are {self.shape_labels}, but got unknown label: {label} in {jp}, please check json info or configs"
            data_info = {
                'ip': ip,
                'json_info': json_info
            }
            self.data_info.append(data_info)

        self.logger.info(f"Loaded {self.mode} Dataset {len(self.data_info)} images, label class: {len(self.label_set)}")

    def get_class_label_dict(self):
        return {name: i + 1 for i, name in enumerate(self.shape_labels)}  # background = 0

    def get_label_class_dict(self):
        return {cls: label for label, cls in self._class_label_dict.items()}

    @property
    def class2label(self):
        return self._class_label_dict

    @property
    def label2class(self):
        return self._label_class_dict

    def prepare_one_data(self, item):
        data_info = self.data_info[item].copy()
        ip = data_info.pop('ip')
        json_info = data_info.pop('json_info')
        image = read_image(ip)
        mask = annotation2mask(json_info, self.class2label)
        data_info['image'] = image
        data_info['mask'] = mask
        return data_info

    def parse_json_info(self, json_info):
        label_set = set()
        for k, shape in json_info["shapes"].items():
            label = shape.get("label", None)
            if label is None: continue
            label_set.add(label)
        if len(label_set) == 0:
            return ['background']
        return list(label_set)

    # def prepare_data(self, data_info):
    #     return data_info.pop('image'), data_info.pop('mask')

    def __getitem__(self, item):
        data_info = self.prepare_one_data(item)
        if self.transform:
            data_info = self.transform(**data_info)
        return data_info


if __name__ == '__main__':
    logger_cfg = dict(
        handlers=(
            dict(type='StreamHandler', level='INFO'),
            dict(type='FileHandler', level='INFO'),
        ),
    )
    default_cfg = dict(workdir='/workspace/mycode/03-seg/seg/workdir/test')
    logger = build_logger(logger_cfg, default_cfg)
    cfg = {
        'root': '/data/wuxiaobin/datasets/Seg/Wire',
        'mode': 'train',
        'shape_labels': [
            "AFM",
            "AOC",
            "AOG",
            "EXC",
            "EXN",
            "EXN_rough",
            "OX",
            "SCT",
            "posun"
        ],
        # 'transforms':[
        #     {
        #         "type": "Resize",
        #         "always_apply": True,
        #         "width": 512,
        #         "height": 512,
        #         "padding": 0
        #     },
        #     {
        #         "type": "Normalize",
        #         "always_apply": True,
        #         "scale": 1.0
        #     },
        #     {
        #         "type": "ToTensor",
        #         "always_apply": True
        #     }
        # ]
        'logger': logger
    }
    train_dataset = DPST(**cfg)
    for data in train_dataset:
        image, mask = data['image'], data['mask']
