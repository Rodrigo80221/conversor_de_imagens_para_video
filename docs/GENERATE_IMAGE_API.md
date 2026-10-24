# POST /generate-image

Endpoint JSON que gera **uma imagem ou um lote em ZIP**. Disponivel no Swagger `/docs`.
Centraliza selecao do gerador, referencias, prompt de capa e HTML.
Retorna a imagem; armazenamento e responsabilidade do cliente/n8n. Os endpoints existentes continuam disponiveis.

## Configuracao no Easypanel

Variaveis de ambiente (somente para os caminhos usados):

- `GEMINI_API_KEY`: chave Google AI Studio.
- `OPENAI_API_KEY`: chave da API OpenAI.
- `COMFYUI_BASE_URL`: opcional; padrao `https://comfyui.progridai.com.br`.
- `COMFYUI_TIMEOUT_SECONDS`: espera total do job local; padrao 300, limite 30-900.
- `COMFYUI_MODEL`, `COMFYUI_CLIP_MODEL`, `COMFYUI_VAE_MODEL`: opcionais; os
  padroes correspondem ao workflow Z-Image-Turbo instalado.
- `COMFYUI_ACCESS_CLIENT_ID` e `COMFYUI_ACCESS_CLIENT_SECRET`: opcionais e devem
  ser configuradas juntas caso o endereco seja protegido por Cloudflare Access.
- `CHROME_BIN`: ja configurado no Dockerfile para renderizar HTML.

Tambem e possivel enviar `api_key` no JSON. Eles prevalecem
sobre o ambiente. Nao salve chaves em exemplos ou no repositorio.
O endpoint usa Pydantic 2, FastAPI, requests, Pillow e o html2image existente.

## Escolha do gerador

| company | technology | model |
|---|---|---|
| `google` | `gemini` | padrao `gemini-3-pro-image-preview`, como no fluxo original |
| `openai` | `chatgpt` ou `openai` | padrao `gpt-image-1`; aceita modelos GPT Image compativeis |
| `local` | `comfyui` | padrao `z_image_turbo_bf16.safetensors` |
| `local` | `html` | omitir |

`company` e opcional, inferida de `technology`; combinacoes divergentes retornam 422.
`cloud` nao identifica uma API concreta. Novos provedores exigem um adaptador em
`PROVIDERS` e inclusao na validacao de `technology/company`. Nenhum modelo e
substituido silenciosamente e nenhuma tentativa paga e repetida automaticamente.
A disponibilidade e os parametros aceitos pelo modelo dependem da conta/provedor.

## Gemini: imagem normal/capa

```json
{
  "company": "google",
  "technology": "gemini",
  "model": "gemini-3-pro-image-preview",
  "prompt": "Uma nutricionista em uma cozinha moderna, segurando uma cesta de vegetais",
  "prompt_style": "reel_cover",
  "on_screen_text": "3 habitos para uma vida melhor",
  "aspect_ratio": "9:16",
  "image_size": "2K",
  "response_format": "binary"
}
```

`prompt_style=raw` (padrao) preserva o prompt fornecido; `reel_cover` acrescenta
orientacoes visuais de capa. `on_screen_text` acrescenta instrucoes de tipografia.
`image_size` e opcional (`1K`, `2K`, `4K`); use apenas em modelos que a suportam.

## Referencia de ator

Adicione `reference_images` ao JSON anterior. Cada item deve conter UMA fonte:

```json
{
  "reference_images": [
    {"url": "https://seu-dominio.com/ator.png"}
  ]
}
```

Alternativa: `{"base64":"..."}` (tambem aceita data URI).
Referencias devem ser resolvidas pelo cliente antes da chamada.
Aceita ate 4 referencias PNG/JPEG/WebP, 15 MiB e 25 megapixels por imagem.
URLs devem ser publicas, diretas e sem redirecionamentos; nenhuma credencial e
enviada no download. Gemini recebe inlineData; OpenAI usa a rota de edicao.

## OpenAI

```json
{
  "company": "openai",
  "technology": "chatgpt",
  "model": "gpt-image-1",
  "prompt": "Capa cinematografica sobre alimentacao saudavel",
  "size": "1024x1536",
  "quality": "high",
  "response_format": "base64"
}
```

`size` padrao `auto`; os tamanhos aceitos dependem do modelo. `quality`:
`auto`, `low`, `medium`, `high`. `aspect_ratio` entra como orientacao no prompt
da OpenAI; as dimensoes reais sao controladas por `size` e pelo modelo.
Nao ha corte/redimensionamento automatico para 9:16.

## ComfyUI local (Z-Image-Turbo)

```json
{
  "company": "local",
  "technology": "comfyui",
  "prompt": "Retrato cinematografico de uma nutricionista em uma cozinha moderna",
  "aspect_ratio": "9:16",
  "seed": 42,
  "steps": 8,
  "response_format": "binary"
}
```

O servidor enfileira o workflow oficial Z-Image-Turbo no ComfyUI, aguarda o job
e baixa a imagem temporaria. `seed` e `steps` sao opcionais e exclusivos do
ComfyUI; o padrao e seed aleatoria e 8 passos. `size` pode ser `auto` ou uma
dimensao explicita, por exemplo `768x1344`. Dimensoes explicitas devem ser
multiplos de 16, entre 256 e 2048. Com `size=auto`, a API calcula dimensoes a
partir de `aspect_ratio`.

O workflow instalado e somente texto-para-imagem e rejeita `reference_images`.
O computador, o ComfyUI na porta 8188 e o Cloudflare Tunnel precisam estar
online. Nao envie `api_key`: esse provedor usa a URL configurada no servidor.

## HTML/CSS existente

```json
{
  "company": "local",
  "technology": "html",
  "html": "<main><h1>Alimentacao saudavel</h1></main>",
  "css": "body{background:#153a29;color:white}main{padding:80px}h1{font:800 96px Inter}",
  "width": 1080,
  "height": 1920,
  "response_format": "binary"
}
```

Recebe HTML/CSS prontos, como o fluxo atual. Reutiliza
`html_img_engine.generate_image_from_html`, com limpeza de temporarios.
Nao gera HTML a partir de prompt. Envie somente HTML confiavel, como no endpoint
existente. Dimensoes de 64 a 4096 pixels por eixo.

## Armazenamento externo

O endpoint nao recebe token, tabela ou registro de banco de dados e nao faz upload.
Use `binary` para receber o arquivo ou `base64` para receber JSON com a imagem.
O n8n deve buscar a URL do ator e salvar o resultado em nodes separados.
O antigo contrato `response_format=baserow` e campos `baserow`/`baserow_token`
agora retorna 422. Use o fluxo V3 com esta versao da API.

## Respostas e erros

- `binary` (padrao): bytes da imagem, MIME detectado e nome de download.
- `base64`: JSON com metadados e `base64` (sem prefixo data URI).
- 422: parametros/credenciais ausentes, combinacao invalida ou referencia invalida.
- 502: falha no provedor, fila/download do ComfyUI ou resposta sem imagem.
- 504: timeout na chamada de geracao ou aguardando o job do ComfyUI.
- 500: falha do renderizador HTML.

Chamadas externas de geracao: timeout de conexao 15s e leitura 180s.
Configure o timeout do proxy/n8n para o tempo total de todas as etapas.
Este endpoint e sincrono; nao ha fila nem idempotencia. Evite retry automatico
de geracao no n8n apos timeout. Nao registra nem devolve chaves em erros externos.

## Mapeamento futuro do n8n

- `structure.scenes[0].scene_image_description` -> `prompt`.
- `structure.scenes[0].on_screen_text` -> `on_screen_text`.
- `actor_ref=true` -> preencher `reference_images` e usar `prompt_style=raw`.
- `generation_technology=html` -> `technology=html`, `Images[0].html/css`, `width/height`.
- `generation_technology=comfyui` -> `technology=comfyui`; nao enviar chave ou referencia.
- Imagem sem ator -> `prompt_style=reel_cover`.
- ID de historico -> node Baserow no n8n, fora da API.

As strings JSON produzidas por agentes devem ser parseadas antes de mapear os
campos. A API recebe parametros estruturados; nao depende de nomes dos nodes
Robin/Joyce/Will nem consulta o historico inteiro. O fluxo n8n V3 resolve referencias e persistencia em nodes separados.

## Testes

`python -m unittest test_image_api test_image_batch -v` (precisa de httpx no ambiente de testes).
Simula as APIs externas e o renderizador, sem consumo de creditos nem alteracao
do Baserow. Validacao real de modelos exige as credenciais e uma chamada real.

Referencias dos contratos:
- https://ai.google.dev/gemini-api/docs/generate-content/image-generation
- https://developers.openai.com/api/reference/resources/images/methods/generate
- https://developers.openai.com/api/reference/resources/images/methods/edit
