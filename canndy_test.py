import cv2
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button, RadioButtons

# ===================== 图像加载与预处理 =====================
# ===================== 1. 读取图像并预处理 =====================
front_name="front/man2.png"
back_name="back/man2.png"
front_img = cv2.imdecode(
    np.fromfile(front_name, dtype=np.uint8), cv2.IMREAD_UNCHANGED
)
back_img = cv2.imdecode(
    np.fromfile(back_name, dtype=np.uint8), cv2.IMREAD_UNCHANGED
)
# plt.imshow(cv2.cvtColor(front_img[..., :3], cv2.COLOR_BGRA2RGBA))
# plt.show()

# img = img[..., 3]  # 保留RGB通道，去掉Alpha通道
# img = cv2.imdecode(np.fromfile('迪迦.jpg', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
# img = cv2.imdecode(np.fromfile('雷电将军.jpg', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
# img = cv2.imdecode(np.fromfile('祢豆子.png', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
# img = cv2.imdecode(np.fromfile('少年时代团.jpg', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
# img = cv2.imdecode(np.fromfile('网红美女.png', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
edge = cv2.Canny(front_img[..., 3], 50, 150)
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
edge = cv2.dilate(edge, kernel, iterations=2)
plt.imshow(edge, cmap="gray")
plt.show()

def canny_perceptual(img, low=50, high=150):
    """在LAB空间检测，L通道主导结构，AB通道捕获色差边界"""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # L通道用标准阈值
    edge_l = cv2.Canny(l, low, high)
    # AB通道色差变化幅度较小，阈值需降低
    edge_a = cv2.Canny(a, low // 2, high // 2)
    edge_b = cv2.Canny(b, low // 2, high // 2)

    return np.maximum.reduce([edge_l, edge_a, edge_b])

edge1 = canny_perceptual(front_img, 50, 150)
edge2 = canny_perceptual(back_img, 50, 150)
plt.subplot(1, 2, 1)
plt.imshow(edge1, cmap="gray")
plt.subplot(1, 2, 2)
plt.imshow(edge2, cmap="gray")
plt.show()
