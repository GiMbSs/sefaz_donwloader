# Envio de NFC-e pelo navegador

Consultas NFC-e (modelo 65), manuais e agendadas, usam Chromium para preencher
o formulário oficial e acionar **Consultar**. O JavaScript do próprio portal
executa sua validação reCAPTCHA. O certificado A1 é carregado do cofre em memória,
após conferir CNPJ, validade, fingerprint e hash; a origem do certificado é
restrita a `https://www4.sefaz.pb.gov.br`.

NF-e (modelo 55) mantém o envio HTTP existente. A caixa de mensagens, os downloads,
as políticas, os períodos e os intervalos de acompanhamento usam o motor atual.
O navegador é iniciado somente durante preparação/envio de uma nova NFC-e e é
encerrado ao terminar a etapa, inclusive nas falhas. Não se mantém navegador
aberto enquanto a SEFAZ gera os anexos.

## Atualização da instalação

É necessário reconstruir a imagem: instalar somente o código na imagem antiga
não disponibiliza o Chromium. A imagem instala Playwright 1.64 e seu navegador
compatível, com bibliotecas do sistema acessíveis ao usuário não privilegiado.

```sh
docker compose up -d --build worker web scheduler
```

Para execução local fora do Docker, depois de instalar as dependências Python:

```sh
.venv/bin/python -m playwright install chromium --only-shell
```

Se faltarem bibliotecas do sistema no Linux, a instalação administrativa pode
usar `playwright install --with-deps chromium --only-shell`. No Docker essa etapa
já ocorre durante o build.

`ATF_NFCE_BROWSER_TIMEOUT_SECONDS` controla o prazo das etapas do formulário
(padrão: 120 segundos). Não altera o prazo de geração dos arquivos, que continua
controlado por `ATF_NFCE_WAIT_TIMEOUT_SECONDS`. Chamadas individuais do navegador
são limitadas também pela duração do lease, para permitir sua renovação.

## Segurança da retomada

Identificação do emitente, preenchimento de datas e seleção XML/TXT acontecem
antes da intenção persistida de envio. Depois de gravar a intenção e as barreiras
por empresa/conta, o sistema permite apenas um clique por sessão. Confirmação só
é aceita para a resposta da consulta NFC-e com os filtros efetivamente enviados
correspondentes ao pedido. CNPJ formatado pelo portal é conferido pela sua forma
normalizada.

Antes de liberar o POST do formulário, o transporte confere novamente o lease e
o cancelamento. Essa verificação também ocorre quando o botão demorou a ficar
disponível ou o JavaScript do portal adiou o envio; um pedido cancelado nesse
intervalo tem sua requisição bloqueada.

O Playwright roda em uma thread dedicada. Acesso ao banco, renovação de leases
e cancelamento continuam na thread do worker; não é necessário habilitar
`DJANGO_ALLOW_ASYNC_UNSAFE`. Senhas, PFX, cookies e tokens não são persistidos em
traces, screenshots ou logs do transporte.

- `atf_nfce_browser_unavailable`: conferir instalação do Playwright/Chromium e
  reconstruir o worker. O navegador não chegou a enviar a consulta.
- `atf_nfce_browser_timeout`: a preparação não respondeu; as tentativas existentes
  do motor continuam sem criar uma intenção fiscal antes de concluir o formulário.
- `atf_captcha_required`: o portal devolveu uma rejeição explícita, mesmo com o
  fluxo do navegador. Conferir a integração antes de repetir o pedido.
- `atf_submission_uncertain`: o clique ocorreu, mas não há confirmação segura.
  Preservar o pedido e consultar a caixa; não criar um novo envio para substituí-lo.

Depois de atualizar, pedidos rejeitados explicitamente por CAPTCHA podem usar
**Retomar pedido**. Pedidos incertos continuam conciliando o envio existente;
esta adaptação não redefine envios incertos como rejeitados.

## Escopo e limites

Esta alteração adapta **o envio NFC-e**. As pendências anteriores de correlação
de mensagens sem filtros e de armazenamento de TXT entregue sem ZIP continuam
descritas em [Validação real de 21/10/2026](VALIDACAO-REAL-ATF-2026-10-21.md).
Confirmar o envio não comprova que todo o pipeline de download esteja concluído.

## Verificação

Regressões de roteamento verificam que NF-e não inicia navegador e que NFC-e
manual/agendada usa o mesmo caminho protegido. Testes com Chromium real e
portal sintético interceptado exercitam confirmação, CNPJ com máscara, rejeição
3291, falhas após o clique, alteração de filtros, cancelamento e encerramento.

```sh
RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_nfce_browser.py -q
```

Os testes de navegador são opcionais na suíte padrão para ambientes sem o binário;
o comando acima exige Chromium instalado e não acessa a SEFAZ.

Verificação final desta alteração: 441 testes aprovados com PostgreSQL e
Chromium; 430 aprovados e 11 específicos de PostgreSQL ignorados com SQLite.
Ruff, mypy, verificações do Django e migrations passaram. A imagem Docker foi
reconstruída e iniciou/encerrou Chromium com A1 sintético como usuário `app`,
sem rede e sem volumes do cliente.

### Validação real em 21/10/2026

O motor foi executado com A1 real e banco isolado, com início e fim em
21/10/2026. A SEFAZ confirmou os seguintes envios pelo novo transporte:

| Origem | Formato | Pedido isolado | Resultado do envio |
| --- | --- | --- | --- |
| Manual | TXT | `fa1853e5-58f7-4042-97a6-d9af125f689f` | Aceito, após corrigir a identificação do CNPJ formatado |
| Manual | XML | `42682b73-de06-48eb-8b33-f5c4d58ca2ca` | Aceito |
| Agendada | XML | `267e2026-e9c4-4edf-992b-f1865fc1f037` | Aceito com a preparação anterior à intenção persistida |

Nas respostas aceitas, o formulário enviou os filtros correspondentes ao pedido
e o resultado da validação reCAPTCHA do próprio portal. O motor registrou
`submission_certainty=accepted`, entrou em espera sem erro atual e manteve
ao menos um minuto até a próxima verificação.

Os testes reais verificaram o **envio**. Os pedidos locais isolados foram
cancelados após registrar a confirmação, com auditoria e sem reenvio; as consultas
remotas podem continuar gerando anexos. Nenhum pedido ou agendamento da instalação
do cliente foi modificado. Essa validação não equivale a um teste completo de
Celery/beat nem resolve as limitações de download descritas acima.

Referências: [certificados de cliente no Playwright](https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-client-certificates),
[fluxo de botão do reCAPTCHA](https://developers.google.com/recaptcha/docs/invisible).
