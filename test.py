import numpy as np
from PIL import Image
from dataclasses import dataclass


@dataclass
class SeedPoint:
    """Voronoi 种子点对象"""

    x: float  # 二维坐标
    y: float
    normal: tuple  # 法线值 (nx, ny, nz)，范围 [-1, 1]
    metalness: float  # 金属度 [0, 1]
    roughness: float  # 粗糙度 [0, 1]
    display: float  # 显示值，用于阈值过滤


def generate_seed_points(num_points, seed=42):
    """生成一组随机种子点对象"""
    rng = np.random.default_rng(seed)
    points = []
    for _ in range(num_points):
        x = rng.uniform(0, 1)
        y = rng.uniform(0, 1)

        # 随机法线：在半球上随机采样，确保 z > 0（朝外）
        theta = rng.uniform(0, 2 * np.pi)
        phi = rng.uniform(0, np.pi / 4)  # 限制倾斜角度，避免太极端
        nx = np.sin(phi) * np.cos(theta)
        ny = np.sin(phi) * np.sin(theta)
        nz = np.cos(phi)
        # 归一化
        length = np.sqrt(nx**2 + ny**2 + nz**2)
        nx, ny, nz = nx / length, ny / length, nz / length

        metalness = rng.uniform(0.9, 1.0)
        roughness = rng.uniform(0.0, 0.20)
        display = rng.uniform(0.0, 1.0)

        points.append(SeedPoint(x, y, (nx, ny, nz), metalness, roughness, display))
    return points


def generate_voronoi_pbr_maps(
    width=1024,
    height=1024,
    num_points=200,
    threshold=0.5,
    seed=42,
    bg_normal=(128, 128, 255),  # 背景法线 = 平面朝上 (0,0,1)
    bg_metalness=0,
    bg_roughness=255,
):
    """
    生成 Voronoi PBR 贴图（法线图、金属度图、粗糙度图）

    Parameters:
        width, height  : 输出图像尺寸
        num_points     : 种子点数量
        threshold      : 显示阈值，display > threshold 的区域才显示
        seed           : 随机种子
        bg_normal      : 背景法线颜色 (RGB)
        bg_metalness   : 背景金属度值 (0-255)
        bg_roughness   : 背景粗糙度值 (0-255)
    """
    # ========== 1. 生成种子点 ==========
    points = generate_seed_points(num_points, seed)
    print(f"生成 {num_points} 个种子点")
    print(f"显示阈值: {threshold}")
    visible_count = sum(1 for p in points if p.display > threshold)
    print(f"可见区域数: {visible_count} / {num_points}")

    # 提取坐标（像素空间）
    coords = np.array([[p.x * width, p.y * height] for p in points], dtype=np.float32)

    # ========== 2. 距离场：逐像素找最近种子点 ==========
    print("计算距离场...")
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    pixels = np.stack([xx.ravel(), yy.ravel()], axis=-1)  # (W*H, 2)

    # 分块计算，避免内存爆炸
    chunk_size = 32768
    nearest_idx = np.zeros(height * width, dtype=np.int32)

    for start in range(0, len(pixels), chunk_size):
        end = min(start + chunk_size, len(pixels))
        # (chunk, 1, 2) - (1, N, 2) → (chunk, N, 2)
        diff = pixels[start:end, np.newaxis, :] - coords[np.newaxis, :, :]
        dist_sq = np.sum(diff**2, axis=-1)  # (chunk, N)
        nearest_idx[start:end] = np.argmin(dist_sq, axis=-1)

    nearest_idx = nearest_idx.reshape(height, width)
    print("距离场计算完成")

    # ========== 3. 构建三张贴图 ==========
    normal_map = np.zeros((height, width, 3), dtype=np.uint8)
    metal_map = np.zeros((height, width), dtype=np.uint8)
    rough_map = np.zeros((height, width), dtype=np.uint8)
    AO_map = np.zeros((height, width), dtype=np.uint8)

    # 先填充背景
    normal_map[:, :, 0] = bg_normal[0]
    normal_map[:, :, 1] = bg_normal[1]
    normal_map[:, :, 2] = bg_normal[2]
    metal_map[:, :] = bg_metalness
    rough_map[:, :] = bg_roughness
    AO_map[:, :] = 255  # 默认 AO 值为最大值

    # ========== 4. 按阈值填充可见区域 ==========
    print("填充可见区域...")
    for i, pt in enumerate(points):
        if pt.display <= threshold:
            continue  # 不显示，保持背景

        # 找到属于该种子点的所有像素
        mask = nearest_idx == i

        # 法线：将 [-1,1] 映射到 [0,255]
        nx, ny, nz = pt.normal
        normal_map[mask, 0] = int((nx * 0.5 + 0.5) * 255)
        normal_map[mask, 1] = int((ny * 0.5 + 0.5) * 255)
        normal_map[mask, 2] = int((nz * 0.5 + 0.5) * 255)

        # 金属度和粗糙度：[0,1] → [0,255]
        metal_map[mask] = int(pt.metalness * 255)
        rough_map[mask] = int(pt.roughness * 255)

    print("填充完成")

    # ========== 5. 绘制细胞边界线（可选，增强视觉效果） ==========
    # 通过检测相邻像素的 nearest_idx 是否不同来判断边界
    print("绘制边界线...")
    boundary = np.zeros((height, width), dtype=bool)
    # 水平方向
    boundary[:, :-1] |= nearest_idx[:, :-1] != nearest_idx[:, 1:]
    # 垂直方向
    boundary[:-1, :] |= nearest_idx[:-1, :] != nearest_idx[1:, :]

    # 在边界上叠加一条暗线（可选）
    # boundary_color = 0  # 黑色边界
    # normal_map[boundary] = [boundary_color, boundary_color, boundary_color]
    # metal_map[boundary] = 0
    # rough_map[boundary] = 255
    # AO_map[boundary] = 0

    # ========== 6. 保存贴图 ==========
    img_normal = Image.fromarray(normal_map, mode="RGB")
    img_metal = Image.fromarray(metal_map, mode="L")
    img_rough = Image.fromarray(rough_map, mode="L")
    img_AO = Image.fromarray(AO_map, mode="L")

    ORM_map = np.stack(
        [AO_map, rough_map, metal_map], axis=-1
    )  # ORM 通道顺序: R=AO, G=Roughness, B=metalness
    img_orm = Image.fromarray(ORM_map, mode="RGB")
    img_normal.save("voronoi_normal.png")
    img_metal.save("voronoi_metalness.png")
    img_rough.save("voronoi_roughness.png")
    img_AO.save("voronoi_ao.png")
    img_orm.save("voronoi_orm.png")
    test_img = np.full_like(img_orm, 255)  # 白色测试图像
    test_img[: test_img.shape[0] // 2, :, 1] = 0
    test_img[: test_img.shape[0] // 2, :, 2] = 255
    test_img[test_img.shape[0] // 2 :, :, 1] = 255
    test_img[test_img.shape[0] // 2 :, :, 2] = 0
    Image.fromarray(test_img, mode="RGB").save("voronoi_test.png")

    print("✅ 保存完成:")
    print("   → voronoi_normal.png")
    print("   → voronoi_metalness.png")
    print("   → voronoi_roughness.png")
    print("   → voronoi_ao.png")

    return img_normal, img_metal, img_rough


# ========== 主程序 ==========
if __name__ == "__main__":
    generate_voronoi_pbr_maps(
        width=720,
        height=1280,
        num_points=500,
        threshold=0.8,  # 调整此值控制显示区域数量
        seed=42,
    )
