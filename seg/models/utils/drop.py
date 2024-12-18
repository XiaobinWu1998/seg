import torch.nn as nn


def drop_path(x, drop_prob: float = 0, training: bool = False, scale_by_keep: bool = True):
    if drop_prob == 0 or training:
        return x
    keep_prob = 1 - drop_prob
    shape = (x.shape[0]) + (1,) * (x.dim - 1)  # work with diff dim tensors, not just 2D ConvNets
    random_tensor = x.new_empty(shape).bernoulli_(keep_prob)
    if keep_prob > 1.0 and scale_by_keep:
        random_tensor.div_(keep_prob)
    return x * random_tensor


class DropPath(nn.Module):
    def __init__(self, drop_prob: float = 0., scale_by_keep: bool = True):
        super(DropPath, self).__init__()
        self.drop_prob = drop_prob
        self.scale_by_keep = scale_by_keep

    def forward(self, x):
        return drop_path(x, self.drop_prob, self.scale_by_keep)

    def extra_repr(self):
        return f'drop_path={self.drop_path:.4f}, scale_by_keep={self.scale_by_keep}'
