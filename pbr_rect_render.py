# -*- coding: utf-8 -*-
"""
PBR 双矩形渲染 + 交互控件
======================
matplotlib.widgets.Slider 实时控制：
  - 点光源位置 (X, Y, Z)
  - 矩形欧拉旋转 (Yaw, Pitch, Roll)
渲染管线：numpy 向量化软光栅化 + Cook-Torrance GGX PBR + 透视投影 + 法线贴图。
场景含两张平行于 xy 平面的矩形（不同 z，深度测试合成）：
  - 前景卡片：恋与深空_rgba.png（基础颜色，alpha 测试镂空）、Nomal.png（法线）、
              金属纹理.png 的 RGB 通道 → ORM 参数
  - 背景：恋与深空_背景扩展.png、恋与深空_背景扩展Nomal.png、金属纹理.png 的 ORM 参数、
          闪卡纹理.png 自发光（滑块控制整体自发光强度）
ORM 通道约定：R → AO，G → roughness，B → metallic。
拖动滑块，图框即时更新。
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider
from matplotlib.font_manager import fontManager
import platform
import os


# ==================== 中文字体配置 ====================
def setup_chinese_font():
    system = platform.system()
    if system == "Windows":
        candidates = ["Microsoft YaHei", "SimHei", "KaiTi", "SimSun"]
    elif system == "Darwin":
        candidates = ["PingFang SC", "Heiti SC", "STHeiti"]
    else:
        candidates = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "Source Han Sans CN"]
    available = {f.name for f in fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name] + plt.rcParams["font.sans-serif"]
            return
    for f in fontManager.ttflist:
        if any(k in f.name.lower() for k in ["cjk", "hei", "noto sans sc"]):
            plt.rcParams["font.sans-serif"] = [f.name] + plt.rcParams["font.sans-serif"]
            return

setup_chinese_font()
plt.rcParams["axes.unicode_minus"] = False


# ==================== 矩阵工具 ====================
def look_at(eye, center, up):
    f = center - eye; f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s)
    u = np.cross(s, f)
    M = np.eye(4)
    M[0, :3] = s; M[1, :3] = u; M[2, :3] = -f
    M[:3, 3] = [-np.dot(s, eye), -np.dot(u, eye), np.dot(f, eye)]
    return M


def perspective(fov_y_deg, aspect, near, far):
    f = 1.0 / np.tan(np.radians(fov_y_deg) / 2.0)
    M = np.zeros((4, 4))
    M[0, 0] = f / aspect
    M[1, 1] = f
    M[2, 2] = (far + near) / (near - far)
    M[2, 3] = 2 * far * near / (near - far)
    M[3, 2] = -1.0
    return M


def transform_points(M, pts):
    homo = np.hstack([pts, np.ones((pts.shape[0], 1))])
    return (M @ homo.T).T


def normalize(v, eps=1e-8):
    n = np.sqrt(np.sum(v * v, axis=-1, keepdims=True))
    return v / (n + eps)


# ==================== 纹理采样 / 加载 ====================
def sample_texture(tex, u, v):
    """u,v ∈ [0,1]；v=0 对应图像底部（plt.imread 行序与 GL 相反）"""
    h, w = tex.shape[:2]
    col = np.clip((u * (w - 1)).astype(np.int32), 0, w - 1)
    row = np.clip(((1.0 - v) * (h - 1)).astype(np.int32), 0, h - 1)
    return tex[row, col]


def _uv_to_indices(tex, u, v):
    """预计算纹理采样索引，供多张同尺寸纹理共享复用"""
    h, w = tex.shape[:2]
    col = np.clip((u * (w - 1)).astype(np.int32), 0, w - 1)
    row = np.clip(((1.0 - v) * (h - 1)).astype(np.int32), 0, h - 1)
    return row, col


def load_texture(path, max_side=640, srgb_to_linear=True, keep_alpha=False):
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到贴图: {path}")
    img = plt.imread(path)
    if img.dtype == np.uint8:
        img = img.astype(np.float32) * (1.0 / 255.0)  # float32 节省内存和带宽
    else:
        img = img.astype(np.float32)
    if img.ndim == 2:
        img = np.stack([img] * 3, axis=2)
    keep_a = keep_alpha and img.shape[2] == 4
    if not keep_a:
        img = img[:, :, :3]
    h, w = img.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        ys = np.linspace(0, h - 1, int(h * scale)).astype(int)
        xs = np.linspace(0, w - 1, int(w * scale)).astype(int)
        img = img[np.ix_(ys, xs)]
    if srgb_to_linear:
        rgb = img[:, :, :3]  # alpha 是遮罩数据，不做 sRGB 解码
        rgb = np.where(rgb <= 0.04045, rgb * (1.0 / 12.92),
                       ((rgb + 0.055) * (1.0 / 1.055)) ** 2.4)
        img = np.dstack([rgb, img[:, :, 3:]]) if keep_a else rgb
    return np.clip(img, 0, 1)


# ==================== PBR BRDF ====================
# Cook-Torrance GGX 各分量已内联至 render_frame 着色循环中，减少函数调用和中间数组分配


# ==================== 视差遮挡贴图（POM） ====================
def parallax_occlusion(depth_tex, u, v, Vt, T_w, B_w, N_w,
                       V_world, max_disp_u, max_disp_v, world_depth, n_steps=8):
    """视差遮挡贴图：沿视线方向在高度场中光线步进，返回偏移后的 UV 及世界位移。

    depth_tex: 深度贴图（R 通道作为高度场，白=凸起/近，黑=凹陷/远）
    Vt: 切线空间视线向量 (N, 3)
    max_disp_u: u 轴最大 UV 偏移幅度（世界尺度换算后）
    max_disp_v: v 轴最大 UV 偏移幅度（世界尺度换算后）
    world_depth: 世界空间最大位移量（用于计算命中点世界位移）
    n_steps: 光线步进步数（越多越精确但越慢）

    返回: (u_offset, v_offset, disp_world)
      disp_world: 命中点沿视线的世界位移量 (1 - hit_z) * world_depth
    """
    # Vt 为表面→相机方向（正面可见时 Vt_z>0），下限钳制防掠射角除零
    Vt_z = np.clip(Vt[:, 2], 0.01, None)
    du_full = -Vt[:, 0] / Vt_z * max_disp_u
    dv_full = -Vt[:, 1] / Vt_z * max_disp_v

    dz_per_step = 1.0 / n_steps
    # first_hit: 记录首次光线穿入表面的步进索引
    first_hit = np.full(len(u), n_steps, dtype=np.int32)
    prev_z = np.ones(len(u), dtype=np.float32)   # 上一步光线高度（z=1 为表面平面）
    prev_h = np.ones(len(u), dtype=np.float32)   # 上一步表面高度（未命中时交点在 z=1 表面）

    for i in range(n_steps):
        ray_z = 1.0 - (i + 1) * dz_per_step
        # FIX4(a): 步进采样改用 clamp 而非 wrap，与 albedo/normal 采样一致，避免边缘 wrap 造成的高度/颜色不一致
        su = np.clip(u + (i + 1) * du_full / n_steps, 0.0, 1.0)
        sv = np.clip(v + (i + 1) * dv_full / n_steps, 0.0, 1.0)
        h = sample_texture(depth_tex, su, sv)
        if h.ndim > 1:
            h = h[:, 0]
        new_hit = (first_hit == n_steps) & (h > ray_z)
        prev_z[new_hit] = 1.0 - i * dz_per_step
        prev_h[new_hit] = h[new_hit]  # 命中时的表面高度（作为上层 h）
        first_hit = np.where(new_hit, i, first_hit)

    # 线性插值精修交点：w_prev=1 表示交点就在上层样本处
    ray_z_hit = 1.0 - (first_hit + 1).astype(np.float32) * dz_per_step
    denom = (prev_z - prev_h) + (prev_h - ray_z_hit) + 1e-8
    w_prev = np.clip((prev_h - ray_z_hit) / denom, 0, 1)
    # 未命中（纯黑凹陷）→ 交点在高度场底部 z=0，偏移应取满值而非保留原 UV
    w_prev = np.where(first_hit < n_steps, w_prev, 1.0)

    # 插值步进索引（prev_step 与 hit_step 之间线性插值；h=1 的纯白像素
    # 交点在片段自身处，偏移为 0 是几何正确结果）；未命中时 w_prev=1 → 满偏移
    t_interp = first_hit.astype(np.float32) + (1.0 - w_prev)
    offset_u = t_interp * du_full / n_steps
    offset_v = t_interp * dv_full / n_steps

    # 边缘安全衰减：按像素到 UV 边界的距离收缩偏移，确保最终 UV 不越界
    # fade 同时应用于 UV 偏移和世界位移，保持几何与纹理一致
    border = np.minimum(np.minimum(u, 1.0 - u), np.minimum(v, 1.0 - v))
    fade = np.clip(border / (np.abs(offset_u) + np.abs(offset_v) + 1e-6), 0.0, 1.0)

    # FIX2: 计算命中点沿视线的世界位移 disp = (1 - hit_z) * world_depth * fade
    # hit_z = 1 - t_interp / n_steps（线性插值后的高度场 z）
    hit_z = 1.0 - t_interp / n_steps
    disp = (1.0 - hit_z) * world_depth * fade

    return u + offset_u * fade, v + offset_v * fade, disp


# ==================== 软光栅化 ====================
def rasterize(world_verts, MVP, SCREEN_W, SCREEN_H):
    """返回每个被覆盖像素的行、列、世界坐标、UV、深度。"""
    uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
    tris = [(0, 1, 2), (0, 2, 3)]

    clip = transform_points(MVP, world_verts)
    ndc = clip[:, :3] / clip[:, 3:4]
    sx = (ndc[:, 0] * 0.5 + 0.5) * SCREEN_W
    sy = (ndc[:, 1] * 0.5 + 0.5) * SCREEN_H

    depth_buf = np.full((SCREEN_H, SCREEN_W), np.inf)
    uv_buf = np.zeros((SCREEN_H, SCREEN_W, 2))
    world_buf = np.zeros((SCREEN_H, SCREEN_W, 3))
    mask = np.zeros((SCREEN_H, SCREEN_W), dtype=bool)

    for (i0, i1, i2) in tris:
        p0, p1, p2 = [sx[i0], sy[i0]], [sx[i1], sy[i1]], [sx[i2], sy[i2]]
        w0, w1, w2 = clip[i0, 3], clip[i1, 3], clip[i2, 3]
        x0 = max(int(np.floor(min(p0[0], p1[0], p2[0]))), 0)
        x1 = min(int(np.ceil(max(p0[0], p1[0], p2[0]))), SCREEN_W - 1)
        y0 = max(int(np.floor(min(p0[1], p1[1], p2[1]))), 0)
        y1 = min(int(np.ceil(max(p0[1], p1[1], p2[1]))), SCREEN_H - 1)
        if x0 > x1 or y0 > y1:
            continue
        px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5,
                             np.arange(y0, y1 + 1) + 0.5)
        area = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])
        lam1 = ((p2[1] - p0[1]) * (px - p0[0]) - (p2[0] - p0[0]) * (py - p0[1])) / area
        lam2 = ((p0[1] - p1[1]) * (px - p0[0]) - (p0[0] - p1[0]) * (py - p0[1])) / area
        lam0 = 1.0 - lam1 - lam2
        gy, gx = np.where((lam0 >= 0) & (lam1 >= 0) & (lam2 >= 0))
        if len(gy) == 0:
            continue
        l0, l1, l2 = lam0[gy, gx], lam1[gy, gx], lam2[gy, gx]
        inv_w = l0 / w0 + l1 / w1 + l2 / w2
        depth = 1.0 / inv_w
        rows, cols = gy + y0, gx + x0
        nearer = depth < depth_buf[rows, cols]
        rows, cols = rows[nearer], cols[nearer]
        l0, l1, l2, inv_w, depth = (l0[nearer], l1[nearer], l2[nearer],
                                     inv_w[nearer], depth[nearer])
        depth_buf[rows, cols] = depth
        uv0, uv1, uv2 = uvs[i0], uvs[i1], uvs[i2]
        uv_buf[rows, cols, 0] = (l0 * uv0[0] / w0 + l1 * uv1[0] / w1 + l2 * uv2[0] / w2) / inv_w
        uv_buf[rows, cols, 1] = (l0 * uv0[1] / w0 + l1 * uv1[1] / w1 + l2 * uv2[1] / w2) / inv_w
        wp0, wp1, wp2 = world_verts[i0], world_verts[i1], world_verts[i2]
        for c in range(3):
            world_buf[rows, cols, c] = (l0 * wp0[c] / w0 + l1 * wp1[c] / w1 + l2 * wp2[c] / w2) / inv_w
        mask[rows, cols] = True

    ys, xs = np.where(mask)
    return ys, xs, world_buf[ys, xs], uv_buf[ys, xs], depth_buf[ys, xs]


# ==================== 完整渲染（含旋转缓存） ====================
_cache = {}


def render_frame(light_pos, yaw_deg, pitch_deg, roll_deg, eye,
                 SCREEN_W, SCREEN_H, rects, intensity, fov_deg=40.0):
    """渲染一帧（多张不同 z 的平行矩形，深度测试合成），旋转/缩放不变时复用光栅化缓存。
    每个 rect 可独立控制：depth_on, depth_scale, z, max_displacement。
    """
    yaw, pitch, roll = np.radians([yaw_deg, pitch_deg, roll_deg])
    cy, sy_ = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cr, sr = np.cos(roll), np.sin(roll)
    Ry = np.array([[cy, 0, sy_], [0, 1, 0], [-sy_, 0, cy]], dtype=np.float32)
    Rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], dtype=np.float32)
    Rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]], dtype=np.float32)
    model = Ry @ Rx @ Rz

    # 旋转 / 缩放键（精确到 0.01° / 0.01 即可）
    rot_key = (round(yaw_deg, 2), round(pitch_deg, 2), round(roll_deg, 2),
               round(fov_deg, 2),
               tuple((round(r.get("scale", 1.0), 2),
                      r.get("depth_on", True),
                      round(r.get("depth_scale", 1.0), 3),
                      round(r.get("z", 0.0), 3)) for r in rects))

    if _cache.get("key") != rot_key:
        T_w = model @ np.array([1.0, 0.0, 0.0], dtype=np.float32)
        B_w = model @ np.array([0.0, 1.0, 0.0], dtype=np.float32)
        N_w = model @ np.array([0.0, 0.0, 1.0], dtype=np.float32)
        view = look_at(eye, np.zeros(3, dtype=np.float32),
                       np.array([0.0, 1.0, 0.0], dtype=np.float32))
        proj = perspective(fov_deg, SCREEN_W / SCREEN_H, 0.1, 100.0)
        MVP = (proj @ view).astype(np.float32)

        geo = []
        for r in rects:
            sc = r.get("scale", 1.0)  # 图层独立缩放
            hw, hh = r["half_w"] * sc, r["half_h"] * sc
            verts = np.array([[-hw, -hh, r["z"]],
                              [ hw, -hh, r["z"]],
                              [ hw,  hh, r["z"]],
                              [-hw,  hh, r["z"]]], dtype=np.float32)
            world = (model @ verts.T).T
            ys, xs, pos, uv, depth = rasterize(world, MVP, SCREEN_W, SCREEN_H)
            if len(ys) == 0:
                geo.append({"ys": ys})
                continue
            u0, u1 = uv[:, 0], uv[:, 1]
            # 先计算视线向量（POM 和着色均需要）
            V = eye[None, :] - pos
            V /= (np.sqrt(np.sum(V * V, axis=-1, keepdims=True)) + 1e-8)
            # 视差遮挡贴图（POM）
            if (r.get("depth_tex") is not None and
                    r.get("depth_on", True) and
                    r.get("depth_scale", 1.0) > 0):
                # FIX3: 按图层世界尺寸做各向异性换算
                scale = r.get("scale", 1.0)
                span_u = 2.0 * r["half_w"] * scale      # u 轴世界宽度
                span_v = 2.0 * r["half_h"] * scale      # v 轴世界高度
                max_disp = r.get("max_displacement", 0.005) * r.get("depth_scale", 1.0)
                world_depth = max_disp * max(span_u, span_v)  # 世界空间最大位移
                max_disp_u = world_depth / span_u  # u/v 轴独立的最大 UV 偏移
                max_disp_v = world_depth / span_v
                Vt_x = V[:, 0] * T_w[0] + V[:, 1] * T_w[1] + V[:, 2] * T_w[2]
                Vt_y = V[:, 0] * B_w[0] + V[:, 1] * B_w[1] + V[:, 2] * B_w[2]
                Vt_z = V[:, 0] * N_w[0] + V[:, 1] * N_w[1] + V[:, 2] * N_w[2]
                Vt = np.stack([Vt_x, Vt_y, Vt_z], axis=-1)
                Vt_n = np.sqrt(Vt_x**2 + Vt_y**2 + Vt_z**2) + 1e-8
                Vt /= Vt_n[:, None]
                # FIX4(b): 步数随位移自适应，上限 48
                base_steps = r.get("pom_steps", 8)
                n_steps = int(np.clip(base_steps * r.get("depth_scale", 1.0), base_steps, 8))
                u0, u1, disp = parallax_occlusion(
                    r["depth_tex"], u0, u1, Vt, T_w, B_w, N_w,
                    V, max_disp_u, max_disp_v, world_depth, n_steps=n_steps)
                # FIX2: 用命中点世界位移修正片元几何（在 alpha 过滤之前完成）
                pos = pos - V * disp[:, None]
                depth = depth + disp          # 沿视线方向即靠近相机
                V = normalize(eye - pos)      # 重算视线向量
            albedo = sample_texture(r["albedo_tex"], u0, u1)
            if albedo.shape[1] == 4:
                # alpha 测试镂空：透明像素丢弃，不遮挡后方矩形
                keep = albedo[:, 3] >= 0.5
                ys, xs, pos, uv, depth = (ys[keep], xs[keep], pos[keep],
                                          uv[keep], depth[keep])
                V = V[keep]
                albedo = albedo[keep, :3]
                # FIX1: 仅按 keep 过滤，不回退到光栅化原始 UV
                u0, u1 = u0[keep], u1[keep]
            # 预计算共享纹理索引（normal 与 ORM 尺寸相同时复用）
            n_row, n_col = _uv_to_indices(r["normal_tex"], u0, u1)
            if r["orm_tex"] is not None:
                # ORM 贴图：R → AO，G → roughness，B → metallic（线性数据，不做 sRGB 解码）
                if r["orm_tex"].shape[:2] == r["normal_tex"].shape[:2]:
                    orm = r["orm_tex"][n_row, n_col]
                else:
                    orm = sample_texture(r["orm_tex"], u0, u1)
                ao = np.clip(orm[:, 0], 0.0, 1.0)
                roughness = np.clip(orm[:, 1], 0.02, 1.0)
                metallic = np.clip(orm[:, 2], 0.0, 1.0)
            else:
                ao_f, rough_f, metal_f = r["fixed_orm"]
                n = len(ys)
                ao = np.full(n, ao_f, dtype=np.float32)
                roughness = np.full(n, np.clip(rough_f, 0.02, 1.0), dtype=np.float32)
                metallic = np.full(n, metal_f, dtype=np.float32)
            # 固定 ORM 图层标记：着色阶段每帧重读，保证滑块实时生效
            fixed_pbr = None if r["orm_tex"] is not None else r["fixed_orm"]
            # 自发光贴图（线性颜色，强度在着色阶段由 rect["emissive_strength"] 控制）
            if r.get("emissive_tex") is not None:
                if r["emissive_tex"].shape[:2] == r["normal_tex"].shape[:2]:
                    emissive = r["emissive_tex"][n_row, n_col]
                else:
                    emissive = sample_texture(r["emissive_tex"], u0, u1)
            else:
                emissive = None
            # 法线贴图（使用预计算索引）
            n_tang = r["normal_tex"][n_row, n_col]
            n_tang = n_tang * 2.0 - 1.0
            n_tang /= (np.sqrt(np.sum(n_tang * n_tang, axis=-1, keepdims=True)) + 1e-8)
            N = n_tang[:, 0:1] * T_w + n_tang[:, 1:2] * B_w + n_tang[:, 2:3] * N_w
            N /= (np.sqrt(np.sum(N * N, axis=-1, keepdims=True)) + 1e-8)
            geo.append({"ys": ys, "xs": xs, "pos": pos, "depth": depth,
                        "N": N, "V": V, "albedo": albedo, "ao": ao,
                        "metallic": metallic, "roughness": roughness,
                        "emissive": emissive, "fixed_pbr": fixed_pbr})
        _cache.update({"key": rot_key, "geo": geo})
    else:
        geo = _cache["geo"]

    frame = np.tile(np.array([0.05, 0.06, 0.09], dtype=np.float32),
                    (SCREEN_H, SCREEN_W, 1))
    depth_acc = np.full((SCREEN_H, SCREEN_W), np.inf, dtype=np.float32)
    light_pos = np.asarray(light_pos, dtype=np.float32)
    for g, rc in zip(geo, rects):
        if len(g["ys"]) == 0:
            continue
        pos, N, V = g["pos"], g["N"], g["V"]
        albedo, metallic, roughness, ao = g["albedo"], g["metallic"], g["roughness"], g["ao"]
        # 固定 ORM 图层：每帧从 rect 重读粗糙度/金属度（滑块实时调节）
        if g["fixed_pbr"] is not None:
            n = albedo.shape[0]
            roughness = np.full(n, np.clip(rc["fixed_orm"][1], 0.02, 1.0),
                                dtype=np.float32)
            metallic = np.full(n, rc["fixed_orm"][2], dtype=np.float32)

        # 点光源（平方反比）
        to_light = light_pos[None, :] - pos
        dist2 = to_light[:, 0] ** 2 + to_light[:, 1] ** 2 + to_light[:, 2] ** 2
        inv_dist = 1.0 / (np.sqrt(dist2) + 1e-8)
        Lx = to_light[:, 0] * inv_dist
        Ly = to_light[:, 1] * inv_dist
        Lz = to_light[:, 2] * inv_dist
        radiance = intensity / np.maximum(dist2, 1e-4)

        # --- Cook-Torrance GGX（内联，消除函数调用和中间数组分配）---
        Hx = Lx + V[:, 0]; Hy = Ly + V[:, 1]; Hz = Lz + V[:, 2]
        inv_Hn = 1.0 / (np.sqrt(Hx * Hx + Hy * Hy + Hz * Hz) + 1e-8)
        Hx *= inv_Hn; Hy *= inv_Hn; Hz *= inv_Hn

        NdotL = np.clip(N[:, 0] * Lx + N[:, 1] * Ly + N[:, 2] * Lz, 0, 1)
        NdotV = np.clip(N[:, 0] * V[:, 0] + N[:, 1] * V[:, 1] + N[:, 2] * V[:, 2], 1e-4, 1)
        NdotH = np.clip(N[:, 0] * Hx + N[:, 1] * Hy + N[:, 2] * Hz, 0, 1)
        HdotV = np.clip(Hx * V[:, 0] + Hy * V[:, 1] + Hz * V[:, 2], 0, 1)

        # metallic 形状对齐：标量或 (N,) → 可广播
        m = np.atleast_1d(metallic)
        if m.shape[0] == albedo.shape[0] and m.ndim == 1:
            m = m[:, None]  # (N,1) 用于 (N,3) 广播

        # D: GGX 法线分布（roughness 为标量时仅计算一次 a2）
        a2 = (roughness * roughness) ** 2  # roughness^4
        denom = NdotH * NdotH * (a2 - 1.0) + 1.0
        D = a2 / (np.pi * denom * denom + 1e-8)

        # G: Smith-Schlick 几何遮蔽
        k = (roughness + 1.0) ** 2 * 0.125  # (r+1)^2 / 8
        G = (NdotV / (NdotV * (1.0 - k) + k + 1e-8)) * \
            (NdotL / (NdotL * (1.0 - k) + k + 1e-8))

        # F: Schlick 菲涅尔（(1-x)^5 用连乘代替幂运算）
        F0 = 0.04 * (1.0 - m) + albedo * m
        t = 1.0 - HdotV
        t2 = t * t
        t5 = t2 * t2 * t  # (1-HdotV)^5
        F = F0 + (1.0 - F0) * t5[:, None]

        # 镜面反射 + 漫反射
        spec = (D * G)[:, None] * F / (4.0 * NdotV[:, None] * NdotL[:, None] + 1e-4)
        kD = (1.0 - F) * (1.0 - m)
        hdr = (kD * albedo * (1.0 / np.pi) + spec) * \
              (radiance * NdotL)[:, None] + 0.03 * albedo * ao[:, None]

        # 自发光：直接叠加到 HDR，不受光照与阴影影响，强度由滑块控制
        if g["emissive"] is not None:
            # α(r)=sin²(k·(|re-r|+|rl-r|))：视点/光源/像素三方距离调制（类干涉条纹）
            d_eye = np.sqrt(((pos - eye[None, :]) ** 2).sum(axis=-1))
            d_lgt = np.sqrt(dist2)                # 复用已算好的到光源平方距离
            alpha = np.maximum(np.sin(rc.get("alpha_k", 20.0) * (d_eye + d_lgt))-0.5,0) ** 2
            hdr = hdr + g["emissive"] * rc.get("emissive_strength", 0.0) * alpha[:, None]

        # Reinhard 色调映射 + gamma 2.2
        ldr = np.clip(hdr / (hdr + 1.0), 0, 1) ** (1.0 / 2.2)
        nearer = g["depth"] < depth_acc[g["ys"], g["xs"]]
        ys, xs = g["ys"][nearer], g["xs"][nearer]
        frame[ys, xs] = ldr[nearer]
        depth_acc[ys, xs] = g["depth"][nearer]
    return frame


# ==================== 主程序 ====================
if __name__ == "__main__":
    SCREEN_W, SCREEN_H = 512, 512

    print("载入贴图...")
    albedo_tex = load_texture("恋与深空_rgba.png", max_side=640,
                              srgb_to_linear=True, keep_alpha=True)
    normal_tex = load_texture("Nomal.png", max_side=640, srgb_to_linear=False)
    orm_tex = load_texture("金属纹理.png", max_side=640, srgb_to_linear=False)
    bg_albedo_tex = load_texture("恋与深空_背景扩展.png", max_side=640,
                                 srgb_to_linear=True)
    bg_normal_tex = load_texture("恋与深空_背景扩展Nomal.png", max_side=640,
                                 srgb_to_linear=False)
    depth_tex = load_texture("depth.png", max_side=640, srgb_to_linear=False)
    bg_depth_tex = load_texture("恋与深空_背景扩展depth.png", max_side=640,
                                srgb_to_linear=False)
    bg_emissive_tex = load_texture("闪卡纹理.png", max_side=640,
                                   srgb_to_linear=True)

    def quad_size(tex, half_h=1.0):
        return half_h * tex.shape[1] / tex.shape[0], half_h

    half_w1, half_h1 = quad_size(albedo_tex)
    half_w2, half_h2 = quad_size(bg_albedo_tex)

    # 两张平行于 xy 平面的矩形：前景卡片 z=0.1，背景 z=-0.1
    rects = [
        dict(albedo_tex=albedo_tex, normal_tex=normal_tex, orm_tex=None,
             depth_tex=depth_tex, depth_on=True, depth_scale=1.0,
             max_displacement=0.005, pom_steps=3,
             fixed_orm=(1.0, 0.5, 0.4), z=0.1, half_w=half_w1, half_h=half_h1,
             scale=1.0),
        dict(albedo_tex=bg_albedo_tex, normal_tex=bg_normal_tex, orm_tex=orm_tex,
             depth_tex=bg_depth_tex, depth_on=True, depth_scale=1.0,
             max_displacement=0.005, pom_steps=3,
             fixed_orm=None, z=-0.1,
             emissive_tex=bg_emissive_tex, emissive_strength=1.5, alpha_k=20.0,
             half_w=half_w2, half_h=half_h2, scale=1.0),
    ]
    print(f"前景卡片: 颜色 {albedo_tex.shape[1]}×{albedo_tex.shape[0]}(RGBA)，"
          f"法线 {normal_tex.shape[1]}×{normal_tex.shape[0]}，"
          f"ORM(R/G/B=AO/粗糙/金属) {orm_tex.shape[1]}×{orm_tex.shape[0]}")
    print(f"背景: 颜色 {bg_albedo_tex.shape[1]}×{bg_albedo_tex.shape[0]}，"
          f"法线 {bg_normal_tex.shape[1]}×{bg_normal_tex.shape[0]}，"
          f"自发光 {bg_emissive_tex.shape[1]}×{bg_emissive_tex.shape[0]}，"
          f"固定 ORM(AO/粗糙/金属)={rects[1]['fixed_orm']}")

    # 光源 / 相机初始值（前景卡片 ORM 由金属纹理.png 提供，背景为固定值）
    INTENSITY = 30.0
    INIT_LIGHT = np.array([0, 0, 2], dtype=np.float32)
    INIT_YAW, INIT_PITCH, INIT_ROLL = 0.0, 0.0, 0.0
    INIT_FOV = 40.0
    EYE = np.array([0.0, 0.0, 3.0], dtype=np.float32)

    # ---- 初始渲染 ----
    import time
    fig = plt.figure(figsize=(14, 8))
    fig.canvas.manager.set_window_title("PBR 双矩形交互渲染")

    # 左侧：渲染图像（尽可能大）
    ax = fig.add_axes([0.02, 0.03, 0.56, 0.93])

    t0 = time.perf_counter()
    frame0 = render_frame(INIT_LIGHT, INIT_YAW, INIT_PITCH, INIT_ROLL, EYE,
                          SCREEN_W, SCREEN_H, rects, INTENSITY, INIT_FOV)
    print(f"首帧渲染耗时: {(time.perf_counter() - t0) * 1000:.1f} ms")
    im = ax.imshow(frame0, origin="lower")
    ax.axis("off")

    title_text = fig.suptitle(
        f"PBR 双矩形交互渲染  |  光源({INIT_LIGHT[0]:+.1f}, {INIT_LIGHT[1]:+.1f}, "
        f"{INIT_LIGHT[2]:+.1f})  旋转({INIT_YAW:+.0f}°, {INIT_PITCH:+.0f}°, "
        f"{INIT_ROLL:+.0f}°)  |  Cook-Torrance GGX",
        fontsize=13)

    # ---- 右侧滑块 ----
    slider_cfg = [
        # 光源
        ("Light X",  -3.0, 3.0, INIT_LIGHT[0], 0.05),
        ("Light Y",  -3.0, 3.0, INIT_LIGHT[1], 0.05),
        ("Light Z",   0.5, 5.0, INIT_LIGHT[2], 0.05),
        # 旋转
        ("Yaw (Y)",   -60, 60, INIT_YAW,  1.0),
        ("Pitch (X)", -60, 60, INIT_PITCH, 1.0),
        ("Roll (Z)",  -60, 60, INIT_ROLL, 1.0),
        # 全局
        ("FOV", 10.0, 40.0, INIT_FOV, 1.0),
        # 前景图层
        ("前景缩放",   0.2, 2.0, rects[0]["scale"], 0.01),
        ("前景Z",     -1.0, 1.0, rects[0]["z"], 0.01),
        ("前景深度",   0.0, 1.0, 1.0, 1.0),       # 0=关, 1=开
        ("前景深度缩放", 0.0, 50.0, rects[0]["depth_scale"], 0.1),
        ("前景粗糙度", 0.02, 1.0, rects[0]["fixed_orm"][1], 0.01),
        ("前景金属度", 0.0, 1.0, rects[0]["fixed_orm"][2], 0.01),
        # 背景图层
        ("背景缩放",   0.2, 2.0, rects[1]["scale"], 0.01),
        ("背景Z",     -1.0, 1.0, rects[1]["z"], 0.01),
        ("背景深度",   0.0, 1.0, 1.0, 1.0),       # 0=关, 1=开
        ("背景深度缩放", 0.0, 50.0, rects[1]["depth_scale"], 0.1),
        ("背景自发光",   0.0, 5.0, rects[1]["emissive_strength"], 0.05),
        ("自发光条纹K",   0.0, 60.0, rects[1]["alpha_k"], 0.5),
    ]
    sliders = []
    n_sliders = len(slider_cfg)
    s_left, s_width = 0.63, 0.33
    s_top, s_gap = 0.95, 0.05
    for i, (label, vmin, vmax, valinit, step) in enumerate(slider_cfg):
        y = s_top - (i + 1) * s_gap
        ax_s = fig.add_axes([s_left, y, s_width, 0.025], facecolor="#222222")
        s = Slider(ax_s, label, vmin, vmax, valinit=valinit,
                   valstep=step, color="#ff7744")
        s.label.set_color("#333333")
        s.valtext.set_color("#333333")
        sliders.append(s)

    def update(_):
        light = np.array([sliders[0].val, sliders[1].val, sliders[2].val],
                         dtype=np.float32)
        yaw, pitch, roll = sliders[3].val, sliders[4].val, sliders[5].val
        fov = sliders[6].val
        # 前景图层
        rects[0]["scale"] = sliders[7].val
        rects[0]["z"] = sliders[8].val
        rects[0]["depth_on"] = sliders[9].val > 0.5
        rects[0]["depth_scale"] = sliders[10].val
        rects[0]["fixed_orm"] = (1.0, sliders[11].val, sliders[12].val)
        # 背景图层
        rects[1]["scale"] = sliders[13].val
        rects[1]["z"] = sliders[14].val
        rects[1]["depth_on"] = sliders[15].val > 0.5
        rects[1]["depth_scale"] = sliders[16].val
        rects[1]["emissive_strength"] = sliders[17].val
        rects[1]["alpha_k"] = sliders[18].val
        t0 = time.perf_counter()
        frame = render_frame(light, yaw, pitch, roll, EYE,
                             SCREEN_W, SCREEN_H, rects, INTENSITY, fov)
        ms = (time.perf_counter() - t0) * 1000
        im.set_data(frame)
        title_text.set_text(
            f"PBR 双矩形交互渲染  |  光源({light[0]:+.1f}, {light[1]:+.1f}, "
            f"{light[2]:+.1f})  旋转({yaw:+.0f}°, {pitch:+.0f}°, "
            f"{roll:+.0f}°)  FOV={fov:.0f}°  {ms:.0f}ms")
        fig.canvas.draw_idle()

    for s in sliders:
        s.on_changed(update)

    print("控件已就绪。拖动滑块观察光照 / 旋转变化。")
    plt.show()
