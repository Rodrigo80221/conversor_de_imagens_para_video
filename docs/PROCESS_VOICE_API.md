# POST /process-voice

Trata uma gravacao de voz do frontend do Nina Labs com FFmpeg local, sem chave
de provedor e sem custo de API de IA. Retorna o arquivo de audio tratado.

## Requisicao

Envie `multipart/form-data` com `file` e campos separados. Nao envie JSON/base64.
O navegador pode enviar diretamente o Blob produzido por MediaRecorder.

| Propriedade | Tipo | Padrao | Efeito |
|---|---|---|---|
| `file` | arquivo | obrigatorio | Gravacao de uma pessoa falando |
| `trim_start` | boolean | `true` | Corta o silencio antes da fala |
| `trim_end` | boolean | `true` | Corta o silencio depois da fala |
| `shorten_pauses` | boolean | `true` | Encurta pausas longas entre trechos |
| `reduce_noise` | boolean | `true` | Reduz ruido ambiente com filtro espectral |
| `silence_threshold_db` | numero | `-35` | Volume abaixo do qual e considerado silencio, entre -80 e -15 dB |
| `min_pause_seconds` | numero | `1.0` | Pausa interna minima para encurtar, entre 0.2 e 30 segundos |
| `keep_pause_seconds` | numero | `0.25` | Tempo de pausa que permanece, entre 0.05 e 5 segundos |
| `edge_padding_seconds` | numero | `0.05` | Margem antes/depois da fala nas bordas, entre 0 e 0.5 segundo |
| `noise_reduction_db` | numero | `12` | Intensidade da reducao de ruido, entre 1 e 30 dB |
| `noise_floor_db` | numero | `-40` | Piso inicial do ruido para o filtro, entre -80 e -20 dB |
| `output_format` | string | `wav` | `wav`, `mp3` ou `webm` |

Use as strings `"true"`/`"false"` nos campos do FormData; nao use apenas a presenca
do campo. Todas as quatro operacoes sao independentes. Exemplo: manter as bordas
e reduzir somente pausas internas usando trim_start=false, trim_end=false,
shorten_pauses=true. Todos false preservam o tempo e desativam o tratamento;
ainda ocorre conversao para o formato de saida.

`keep_pause_seconds` deve ser menor que `min_pause_seconds`.
Pausas internas menores que o limite permanecem. A pausa mantida e dividida entre
o final de um trecho e o inicio do seguinte. A margem de 50ms nas bordas evita
comecar/terminar exatamente no limite da palavra; ajuste para 0 para corte sem margem.

## Exemplo para o frontend

```javascript
// audioBlob: Blob final capturado pelo MediaRecorder.
// apiBaseUrl: URL da API configurada no frontend.
const form = new FormData();
form.append('file', audioBlob, 'gravacao.webm');
form.append('trim_start', 'true');
form.append('trim_end', 'true');
form.append('shorten_pauses', 'true');
form.append('reduce_noise', 'true');
form.append('min_pause_seconds', '1.0');
form.append('keep_pause_seconds', '0.25');
form.append('output_format', 'wav');

const response = await fetch(`${apiBaseUrl}/process-voice`, {
  method: 'POST',
  body: form
});
// Nao defina Content-Type manualmente: o navegador inclui o boundary multipart.
if (!response.ok) {
  const error = await response.json();
  throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));
}
const treatedAudio = await response.blob();
const playbackUrl = URL.createObjectURL(treatedAudio);
audioPlayer.src = playbackUrl;
// URL.revokeObjectURL(playbackUrl) quando o player/arquivo nao for mais usado.
```

Use os booleans do estado dos seus quatro controles para preencher cada campo:
`form.append('trim_start', String(config.trim_start))`, por exemplo.
O Nina Labs pode reproduzir, baixar ou salvar o Blob retornado como preferir.
O endpoint `/process-voice` permite CORS sem credenciais para o frontend web.
Por padrao aceita qualquer origem; para restringir, configure `VOICE_ALLOWED_ORIGINS`
com as origens separadas por virgula (incluindo esquema e porta, quando houver).
O middleware se aplica somente a este endpoint e expoe os cabecalhos de duracao
e cortes. Publique a versao com `voice_cors.py` para ativar no servidor.

## Entrada, saida e execucao

- Aceita formatos decodificaveis pelo FFmpeg, incluindo WebM/Opus (MediaRecorder),
  OGG/Opus, WAV, MP3 e M4A/AAC. O conteudo e inspecionado; extensao/MIME nao sao confiados.
- Ate 100 MiB por arquivo e 30 minutos de audio, mono/estereo e frequencia de 8 a 96 kHz.
- Mantem a frequencia e os canais no WAV; MP3/Opus podem ajustar a frequencia conforme o codec.
- Usa o primeiro stream de audio e ignora eventual video.
- A reducao de ruido e aplicada antes da deteccao/corte de silencio.
- Deteccao por volume, sem reconhecimento/transcricao de fala. Voz baixa pode
  ser considerada silencio se o limiar estiver alto. Um limiar mais negativo,
  por exemplo -45, preserva sons mais baixos, mas pode manter mais ruido.
- A reducao espectral ajuda com chiado, ventilador e ruido continuo. Nao garante
  eliminar musica, outras pessoas falando, eco ou ruido forte junto com a voz.
  Intensidade excessiva pode alterar a voz; ajuste os parametros e confira o resultado.
- Se nao houver trecho acima do limiar e cortes de borda estiverem ativos, retorna
  422 explicito em vez de entregar arquivo vazio. Com cortes de borda desligados,
  gravacao inteiramente silenciosa e preservada, mesmo com shorten_pauses=true.
- Resposta binaria com Content-Disposition e MIME `audio/wav`, `audio/mpeg` ou `audio/webm`.
- Cabecalhos: `X-Audio-Input-Duration`, `X-Audio-Output-Duration`,
  `X-Audio-Removed-Seconds` (segundos) e `X-Audio-Cuts` (quantidade de cortes).
  Duracoes correspondem ao PCM processado; formatos com perdas podem ter padding do codec.
- Temporarios removidos apos o download ou em caso de erro.
- 422: parametros/audio invalidos ou nenhum trecho detectado; 413: tamanho/duracao;
  503: FFmpeg/ffprobe ausente; 504: tempo limite de uma etapa externa (180 segundos).
- Rota sincrona executada no thread pool do FastAPI, sem fila. O timeout total do
  frontend/proxy precisa permitir a soma das etapas de decodificacao, deteccao e codificacao.

## Deploy e testes

O Dockerfile do projeto ja instala FFmpeg, e requirements.txt ja inclui
`python-multipart`. Basta publicar a versao atualizada. Endpoint disponivel em `/docs`.

Teste local: `python -m unittest test_voice_api -v` (FFmpeg, ffprobe e httpx no ambiente).
Os testes geram audio sintetico para medir cortes, detectar perda indevida de
trechos, verificar reducao de ruido e exercitar formatos de navegadores e controles.
Uma gravacao real do microfone ainda deve ser avaliada para ajustar limiar e intensidade.

Referencia do processamento: https://www.ffmpeg.org/ffmpeg-filters.html
