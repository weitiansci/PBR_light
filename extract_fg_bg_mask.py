# -*- coding: utf-8 -*-
"""
从 恋与深空_rgba.png 提取 Alpha 通道：
1. 前景 mask：Alpha 通道本身，保存为 8bit 灰度 PNG (mode="L")
2. 背景 mask：前景 mask 取反 (255 - alpha)，同样 8bit 灰度 PNG
3. 背景图片：RGBA —— 前景 mask 区域 RGB 置 0，其余区域 RGB 保持原图不变，
   A 通道替换为背景 mask
"""

import os
import cv2
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
input_name = "front/man2"  # 不带扩展名的输入文件名
SRC_PATH = os.path.join(BASE_DIR, f"{input_name}.png")

FG_MASK_PATH = os.path.join(BASE_DIR, f"{input_name}_前景mask.png")
BG_MASK_PATH = os.path.join(BASE_DIR, f"{input_name}_背景mask.png")
BG_IMG_PATH = os.path.join(BASE_DIR, f"{input_name}_背景.png")
front_ORM_PATH = os.path.join(BASE_DIR, f"{input_name}_ORM.png")

depth_DIR = os.path.join(BASE_DIR, "空白深度.png")
rgba_zeros_DIR = os.path.join(BASE_DIR, "空白颜色.png")
normal_DIR = os.path.join(BASE_DIR, "空白法线.png")


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


def dilate(img, kernel_size=3, iterations=1):
    """膨胀操作"""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    return cv2.dilate(img, kernel, iterations=iterations)


def main():
    img = Image.open(SRC_PATH).convert("RGBA")
    rgba = np.asarray(img)

    # Alpha 通道 -> 8bit 前景 mask
    fg_mask = rgba[..., 3].copy()

    # 前景 mask 取反 -> 背景 mask
    bg_mask = (255 - fg_mask).astype(np.uint8)

    rgba_zero = np.zeros_like(rgba)
    normal = np.zeros_like(rgba)
    normal[:, :, 0] = 127
    normal[:, :, 1] = 127
    normal[:, :, 2] = 255
    depth = rgba_zero[:, :, :3]

    edge = cv2.Canny(fg_mask, 50, 150)
    edge = dilate(edge, kernel_size=5, iterations=2)
    edge2 = canny_perceptual(rgba[..., :3], 50, 150)
    edge2 = dilate(edge2, kernel_size=3, iterations=1)
    edge = np.maximum(edge, edge2)
    plt.imshow(edge, cmap="gray")
    plt.show()
    AO = np.zeros_like(edge) + 255
    metal = np.zeros_like(edge)
    roughness = np.zeros_like(edge)
    metal[edge > 0] = 255
    roughness[:, :] = 0.8 * 255
    roughness[edge > 0] = 0.2 * 255
    ORM = np.stack(
        [AO, metal, roughness,np.full_like(edge, 255)],  # A 通道全 255
        axis=-1,
    )
    plt.imshow(ORM)
    plt.show()
    Image.fromarray(ORM, mode="RGBA").save(front_ORM_PATH)

    # 保存 8bit 灰度 PNG（mode="L" 保证位深为 8，而非 RGBA 32bit）
    Image.fromarray(fg_mask, mode="L").save(FG_MASK_PATH, bits=8)
    Image.fromarray(bg_mask, mode="L").save(BG_MASK_PATH, bits=8)

    # 背景图片：前景 mask 区域 RGB 置 0，其余区域 RGB 不变，A 通道 = 背景 mask
    bg_rgba = rgba.copy()
    bg_rgba[fg_mask > 0, :3] = 0
    bg_rgba[..., 3] = bg_mask
    Image.fromarray(bg_rgba, mode="RGBA").save(BG_IMG_PATH)

    Image.fromarray(rgba_zero, mode="RGBA").save(rgba_zeros_DIR)
    Image.fromarray(normal, mode="RGBA").save(normal_DIR)
    Image.fromarray(depth, mode="RGB").save(depth_DIR)

    h, w = fg_mask.shape
    print(f"图像尺寸: {w} x {h}")
    print(
        f"前景 mask -> {os.path.basename(FG_MASK_PATH)}  (非零像素: {(fg_mask > 0).sum()})"
    )
    print(
        f"背景 mask -> {os.path.basename(BG_MASK_PATH)}  (非零像素: {(bg_mask > 0).sum()})"
    )
    print(f"背景图片  -> {os.path.basename(BG_IMG_PATH)}  (RGBA, A=背景mask)")


if __name__ == "__main__":
    main()
