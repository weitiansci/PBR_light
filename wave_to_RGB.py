import math
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from typing import Tuple

# ============================================================
# 中文字体配置（避免乱码）
# ============================================================
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
matplotlib.rcParams['axes.unicode_minus'] = False  # 正常显示负号

# ============================================================
# BK7 Sellmeier 系数 (λ 单位: μm)
# ============================================================
_B1, _B2, _B3 = 1.03961212, 0.231792344, 1.01046945
_C1, _C2, _C3 = 0.00600069867, 0.0200179144, 103.560653


def _sellmeier_n(wl_um: float) -> float:
    """BK7 折射率 (Sellmeier), wl_um 单位 μm"""
    wl2 = wl_um * wl_um
    n2 = (1.0
          + _B1 * wl2 / (wl2 - _C1)
          + _B2 * wl2 / (wl2 - _C2)
          + _B3 * wl2 / (wl2 - _C3))
    return math.sqrt(n2)


def _min_deviation(wl_nm: float, apex_deg: float) -> float:
    """给定波长(nm)和棱镜顶角(°)，返回最小偏向角(°)"""
    A = math.radians(apex_deg)
    n = _sellmeier_n(wl_nm / 1000.0)
    sin_val = n * math.sin(A / 2.0)
    if abs(sin_val) > 1.0:
        return float('inf')
    delta = 2.0 * math.asin(sin_val) - A
    return math.degrees(delta)


def _invert_dispersion(theta_deg: float, apex_deg: float,
                       wl_lo: float = 300.0,
                       wl_hi: float = 1100.0,
                       tol: float = 1e-4,
                       max_iter: int = 80) -> float:
    """数值反解: θ(°) → λ(nm)。超出范围返回 -1。"""
    d_lo = _min_deviation(wl_lo, apex_deg)
    d_hi = _min_deviation(wl_hi, apex_deg)
    if theta_deg > d_lo or theta_deg < d_hi:
        return -1.0
    lo, hi = wl_lo, wl_hi
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        d_mid = _min_deviation(mid, apex_deg)
        if abs(d_mid - theta_deg) < tol:
            return mid
        if d_mid > theta_deg:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ============================================================
# 太阳光谱功率分布 (Planck 黑体, T≈5778K)
# ============================================================
_H, _C_LIGHT, _K_B = 6.62607015e-34, 2.99792458e8, 1.380649e-23
_SUN_T = 5778.0  # 太阳表面等效温度


def _planck_spd(wl_nm: float, T: float = _SUN_T) -> float:
    """Planck 黑体光谱辐射出射度（相对值即可），wl_nm 单位 nm"""
    lam = wl_nm * 1e-9
    try:
        denom = math.exp(_H * _C_LIGHT / (lam * _K_B * T)) - 1.0
    except OverflowError:
        return 0.0
    if denom <= 0.0:
        return 0.0
    return (2.0 * _H * _C_LIGHT ** 2 / lam ** 5) / denom


# 可见光范围内归一化峰值（峰值约在 500nm 附近）
_SPD_PEAK = max(_planck_spd(w) for w in range(380, 781))


# ============================================================
# CIE 1931 标准观察者色匹配函数（分段高斯解析近似）
# ȳ(λ) 即明视觉光谱光视效率 V(λ)，已包含人眼敏感度
# ============================================================
def _g(wl: float, mu: float, s1: float, s2: float) -> float:
    s = s1 if wl < mu else s2
    return math.exp(-0.5 * ((wl - mu) / s) ** 2)


def _cie_cmfs(wl: float) -> Tuple[float, float, float]:
    """λ(nm) → (x̄, ȳ, z̄)，维基百科高斯拟合参数"""
    x_bar = (1.056 * _g(wl, 599.8, 37.9, 31.0)
             + 0.362 * _g(wl, 442.0, 16.0, 26.7)
             - 0.065 * _g(wl, 501.1, 20.4, 26.2))
    y_bar = (0.821 * _g(wl, 568.8, 46.9, 40.5)
             + 0.286 * _g(wl, 530.9, 16.3, 31.1))
    z_bar = (1.217 * _g(wl, 437.0, 11.8, 36.0)
             + 0.681 * _g(wl, 459.0, 26.0, 13.8))
    return x_bar, y_bar, z_bar


# ============================================================
# 色域映射与 gamma：XYZ → sRGB（真实屏幕无法再现纯光谱色，
# 越界时沿色度方向向白点降饱和，保住色相）
# ============================================================
def _xyz_to_linear_srgb(x: float, y: float, z: float) -> Tuple[float, float, float]:
    """CIE XYZ → 线性 sRGB（D65 白点标准矩阵）"""
    rl = 3.2406 * x - 1.5372 * y - 0.4986 * z
    gl = -0.9689 * x + 1.8758 * y + 0.0415 * z
    bl = 0.0557 * x - 0.2040 * y + 1.0570 * z
    return rl, gl, bl


def _gamut_desaturate(rl: float, gl: float, bl: float) -> Tuple[float, float, float]:
    """线性 sRGB 越界处理：负值向白点(1,1,1)回拉，超 1 等比压缩"""
    mn = min(rl, gl, bl)
    if mn < 0.0:
        t = -mn / (1.0 - mn)  # 使最负通道恰好归零的混合系数
        rl += t * (1.0 - rl)
        gl += t * (1.0 - gl)
        bl += t * (1.0 - bl)
    mx = max(rl, gl, bl)
    if mx > 1.0:
        rl /= mx; gl /= mx; bl /= mx
    return max(rl, 0.0), max(gl, 0.0), max(bl, 0.0)


def _srgb_gamma(c: float) -> float:
    """线性 → sRGB 非线性（分段 gamma）"""
    c = max(c, 0.0)
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * c ** (1.0 / 2.4) - 0.055


# ============================================================
# λ(nm) → RGB 完整管线:
# CMF → ×太阳光谱 → XYZ → 线性 sRGB → 色域映射 → gamma → 8bit
# ============================================================
def _wavelength_to_rgb(wl: float) -> Tuple[int, int, int]:
    if wl < 380.0 or wl > 780.0:
        return (0, 0, 0)
    x_bar, y_bar, z_bar = _cie_cmfs(wl)
    spd = _planck_spd(wl) / _SPD_PEAK  # 太阳光谱加权（亮度）
    x, y, z = x_bar * spd, y_bar * spd, z_bar * spd
    rl, gl, bl = _xyz_to_linear_srgb(x, y, z)
    rl, gl, bl = _gamut_desaturate(rl, gl, bl)
    return (int(round(255 * _srgb_gamma(rl))),
            int(round(255 * _srgb_gamma(gl))),
            int(round(255 * _srgb_gamma(bl))))


# ============================================================
# 颜色查找表（LUT）初始化与线性插值（基于新管线预计算）
# ============================================================
_WL_MIN, _WL_MAX = 380.0, 780.0
_LUT_N = 64
_STEP = (_WL_MAX - _WL_MIN) / (_LUT_N - 1)
_LUT_R = _LUT_G = _LUT_B = None
_LUT_WL = None  # 各节点对应的波长（自适应细分后非均匀）


def init_color_lut(lut_n: int = 64, tol: int = 3) -> int:
    """初始化颜色查找表：在 380~780nm 波长域均匀采样 lut_n 个基础点，
    每个节点用完整物理管线（CMF×太阳光谱→XYZ→sRGB→gamma）预计算；
    随后自适应细分：相邻节点间线性插值误差超过 tol/255 时，
    在其中点加密，最多 5 轮。返回实际生成的表长度。"""
    global _LUT_N, _STEP, _LUT_R, _LUT_G, _LUT_B, _LUT_WL

    def _build(nodes):
        table = [(wl, *_wavelength_to_rgb(wl)) for wl in nodes]
        return table

    step = (_WL_MAX - _WL_MIN) / (max(2, int(lut_n)) - 1)
    nodes = [_WL_MIN + i * step for i in range(max(2, int(lut_n)))]

    for _ in range(5):  # 自适应细分，控制插值误差 ≤ tol/255
        table = _build(nodes)
        new_nodes = []
        subdivided = False
        for (w1, r1, g1, b1), (w2, r2, g2, b2) in zip(table[:-1], table[1:]):
            new_nodes.append(w1)
            mid = (w1 + w2) / 2.0
            rm, gm, bm = _wavelength_to_rgb(mid)
            ri = (r1 + r2) / 2.0; gi = (g1 + g2) / 2.0; bi = (b1 + b2) / 2.0
            if max(abs(rm - ri), abs(gm - gi), abs(bm - bi)) > tol:
                new_nodes.append(mid)
                subdivided = True
        new_nodes.append(_WL_MAX)
        nodes = new_nodes
        if not subdivided:
            break

    _LUT_WL = nodes
    _LUT_R, _LUT_G, _LUT_B = [], [], []
    for wl in nodes:
        rv, gv, bv = _wavelength_to_rgb(wl)
        _LUT_R.append(rv); _LUT_G.append(gv); _LUT_B.append(bv)
    _LUT_N = len(nodes)
    _STEP = step  # 保留基础步长（仅供兼容，插值以 _LUT_WL 为准）
    return _LUT_N


init_color_lut()  # 模块导入时默认生成 64 基础点 + 自适应加密的表


def _lut_wavelength_to_rgb(wl: float) -> Tuple[int, int, int]:
    if wl < _WL_MIN or wl > _WL_MAX:
        return (0, 0, 0)
    # 在（可能非均匀的）节点波长上定位区间，线性插值取色
    i = int(np.searchsorted(_LUT_WL, wl)) - 1
    i = max(0, min(i, _LUT_N - 2))
    w1, w2 = _LUT_WL[i], _LUT_WL[i + 1]
    frac = (wl - w1) / (w2 - w1) if w2 > w1 else 0.0
    R = _LUT_R[i] + frac * (_LUT_R[i+1] - _LUT_R[i])
    G = _LUT_G[i] + frac * (_LUT_G[i+1] - _LUT_G[i])
    B = _LUT_B[i] + frac * (_LUT_B[i+1] - _LUT_B[i])
    return (int(round(R)), int(round(G)), int(round(B)))


# ============================================================
# θ → RGB 直接查找表（单步查询，免去逐点二分反解）
# ============================================================
_TLUT_TH = None   # 节点偏折角（°，可能非均匀）
_TLUT_R = _TLUT_G = _TLUT_B = None
_TLUT_APEX = None


def init_theta_rgb_lut(apex_deg: float = 60.0,
                       num_nodes: int = 256,
                       tol: int = 3) -> int:
    """初始化 θ→RGB 直接查找表：在有效偏折角区间 [θ(780nm), θ(380nm)]
    内均匀采样 num_nodes 个基础节点，每个节点用完整解析管线预计算；
    随后自适应细分（中点插值误差超过 tol/255 时加密，最多 5 轮）。
    表外角度直接返回黑色。返回实际表长度。"""
    global _TLUT_TH, _TLUT_R, _TLUT_G, _TLUT_B, _TLUT_APEX

    th_lo = _min_deviation(_WL_MAX, apex_deg)  # 红端(780nm) → 最小偏折角
    th_hi = _min_deviation(_WL_MIN, apex_deg)  # 紫端(380nm) → 最大偏折角

    def _rgb_at(th):
        wl = _invert_dispersion(th, apex_deg)
        if wl < _WL_MIN or wl > _WL_MAX:
            return (0, 0, 0)
        return _wavelength_to_rgb(wl)

    step = (th_hi - th_lo) / (max(2, int(num_nodes)) - 1)
    nodes = [th_lo + i * step for i in range(max(2, int(num_nodes)))]

    for _ in range(5):  # 自适应细分，控制插值误差 ≤ tol/255
        table = [(th, *_rgb_at(th)) for th in nodes]
        new_nodes = []
        subdivided = False
        for (t1, r1, g1, b1), (t2, r2, g2, b2) in zip(table[:-1], table[1:]):
            new_nodes.append(t1)
            mid = (t1 + t2) / 2.0
            rm, gm, bm = _rgb_at(mid)
            ri = (r1 + r2) / 2.0; gi = (g1 + g2) / 2.0; bi = (b1 + b2) / 2.0
            if max(abs(rm - ri), abs(gm - gi), abs(bm - bi)) > tol:
                new_nodes.append(mid)
                subdivided = True
        new_nodes.append(th_hi)
        nodes = new_nodes
        if not subdivided:
            break

    _TLUT_TH = nodes
    _TLUT_R, _TLUT_G, _TLUT_B = [], [], []
    for th in nodes:
        rv, gv, bv = _rgb_at(th)
        _TLUT_R.append(rv); _TLUT_G.append(gv); _TLUT_B.append(bv)
    _TLUT_APEX = apex_deg
    return len(nodes)


def _lut_theta_to_rgb(theta: float) -> Tuple[int, int, int]:
    """在 θ 节点表上定位区间，线性插值取色；表外返回黑色"""
    if theta < _TLUT_TH[0] or theta > _TLUT_TH[-1]:
        return (0, 0, 0)
    i = int(np.searchsorted(_TLUT_TH, theta)) - 1
    i = max(0, min(i, len(_TLUT_TH) - 2))
    t1, t2 = _TLUT_TH[i], _TLUT_TH[i + 1]
    frac = (theta - t1) / (t2 - t1) if t2 > t1 else 0.0
    R = _TLUT_R[i] + frac * (_TLUT_R[i+1] - _TLUT_R[i])
    G = _TLUT_G[i] + frac * (_TLUT_G[i+1] - _TLUT_G[i])
    B = _TLUT_B[i] + frac * (_TLUT_B[i+1] - _TLUT_B[i])
    return (int(round(R)), int(round(G)), int(round(B)))


init_theta_rgb_lut()  # 模块导入时默认生成 A=60° 的 θ→RGB 表
# ============================================================
# ★ 主函数（use_lut 时走 θ→RGB 单步查找表）
# ============================================================
def theta_to_rgb(theta: float,
                 apex_deg: float = 60.0,
                 use_lut: bool = True) -> Tuple[int, int, int]:
    if theta < 0.0 or theta > 90.0:
        return (0, 0, 0)
    if use_lut:
        # 顶角变更时自动重建表，保证 θ 区间与色散关系匹配
        if _TLUT_APEX != apex_deg:
            init_theta_rgb_lut(apex_deg=apex_deg)
        return _lut_theta_to_rgb(theta)
    wl = _invert_dispersion(theta, apex_deg)
    if wl < 0:
        return (0, 0, 0)
    return _wavelength_to_rgb(wl)


# ============================================================
# ★ 可视化：900 色带渲染
# ============================================================
def render_theta_colorbar(num_samples: int = 900,
                          apex_deg: float = 60.0,
                          theta_start: float = 0.0,
                          theta_end: float = 90.0,
                          wl_tick_step: int = 20,
                          compare_lut: bool = True,
                          save_path: str = None):
    """
    生成 θ → RGB 的颜色带图。

    Parameters
    ----------
    num_samples : int
        采样点数（默认 900）。
    apex_deg : float
        棱镜顶角（度）。
    theta_start : float
        起始角度（度），默认 0°。
    theta_end : float
        结束角度（度），默认 90°。
    wl_tick_step : int
        顶部波长刻度的间隔（nm），默认 20。
    compare_lut : bool
        是否同屏对比「查找表插值」与「解析解」两条色带，默认 True。
    save_path : str or None
        若提供则保存图片到该路径。
    """
    if theta_end <= theta_start:
        raise ValueError("theta_end 必须大于 theta_start")

    thetas = np.linspace(theta_start, theta_end, num_samples)
    rows = 2 if compare_lut else 1
    image = np.zeros((rows, num_samples, 3), dtype=np.uint8)
    max_diff, sum_diff = 0, 0

    for idx, th in enumerate(thetas):
        r_l, g_l, b_l = theta_to_rgb(float(th), apex_deg=apex_deg, use_lut=True)
        image[0, idx] = [r_l, g_l, b_l]
        if compare_lut:
            r_a, g_a, b_a = theta_to_rgb(float(th), apex_deg=apex_deg, use_lut=False)
            image[1, idx] = [r_a, g_a, b_a]
            d = max(abs(r_l - r_a), abs(g_l - g_a), abs(b_l - b_a))
            max_diff = max(max_diff, d)
            sum_diff += d

    if compare_lut:
        mean_diff = sum_diff / num_samples
        print(f"[LUT对比] 最大通道误差: {max_diff}/255, "
              f"平均误差: {mean_diff:.2f}/255")

    # --- 绘图 ---
    fig, ax = plt.subplots(figsize=(14, 3.4 if compare_lut else 2.2))
    ax.imshow(image, aspect='auto', interpolation='nearest')

    ax.set_xlim(0, num_samples - 1)
    tick_positions = np.linspace(0, num_samples - 1, 10)
    tick_labels = [f"{v:.1f}°" for v in np.linspace(theta_start, theta_end, 10)]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, fontsize=11)
    if compare_lut:
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["查找表插值", "解析解"], fontsize=11)
    else:
        ax.set_yticks([])
    ax.set_xlabel("最小偏向角 θ", fontsize=13)
    title = (f"BK7 三棱镜色散  θ → RGB 映射 (A={apex_deg}°, "
             f"θ∈[{theta_start:.1f}°, {theta_end:.1f}°], {num_samples} samples)")
    if compare_lut:
        title += f" | LUT最大误差 {max_diff}/255"
    ax.set_title(title, fontsize=14)

    # --- 顶部波长刻度轴 ---
    ax_wl = ax.twiny()  # 共享 y 轴，刻度以波长(nm)标注
    ax_wl.set_xlim(0, num_samples - 1)
    wl_ticks, wl_positions = [], []
    for wl in range(380, 781, wl_tick_step):
        th_wl = _min_deviation(wl, apex_deg)
        if theta_start <= th_wl <= theta_end:
            pos = (th_wl - theta_start) / (theta_end - theta_start) * (num_samples - 1)
            wl_ticks.append(wl)
            wl_positions.append(pos)
    if wl_ticks:
        ax_wl.set_xticks(wl_positions)
        ax_wl.set_xticklabels([f"{wl}" for wl in wl_ticks], fontsize=9)
    else:
        ax_wl.set_xticks([])
    ax_wl.set_xlabel("光波波长 λ (nm)", fontsize=11)

    # 标注可见光有效区间
    wl_vis_lo = _invert_dispersion(0, apex_deg)   # 不会命中，仅示意
    # 找到实际有颜色的起止索引
    first_color = next((i for i in range(num_samples)
                        if tuple(image[0, i]) != (0, 0, 0)), None)
    last_color = next((i for i in range(num_samples - 1, -1, -1)
                       if tuple(image[0, i]) != (0, 0, 0)), None)
    if first_color is not None and last_color is not None:
        ax.axvline(first_color, color='white', linewidth=0.8, linestyle='--')
        ax.axvline(last_color, color='white', linewidth=0.8, linestyle='--')
        mid = (first_color + last_color) / 2
        text_y = (rows - 1) / 2
        ax.text(mid, text_y, "← 可见光区 →", ha='center', va='center',
                fontsize=10, color='white', fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.2', fc='black', alpha=0.5))

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"图片已保存至: {save_path}")
    plt.show()


# ============================================================
# 运行入口
# ============================================================
if __name__ == "__main__":
    # 控制台打印部分采样
    print(f"{'θ (°)':>8} {'λ (nm)':>8} {'R':>4} {'G':>4} {'B':>4}")
    print("-" * 36)
    for deg in range(0, 91, 5):
        r, g, b = theta_to_rgb(deg)
        wl = _invert_dispersion(deg, apex_deg=60.0)
        wl_str = f"{wl:.1f}" if wl > 0 else "N/A"
        print(f"{deg:>8} {wl_str:>8} {r:>4} {g:>4} {b:>4}")

    print("\n正在生成颜色带渲染图...")
    # 可通过 theta_start / theta_end 配置光条显示的角度范围（单位：度）
    render_theta_colorbar(num_samples=900, apex_deg=60.0,
                          theta_start=38.0, theta_end=40.3)