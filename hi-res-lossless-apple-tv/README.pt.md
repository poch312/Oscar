# Verificação de Hi-Res Lossless: Apple TV + Extrator de Áudio HDMI + Vários DACs

> 🌐 [Español](README.md) · [English](README.en.md) · [中文](README.zh.md) · [हिन्दी](README.hi.md) · [日本語](README.ja.md) · **Português**

Documentação de testes práticos que confirmam que a Apple TV (com tvOS 27) entrega áudio genuinamente acima de 48kHz para conteúdo marcado como "Hi-Res Lossless" no Apple Music, verificado com diferentes DACs conectados à mesma cadeia de extração de áudio HDMI.

## Configuração comum

- **Fonte**: Apple TV 4K, tvOS 27, app Apple Music
- **Conexão**: HDMI (Apple TV) → Extrator de áudio HDMI → Saída óptica/coaxial → Entrada do DAC em teste

---

## DAC 1: FiiO K7

**Dispositivo de verificação**: FiiO K7 (DAC/amplificador), indicador LED RGB ao redor do botão de volume

### Método de teste

O FiiO K7 não tem tela numérica. Ele indica a taxa de amostragem (sample rate) do sinal digital de entrada pela cor do seu LED RGB, de acordo com a página oficial de suporte da FiiO:

| Cor do LED | Significado |
|---|---|
| Ciano | Sample rate ≤ 48kHz |
| Amarelo | Sample rate > 48kHz |
| Verde | Sinal DSD |

### Resultado observado

- Reproduzindo uma faixa marcada como **"Hi-Res Lossless"** no Apple Music (Coldplay — "Green Eyes") → o LED fica **amarelo** (> 48kHz)
- Reproduzindo uma faixa marcada como **"Lossless"** padrão (Miley Cyrus — "Younger Now") → o LED fica **ciano/azul** (≤ 48kHz)

### Evidência fotográfica — FiiO K7

**Faixa Hi-Res Lossless (Coldplay — "Green Eyes", *A Rush of Blood to the Head*)**

![Apple TV mostrando Hi-Res Lossless](images/apple-tv-coldplay-hires-lossless.jpeg)

O selo "Hi-Res Lossless" aparece no canto inferior esquerdo da tela do Apple Music na Apple TV.

![FiiO K7 com LED amarelo](images/k7-led-amarillo-hires.jpeg)

O LED do K7 fica **amarelo/verde** — confirma sample rate > 48kHz, exatamente como prevê a tabela oficial da FiiO.

**Faixa Lossless padrão (Miley Cyrus — "Younger Now")**

![Apple TV mostrando Lossless](images/apple-tv-miley-lossless.jpeg)

Aqui o selo diz apenas "Lossless" (sem "Hi-Res").

![FiiO K7 com LED azul/ciano](images/k7-led-azul-lossless.jpeg)

O LED do K7 muda para **ciano/azul** — confirma sample rate ≤ 48kHz, coerente com a classificação padrão (não Hi-Res) desta faixa.

**O extrator de áudio HDMI na cadeia**

![Painel de saídas do extrator](images/extractor-panel-salidas.jpeg)

Vista aproximada do painel de saídas do extrator (óptica, coaxial, IIS/I2S) conectado entre a Apple TV e o DAC, com o LED de status verde indicando sinal ativo.

**Vídeo**: mudança de cor do LED em tempo real.

https://github.com/user-attachments/assets/fa6dc061-688a-4db3-85d3-997c63ec1e9c

[Qualidade original (.mov)](https://github.com/poch312/Oscar/releases/download/videos-hires/k7-led-cambio-color-video.mov)

---

## DAC 2: Fosi Audio ZD3

**Dispositivo de verificação**: Fosi Audio ZD3, tela OLED redonda — ao contrário do K7, mostra o **valor numérico exato** do sample rate, e não apenas uma cor aproximada.

### Resultado observado

Reproduzindo **"Green Eyes"** (Coldplay — *A Rush of Blood to the Head*), marcada como **Hi-Res Lossless** no Apple Music, pela entrada **óptica (OPT)**:

- A tela do ZD3 mostra: **192k** (sample rate), **PCM** (formato), volume em **50**
- Isso confirma com um número exato — e não uma aproximação por cor — que o sinal chega a 24-bit/192kHz, muito acima do limite de 48kHz que existia antes do tvOS 27

Esta é uma confirmação **mais precisa** que a do K7: enquanto o K7 indica apenas "acima de 48kHz" com a cor amarela, o ZD3 confirma o valor exato (192kHz).

### Evidência fotográfica — Fosi ZD3

![Tela do ZD3 mostrando 192k PCM pela entrada óptica](images/zd3-display-192k-opt.jpeg)

Tela do ZD3 mostrando **192k / OPT / PCM** com o volume em 50, enquanto reproduz a faixa Hi-Res Lossless.

![Apple TV mostrando Green Eyes em Hi-Res Lossless](images/apple-tv-greeneyes-hires-lossless-extractor.jpeg)

Apple TV reproduzindo "Green Eyes" do Coldplay (álbum *A Rush of Blood to the Head*), com o selo "Hi-Res Lossless" visível e o extrator de áudio HDMI visível no canto inferior direito, sobre a soundbar.

**Vídeos**:

*Vídeo 1*

https://github.com/user-attachments/assets/82a875ff-21fc-429f-bb8d-3ef2c630162e

[Qualidade original (.mov)](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-1.mov)

*Vídeo 2*

https://github.com/user-attachments/assets/a61e8090-e8d0-4bf9-a687-05de88ff00e6

[Qualidade original (.mov)](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-2.mov)

*Vídeo 3*

https://github.com/user-attachments/assets/0e932fb8-033e-4ee8-ab29-6125ce7eeeb3

[Qualidade original (.mov)](https://github.com/poch312/Oscar/releases/download/videos-hires/zd3-video-3.mov)

---

## Explicação técnica (vale para os dois DACs)

Até o **tvOS 26**, a Apple TV 4K limitava **toda** a saída de áudio via HDMI a um teto fixo de 24-bit/48kHz, independentemente do nível de qualidade selecionado no app — ou seja, mesmo escolhendo "Hi-Res Lossless", a saída real nunca passava de 48kHz.

Isso mudou com o **tvOS 27** (lançado em junho de 2026), que pela primeira vez permite que a Apple TV 4K (modelos 2021 e 2022) entregue Hi-Res Lossless real de até 24-bit/192kHz via HDMI, desde que o sistema de áudio conectado seja reconhecido como compatível.

## Conclusão

O comportamento observado nos dois testes confirma que:

1. A Apple TV está rodando o tvOS 27 (ou posterior)
2. Ela está entregando áudio genuinamente acima de 48kHz para conteúdo Hi-Res Lossless — não é apenas um rótulo na interface sem mudança real no sinal
3. A cadeia extrator de áudio HDMI → DAC é reconhecida pelo sistema como uma saída compatível com Hi-Res, habilitando a saída de maior resolução
4. Com o ZD3 confirma-se também o valor exato: **192kHz**, e não apenas "acima de 48kHz"

## Fontes consultadas

- Página oficial de suporte da FiiO — tabela de indicação por cor do LED do K7
- Ficha técnica oficial da Fosi Audio — especificações de tela e sample rate do ZD3
- Cobertura da imprensa sobre o tvOS 27 e os limites de áudio anteriores da Apple TV (iPhoneSoft.fr, iFun.de)

---

*Documentado em 22 de setembro de 2026.*
