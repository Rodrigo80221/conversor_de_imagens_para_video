# POST /add-subtitles — tempos de legenda

Envie video e SRT por multipart/form-data, em `video_file` e `subtitle_content`.
O SRT e texto, nao JSON: cada bloco tem numero, intervalo e conteudo.
As opcoes visuais existentes continuam disponiveis em `/docs`.

## Validacao antes da renderizacao

O endpoint rejeita com HTTP 422:

- SRT vazio, incompleto ou com timestamp invalido.
- Fim menor ou igual ao inicio.
- Blocos fora de ordem cronologica.
- Sobreposicao entre blocos de legenda sequenciais (tolerancia de 1ms).
- Legenda terminando depois do video (tolerancia de 100ms para arredondamento).

Exemplo de erro encontrado em uma gravacao:

```srt
19
00:00:09,640 --> 00:10:09,099
a
```

O tempo final e 609,099 segundos, por isso a letra continua visivel enquanto
as palavras seguintes aparecem. Para esse exemplo, o fim coerente com o inicio
da proxima palavra e `00:00:10,099`:

```srt
19
00:00:09,640 --> 00:00:10,099
a
```

Resposta de erro:

```json
{
  "detail": {
    "message": "Legenda 19: termina em 609.099s, depois do inicio da legenda 20 (10.099s). Corrija o tempo final para evitar sobreposicao.",
    "cue": 19
  }
}
```

O endpoint nao adivinha nem corrige tempos automaticamente. A origem do SRT
deve produzir os intervalos corretos. O frontend/n8n deve tratar HTTP 422 como
falha de entrada e exibir `detail.message`, em vez de armazenar a resposta como video.

A validacao no motor ocorre antes do agrupamento por `max_lines` e antes da
conversao de highlights/karaoke, evitando esconder um intervalo malformado.
Tags `<highlight>` continuam disponiveis. No modo de captions desta API, cada
bloco e sequencial; use multiplas linhas no mesmo bloco quando necessario.

Teste: `python -m unittest test_subtitle_timing -v`. Inclui regressao do timestamp
incorreto, HTTP 422 antes do render, highlights e renderizacao FFmpeg de SRT valido.
