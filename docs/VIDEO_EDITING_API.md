# Edição de vídeo — versão 1

Módulo independente em `video_editing/`, registrado em `main.py`. Prefixo:
`/video-editing/v1`. Os endpoints antigos continuam com seus contratos.

O motor implementa as operações usadas no Shorts de Paris: importação de vídeos
e fotos, inspeção e folhas de contato, cortes, enquadramento vertical com posição
ajustável, câmera lenta, zoom suave em fotos, correção de cor, títulos e nomes de
locais, cortes secos e dissolvências, som original e exportação MP4/H.264.
Não escolhe sozinho os melhores momentos nem identifica locais; o agente analisa
as prévias e fornece as decisões e os textos na receita.

## Executar

Python 3.11+, FFmpeg **6 ou superior** com libx264 e ffprobe no PATH.
Para executar somente este módulo, sem instalar os motores de IA do projeto:

```powershell
python -m pip install -r video_editing/requirements.txt
$env:VIDEO_EDITING_DATA_DIR = 'C:\dados\video-editing'
python -m uvicorn video_editing.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Na API completa, use o comando de inicialização existente de `main:app`.
O Dockerfile instala as dependências e copia as fontes do módulo. No Easypanel,
monte um volume persistente e configure `VIDEO_EDITING_DATA_DIR=/data/video-editing`.
Configure `VIDEO_EDITING_API_KEY` ao publicar e envie a chave no header
`X-Video-Editing-Key`. Ela protege **somente os novos endpoints**.

A fila desta primeira versão é local: um processo, uma renderização por vez e
até oito tarefas ativas/na fila. Use `--workers 1`; um lock impede dois processos
de usar o mesmo diretório. Resultados, mídias e metadados persistem em disco.
Após reinício, tarefas interrompidas ficam como `failed`; o cliente pode reenviar
a receita usando os mesmos IDs. Não há retomada automática nem fila distribuída.
Arquivos de trabalho são removidos ao terminar; mídias importadas e resultados
ficam disponíveis. Ainda não há expiração automática: planeje espaço no volume.

## Fluxo HTTP

| Método e endpoint | Corpo / resultado |
|---|---|
| `POST /assets` | Multipart `file`; retorna `asset_id`, duração, dimensões e áudio |
| `POST /inspect` | JSON `{"asset_ids":["..."]}`; metadados de várias mídias |
| `POST /previews` | JSON `{"asset_id":"...","times":[1,3,5]}`; JPEG com quadros e tempos |
| `GET /fonts` | Fontes efetivamente disponíveis em cada perfil |
| `POST /render` | Receita JSON; HTTP 202 com ID e URL de acompanhamento |
| `GET /jobs/{id}` | Estado, progresso, fontes usadas, avisos e erro, quando houver |
| `POST /jobs/{id}/cancel` | Solicita cancelamento, inclusive do processo FFmpeg ativo |
| `GET /jobs/{id}/result` | MP4 quando concluído; HTTP 409 enquanto indisponível |

Todas as rotas usam o prefixo `/video-editing/v1`. A documentação interativa é
servida em `/docs`. Estados: `queued`, `running`, `cancelling`, `cancelled`,
`succeeded`, `failed`. O progresso corresponde às etapas, não a uma previsão de tempo.

O upload aceita MP4, MOV, M4V, MKV, JPG, PNG, WEBP e HEIC/HEIF. Fotos são
normalizadas com orientação EXIF. Nenhum endpoint aceita caminhos locais nem URLs
arbitrárias; use os IDs retornados pelo upload. Limite padrão: 512 MB por arquivo,
configurável por `VIDEO_EDITING_MAX_UPLOAD_MB`.

## Receita mínima

```json
{
  "version": "1",
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "audio": "original",
  "typography": {"font_profile": "auto"},
  "shots": [
    {
      "asset_id": "ID_RETORNADO_PELO_UPLOAD",
      "start": 1.7,
      "duration": 3.3,
      "speed": 0.85,
      "caption": "Torre Eiffel",
      "kicker": "P A R I S  /  F R A N Ç A",
      "transition_to_next": {"type": "dissolve", "duration": 0.3}
    },
    {
      "asset_id": "ID_DA_FOTO",
      "duration": 3.1,
      "photo_zoom": 1.03,
      "caption": "Torre Eiffel"
    }
  ]
}
```

`duration` é o tempo da cena na **edição**, não no original. Uma cena de 3 s a
`speed=0.85` usa 2,55 s da fonte, a partir de `start`. O áudio acompanha a velocidade
com preservação de tom (`atempo`). Fotos e vídeos sem áudio recebem silêncio; a
ausência de áudio em um vídeo aparece nos avisos do job. Dissolvências sobrepõem
também o áudio. Microfades de 12/25 ms suavizam as bordas sonoras. `audio="mute"`
na receita remove a faixa de áudio do resultado; na cena, silencia só aquele trecho.

Cada dissolvência reduz a duração total por sua duração. O exemplo dura 6,1 s.
Tempos de cena e transição são arredondados ao quadro mais próximo (30 fps).
Transições sobrepostas que consumam uma cena inteira são recusadas.

Campos de cena adicionais:

- `crop_x` e `crop_y`: de 0 a 1; 0 = esquerda/topo, 1 = direita/base; padrão 0,5.
- `photo_zoom`: de 1 a 1,15; usado apenas nas fotos. Fotos exigem `start=0` e `speed=1`.
- `title` e `subtitle`: abertura centralizada.
- `caption` e `kicker`: identificação discreta na parte inferior.
- `closing`: frase de encerramento centralizada abaixo do meio da imagem.
- `transition_to_next.type`: `cut` (padrão) ou `dissolve`. A última cena deve usar `cut`.

As fontes são reduzidas automaticamente para acomodar o texto. Para leitura em
celular, prefira nomes curtos. Não há quebra de linha editorial automática.

A receita permite `grade` com `contrast`, `brightness`, `saturation`,
`red_shadows`, `blue_shadows`, `red_highlights`, `blue_highlights`. Os valores
padrão reproduzem os ajustes sutis usados em Paris. Para imagem neutra, use
contraste/saturação 1 e os demais 0. `fade_in=0.25`, `fade_out=0.6` e `crf=19`
são os padrões de exportação. O fade final afeta a imagem; o som mantém apenas
o microfade de borda. Esta versão aceita até 60 cenas e 180 segundos, dimensões
pares de 240 a 1920 pixels e 30 fps. Material HDR é recusado explicitamente:
esta versão trabalha com SDR, como os vídeos selecionados de Paris.

## Fontes

- `auto`: Baskerville (Baskerville Old Face, `BASKVILL.TTF`) e Segoe UI, se ambas estiverem instaladas no Windows;
  senão, **Libre Baskerville + Source Sans 3**, incluídas no repositório.
- `original`: exige as fontes da edição original; retorna erro se indisponíveis.
- `open`: sempre usa as duas fontes abertas incluídas, inclusive no Windows.

As alternativas abertas são visualmente próximas, **não idênticas** às originais.
`GET /fonts` e o resultado do job informam as famílias usadas. Em outro ambiente,
fontes próprias podem ser indicadas por `VIDEO_EDITING_SERIF_FONT` e
`VIDEO_EDITING_SANS_FONT`, apontando para arquivos TTF/OTF acessíveis ao servidor.
Baskerville/Segoe UI do Windows não foram copiadas ou redistribuídas. Para usá-las
na nuvem, disponibilize arquivos com licença adequada ao ambiente.

Fontes abertas, licenças OFL e URLs de origem estão em `video_editing/fonts/`.
`typography.caption_size`, `title_size` e `small_size` usam a referência de 1080 px
de largura e são escalados com a saída.

## Reproduzir a seleção de Paris

O template `examples/paris_edit.template.json` guarda os 18 arquivos, cortes,
velocidades, textos e quatro dissolvências: 51,3 segundos. Ele usa o campo `source`
para nomes de arquivo e deve ser resolvido pelo cliente de exemplo; **não é o
corpo direto do endpoint**. O cliente substitui `source` por `asset_id` após upload.

```powershell
python examples/render_paris.py --media-dir 'C:\Users\rodri\Downloads\chegada paris' --output 'C:\videos\paris.mp4'
```

Use `--preview` para 360×640, `--font-profile open` para conferir as fontes do
servidor, ou `--api-url https://seu-servidor` para outra instalação. O cliente usa
`requests` (já está nas dependências gerais) e grava também a receita resolvida.
Cada execução importa os arquivos novamente; clientes de produção devem reutilizar
os IDs quando possível. As mídias pessoais não estão incluídas no repositório.

## Testes

```powershell
python -m pip install httpx
python -m unittest test_video_editing -v
```

Os testes geram mídias sintéticas e executam FFmpeg de verdade: orientação de
celular, dissolvência, câmera lenta, áudio antes/depois da foto, silêncio na foto,
exportação muda, prévias, validação, autenticação, cancelamento e recuperação após
reinício. Não usam créditos de APIs nem arquivos pessoais.

Variáveis opcionais `VIDEO_EDITING_FFMPEG` e `VIDEO_EDITING_FFPROBE` selecionam os
binários. Para escalar futuramente, a fila pode ser substituída por workers externos
sem mudar a receita de edição.

## Revisão da edição de Paris

A sequência inicial é: voo, asa do avião na chegada e foto do casal. O template
usa `font_profile="original"` para preservar Baskerville Old Face e Segoe UI.
O cliente respeita esse perfil; use `--font-profile open` somente se quiser as
alternativas abertas. A saída principal é Full HD (1080×1920); `--preview` é
apenas uma versão reduzida para revisão e não deve ser usada para avaliar a
nitidez final das letras pequenas.
