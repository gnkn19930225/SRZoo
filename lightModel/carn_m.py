import torch
import torch.nn as nn
import math

'''
    This is PyTorch implementation of Paper: 'Fast, Accurate, and Lightweight Super-Resolution with Cascading
    Residual Network'. The official code is in https://github.com/nmhkahn/CARN-pytorch. 
'''

def make_model(args, parent=False):
    return E_CARN(args)

class MeanShift(nn.Conv2d):
    def __init__(self, rgb_mean, rgb_std, sign=-1):
        super(MeanShift, self).__init__(3, 3, kernel_size=1)
        std = torch.Tensor(rgb_std)
        self.weight.data = torch.eye(3).view(3, 3, 1, 1)
        self.weight.data.div_(std.view(3, 1, 1, 1))
        self.bias.data = sign * 255. * torch.Tensor(rgb_mean)
        self.bias.data.div_(std)
        self.requires_grad = False

class Upsampler(nn.Sequential):
    def __init__(self, scale, n_feats, act, group):
        m = []
        if (scale & (scale - 1)) == 0:
            for _ in range(int(math.log(scale, 2))):
                m.append(nn.Conv2d(n_feats, 4 * n_feats, 3, padding=1, groups=group))
                m.append(nn.PixelShuffle(2))
                if act: m.append(nn.ReLU(True))
        elif scale == 3:
            m.append(nn.Conv2d(n_feats, 9 * n_feats, 3, padding=1, groups=group))
            m.append(nn.PixelShuffle(3))
            if act is not None: m.append(act)
        else:
            raise NotImplementedError

        super(Upsampler, self).__init__(*m)

# Effective ResidualBlock
class EResidual_block(nn.Module):
    def __init__(self, n_feats, kernel_size, act, group):
        super(EResidual_block, self).__init__()
        self.conv1 = nn.Conv2d(n_feats, n_feats, kernel_size, 1, kernel_size//2, groups=group)
        self.conv2 = nn.Conv2d(n_feats, n_feats, kernel_size, 1, kernel_size//2, groups=group)
        self.conv3 = nn.Conv2d(n_feats, n_feats, 1, 1, 0)

        self.act = act

    def forward(self, x):
        out = self.act(self.conv1(x))
        out = self.act(self.conv2(out))
        out = self.act(self.conv3(out) + x)
        return out

# Cascade Residual Block
class CARB(nn.Module):
    def __init__(self, n_feats, kernel_size, act, group):
        super(CARB, self).__init__()
        self.b = EResidual_block(n_feats, kernel_size, act, group)

        self.c1 = nn.Conv2d(n_feats * 2, n_feats, 1, 1, 0)
        self.c2 = nn.Conv2d(n_feats * 3, n_feats, 1, 1, 0)
        self.c3 = nn.Conv2d(n_feats * 4, n_feats, 1, 1, 0)
        self.act =act

    def forward(self, x):
        b1 = self.b(x)
        c1 = torch.cat([x, b1], dim = 1)
        o1 = self.act(self.c1(c1))

        b2 = self.b(o1)
        c2 = torch.cat([c1, b2], dim = 1)
        o2 = self.act(self.c2(c2))

        b3 = self.b(o2)
        c3 = torch.cat([c2, b3], dim = 1)
        o3 = self.act(self.c3(c3))

        return o3

class E_CARN(nn.Module):
    def __init__(self):
        super(E_CARN, self).__init__()

        n_colors = 3
        n_feats = 64
        kernel_size = 3
        scale = 4
        group = 4
        self.act = act = nn.ReLU(True)

        # RGB mean for DIV2K
        rgb_mean = (0.4488, 0.4371, 0.4040)
        rgb_std = (1.0, 1.0, 1.0)
        self.sub_mean = MeanShift(rgb_mean, rgb_std)
        self.add_mean = MeanShift(rgb_mean, rgb_std, 1)

        # feature shallow extraction layer
        self.head = nn.Conv2d(n_colors, n_feats, kernel_size, padding=kernel_size // 2)

        # middle feature extraction layer
        self.b1 = CARB(n_feats, kernel_size, act, group)
        self.b2 = CARB(n_feats, kernel_size, act, group)
        self.b3 = CARB(n_feats, kernel_size, act, group)

        self.c1 = nn.Conv2d(n_feats * 2, n_feats, 1, 1, 0)
        self.c2 = nn.Conv2d(n_feats * 3, n_feats, 1, 1, 0)
        self.c3 = nn.Conv2d(n_feats * 4, n_feats, 1, 1, 0)

        # upsample and reconstruction layer
        self.tail = nn.Sequential(*[
            Upsampler(scale, n_feats, act=None, group=group),
            nn.Conv2d(n_feats, n_colors, kernel_size=3, padding=kernel_size // 2)
        ])

    def forward(self, x):
        x = self.sub_mean(x)
        x = self.head(x)

        b1 = self.b1(x)
        c1 = torch.cat([x, b1], dim=1)
        o1 = self.act(self.c1(c1))

        b2 = self.b2(o1)
        c2 = torch.cat([c1, b2], dim=1)
        o2 = self.act(self.c2(c2))

        b3 = self.b3(o2)
        c3 = torch.cat([c2, b3], dim=1)
        o3 = self.act(self.c3(c3))

        x = self.tail(o3)
        x = self.add_mean(x)
        return x

from torchstat import stat
net = E_CARN()
stat(net, (3, 10, 10))