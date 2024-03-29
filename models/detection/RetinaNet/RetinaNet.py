import os
import sys

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

import torch
import torch.nn as nn
from torchvision.ops import nms
from models.detection.RetinaNet.neck import FPN
from models.detection.RetinaNet.loss import FocalLoss
from models.detection.RetinaNet.anchor import Anchors
from models.detection.RetinaNet.head import clsHead, regHead
from models.detection.RetinaNet.backbones.ResNet import ResNet
from models.detection.RetinaNet.utils.ClipBoxes import ClipBoxes
from models.detection.RetinaNet.backbones.DarkNet import DarkNet
from models.detection.RetinaNet.utils.BBoxTransform import BBoxTransform


# assert input annotations are [x_min, y_min, x_max, y_max]
class RetinaNet(nn.Module):
    def __init__(self,
                 backbones_type="resnet50",
                 num_classes=80,
                 planes=256,
                 pretrained=False,
                 training=False):
        super(RetinaNet, self).__init__()
        self.backbones_type = backbones_type
        # coco 80, voc 20
        self.num_classes = num_classes
        self.planes = planes
        self.training = training
        if backbones_type[:6] == 'resnet':
            self.backbone = ResNet(resnet_type=self.backbones_type,
                                   pretrained=pretrained)
        elif backbones_type[:7] == 'darknet':
            self.backbone = DarkNet(darknet_type=self.backbones_type)
        expand_ratio = {
            "resnet18": 1,
            "resnet34": 1,
            "resnet50": 4,
            "resnet101": 4,
            "resnet152": 4,
            "darknettiny": 0.5,
            "darknet19": 1,
            "darknet53": 2
        }

        C3_inplanes, C4_inplanes, C5_inplanes = \
            int(128 * expand_ratio[self.backbones_type]), \
            int(256 * expand_ratio[self.backbones_type]), \
            int(512 * expand_ratio[self.backbones_type])
        self.fpn = FPN(C3_inplanes=C3_inplanes,
                       C4_inplanes=C4_inplanes,
                       C5_inplanes=C5_inplanes,
                       planes=self.planes)

        self.cls_head = clsHead(inplanes=self.planes,
                                num_classes=self.num_classes)

        self.reg_head = regHead(inplanes=self.planes)

        self.anchors = Anchors()
        self.regressBoxes = BBoxTransform()
        self.clipBoxes = ClipBoxes()

        self.loss = FocalLoss()
        self.freeze_bn()

    def freeze_bn(self):
        '''Freeze BatchNorm layers.'''
        for layer in self.modules():
            if isinstance(layer, nn.BatchNorm2d):
                layer.eval()

    def forward(self, inputs):
        if self.training:
            img_batch, annots = inputs

        # inference
        else:
            img_batch = inputs

        [C3, C4, C5] = self.backbone(img_batch)

        del inputs
        features = self.fpn([C3, C4, C5])
        del C3, C4, C5
        # (batch_size, total_anchors_nums, num_classes)
        cls_heads = torch.cat([self.cls_head(feature) for feature in features], dim=1)
        # (batch_size, total_anchors_nums, 4)
        reg_heads = torch.cat([self.reg_head(feature) for feature in features], dim=1)

        del features

        anchors = self.anchors(img_batch)

        if self.training:
            return self.loss(cls_heads, reg_heads, anchors, annots)
        # inference
        else:
            transformed_anchors = self.regressBoxes(anchors, reg_heads)
            transformed_anchors = self.clipBoxes(transformed_anchors, img_batch)

            # scores
            finalScores = torch.Tensor([])

            # anchor id:0~79
            finalAnchorBoxesIndexes = torch.Tensor([]).long()

            # coordinates size:[...,4]
            finalAnchorBoxesCoordinates = torch.Tensor([])

            if torch.cuda.is_available():
                finalScores = finalScores.cuda()
                finalAnchorBoxesIndexes = finalAnchorBoxesIndexes.cuda()
                finalAnchorBoxesCoordinates = finalAnchorBoxesCoordinates.cuda()

            # num_classes
            for i in range(cls_heads.shape[2]):
                scores = torch.squeeze(cls_heads[:, :, i])
                scores_over_thresh = (scores > 0.05)
                if scores_over_thresh.sum() == 0:
                    # no boxes to NMS, just continue
                    continue
                scores = scores[scores_over_thresh]
                anchorBoxes = torch.squeeze(transformed_anchors)
                anchorBoxes = anchorBoxes[scores_over_thresh]
                anchors_nms_idx = nms(anchorBoxes, scores, 0.5)

                # use idx to find the scores of anchor
                finalScores = torch.cat((finalScores, scores[anchors_nms_idx]))
                # [0,0,0,...,1,1,1,...,79,79]
                finalAnchorBoxesIndexesValue = torch.tensor([i] * anchors_nms_idx.shape[0])

                if torch.cuda.is_available():
                    finalAnchorBoxesIndexesValue = finalAnchorBoxesIndexesValue.cuda()

                finalAnchorBoxesIndexes = torch.cat((finalAnchorBoxesIndexes, finalAnchorBoxesIndexesValue))
                # [...,4]
                finalAnchorBoxesCoordinates = torch.cat((finalAnchorBoxesCoordinates, anchorBoxes[anchors_nms_idx]))

        return finalScores, finalAnchorBoxesIndexes, finalAnchorBoxesCoordinates


if __name__ == "__main__":
    C = torch.randn([8, 3, 512, 512])
    annot = torch.randn([8, 15, 5])
    model = RetinaNet(backbones_type="darknet19", num_classes=80, pretrained=True, training=True)
    model = model.cuda()
    C = C.cuda()
    annot = annot.cuda()
    model = torch.nn.DataParallel(model).cuda()
    model.training = True
    out = model([C, annot])
    # if model.training == True out==loss
    # out = model([C, annot])
    # if model.training == False out== scores
    # out = model(C)
    for i in range(len(out)):
        print(out[i])

# Scores: torch.Size([486449])
# tensor([4.1057, 4.0902, 4.0597,  ..., 0.0509, 0.0507, 0.0507], device='cuda:0')
# Id: torch.Size([486449])
# tensor([ 0,  0,  0,  ..., 79, 79, 79], device='cuda:0')
# loc: torch.Size([486449, 4])
# tensor([[ 45.1607, 249.4807, 170.5788, 322.8085],
# [ 85.9825, 324.4150, 122.9968, 382.6297],
# [148.1854, 274.0474, 179.0922, 343.4529],
# ...,
# [222.5421,   0.0000, 256.3059,  15.5591],
# [143.3349, 204.4784, 170.2395, 228.6654],
# [208.4509, 140.1983, 288.0962, 165.8708]], device='cuda:0')
