import os
from PIL import Image
import numpy as np
from tqdm import tqdm
from dataset.NYU_Dataset import NYU_Dataset_clear
from torch.utils.data import DataLoader

def clear2hazy(clear, airlight, depth, beta):
    trans = np.exp(-beta * depth)
    
    airlight_image = []
    for i in range(3):
        temp_air = np.full((clear.shape[1], clear.shape[2]), airlight[i])
        airlight_image.append(temp_air)
    airlight_image = np.array(airlight_image)/255.0

    hazy = (clear * trans) + (airlight_image * (1 - trans))
    hazy = np.rint(hazy*255).astype(np.uint8)
    hazy = np.clip(hazy, 0, 255)
    
    return hazy

def save_hazy(path, hazy, airlight, beta, fileName, show=False):
    save_path = f"{path}/hazy/NYU_{airlight}_{beta}"
    if not os.path.exists(save_path):
        os.makedirs(save_path)
    save_path += f'/{fileName}_{airlight}_{beta}.jpg'
    
    if len(hazy) == 3:
        hazy = hazy.transpose(1,2,0)
    
    if show:
        Image.fromarray(hazy).show()
    Image.fromarray(hazy).save(save_path)
    

if __name__ == '__main__':
    dataRoot = 'C:/Users/IIPL/Desktop/data/NYU'
    
    for split in ['/train', '/val']:
        path = dataRoot + split
        dataset = NYU_Dataset_clear(path)
        dataloader = DataLoader(dataset=dataset, batch_size=1, num_workers=2, drop_last=False, shuffle=False)
        
        for data in tqdm(dataloader):
            clear = data[0].squeeze().numpy()
            GT_depth = data[1].squeeze().numpy()
            fileName = data[2][0]
            
            # (212, 191, 107), (204, 184, 87), (191, 199, 150), (181, 189, 143)
            airlight_list = [[212, 191, 107], [204, 184, 87], [191, 199, 150], [181, 189, 143]]
            # airlight_list = [0.3, 0.6, 0.9]
            beta_list = [0.1, 0.2, 0.3, 0.5, 0.8]
            for i, airlight in enumerate(airlight_list):
                for beta in beta_list:
                    hazy = clear2hazy(clear, airlight, GT_depth, beta)
                    save_hazy(path, hazy, i, beta, fileName)
                