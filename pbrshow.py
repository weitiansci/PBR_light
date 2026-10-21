import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider
from matplotlib.lines import Line2D
from mpl_toolkits.mplot3d import Axes3D

# ==========================================
# 1. 基础参数与网格预计算 (只执行一次)
# ==========================================
RES = 60  # 半球采样分辨率，过高会导致拖动卡顿
c_base_init = np.array([0.95, 0.64, 0.54])  # 材质基础颜色初值（铜色，滑块可调）
lightColor_init = np.array([1.0, 1.0, 1.0])  # 入射光颜色初值（白光，滑块可调）

# 固定法线 N
N = np.array([0.0, 0.0, 1.0])

# 预计算观察方向 V 的球坐标网格
theta_v = np.linspace(0, np.pi / 2, RES)
phi_v = np.linspace(0, 2 * np.pi, RES)
Theta, Phi = np.meshgrid(theta_v, phi_v)

# 单位球面坐标 (方向向量 V)
Vx = np.sin(Theta) * np.cos(Phi)
Vy = np.sin(Theta) * np.sin(Phi)
Vz = np.cos(Theta)
V_flat = np.stack([Vx.flatten(), Vy.flatten(), Vz.flatten()], axis=-1)

# 预计算面片角索引（与 plot_surface 内部 _array_perimeter 周长顺序一致）
rowIdx, colIdx = np.meshgrid(np.arange(RES - 1), np.arange(RES - 1), indexing='ij')
faceR = [rowIdx.ravel(), rowIdx.ravel(), (rowIdx + 1).ravel(), (rowIdx + 1).ravel()]
faceC = [colIdx.ravel(), (colIdx + 1).ravel(), (colIdx + 1).ravel(), colIdx.ravel()]

# ==========================================
# 2. BRDF 增益计算核心函数
# ==========================================
def compute_gain(theta_l_deg, metalness, roughness, baseColor, lightColor):
    """返回压缩后的RGB半径网格及原始最大增益"""
    m = float(metalness)
    r = max(float(roughness), 0.01)
    theta_l = np.radians(theta_l_deg)
    c_base = np.asarray(baseColor, dtype=float)
    l_col = np.asarray(lightColor, dtype=float)
    
    L = np.array([np.sin(theta_l), 0.0, np.cos(theta_l)])
    NoL = max(L[2], 1e-5)
    
    # 向量化计算半角向量 H
    H = V_flat + L
    H /= (np.linalg.norm(H, axis=1, keepdims=True) + 1e-8)
    
    NoV = np.maximum(V_flat[:, 2], 1e-5)
    VoH = np.maximum(np.sum(V_flat * H, axis=1), 1e-5)
    # N=(0,0,1)，NoH 即 H 的 z 分量
    NoH = np.maximum(H[:, 2], 1e-5)
    
    # GGX 法线分布 D：微表面法线等于半角向量 H 的概率密度，自变量必须是 NoH
    a2 = r ** 4
    denom = NoH**2 * (a2 - 1) + 1
    D = a2 / (np.pi * denom**2)
    
    # Schlick-GGX 几何项 G
    k = (r + 1)**2 / 8
    G = (NoV / (NoV * (1-k) + k)) * (NoL / (NoL * (1-k) + k))
    
    # 菲涅尔 F 与 BRDF 组合
    spec_coeff = (D * G) / (4 * NoV * NoL + 1e-8)
    F0 = 0.04 * (1 - m) + c_base * m
    F_i = F0[None, :] + (1 - F0[None, :]) * ((1 - VoH)**5)[:, None]
    
    diff = (1 - m) * (1 - F_i) / np.pi
    spec = spec_coeff[:, None] * F_i
    # 出射增益 = BRDF · Li · NoL：入射光颜色按 R/G/B 通道分别缩放
    gain_flat = (diff + spec) * NoL * l_col
    
    # 分离通道并重塑为网格
    gains = [gain_flat[:, i].reshape(RES, RES) for i in range(3)]
    max_gain = max(np.max(gains[0]), np.max(gains[1]), np.max(gains[2]), 1e-5)
    
    # 线性强度：仅除以公共最大值做线性归一化，保持方向间与通道间的线性比例
    gainsNorm = [g / max_gain for g in gains]
        
    return gainsNorm, max_gain, L

def build_faces(g):
    """将压缩半径网格组装为 (n_faces, 4, 3) 面片顶点数组"""
    gx = Vx * g
    gy = Vy * g
    gz = Vz * g
    return np.stack([
        np.stack([gx[r, c], gy[r, c], gz[r, c]], axis=-1)
        for r, c in zip(faceR, faceC)
    ], axis=1)

# ==========================================
# 3. 初始化图形与滑块
# ==========================================
fig = plt.figure(figsize=(10, 9), facecolor='white')
ax = fig.add_subplot(111, projection='3d')
plt.subplots_adjust(bottom=0.28)  # 为底部滑块留出空间

# 初始状态
initGains, init_max, init_L = compute_gain(45, 0.8, 0.2, c_base_init, lightColor_init)

# 创建 R/G/B 三个半透明曲面
colors = ['red', 'green', 'blue']
surfaces = []
for i in range(3):
    surf = ax.plot_surface(
        Vx * initGains[i], Vy * initGains[i], Vz * initGains[i],
        facecolors=plt.cm.colors.to_rgba_array(colors[i]).repeat(RES*RES, axis=0).reshape(RES, RES, 4),
        alpha=0.55, rstride=1, cstride=1, shade=False, antialiased=True
    )
    surfaces.append(surf)

# 添加 N 和 L 指示箭头（pivot='tail'：从原点指向方向端点）
arrow_kw = dict(arrow_length_ratio=0.12, linewidth=4)
n_arrow = ax.quiver(0, 0, 0, 0, 0, 1.2, color=c_base_init, label='N', **arrow_kw)
l_arrow = ax.quiver(0, 0, 0, init_L[0]*1.2, init_L[1]*1.2, init_L[2]*1.2,
                    color=lightColor_init, label='L', **arrow_kw)
arrows = [n_arrow, l_arrow]

ax.set_xlim(-1.2, 1.2); ax.set_ylim(-1.2, 1.2); ax.set_zlim(-0.1, 1.2)
ax.set_box_aspect([1,1,1])

# 坐标轴网格区域（pane）纯黑；网格之外（图例、滑块所在的图窗区域）为白色
ax.xaxis.set_pane_color((0, 0, 0, 1))
ax.yaxis.set_pane_color((0, 0, 0, 1))
ax.zaxis.set_pane_color((0, 0, 0, 1))
ax.tick_params(colors='black')
for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
    axis.label.set_color('black')

# Proxy 图例（白底黑字；实际箭头绘制在黑 pane 上颜色正确。图例 L 线为
# 静态示意色，纯白光在白底上不可见，故用深灰示意）
legend_handles = [
    Line2D([0], [0], color=c_base_init, lw=4, label='N'),
    Line2D([0], [0], color=(0.35, 0.35, 0.35), lw=4, label='L'),
]
ax.legend(handles=legend_handles, loc='upper left')

title_text = fig.suptitle(f'3D BRDF Channel Gain | Max Raw: {init_max:.2f}',
                          fontsize=13, color='black')

# --- 创建滑块（3 行 3 列：Light RGB / Base RGB / 光照与材质参数）---
slider_color = 'white'
xCols = [0.13, 0.41, 0.69]
yRows = [0.18, 0.12, 0.06]
wS, hS = 0.26, 0.03

# 左侧组标签
fig.text(0.02, yRows[0] + 0.008, 'Light', fontsize=9, color='#555555', va='center')
fig.text(0.02, yRows[1] + 0.008, 'Base', fontsize=9, color='#555555', va='center')

axLight = [plt.axes([x, yRows[0], wS, hS], facecolor=slider_color) for x in xCols]
axBase = [plt.axes([x, yRows[1], wS, hS], facecolor=slider_color) for x in xCols]
ax_theta = plt.axes([xCols[0], yRows[2], wS, hS], facecolor=slider_color)
ax_metal = plt.axes([xCols[1], yRows[2], wS, hS], facecolor=slider_color)
ax_rough = plt.axes([xCols[2], yRows[2], wS, hS], facecolor=slider_color)

sLight = [Slider(ax, label, 0, 1, valinit=lightColor_init[i], valstep=0.01)
          for i, (ax, label) in enumerate(zip(axLight, ['R', 'G', 'B']))]
sBase = [Slider(ax, label, 0, 1, valinit=c_base_init[i], valstep=0.01)
         for i, (ax, label) in enumerate(zip(axBase, ['R', 'G', 'B']))]
s_theta = Slider(ax_theta, 'θ_L (°)', 0, 89, valinit=45, valstep=1)
s_metal = Slider(ax_metal, 'Metalness', 0, 1, valinit=0.8, valstep=0.01)
s_rough = Slider(ax_rough, 'Roughness', 0.01, 1, valinit=0.2, valstep=0.01)

# 白色图窗上滑块文字纯黑（标签与右侧数值）
for s in sLight + sBase + [s_theta, s_metal, s_rough]:
    s.label.set_color('black')
    s.valtext.set_color('black')

# ==========================================
# 4. 滑块回调 (仅更新顶点，不重建Mesh)
# ==========================================
def update(val):
    lightColor = np.array([sLight[i].val for i in range(3)])
    baseColor = np.array([sBase[i].val for i in range(3)])
    gains, max_g, L_vec = compute_gain(
        s_theta.val, s_metal.val, s_rough.val, baseColor, lightColor)
    
    for i in range(3):
        # 通过 set_verts 直接替换渲染用的面片顶点数据，避免销毁重建开销
        surfaces[i].set_verts(build_faces(gains[i]))
    
    # N 箭头颜色跟随材质基础颜色
    arrows[0].set_color(baseColor)
    
    # L 箭头方向与颜色随参数变化：quiver 无公开的向量更新 API（箭头形状
    # 在创建时预计算），重建单个箭头开销极小
    arrows[1].remove()
    arrows[1] = ax.quiver(0, 0, 0, L_vec[0]*1.2, L_vec[1]*1.2, L_vec[2]*1.2,
                          color=lightColor, **arrow_kw)
    
    title_text.set_text(f'3D BRDF Channel Gain | Max Raw: {max_g:.2f}')
    fig.canvas.draw_idle()  # draw_idle 比 draw 更省资源

for s in sLight + sBase + [s_theta, s_metal, s_rough]:
    s.on_changed(update)

plt.show()