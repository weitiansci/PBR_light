# -*- coding: utf-8 -*-
"""
从 恋与深空_rgba.png 提取 Alpha 通道：
1. 前景 mask：Alpha 通道本身，保存为 8bit 灰度 PNG (mode="L")
2. 背景 mask：前景 mask 取反 (255 - alpha)，同样 8bit 灰度 PNG
3. 背景图片：RGBA —— 前景 mask 区域 RGB 置 0，其余区域 RGB 保持原图不变，
   A 通道替换为背景 mask
"""
import os

import numpy as np
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(BASE_DIR, "恋与深空_rgba.png")

FG_MASK_PATH = os.path.join(BASE_DIR, "恋与深空_前景mask.png")
BG_MASK_PATH = os.path.join(BASE_DIR, "恋与深空_背景mask.png")
BG_IMG_PATH = os.path.join(BASE_DIR, "恋与深空_背景.png")


def main():
    img = Image.open(SRC_PATH).convert("RGBA")
    rgba = np.asarray(img)

    # Alpha 通道 -> 8bit 前景 mask
    fg_mask = rgba[..., 3].copy()

    # 前景 mask 取反 -> 背景 mask
    bg_mask = (255 - fg_mask).astype(np.uint8)

    # 保存 8bit 灰度 PNG（mode="L" 保证位深为 8，而非 RGBA 32bit）
    Image.fromarray(fg_mask, mode="L").save(FG_MASK_PATH, bits=8)
    Image.fromarray(bg_mask, mode="L").save(BG_MASK_PATH, bits=8)

    # 背景图片：前景 mask 区域 RGB 置 0，其余区域 RGB 不变，A 通道 = 背景 mask
    bg_rgba = rgba.copy()
    bg_rgba[fg_mask > 0, :3] = 0
    bg_rgba[..., 3] = bg_mask
    Image.fromarray(bg_rgba, mode="RGBA").save(BG_IMG_PATH)

    h, w = fg_mask.shape
    print(f"图像尺寸: {w} x {h}")
    print(f"前景 mask -> {os.path.basename(FG_MASK_PATH)}  (非零像素: {(fg_mask > 0).sum()})")
    print(f"背景 mask -> {os.path.basename(BG_MASK_PATH)}  (非零像素: {(bg_mask > 0).sum()})")
    print(f"背景图片  -> {os.path.basename(BG_IMG_PATH)}  (RGBA, A=背景mask)")


if __name__ == "__main__":
    main()
