# Documentação da API

Os documentos do projeto estão centralizados neste diretório.

| Documento | Conteúdo |
|---|---|
| [Geração de imagens](GENERATE_IMAGE_API.md) | `POST /generate-image`: imagem única, provedores, modelos e parâmetros |
| [Lotes de imagens em ZIP](GENERATE_IMAGE_BATCH.md) | `POST /generate-image`: lista de imagens, configurações comuns e retorno ZIP |
| [Tratamento de voz](PROCESS_VOICE_API.md) | `POST /process-voice`: silêncio inicial/final, pausas longas e redução de ruído |
| [Legendas e validação de tempos](ADD_SUBTITLES_API.md) | `POST /add-subtitles`: formato SRT, sobreposições e erros de temporização |
| [Edição de vídeo](VIDEO_EDITING_API.md) | Operações de `/video-editing/v1` e exemplos de utilização |
| [Efeitos e transições](EFFECTS_AND_TRANSITIONS.md) | Efeitos e transições disponíveis no processamento de vídeo |

Para consultar todos os endpoints registrados na aplicação em execução, acesse
`/docs` (Swagger), `/redoc` (ReDoc) ou `/openapi.json` (contrato OpenAPI).

Os comandos e caminhos de código apresentados nos documentos partem da raiz do
projeto, salvo indicação diferente.
