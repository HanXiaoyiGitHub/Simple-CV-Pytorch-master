import os
import logging
import argparse
import warnings

warnings.filterwarnings('ignore')

import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

import time
import torch
import torchvision
import torch.nn.parallel
from torchvision import transforms
from utils.get_logger import get_logger
from torch.utils.data import DataLoader
from models.classification.lenet5 import lenet5
from models.classification.alexnet import alexnet
from models.classification.googlenet import googlenet
from models.classification.utils.accuracy import accuracy
from models.classification.mobilenet_v3 import MobileNet_v3
from models.classification.mobilenet_v2 import mobilenet_v2
from models.classification.vgg import vgg11, vgg13, vgg16, vgg19
from models.classification.utils.AverageMeter import AverageMeter
from utils.path import log, CheckPoints, ImageNet_EVAL_ROOT, CIFAR_ROOT, classification_evaluate, \
    classification_eval_log
from models.classification.shufflenet import shufflenet_v2_x0_5, shufflenet_v2_x1_0, shufflenet_v2_x1_5, \
    shufflenet_v2_x2_0
from models.classification.resnet import resnet18, resnet34, resnet50, resnet101, resnet152, resnext50_32x4d, \
    resnext101_32x8d


def parse_args():
    parser = argparse.ArgumentParser(description='PyTorch classification Evaluation')
    parser.add_mutually_exclusive_group()
    parser.add_argument('--dataset',
                        type=str,
                        default='ImageNet',
                        choices=['ImageNet', 'CIFAR'],
                        help='ImageNet,CIFAR')
    parser.add_argument('--dataset_root',
                        type=str,
                        default=ImageNet_EVAL_ROOT,
                        choices=[ImageNet_EVAL_ROOT, CIFAR_ROOT],
                        help='Dataset root directory path')
    parser.add_argument('--basenet',
                        type=str,
                        default='shufflenet',
                        choices=['resnet', 'vgg', 'lenet', 'alexnet', 'googlenet', 'resnext', 'mobilenet',
                                 'shufflenet'],
                        help='Pretrained base model')
    parser.add_argument('--depth',
                        type=int,
                        default=5,
                        help='BaseNet depth, including: LeNet of 5, AlexNet of 0, VGG of 11, 13, 16, 19, ResNet of 18, 34, 50, 101, 152, ResNext of 50, 101, GoogLeNet of 0, MobileNet of 2, 3, ShuffleNet of 5, 10, 15, 20')
    parser.add_argument('--batch_size',
                        type=int,
                        default=32,
                        help='Batch size for training')
    parser.add_argument('--evaluate',
                        type=str,
                        default=classification_evaluate,
                        help='Checkpoint state_dict file to evaluate training from')
    parser.add_argument('--num_workers',
                        type=int,
                        default=8,
                        help='Number of workers user in dataloading')
    parser.add_argument('--cuda',
                        type=str,
                        default=True,
                        help='Use CUDA to eval model')
    parser.add_argument('--save_folder',
                        type=str,
                        default=CheckPoints,
                        help='Directory for saving checkpoint models')
    parser.add_argument('--log_folder',
                        type=str,
                        default=log,
                        help='Log Folder')
    parser.add_argument('--log_name',
                        type=str,
                        default=classification_eval_log,
                        help='Log Name')
    parser.add_argument('--num_classes',
                        type=int,
                        default=1000,
                        help='the number classes, like ImageNet:1000, cifar:10')
    parser.add_argument('--image_size',
                        type=int,
                        default=224,
                        help='image size, like ImageNet:224, cifar:32')

    return parser.parse_args()


args = parse_args()

# 1. Torch choose cuda or cpu
if torch.cuda.is_available():
    if args.cuda:
        torch.set_default_tensor_type('torch.cuda.FloatTensor')
    if not args.cuda:
        print("WARNING: It looks like you have a CUDA device, but you aren't using it" +
              "\n You can set the parameter of cuda to True.")
        torch.set_default_tensor_type('torch.FloatTensor')
else:
    torch.set_default_tensor_type('torch.FloatTensor')

if os.path.exists(args.save_folder) is None:
    os.mkdir(args.save_folder)

# 2. Log
get_logger(args.log_folder, args.log_name)
logger = logging.getLogger(args.log_name)


def eval():
    # vgg16, alexnet and lenet5 need to resize image_size, because of fc.
    if args.basenet == 'vgg' or args.basenet == 'alexnet' or args.basenet == 'googlenet':
        args.image_size = 224
    elif args.basenet == 'lenet':
        args.image_size = 32

    # 3. Ready dataset
    if args.dataset == 'ImageNet':
        if args.dataset_root == CIFAR_ROOT:
            raise ValueError("Must specify dataset_root if specifying dataset ImageNet")
        elif os.path.exists(ImageNet_EVAL_ROOT) is None:
            raise ValueError("WARNING: Using default ImageNet dataset_root because " +
                             "--dataset_root was not specified.")

        dataset = torchvision.datasets.ImageFolder(
            root=args.dataset_root,
            transform=torchvision.transforms.Compose([
                transforms.Resize((args.image_size,
                                   args.image_size)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                     std=[0.229, 0.224, 0.225]),
            ]))

    elif args.dataset == 'CIFAR':
        if args.dataset_root == ImageNet_EVAL_ROOT:
            raise ValueError('Must specify dataset_root if specifying dataset CIFAR')
        elif args.dataset_root is None:
            raise ValueError("Must provide --dataset_root when training on CIFAR")

        dataset = torchvision.datasets.CIFAR10(
            root=args.dataset_root, train=False,
            transform=torchvision.transforms.Compose([
                transforms.Resize((args.image_size,
                                   args.image_size)),
                torchvision.transforms.ToTensor()]))

    else:
        raise ValueError('Dataset type not understood (must be ImageNet or CIFAR), exiting.')

    dataloader = torch.utils.data.DataLoader(dataset=dataset, batch_size=args.batch_size,
                                             shuffle=True, num_workers=args.num_workers,
                                             pin_memory=False, generator=torch.Generator(device='cuda'))

    top1 = AverageMeter()
    top5 = AverageMeter()

    # 4. Define to mode
    if args.basenet == 'lenet':
        if args.depth == 5:
            model = lenet5(num_classes=args.num_classes)
        else:
            raise ValueError('Unsupported LeNet depth!')

    elif args.basenet == 'alexnet':
        if args.depth == 0:
            model = alexnet(num_classes=args.num_classes)
        else:
            raise ValueError('Unsupported AlexNet depth!')

    elif args.basenet == 'googlenet':
        if args.depth == 0:
            model = googlenet(num_classes=args.num_classes,
                              aux_logits=False)
        else:
            raise ValueError('Unsupported GoogLeNet depth!')

    elif args.basenet == 'vgg':
        if args.depth == 11:
            model = vgg11(num_classes=args.num_classes)
        elif args.depth == 13:
            model = vgg13(num_classes=args.num_classes)
        elif args.depth == 16:
            model = vgg16(num_classes=args.num_classes)
        elif args.depth == 19:
            model = vgg19(num_classes=args.num_classes)
        else:
            raise ValueError('Unsupported VGG depth!')

    elif args.basenet == 'resnet':
        if args.depth == 18:
            model = resnet18(num_classes=args.num_classes)
        elif args.depth == 34:
            model = resnet34(num_classes=args.num_classes)
        elif args.depth == 50:
            model = resnet50(num_classes=args.num_classes)  # False means the models is not trained
        elif args.depth == 101:
            model = resnet101(num_classes=args.num_classes)
        elif args.depth == 152:
            model = resnet152(num_classes=args.num_classes)
        else:
            raise ValueError('Unsupported ResNet depth!')

    elif args.basenet == 'resnext':
        if args.depth == 50:
            model = resnext50_32x4d(num_classes=args.num_classes)
        elif args.depth == 101:
            model = resnext101_32x8d(num_classes=args.num_classes)
        else:
            raise ValueError('Unsupported ResNeXt depth!')

    elif args.basenet == 'mobilenet':
        if args.depth == 2:
            model = mobilenet_v2(num_classes=args.num_classes)
        elif args.depth == 3:
            model = MobileNet_v3(num_classes=args.num_classes, type='large')
        else:
            raise ValueError('Unsupported MobileNet depth!')

    elif args.basenet == 'shufflenet':
        if args.depth == 5:
            model = shufflenet_v2_x0_5(num_classes=args.num_classes)
        elif args.depth == 10:
            model = shufflenet_v2_x1_0(num_classes=args.num_classes)
        elif args.depth == 15:
            model = shufflenet_v2_x1_5(num_classes=args.num_classes)
        elif args.depth == 20:
            model = shufflenet_v2_x2_0(num_classes=args.num_classes)
        else:
            raise ValueError('Unsupported ShuffleNet depth!')

    else:
        raise ValueError('Unsupported model type!')

    if args.cuda:
        if torch.cuda.is_available():
            model = model.cuda()
            model = torch.nn.DataParallel(model).cuda()
    else:
        model = torch.nn.DataParallel(model)

        # 5. Loading model
    if args.evaluate:
        other, ext = os.path.splitext(args.evaluate)
        if ext == '.pkl' or '.pth':
            print('Loading weights into state dict...')
            model_evaluate_load = os.path.join(args.save_folder, args.evaluate)
            model_evaluate_load = torch.load(model_evaluate_load)
            if args.basenet == 'googlenet':
                model_evaluate_load = {k: v for k, v in model_evaluate_load.items() if "aux" not in k}
            model.load_state_dict(model_evaluate_load)
        else:
            print('Sorry only .pth and .pkl files supported.')
    elif args.evaluate is None:
        raise ValueError("Sorry, you should load weights! ")

    model.eval()

    # 6. Length
    iter_size = len(dataset) // args.batch_size
    print("len(dataset): {}, iter_size: {}".format(len(dataset), iter_size))
    logger.info(f"args - {args}")
    t0 = time.time()
    iteration = 0

    # 7. Test
    with torch.no_grad():
        torch.cuda.empty_cache()
        # 8. Load test data
        for data in dataloader:
            iteration += 1
            images, targets = data
            if args.cuda:
                images, targets = images.cuda(), targets.cuda()

            # 9. Forward
            outputs = model(images)

            # 10. measure accuracy and record loss
            acc1, acc5 = accuracy(outputs, targets, topk=(1, 5))
            top1.update(acc1.item(), images.size(0))
            top5.update(acc5.item(), images.size(0))

            logger.info(
                f"iteration: {iteration}, top1 acc: {acc1.item():.2f}%, top5 acc: {acc5.item():.2f}%. ")

        t1 = time.time()
        m = (t1 - t0) // 60
        s = (t1 - t0) % 60
        print("It took a total of {}m{}s to complete the evaluating.".format(int(m), int(s)))
    return top1.avg, top5.avg


if __name__ == '__main__':
    torch.multiprocessing.set_start_method('spawn')
    logger.info("Program started")
    top1, top5 = eval()
    print("top1 acc: {}, top5 acc: {}".format(top1, top5))
    logger.info("Done!")
