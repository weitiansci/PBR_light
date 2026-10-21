import os
import cv2
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt

file_name="test_matcolor.png"
img = Image.open(file_name)
height, width = img.size
img_normal = np.zeros((height, width, 4), dtype=np.uint8)
img_normal[:, :, 0] = 127
img_normal[:, :, 1] = 127
img_normal[:, :, 2] = 255
img_normal[:, :, 3] = 255
img_depth = np.zeros((height, width, 4), dtype=np.uint8)
img_rgba = np.zeros((height, width, 4), dtype=np.uint8)


os.makedirs("output/Depth/result", exist_ok=True)
os.makedirs("output/Normal", exist_ok=True)
os.makedirs("output/RGBA", exist_ok=True)

plt.imsave("output/Depth/result/img_depth.png", img_depth)
for i in range(4):
    plt.imsave(f"output/Normal/layer{i}.png", img_normal)
    plt.imsave(f"output/RGBA/layer{i}.png", img_rgba)
