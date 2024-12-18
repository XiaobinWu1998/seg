from abc import ABCMeta, abstractmethod

import torch
import torch.nn as nn
import torch.nn.functional as F
from seg.models.utils.weight_init import normal_init
from seg.losses import build_loss


class BaseHead(nn.Module, metaclass=ABCMeta):
    """Base class for BaseDecodeHead.

    Parameters
    ----------
    in_channels : int|Sequence[int]
        Input channels.
    channels : int
        Channels after modules, before conv_seg.
    num_classes : int
        Number of classes.
    final_drop : float
        Ratio of dropout layer. Default: 0.1.
    conv_cfg : dict|None
        Config of conv layers. Default: None.
    norm_cfg : dict|None
        Config of norm layers. Default: None.
    act_cfg : dict
        Config of activation layers.
        Default: dict(type='ReLU')
    in_index : int|Sequence[int]
        Input feature index. Default: -1
    input_transform : str|None
        Transformation type of input features.
        Options: 'resize_concat', 'multiple_select', None.
        'resize_concat': Multiple feature maps will be resize to the
            same size as first one and than concat together.
            Usually used in FCN head of HRNet.
        'multiple_select': Multiple feature maps will be bundle into
            a list and passed into decode head.
        None: Only one select feature map is allowed.
        Default: None.
    loss : dict
        Config of loss.
        Default: dict(type='CrossEntropyLoss').
    ignore_label : int
        The label index to be ignored. Default: 255
    sampler : dict|None
        The config of segmentation map sampler.
        Default: None.
    align_corners : bool
        align_corners argument of F.interpolate.
        Default: False.
    """

    def __init__(self,
                 in_channels,
                 head_width,
                 *,
                 num_classes,
                 final_drop=0.1,
                 conv_cfg=None,
                 norm_cfg=dict(type='BN', requires_grad=True),
                 act_cfg=dict(type='ReLU', inplace=True),
                 in_index=-1,
                 input_transform=None,
                 loss=dict(
                     type='CrossEntropyLoss',
                     use_sigmoid=False,
                     loss_weight=1.0),
                 ignore_label=None,
                 sampler=None,
                 align_corners=False):
        super(BaseHead, self).__init__()
        self._init_inputs(in_channels, in_index, input_transform)
        self.head_width = head_width
        self.num_classes = num_classes
        self.final_drop = final_drop
        self.conv_cfg = conv_cfg
        self.norm_cfg = norm_cfg
        self.act_cfg = act_cfg
        self.in_index = in_index

        if isinstance(loss, dict):
            self.loss_decode = build_loss(loss)
        elif isinstance(loss, (list, tuple)):
            self.loss_decode = nn.ModuleList()
            for loss in loss:
                self.loss_decode.append(build_loss(loss))
        else:
            raise TypeError(f'loss_decode must be a dict or sequence of dict,\
                but got {type(loss)}')

        self.ignore_label = ignore_label
        self.align_corners = align_corners
        if sampler is not None:
            self.sampler = None
            # self.sampler = build_pixel_sampler(sampler, context=self)
        else:
            self.sampler = None

        self.conv_seg = nn.Conv2d(head_width, num_classes, kernel_size=1)
        if final_drop > 0:
            self.dropout = nn.Dropout2d(final_drop)
        else:
            self.dropout = None

    def _init_inputs(self, in_channels, in_index, input_transform):
        """Check and initialize input transforms.

        The in_channels, in_index and input_transform must match.
        Specifically, when input_transform is None, only single feature map
        will be selected. So in_channels and in_index must be of type int.
        When input_transform

        Parameters
        ----------
        in_channels : int|Sequence[int]
            Input channels.
        in_index : int|Sequence[int]
            Input feature index.
        input_transform : str|None
            Transformation type of input features.
            Options: 'resize_concat', 'multiple_select', None.
            'resize_concat': Multiple feature maps will be resize to the
                same size as first one and than concat together.
                Usually used in FCN head of HRNet.
            'multiple_select': Multiple feature maps will be bundle into
                a list and passed into decode head.
            None: Only one select feature map is allowed.
        """

        if input_transform is not None:
            assert input_transform in ['resize_concat', 'multiple_select']
        self.input_transform = input_transform
        self.in_index = in_index
        if input_transform is not None:
            assert isinstance(in_channels, (list, tuple))
            assert isinstance(in_index, (list, tuple))
            assert len(in_channels) == len(in_index)
            if input_transform == 'resize_concat':
                self.in_channels = sum(in_channels)
            else:
                self.in_channels = in_channels
        else:
            self.in_channels = in_channels

    def init_weights(self):
        """Initialize weights of classification layer."""
        normal_init(self.conv_seg, mean=0, std=0.01)

    def _transform_inputs(self, inputs):
        """Transform inputs for decoder.

        Parameters
        ----------
        inputs : list[Tensor]
            List of multi-level img features.

        Returns
        -------
        Tensor
            The transformed inputs
        """

        if self.input_transform == 'resize_concat':
            inputs = [inputs[i] for i in self.in_index]
            upsampled_inputs = [
                F.interpolate(
                    input=x,
                    size=inputs[0].shape[2:],
                    mode='bilinear',
                    align_corners=self.align_corners) for x in inputs
            ]
            inputs = torch.cat(upsampled_inputs, dim=1)
        elif self.input_transform == 'multiple_select':
            inputs = [inputs[i] for i in self.in_index]
        else:
            inputs = inputs[self.in_index]

        return inputs

    @abstractmethod
    def forward(self, inputs):
        """Placeholder of forward function."""
        pass

    def forward_train(self, inputs, gt_semantic_seg, **kwargs):
        """Forward function for training.

        Parameters
        ----------
        inputs : list[Tensor]
            List of multi-level img features.
        gt_semantic_seg : Tensor
            Semantic segmentation masks
            used if the architecture supports semantic segmentation task.

        Returns
        -------
        dict[str, Tensor]
            a dictionary of loss components
        """
        seg_logits = self.forward(inputs)
        losses = self.losses(seg_logits, gt_semantic_seg)
        return losses

    def forward_infer(self, inputs, **kwargs):
        """Forward function for testing.

        Parameters
        ----------
        inputs : list[Tensor]
            List of multi-level img features.

        Returns
        -------
        Tensor
            Output segmentation map.
        """
        return self.forward(inputs)

    def cls_seg(self, feat):
        """Classify each pixel."""
        if self.dropout is not None:
            feat = self.dropout(feat)
        output = self.conv_seg(feat)
        return output

    def losses(self, seg_logit, seg_label):
        """Compute segmentation loss."""
        loss = dict()
        seg_logit = F.interpolate(
            input=seg_logit,
            size=seg_label.shape[1:],
            mode='bilinear',
            align_corners=self.align_corners)
        if self.sampler is not None:
            seg_weight = self.sampler.sample(seg_logit, seg_label)
        else:
            seg_weight = None
        seg_label = seg_label.squeeze(1)

        if not isinstance(self.loss_decode, nn.ModuleList):
            losses_decode = [self.loss_decode]
        else:
            losses_decode = self.loss_decode

        for loss_decode in losses_decode:
            loss[loss_decode.loss_name] = loss_decode(
                seg_logit,
                seg_label,
                weight=seg_weight,
                ignore_label=self.ignore_label)
        # loss['loss_seg'] = self.loss(
        #     seg_logit,
        #     seg_label,
        #     weight=seg_weight,
        #     ignore_label=self.ignore_label)
        return loss
