import numpy as np
from PIL import Image

def voronoi_distance_field(width, height, num_points, seed=42):
    """
    返回 F1(最近距离) 和 F2(次近距离) 两个通道
    F1 可用于细胞内部渐变
    F2-F1 可用于生成平滑的边缘线（比矢量线条更适合做PBR贴图）
    """
    rng = np.random.default_rng(seed)
    points = rng.uniform(0, 1, (num_points, 2))
    points[:, 0] *= width
    points[:, 1] *= height
    
    # 创建像素坐标网格
    yy, xx = np.mgrid[0:height, 0:width]
    pixels = np.stack([xx.ravel(), yy.ravel()], axis=-1).astype(np.float32)
    
    # 分块计算避免内存爆炸
    f1 = np.full(height * width, np.inf, dtype=np.float32)
    f2 = np.full(height * width, np.inf, dtype=np.float32)
    
    chunk_size = 65536
    for start in range(0, len(pixels), chunk_size):
        end = min(start + chunk_size, len(pixels))
        diff = pixels[start:end, None, :] - points[None, :, :]  # (chunk, N, 2)
        dist_sq = np.sum(diff ** 2, axis=-1)  # (chunk, N)
        
        # 取最小和次小
        sorted_dist = np.partition(dist_sq, 1, axis=-1)[:, :2]
        f1[start:end] = np.sqrt(sorted_dist[:, 0])
        f2[start:end] = np.sqrt(sorted_dist[:, 1])
    
    return f1.reshape(height, width), f2.reshape(height, width)

# === 生成PBR友好的边缘贴图 ===
f1, f2 = voronoi_distance_field(1024, 1024, num_points=300, seed=42)

# 边缘检测：F2 - F1 在cell边界处趋近于0，内部较大
edge = f2 - f1
edge_normalized = np.clip(edge / edge.max(), 0, 1)

# 反转：边界亮、内部暗 → 适合做金属度/高光遮罩
metallic_mask = 1.0 - edge_normalized

Image.fromarray((metallic_mask * 255).astype(np.uint8)).save("voronoi_metallic.png")

# F1 归一化 → 适合做细胞内渐变（如粗糙度从中心到边缘变化）
f1_norm = np.clip(f1 / f1.max(), 0, 1)
Image.fromarray((f1_norm * 255).astype(np.uint8)).save("voronoi_roughness_gradient.png")