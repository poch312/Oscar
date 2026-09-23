# Hi-Res Lossless 验证：Apple TV + HDMI 音频分离器 + 多款 DAC

> 🌐 [Español](README.md) · [English](README.en.md) · **中文** · [हिन्दी](README.hi.md) · [日本語](README.ja.md)

本文记录了一系列实际测试，证实 Apple TV（运行 tvOS 27）在播放 Apple Music 中标有“Hi-Res Lossless（高解析度无损）”的内容时，输出的音频采样率确实高于 48kHz。测试使用了多款不同的 DAC，均连接在同一条 HDMI 音频分离链路上。

## 通用配置

- **音源**：Apple TV 4K，tvOS 27，Apple Music 应用
- **连接方式**：HDMI（Apple TV）→ HDMI 音频分离器 → 光纤/同轴输出 → 被测 DAC 的输入端

---

## DAC 1：FiiO K7

**验证设备**：FiiO K7（DAC/耳放），音量旋钮周围带有 RGB LED 指示灯

### 测试方法

FiiO K7 没有数字显示屏。根据 FiiO 官方支持页面，它通过 RGB LED 的颜色来指示输入数字信号的采样率：

| LED 颜色 | 含义 |
|---|---|
| 青色 | 采样率 ≤ 48kHz |
| 黄色 | 采样率 > 48kHz |
| 绿色 | DSD 信号 |

### 观察结果

- 播放 Apple Music 中标有 **“Hi-Res Lossless”** 的曲目（Coldplay —《Green Eyes》）→ LED 变为 **黄色**（> 48kHz）
- 播放标有普通 **“Lossless”** 的曲目（Miley Cyrus —《Younger Now》）→ LED 变为 **青色/蓝色**（≤ 48kHz）

### 照片证据 — FiiO K7

**Hi-Res Lossless 曲目（Coldplay —《Green Eyes》，专辑 *A Rush of Blood to the Head*）**

![Apple TV 显示 Hi-Res Lossless](images/apple-tv-coldplay-hires-lossless.jpeg)

Apple TV 上 Apple Music 界面的左下角可以看到“Hi-Res Lossless”标识。

![FiiO K7 LED 显示黄色](images/k7-led-amarillo-hires.jpeg)

K7 的 LED 变为 **黄色/绿色** —— 确认采样率 > 48kHz，与 FiiO 官方对照表完全一致。

**普通 Lossless 曲目（Miley Cyrus —《Younger Now》）**

![Apple TV 显示 Lossless](images/apple-tv-miley-lossless.jpeg)

此处标识仅显示“Lossless”（没有“Hi-Res”）。

![FiiO K7 LED 显示蓝色/青色](images/k7-led-azul-lossless.jpeg)

K7 的 LED 变为 **青色/蓝色** —— 确认采样率 ≤ 48kHz，与该曲目的普通（非 Hi-Res）分级一致。

**链路中的 HDMI 音频分离器**

![分离器输出面板](images/extractor-panel-salidas.jpeg)

分离器输出面板（光纤、同轴、IIS/I2S）的近景，它连接在 Apple TV 与 DAC 之间，状态 LED 为绿色，表示信号正常。

**视频**：[k7-led-cambio-color-video.mov](https://github.com/poch312/Oscar/releases/download/videos-hires/k7-led-cambio-color-video.mov) —— LED 实时变色过程。

---

## DAC 2：Fosi Audio ZD3

**验证设备**：Fosi Audio ZD3，圆形 OLED 显示屏 —— 与 K7 不同，它显示采样率的 **精确数值**，而不仅仅是近似的颜色。

### 观察结果

通过 **光纤（OPT）** 输入播放 Apple Music 中标有 **Hi-Res Lossless** 的 **《Green Eyes》**（Coldplay —— *A Rush of Blood to the Head*）：

- ZD3 屏幕显示：**192k**（采样率）、**PCM**（格式）、音量 **50**
- 这以精确数值（而非颜色近似）证实信号以 24-bit/192kHz 到达，远高于 tvOS 27 之前存在的 48kHz 上限

这是比 K7 **更精确** 的确认：K7 只能通过黄色表示“高于 48kHz”，而 ZD3 则确认了精确数值（192kHz）。

### 照片证据 — Fosi ZD3

![ZD3 屏幕通过光纤显示 192k PCM](images/zd3-display-192k-opt.jpeg)

播放 Hi-Res Lossless 曲目时，ZD3 屏幕显示 **192k / OPT / PCM**，音量为 50。

![Apple TV 以 Hi-Res Lossless 播放 Green Eyes](images/apple-tv-greeneyes-hires-lossless-extractor.jpeg)

Apple TV 正在播放 Coldplay 的《Green Eyes》（专辑 *A Rush of Blood to the Head*），可以看到“Hi-Res Lossless”标识，右下角回音壁上方可以看到 HDMI 音频分离器。

**视频**：[zd3-video-1.mov](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-1.mov)、[zd3-video-2.mov](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-2.mov)、[zd3-video-3.mov](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-3.mov)

---

## 技术说明（适用于两款 DAC）

在 **tvOS 26** 及之前，Apple TV 4K 将 **所有** HDMI 音频输出限制在固定的 24-bit/48kHz 上限，无论在应用中选择何种音质等级 —— 也就是说，即使选择了“Hi-Res Lossless”，实际输出也从未超过 48kHz。

这一情况在 **tvOS 27**（2026 年 6 月发布）中发生了改变：Apple TV 4K（2021 和 2022 年款）首次可以通过 HDMI 输出真正的 Hi-Res Lossless，最高达 24-bit/192kHz，前提是所连接的音频系统被识别为兼容设备。

## 结论

两项测试中观察到的现象证实：

1. 该 Apple TV 运行的是 tvOS 27（或更高版本）
2. 对于 Hi-Res Lossless 内容，它输出的音频确实高于 48kHz —— 而不仅仅是界面上的标签、信号并无实际变化
3. HDMI 音频分离器 → DAC 这条链路被系统识别为兼容 Hi-Res 的输出，从而启用了更高解析度的输出
4. ZD3 进一步确认了精确数值：**192kHz**，而不仅仅是“高于 48kHz”

## 参考资料

- FiiO 官方支持页面 —— K7 LED 颜色指示对照表
- Fosi Audio 官方规格表 —— ZD3 显示屏及采样率规格
- 关于 tvOS 27 及 Apple TV 以往音频限制的媒体报道（iPhoneSoft.fr、iFun.de）

---

*记录于 2026 年 9 月 22 日。*
