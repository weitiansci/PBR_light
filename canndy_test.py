import cv2
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button, RadioButtons

# ===================== 图像加载与预处理 =====================
# ===================== 1. 读取图像并预处理 =====================
img = cv2.imdecode(np.fromfile('test.png', dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
if img is None:
    img = np.zeros((300, 400), dtype=np.uint8)
    cv2.rectangle(img, (50, 50), (200, 200), 255, -1)
    cv2.circle(img, (300, 150), 80, 255, -1)
    print("⚠️ 未找到 image.jpg，已生成测试图像")

# ===================== 创建布局 =====================
fig, ax = plt.subplots(figsize=(12, 9))
plt.subplots_adjust(left=0.25, bottom=0.35, top=0.92, right=0.95)
ax.set_title('Edge Detection Interactive Tuner', fontsize=14)
ax.axis('off')

# 初始显示 Canny
display = ax.imshow(cv2.Canny(cv2.GaussianBlur(img, (5, 5), 1.4), 50, 150),
                    cmap='gray', vmin=0, vmax=255)

# ===================== 算法选择器 =====================
algo_ax = plt.axes([0.02, 0.75, 0.15, 0.15])
radio = RadioButtons(algo_ax, ('Canny', 'Sobel', 'Laplacian', 'Scharr'), active=0)
algo_ax.set_title('Algorithm', fontsize=10)

# ===================== 滑块定义 =====================
slider_color = 'lightgoldenrodyellow'
active_color = '#4A90D9'

# --- Canny 参数 ---
ax_low   = plt.axes([0.25, 0.25, 0.65, 0.03], facecolor=slider_color)
ax_high  = plt.axes([0.25, 0.20, 0.65, 0.03], facecolor=slider_color)
s_low    = Slider(ax_low,  'Canny Low',  0, 255, valinit=50,  valstep=1)
s_high   = Slider(ax_high, 'Canny High', 0, 255, valinit=150, valstep=1)

# --- Sobel/Scharr/Laplacian 共用: 模糊核大小 + ksize ---
ax_blur  = plt.axes([0.25, 0.15, 0.65, 0.03], facecolor=slider_color)
ax_ksize = plt.axes([0.25, 0.10, 0.65, 0.03], facecolor=slider_color)
s_blur   = Slider(ax_blur,  'Gauss Blur σ', 0, 10, valinit=1.4, valstep=0.1)
s_ksize  = Slider(ax_ksize, 'Kernel Size',  1, 7,  valinit=3,   valstep=2)
# ksize 映射: slider值 1,3,5,7 → 实际核大小 1,3,5,7

# --- Laplacian 专用: scale ---
ax_scale = plt.axes([0.25, 0.05, 0.65, 0.03], facecolor=slider_color)
s_scale  = Slider(ax_scale, 'Lap Scale', 0.1, 5.0, valinit=1.0, valstep=0.1)

all_sliders = [s_low, s_high, s_blur, s_ksize, s_scale]

# ===================== 参数可见性管理 =====================
def update_slider_visibility(algo):
    """根据当前算法显示/隐藏对应滑块"""
    # 重置所有滑块样式
    for s in all_sliders:
        s.label.set_color('gray')
        s.valtext.set_color('gray')

    if algo == 'Canny':
        visible = [s_low, s_high, s_blur]
    elif algo in ('Sobel', 'Scharr'):
        visible = [s_blur, s_ksize]
    elif algo == 'Laplacian':
        visible = [s_blur, s_ksize, s_scale]
    else:
        visible = []

    for s in all_sliders:
        s.ax.set_visible(s in visible)
        if s in visible:
            s.label.set_color('black')
            s.valtext.set_color('black')

    fig.canvas.draw_idle()

# ===================== 核心更新函数 =====================
current_algo = ['Canny']  # 用列表以便在闭包中修改

def update(_=None):
    sigma = s_blur.val
    blur_k = max(3, int(sigma * 2 + 1) | 1)  # 确保奇数且≥3
    blurred = cv2.GaussianBlur(img, (blur_k, blur_k), sigma)

    algo = current_algo[0]

    if algo == 'Canny':
        low = int(s_low.val)
        high = int(s_high.val)
        result = cv2.Canny(blurred, min(low, high), max(low, high))

    elif algo == 'Sobel':
        ks = int(s_ksize.val) | 1  # 确保奇数
        gx = cv2.Sobel(blurred, cv2.CV_64F, 1, 0, ksize=ks)
        gy = cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=ks)
        result = np.uint8(np.sqrt(gx**2 + gy**2))

    elif algo == 'Scharr':
        gx = cv2.Scharr(blurred, cv2.CV_64F, 1, 0)
        gy = cv2.Scharr(blurred, cv2.CV_64F, 0, 1)
        result = np.uint8(np.sqrt(gx**2 + gy**2))

    elif algo == 'Laplacian':
        ks = int(s_ksize.val) | 1
        lap = cv2.Laplacian(blurred, cv2.CV_64F, ksize=ks, scale=s_scale.val)
        result = np.uint8(np.absolute(lap))

    display.set_data(result)
    ax.set_title(f'{algo} Edge Detection', fontsize=14)
    fig.canvas.draw_idle()

# ===================== 事件绑定 =====================
for s in all_sliders:
    s.on_changed(update)

def on_algo_change(label):
    current_algo[0] = label
    update_slider_visibility(label)
    update()

radio.on_clicked(on_algo_change)

# 添加保存按钮
btn_ax = plt.axes([0.02, 0.02, 0.12, 0.04])
btn_save = Button(btn_ax, '💾 Save Result', color='#E8F5E9', hovercolor='#C8E6C9')

def save_result(_):
    fname = f'edge_{current_algo[0].lower()}_result.png'
    extent = display.get_extent()
    fig.savefig(fname, dpi=150, bbox_inches='tight')
    print(f"✅ 已保存: {fname}")

btn_save.on_clicked(save_result)

# ===================== 初始化并启动 =====================
update_slider_visibility('Canny')
update()
plt.show()