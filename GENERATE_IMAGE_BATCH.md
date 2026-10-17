# Lote de imagens no mesmo POST /generate-image

O contrato de imagem unica continua igual: envie `prompt` ou `html` na raiz e
receba a imagem em `binary` ou `base64`. O fluxo V3 existente continua funcionando.
Os endpoints antigos `/create-images` e `/batch-html-to-image` nao foram alterados.

Para gerar um ZIP, envie `images`, com uma entrada por imagem. Cada entrada aceita
os mesmos parametros de geracao do modo individual, exceto `response_format`.
`defaults` define valores compartilhados; valores de cada item prevalecem.
Credenciais podem vir de `api_key` em defaults/item ou das variaveis de ambiente.

## Exemplo: duas cenas com Gemini

```json
{
  "response_format": "zip",
  "defaults": {
    "company": "google",
    "technology": "gemini",
    "model": "gemini-3-pro-image-preview",
    "aspect_ratio": "9:16",
    "image_size": "2K"
  },
  "images": [
    {
      "prompt": "Uma nutricionista apresentando vegetais frescos",
      "on_screen_text": "Escolha alimentos frescos",
      "reference_images": [{"url": "https://seu-dominio.com/ator.png"}]
    },
    {
      "prompt": "Uma mesa com uma refeicao equilibrada",
      "on_screen_text": "Monte seu prato"
    }
  ]
}
```

Resposta: `application/zip`, download `generated_images.zip`, contendo
`image_1.png`, `image_2.png`, etc. A extensao reflete o formato efetivo da imagem
(`.png`, `.jpg` ou `.webp`). A ordem e a mesma da lista enviada.
`X-Image-Count` informa a quantidade de imagens. Mesmo um lote de uma imagem
retorna ZIP, sem mudar automaticamente para arquivo de imagem.

## Capa e primeira cena

O padrao e `skip_first: false`: gera todos os itens recebidos.
Use `skip_first: true` quando enviar a capa como primeira entrada e quiser gerar
somente o restante, como no fluxo enviado. A numeracao do ZIP comeca em 1 apos
o descarte. Se ja enviar somente as cenas restantes, mantenha false.

A selecao e por posicao, nao pelo campo `scene_number`. Nenhuma capa e ignorada
implicitamente. Lote vazio (inclusive depois do descarte) retorna 422.

## Lote HTML

```json
{
  "defaults": {"technology": "html", "width": 1080, "height": 1920},
  "skip_first": true,
  "images": [
    {"html": "<h1>Capa ja criada</h1>"},
    {"html": "<h1>Primeira cena</h1>", "css": "h1{color:blue}"},
    {"html": "<h1>Segunda cena</h1>", "css": "h1{color:green}"}
  ]
}
```

`response_format` pode ser omitido no lote: o padrao e `zip`.

## Lote misto

```json
{
  "images": [
    {"technology": "gemini", "model": "gemini-3-pro-image-preview", "prompt": "Uma floresta"},
    {"technology": "chatgpt", "model": "gpt-image-1", "prompt": "Uma praia", "size": "1024x1536"},
    {"technology": "html", "html": "<h1>Conclusao</h1>", "css": "h1{font-size:96px}"}
  ]
}
```

Nesse exemplo, configure GEMINI_API_KEY e OPENAI_API_KEY no servidor, ou envie
`api_key` em cada item. Nao compartilhe uma chave Google em defaults se houver
itens OpenAI sem sua propria chave. Em lotes mistos, prefira informar empresa,
modelo e parametros especificos em cada item.

A heranca e literal: `reference_images: []` remove referencias comuns;
`model: null`, `company: null` e `image_size: null` removem esses valores de defaults.
HTML nao aceita prompt, modelo ou referencias: evite herdar esses campos ou
limpe-os no item. Nenhum parametro incompatível e descartado silenciosamente.

## Adaptacao futura do fluxo enviado

- `structure.scenes[].scene_image_description` -> `images[].prompt`.
- `on_screen_text` -> `images[].on_screen_text`.
- Ator: o n8n resolve o ID no Baserow e fornece a URL em `reference_images`
  somente nos itens correspondentes (nao em todas as cenas).
- HTML salvo em `Images[]` -> `images[]`, com `technology=html`, html/css e dimensoes.
- Capa: excluir antes de enviar ou usar `skip_first=true`, nunca ambos.
- Receber o ZIP como arquivo e fazer upload/atualizacao no Baserow pelo n8n.

O endpoint recebe dados estruturados. Nao recebe o documento bruto de
DiretorConteudo/SecretariaJoyce nem tokens/IDs do Baserow. O novo JSON do n8n
sera tratado em outra etapa, conforme solicitado.

## Limites, erros e execucao

- De 1 a 20 itens por requisicao, incluindo a capa se enviada.
- Geracao sequencial: uma chamada de geracao por item, sem retry automatico.
- Ate 200 MiB de imagens no ZIP; referencias e imagens mantêm os limites do modo individual.
- Estrutura de todos os itens e validada antes da geracao. Credenciais ausentes
  e referencias base64 invalidas tambem sao detectadas antes de gerar o primeiro item.
- URLs sao baixadas quando seu item e processado; falhas remotas ainda podem
  acontecer depois que itens anteriores foram gerados.
- Se um item falhar, o lote para e retorna erro HTTP, sem ZIP parcial. `detail.index`
  identifica a posicao original (base zero), `detail.completed` conta itens concluidos,
  e `detail.archive_returned=false` indica que nenhum ZIP foi entregue.
- Itens anteriores a uma falha podem ter gerado custo. Nao ha rollback de cobranca,
  retomada, fila ou idempotencia; repetir o lote gera tudo novamente.
- O ZIP temporario e removido apos a resposta ou em caso de erro.
- Ajuste os timeouts do n8n/proxy ao tempo total do lote. O limite por chamada
  externa continua sendo 15s de conexao e 180s de leitura.

Opcionalmente envie `include_manifest: true` para incluir `manifest.json` com
nomes, indices de origem, provedores/modelos e dimensoes. O padrao false deixa
somente as imagens no ZIP. O manifesto nao inclui prompts, chaves ou referencias.

Testes: `python -m unittest test_image_api test_image_batch -v`.
