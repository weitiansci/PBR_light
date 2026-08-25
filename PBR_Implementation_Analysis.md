# PBR 光照实现修改分析

## 概述
要将当前的混合式光照模型（Blinn-Phong）转换为完整的物理基础渲染（PBR）模型，核心在于引入 **Cook-Torrance BRDF**。这需要从“模拟光影效果”转变为“模拟微表面反射物理”。

## 核心修改逻辑对比

| 组件 | 当前实现 (Blinn-Phong / 启发式) | 修改后实现 (PBR / Cook-Torrance) | 修改要点 |
| :--- | :--- | :--- | :--- |
| **漫反射 (Diffuse)** | `ndotl * 0.6 + 0.4` | `kD * (c / π)` | 引入能量守恒：漫反射能量 = 总能量 - 镜面反射能量。 |
| **镜面反射 (Specular)** | `pow(ndoth, uSpecPower)` | `(D * F * G) / (4 * (n·v) * (n·l))` | 使用分布函数(D)、几何函数(G)和菲涅尔方程(F)的乘积。 |
| **粗糙度 (Roughness)** | 无（通过 `uSpecPower` 间接控制） | 引入 `uRoughness` 变量 | 粗糙度决定微表面的对齐程度，直接影响 D 和 G 函数。 |
| **金属度 (Metallic)** | 无 | 引入 `uMetallic` 变量 | 金属材质几乎没有漫反射，镜面反射强度由金属度决定。 |
| **菲涅尔效应 (Fresnel)** | 无 | 使用 Schlick 近似 | 模拟光线在不同入射角下反射比例的变化。 |

## 代码层级对应修改

### 1. 统一缓冲区 (UBO) 结构更新
需要增加 PBR 核心参数：
```glsl
// 修改前
float uSpecPower; 

// 修改后
float uRoughness; // 粗糙度 [0-1]
float uMetallic;  // 金属度 [0-1]
vec4 uBaseColor;  // 材质基础颜色
```

### 2. 光照函数核心重写 (`ApplyNormalLight`)

#### 修改前 (当前实现):
```glsl
vec3 ApplyNormalLight(vec3 baseColor, vec3 normal, vec3 viewDir, vec2 uv) {
    vec3 viewLocal  = normalize(viewDir);
    vec3 lightLocal = normalize(ubo.uLightDir.xyz);
    vec3 halfDir    = normalize(lightLocal + viewLocal);

    float ndotl = max(dot(normal, lightLocal), 0.0);
    float ndoth = max(dot(normal, halfDir),    0.0);
    float ndotv = max(dot(normal, vec3(abs(viewDir.x), viewDir.y, viewDir.z)), 0.0);

    float diffuse = ndotl * 0.6 + 0.4; // 启发式漫反射
    float grazing = 1.0 - ndotv;
    float specular = pow(ndoth, ubo.uSpecPower); // Blinn-Phong 镜面

    vec3 reflectDir = reflect(-viewDir, normal);
    vec3 envColor   = GetProceduralEnvColor(reflectDir);
    float envWeight = specular * 0.5 + grazing * grazing * 0.3;

    vec3 lit = baseColor * diffuse;
    lit += ubo.uLightScale * specular * vec3(1.0, 0.95, 0.80);
    lit += envColor * envWeight * ubo.uEnvStrength;

    return clamp(lit, 0.0, 1.0);
}
```

#### 修改后 (PBR 实现):
```glsl
vec3 ApplyNormalLight(vec3 baseColor, vec3 normal, vec3 viewDir, vec2 uv) {
    vec3 V = normalize(viewDir);
    vec3 L = normalize(ubo.uLightDir.xyz);
    vec3 H = normalize(V + L);
    
    float dotNV = max(dot(normal, V), 0.0);
    float dotNL = max(dot(normal, L), 0.0);
    float dotNH = max(dot(normal, H), 0.0);

    // 1. 菲涅尔方程 (Schlick 近似)
    vec3 F0 = mix(vec3(0.04), baseColor, ubo.uMetallic); // 金属是反射颜色，绝缘体是 0.04
    vec3 F = F0 + (1.0 - F0) * pow(1.0 - max(dot(H, V), 0.0), 5.0);

    // 2. 分布函数 (Trowbridge-Reitz GGX)
    float alpha = ubo.uRoughness * ubo.uRoughness;
    float alpha2 = alpha * alpha;
    float denom = (dotNV * dotNV * (alpha2 - 1.0) + 1.0);
    float D = alpha2 / (3.14159 * denom * denom);

    // 3. 几何函数 (Smith's method with GGX)
    float k = (uRoughness + 1.0) * (uRoughness + 1.0) / 8.0;
    float G1V = dotNV / (dotNV * (1.0 - k) + k);
    float G1L = dotNL / (dotNL * (1.0 - k) + k);
    float G = G1V * G1L;

    // 4. 镜面反射项
    vec3 specular = (D * F * G) / (4.0 * max(dot(V, N), 0.0) * max(dot(L, N), 0.0) + 0.001);

    // 5. 漫反射项 (能量守恒)
    vec3 kD = (vec3(1.0) - F);
    kD *= (1.0 - ubo.uMetallic);
    vec3 diffuse = kD * baseColor / 3.14159;

    // 最终混合
    vec3 lit = (diffuse + specular) * ubo.uLightScale * dotNL;
    
    // 环境光处理 (可选)
    vec3 envColor = GetProceduralEnvColor(reflect(-V, normal));
    lit += envColor * F * ubo.uEnvStrength;

    return clamp(lit, 0.0, 1.0);
}
```

## 修改要点总结

1.  **引入 Roughness (粗糙度)**: 取代了原来的 `uSpecPower`。Roughness 为 0 时是镜面反射，为 1 时是完全漫反射。
2.  **引入 Metallic (金属度)**: 决定了材质是像金子/铝Ini（金属）还是像塑料/石头（绝缘体）。
3.  **能量守恒**: 通过 `kD = (1.0 - F) * (1.0 - metallic)` 确保了光线不会在漫反射和镜面反射中被重复计算。
4.  **Cook-Torrance 模型**: 实现了真实的微表面分布（D）和几何遮挡（G），使光照在不同角度下的衰减符合物理规律。
