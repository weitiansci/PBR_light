# 实时渲染中的 PBR 光照渲染算法研究

> 基于联网调研整理（LearnOpenGL、Disney/SIGGRAPH 论文、PBR Book、Self Shadow 博客、Enterprise PBR Shading Model 规范、NVIDIA 研究等），面向实时渲染（游戏引擎 / Vulkan / OpenGL / 移动端）的 PBR 光照算法综述与实现参考。

---

## 目录

1. [PBR 概述与发展历程](#1-pbr-概述与发展历程)
2. [辐射度量学基础](#2-辐射度量学基础)
3. [渲染方程](#3-渲染方程)
4. [BRDF 基础理论](#4-brdf-基础理论)
5. [微表面模型与 Cook-Torrance 镜面反射](#5-微表面模型与-cook-torrance-镜面反射)
6. [漫反射项](#6-漫反射项)
7. [材质参数化工作流](#7-材质参数化工作流)
8. [直接光照（解析光源）](#8-直接光照解析光源)
9. [间接光照与基于图像的照明（IBL）](#9-间接光照与基于图像的照明ibl)
10. [进阶材质模型](#10-进阶材质模型)
11. [实时全局光照的前沿趋势](#11-实时全局光照的前沿趋势)
12. [实时性能优化要点](#12-实时性能优化要点)
13. [最小可运行 GLSL 参考实现](#13-最小可运行-glsl-参考实现)
14. [参考资料](#14-参考资料)

---

## 1. PBR 概述与发展历程

**PBR（Physically Based Rendering，基于物理的渲染）** 是一套用物理光学原理描述光与表面交互的渲染方法论。与传统经验模型（Phong / Blinn-Phong）相比，PBR 的核心差异在于：

| 特性 | 经验模型（Phong 等） | PBR |
|---|---|---|
| 光照响应 | 手工调参的经验公式 | 基于能量守恒与微表面物理模型 |
| 菲涅尔效应 | 通常忽略 | 内建（入射角相关反射率） |
| 材质一致性 | 依赖美术逐材质调试 | 统一参数空间，跨环境一致 |
| 环境适应性 | 差（换环境需重新调） | 好（能量守恒自动适应） |

**关键里程碑：**

- **1982**：Cook & Torrance 提出微表面镜面反射模型（Cook-Torrance BRDF），成为现代 PBR 镜面项的根基。
- **1985–2000s**：微表面理论（Beckmann、Trowbridge-Reitz/GGX 分布）、Smith 遮蔽-阴影函数逐步完善。
- **2007**：Trowbridge-Reitz 分布被重新发现并推广为 **GGX**（Walter et al.），因长尾高光更符合真实测量数据，成为业界事实标准。
- **2012**：迪士尼在 SIGGRAPH 2012 发表 **Disney Principled BRDF**（Brent Burley），用直观的艺术化参数（metallic、roughness、subsurface、sheen 等）统一描述绝大多数材质，直接推动了 metal/rough 工作流成为行业标准。
- **2013–2015**：UE4、Unity、Frostbite、寒霜等主流引擎全面落地 PBR；Karis（UE4）提出移动端友好的实时 PBR 近似。
- **2017 至今**：多次散射能量补偿（Kulla-Conty, 2017）、硬件光追（RTX）、实时全局光照（Lumen、Radiance Cache、DDGI、神经辐射缓存）让 PBR 从"单点着色"走向"全链路物理光照"。

PBR 的三大支柱约定：

1. **微表面理论（Microfacet Theory）**
2. **能量守恒（Energy Conservation）**
3. **基于物理的 BRDF**

---

## 2. 辐射度量学基础

PBR 建立在辐射度量学（Radiometry）之上，核心量：

- **辐射能量 \(Q\)（Radiant Energy，J）**：以光子形式传输的能量。
- **辐射通量 \(\Phi\)（Radiant Flux，W）**：单位时间传输的能量，\(\Phi = \frac{dQ}{dt}\)。
- **立体角 \(\omega\)（Solid Angle，sr）**：观察者在单位球面上截取的面积，\(d\omega = \sin\theta \, d\theta \, d\phi\)。
- **辐射强度 \(I\)（Radiant Intensity，W/sr）**：单位立体角内的辐射通量，\(I = \frac{d\Phi}{d\omega}\)。
- **辐照度 \(E\)（Irradiance，W/m²）**：单位表面积接收的辐射通量总和。
- **辐射率 \(L\)（Radiance，W·m⁻²·sr⁻¹）**：单位投影面积、单位立体角内的辐射通量：

\[
L = \frac{d^2\Phi}{dA \, \cos\theta \, d\omega}
\]

**辐射率是渲染中最重要的量**：它沿真空（无介质）直线传播时不衰减，且同时包含"方向"与"面积"信息。着色器最终计算的就是从表面沿视线方向出射的辐射率 \(L_o\)。

注意**朗伯余弦定律**：入射光与表面夹角越小，单位面积接收的能量越少，故辐照度积分中要乘 \(\cos\theta\)（即 \(N \cdot L\)）。

---

## 3. 渲染方程

Kajiya（1986）提出的**渲染方程**是 PBR 的总纲，描述表面一点 \(x\) 沿方向 \(\omega_o\) 出射的辐射率：

\[
L_o(x, \omega_o) = L_e(x, \omega_o) + \int_{\Omega} f_r(x, \omega_i, \omega_o) \, L_i(x, \omega_i) \, (n \cdot \omega_i) \, d\omega_i
\]

- \(L_e\)：自发光（emissive）。
- \(\Omega\)：以 \(x\) 为中心的半球域（所有入射方向）。
- \(f_r\)：**BRDF**，描述入射方向 \(\omega_i\) 对出射方向 \(\omega_o\) 辐射率的贡献比例。
- \(L_i(\omega_i)\)：来自方向 \(\omega_i\) 的入射辐射率。
- \((n \cdot \omega_i)\)：朗伯余弦项。

渲染方程是一个积分方程，**实时渲染不可能精确求解**，因此所有实时 PBR 都是对它的近似拆分：

\[
\text{总光照} \approx \underbrace{\text{直接光照（解析光源，逐项求和）}}_{\text{punctual lights}} + \underbrace{\text{间接光照（IBL / GI，半球积分的近似）}}_{\text{environment / GI}}
\]

---

## 4. BRDF 基础理论

**BRDF（Bidirectional Reflectance Distribution Function，双向反射分布函数）** 定义：

\[
f_r(\omega_i, \omega_o) = \frac{dL_o(\omega_o)}{dE_i(\omega_i)} = \frac{dL_o(\omega_o)}{L_i(\omega_i) \cos\theta_i \, d\omega_i}
\]

直观理解：给定来自 \(\omega_i\) 的入射光，BRDF 决定有多少光被反射到 \(\omega_o\)。

实时 PBR 中 BRDF 一般拆为漫反射 + 镜面反射两部分：

\[
f_r = k_d \, f_{diffuse} + k_s \, f_{specular}
\]

其中 \(k_d + k_s \le 1\)（能量守恒）。

**物理正确的 BRDF 需满足：**

1. **能量守恒**：反射总能量不超过入射能量。实时渲染中通常采用"近似能量守恒"（如 UE4 的做法），用可见性项替代部分归一化以换取性能。
2. **Helmholtz 互易性**：\(f_r(\omega_i, \omega_o) = f_r(\omega_o, \omega_i)\)。
3. **非负性**：\(f_r \ge 0\)。

**金属 vs 电介质（介电体）：**

| 性质 | 电介质（塑料、皮肤、木头） | 金属 |
|---|---|---|
| 反射率 F0 | 约 0.02–0.05（近乎无色） | 0.5–1.0，且带颜色（金、铜） |
| 漫反射 | 有（光折射进入内部再散射出来） | 几乎无（光在表面即被吸收/反射） |
| 反射颜色 | 白色/无色高光 | 高光带金属本色 |

常见材质 F0 参考值：水 0.02、塑料 0.04、玻璃 0.04、钻石 0.08、银 0.97、铝 0.91、金 0.95（带黄红色调）。业界约定**电介质默认 F0 = 0.04**。

---

## 5. 微表面模型与 Cook-Torrance 镜面反射

### 5.1 微表面理论

宏观表面上任意一点，在微观尺度都由无数朝向各异的微小镜面（microfacet）组成。粗糙度越大，微表面朝向越分散，高光越模糊。只有**法线恰好等于半程向量 \(h = \frac{\omega_i + \omega_o}{|\omega_i + \omega_o|}\) 的微表面**才能把光反射到观察者眼中。

### 5.2 Cook-Torrance 镜面 BRDF

\[
f_{spec} = \frac{D(\omega_i, \omega_o) \, F(\omega_i, \omega_o) \, G(\omega_i, \omega_o)}{4 \, (\omega_o \cdot n)(\omega_i \cdot n)}
\]

三个因子各司其职：

#### D —— 法线分布函数（NDF）

估算微表面中法线对齐半程向量 \(h\) 的比例，决定高光斑的形状与大小。**GGX（Trowbridge-Reitz）是当前标准**：

\[
D_{GGX}(n, h, \alpha) = \frac{\alpha^2}{\pi \, ((n \cdot h)^2 (\alpha^2 - 1) + 1)^2}
\]

其中 \(\alpha\) 为粗糙度。GGX 的长尾特性使高光边缘衰减自然，优于 Blinn-Phong 与 Beckmann。

其他历史选项：Beckmann、Blinn-Phong（\((n \cdot h)^{m}\) 形式，非能量守恒）。

#### G —— 几何函数（遮蔽与阴影）

描述微表面相互遮挡导致光线损失的比例：粗糙表面微表面起伏大，反射光更容易被其他微表面挡住（Masking：挡住出射光；Shadowing：挡住入射光）。实时实现常用 **Smith 方法 + Schlick-GGX**：

\[
G_{SchlickGGX}(n, v, k) = \frac{n \cdot v}{(n \cdot v)(1 - k) + k}, \quad
k_{direct} = \frac{(\alpha + 1)^2}{8}, \quad k_{IBL} = \frac{\alpha^2}{2}
\]

\[
G(n, v, l, k) = G_{SchlickGGX}(n, v, k) \cdot G_{SchlickGGX}(n, l, k)
\]

更精确的现代选择是 **height-correlated Smith**（Hammon 2017，UE5 采用），将遮蔽与阴影视为相关而非独立事件，减少能量误差：

\[
G_2 = \frac{2 (n \cdot l)(n \cdot v)}{(n \cdot v)\sqrt{\alpha^2 + (1-\alpha^2)(n \cdot l)^2} + (n \cdot l)\sqrt{\alpha^2 + (1-\alpha^2)(n \cdot v)^2}}
\]

#### F —— 菲涅尔方程

描述不同入射角下反射与折射的能量比例。精确的 Fresnel 方程对偏振态求解复杂，实时渲染使用 **Fresnel-Schlick 近似**：

\[
F_{Schlick}(h, v, F_0) = F_0 + (1 - F_0)(1 - (h \cdot v))^5
\]

- 正对表面（垂直入射）时反射率为 \(F_0\)；
- 掠射角（grazing angle）时反射率趋近 1 —— 即"所有材质在掠射角都像镜子"的真实现象。

改进变体：**Fresnel-Schlick-Lagarde** 用 \((1 - (h \cdot v))^5\) 替换指数以适配粗糙表面；**球面高斯近似** \((1 - (h \cdot v))^{5.6}\) 或 `exp2(-10.86 * dot + 5.25)` 可进一步提速。

### 5.3 能量守恒与 kd/ks 拆分

菲涅尔项同时充当镜面反射比例 \(k_s = F\)，漫反射权重为：

\[
k_d = (1 - F)(1 - metallic)
\]

金属没有漫反射，故乘 \((1 - metallic)\)。

---

## 6. 漫反射项

- **Lambert**：\(f_{diff} = \frac{c}{\pi}\)，常数分布，最简单，实时默认选择。
- **Disney Diffuse**（Burley 2012）：加入掠射角处粗糙表面变暗/变亮的经验修正：

\[
f_{d} = \frac{c}{\pi}\left(1 + (F_{D90} - 1)(1 - \cos\theta_l)^5\right)\left(1 + (F_{D90} - 1)(1 - \cos\theta_v)^5\right)
\]

其中 \(F_{D90} = 0.5 + 2 \, roughness \, \cos^2\theta_d\)，\(\theta_d\) 为光与半程向量夹角。
- **Oren-Nayar**：考虑微表面相互遮蔽/阴影的严格漫反射模型，计算量较大，多用于离线。
- **Kulla-Conty Diffuse / 多次散射补偿漫反射**：见第 10 节。

---

## 7. 材质参数化工作流

### 7.1 两大主流工作流

| | Metal/Rough 工作流 | Specular/Gloss 工作流 |
|---|---|---|
| 贴图 | BaseColor + Metallic + Roughness | Diffuse + Specular(color) + Glossiness |
| 内存 | 更省（Metallic 常为单通道） | 多一张彩色 specular 图 |
| 行业标准 | UE、Unity、glTF、Substance | 早期 PBR 工具，正逐步淘汰 |
| 出错风险 | 低（参数有物理约束） | 美术可能填不物理的值 |

glTF 2.0 标准采用 **metallic-roughness** 模型，参数：

- `baseColorFactor`（0–1 线性 RGB，金属时代表反射颜色，电介质时代表漫反射颜色）
- `metallicFactor`（0–1）
- `roughnessFactor`（0–1）
- 可选：normal、occlusion、emissive

### 7.2 Disney Principled BRDF（SIGGRAPH 2012）

迪士尼原则的参数化思想直接塑造了今天的引擎着色模型，核心参数：

- **BaseColor**：基础颜色
- **Subsurface**：次表面散射比例（混合漫反射形状）
- **Metallic**：金属度
- **Specular**：电介质反射强度（默认 0.5 ≈ F0=0.04）
- **Roughness**：粗糙度
- **Specular Tint**：高光染色
- **Anisotropic**：各向异性
- **Sheen**：织物绒毛光泽
- **Sheen Tint**、**Clearcoat**、**Clearcoat Gloss**

设计哲学：**用艺术家直觉友好的参数覆盖测量数据的分布空间**，而非严格物理参数，但保持能量守恒与物理 plausible。

---

## 8. 直接光照（解析光源）

对每个解析光源（方向光、点光、聚光）直接评估 BRDF：

\[
L_o = \sum_{lights} \left( k_d \, f_{diffuse} + f_{spec} \right) L_i \, (n \cdot l)
\]

- **方向光**：\(L_i\) 为常数强度与颜色。
- **点光**：物理正确的**平方反比衰减** \(L_i = \frac{I}{d^2}\)（I 为光源辐射强度）。实时实现常加平滑截断避免除零与硬边，例如 UE 的 \(Attenuation = \frac{1}{(\frac{d}{r})^4 + 1} - 1\) 窗口函数。
- **聚光**：在点光基础上乘角度衰减（smoothstep 内外锥角）。

**关键实现细节：**

- roughness 不能为 0：GGX 在 \(\alpha = 0\) 时分母为零，且高光退化成点；通常钳制 \(\alpha = max(roughness^2, 0.002)\)。
- 业界约定存储的 roughness 是"感知粗糙度"，进入公式前平方：\(\alpha = roughness^2\)（线性化感知映射）。
- 点光/聚光的几何函数 \(k\) 用直接光照版本 \(k = \frac{(\alpha+1)^2}{8}\)，IBL 用 \(k = \frac{\alpha^2}{2}\)。

---

## 9. 间接光照与基于图像的照明（IBL）

间接光贡献渲染方程的半球积分，实时上无法逐像素积分，**IBL（Image Based Lighting）** 用环境贴图（HDR 环境图，等距柱状或立方体贴图）作为无限远球面光源来近似：

\[
L_{indirect} = \int_{\Omega} f_r(\omega_i, \omega_o) \, L_{env}(\omega_i) \, (n \cdot \omega_i) \, d\omega_i
\]

同样拆成漫反射与镜面两部分处理。

### 9.1 漫反射 IBL：辐照度图（Irradiance Map）

漫反射积分中 BRDF 是常数 \(\frac{c}{\pi}\)，可提到积分外：

\[
L_{irr} = \frac{c}{\pi} \int_{\Omega} L_{env}(\omega_i) \cos\theta_i \, d\omega_i
\]

**离线预计算**：对环境贴图按半球余弦加权的卷积，生成低分辨率辐照度图（典型 32×32），运行时直接按法线采样。卷积可用球谐坐标离散化或重要性采样蒙特卡洛完成。

更紧凑的替代：**球谐函数（Spherical Harmonics，SH）** 用 9 个系数（二阶）存储辐照度，采样极快，广泛用于移动端。

### 9.2 镜面 IBL：Split-Sum 近似（Karis, UE4, 2013）

镜面积分不能提常数，Epic 的 Brian Karis 提出**分裂和近似（Split Sum Approximation）**，把积分拆成两个可预计算部分的乘积：

\[
\int_{\Omega} f_r \, L_i \, (n \cdot \omega_i) d\omega_i
\approx
\underbrace{\left( \int_{\Omega} L_i(\omega_i) d\omega_i \right)}_{\text{预滤波环境图}}
\cdot
\underbrace{\left( \int_{\Omega} f_r(\omega_i, \omega_o)(n \cdot \omega_i) d\omega_i \right)}_{\text{BRDF 积分 LUT}}
\]

**① 预滤波环境图（Pre-filtered Environment Map）**

用 GGX 重要性采样对每个粗糙度级别卷积环境图，结果存入 mipmap 链（粗糙度越高采样越模糊）。预滤波时假设 \(n = v = r\)（镜面反射方向），这是近似误差的主要来源。

**② BRDF 积分 LUT（2D 查找表）**

把 BRDF 积分预计算成一张 512×512 的 2D 纹理，横轴 \(N \cdot V\)，纵轴粗糙度，RG 通道存两个缩放/偏置系数：

\[
\int_{\Omega} f_r (n \cdot \omega_i) d\omega_i \approx F_0 \cdot A(N\cdot V, roughness) + B(N\cdot V, roughness)
\]

LUT 与具体环境图无关，一次生成全局复用。

**③ 运行时合成：**

```glsl
vec3 specularIBL = prefilteredColor * (F0 * brdf.x + brdf.y);
```

**现代补充：多散射 IBL**。Split-sum 只考虑单次弹射，粗糙金属会因能量损失发暗。2020 年后主流引擎引入**多次散射 IBL LUT**（如 Frostbite 的"multi-scattering"项、Opsenica 的实现），额外采样一张存储多次弹射能量补偿的纹理加回去。

### 9.3 环境遮蔽与间接光衰减

- SSAO / GTAO 为间接漫反射提供遮蔽项。
- Specular 遮挡：用屏幕空间反射（SSR）+ 反射捕获混合。

---

## 10. 进阶材质模型

现代引擎着色模型（UE5、Enterprise PBR、MaterialX PBR Spec 2024x）在基础层之上叠加：

### 10.1 多次散射能量补偿（Kulla-Conty, 2017）

单次弹射微表面模型在粗糙表面丢失大量能量（光在微表面间弹射多次后其实仍会出射）。Kulla & Conty 提出用离线预计算的**方向反照率 E(μ)** 表构造补偿项：

\[
f_{ms}(\omega_i, \omega_o) = \frac{(1 - E(\omega_i))(1 - E(\omega_o))}{\pi (1 - E_{avg})} \cdot f_{avg}
\]

运行时用两张小 LUT 查表合成，成本低，已广泛用于 UE5 与商业引擎，显著改善粗糙金属亮度与着色能量守恒。

### 10.2 Clear Coat（清漆层）

双层材质：上层光滑透明涂层（如车漆、漆器），下层基础层。实现为**叠加第二个 GGX 镜面项**（固定 F0≈0.04、独立粗糙度），并按菲涅尔对下层能量衰减：

\[
f = f_{base} \cdot (1 - F_{coat}) + f_{coat}
\]

### 10.3 各向异性（Anisotropy）

拉丝金属/头发：微表面凹槽有方向性，高光沿切线方向拉伸。使用**各向异性 GGX**：

\[
D_{aniso} = \frac{1}{\pi \alpha_t \alpha_b \left( \frac{(h \cdot t)^2}{\alpha_t^2} + \frac{(h \cdot b)^2}{\alpha_b^2} + (h \cdot n)^2 \right)^2}
\]

其中 \(t, b\) 为切线与副切线，\(\alpha_t, \alpha_b\) 由粗糙度与各向异性参数合成。glTF 的 `KHR_materials_anisotropy` 扩展即此模型。

### 10.4 Sheen（织物光泽）

绒毛/织物边缘的逆向散射。常用 **Charlie NDF** + 近似可见性，或 MaterialX 中的 Conty-Kulla / Zeltner sheen 模型。

### 10.5 次表面散射（SSS）

皮肤、玉石、蜡：光进入材质内部散射后从别处出射。实时方案：

- **透射贴图 / wrap lighting**（廉价）
- **屏幕空间 SSS（Separable SSS，Jimenez）**：对深度不连续敏感区域做可分离卷积
- **扩散剖面（Diffusion Profile）**：UE 系引擎的标准做法
- 预积分皮肤 LUT（pre-integrated skin）

### 10.6 透射与折射

玻璃/液体：KHR_materials_transmission、volume 扩展；实时常用屏幕空间折射 + 粗糙度模糊环境。

---

## 11. 实时全局光照的前沿趋势

2023–2026 年，实时 PBR 的重心已从"着色模型"转向"光照传输求解"：

| 技术 | 代表 | 原理 |
|---|---|---|
| **硬件光追反射/GI** | Cyberpunk 2077 RT Overdrive、RTXDI | 少量光线 + 重降噪（ReSTIR、SVGF） |
| **Lumen** | UE5 | 软件光追（SDF / Mesh Cards）+ 硬件光追可选；表面缓存（Surface Cache）+ Final Gather |
| **Radiance Caching** | NVIDIA Ada/GDC 2023 演示 | 光线追踪 + 异步辐射缓存，GPU 上实时路径追踪 final gather |
| **神经辐射缓存（NRC）** | NVIDIA Research | 用极小 MLP 在线学习间接辐射场，每帧增量训练，配合 Tensor Core |
| **DDGI / RTXGI** | UE5 Lumen 备选、NVIDIA RTXGI | 动态探针网格存储辐照度八面体图集，支持全动态场景 |
| **Voxel GI / VCT** | UE5 实验性 VCT | 体素锥追踪，无硬件光追需求 |
| **ReSTIR DI/GI** | RTXDI | 时空重采样重要性采样，单样本高质量直接/间接光 |

趋势总结：**PBR 着色模型已高度标准化（GGX + Smith + Fresnel-Schlick 是事实标准），竞争点转移到 GI 求解器与降噪/神经缓存**。

---

## 12. 实时性能优化要点

1. **预计算优先**：BRDF LUT、辐照度图、预滤波环境图全部离线/启动时生成。
2. **重要性采样**：GGX NDF 采样预滤波贴图，收敛快。
3. **近似公式**：
   - Fresnel 指数用球面高斯近似：`exp2(-10.86*x + 5.25)`
   - `1/N·V` 项与几何项合并消元（ Visibility = G/(4 N·V N·L) 预合并为 `V_SmithJointApprox`）
4. **half 精度**：移动端（Mali/Adreno）PBR 着色大量使用 mediump。
5. **IBL 多 LOD**：粗糙度映射到 mipmap level，避免分支。
6. **延迟渲染**：PBR 多参数非常适合 GBuffer 延迟管线（UE/Unity HDRP 默认）。
7. **环境光近似**：低端设备用 SH 9 系数替代辐照度卷积采样。

---

## 13. 最小可运行 GLSL 参考实现

```glsl
// ---------- PBR 直接光照核心 ----------
const float PI = 3.14159265359;

float DistributionGGX(vec3 N, vec3 H, float roughness) {
    float a  = roughness * roughness;
    float a2 = a * a;
    float NdotH  = max(dot(N, H), 0.0);
    float NdotH2 = NdotH * NdotH;
    float denom = (NdotH2 * (a2 - 1.0) + 1.0);
    denom = PI * denom * denom;
    return a2 / denom;
}

float GeometrySchlickGGX(float NdotV, float roughness) {
    float r = roughness + 1.0;
    float k = (r * r) / 8.0;                 // 直接光照
    return NdotV / (NdotV * (1.0 - k) + k);
}

float GeometrySmith(vec3 N, vec3 V, vec3 L, float roughness) {
    float NdotV = max(dot(N, V), 0.0);
    float NdotL = max(dot(N, L), 0.0);
    return GeometrySchlickGGX(NdotV, roughness)
         * GeometrySchlickGGX(NdotL, roughness);
}

vec3 FresnelSchlick(float cosTheta, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

vec3 ShadeDirectLight(vec3 N, vec3 V, vec3 L, vec3 radiance,
                      vec3 albedo, float metallic, float roughness, vec3 F0) {
    vec3 H = normalize(V + L);
    float NDF = DistributionGGX(N, H, roughness);
    float G   = GeometrySmith(N, V, L, roughness);
    vec3  F   = FresnelSchlick(max(dot(H, V), 0.0), F0);

    vec3 numerator   = NDF * G * F;
    float denominator = 4.0 * max(dot(N, V), 0.0) * max(dot(N, L), 0.0) + 0.0001;
    vec3 specular = numerator / denominator;

    vec3 kS = F;
    vec3 kD = (vec3(1.0) - kS) * (1.0 - metallic);

    float NdotL = max(dot(N, L), 0.0);
    return (kD * albedo / PI + specular) * radiance * NdotL;
}

// ---------- IBL 间接光照（Split-Sum） ----------
uniform samplerCube irradianceMap;     // 漫反射辐照度图
uniform samplerCube prefilteredMap;    // 镜面预滤波环境图（mip = 粗糙度）
uniform sampler2D   brdfLUT;           // BRDF 积分查找表

vec3 ShadeIBL(vec3 N, vec3 V, vec3 R,
              vec3 albedo, float metallic, float roughness, vec3 F0) {
    // 漫反射
    vec3 irradiance = texture(irradianceMap, N).rgb;
    vec3 diffuse    = irradiance * albedo;

    // 镜面：split-sum
    vec3 prefilteredColor = textureLod(prefilteredMap, R, roughness * 4.0).rgb;
    vec2 brdf = texture(brdfLUT, vec2(max(dot(N, V), 0.0), roughness)).rg;
    vec3 specular = prefilteredColor * (F0 * brdf.x + brdf.y);

    vec3 F = FresnelSchlick(max(dot(N, V), 0.0), F0);
    vec3 kD = (1.0 - F) * (1.0 - metallic);
    return kD * diffuse + specular;
}

// ---------- 主入口 ----------
vec3 PBRShade(vec3 N, vec3 V, vec3 albedo,
              float metallic, float roughness, float ao) {
    vec3 F0 = mix(vec3(0.04), albedo, metallic);
    vec3 Lo = vec3(0.0);
    // ... 遍历解析光源调用 ShadeDirectLight 累加 ...
    vec3 R = reflect(-V, N);
    vec3 ambient = ShadeIBL(N, V, R, albedo, metallic, roughness, F0) * ao;
    return Lo + ambient;   // 后续做 HDR + ACES/Filmic tonemapping + gamma
}
```

---

## 14. 参考资料

**书籍与系统教程**

- LearnOpenGL —— PBR Theory / IBL（learnopengl.com/PBR；中文站 learnopengl-cn.github.io）
- 《Real-Time Rendering 4th》Ch.9 Physically Based Shading
- PBR Book（pbr-book.org 4th ed.）—— Microfacet Theory 章节
- QianMJ 的《基于物理的渲染（PBR）白皮书》（github.com/QianMJ/PBR-White-Paper）

**论文与演讲**

- Cook & Torrance, *A Reflectance Model for Computer Graphics*, SIGGRAPH 1982
- Walter et al., *Microfacet Models for Refraction through Rough Surfaces*, EGSR 2007（GGX）
- Burley, *Physically-Based Shading at Disney*, SIGGRAPH 2012 Course
- Karis, *Real Shading in Unreal Engine 4*, SIGGRAPH 2013（Split-Sum）
- Kulla & Conty, *Revisiting Physically Based Shading at Imageworks*, SIGGRAPH 2017（多次散射）
- Hammon, *PBR Diffuse Lighting for GGX+Smith Microsurfaces*, GDC 2017

**行业规范与前沿**

- Dassault Enterprise PBR Shading Model Spec 2025x
- Academy Software Foundation MaterialX PBR Spec
- glTF 2.0 KHR_materials_* 扩展（Khronos）
- NVIDIA：Neural Radiance Caching、RTXGI、RTXDI 技术博客
- Self Shadow blog（blog.selfshadow.com）—— Multi-Faceted Exploration 系列
