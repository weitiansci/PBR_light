# 闪卡彩虹渐变效果 — 原理、公式与 GLSL 实现

> 基于衍射光栅、薄膜干涉、结构色等物理光学原理，结合 Alan Zucconi 的 CD-ROM 着色器教程、维基百科光栅方程、小米 9 全息幻彩工艺、宝可梦闪卡工艺等资料整理。

---

## 目录

1. [闪卡的物理原理](#1-闪卡的物理原理)
2. [结构光核心公式推导](#2-结构光核心公式推导)
3. [波长到 RGB 的光谱转换](#3-波长到-rgb-的光谱转换)
4. [GLSL 闪卡彩虹着色器实现](#4-glsl-闪卡彩虹着色器实现)
5. [效果调参指南](#5-效果调参指南)

---

## 1. 闪卡的物理原理

### 1.1 什么是闪卡

闪卡（Holographic Card / Foil Card）是一种利用**微观光栅结构**产生彩虹色反光的卡片。市面上常见的形态：

| 类型 | 代表产品 | 工艺 |
|------|---------|------|
| **全息烫印卡** | 宝可梦闪卡（宇宙全息、星光全息等） | 全息铝箔热压转印 |
| **纳米光栅膜片** | 小米 9 全息幻彩后盖 | 纳米级激光雕刻 + 双层镀膜 |
| **柱镜光栅卡** | 3D 变画光栅卡 | 柱镜透镜阵列 + 多图像分条 |
| **衍射光栅卡** | 信用卡全息防伪标 | 微细衍射光栅 + 镀铝反射层 |

### 1.2 核心原理：衍射光栅

闪卡表面的微观结构是**衍射光栅**——由大量等宽、等间距的平行狭缝或沟槽组成，间距在光波长量级（约 300-2000 nm）。

**物理机制：**

```
白光入射 → 光栅衍射 → 不同波长向不同角度偏折 → 人眼看到彩虹色
```

当白光照射光栅时，不同波长的光在不同角度发生**相长干涉**（constructive interference），形成光谱色散。由于：

- **不同视角**：观察者改变角度时，接收到的波长变化，颜色随之变化（视角依赖虹彩）
- **不同区域**：卡片表面不同位置的光栅方向/间距不同，同一角度下不同区域反射不同波长（空间彩虹渐变）

### 1.3 制造工艺（以小米 9 为例）

根据小米官方科普：

> "小米 9 使用纳米全息纹 + 双层纳米镀，超过 100 万个光学点阵，约 1.7 亿根纳米光栅。"

工艺流程：
1. 在纹理模具上用激光雕刻**上万个幻彩衍射单元**
2. 每个单元上切割出多个**光学衍射面**
3. 不同单元的衍射面方向不同 → 空间上产生渐变彩虹
4. 通过 UV 转印将纳米光栅结构复制到玻璃后盖
5. 双层纳米镀膜增强衍射效率和色彩饱和度

### 1.4 两种虹彩机制对比

| 机制 | 原理 | 典型应用 | 公式 |
|------|------|---------|------|
| **衍射光栅虹彩** | 周期性结构导致光波相长/相消干涉 | 闪卡、CD-ROM、小米 9 | `d(sin θᵢ - sin θₘ) = mλ` |
| **薄膜干涉虹彩** | 光在薄膜上下表面反射产生光程差 | 油膜、肥皂泡、珠光车漆 | `2nᵈ·cos θ + φ = mλ` |
| **多层反射虹彩** | 多层薄膜堆叠产生干涉 | 蝴蝶翅膀、蛋白石 | 琼斯矩阵计算 |

闪卡主要使用**衍射光栅虹彩**，但高端产品（如某些宝可梦星光全息卡）可能同时使用薄膜干涉来增强效果。

---

## 2. 结构光核心公式推导

### 2.1 光栅衍射方程（Grating Equation）

#### 基础形式

对于一束波长为 λ 的光以角度 θᵢ 入射到周期为 d 的光栅上，第 m 级衍射角 θₘ 满足：

$$
d(\sin\theta_i - \sin\theta_m) = m\lambda
$$

其中：
- **d** = 光栅周期（相邻沟槽间距），单位 nm，典型值 1000-2000 nm
- **θᵢ** = 入射光与表面法线的夹角
- **θₘ** = 第 m 级衍射光与法线的夹角
- **m** = 衍射级次，整数 (±1, ±2, ±3, ...)
- **λ** = 光波长，可见光范围 380-780 nm

#### 推导（基于光程差）

```
                    入射光 θᵢ
                     ↘
  ──┬──┬──┬──┬──┬──   光栅平面
    d  d  d  d
  ──┴──┴──┴──┴──┴──
              ↗
           衍射光 θₘ
```

相邻两缝发出的光的光程差：

$$
\Delta = d(\sin\theta_i - \sin\theta_m)
$$

相长干涉条件（光程差 = 整数波长）：

$$
\Delta = m\lambda \quad \Rightarrow \quad d(\sin\theta_i - \sin\theta_m) = m\lambda
$$

#### 反解波长

在着色器中，我们已知入射角和观察角，要求"什么波长在这个角度被增强"：

$$
\lambda_m = \frac{d \cdot |\sin\theta_i - \sin\theta_m|}{m}
$$

### 2.2 着色器中的角度计算

在着色器中，使用**切线方向**而非法线来计算角度。设：
- **L** = 光照方向（指向光源）
- **V** = 视线方向（指向观察者）
- **T** = 表面切线方向（沿光栅沟槽的垂直方向）

则：

$$
\cos\theta_L = \mathbf{L} \cdot \mathbf{T}, \quad \cos\theta_V = \mathbf{V} \cdot \mathbf{T}
$$

$$
u = |\cos\theta_L - \cos\theta_V|
$$

$$
\lambda_m = \frac{u \cdot d}{m}
$$

> **注意**：这里用切线而非法线，是因为光栅衍射的方向依赖性沿沟槽方向。不同切线方向 → 不同彩虹取向，这正是闪卡"不同区域不同颜色"的原因。

### 2.3 薄膜干涉方程（补充）

对于薄膜干涉（如油膜、肥皂泡），光程差为：

$$
2 n_{film} d_{film} \cos\theta_r + \frac{\lambda}{2} = m\lambda
$$

其中：
- **n_film** = 薄膜折射率
- **d_film** = 薄膜厚度
- **θ_r** = 薄膜内折射角
- **λ/2** = 半波损失（当光从光疏介质入射到光密介质反射时）

反解出增强波长：

$$
\lambda_m = \frac{2 n_{film} d_{film} \cos\theta_r}{m - \frac{1}{2}}
$$

### 2.4 两种公式的着色器对照

| 参数 | 衍射光栅 | 薄膜干涉 |
|------|---------|---------|
| 周期/厚度 | d（光栅周期，~1600nm） | d_film（膜厚，~300-500nm） |
| 角度依赖 | sin θᵢ - sin θₘ（切线方向） | cos θᵣ（法线方向） |
| 级次 | m = 1,2,3,...8 | m = 1,2,3 |
| 折射率 | 无 | n_film = 1.3-1.5 |
| 额外项 | 无 | λ/2 半波损失 |

---

## 3. 波长到 RGB 的光谱转换

### 3.1 可见光谱

| 波长 (nm) | 颜色 | RGB 近似 |
|-----------|------|----------|
| 380-450 | 紫色 | (0.5, 0.0, 1.0) |
| 450-490 | 蓝色 | (0.0, 0.3, 1.0) |
| 490-560 | 绿色 | (0.0, 1.0, 0.3) |
| 560-590 | 黄色 | (1.0, 1.0, 0.0) |
| 590-620 | 橙色 | (1.0, 0.5, 0.0) |
| 620-780 | 红色 | (1.0, 0.0, 0.0) |

### 3.2 spectral_zucconi6 近似函数

Alan Zucconi 提出的高效波长→RGB 转换函数，用 6 段高斯近似 CIE 色彩匹配函数：

```glsl
// 波长 (nm) → RGB
// 有效范围: 380-780 nm, 范围外返回黑色
vec3 spectral_zucconi6(float w) {
    return clamp(
        vec3(
            bump3y(c1, x1) + bump3y(c2, x2),  // R
            bump3y(c3, x3) + bump3y(c4, x4),  // G
            bump3y(c5, x5) + bump3y(c6, x6)   // B
        ),
        0.0, 1.0
    );
}
```

其中 `bump3y` 是带参数的钟形函数，6 组参数拟合可见光谱的 6 个特征峰。

### 3.3 简化版波长→RGB（适合移动端）

对于移动 GPU（Mali-G31），可使用更简化的分段线性近似：

```glsl
vec3 wavelengthToRGB(float wavelength) {
    vec3 color;
    if (wavelength < 380.0 || wavelength > 780.0) {
        color = vec3(0.0);
    } else if (wavelength < 440.0) {
        color = vec3(0.6, 0.0, 1.0) * (440.0 - wavelength) / 60.0
              + vec3(0.3, 0.0, 1.0) * (wavelength - 380.0) / 60.0;
    } else if (wavelength < 490.0) {
        color = vec3(0.0, (wavelength - 440.0) / 50.0, 1.0);
    } else if (wavelength < 510.0) {
        color = vec3(0.0, 1.0, (510.0 - wavelength) / 20.0);
    } else if (wavelength < 580.0) {
        color = vec3((wavelength - 510.0) / 70.0, 1.0, 0.0);
    } else if (wavelength < 645.0) {
        color = vec3(1.0, (645.0 - wavelength) / 65.0, 0.0);
    } else {
        color = vec3(1.0, 0.0, 0.0);
    }
    // 边缘亮度衰减
    float factor = 1.0;
    if (wavelength < 420.0) factor = 0.3 + 0.7 * (wavelength - 380.0) / 40.0;
    if (wavelength > 700.0) factor = 0.3 + 0.7 * (780.0 - wavelength) / 80.0;
    return color * factor;
}
```

---

## 4. GLSL 闪卡彩虹着色器实现

### 4.1 设计目标

1. **视角依赖虹彩**：转动卡片时，同一位置颜色随视角变化
2. **空间彩虹渐变**：同一角度下，卡片不同区域反射不同颜色
3. **光照交互**：光源方向影响虹彩强度和颜色
4. **可叠加在基础材质上**：与现有 PBR/玻璃渲染共存

### 4.2 完整 GLSL 片段着色器

```glsl
#version 450
#extension GL_ARB_separate_shader_objects : enable

// ============ UBO ============
layout(binding = 0) uniform HoloUbo {
    mat4 uViewProj;
    vec4 uCamPos;
    vec4 uLightDir;       // 指向光源的方向（世界空间）
    vec4 uLightColor;     // 光源颜色
    float uGratingPeriod; // 光栅周期 d (nm)，典型 1600
    float uGratingScale;  // 光栅方向变化的空间频率
    float uIntensity;     // 虹彩强度
    float uSpecPower;     // 高光指数
    float uSpecStrength;  // 高光强度
    float uBaseMix;       // 基础色与虹彩的混合比
} ubo;

// ============ 纹理 ============
layout(binding = 1) uniform sampler2D uBaseTex;       // 基础颜色贴图
layout(binding = 2) uniform sampler2D uNormalTex;     // 法线贴图
layout(binding = 3) uniform sampler2D uGratingDirTex; // 光栅方向贴图（RGB=切线方向xyz）

// ============ 输入/输出 ============
layout(location = 0) in vec3 vWorldPos;
layout(location = 1) in vec3 vWorldNormal;
layout(location = 2) in vec2 vTexCoord;
layout(location = 3) in mat3 vTBN; // 切线空间矩阵

layout(location = 0) out vec4 outColor;

const float PI = 3.14159265359;

// ============ 波长→RGB 转换 ============
vec3 wavelengthToRGB(float w) {
    if (w < 380.0 || w > 780.0) return vec3(0.0);
    
    vec3 c;
    if (w < 440.0) {
        float t = (w - 380.0) / 60.0;
        c = vec3(0.6 * (1.0 - t) + 0.3 * t, 0.0, 1.0);
    } else if (w < 490.0) {
        c = vec3(0.0, (w - 440.0) / 50.0, 1.0);
    } else if (w < 510.0) {
        c = vec3(0.0, 1.0, (510.0 - w) / 20.0);
    } else if (w < 580.0) {
        c = vec3((w - 510.0) / 70.0, 1.0, 0.0);
    } else if (w < 645.0) {
        c = vec3(1.0, (645.0 - w) / 65.0, 0.0);
    } else {
        c = vec3(1.0, 0.0, 0.0);
    }
    
    // 边缘亮度衰减
    float factor = 1.0;
    if (w < 420.0) factor = 0.3 + 0.7 * (w - 380.0) / 40.0;
    else if (w > 700.0) factor = 0.3 + 0.7 * (780.0 - w) / 80.0;
    return c * factor;
}

// ============ 空间光栅方向变化 ============
// 不同位置的光栅切线方向不同 → 产生空间彩虹渐变
vec3 getGratingTangent(vec2 uv, vec3 normal) {
    // 方案1: 从贴图采样
    vec3 texTangent = texture(uGratingDirTex, uv).xyz * 2.0 - 1.0;
    texTangent = normalize(texTangent);
    
    // 方案2: 程序化生成（不依赖贴图）
    // 使用 UV 坐标生成旋转的切线方向
    float angle = uv.x * ubo.uGratingScale * 2.0 * PI;
    vec2 dir = vec2(cos(angle), sin(angle));
    // 构造切线向量（在切平面内）
    vec3 T = normalize(vec3(dir.x, 0.0, dir.y)
                     - normal * dot(vec3(dir.x, 0.0, dir.y), normal));
    // 混合两种方案
    return normalize(mix(T, texTangent, 0.5));
}

// ============ 衍射光栅虹彩计算 ============
vec3 diffractionIridescence(vec3 normal, vec3 tangent, vec3 lightDir, vec3 viewDir) {
    // 光照方向和视线方向与切线的夹角余弦
    float cosThetaL = dot(lightDir, tangent);
    float cosThetaV = dot(viewDir, tangent);
    
    // 光栅方程: λ = d * |sin(θ_L) - sin(θ_V)| / m
    // 这里用 cos 投影近似（实际推导中 sin 可通过 cos 在切线方向等价表达）
    float u = abs(cosThetaL - cosThetaV);
    if (u < 1e-5) return vec3(0.0);
    
    // 叠加多级衍射
    vec3 iridescence = vec3(0.0);
    for (int m = 1; m <= 6; m++) {
        float wavelength = u * ubo.uGratingPeriod / float(m);
        vec3 specColor = wavelengthToRGB(wavelength);
        
        // 高级次衍射强度衰减
        float orderFalloff = 1.0 / float(m);
        iridescence += specColor * orderFalloff;
    }
    
    // 菲涅尔效应：掠射角更明显
    float fresnel = pow(1.0 - max(dot(normal, viewDir), 0.0), 3.0);
    
    return iridescence * (0.5 + 0.5 * fresnel);
}

// ============ 薄膜干涉虹彩（补充效果） ============
vec3 thinFilmIridescence(vec3 normal, vec3 viewDir, float filmThickness) {
    // 薄膜折射率
    float n_film = 1.5;
    float cosTheta = abs(dot(normal, viewDir));
    float cosThetaR = sqrt(1.0 - (1.0 - cosTheta * cosTheta) / (n_film * n_film));
    
    vec3 iridescence = vec3(0.0);
    for (int m = 1; m <= 3; m++) {
        float wavelength = 2.0 * n_film * filmThickness * cosThetaR / (float(m) - 0.5);
        iridescence += wavelengthToRGB(wavelength) / float(m);
    }
    return iridescence;
}

// ============ 主函数 ============
void main() {
    vec3 N = normalize(vWorldNormal);
    
    // 从法线贴图读取微法线
    vec3 normalMap = texture(uNormalTex, vTexCoord).xyz * 2.0 - 1.0;
    vec3 microNormal = normalize(vTBN * normalMap);
    N = normalize(mix(N, microNormal, 0.3));
    
    vec3 V = normalize(ubo.uCamPos.xyz - vWorldPos);
    vec3 L = normalize(-ubo.uLightDir.xyz);
    vec3 H = normalize(L + V);
    
    // 基础颜色
    vec3 baseColor = texture(uBaseTex, vTexCoord).rgb;
    
    // 获取光栅切线方向（空间变化）
    vec3 T = getGratingTangent(vTexCoord, N);
    
    // 衍射光栅虹彩
    vec3 holoColor = diffractionIridescence(N, T, L, V);
    
    // 薄膜干涉虹彩（可选，叠加增强）
    // 使用 UV 坐标驱动薄膜厚度变化 → 空间彩虹渐变
    float filmThickness = 300.0 + 200.0 * sin(vTexCoord.x * 3.14159);
    vec3 thinFilmColor = thinFilmIridescence(N, V, filmThickness) * 0.3;
    
    // 漫反射 + 高光（Blinn-Phong）
    float NdotL = max(dot(N, L), 0.0);
    float NdotH = max(dot(N, H), 0.0);
    float spec = pow(NdotH, ubo.uSpecPower) * ubo.uSpecStrength;
    
    vec3 lighting = baseColor * (NdotL * 0.8 + 0.2) + spec * ubo.uLightColor.rgb;
    
    // 混合基础光照与虹彩
    vec3 holoTotal = (holoColor + thinFilmColor) * ubo.uIntensity;
    vec3 finalColor = mix(lighting, holoTotal, ubo.uBaseMix);
    
    // 菲涅尔增强：掠射角更虹彩
    float fresnel = pow(1.0 - max(dot(N, V), 0.0), 5.0);
    finalColor += holoTotal * fresnel * 0.5;
    
    outColor = vec4(clamp(finalColor, 0.0, 1.0), 1.0);
}
```

### 4.3 顶点着色器

```glsl
#version 450
#extension GL_ARB_separate_shader_objects : enable

layout(location = 0) in vec3 inPosition;
layout(location = 1) in vec3 inNormal;
layout(location = 2) in vec2 inTexCoord;
layout(location = 3) in vec4 inTangent;

layout(binding = 0) uniform HoloUbo {
    mat4 uViewProj;
    vec4 uCamPos;
    vec4 uLightDir;
    vec4 uLightColor;
    float uGratingPeriod;
    float uGratingScale;
    float uIntensity;
    float uSpecPower;
    float uSpecStrength;
    float uBaseMix;
} ubo;

layout(location = 0) out vec3 vWorldPos;
layout(location = 1) out vec3 vWorldNormal;
layout(location = 2) out vec2 vTexCoord;
layout(location = 3) out mat3 vTBN;

void main() {
    vWorldPos = inPosition;
    vWorldNormal = normalize(inNormal);
    vTexCoord = inTexCoord;
    
    // 构造 TBN 矩阵
    vec3 T = normalize(inTangent.xyz);
    vec3 N = normalize(inNormal);
    vec3 B = normalize(cross(N, T) * inTangent.w);
    vTBN = mat3(T, B, N);
    
    gl_Position = ubo.uViewProj * vec4(inPosition, 1.0);
}
```

### 4.4 关键设计解析

#### 设计 1：空间彩虹渐变

**问题**：同一角度下，卡片不同区域应反射不同颜色。

**方案**：让光栅切线方向 `T` 在卡片表面**空间变化**：

```glsl
float angle = uv.x * uGratingScale * 2.0 * PI;
vec2 dir = vec2(cos(angle), sin(angle));
```

- `uGratingScale` 控制变化频率（大→细密条纹，小→大块色块）
- UV 坐标驱动方向旋转 → 不同位置切线方向不同 → 衍射波长不同 → 彩虹渐变

**效果对比**：

| uGratingScale | 效果 |
|---------------|------|
| 1.0 | 1-2 个大色带 |
| 5.0 | 中等密度彩虹条纹 |
| 20.0 | 细密彩虹光纹 |

#### 设计 2：视角依赖虹彩

**问题**：转动卡片时颜色变化。

**方案**：衍射方程中 `u = |cos θ_L - cos θ_V|` 依赖视角，当 V 变化时 u 变化 → 波长变化 → 颜色变化。

```
视角正对 → cos θ_V ≈ 0 → u 小 → 波长短 → 偏蓝/紫
视角倾斜 → cos θ_V 大 → u 大 → 波长长 → 偏红
```

#### 设计 3：多级衍射叠加

```glsl
for (int m = 1; m <= 6; m++) {
    float wavelength = u * d / float(m);
    iridescence += wavelengthToRGB(wavelength) / float(m);
}
```

光栅衍射存在多级次（m=1,2,3...），每级产生不同波长的颜色。叠加多级可模拟更真实的彩虹效果。高级次强度衰减。

#### 设计 4：菲涅尔增强

```glsl
float fresnel = pow(1.0 - max(dot(N, V), 0.0), 5.0);
finalColor += holoTotal * fresnel * 0.5;
```

掠射角（侧看）时虹彩更明显——这与真实闪卡的行为一致。

### 4.5 纯程序化版（无贴图依赖）

如果不需要基础颜色贴图和法线贴图，可以简化为纯程序化版本：

```glsl
#version 450
#extension GL_ARB_separate_shader_objects : enable

layout(binding = 0) uniform HoloUbo {
    mat4 uViewProj;
    vec4 uCamPos;
    vec4 uLightDir;
    float uGratingPeriod;  // 1600.0
    float uGratingScale;   // 5.0
    float uIntensity;      // 1.0
} ubo;

layout(location = 0) in vec3 vWorldPos;
layout(location = 1) in vec3 vWorldNormal;
layout(location = 2) in vec2 vTexCoord;

layout(location = 0) out vec4 outColor;

vec3 wavelengthToRGB(float w) {
    if (w < 380.0 || w > 780.0) return vec3(0.0);
    vec3 c;
    if (w < 440.0)      c = vec3((440.0 - w) / 60.0 * 0.3 + 0.3, 0.0, 1.0);
    else if (w < 490.0) c = vec3(0.0, (w - 440.0) / 50.0, 1.0);
    else if (w < 510.0) c = vec3(0.0, 1.0, (510.0 - w) / 20.0);
    else if (w < 580.0) c = vec3((w - 510.0) / 70.0, 1.0, 0.0);
    else if (w < 645.0) c = vec3(1.0, (645.0 - w) / 65.0, 0.0);
    else                c = vec3(1.0, 0.0, 0.0);
    float f = 1.0;
    if (w < 420.0)      f = 0.3 + 0.7 * (w - 380.0) / 40.0;
    else if (w > 700.0) f = 0.3 + 0.7 * (780.0 - w) / 80.0;
    return c * f;
}

void main() {
    vec3 N = normalize(vWorldNormal);
    vec3 V = normalize(ubo.uCamPos.xyz - vWorldPos);
    vec3 L = normalize(-ubo.uLightDir.xyz);
    
    // 空间变化的光栅切线方向
    float angle = vTexCoord.x * ubo.uGratingScale * 6.28318;
    vec3 T = normalize(vec3(cos(angle), 0.0, sin(angle))
                     - N * dot(vec3(cos(angle), 0.0, sin(angle)), N));
    
    // 衍射虹彩
    float u = abs(dot(L, T) - dot(V, T));
    vec3 holo = vec3(0.0);
    for (int m = 1; m <= 6; m++) {
        float w = u * ubo.uGratingPeriod / float(m);
        holo += wavelengthToRGB(w) / float(m);
    }
    
    // 菲涅尔
    float fresnel = pow(1.0 - max(dot(N, V), 0.0), 5.0);
    
    // 漫反射底色
    float diff = max(dot(N, L), 0.0) * 0.3 + 0.1;
    vec3 base = vec3(0.05, 0.05, 0.08); // 深色底
    
    vec3 finalColor = base * diff + holo * ubo.uIntensity * (0.5 + 0.5 * fresnel);
    
    outColor = vec4(clamp(finalColor, 0.0, 1.0), 1.0);
}
```

---

## 5. 效果调参指南

### 5.1 参数效果对照

| 参数 | 范围 | 效果 |
|------|------|------|
| `uGratingPeriod` (d) | 800-3000 nm | 小→偏蓝紫；大→偏红橙 |
| `uGratingScale` | 1-50 | 控制空间彩虹条纹密度 |
| `uIntensity` | 0-3 | 虹彩亮度 |
| `uBaseMix` | 0-1 | 0=全虹彩，1=全基础色 |
| `uSpecPower` | 8-128 | 高光锐度 |
| `uSpecStrength` | 0-2 | 高光亮度 |

### 5.2 典型预设

#### 预设 A：宝可梦宇宙全息卡

```glsl
uGratingPeriod = 1600.0;  // 标准光栅周期
uGratingScale   = 8.0;     // 中等密度
uIntensity      = 1.2;
uBaseMix        = 0.3;     // 虹彩为主
uSpecPower      = 64.0;
uSpecStrength   = 1.5;
```

#### 预设 B：小米 9 全息幻彩

```glsl
uGratingPeriod = 1200.0;  // 纳米光栅，较小周期
uGratingScale   = 15.0;    // 较密变化
uIntensity      = 0.8;     // 较柔和
uBaseMix        = 0.5;     // 基础色与虹彩均衡
uSpecPower      = 32.0;
uSpecStrength   = 0.8;
```

#### 预设 C：信用卡全息防伪标

```glsl
uGratingPeriod = 2000.0;  // 较大周期→偏红
uGratingScale   = 3.0;    // 大块色带
uIntensity      = 2.0;    // 高对比
uBaseMix        = 0.1;    // 几乎全虹彩
uSpecPower      = 128.0;
uSpecStrength   = 1.0;
```

### 5.3 Mali-G31 优化建议

1. **循环展开**：将衍射级次循环从 6 改为 3（`m=1,2,3`），减少 ALU 开销
2. **mediump 精度**：波长转换和衍射计算用 `mediump` 足够
3. **预计算波长→RGB 查找表**：用 1D 纹理（256x1）替代运行时计算
4. **减少空间变化频率**：`uGratingScale` 不宜过大，避免高频细节被 GPU 过滤
5. **合并薄膜干涉**：如果不需同时使用两种机制，只用衍射光栅

---

## 参考来源

| 来源 | URL |
|------|-----|
| Alan Zucconi CD-ROM Shader | https://www.alanzucconi.com/2017/07/15/cd-rom-shader-1/ |
| Alan Zucconi Car Paint / Thin Film | https://www.alanzucconi.com/2017/10/27/carpaint-shader-thin-film-interference |
| 维基百科：衍射光栅 | https://en.wikipedia.org/wiki/Diffraction_grating |
| 小米 9 全息幻彩工艺 | https://www.sohu.com/a/299234526_163726 |
| 光栅卡成像原理 | https://www.tinghu.gov.cn/art/2024/8/5/art_31891_4220428.html |
| 宝可梦闪卡工艺 | https://www.pokemon.cn/tcg/product/16377.html |
| Thorlabs 衍射光栅教程 | https://www.thorlabs.com/zh/diffraction-gratings-tutorial |
| 全息巧克力（衍射光栅制造） | https://henryquach.org/grating.html |
| GLSL Iridescent Shader | https://medium.com/phishchiang/glsl-study-simple-iridescent-shader-156f8d1a9e5d |
| WPI 衍射着色论文 | http://www.cs.wpi.edu/~emmanuel/courses/cs563/agu_diffraction.pdf |
