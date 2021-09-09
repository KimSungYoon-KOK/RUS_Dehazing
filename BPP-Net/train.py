import torch
import wandb
from tqdm import tqdm

from models import *
from metrics import *
from torch.utils.data import DataLoader
from HazeDataset import RESIDE_Beta_Train_Dataset

def train(max_epochs, model, train_loader):
    
    for epoch in range(max_epochs):
        i=1
        mse_epoch = 0.0
        ssim_epoch = 0.0
        psnr_epoch = 0.0
        unet_epoch = 0.0
        for batch in tqdm(train_loader):
            haze_images, dehaze_images = batch
            with torch.autograd.set_detect_anomaly(True):
                unet_loss, dis_loss, mse, ssim, psnr = model.process(haze_images.cuda(), dehaze_images.cuda())
                model.backward(unet_loss.cuda(), dis_loss.cuda())
            print('Epoch: '+str(epoch+1)+ ' || Batch: '+str(i)+ " || unet loss: "+str(unet_loss.cpu().item()) + " || dis loss: "+str(dis_loss.cpu().item()) + " || mse: "+str(mse.cpu().item()) + " | ssim:" + str(ssim.cpu().item()) + " | psnr:" + str(psnr))
            
            mse_epoch =  mse_epoch + mse.cpu().item() 
            ssim_epoch = ssim_epoch + ssim.cpu().item()
            psnr_epoch = psnr_epoch + psnr
            unet_epoch = unet_epoch + unet_loss.cpu().item()
            i=i+1
        
        print()
        mse_epoch = mse_epoch/i
        ssim_epoch = ssim_epoch/i
        psnr_epoch = psnr_epoch/i
        unet_epoch = unet_epoch/i
        graph_gloss.append(ssim_epoch)
        print("mse: + "+str(mse_epoch) + " | ssim: "+ str(ssim_epoch) + " | psnr:"+str(psnr_epoch) + " | unet:"+str(unet_epoch))
        print()
        
        wandb.log({"UNet Loss" : unet_epoch,
                   "MSE" : mse_epoch,
                   "SSIM": ssim_epoch,
                   "PSNR" : psnr_epoch,
                   "global_step" : epoch+1})
        

if __name__ == '__main__':
    # ============== Config Init ==============
    config_defaults = {
		'model_name' : 'BPP-Net'
	}
    wandb.init(config=config_defaults, project='Dehazing', entity='rus')
    wandb.run.name = config_defaults['model_name']
    config = wandb.config
    
    # ================ DataLoader ================

    train_dataset = RESIDE_Beta_Train_Dataset('D:/data/RESIDE-beta/train')
    train_loader = DataLoader(
                dataset=train_dataset,
                batch_size=1,
                num_workers=0,
                drop_last=True,
                shuffle=True
            )
    
    # ================ Creating the model ================
    graph_gloss = []
    input_unet_channel = 3
    output_unet_channel = 3
    input_dis_channel = 3
    max_epochs = 100
    DUNet = DU_Net(input_unet_channel ,output_unet_channel ,input_dis_channel).cuda()
    
    # ================ Training ================
    epochs = 150
    train(epochs, DUNet, train_loader)
    
    
    # ================ Saving weights ================
    path_of_generator_weight = 'weight/generator.pth'  #path for storing the weights of genertaor
    path_of_discriminator_weight = 'weight/discriminator.pth'  #path for storing the weights of discriminator
    DUNet.save_weight(path_of_generator_weight,path_of_discriminator_weight)