# Plano do Clipador

## Pipeline

```
link ──► [download] áudio (m4a/opus) + chat + vídeo leve 360p (só análise)
            │
            ├─► [detect: sinais baratos] picos de áudio (RMS/LUFS) + picos de chat ──► candidatos
            │
            ├─► [transcribe] faster-whisper com timestamps por palavra
            │       • vídeo curto (< ~40 min) ou GPU: transcreve tudo
            │       • live longa em CPU: transcreve só as janelas candidatas (±90 s)
            │
            ├─► [detect: semântico] Claude avalia só os top ~30 candidatos
            │       ► score final 0–100, remove sobreposição, top N
            │       ► ajusta início (2–4 s antes do gancho) e fim (fim de frase)
            │
            ├─► [download] vídeo 1080p SÓ dos trechos (yt-dlp --download-sections)
            ├─► [layout] facecam (MediaPipe) em cima + gameplay embaixo / crop inteligente
            ├─► [captions] .ass karaokê palavra por palavra
            └─► [render] ffmpeg: H.264, libass, loudnorm -14 LUFS (2 passadas)
                    ► output/<video>/clip_XX.mp4 + report.json + report.md
```

Cache: `cache/<video_id>/<etapa>.json|wav|...`; cada etapa verifica se o seu
artefato já existe e pula.

## Fases

| Fase | Entrega | Teste |
|---|---|---|
| 1 (MVP) | link → áudio → transcrição → top 5 por áudio+texto → corte 9:16 centralizado com legenda simples, -14 LUFS, cache | vídeo real de 5–10 min |
| 2 | facecam automática (MediaPipe) + layout dividido + box manual + crop por movimento / fundo desfocado | VOD com facecam e sem facecam |
| 3 | chat (Twitch/YouTube) + Claude no score, legendas animadas caprichadas, report com 3 títulos por clipe | VOD com chat, depois live longa |

## Onde eu mudaria o pedido original (crítica)

1. **Não transcreva uma live de 6 h inteira em CPU.** `large-v3` em CPU roda perto
   de 1x tempo real ou pior — 6 h de live = 6+ h de transcrição. Ordem melhor:
   sinais baratos (chat + áudio) primeiro, depois transcrever só as janelas
   candidatas. Com GPU NVIDIA, transcrever tudo é viável (`large-v3-turbo`).
2. **Não mande a transcrição inteira para o Claude.** Mande só os ~30 melhores
   candidatos (com triagem num modelo barato). Custo cai de dólares para centavos
   por live, e a análise fica melhor porque cada janela tem contexto focado.
3. **"Só áudio primeiro" não basta para a facecam.** Detectar facecam e região de
   movimento precisa de frames. Solução: baixar também um vídeo de 360p (barato)
   só para análise; o 1080p vem depois só dos trechos.
4. **Chat da Twitch:** `chat-downloader` está pouco mantido e quebra com
   frequência. Prefiro TwitchDownloaderCLI como principal e chat-downloader como
   alternativa. No YouTube, o chat só existe em VOD de live com replay.
5. **GTA 6 / gameplay sem streamer:** sem voz e sem chat, os sinais de "momento
   viral" ficam fracos (o áudio do jogo é alto o tempo todo). Vai funcionar, mas
   a qualidade dos cortes depende de ter narração/reação. Além disso, a Rockstar
   e o Content ID são agressivos com trilha sonora do jogo — rádio do GTA costuma
   dar claim/mute.
6. **Direito de uso:** clipar lives de terceiros sem permissão pode derrubar a
   conta. Para canais alheios, o ideal é estar num programa de clipadores do
   streamer.
7. **Fonte:** "The Bold Font" não é livre para uso comercial. Padrão será
   Montserrat Black (OFL).
8. **Score 0–100 com pesos fixos** é um começo, mas os pesos certos dependem do
   streamer. O report vai guardar os sinais brutos de cada clipe, para depois
   ajustarmos os pesos com base em quais clipes performaram.

## Decisões a partir do perfil de uso

Perfil: **Windows, sem GPU (só CPU), lives longas (2 h+) da Twitch, ainda sem
chave da Anthropic.**

- **Ordem do pipeline para lives longas:** chat da Twitch + picos de áudio
  primeiro → ~30 janelas candidatas → transcrição só delas
  (`large-v3-turbo`, `int8`, CPU). Uma live de 4 h vira ~45 min de áudio
  transcrito, em vez de 4 h.
- **Chat da Twitch é o sinal principal.** Ele vira peso alto no MVP (antes
  previsto só para a Fase 3), porque sem GPU e sem Claude é o sinal mais forte
  e mais barato. Ferramenta: TwitchDownloaderCLI (tem `.exe` para Windows),
  com chat-downloader como reserva.
- **Claude é opcional:** sem `ANTHROPIC_API_KEY`, o score usa só chat + áudio +
  heurísticas de texto (palavrões, risada, "MDS", gritos) e o report sai sem
  títulos gerados. Com a chave, a Fase 3 liga sozinha.
- **Windows:** caminhos com `pathlib`, ffmpeg via `winget`, filtro de legenda
  do ffmpeg com escape de caminho do Windows (`C\:/...`), README com
  instruções em PowerShell.
- **Desenvolvimento e testes** acontecem num ambiente Linux na nuvem. Os
  comandos específicos de Windows precisam ser validados por você na sua
  máquina.
