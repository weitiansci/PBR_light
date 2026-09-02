import cv2
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button, RadioButtons

# ===================== 图像加载与预处理 =====================
# ===================== 1. 读取图像并预处理 =====================
# img = cv2.imdecode(np.fromfile("test.png", dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
img = cv2.imdecode(
    np.fromfile("迪迦rgba.png", dtype=np.uint8), cv2.IMREAD_UNCHANGED
)
plt.imshow(img[..., :3])
plt.show()
img = img[..., 3]  # 保留RGB通道，去掉Alpha通道
# img = cv2.imdecode(np.fromfile('迪迦.jpg', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
# img = cv2.imdecode(np.fromfile('雷电将军.jpg', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
# img = cv2.imdecode(np.fromfile('祢豆子.png', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
# img = cv2.imdecode(np.fromfile('少年时代团.jpg', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
# img = cv2.imdecode(np.fromfile('网红美女.png', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
edge = cv2.Canny(img, 50, 150)
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
edge = cv2.dilate(edge, kernel, iterations=1)
plt.imshow(edge, cmap="gray")
plt.show()
