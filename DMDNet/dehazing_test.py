# User warnings ignore
import warnings

from torch._C import wait

warnings.filterwarnings("ignore")

import os
os.environ['KMP_DUPLICATE_LIB_OK']='True'

import argparse
import cv2
import numpy as np
import random
from tqdm import tqdm
import csv

import torch
from models.depth_models import DPTDepthModel
from models.air_models import UNet

from dataset import *
from torch.utils.data import DataLoader

from utils.metrics import get_ssim, get_psnr
from utils import misc, save_log, util
from utils.util import compute_errors
from utils.entropy_module import Entropy_Module
from utils.airlight_module import Airlight_Module
from glob import glob
from utils.io import *


def get_args():
    parser = argparse.ArgumentParser()
    # dataset parameters
    # NYU
    # parser.add_argument('--dataset', required=False, default='NYU',  help='dataset name')
    # parser.add_argument('--scale', type=float, default=0.000305,  help='depth scale')
    # parser.add_argument('--shift', type=float, default= 0.1378,  help='depth shift')
    # parser.add_argument('--preTrainedModel', type=str, default='weights/depth_weights/dpt_hybrid_nyu-2ce69ec_RESIDE_017_RESIDE_002', help='pretrained DPT path')
    # parser.add_argument('--preTrainedAirModel', type=str, default='weights/air_weights/Air_UNet_RESIDE_V0_epoch_16.pt', help='pretrained Air path')
    
    # RESIDE
    parser.add_argument('--dataset', required=False, default='RESIDE',  help='dataset name')
    parser.add_argument('--scale', type=float, default=0.000150,  help='depth scale')
    parser.add_argument('--shift', type=float, default= 0.1378,  help='depth shift')
    parser.add_argument('--preTrainedModel', type=str, default='weights/depth_weights/dpt_hybrid_nyu-2ce69ec_RESIDE_017_RESIDE_003_RESIDE_004.pt', help='pretrained DPT path')
    parser.add_argument('--preTrainedAirModel', type=str, default='weights/air_weights/Air_UNet_RESIDE_V0_epoch_16.pt', help='pretrained Air path')
    
    # learning parameters
    parser.add_argument('--seed', type=int, default=101, help='Random Seed')
    parser.add_argument('--norm', action='store_true',  help='Image Normalize flag')
    parser.add_argument('--imageSize_W', type=int, default=256, help='the width of the resized input image to network')
    parser.add_argument('--imageSize_H', type=int, default=256, help='the height of the resized input image to network')
    parser.add_argument('--device', default=torch.device('cuda' if torch.cuda.is_available() else 'cpu'))
    
    # model parameters
    parser.add_argument('--backbone', type=str, default="vitb_rn50_384", help='DPT backbone')
    
    # run parameters
    parser.add_argument('--betaStep', type=float, default=0.01, help='beta step')
    parser.add_argument('--stepLimit', type=int, default=30, help='Multi step limit')
    parser.add_argument('--eps', type=float, default=1e-12, help='Epsilon value for non zero calculating')
    return parser.parse_args()
    


def run(opt, model, airlight_module, entropy_module, imgs, transform):
    model.eval()
    # airlight_module.eval()

    for img in tqdm(imgs):
        hazy = transform({"image": cv2.cvtColor(cv2.imread(img), cv2.COLOR_BGR2RGB) / 255.0})["image"]
        
        haze_name = os.path.basename(img)

        hazy_images = torch.Tensor(hazy).unsqueeze(0).to(opt.device)
        cur_hazy = hazy_images

        # with torch.no_grad():
        #     airlight = airlight_model.forward(cur_hazy)

        airlight = airlight_module.get_airlight(cur_hazy, opt.norm)


        airlight = util.air_denorm(opt.dataset,opt.norm,airlight)

        folder_name = f'D:/data/output_dehaze/pred_DMD_RealHaze/{haze_name[:-5]}'
        if not os.path.exists(folder_name):
            os.mkdir(folder_name)

        f = open(f'D:/data/output_dehaze/pred_DMD_RealHaze/{haze_name[:-5]}/{haze_name[:-5]}.csv', 'w', newline = '')
        wr = csv.writer(f)

        for step in range(0, opt.stepLimit+1):
            with torch.no_grad():
                cur_depth = model.forward(cur_hazy)
            cur_hazy = util.denormalize(cur_hazy,opt.norm)

            trans = torch.exp(cur_depth*opt.betaStep*-1)
            prediction = (cur_hazy - airlight) / (trans + opt.eps) + airlight
            entropy, _, _ = entropy_module.get_cur(cur_hazy[0].detach().cpu().numpy().transpose(1,2,0))
            wr.writerow([step]+[entropy])
            
            result_haze = cur_hazy[0].detach().cpu().numpy().transpose(1,2,0)
            result_depth = (cur_depth[0]/torch.max(cur_depth[0])).repeat(3,1,1).detach().cpu().numpy().transpose(1,2,0)
            result_img = (np.hstack([result_haze, result_depth])*255).astype(np.uint8)

            # cv2.imshow("airlight", np.full([opt.imageSize_W, opt.imageSize_W],airlight.detach().cpu()))
            # cv2.imshow("depth", cur_depth[0][0].detach().cpu().numpy()/10)
            # cv2.imshow("result", result_img)
            cv2.imwrite(f"{folder_name}/{haze_name[:-5]}_{step*opt.betaStep:1.3f}.jpg",cv2.cvtColor(result_img,cv2.COLOR_RGB2BGR))
        
            cur_hazy = util.normalize(prediction[0].detach().cpu().numpy().transpose(1,2,0),opt.norm).unsqueeze(0).to(opt.device)
        f.close()


if __name__ == '__main__':
    opt = get_args()
    opt.norm = True
    opt.verbose = True
    
    #opt.seed = random.randint(1, 10000)
    random.seed(opt.seed)
    torch.manual_seed(opt.seed)
    torch.cuda.manual_seed_all(opt.seed)
    print("=========| Option |=========\n", opt)
    
    
    model = DPTDepthModel(
        path = opt.preTrainedModel,
        scale=opt.scale, shift=opt.shift, invert=True,
        backbone=opt.backbone,
        non_negative=True,
        enable_attention_hooks=False,
    )
    model = model.to(memory_format=torch.channels_last)
    model.to(opt.device)
    
        
    airlight_model = UNet([opt.imageSize_W, opt.imageSize_H], in_channels=3, out_channels=1, bilinear=True)
    checkpoint = torch.load(opt.preTrainedAirModel)
    airlight_model.load_state_dict(checkpoint['model_state_dict'])
    airlight_model.to(opt.device)

    hazy_imgs = glob('input/RESIDE_REALHAZE/*.jpeg')

    imgs=[]
    for hazy_img in hazy_imgs:
        imgs.append(hazy_img)
    
    transform = make_transform([opt.imageSize_W, opt.imageSize_H], norm=opt.norm)
    metrics_module = Entropy_Module()
    airlight_module = Airlight_Module()

    run(opt, model, airlight_module, metrics_module, imgs, transform)