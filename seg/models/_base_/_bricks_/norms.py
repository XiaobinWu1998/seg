import inspect
import torch.nn as nn

from torch.nn.modules.batchnorm import _BatchNorm
from torch.nn.modules.instancenorm import _InstanceNorm
from torch.nn import SyncBatchNorm

from seg.models.registry import NORMS
from seg.models.utils.common import is_tuple_of

NORMS.register_module('BN', module=nn.BatchNorm2d)
NORMS.register_module('BN1d', module=nn.BatchNorm1d)
NORMS.register_module('BN2d', module=nn.BatchNorm2d)
NORMS.register_module('BN3d', module=nn.BatchNorm3d)
NORMS.register_module('SyncBN', module=SyncBatchNorm)
NORMS.register_module('GN', module=nn.GroupNorm)
NORMS.register_module('LN', module=nn.LayerNorm)
NORMS.register_module('LayerNorm', module=nn.LayerNorm)
NORMS.register_module('IN', module=nn.InstanceNorm2d)
NORMS.register_module('IN1d', module=nn.InstanceNorm1d)
NORMS.register_module('IN2d', module=nn.InstanceNorm2d)
NORMS.register_module('IN3d', module=nn.InstanceNorm3d)


def build_norm_layer(cfg, num_features, postfix='', anonymous=False):
    """Build normalization layer.

    Parameters
    ----------
    cfg : dict
        The norm layer config, which should contain:
            - type (str): Layer type.
            - layer args: Args needed to instantiate a norm layer.
            - requires_grad (bool, optional): Whether stop gradient updates.
    num_features : int
        Number of input channels.
    postfix : {int, str}
        The postfix to be appended into norm abbreviation to create named layer.

    Returns
    -------
    (name, layer) : (str, nn.Module)
        The first element is the layer name consisting of abbreviation and postfix,
        e.g., bn1, gn. The second element is the created norm layer.
    """
    if not isinstance(cfg, dict):
        raise TypeError('cfg must be a dict')
    if 'type' not in cfg:
        raise KeyError('the cfg dict must contain the key "type"')
    cfg_ = cfg.copy()

    layer_type = cfg_.pop('type')
    if layer_type not in NORMS:
        raise KeyError(f'Unrecognized norm type {layer_type}')

    norm_layer = NORMS.get(layer_type)
    requires_grad = cfg_.pop('requires_grad', True)
    cfg_.setdefault('eps', 1e-5)
    if layer_type != 'GN':
        layer = norm_layer(num_features, **cfg_)
        if layer_type == 'SyncBN':
            layer._specify_ddp_gpu_num(1)
    else:
        assert 'num_groups' in cfg_
        layer = norm_layer(num_channels=num_features, **cfg_)

    for param in layer.parameters():
        param.requires_grad = requires_grad

    if anonymous:
        return layer
    else:
        abbr = abbreviation(norm_layer)
        assert isinstance(postfix, (int, str))
        name = abbr + str(postfix)
        return name, layer


def abbreviation(class_type):
    """Inference abbreviation from the class name.

    When we build a norm layer with `build_norm_layer()`, we want to preserve
    the norm type in variable names, e.g, self.bn1, self.gn. This method will
    inference the abbreviation to map class types to abbreviations.

    Rule 1: If the class has the property "_abbr_", return the property.
    Rule 2: If the parent class is _BatchNorm, GroupNorm, LayerNorm or
    InstanceNorm, the abbreviation of this layer will be "bn", "gn", "ln" and
    "in" respectively.
    Rule 3: If the class name contains "batch", "group", "layer" or "instance",
    the abbreviation of this layer will be "bn", "gn", "ln" and "in"
    respectively.
    Rule 4: Otherwise, the abbreviation falls back to "norm".

    Parameters
    ----------
    class_type : type
        The norm layer type.

    Returns
    -------
    abbr : str
        The inferred abbreviation.
    """
    if not inspect.isclass(class_type):
        raise TypeError(
            f'class_type must be a type, but got {type(class_type)}')
    if hasattr(class_type, '_abbr_'):
        return class_type._abbr_
    if issubclass(class_type, _InstanceNorm):
        return 'in'
    elif issubclass(class_type, _BatchNorm):
        return 'bn'
    elif issubclass(class_type, nn.GroupNorm):
        return 'gn'
    elif issubclass(class_type, nn.LayerNorm):
        return 'ln'
    else:
        class_name = class_type.__name__.lower()
        if 'batch' in class_name:
            return 'bn'
        elif 'group' in class_name:
            return 'gn'
        elif 'layer' in class_name:
            return 'ln'
        elif 'instance' in class_name:
            return 'in'
        else:
            return 'norm'


def is_norm(layer, exclude=None):
    """Check if a layer is a normalization layer.

    Parameters
    ----------
    layer : nn.Module
        The layer to be checked.
    exclude : {type, tuple[type]}
        Types to be excluded.

    Returns
    -------
    is_norm : bool
        Whether the layer is a norm layer.
    """
    if exclude is not None:
        if not isinstance(exclude, tuple):
            exclude = (exclude, )
        if not is_tuple_of(exclude, type):
            raise TypeError(
                f'"exclude" must be either None or type or a tuple of types, '
                f'but got {type(exclude)}: {exclude}')

    if exclude and isinstance(layer, exclude):
        return False

    all_norm_bases = (_BatchNorm, _InstanceNorm, nn.GroupNorm, nn.LayerNorm)
    return isinstance(layer, all_norm_bases)
