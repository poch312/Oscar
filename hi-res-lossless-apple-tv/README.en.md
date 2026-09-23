# Hi-Res Lossless Verification: Apple TV + HDMI Audio Extractor + Multiple DACs

> 🌐 [Español](README.md) · **English** · [中文](README.zh.md) · [हिन्दी](README.hi.md) · [日本語](README.ja.md) · [Português](README.pt.md)

Documentation of hands-on tests confirming that Apple TV (running tvOS 27) delivers audio genuinely above 48kHz for content labeled "Hi-Res Lossless" in Apple Music, verified with different DACs connected to the same HDMI audio extraction chain.

## Common setup

- **Source**: Apple TV 4K, tvOS 27, Apple Music app
- **Connection**: HDMI (Apple TV) → HDMI audio extractor → Optical/coaxial output → Input of the DAC under test
- **HDMI extractor**: generic "HDMI/MHL to IIS I2S" audio extractor with I2S/DSD, optical and coaxial outputs, in an enclosure ([AliExpress](https://a.aliexpress.com/_m0gQ4Sf))

---

## DAC 1: FiiO K7

**Verification device**: FiiO K7 (DAC/amplifier), RGB LED indicator around the volume knob

### Test method

The FiiO K7 has no numeric display. It indicates the sample rate of the incoming digital signal through the color of its RGB LED, according to FiiO's official support page:

| LED color | Meaning |
|---|---|
| Cyan | Sample rate ≤ 48kHz |
| Yellow | Sample rate > 48kHz |
| Green | DSD signal |

### Observed result

- Playing a track labeled **"Hi-Res Lossless"** in Apple Music (Coldplay — "Green Eyes") → LED turns **yellow** (> 48kHz)
- Playing a track labeled standard **"Lossless"** (Miley Cyrus — "Younger Now") → LED turns **cyan/blue** (≤ 48kHz)

### Photographic evidence — FiiO K7

**Hi-Res Lossless track (Coldplay — "Green Eyes", *A Rush of Blood to the Head*)**

![Apple TV showing Hi-Res Lossless](images/apple-tv-coldplay-hires-lossless.jpeg)

The "Hi-Res Lossless" badge is visible in the lower-left corner of the Apple Music screen on Apple TV.

![FiiO K7 with yellow LED](images/k7-led-amarillo-hires.jpeg)

The K7's LED turns **yellow/green** — confirming a sample rate > 48kHz, exactly as FiiO's official table predicts.

**Standard Lossless track (Miley Cyrus — "Younger Now")**

![Apple TV showing Lossless](images/apple-tv-miley-lossless.jpeg)

Here the badge only says "Lossless" (no "Hi-Res").

![FiiO K7 with blue/cyan LED](images/k7-led-azul-lossless.jpeg)

The K7's LED changes to **cyan/blue** — confirming a sample rate ≤ 48kHz, consistent with this track's standard (non-Hi-Res) classification.

**The HDMI audio extractor in the chain**

![Extractor output panel](images/extractor-panel-salidas.jpeg)

Close-up of the extractor's output panel (optical, coaxial, IIS/I2S) connected between the Apple TV and the DAC, with its status LED green indicating an active signal.

**Video**: the LED changing color in real time.

https://github.com/user-attachments/assets/fa6dc061-688a-4db3-85d3-997c63ec1e9c

[Original quality (.mov)](https://github.com/poch312/Oscar/releases/download/videos-hires/k7-led-cambio-color-video.mov)

---

## DAC 2: Fosi Audio ZD3

**Verification device**: Fosi Audio ZD3, round OLED display — unlike the K7, it shows the **exact numeric value** of the sample rate, not just an approximate color.

### Observed result

Playing **"Green Eyes"** (Coldplay — *A Rush of Blood to the Head*), labeled **Hi-Res Lossless** in Apple Music, via the **optical (OPT)** input:

- The ZD3 display shows: **192k** (sample rate), **PCM** (format), volume at **50**
- This confirms with an exact number — not a color approximation — that the signal arrives at 24-bit/192kHz, well above the 48kHz ceiling that existed before tvOS 27

This is a **more precise** confirmation than the K7's: while the K7 only indicates "above 48kHz" with its yellow color, the ZD3 confirms the exact value (192kHz).

### Photographic evidence — Fosi ZD3

![ZD3 display showing 192k PCM via optical](images/zd3-display-192k-opt.jpeg)

ZD3 display showing **192k / OPT / PCM** with volume at 50, while playing the Hi-Res Lossless track.

![Apple TV showing Green Eyes in Hi-Res Lossless](images/apple-tv-greeneyes-hires-lossless-extractor.jpeg)

Apple TV playing "Green Eyes" by Coldplay (album *A Rush of Blood to the Head*), with the "Hi-Res Lossless" badge visible, and the HDMI audio extractor visible in the lower-right corner on top of the soundbar.

**Videos**:

*Video 1*

https://github.com/user-attachments/assets/82a875ff-21fc-429f-bb8d-3ef2c630162e

[Original quality (.mov)](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-1.mov)

*Video 2*

https://github.com/user-attachments/assets/a61e8090-e8d0-4bf9-a687-05de88ff00e6

[Original quality (.mov)](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-2.mov)

*Video 3*

https://github.com/user-attachments/assets/0e932fb8-033e-4ee8-ab29-6125ce7eeeb3

[Original quality (.mov)](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-3.mov)

---

## Technical explanation (applies to both DACs)

Up to **tvOS 26**, Apple TV 4K capped **all** HDMI audio output at a fixed 24-bit/48kHz ceiling, regardless of the quality level selected in the app — that is, even if you chose "Hi-Res Lossless", the actual output never exceeded 48kHz.

This changed with **tvOS 27** (released in June 2026), which for the first time allows Apple TV 4K (2021 and 2022 models) to deliver true Hi-Res Lossless up to 24-bit/192kHz over HDMI, as long as the connected audio system is recognized as compatible.

## Conclusion

The behavior observed in both tests confirms:

1. The Apple TV is running tvOS 27 (or later)
2. It is delivering audio genuinely above 48kHz for Hi-Res Lossless content — not just an interface label with no real change in the signal
3. The HDMI audio extractor → DAC chain is recognized by the system as a Hi-Res-compatible output, enabling the higher-resolution output
4. The ZD3 additionally confirms the exact value: **192kHz**, not just "above 48kHz"

## Sources consulted

- FiiO official support page — K7 LED color indication table
- Fosi Audio official spec sheet — ZD3 display and sample rate specifications
- Press coverage of tvOS 27 and Apple TV's previous audio limits (iPhoneSoft.fr, iFun.de)

---

*Documented on September 22, 2026.*
