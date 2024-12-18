import torch
import torch.nn.functional as F
import math
import torch.nn as nn
import numpy as np
from seg.models.registry import *
from seg.losses import build_loss
from seg.models._base_._bricks_ import *

def fill_up_weights(up):
    w = up.weight.data
    f = math.ceil(w.size(2) / 2)
    c = (2 * f - 1 - f % 2) / (2. * f)
    for i in range(w.size(2)):
        for j in range(w.size(3)):
            w[:, 0, i, j] = \
                (1 - math.fabs(i / f - c)) * (1 - math.fabs(j / f - c))


class IDAUP(nn.Module):

    def __init__(self, kernel, out_dim, channels, up_factors,
                 norm_cfg=dict(type='BN', requires_grad=True),
                 act_cfg=dict(type='ReLU6', inplace=True),
                 upsample_cfg=dict(type="bilinear", scale_factor=2),
                 order=('conv', 'norm', 'act'),
                 **kwargs
                 ):
        super(IDAUP, self).__init__()
        self.channels = channels
        self.out_dim = out_dim

        for i, c in enumerate(channels):
            if c == out_dim:
                proj = nn.Identity()
            else:
                proj = ConvModule(c, out_dim, kernel_size=1, stride=1, norm_cfg=norm_cfg, act_cfg=act_cfg, order=order)
            f = int(up_factors[i])
            if f == 1:
                up = nn.Identity()
            else:
                # if use_deconv:
                #     up = nn.ConvTranspose2d(out_dim, out_dim, f * 2, stride=f, padding=f // 2,
                #                             output_padding=0, groups=out_dim, bias=False)
                #     fill_up_weights(up)
                # else:
                #     # up = nn.Upsample(scale_factor=f, mode=up_mode, align_corners=align_corners)
                #     up = build_upsample_layer(upsample_cfg)
                if upsample_cfg.get("type") == "deconv":
                    upsample_cfg["in_channels"] = out_dim
                    upsample_cfg["out_channels"] = out_dim
                    upsample_cfg["kernel_size"] = f * 2
                    upsample_cfg["stride"] = f
                    upsample_cfg["padding"] = f // 2
                    upsample_cfg["groups"] = out_dim
                    upsample_cfg["output_padding"] = 0
                    upsample_cfg["bias"] = False
                elif  upsample_cfg.get("type") == "pixel_shuffle":
                    upsample_cfg["in_channels"] = out_dim
                    upsample_cfg["out_channels"] = out_dim
                    upsample_cfg["scale_factor"] = f
                    upsample_cfg["upsample_kernel"] = upsample_cfg.get("upsample_kernel", 3)

                up = build_upsample_layer(upsample_cfg)
                if upsample_cfg.get("type") == "deconv":
                    fill_up_weights(up)

            setattr(self, 'proj_' + str(i), proj)
            setattr(self, 'up_' + str(i), up)

        for i in range(1, len(channels)):
            node = ConvModule(out_dim * 2, out_dim, kernel_size=kernel, stride=1,
                              padding=kernel // 2,
                              norm_cfg=norm_cfg, act_cfg=act_cfg,order=order)

            setattr(self, 'node_' + str(i), node)

        self.init_weights()

    def forward(self, layers):
        assert len(self.channels) == len(layers), \
            '{} vs {} layers'.format(len(self.channels), len(layers))

        for i, l in enumerate(layers):
            upsample = getattr(self, 'up_' + str(i))
            project = getattr(self, 'proj_' + str(i))
            layers[i] = upsample(project(l))

        x = layers[0]
        y = []
        for i in range(1, len(layers)):
            node = getattr(self, 'node_' + str(i))
            x = node(torch.cat([x, layers[i]], dim=1))
            y.append(x)
        return x, y

    def init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()


class DLAUP(nn.Module):
    def __init__(self, channels, scales=(1, 2, 4, 8, 16),
                 in_channels=None,
                 norm_cfg=dict(type='BN', requires_grad=True),
                 act_cfg=dict(type='ReLU6'),
                 upsample_cfg=dict(type="bilinear", scale_factor=2),
                 order=('conv', 'norm', 'act'),
                 **kwargs
                 ):
        super(DLAUP, self).__init__()
        if in_channels is None:
            in_channels = channels
        channels = list(channels)
        scales = np.array(scales, dtype=int)
        for i in range(len(channels) - 1):
            j = -i - 2
            setattr(self, 'ida_{}'.format(i),
                    IDAUP(3, channels[j], in_channels[j:],
                          scales[j:] // scales[j], norm_cfg=norm_cfg, act_cfg=act_cfg,
                          upsample_cfg=upsample_cfg, order=order
                          ))
            scales[j + 1:] = scales[j]
            in_channels[j + 1:] = [channels[j] for _ in channels[j + 1:]]

    def forward(self, layers, out_list=False):
        layers = list(layers)
        assert len(layers) > 1
        if out_list:
            outs = []
        for i in range(len(layers) - 1):
            ida = getattr(self, 'ida_{}'.format(i))
            x, y = ida(layers[-i - 2:])
            layers[-i - 1:] = y
            if out_list:
                outs.append(x)

        return outs if out_list else x


@HEADS.register_module()
class DLAHead(nn.Module):

    def __init__(self, num_classes,
                 in_channels=[16, 32, 128, 256, 512, 1024],
                 norm_cfg=dict(type='BN', requires_grad=True),
                 act_cfg=dict(type='ReLU', inplace=True),
                 loss=dict(
                     type='CrossEntropyLoss',
                     use_sigmoid=False,
                     loss_weight=1.0),
                 ignore_label=None,
                 align_corners=False,
                 dropout=0.,
                 sampler=None,
                 order=('conv', 'norm', 'act'),
                 upsample_cfg=dict(type="bilinear", scale_factor=2),
                 **kwargs):
        super(DLAHead, self).__init__()

        self.num_classes = num_classes

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
        self.num_classes = num_classes

        scales = [2 ** i for i in range(len(in_channels))]
        self.dla_up = DLAUP(in_channels, scales=scales,
                            norm_cfg=norm_cfg,
                            act_cfg=act_cfg,
                            upsample_cfg=upsample_cfg,
                            order=order
                            )
        up_factor = 2

        self.up = build_upsample_layer(dict(type="bilinear", scale_factor=up_factor))

        self.fc = nn.Sequential(
            nn.Dropout2d(dropout),
            nn.Conv2d(in_channels[0], num_classes, kernel_size=1,
                      stride=1, padding=0, bias=True))

        if sampler is not None:
            # self.sampler = build_pixel_sampler(sampler, context=self)
            self.sampler = None
        else:
            self.sampler = None

        self.init_weights()

    def forward(self, x, return_feat=False, **kwargs):

        feat = self.dla_up(x)
        logits = self.fc(feat)
        if return_feat:
            return logits, feat
        else:
            return logits

    def init_weights(self):

        for ly in self.children():
            if isinstance(ly, nn.Conv2d):
                nn.init.kaiming_normal_(ly.weight, a=1)
                if not ly.bias is None: nn.init.constant_(ly.bias, 0)

        for m in self.fc.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
                m.bias.data.fill_(-math.log((1-0.01) / 0.01))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

    def losses(self, seg_logit, seg_label, weight=None):
        """Compute segmentation loss."""
        if self.sampler is not None:
            seg_weight = self.sampler.sample(seg_logit, seg_label)
        else:
            seg_weight = weight

        loss = dict()
        seg_label = seg_label.squeeze(1)
        input_size = seg_label.shape[1:]
        seg_logit = F.interpolate(input=seg_logit,
                           size=input_size,
                           mode='bilinear',
                           align_corners=self.align_corners)

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
        return loss

    def forward_train(self, inputs, gt_semantic_seg, weight=None, **kwargs):
        """Forward function for training.

        Parameters
        ----------
        inputs : list[Tensor]
            List of multi-level img features.
        gt_semantic_seg : Tensor
            Semantic segmentation masks
            used if the architecture supports semantic segmentation task.
        weight: Tensor
            image weight for calculate loss.
        Returns
        -------
        dict[str, Tensor]
            a dictionary of loss components
        """
        feat = None
        if kwargs.get("return_feat", False):
            seg_logits, feat = self.forward(inputs, **kwargs)
        else:
            seg_logits = self.forward(inputs, **kwargs)
        losses = self.losses(seg_logits, gt_semantic_seg, weight)
        return losses if feat is None else (losses, feat)

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
        return self.forward(inputs, **kwargs)

    def losses_change(self, seg_logit, seg_label):
        """
        change detection use num class is 1,
        """
        loss = dict()
        seg_logit = F.interpolate(
            input=seg_logit,
            size=seg_label.shape[1:],
            mode='bilinear',
            align_corners=self.align_corners)
        loss['loss'] = self.loss_decode(seg_logit, seg_label)
        return loss
