from __future__ import print_function
import warnings
warnings.filterwarnings("ignore")
import argparse
import os
import sys
import random
import torch
import torch.nn as nn
import torch.nn.parallel
import torch.backends.cudnn as cudnn

cudnn.benchmark = True
cudnn.fastest = True
import torch.optim as optim
import torchvision.utils as vutils
from torch.autograd import Variable

from misc import *
import models.dehaze22  as net

import torchvision.models as models
from myutils import utils
import pdb


if __name__=='__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--dataset', required=False, default='pix2pix',  help='')
  parser.add_argument('--dataroot', required=False, default='', help='path to trn dataset')
  parser.add_argument('--valDataroot', required=False, default='', help='path to val dataset')
  parser.add_argument('--mode', type=str, default='B2A', help='B2A: facade, A2B: edges2shoes')
  parser.add_argument('--batchSize', type=int, default=1, help='input batch size')
  parser.add_argument('--valBatchSize', type=int, default=16, help='input batch size')
  parser.add_argument('--originalSize', type=int, default=286, help='the height / width of the original input image')
  parser.add_argument('--imageSize', type=int, default=256, help='the height / width of the cropped input image to network')
  parser.add_argument('--inputChannelSize', type=int, default=3, help='size of the input channels')
  parser.add_argument('--outputChannelSize', type=int, default=3, help='size of the output channels')
  parser.add_argument('--ngf', type=int, default=64)
  parser.add_argument('--ndf', type=int, default=64)
  parser.add_argument('--niter', type=int, default=400, help='number of epochs to train for')
  parser.add_argument('--lrD', type=float, default=0.0002, help='learning rate, default=0.0002')
  parser.add_argument('--lrG', type=float, default=0.0002, help='learning rate, default=0.0002')
  parser.add_argument('--annealStart', type=int, default=0, help='annealing learning rate start to')
  parser.add_argument('--annealEvery', type=int, default=400, help='epoch to reaching at learning rate of 0')
  parser.add_argument('--lambdaGAN', type=float, default=0.35, help='lambdaGAN')
  parser.add_argument('--lambdaIMG', type=float, default=1, help='lambdaIMG')
  parser.add_argument('--poolSize', type=int, default=50, help='Buffer size for storing previously generated samples from G')
  parser.add_argument('--wd', type=float, default=0.0000, help='weight decay in D')
  parser.add_argument('--beta1', type=float, default=0.5, help='beta1 for adam')
  parser.add_argument('--netG', default='', help="path to netG (to continue training)")
  parser.add_argument('--netD', default='', help="path to netD (to continue training)")
  parser.add_argument('--workers', type=int, help='number of data loading workers', default=1)
  parser.add_argument('--exp', default='sample', help='folder to output images and model checkpoints')
  parser.add_argument('--display', type=int, default=5, help='interval for displaying train-logs')
  parser.add_argument('--evalIter', type=int, default=100, help='interval for evauating(generating) images from valDataroot')
  parser.add_argument('--device', default=torch.device('cuda' if torch.cuda.is_available() else 'cpu'))
  opt = parser.parse_args()
  print(opt)

  create_exp_dir(opt.exp)
  opt.manualSeed = random.randint(1, 10000)
  # opt.manualSeed = 101
  random.seed(opt.manualSeed)
  torch.manual_seed(opt.manualSeed)
  torch.cuda.manual_seed_all(opt.manualSeed)
  print("Random Seed: ", opt.manualSeed)
  opt.workers=1


  # get dataloader
  dataloader = getLoader(opt.dataset,
                        opt.dataroot,
                        opt.originalSize,
                        opt.imageSize,
                        opt.batchSize,
                        opt.workers,
                        mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5),
                        split='train',
                        shuffle=True,
                        seed=opt.manualSeed)


  opt.dataset='pix2pix_val2'
  valDataloader = getLoader(opt.dataset,
                            opt.valDataroot,
                            opt.imageSize, #opt.originalSize,
                            opt.imageSize,
                            opt.valBatchSize,
                            opt.workers,
                            mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5),
                            split='val',
                            shuffle=False,
                            seed=opt.manualSeed)

  # get logger
  trainLogger = open(f'{opt.exp}/train.log', 'w')


  # Two directional gradient loss function
  def gradient(y):
      gradient_h=torch.abs(y[:, :, :, :-1] - y[:, :, :, 1:])
      gradient_y=torch.abs(y[:, :, :-1, :] - y[:, :, 1:, :])

      return gradient_h, gradient_y


  ngf = opt.ngf
  ndf = opt.ndf
  inputChannelSize = opt.inputChannelSize
  outputChannelSize= opt.outputChannelSize

  # get models
  netG = net.dehaze(inputChannelSize, outputChannelSize, ngf)


  netG.apply(weights_init)
  if opt.netG != '':
    netG.load_state_dict(torch.load(opt.netG))
  print(netG)


  netD = net.D(inputChannelSize + outputChannelSize, ndf)

  netD.apply(weights_init)
  if opt.netD != '':
    netD.load_state_dict(torch.load(opt.netD))



  netG.train()
  netD.train()


  criterionBCE = nn.BCELoss()
  criterionCAE = nn.L1Loss()

  target= torch.FloatTensor(opt.batchSize, outputChannelSize, opt.imageSize, opt.imageSize)
  input = torch.FloatTensor(opt.batchSize, inputChannelSize, opt.imageSize, opt.imageSize)




  val_target= torch.FloatTensor(opt.valBatchSize, outputChannelSize, opt.imageSize, opt.imageSize)
  val_input = torch.FloatTensor(opt.valBatchSize, inputChannelSize, opt.imageSize, opt.imageSize)
  label_d = torch.FloatTensor(opt.batchSize)


  target = torch.FloatTensor(opt.batchSize, outputChannelSize, opt.imageSize, opt.imageSize)
  input = torch.FloatTensor(opt.batchSize, inputChannelSize, opt.imageSize, opt.imageSize)
  trans = torch.FloatTensor(opt.batchSize, inputChannelSize, opt.imageSize, opt.imageSize)
  ato = torch.FloatTensor(opt.batchSize, inputChannelSize, opt.imageSize, opt.imageSize)


  val_target = torch.FloatTensor(opt.valBatchSize, outputChannelSize, opt.imageSize, opt.imageSize)
  val_input = torch.FloatTensor(opt.valBatchSize, inputChannelSize, opt.imageSize, opt.imageSize)
  val_trans = torch.FloatTensor(opt.valBatchSize, inputChannelSize, opt.imageSize, opt.imageSize)
  val_ato = torch.FloatTensor(opt.valBatchSize, inputChannelSize, opt.imageSize, opt.imageSize)




  # NOTE: size of 2D output maps in the discriminator
  sizePatchGAN = 30
  real_label = 1
  fake_label = 0

  # image pool storing previously generated samples from G
  imagePool = ImagePool(opt.poolSize)

  # NOTE weight for L_cGAN and L_L1 (i.e. Eq.(4) in the paper)
  lambdaGAN = opt.lambdaGAN
  lambdaIMG = opt.lambdaIMG

  netD.to(opt.device)
  netG.to(opt.device)
  criterionBCE.to(opt.device)
  criterionCAE.to(opt.device)


  target, input, trans, ato = target.to(opt.device), input.to(opt.device), trans.to(opt.device), ato.to(opt.device)
  val_target, val_input, val_trans, val_ato = val_target.to(opt.device), val_input.to(opt.device), val_trans.to(opt.device), val_ato.to(opt.device)

  target = Variable(target)
  input = Variable(input)
  # input = Variable(input, requires_grad=False)

  trans = Variable(trans)
  ato = Variable(ato)

  # Initialize VGG-16
  vgg = models.vgg16(pretrained=True)
  vgg.to(opt.device)


  label_d = Variable(label_d.to(opt.device))

  # get randomly sampled validation images and save it
  val_iter = iter(valDataloader)
  data_val = next(val_iter)

  val_input_cpu, val_target_cpu, val_tran_cpu, val_ato_cpu, imgname = data_val

  val_target_cpu, val_input_cpu = val_target_cpu.float().to(opt.device), val_input_cpu.float().to(opt.device)
  val_tran_cpu, val_ato_cpu = val_tran_cpu.float().to(opt.device), val_ato_cpu.float().to(opt.device)


  val_target.resize_as_(val_target_cpu).copy_(val_target_cpu)
  val_input.resize_as_(val_input_cpu).copy_(val_input_cpu)
  vutils.save_image(val_target, f'{opt.exp}/real_target.png', normalize=True)
  vutils.save_image(val_input, f'{opt.exp}/real_input.png', normalize=True)


  # pdb.set_trace()
  # get optimizer
  optimizerD = optim.Adam(netD.parameters(), lr = opt.lrD, betas = (opt.beta1, 0.999), weight_decay=opt.wd)
  optimizerG = optim.Adam(netG.parameters(), lr = opt.lrG, betas = (opt.beta1, 0.999), weight_decay=0.00005)

  # NOTE training loop
  ganIterations = 0
  for epoch in range(opt.niter):
    if epoch > opt.annealStart:
      adjust_learning_rate(optimizerD, opt.lrD, epoch, None, opt.annealEvery)
      adjust_learning_rate(optimizerG, opt.lrG, epoch, None, opt.annealEvery)


    for i, data in enumerate(dataloader, 0):

      input_cpu, target_cpu, trans_cpu, ato_cpu, imgname = data
      batch_size = target_cpu.size(0)

      target_cpu, input_cpu, trans_cpu, ato_cpu = target_cpu.float().to(opt.device), input_cpu.float().to(opt.device), trans_cpu.float().to(opt.device), ato_cpu.float().to(opt.device)


      # get paired data
      target.resize_as_(target_cpu).copy_(target_cpu)
      input.resize_as_(input_cpu).copy_(input_cpu)
      trans.resize_as_(trans_cpu).copy_(trans_cpu)
      ato.resize_as_(ato_cpu).copy_(ato_cpu)

      # target_cpu, input_cpu = target_cpu.float().to(opt.device), input_cpu.float().to(opt.device)
      # # NOTE paired samples
      # target.resize_as_(target_cpu).copy_(target_cpu)
      # input.resize_as_(input_cpu).copy_(input_cpu)
      # trans.resize_as_(trans_cpu).copy_(trans_cpu)


      for p in netD.parameters():
        p.requires_grad = True

      netD.zero_grad()
      sizePatchGAN=62

      x_hat, tran_hat, atp_hat, dehaze21 = netG(input)


      # max_D first
      for p in netD.parameters():
        p.requires_grad = True
      netD.zero_grad()

      # NOTE: compute L_cGAN in eq.(2)
      label_d.resize_((batch_size, 1, sizePatchGAN, sizePatchGAN)).fill_(real_label)
      output = netD(torch.cat([trans, target], 1)) # conditional
      errD_real = criterionBCE(output, label_d)
      errD_real.backward()
      D_x = output.data.mean()

      fake = x_hat.detach()
      fake = Variable(imagePool.query(fake.data))

      fake_trans = tran_hat.detach()
      fake_trans = Variable(imagePool.query(fake_trans.data))

      label_d.data.fill_(fake_label)
      output = netD(torch.cat([fake_trans, fake], 1)) # conditional
      errD_fake = criterionBCE(output, label_d)
      errD_fake.backward()
      D_G_z1 = output.data.mean()
      errD = errD_real + errD_fake
      optimizerD.step() # update parameters

      # prevent computing gradients of weights in Discriminator
      for p in netD.parameters():
        p.requires_grad = False


      netG.zero_grad() # start to update G



      # compute L_L1 (eq.(4) in the paper
      L_img_ = criterionCAE(x_hat, target)
      L_img = lambdaIMG * L_img_
      if lambdaIMG != 0:
        L_img.backward(retain_graph=True)



      # NOTE compute L1 for transamission map
      L_tran_ = criterionCAE(tran_hat, trans)

      # NOTE compute gradient loss for transamission map
      gradie_h_est, gradie_v_est=gradient(tran_hat)
      gradie_h_gt, gradie_v_gt=gradient(trans)

      L_tran_h = criterionCAE(gradie_h_est, gradie_h_gt)
      L_tran_v = criterionCAE(gradie_v_est, gradie_v_gt)

      L_tran =  lambdaIMG * (L_tran_+ 2*L_tran_h+ 2* L_tran_v)

      if lambdaIMG != 0:
          L_tran.backward(retain_graph=True)

      # NOTE feature loss for transmission map
      features_content = vgg(trans)
      f_xc_c = Variable(features_content[0].data, requires_grad=False)

      features_y = vgg(tran_hat)
      content_loss =  0.8*lambdaIMG* criterionCAE(features_y[0], f_xc_c)
      content_loss.backward(retain_graph=True)

      # Edge Loss 2
      features_content = vgg(trans)
      f_xc_c = Variable(features_content[0].data, requires_grad=False)

      features_y = vgg(tran_hat)
      content_loss1 =  0.8*lambdaIMG* criterionCAE(features_y[0], f_xc_c)
      content_loss1.backward(retain_graph=True)


      # NOTE compute L1 for atop-map
      L_ato_ = criterionCAE(atp_hat, ato)
      L_ato =  lambdaIMG * L_ato_
      if lambdaIMG != 0:
          L_ato_.backward(retain_graph=True)





      # compute  gan_loss for the joint discriminator
      label_d.data.fill_(real_label)
      output = netD(torch.cat([tran_hat, x_hat], 1))
      errG_ = criterionBCE(output, label_d)
      errG = lambdaGAN * errG_

      if lambdaGAN != 0:
          (errG).backward()


      optimizerG.step()
      ganIterations += 1

      if (ganIterations % opt.display) == 0:
        print(f'[{epoch}/{opt.niter}][{i}/{len(dataloader)}] L_D: {L_tran_.item()} L_img: {L_tran_.item()} L_G: {L_img.item()} D(x): {L_img.item()} D(G(z)): {L_img.item()} / {L_img.item()}')
        sys.stdout.flush()
        trainLogger.write(f'{i}\t{L_img.item()}\t{L_img.item()}\t{L_img.item()}\t{L_img.item()}\t{L_img.item()}\t{L_img.item()}\n')
        trainLogger.flush()
      if ganIterations % opt.evalIter == 0:
        val_batch_output = torch.FloatTensor(val_input.size()).fill_(0)
        for idx in range(val_input.size(0)):
          single_img = val_input[idx,:,:,:].unsqueeze(0)
          val_inputv = Variable(single_img, volatile=True)
          x_hat_val, x_hat_val2, x_hat_val3, dehaze21 = netG(val_inputv)
          val_batch_output[idx,:,:,:].copy_(dehaze21.data.squeeze(0))
        vutils.save_image(val_batch_output,  
                          f'{opt.exp}/generated_epoch_{epoch:08d}_iter{ganIterations:08d}.png', 
                          normalize=False, scale_each=False)

    if epoch % 2 == 0:
          torch.save(netG.state_dict(), f'{opt.exp}/netG_epoch_{epoch}.pth')
          torch.save(netD.state_dict(), f'{opt.exp}/netD_epoch_{epoch}.pth')
  trainLogger.close()
