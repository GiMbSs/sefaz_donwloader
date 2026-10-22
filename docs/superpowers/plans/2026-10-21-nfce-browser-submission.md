# NFC-e: envio pelo navegador oficial

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enviar consultas NFC-e pelo formulário oficial com A1 e JavaScript do
portal, tanto para pedidos manuais quanto agendados, preservando o envio HTTP
de NF-e.

**Architecture:** O cliente HTTP mantém autenticação, caixa e downloads. Somente
`lookup_issuer(..., document_model="65")` prepara uma sessão Chromium isolada;
`submit_query` do modelo 65 aciona o botão oficial nessa sessão. Preparação
acontece antes da intenção persistida; o clique fiscal ocorre depois dela.
Uma resposta não confirmada após o clique continua incerta e não é reenviada.

**Tech Stack:** Django/Celery existentes; Playwright Python e Chromium; A1/PFX
verificado e entregue em memória à origem HTTPS fixa da SEFAZ-PB.

**Spec:** Pedido do usuário nesta sessão: adaptar apenas NFC-e; NF-e não
apresentou a rejeição. Evidência: `docs/VALIDACAO-REAL-ATF-2026-10-21.md`.

## Global Constraints

- Nenhuma mudança no envio HTTP de NF-e ou nos períodos dos pedidos.
- Usar somente o fluxo original do portal, inclusive validação do botão.
- Nenhuma chave, senha, cookie ou resposta privada em logs, traces ou screenshots.
- A1 deve passar pelas conferências existentes de CNPJ, fingerprint, hash e validade.
- Navegador apenas para envio NFC-e; consultas de acompanhamento usam HTTP.
- Falhas antes do clique não devem criar novas submissões remotas; depois do
  clique, ausência de confirmação nunca autoriza repetir o POST automaticamente.
- Manter barreiras por conta/empresa, cancelamento, espera mínima e reagendamentos.
- A adaptação do envio não redefine as regras de conciliação ou o armazenamento
  de TXT direto, pendências identificadas no relatório anterior.

## Review Focus

- Navegador ausente ou falha de A1 durante preparação não deixa intenção fiscal.
- Cancelamento/perda de lease impede o clique e interrompe a espera.
- POST com erro, redirecionamento ou timeout não dispara um novo clique nem
  uma nova chamada automática a submit_query.
- Confirmação só vale para resposta POST do endpoint NFC-e com ação consultar.
- Sessões e processos são encerrados mesmo quando a confirmação não chega.

### Task 1: Transporte NFC-e e integração seletiva

**Files:** `apps/fiscal/atf/nfce_browser.py`, `tls.py`, `client.py`,
`errors.py`, `diagnostics.py`; `tests/test_nfce_browser.py`,
`tests/test_atf_tls.py`.

**Interfaces:** `load_verified_a1(certificate_id)` fornece PFX/senha/CNPJ apenas
em memória; `open_nfce_query(certificate_id, heartbeat=...)` produz um objeto
com `lookup_issuer(cnpj)` e `submit_query(issuer, period, format)`.
`AtfPbClient` recebe uma fábrica preguiçosa desse objeto no contexto de produção.

- [x] Escrever regressões de seleção exclusiva do modelo 65, validação do A1,
  preparação, confirmação, rejeição 3291, timeout após clique, cancelamento e limpeza.
- [x] Rodar as regressões e observar falha pela implementação ausente.
- [x] Implementar A1 compartilhado verificado e transporte do navegador, sem
  alterar os métodos HTTP usados por NF-e e pela caixa de mensagens.
- [x] Rodar testes focados, incluindo Chromium real com portal sintético
  interceptado, sem rede externa e sem dados do cliente.

### Task 2: Instalação, operação e verificação

**Files:** `pyproject.toml`, `requirements.txt`, `Dockerfile`,
`docker-compose.yml`, `.env.example`, `config/settings/base.py`,
`docs/OPERACAO-ATF-PB.md`.

**Interfaces:** A imagem contém versão compatível do Playwright e Chromium;
o usuário não privilegiado do worker consegue iniciar e encerrar o navegador.

- [x] Instalar dependência alinhada nas duas declarações e Chromium na imagem.
- [x] Documentar rebuild do worker, diagnóstico de instalação e retomada dos
  pedidos anteriormente rejeitados por CAPTCHA, sem repetir envios incertos.
- [x] Verificar suíte completa, tipos, lint, migrations e build da imagem.
- [x] Validar o transporte contra o portal real com A1 em ambiente isolado,
  limitando qualquer nova consulta ao dia local corrente e registrando o resultado.
- [x] Fazer uma revisão independente das mudanças, corrigir achados relevantes
  com regressões e registrar evidências sem alegar entrega completa de NFC-e.

## Resultado

Implementação e revisão concluídas na branch local `fix/nfce-browser-submission`.
Suíte final com Chromium: 441 testes aprovados em PostgreSQL; em SQLite,
430 aprovados e 11 específicos de locks ignorados. Ruff, mypy (91 arquivos),
`manage.py check`, migrations e verificação de whitespace sem falhas.
Imagem reconstruída e Chromium iniciado/encerrado como usuário `app`, sem rede,
com certificado sintético. A revisão identificou um caso de cancelamento durante
a espera pelo botão; regressão reproduziu o envio indevido e passou após proteger
a saída do POST com nova conferência de lease/cancelamento.

Envios reais manuais TXT/XML e agendado XML aceitos em banco isolado; evidências
e limites em [Envio NFC-e pelo navegador](../../ENVIO-NFCE-NAVEGADOR.md).
Sem commit ou alteração de serviços/dados da instalação do cliente.
