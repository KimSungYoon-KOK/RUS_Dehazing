# User warnings ignore
import warnings

from numpy.lib.function_base import diff

warnings.filterwarnings("ignore")

import os
os.environ['KMP_DUPLICATE_LIB_OK']='True'

import torch.nn as nn
import argparse
import cv2
import numpy as np
import random
from tqdm import tqdm
from torchvision.models import vgg16
from loss import LossNetwork as PerLoss
import torch.optim as optim

import torch
import wandb
from dpt.models import DPTDepthModel

from dataset import *
from torch.utils.data import DataLoader

from Module_Airlight.Airlight_Module import Airlight_Module
from Module_Metrics.Entropy_Module import Entropy_Module
from Module_Metrics.NIQE_Module import NIQE_Module
from Module_Metrics.metrics import get_ssim, get_psnr
from util import misc, save_log, utils
from validate_NYU_depth import compute_errors

def get_args():
    parser = argparse.ArgumentParser()
    # dataset parameters
    parser.add_argument('--dataset', required=False, default='RESIDE-beta',  help='dataset name')
    parser.add_argument('--dataRoot', type=str, default='D:/data/Dense_Haze/train',  help='data file path')
    parser.add_argument('--norm', action='store_true',  help='Image Normalize flag')
    
    # learning parameters
    parser.add_argument('--seed', type=int, default=101, help='Random Seed')
    parser.add_argument('--lr', type=float, default=0.00001, help='Learning Rage')
    parser.add_argument('--batchSize_train', type=int, default=16, help='train dataloader input batch size')
    parser.add_argument('--batchSize_val', type=int, default=16, help='test dataloader input batch size')
    parser.add_argument('--imageSize_W', type=int, default=256, help='the width of the resized input image to network')
    parser.add_argument('--imageSize_H', type=int, default=256, help='the height of the resized input image to network')
    parser.add_argument('--epochs', type=int, default=100, help='number of epochs to train for')
    parser.add_argument('--evalIter', type=int, default=10, help='interval for evaluating')
    parser.add_argument('--savePath', default='weights', help='folder to model checkpoints')
    parser.add_argument('--inputPath', default='input', help='input path')
    parser.add_argument('--outputPath', default='output_dehazed', help='dehazed output path')
    parser.add_argument('--device', default=torch.device('cuda' if torch.cuda.is_available() else 'cpu'))
    
    # model parameters
    parser.add_argument('--preTrainedModel', type=str, default='weights/dpt_hybrid_nyu-2ce69ec7.pt', help='pretrained DPT path')
    parser.add_argument('--backbone', type=str, default="vitb_rn50_384", help='DPT backbone')
    
    # test_stop_when_threshold parameters
    parser.add_argument('--save_log', action='store_true', help='log save flag')
    parser.add_argument('--saveORshow', type=str, default='show',  help='results show or save')
    parser.add_argument('--verbose', action='store_true', help='print log')
    parser.add_argument('--airlight_step_flag', action='store_true', help='flag of multi step airlight estimation')
    parser.add_argument('--betaStep', type=float, default=0.05, help='beta step')
    parser.add_argument('--stepLimit', type=int, default=250, help='Multi step limit')
    parser.add_argument('--metrics_module', type=str, default='Entropy_Module',  help='No Reference metrics method name')
    parser.add_argument('--metricsThreshold', type=float, default=0, help='Metrics threshold: Entropy(0.00), NIQUE(??)')
    parser.add_argument('--eps', type=float, default=1e-12, help='Epsilon value for non zero calculating')

    return parser.parse_args()
def evaluate(model, device, valid_loader, log_wandb, epoch):
    model.eval()
    
    #NYU {"0.0":0.0,"0.1":0.0,"0.2":0.0,"0.3":0.0,"0.5":0.0,"0.8":0.0}
    val_iters = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}
        
    abs_rel_list ={"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0} 
    sq_rel_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0} 
    rmse_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}
    rmse_log_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}
    a1_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}
    a2_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}  
    a3_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0} 
    
    score_lists = {"val_abs_rel_list":abs_rel_list,
                   "val_sq_rel_list":sq_rel_list,
                   "val_rmse_list":rmse_list,
                   "val_rmse_log_list":rmse_log_list,
                   "val_a1_list":a1_list,
                   "val_a2_list":a2_list,
                   "val_a3_list":a3_list}
    
    score_name_list = ["val_abs_rel_list",
                       "val_sq_rel_list", 
                       "val_rmse_list", 
                       "val_rmse_log_list", 
                       "val_a1_list", 
                       "val_a2_list", 
                       "val_a3_list"] 
    
    
    for batch in tqdm(valid_loader):
        hazy_images, clear_images , depth_images, _, gt_betas, haze_names = batch
        
        hazy_images = hazy_images.to(device)
        clear_images = clear_images.to(device)
        depth_images = depth_images.to(device)
        
        _, depth_pred = model.forward(hazy_images)
        
        gt_depth = depth_images.detach().cpu().numpy()
        depth_pred = depth_pred.detach().cpu().numpy()
        
        for i, haze_name in enumerate(haze_names):
            beta = str(gt_betas[i].item())
            
            val_iters[beta]+=1
            scores = compute_errors(gt_depth[i], depth_pred[i])
            for j, score in enumerate(scores):
                score_name = score_name_list[j]
                score_lists[score_name][beta] += score
    
    for score_name in score_name_list:
        score_list = score_lists[score_name]
        for beta, val_iter in val_iters.items():
            score_list[beta] /= val_iter
    
    score_lists["global_step"] = epoch
        
    if log_wandb:
        wandb.log(score_lists)


def train(model, device, train_loader, optim,loss_fun, log_wandb, epoch):
    if epoch==0:
        model.eval()
    else:
        model.train()
    
    #NYU {"0.0":0.0,"0.1":0.0,"0.2":0.0,"0.3":0.0,"0.5":0.0,"0.8":0.0}
    #RESIDE {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}
    
    train_iters = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}
    global_iter = 0
        
    abs_rel_list ={"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0} 
    sq_rel_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0} 
    rmse_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}
    rmse_log_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}
    a1_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}
    a2_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0}  
    a3_list = {"0.1":0.0,"0.2":0.0,"0.04":0.0,"0.06":0.0,"0.08":0.0,"0.12":0.0, "0.16":0.0} 
    
    score_lists = {"train_abs_rel_list":abs_rel_list,
                   "train_sq_rel_list":sq_rel_list,
                   "train_rmse_list":rmse_list,
                   "train_rmse_log_list":rmse_log_list,
                   "train_a1_list":a1_list,
                   "train_a2_list":a2_list,
                   "train_a3_list":a3_list}
    
    score_name_list = ["train_abs_rel_list",
                       "train_sq_rel_list", 
                       "train_rmse_list", 
                       "train_rmse_log_list", 
                       "train_a1_list", 
                       "train_a2_list", 
                       "train_a3_list"] 
    
    loss_sum = 0 
    for batch in tqdm(train_loader):
        optim.zero_grad()
        hazy_images, clear_images , depth_images, _, gt_betas, haze_names = batch
        
        hazy_images = hazy_images.to(device)
        clear_images = clear_images.to(device)
        depth_images = depth_images.to(device)
        
        _, depth_pred = model.forward(hazy_images)
        global_iter +=1
        

        loss = loss_fun(depth_pred, depth_images)
        if epoch!=0:
            loss.backward()
                
            optim.step()
        loss_sum += loss.item()
        
        
        gt_depth = depth_images.detach().cpu().numpy()
        depth_pred = depth_pred.detach().cpu().numpy()
        
        for i, haze_name in enumerate(haze_names):
            beta = str(gt_betas[i].item())
            train_iters[beta]+=1
            scores = compute_errors(gt_depth[i], depth_pred[i])
            for j, score in enumerate(scores):
                score_name = score_name_list[j]
                score_lists[score_name][beta] += score
    
    for score_name in score_name_list:
        score_list = score_lists[score_name]
        for beta, train_iter in train_iters.items():
            score_list[beta] /= train_iter
    
    
    loss_mean = loss_sum / global_iter
    score_lists["global_step"] = epoch
        
    if log_wandb:
        wandb.log(score_lists)
        wandb.log({"loss":loss_mean,
                   "global_step":epoch})

def run(model, train_loader, valid_loader, optim, epochs, device, log_wandb):
    
    loss_fun = nn.L1Loss().to(device)
    
    train(model,device,train_loader,optim,loss_fun,log_wandb,0)
    evaluate(model, device, valid_loader, log_wandb,0)
        
    for epoch in range(epochs):
        train(model,device,train_loader,optim,loss_fun,log_wandb,epoch+1)
        evaluate(model, device, valid_loader, log_wandb,epoch+1)
        
        weight_path = f'weights/dpt_hybrid_nyu-2ce69ec7_{epoch+1:03}.pt'  #path for storing the weights of genertaor
        torch.save(model.state_dict(), weight_path)

if __name__ == '__main__':
    
    log_wandb = False
    opt = get_args()
    opt.norm=True
    random.seed(opt.seed)
    torch.manual_seed(opt.seed)
    torch.cuda.manual_seed_all(opt.seed)
    
    config_defaults = {
        'model_name' : 'DPT_finetuning',
        'init_lr' : opt.lr,
        'epochs' : opt.epochs,
        'dataset' : 'RESIDE_beta_Dataset',
        'batch_size': opt.batchSize_train,
        'image_size': [opt.imageSize_W,opt.imageSize_H]}
    
    if log_wandb:
        wandb.init(config=config_defaults, project='Dehazing', entity='rus')
        wandb.run.name = config_defaults['model_name']
    
    model = DPTDepthModel(
        path = opt.preTrainedModel,
        scale=0.000150, shift=0.1378, invert=True,
        backbone=opt.backbone,
        non_negative=True,
        enable_attention_hooks=False,
    )
    
    model = model.to(memory_format=torch.channels_last)
    model.to(opt.device)

    #opt.dataRoot = 'D:/data/NYU/'
    #dataset_train = NYU_Dataset.NYU_Dataset_With_Notation(opt.dataRoot, [opt.imageSize_W, opt.imageSize_H],split='train', printName=False, returnName=True, norm=opt.norm)
    #loader_train = DataLoader(dataset=dataset_train, batch_size=opt.batchSize_train,num_workers=1, drop_last=False, shuffle=True)
    
    #dataset_valid = NYU_Dataset.NYU_Dataset_With_Notation(opt.dataRoot, [opt.imageSize_W, opt.imageSize_H],split='val', printName=False, returnName=True, norm=opt.norm)
    #loader_valid = DataLoader(dataset=dataset_valid, batch_size=opt.batchSize_val,num_workers=1, drop_last=False, shuffle=True)
    
    opt.dataRoot = 'D:/data/RESIDE_beta/'
    dataset_train = RESIDE_Beta_Dataset.RESIDE_Beta_Dataset_With_Notation(opt.dataRoot, [opt.imageSize_W, opt.imageSize_H],split='train', printName=False, returnName=True, norm=opt.norm)
    loader_train = DataLoader(dataset=dataset_train, batch_size=opt.batchSize_train,num_workers=1, drop_last=False, shuffle=True)
    
    dataset_valid = RESIDE_Beta_Dataset.RESIDE_Beta_Dataset_With_Notation(opt.dataRoot, [opt.imageSize_W, opt.imageSize_H],split='val', printName=False, returnName=True, norm=opt.norm)
    loader_valid = DataLoader(dataset=dataset_valid, batch_size=opt.batchSize_val,num_workers=1, drop_last=False, shuffle=True)
    
    
    
    optimizer = optim.Adam(model.parameters(),opt.lr, betas = (0.9, 0.999), eps=1e-08)
    
    run(model, loader_train, loader_valid, optimizer, opt.epochs, opt.device, log_wandb)