import numpy as np
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties, fontManager
import platform
import os

# ==================== 中文字体配置（修复乱码）====================
def setup_chinese_font():
    """自动检测系统中文字体"""
    system = platform.system()
    if system == "Windows":
        candidates = ["Microsoft YaHei", "SimHei", "KaiTi", "SimSun"]
    elif system == "Darwin":
        candidates = ["PingFang SC", "Heiti SC", "STHeiti"]
    else:
        candidates = ["WenQuanYi Micro Hei", "Noto Sans CJK SC",
                      "Source Han Sans CN", "AR PL UMing CN"]

    available = {f.name for f in fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name] + plt.rcParams["font.sans-serif"]
            print(f"✓ 已设置中文字体: {name}")
            return
    # 兜底：扫描含 CJK 关键字的字体
    for f in fontManager.ttflist:
        low = f.name.lower()
        if any(k in low for k in ["cjk", "hei", "song", "noto sans sc"]):
            plt.rcParams["font.sans-serif"] = [f.name] + plt.rcParams["font.sans-serif"]
            print(f"✓ 已设置中文字体(兜底): {f.name}")
            return
    print("⚠ 未找到中文字体，请安装后重试")

setup_chinese_font()
plt.rcParams["axes.unicode_minus"] = False
# ==============================================================


# ==================== 波长 → RGB（CIE 1931 色度学）====================
def wavelength_to_rgb(wavelength):
    """波长 → sRGB，基于 CIE 1931 标准观察者色匹配函数的高斯解析近似。
    流程: λ → x̄ȳz̄(高斯) → XYZ → sRGB(矩阵) → gamma → 边缘 smoothstep 淡出。"""
    w = np.asarray(wavelength, dtype=np.float64)

    # ---- 分段高斯基函数 ----
    def _g(mu, s1, s2):
        s = np.where(w < mu, s1, s2)
        return np.exp(-0.5 * ((w - mu) / s) ** 2)

    # ---- CIE 1931 2° 标准观察者色匹配函数（维基百科参数）----
    x_bar = (1.056 * _g(599.8, 37.9, 31.0)
           + 0.362 * _g(442.0, 16.0, 26.7)
           - 0.065 * _g(501.1, 20.4, 26.2))
    y_bar = (0.821 * _g(568.8, 46.9, 40.5)
           + 0.286 * _g(530.9, 16.3, 31.1))
    z_bar = (1.217 * _g(437.0, 11.8, 36.0)
           + 0.681 * _g(459.0, 26.0, 13.8))

    # XYZ → 线性 sRGB（CIE 标准矩阵，D65 白点）
    rl =  3.2406 * x_bar - 1.5372 * y_bar - 0.4986 * z_bar
    gl = -0.9689 * x_bar + 1.8758 * y_bar + 0.0415 * z_bar
    bl =  0.0557 * x_bar - 0.2040 * y_bar + 1.0570 * z_bar

    # sRGB gamma 校正（线性 → 非线性）
    def _gamma(c):
        c = np.maximum(c, 0.0)
        return np.where(c <= 0.0031308,
                        12.92 * c,
                        1.055 * np.power(c + 1e-10, 1.0 / 2.4) - 0.055)

    r = _gamma(rl)
    g = _gamma(gl)
    b = _gamma(bl)

    # UV / IR 边缘 smoothstep 淡出
    uv = np.clip((w - 340.0) / 60.0, 0.0, 1.0)
    ir = np.clip((840.0 - w) / 60.0, 0.0, 1.0)
    fade = (uv * uv * (3.0 - 2.0 * uv)) * (ir * ir * (3.0 - 2.0 * ir))

    return np.clip(r * fade, 0.0, 1.0), \
           np.clip(g * fade, 0.0, 1.0), \
           np.clip(b * fade, 0.0, 1.0)


# ==================== 光栅方向场 ====================
def get_grating_direction(x_coor, y_coor, grating_type, angle_deg=45.0):
    h, w = x_coor.shape
    if grating_type == "linear":
        a = np.radians(angle_deg)
        return np.full((h, w), np.cos(a)), np.full((h, w), np.sin(a))
    elif grating_type == "radial":
        dx, dy = x_coor, y_coor
        length = np.sqrt(dx**2 + dy**2) + 1e-8
        return dx / length, dy / length
    elif grating_type == "spiral":
        dx, dy = x_coor, y_coor
        radius = np.sqrt(dx**2 + dy**2)
        angle = np.arctan2(dy, dx) + radius * 3.0
        return np.cos(angle), np.sin(angle)
    elif grating_type == "random":
        np.random.seed(42)
        block = max(8, min(h, w) // 16)
        gx = np.zeros((h, w)); gy = np.zeros((h, w))
        for i in range(0, h, block):
            for j in range(0, w, block):
                a = np.random.uniform(0, 2 * np.pi)
                gx[i:i+block, j:j+block] = np.cos(a)
                gy[i:i+block, j:j+block] = np.sin(a)
        return gx, gy
    else:
        raise ValueError(f"未知光栅类型: {grating_type}")


# ==================== 核心渲染：彩虹 + 底色混合 ====================
def render_holo(x_coor, y_coor, base_tex, light_pos, view_pos,
                grating_period=800.0, grating_type="radial",
                metallic=0.9, roughness=0.30, iridescence=1.0,
                sigma=0.30, m_order=1):
    """
    C_final = C_base*k_d + (C_base² ⊙ S(λ))*k_irid + C_spec*k_s
    """
    h, w = x_coor.shape

    # 像素世界坐标（z=0 平面），保持长宽比
    pixel_pos = np.zeros((h, w, 3))
    pixel_pos[:, :, 0] = x_coor
    pixel_pos[:, :, 1] = y_coor

    L = light_pos[None, None, :] - pixel_pos
    L_norm = L / (np.linalg.norm(L, axis=2, keepdims=True) + 1e-8)
    V = view_pos[None, None, :] - pixel_pos
    V_norm = V / (np.linalg.norm(V, axis=2, keepdims=True) + 1e-8)
    H = L_norm + V_norm
    H_norm = H / (np.linalg.norm(H, axis=2, keepdims=True) + 1e-8)

    NdotL = np.clip(L_norm[:, :, 2], 0, 1)          # 法线=(0,0,1)
    NdotV = np.clip(V_norm[:, :, 2], 1e-4, 1)
    NdotH = np.clip(H_norm[:, :, 2], 0, 1)
    HdotV = np.clip(np.sum(H_norm * V_norm, axis=2), 0, 1)

    # 光栅方向 → 衍射波长
    gx, gy = get_grating_direction(x_coor, y_coor, grating_type)
    gdir = np.zeros((h, w, 3))
    gdir[:, :, 0] = gx; gdir[:, :, 1] = gy
    sin_i = np.sum(L_norm * gdir, axis=2)
    sin_o = np.sum(V_norm * gdir, axis=2)
    wavelength = grating_period * (sin_i + sin_o) / m_order

    # 多级衍射叠加：不同级次产生不同波长，混合后颜色更柔和
    S = np.zeros((h, w, 3))
    for m in range(1, 5):
        wl = grating_period * (sin_i + sin_o) / m
        dr, dg, db = wavelength_to_rgb(wl)
        weight = 1.0 / m
        S += np.stack([dr, dg, db], axis=2) * weight

    grating_resp = np.exp(-((sin_i + sin_o) * 0.5)**2 / (2 * sigma**2))
    S *= grating_resp[..., None]

    # ---- 基础颜色（逐像素）----
    br = base_tex[:, :, 0]; bg = base_tex[:, :, 1]; bb = base_tex[:, :, 2]

    # Fresnel (Schlick)，金属 F0 = albedo
    F0 = np.stack([
        0.04 * (1 - metallic) + br * metallic,
        0.04 * (1 - metallic) + bg * metallic,
        0.04 * (1 - metallic) + bb * metallic], axis=2)
    fres = (1 - HdotV) ** 5
    F = F0 + (1 - F0) * fres[..., None]

    # GGX 镜面高光
    a = roughness * roughness; a2 = a * a
    denom = NdotH**2 * (a2 - 1) + 1
    D = a2 / (np.pi * denom**2 + 1e-8)
    k = (roughness + 1)**2 / 8
    G = (NdotV / (NdotV * (1 - k) + k)) * (NdotL / (NdotL * (1 - k) + k + 1e-8))
    spec = (D * G)[..., None] * F / (4 * NdotV[..., None] * NdotL[..., None] + 1e-8)

    # ---- 三层混合 ----
    k_s    = np.mean(F, axis=2)[..., None]
    k_irid = metallic * iridescence
    k_d    = (1 - metallic) * (1 - iridescence * metallic)

    base = np.stack([br, bg, bb], axis=2)
    ambient = 0.15
    diffuse = base * (k_d * NdotL[..., None] + ambient)      # ① 漫反射层（含环境光保底）
    irid = S * k_irid * 2.5                                  # ② 衍射虹彩（独立增益，不再受 base² 压暗）
    specular = np.tanh(spec * NdotL[..., None]) * 0.4        # ③ 镜面高光（tanh 软裁剪防过曝）

    return diffuse + irid + specular


# ==================== 载入基础颜色纹理 ====================
def load_base_texture(path, max_side=720):
    """读取图片作为基础颜色，限制最大边长防止过慢"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到图片: {path}\n请把 恋与深空.png 放到脚本同目录")
    img = plt.imread(path)
    if img.dtype == np.uint8:
        img = img.astype(np.float64) / 255.0
    if img.ndim == 2:
        img = np.stack([img]*3, axis=2)
    img = img[:, :, :3]  # 去掉 alpha

    h, w = img.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        new_h, new_w = int(h * scale), int(w * scale)
        # 简单双线性缩放（用 meshgrid 索引最近邻近似，避免依赖 cv2）
        ys = np.linspace(0, h - 1, new_h).astype(int)
        xs = np.linspace(0, w - 1, new_w).astype(int)
        img = img[np.ix_(ys, xs)]
    return np.clip(img, 0, 1)


# ==================== 主程序 ====================
if __name__ == "__main__":
    IMG_PATH = "恋与深空.png"

    print("载入基础颜色纹理...")
    base_tex = load_base_texture(IMG_PATH, max_side=720)
    H, W = base_tex.shape[:2]
    print(f"渲染分辨率: {W} × {H}")

    # 归一化坐标，保持长宽比
    aspect = W / H
    x = np.linspace(-aspect, aspect, W)
    y = np.linspace(-1, 1, H)
    x_coor, y_coor = np.meshgrid(x, y)

    light_pos = np.array([1, 1, 1])
    view_pos  = np.array([0.0, 0.0, 1.0])

    # ---- 参数（可调整模拟不同闪卡）----
    params = dict(
        grating_period=800.0,
        grating_type="linear",   # linear / radial / spiral / random
        metallic=0.9,
        roughness=0.30,
        iridescence=1.0,
    )

    print("渲染中...")
    result = render_holo(x_coor, y_coor, base_tex, light_pos, view_pos, **params)

    # 归一化 + Gamma（tanh 已锁住高光，无需 Reinhard）
    mx = np.max(result)
    if mx > 0:
        result = result / mx
    result = np.clip(result, 0, 1) ** (1.0 / 2.2)

    # ---- 可视化：原图 vs 渲染结果 ----
    extent = [-aspect, aspect, -1, 1]
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    axes[0].imshow(base_tex, origin='lower', extent=extent)
    axes[0].set_title('基础颜色（恋与深空）', fontsize=13)
    axes[0].axis('off')

    axes[1].imshow(result, origin='lower', extent=extent)
    axes[1].set_title(f'彩虹结构色渲染\n光栅:{params["grating_type"]}, d={params["grating_period"]}nm', fontsize=13)
    axes[1].axis('off')

    # 彩虹强度对比：无底色彩虹 vs 混合
    white_tex = np.ones_like(base_tex) * 0.95
    pure_rainbow = render_holo(x_coor, y_coor, white_tex, light_pos, view_pos, **params)
    mx2 = np.max(pure_rainbow)
    if mx2 > 0:
        pure_rainbow = pure_rainbow / mx2
    pure_rainbow = np.clip(pure_rainbow, 0, 1) ** (1.0 / 2.2)
    axes[2].imshow(pure_rainbow, origin='lower', extent=extent)
    axes[2].set_title('纯彩虹（白底参考）', fontsize=13)
    axes[2].axis('off')

    plt.suptitle('光栅彩虹反射光 × 基础颜色 物理混合', fontsize=15)
    plt.tight_layout()
    plt.savefig('holo_render_result.png', dpi=150, bbox_inches='tight')
    plt.show()

    # ---- 多角度观察（闪卡转动效果）----
    print("生成多角度对比...")
    views = [
        np.array([0.0, 0.0, 3.0]),
        np.array([1.2, 0.0, 2.5]),
        np.array([-1.2, 0.6, 2.0]),
        np.array([0.0, 1.5, 2.2]),
        np.array([0.9, -0.9, 3.2]),
        np.array([-0.6, -1.2, 1.8]),
    ]
    fig2, axes2 = plt.subplots(2, 3, figsize=(15, 10))
    for idx, vp in enumerate(views):
        ax = axes2[idx // 3, idx % 3]
        r = render_holo(x_coor, y_coor, base_tex, light_pos, vp, **params)
        mx = np.max(r)
        if mx > 0:
            r = r / mx
        r = np.clip(r, 0, 1) ** (1.0 / 2.2)
        ax.imshow(r, origin='lower', extent=extent)
        ax.set_title(f'视角 ({vp[0]:.1f}, {vp[1]:.1f}, {vp[2]:.1f})', fontsize=10)
        ax.axis('off')
    plt.suptitle('不同观察角度 — 闪卡转动时彩虹流动', fontsize=14)
    plt.tight_layout()
    plt.savefig('holo_render_multiview.png', dpi=150, bbox_inches='tight')
    plt.show()

    print("完成！输出: holo_render_result.png / holo_render_multiview.png")