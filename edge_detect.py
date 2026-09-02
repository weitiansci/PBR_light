import cv2
import numpy as np
import matplotlib.pyplot as plt

# ===================== 1. 读取图像并预处理 =====================
img = cv2.imdecode(np.fromfile('test.png', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)

# 如果图片不存在，创建一个测试用的渐变图像
if img is None:
    img = np.zeros((300, 400), dtype=np.uint8)
    cv2.rectangle(img, (50, 50), (200, 200), 255, -1)
    cv2.circle(img, (300, 150), 80, 255, -1)
    print("⚠️ 未找到 image.jpg，已生成测试图像")

# 高斯模糊降噪（边缘检测前的重要步骤）
blurred = cv2.GaussianBlur(img, (5, 5), 1.4)

# ===================== 2. Canny 边缘检测 =====================
# 最常用、效果最好的边缘检测算法
# 参数: 低阈值, 高阈值, apertureSize(可选)
canny = cv2.Canny(blurred, threshold1=50, threshold2=150)

# ===================== 3. Sobel 边缘检测 =====================
# 基于梯度的一阶微分算子，可分别检测水平和垂直边缘
sobel_x = cv2.Sobel(blurred, cv2.CV_64F, dx=1, dy=0, ksize=3)  # 水平方向
sobel_y = cv2.Sobel(blurred, cv2.CV_64F, dx=0, dy=1, ksize=3)  # 垂直方向
# 取绝对值后转回 uint8
sobel_x_abs = np.uint8(np.absolute(sobel_x))
sobel_y_abs = np.uint8(np.absolute(sobel_y))
# 合并两个方向
sobel_combined = cv2.bitwise_or(sobel_x_abs, sobel_y_abs)

# ===================== 4. Laplacian 边缘检测 =====================
# 二阶微分算子，对各向同性边缘敏感
laplacian = cv2.Laplacian(blurred, cv2.CV_64F, ksize=3)
laplacian_abs = np.uint8(np.absolute(laplacian))

# ===================== 5. Scharr 边缘检测 =====================
# Sobel 的改进版，在 ksize=3 时精度更高
scharr_x = cv2.Scharr(blurred, cv2.CV_64F, dx=1, dy=0)
scharr_y = cv2.Scharr(blurred, cv2.CV_64F, dx=0, dy=1)
scharr_combined = np.uint8(
    np.absolute(scharr_x) + np.absolute(scharr_y)
)

# ===================== 6. 可视化结果 =====================
titles = ['Original', 'Canny', 'Sobel Combined', 'Laplacian', 'Scharr']
images = [img, canny, sobel_combined, laplacian_abs, scharr_combined]

plt.figure(figsize=(15, 10))
for i in range(len(images)):
    plt.subplot(2, 3, i + 1)
    plt.imshow(images[i], cmap='gray')
    plt.title(titles[i])
    plt.axis('off')

plt.tight_layout()
plt.savefig('edge_detection_result.png', dpi=150)
plt.show()