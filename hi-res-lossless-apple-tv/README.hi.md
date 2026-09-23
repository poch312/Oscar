# Hi-Res Lossless सत्यापन: Apple TV + HDMI ऑडियो एक्सट्रैक्टर + कई DAC

> 🌐 [Español](README.md) · [English](README.en.md) · [中文](README.zh.md) · **हिन्दी** · [日本語](README.ja.md)

यह दस्तावेज़ उन व्यावहारिक परीक्षणों का विवरण है जो पुष्टि करते हैं कि Apple TV (tvOS 27 के साथ) Apple Music में "Hi-Res Lossless" चिह्नित सामग्री के लिए वास्तव में 48kHz से अधिक सैंपल रेट पर ऑडियो भेजता है। इसकी पुष्टि एक ही HDMI ऑडियो एक्सट्रैक्शन चेन से जुड़े अलग-अलग DAC के साथ की गई।

## सामान्य सेटअप

- **स्रोत**: Apple TV 4K, tvOS 27, Apple Music ऐप
- **कनेक्शन**: HDMI (Apple TV) → HDMI ऑडियो एक्सट्रैक्टर → ऑप्टिकल/कोएक्सियल आउटपुट → परीक्षण किए जा रहे DAC का इनपुट

---

## DAC 1: FiiO K7

**सत्यापन उपकरण**: FiiO K7 (DAC/एम्पलीफ़ायर), वॉल्यूम नॉब के चारों ओर RGB LED संकेतक

### परीक्षण विधि

FiiO K7 में कोई संख्यात्मक डिस्प्ले नहीं है। FiiO के आधिकारिक सपोर्ट पेज के अनुसार, यह आने वाले डिजिटल सिग्नल का सैंपल रेट अपनी RGB LED के रंग से दर्शाता है:

| LED का रंग | अर्थ |
|---|---|
| सियान (हल्का नीला) | सैंपल रेट ≤ 48kHz |
| पीला | सैंपल रेट > 48kHz |
| हरा | DSD सिग्नल |

### देखा गया परिणाम

- Apple Music में **"Hi-Res Lossless"** चिह्नित ट्रैक चलाने पर (Coldplay — "Green Eyes") → LED **पीली** हो जाती है (> 48kHz)
- सामान्य **"Lossless"** चिह्नित ट्रैक चलाने पर (Miley Cyrus — "Younger Now") → LED **सियान/नीली** हो जाती है (≤ 48kHz)

### फ़ोटोग्राफ़िक प्रमाण — FiiO K7

**Hi-Res Lossless ट्रैक (Coldplay — "Green Eyes", *A Rush of Blood to the Head*)**

![Apple TV पर Hi-Res Lossless](images/apple-tv-coldplay-hires-lossless.jpeg)

Apple TV पर Apple Music स्क्रीन के निचले बाएँ कोने में "Hi-Res Lossless" बैज दिखाई दे रहा है।

![पीली LED के साथ FiiO K7](images/k7-led-amarillo-hires.jpeg)

K7 की LED **पीली/हरी** हो जाती है — यह पुष्टि करता है कि सैंपल रेट > 48kHz है, ठीक वैसे ही जैसे FiiO की आधिकारिक तालिका बताती है।

**सामान्य Lossless ट्रैक (Miley Cyrus — "Younger Now")**

![Apple TV पर Lossless](images/apple-tv-miley-lossless.jpeg)

यहाँ बैज पर केवल "Lossless" लिखा है ("Hi-Res" नहीं)।

![नीली/सियान LED के साथ FiiO K7](images/k7-led-azul-lossless.jpeg)

K7 की LED **सियान/नीली** हो जाती है — यह पुष्टि करता है कि सैंपल रेट ≤ 48kHz है, जो इस ट्रैक के सामान्य (गैर-Hi-Res) वर्गीकरण के अनुरूप है।

**चेन में HDMI ऑडियो एक्सट्रैक्टर**

![एक्सट्रैक्टर का आउटपुट पैनल](images/extractor-panel-salidas.jpeg)

Apple TV और DAC के बीच जुड़े एक्सट्रैक्टर के आउटपुट पैनल (ऑप्टिकल, कोएक्सियल, IIS/I2S) का नज़दीकी दृश्य; हरी स्टेटस LED सक्रिय सिग्नल दर्शाती है।

**वीडियो**: [k7-led-cambio-color-video.mov](https://github.com/poch312/Oscar/releases/download/videos-hires/k7-led-cambio-color-video.mov) — LED का रीयल टाइम में रंग बदलना।

---

## DAC 2: Fosi Audio ZD3

**सत्यापन उपकरण**: Fosi Audio ZD3, गोल OLED डिस्प्ले — K7 के विपरीत, यह केवल अनुमानित रंग नहीं बल्कि सैंपल रेट का **सटीक संख्यात्मक मान** दिखाता है।

### देखा गया परिणाम

Apple Music में **Hi-Res Lossless** चिह्नित **"Green Eyes"** (Coldplay — *A Rush of Blood to the Head*) को **ऑप्टिकल (OPT)** इनपुट से चलाने पर:

- ZD3 की स्क्रीन दिखाती है: **192k** (सैंपल रेट), **PCM** (फ़ॉर्मेट), वॉल्यूम **50**
- यह सटीक संख्या के साथ — रंग के अनुमान से नहीं — पुष्टि करता है कि सिग्नल 24-bit/192kHz पर पहुँच रहा है, जो tvOS 27 से पहले की 48kHz सीमा से बहुत ऊपर है

यह K7 की तुलना में **अधिक सटीक** पुष्टि है: K7 पीले रंग से केवल "48kHz से ऊपर" बताता है, जबकि ZD3 सटीक मान (192kHz) की पुष्टि करता है।

### फ़ोटोग्राफ़िक प्रमाण — Fosi ZD3

![ऑप्टिकल से 192k PCM दिखाती ZD3 स्क्रीन](images/zd3-display-192k-opt.jpeg)

Hi-Res Lossless ट्रैक चलते समय ZD3 स्क्रीन पर **192k / OPT / PCM** और वॉल्यूम 50।

![Apple TV पर Hi-Res Lossless में Green Eyes](images/apple-tv-greeneyes-hires-lossless-extractor.jpeg)

Apple TV पर Coldplay का "Green Eyes" (एल्बम *A Rush of Blood to the Head*) चल रहा है, "Hi-Res Lossless" बैज दिखाई दे रहा है, और निचले दाएँ कोने में साउंडबार के ऊपर HDMI ऑडियो एक्सट्रैक्टर दिखाई दे रहा है।

**वीडियो**: [zd3-video-1.mov](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-1.mov), [zd3-video-2.mov](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-2.mov), [zd3-video-3.mov](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-3.mov)

---

## तकनीकी व्याख्या (दोनों DAC पर लागू)

**tvOS 26** तक, Apple TV 4K **सभी** HDMI ऑडियो आउटपुट को 24-bit/48kHz की निश्चित सीमा पर रोक देता था, चाहे ऐप में कोई भी गुणवत्ता स्तर चुना गया हो — यानी "Hi-Res Lossless" चुनने पर भी वास्तविक आउटपुट कभी 48kHz से अधिक नहीं होता था।

यह **tvOS 27** (जून 2026 में जारी) के साथ बदल गया, जो पहली बार Apple TV 4K (2021 और 2022 मॉडल) को HDMI के माध्यम से 24-bit/192kHz तक वास्तविक Hi-Res Lossless देने की अनुमति देता है, बशर्ते जुड़ा हुआ ऑडियो सिस्टम संगत के रूप में पहचाना जाए।

## निष्कर्ष

दोनों परीक्षणों में देखा गया व्यवहार पुष्टि करता है कि:

1. Apple TV पर tvOS 27 (या बाद का संस्करण) चल रहा है
2. यह Hi-Res Lossless सामग्री के लिए वास्तव में 48kHz से अधिक पर ऑडियो भेज रहा है — यह सिग्नल में बिना किसी वास्तविक बदलाव के केवल इंटरफ़ेस का लेबल नहीं है
3. HDMI ऑडियो एक्सट्रैक्टर → DAC चेन को सिस्टम Hi-Res-संगत आउटपुट के रूप में पहचानता है, जिससे उच्च रिज़ॉल्यूशन आउटपुट सक्षम होता है
4. ZD3 से सटीक मान की भी पुष्टि होती है: **192kHz**, न कि केवल "48kHz से ऊपर"

## संदर्भ स्रोत

- FiiO का आधिकारिक सपोर्ट पेज — K7 की LED रंग संकेत तालिका
- Fosi Audio की आधिकारिक विनिर्देश शीट — ZD3 के डिस्प्ले और सैंपल रेट विनिर्देश
- tvOS 27 और Apple TV की पिछली ऑडियो सीमाओं पर प्रेस कवरेज (iPhoneSoft.fr, iFun.de)

---

*22 सितंबर 2026 को प्रलेखित।*
