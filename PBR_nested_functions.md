# PBR 光照 · 嵌套函数式完全讲解

> 本文以**最终输出的 RGB** 为根，把渲染方程逐层拆解成**嵌套函数调用**——每个函数对应一条数学公式，函数体就是它的 GLSL 实现。读完这一棵"调用树"，你就掌握了实时 PBR 的全部主干。

---

## 0. 总览：一条渲染方程 = 一棵函数调用树

实时渲染的终极目标是求解**渲染方程**：

$$
L_o(p,\omega_o) \;=\; L_e(p,\omega_o) \;+\; \int_{\Omega} f_r(p,\omega_i,\omega_o)\, L_i(p,\omega_i)\, (n\cdot\omega_i)\; d\omega_i
$$

- $L_o$：出射辐射率（我们最终要算的东西，经显示变换后成为屏幕 RGB）；
- $L_e$：自发光；
- $f_r$：BRDF（双向反射分布函数），微表面理论的主战场；
- $L_i$：从 $\omega_i$ 方向入射的辐射率；
- $(n\cdot\omega_i)$：Lambert 余弦项；
- $\int_\Omega$：上半球积分——**实时无法解析求解**，工程上拆成"直接光求和 + 环境光预计算"。

这个积分天然对应一棵**函数调用树**。下面是完整调用栈（`→` 表示"调用"）：

```text
FinalRGB(Lo, ambient, emission)                          ← 根节点：最终输出 RGB
│    color = Lo + ambient + emission      (渲染方程组装)
│    color = ToneMap(color)               (HDR→LDR)
│    return GammaCorrect(color)           (线性→sRGB)
│
├─► GammaCorrect(c)                       =  c^(1/2.2)
├─► ToneMap(c)                            =  c/(c+1)   或  ACES(x)
│
└─► ShadePixel(mat, N, V, worldPos)                       ← 渲染方程 L_o
     │    Lo      = DirectLighting(mat, N, V, worldPos)   (B1 直接光)
     │    ambient = IBL(mat, N, V)                        (B2 间接光)
     │    return FinalRGB(Lo, ambient, mat.emission)      (B0 自发光)
     │
     ├─► DirectLighting(...)                              ← 对 N 盏灯 Σ 求和
     │    │   for each light i:
     │    │     radiance = IncidentRadiance(...)
     │    │     Lo += EvaluateBRDF(...) * radiance * NdotL
     │    │
     │    ├─► IncidentRadiance(lightCol, lightPos, pos)   ← 平方反比衰减 1/d²
     │    │
     │    └─► EvaluateBRDF(mat, N, V, L, F0)              ← f_r = kD·f_diff + kS·f_spec
     │         │    F  = F_Schlick(H·V, F0)
     │         │    kS = F
     │         │    kD = (1 − F)·(1 − metallic)          (能量守恒)
     │         │
     │         ├─► DiffuseBRDF(albedo)                    =  albedo / π
     │         │
     │         └─► CookTorrance(N, V, L, H, rough, F0)    =  D·F·G / (4·NdotV·NdotL)
     │              ├─► D_GGX(N, H, rough)                (法线分布)
     │              ├─► G_Smith(N, V, L, rough)           (几何遮蔽)
     │              │     └─► G1_SchlickGGX(NdotV, k)
     │              └─► F_Schlick(H·V, F0)                (菲涅尔)
     │
     └─► IBL(mat, N, V)                                    ← 基于图像的间接光
          │    F  = F_SchlickRoughness(NdotV, F0, rough)
          │    kS = F;  kD = (1 − F)(1 − metallic)
          │    return (kD·IBL_Diffuse + IBL_Specular) · AO
          │
          ├─► IBL_Diffuse(N, albedo)                      =  Irradiance(n)·albedo
          ├─► IBL_Specular(N, V, rough, F)                =  Prefilter × (F0·A + B)   (Split-Sum)
          │     ├─► textureLod(prefilterMap, R, rough·MAX_LOD)
          │     └─► texture(brdfLUT, (NdotV, rough)) → (A, B)
          └─► F_SchlickRoughness(NdotV, F0, rough)

叶子（所有函数的输入）:
  GetMaterial(uv) → albedo / metallic / roughness / ao / emission
  ComputeF0(albedo, metallic) → F0 = lerp(0.04, albedo, metallic)
  几何向量: N(法线) · V(视线) · L(光向) · H = normalize(V+L)(半程向量)

```

**阅读方法**：下面每一节 = 一个函数。每节给出 ①它实现的数学公式 ②GLSL 代码 ③物理含义与工程细节。顺序是**自顶向下**（从根到叶子），符合"调用"的直觉；文末提供一份**自底向上、可直接编译**的完整 shader。

---

## 1. 根函数 `FinalRGB`：一切的出口

**职责**：把渲染方程算出的三个部分（直接光、间接光、自发光）组装起来，再做显示变换，吐出屏幕像素。

$$
\text{RGB} = \text{GammaCorrect}\Big(\text{ToneMap}\big(L_o^{direct} + L^{IBL} + L_e\big)\Big)
$$

```glsl
vec3 FinalRGB(vec3 Lo, vec3 ambient, vec3 emission)
{
    vec3 color = Lo + ambient + emission;   // 渲染方程组装：直接光 + 间接光 + 自发光
    color = ToneMap(color);                 // 第 1 层：HDR 压缩到 [0,1]
    color = GammaCorrect(color);            // 第 1 层：线性空间 → sRGB
    return color;                           // ★ 根节点：最终输出
}

```

**注意顺序**：先色调映射、后伽马校正。色调映射必须在线性空间做（它是物理量压缩），伽马校正永远是最后一步（它是显示编码）。

---

## 2. 第 1 层：`GammaCorrect` 伽马校正

**公式**：

$$
c_{sRGB} = c_{linear}^{\,1/2.2}
$$

**为什么需要**：光照计算全程在**线性空间**进行（物理上光强可线性叠加），但显示器以伽马曲线响应、且人眼对暗部更敏感。若不编码回 sRGB，画面会整体偏暗、对比失真。

```glsl
vec3 GammaCorrect(vec3 linearColor)
{
    return pow(linearColor, vec3(1.0 / 2.2));
}

```

> 工程提示：输入的 albedo 贴图是 sRGB 编码的，采样后必须 `pow(2.2)` **解码回线性**才能参与计算（见第 15 节）；而 metallic/roughness/AO/法线是线性数据，不解码。

---

## 3. 第 1 层：`ToneMap` 色调映射

**公式**（Reinhard；ACES 为引擎常用替代）：

$$
\text{Reinhard}: \quad c_{LDR} = \frac{c_{HDR}}{c_{HDR}+1}
\qquad
\text{ACES}: \quad \text{clamp}\!\left(\frac{x(2.51x+0.03)}{x(2.43x+0.59)+0.14},\ 0,\ 1\right)
$$

**为什么需要**：渲染方程的结果是无上限的 HDR 辐射率（太阳可以远大于 1），显示器只能表达 [0,1]。色调映射把高动态范围压缩进可显示区间，同时尽量保留高光层次。

```glsl
vec3 ToneMap(vec3 hdr)
{
    // Reinhard：简单，但高光易发灰
    return hdr / (hdr + vec3(1.0));
}

// 备选：ACES 拟合曲线（对比与高光过渡更好，UE/Unity 常用）
vec3 ACESFilm(vec3 x)
{
    return clamp((x * (2.51*x + 0.03)) / (x * (2.43*x + 0.59) + 0.14),
                 0.0, 1.0);
}

```

---

## 4. 第 2 层：`ShadePixel` —— 渲染方程本体

**职责**：把渲染方程的三项分别求值。积分 $\int_\Omega$ 在这里被拆成两个可计算的近似：

$$
L_o \;\approx\; \underbrace{\text{DirectLighting}}_{\text{解析光源，有限求和}} \;+\; \underbrace{\text{IBL}}_{\text{环境贴图，预计算}} \;+\; \underbrace{L_e}_{\text{自发光}}
$$

```glsl
vec3 ShadePixel(Material mat, vec3 N, vec3 V, vec3 worldPos)
{
    vec3 Lo      = DirectLighting(mat, N, V, worldPos);  // B1：直接光（Σ 求和）
    vec3 ambient = IBL(mat, N, V);                       // B2：间接光（环境）
    return FinalRGB(Lo, ambient, mat.emission);          // B0：自发光 + 显示变换
}

```

---

## 5. 第 3 层：`DirectLighting` —— 积分退化为有限求和

对每一盏解析光源（点光/平行光/聚光），半球积分退化为**单项**，遍历所有灯累加：

$$
L_o^{direct}(\omega_o) = \sum_{k=1}^{N} \big[\, f_r(\omega_k, \omega_o)\, \big] \cdot L_k \cdot (n\cdot\omega_k)
$$

其中 $f_r$ 就是 `EvaluateBRDF`，$L_k$ 是 `IncidentRadiance`，$(n\cdot\omega_k)$ 是余弦项。

```glsl
vec3 DirectLighting(Material mat, vec3 N, vec3 V, vec3 worldPos)
{
    vec3 F0 = ComputeF0(mat.albedo, mat.metallic);   // 叶子：垂直入射反射率
    vec3 Lo = vec3(0.0);

    for (int i = 0; i < NUM_LIGHTS; ++i)
    {
        vec3  L        = normalize(lightPositions[i] - worldPos); // 光方向
        vec3  radiance = IncidentRadiance(lightColors[i], lightPositions[i], worldPos);
        float NdotL    = max(dot(N, L), 0.0);                     // Lambert 余弦项

        // 渲染方程的离散项：f_r · Li · (n·l)
        Lo += EvaluateBRDF(mat, N, V, L, F0) * radiance * NdotL;
    }
    return Lo;
}

```

### 5.1 子函数 `IncidentRadiance`：平方反比衰减

点光源能量随距离平方扩散：

$$
L_k = \text{lightColor} \cdot \frac{1}{d^2}
$$

```glsl
vec3 IncidentRadiance(vec3 lightColor, vec3 lightPos, vec3 worldPos)
{
    float d           = length(lightPos - worldPos);
    float attenuation = 1.0 / (d * d);          // 平方反比物理衰减
    return lightColor * attenuation;
    // 平行光：无衰减，直接返回 lightColor
    // 聚光灯：再乘 smoothstep(外锥角, 内锥角, 夹角)
}

```

---

## 6. 第 4 层：`EvaluateBRDF` —— 能量守恒的分界点

**公式**：

$$
f_r = k_d\, f_{diffuse} + k_s\, f_{specular}, \qquad
k_s = F,\quad k_d = (1-F)(1-\text{metallic})
$$

**物理意义**（这是整个微表面理论的分水岭）：

- 光打到表面，比例 $F$（菲涅尔）**当场被反射** → 镜面分支；
- 剩余 $1-F$ **折射进入材质内部**，多次散射后再射出 → 漫反射分支；
- **金属没有次表面散射**（自由电子直接吸收进入的光），所以漫反射还要乘 $(1-\text{metallic})$——纯金属漫反射为 0。

```glsl
vec3 EvaluateBRDF(Material mat, vec3 N, vec3 V, vec3 L, vec3 F0)
{
    vec3 H = normalize(V + L);                       // 半程向量（微表面有效法线）

    vec3 F  = F_Schlick(max(dot(H, V), 0.0), F0);    // 当场反射的比例
    vec3 kS = F;                                     // 镜面权重
    vec3 kD = (vec3(1.0) - kS) * (1.0 - mat.metallic); // 漫反射权重（能量守恒）

    // 两大分支加权求和
    return kD * DiffuseBRDF(mat.albedo)
         + kS * CookTorrance(N, V, L, H, mat.roughness, F0);
}

```

---

## 7. 第 5 层（分支 A）：`DiffuseBRDF` —— Lambert 漫反射

**公式**：

$$
f_{diffuse} = \frac{\text{albedo}}{\pi}
$$

**为什么除 π**：漫反射光在材质内部多次散射后近似**各向同性**射出。除 $\pi$ 是为了让半球积分归一、保证能量守恒：

$$
\int_{\Omega} \frac{1}{\pi}\cos\theta\; d\omega = 1
$$

```glsl
vec3 DiffuseBRDF(vec3 albedo)
{
    return albedo / PI;
    // UE4 实践：实时渲染用 Lambert 已足够；
    // Oren-Nayar 更精确地建模粗糙漫反射，但开销大，移动端极少使用
}

```

---

## 8. 第 5 层（分支 B）：`CookTorrance` —— 镜面反射（PBR 的心脏）

**公式**：

$$
f_{specular} = \frac{D(\mathbf{h})\; F(\omega_o)\; G(\omega_i,\omega_o)}{4\,(n\cdot\omega_o)\,(n\cdot\omega_i)}
$$

**微表面理论三大假设**：

1. 表面由无数**小于像素、大于光波长**的微小镜面组成，可用统计描述；
2. **只有法线恰好等于半程向量 $\mathbf{h}$ 的微表面**才能把光从 $\mathbf{l}$ 反射进眼睛 $\mathbf{v}$；
3. `roughness` 控制微表面法线分散程度：集中→高光锐利（镜子），分散→高光弥散（磨砂）。

三项分工：$D$ = 有多少微表面参与，$G$ = 其中多少没被同伴挡住，$F$ = 每块反射多少光；分母 $4(n\cdot v)(n\cdot l)$ 是把"微表面投影面积上的能量"换算成"宏观单位面积 BRDF"的几何因子。

```glsl
vec3 CookTorrance(vec3 N, vec3 V, vec3 L, vec3 H, float roughness, vec3 F0)
{
    float D = D_GGX(N, H, roughness);                        // 法线分布
    float G = G_Smith(N, V, L, roughness);                   // 几何遮蔽
    vec3  F = F_Schlick(max(dot(H, V), 0.0), F0);            // 菲涅尔

    float NdotV = max(dot(N, V), 0.0);
    float NdotL = max(dot(N, L), 0.0);
    float denominator = 4.0 * NdotV * NdotL + 0.0001;        // +ε 防除零

    return (D * F * G) / denominator;
}

```

> 工程优化：外层渲染方程还有一个 $(n\cdot l)$ 余弦项，与分母的 $(n\cdot l)$ **数学上可约分**，得 $\frac{D\,G\,F}{4(n\cdot v)}$——许多引擎这么做，顺便避免除以接近 0 的 NdotL。

下面三个函数就是 $D$、$G$、$F$ 的实现。

---

## 9. 第 6 层：`D_GGX` —— 法线分布函数

**公式**（GGX / Trowbridge-Reitz）：

$$
D(\mathbf{h}) = \frac{\alpha^2}{\pi\big((n\cdot h)^2(\alpha^2-1)+1\big)^2}, \qquad \alpha = \text{roughness}^2
$$

**含义**：微表面法线与半程向量 $h$ 对齐的**概率密度**。$\alpha = \text{roughness}^2$ 是 Disney 的**感知重映射**——让美术拉 0→1 滑条时视觉变化更线性。GGX 相比 Beckmann 有**更长的拖尾**，能表现金属高光边缘的亮边，是 UE4/Unity 的事实标准。

```glsl
float D_GGX(vec3 N, vec3 H, float roughness)
{
    float a      = roughness * roughness;   // α = roughness²（感知重映射）
    float a2     = a * a;                   // α²
    float NdotH  = max(dot(N, H), 0.0);
    float NdotH2 = NdotH * NdotH;

    float nom   = a2;
    float denom = NdotH2 * (a2 - 1.0) + 1.0;
    denom = PI * denom * denom;

    return nom / denom;
}

```

---

## 10. 第 6 层：`G_Smith` —— 几何遮蔽函数

**公式**：

$$
G(\omega_i,\omega_o) = G_1(\omega_o)\,G_1(\omega_i), \qquad
G_1(x) = \frac{n\cdot x}{(n\cdot x)(1-k)+k}
$$

**含义**：粗糙表面上微表面会互相遮挡——

- **Masking**：反射光出射路上被同伴挡住（视线方向）；
- **Shadowing**：入射光到达前就被前方微表面挡住（光线方向）。

$G$ 就是"双向都存活"的概率。$k$ 的取值：直接光照 $k=\frac{(\text{roughness}+1)^2}{8}$；IBL 用 $k=\frac{\text{roughness}^2}{2}$（Karis 约定）。

```glsl
float G1_SchlickGGX(float NdotV, float k)
{
    return NdotV / (NdotV * (1.0 - k) + k);
}

float G_Smith(vec3 N, vec3 V, vec3 L, float roughness)
{
    float k = (roughness + 1.0);  k = (k * k) / 8.0;   // 直接光照的 k
    float NdotV = max(dot(N, V), 0.0);
    float NdotL = max(dot(N, L), 0.0);

    return G1_SchlickGGX(NdotV, k)      // Masking：视线方向
         * G1_SchlickGGX(NdotL, k);     // Shadowing：光线方向
}

```

> 移动端优化（UE4/高通推荐）：把 $G$ 与分母合并成**可见性项 $V$**，只做一次除法：
>
> $$V = \frac{0.5}{(n\cdot l)\sqrt{(n\cdot v)^2(1-\alpha^2)+\alpha^2} + (n\cdot v)\sqrt{(n\cdot l)^2(1-\alpha^2)+\alpha^2}}$$

---

## 11. 第 6 层：`F_Schlick` —— 菲涅尔方程

**公式**（Schlick 近似）：

$$
F(\omega_o) = F_0 + (1-F_0)\,(1 - h\cdot\omega_o)^5
$$

**含义**：光在界面上"反射 vs 折射"的比例随入射角变化——**垂直入射最低（$F_0$），掠射角趋向 100%**。这就是为什么斜看水面/桌面会像镜子。完整菲涅尔含指数运算，实时渲染用此近似。

```glsl
vec3 F_Schlick(float cosTheta, vec3 F0)
{
    // cosTheta = dot(H, V)：入射光相对微表面法线的角度
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

```

### 11.1 叶子：`ComputeF0` —— 垂直入射反射率

$$
F_0 = \text{lerp}(0.04,\ \text{albedo},\ \text{metallic})
$$

电介质（水/塑料/木头）$F_0$ 约 0.04（来自 IOR≈1.5：$\big(\frac{1-1.5}{1+1.5}\big)^2$）；金属的 $F_0$ 带颜色（金=黄、铜=橙），直接用 albedo。

```glsl
vec3 ComputeF0(vec3 albedo, float metallic)
{
    return mix(vec3(0.04), albedo, metallic);
}

```

| 材质 | $F_0$ | 材质 | $F_0$ |
|---|---|---|---|
| 水 | 0.02 | 铁 | (0.56, 0.57, 0.58) |
| 塑料 | 0.04 | 铜 | (0.95, 0.64, 0.54) |
| 钻石 | 0.17 | 金 | (1.00, 0.71, 0.29) |
| 玻璃 | 0.05 | 铝 | (0.91, 0.92, 0.92) |

---

## 12. 第 3 层：`IBL` —— 间接光照（基于图像的环境光）

解析光源只有几盏，真实环境中"四面八方"的光（天空、墙壁、物体）必须用**HDR 环境贴图 + 离线预计算**近似。同样拆漫反射 + 镜面两支，再乘 AO：

$$
L^{IBL} = \big(k_d \cdot L_{diff}^{IBL} + L_{spec}^{IBL}\big) \cdot AO
$$

```glsl
vec3 IBL(Material mat, vec3 N, vec3 V)
{
    vec3  F0    = ComputeF0(mat.albedo, mat.metallic);
    float NdotV = max(dot(N, V), 0.0);

    // 注意：这里用"粗糙表面变体"的菲涅尔
    vec3 F  = F_SchlickRoughness(NdotV, F0, mat.roughness);
    vec3 kS = F;
    vec3 kD = (vec3(1.0) - kS) * (1.0 - mat.metallic);

    vec3 diffuse  = IBL_Diffuse(N, mat.albedo);
    vec3 specular = IBL_Specular(N, V, mat.roughness, F);

    return (kD * diffuse + specular) * mat.ao;
}

```

---

## 13. `IBL_Diffuse` —— 辐照度漫反射

漫反射的 BRDF 是常数 $c/\pi$，可提出积分，只需预计算**辐照度** $E(n)$：

$$
E(\mathbf{n}) = \int_{\Omega} L_i(\omega_i)\,(n\cdot\omega_i)\,d\omega_i
\quad\xrightarrow{\text{离线余弦加权卷积}}\quad \text{IrradianceMap}(\mathbf{n})
$$

$$
L_{diff}^{IBL} = E(\mathbf{n})\cdot\text{albedo}
$$

```glsl
vec3 IBL_Diffuse(vec3 N, vec3 albedo)
{
    vec3 irradiance = texture(irradianceMap, N).rgb;  // 低频信号，32×32 即可
    return irradiance * albedo;                       // albedo/π 已计入离线卷积
}

```

---

## 14. `IBL_Specular` —— Split-Sum 拆分求和（Karis 2013）

镜面反射积分 $\int L_i\,f_{spec}\cos\theta\,d\omega$ **同时依赖环境和 BRDF**，维度太高无法穷举预计算。Epic 的方案是拆成两个可独立预计算的部分相乘：

$$
L_{spec}^{IBL} \approx
\underbrace{\int_{\Omega} L_i\,D\,d\omega}_{\text{① 预过滤环境图（按粗糙度分 mip）}}
\times
\underbrace{\int_{\Omega} f_r\cos\theta\,d\omega}_{\text{② BRDF 积分 LUT}}
= L_{prefiltered}(\mathbf{R},\text{roughness})\cdot(F_0 A + B)
$$

```glsl
vec3 IBL_Specular(vec3 N, vec3 V, float roughness, vec3 F)
{
    vec3 R = reflect(-V, N);                          // 镜面反射方向

    // ① 按粗糙度采样对应 mip（粗糙度越高越模糊）
    vec3 prefiltered = textureLod(prefilterMap, R, roughness * MAX_LOD).rgb;

    // ② 查 BRDF 积分表，输出 (A, B)
    float NdotV = max(dot(N, V), 0.0);
    vec2 brdf = texture(brdfLUT, vec2(NdotV, roughness)).rg;

    return prefiltered * (F * brdf.x + brdf.y);       // F0·A + B
}

```

### 14.1 `F_SchlickRoughness` —— 粗糙表面的菲涅尔变体

粗糙表面会**削弱掠射角处的菲涅尔增强**，所以 IBL 里用这个变体：

$$
F = F_0 + \big(\max(1-\text{roughness},\,F_0) - F_0\big)\,(1-n\cdot v)^5
$$

```glsl
vec3 F_SchlickRoughness(float cosTheta, vec3 F0, float roughness)
{
    return F0 + (max(vec3(1.0 - roughness), F0) - F0)
              * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

```

---

## 15. 叶子：材质参数与几何向量

所有函数的输入，来自贴图采样与几何计算：

```glsl
struct Material { vec3 albedo; float metallic; float roughness;
                  float ao; vec3 emission; };

Material GetMaterial(vec2 uv)
{
    Material m;
    m.albedo    = pow(texture(albedoMap, uv).rgb, vec3(2.2)); // sRGB→线性 解码！
    m.metallic  = texture(metallicMap, uv).r;                 // 线性贴图，不解码
    m.roughness = texture(roughnessMap, uv).r;
    m.ao        = texture(aoMap, uv).r;
    m.emission  = texture(emissionMap, uv).rgb;
    return m;
}

// 几何向量
vec3 V = normalize(camPos - worldPos);    // 视线方向
vec3 L = normalize(lightPos - worldPos);  // 光源方向
vec3 H = normalize(V + L);                // 半程向量（微表面有效法线）
vec3 N = GetNormalFromNormalMap();        // 法线（可被法线贴图扰动）

```

---

## 16. 函数 ↔ 公式 ↔ 物理意义 速查表

| 函数 | 数学公式 | 物理意义 |
|---|---|---|
| `FinalRGB` | `Gamma(ToneMap(Lo+ambient+emission))` | 渲染方程组装 + 显示变换 |
| `ToneMap` | $c/(c+1)$ 或 ACES | HDR→LDR，保留高光 |
| `GammaCorrect` | $c^{1/2.2}$ | 线性→sRGB，适配显示器 |
| `DirectLighting` | $\sum f_r L_k (n\cdot l_k)$ | 积分→离散求和 |
| `IncidentRadiance` | $\text{color}/d^2$ | 平方反比物理衰减 |
| `EvaluateBRDF` | $k_d f_{diff}+k_s f_{spec}$ | 能量守恒拆分 |
| `DiffuseBRDF` | $\text{albedo}/\pi$ | 内部多次散射，各向同性 |
| `CookTorrance` | $D F G / 4(n\cdot v)(n\cdot l)$ | 微表面镜面反射 |
| `D_GGX` | $\alpha^2/(\pi((n\cdot h)^2(\alpha^2-1)+1)^2)$ | 有多少微表面对准你 |
| `G_Smith` | $G_1(v)G_1(l)$ | 多少没被同伴挡住 |
| `F_Schlick` | $F_0+(1-F_0)(1-h\cdot v)^5$ | 每块微表面反射多少 |
| `ComputeF0` | $\text{lerp}(0.04,\text{albedo},\text{metallic})$ | 垂直入射反射率 |
| `IBL_Diffuse` | $\text{Irradiance}(n)\cdot\text{albedo}$ | 环境漫反射 |
| `IBL_Specular` | $\text{Prefilter}\cdot(F_0 A+B)$ | Split-Sum 环境镜面 |
| `F_SchlickRoughness` | $F_0+(\max(1-r,F_0)-F_0)(1-n\cdot v)^5$ | 粗糙表面菲涅尔 |

---

## 17. 完整 Shader 组装（自底向上，可直接编译）

把前面所有函数按**被调用者先定义**的顺序拼起来，就是完整片元着色器：

```glsl
#version 330 core
out vec4 FragColor;
in vec2 TexCoords;
in vec3 WorldPos;
in vec3 Normal;

uniform sampler2D albedoMap, normalMap, metallicMap, roughnessMap, aoMap, emissionMap;
uniform samplerCube irradianceMap;      // IBL_Diffuse
uniform samplerCube prefilterMap;       // IBL_Specular ①
uniform sampler2D   brdfLUT;            // IBL_Specular ②
uniform vec3  camPos;
uniform vec3  lightPositions[4];
uniform vec3  lightColors[4];

const float PI = 3.14159265359;
const float MAX_LOD = 4.0;

struct Material { vec3 albedo; float metallic; float roughness;
                  float ao; vec3 emission; };

// ===== 叶子 =====
vec3 ComputeF0(vec3 albedo, float metallic) {
    return mix(vec3(0.04), albedo, metallic);
}

// ===== 第 6 层：D / G / F =====
float D_GGX(vec3 N, vec3 H, float roughness) {
    float a  = roughness * roughness;
    float a2 = a * a;
    float NdotH  = max(dot(N, H), 0.0);
    float NdotH2 = NdotH * NdotH;
    float denom = NdotH2 * (a2 - 1.0) + 1.0;
    return a2 / (PI * denom * denom);
}
float G1_SchlickGGX(float NdotV, float k) {
    return NdotV / (NdotV * (1.0 - k) + k);
}
float G_Smith(vec3 N, vec3 V, vec3 L, float roughness) {
    float k = (roughness + 1.0); k = (k * k) / 8.0;
    return G1_SchlickGGX(max(dot(N,V),0.0), k)
         * G1_SchlickGGX(max(dot(N,L),0.0), k);
}
vec3 F_Schlick(float cosTheta, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}
vec3 F_SchlickRoughness(float cosTheta, vec3 F0, float roughness) {
    return F0 + (max(vec3(1.0 - roughness), F0) - F0)
              * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

// ===== 第 5 层：两个分支 =====
vec3 DiffuseBRDF(vec3 albedo) { return albedo / PI; }
vec3 CookTorrance(vec3 N, vec3 V, vec3 L, vec3 H, float roughness, vec3 F0) {
    float D = D_GGX(N, H, roughness);
    float G = G_Smith(N, V, L, roughness);
    vec3  F = F_Schlick(max(dot(H,V),0.0), F0);
    float NdotV = max(dot(N,V),0.0);
    float NdotL = max(dot(N,L),0.0);
    return (D * F * G) / (4.0 * NdotV * NdotL + 0.0001);
}

// ===== 第 4 层 =====
vec3 EvaluateBRDF(Material mat, vec3 N, vec3 V, vec3 L, vec3 F0) {
    vec3 H = normalize(V + L);
    vec3 F  = F_Schlick(max(dot(H,V),0.0), F0);
    vec3 kS = F;
    vec3 kD = (vec3(1.0) - kS) * (1.0 - mat.metallic);
    return kD * DiffuseBRDF(mat.albedo)
         + kS * CookTorrance(N, V, L, H, mat.roughness, F0);
}

// ===== 第 3 层：直接光 =====
vec3 IncidentRadiance(vec3 lightColor, vec3 lightPos, vec3 worldPos) {
    float d = length(lightPos - worldPos);
    return lightColor / (d * d);
}
vec3 DirectLighting(Material mat, vec3 N, vec3 V, vec3 worldPos) {
    vec3 F0 = ComputeF0(mat.albedo, mat.metallic);
    vec3 Lo = vec3(0.0);
    for (int i = 0; i < 4; ++i) {
        vec3  L = normalize(lightPositions[i] - worldPos);
        vec3  radiance = IncidentRadiance(lightColors[i], lightPositions[i], worldPos);
        float NdotL = max(dot(N, L), 0.0);
        Lo += EvaluateBRDF(mat, N, V, L, F0) * radiance * NdotL;
    }
    return Lo;
}

// ===== 第 3 层：IBL =====
vec3 IBL_Diffuse(vec3 N, vec3 albedo) {
    return texture(irradianceMap, N).rgb * albedo;
}
vec3 IBL_Specular(vec3 N, vec3 V, float roughness, vec3 F) {
    vec3 R = reflect(-V, N);
    vec3 prefiltered = textureLod(prefilterMap, R, roughness * MAX_LOD).rgb;
    vec2 brdf = texture(brdfLUT, vec2(max(dot(N,V),0.0), roughness)).rg;
    return prefiltered * (F * brdf.x + brdf.y);
}
vec3 IBL(Material mat, vec3 N, vec3 V) {
    vec3  F0    = ComputeF0(mat.albedo, mat.metallic);
    float NdotV = max(dot(N, V), 0.0);
    vec3 F  = F_SchlickRoughness(NdotV, F0, mat.roughness);
    vec3 kS = F;
    vec3 kD = (vec3(1.0) - kS) * (1.0 - mat.metallic);
    vec3 diffuse  = IBL_Diffuse(N, mat.albedo);
    vec3 specular = IBL_Specular(N, V, mat.roughness, F);
    return (kD * diffuse + specular) * mat.ao;
}

// ===== 第 1 层：显示变换 =====
vec3 ToneMap(vec3 hdr)      { return hdr / (hdr + vec3(1.0)); }
vec3 GammaCorrect(vec3 lin) { return pow(lin, vec3(1.0 / 2.2)); }

// ===== 根函数 =====
vec3 FinalRGB(vec3 Lo, vec3 ambient, vec3 emission) {
    vec3 color = Lo + ambient + emission;
    color = ToneMap(color);
    color = GammaCorrect(color);
    return color;
}

void main()
{
    // 叶子：采样材质 + 几何向量
    Material mat;
    mat.albedo    = pow(texture(albedoMap, TexCoords).rgb, vec3(2.2));
    mat.metallic  = texture(metallicMap, TexCoords).r;
    mat.roughness = texture(roughnessMap, TexCoords).r;
    mat.ao        = texture(aoMap, TexCoords).r;
    mat.emission  = texture(emissionMap, TexCoords).rgb;

    vec3 N = normalize(Normal);            // 实际项目中读法线贴图
    vec3 V = normalize(camPos - WorldPos);

    // 第 2 层：渲染方程
    vec3 Lo      = DirectLighting(mat, N, V, WorldPos);
    vec3 ambient = IBL(mat, N, V);

    FragColor = vec4(FinalRGB(Lo, ambient, mat.emission), 1.0);  // ★ 根节点输出
}

```

---

## 18. 一句话总结这棵调用树

> **最终 RGB** = `GammaCorrect`( `ToneMap`( 自发光 + `DirectLighting`(Σ 每盏灯 = `EvaluateBRDF`(漫反射 `albedo/π` + 镜面 `D·F·G/4NdotV·NdotL`) × 光强 × NdotL) + `IBL`(辐照度漫反射 + Split-Sum 镜面 × AO) ) )

微表面理论的精髓：**用三个统计函数把微观世界的复杂光学，压缩成每像素几十次乘加运算**——$D$ 数"有多少微表面对准了你"，$G$ 算"它们有没有被同伴挡住"，$F$ 定"每块反射多少光"。这正是它统治实时渲染领域的原因。