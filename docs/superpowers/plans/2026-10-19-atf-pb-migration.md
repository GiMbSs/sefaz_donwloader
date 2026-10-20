# Migração para downloads ATF-PB — Implementation Plan

## Revisão autorizada em 20/10/2026 — prevalece sobre o plano original

O usuário autorizou continuar e dispensou a preservação de dados gerados pelo motor anterior. As exigências abaixo substituem qualquer trecho conflitante deste documento e da especificação original.

- Retirar a exportação/restauração e a consulta do histórico legado do escopo e dos gates das migrations. Remover os modelos antigos por migrations novas; não resetar cadastros, usuários, políticas programáveis ou certificados. Arquivos antigos não serão apagados por esta implementação.
- Verificar o XML no download e extrair `ide/nNF`, validando sua correspondência com a chave de acesso. Exibir o número da nota na consulta por empresa; eventos são distintos de notas. Validação estrutural/identidade não equivale à validação criptográfica da assinatura ou a XSD completo.
- Armazenar ZIPs e conteúdos em `escritorios/<identificador>/empresas/<CNPJ>/XML|TXT/AAAA/MM/DD/`, com a data original da solicitação no fuso configurado e identificadores adicionais para evitar colisão entre pedidos/partes. O prefixo de escritório mantém isolamento quando o mesmo CNPJ pertence a dois tenants. Preservar TXT e ZIP originais.
- Tratar lentidão com timeouts configuráveis, renovação de leases e execução em etapas sem bloquear worker com sleeps. Retentar somente erros transitórios, respeitando Retry-After e evitando reenviar POST de resultado incerto.
- Ao esgotar as tentativas curtas de uma tarefa agendada, persistir nova tentativa para o mesmo período/parte após intervalo maior, sem depender da próxima ocorrência regular. Verificar política/empresa ainda ativas; tarefas manuais não entram nessa repetição automática longa. Manter tentativas auditáveis, sem criar pedidos duplicados. Submissão incerta continua em conciliação, nunca é reenviada automaticamente.
- Tela específica de cada empresa deve listar todos os pedidos automáticos e manuais, com período, origem, estado, datas, próxima tentativa e usuário solicitante manual. Pedidos manuais exigem data inicial e final.

### Sequência revisada restante

1. Testar e implementar número da nota, estrutura de armazenamento e reagendamento longo; conferir histórico por empresa e inputs de período.
2. Substituir a tarefa 10 por retirada do subsistema de preservação do legado ainda incompleto. Tarefas 11–12: retirar tabelas e funcionalidades exclusivas SOAP/NSU, adaptar acessos e testes úteis ao domínio ATF.
3. Concluir configuração, diagnóstico, documentação operacional e testes offline/concorrência/instalação/atualização; revisão final independente. Não executar corte em base real nesta implementação.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task; use superpowers:subagent-driven-development only if the user chooses delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir a distribuição nacional DF-e por downloads de NF-e emitidas na SEFAZ-PB, em ZIP de XML/TXT, mantendo e adaptando o download automático programável e removendo NSU e funcionalidades exclusivas da integração anterior sem perder cadastros, certificados ou histórico.

**Architecture:** Manter a aplicação Django e implementar um cliente HTTP ATF-PB autenticado com A1 individual, coordenado por etapas Celery persistidas. Separar pedidos, partes, arquivos, notas e eventos; preservar a origem dos dados legados em snapshots consultáveis. Fazer a troca em releases de expansão, corte e limpeza, com restauração e reconciliação verificadas antes das remoções de tabelas.

**Tech Stack:** Python >=3.13,<3.14; Django >=6.0,<6.1; Celery/Redis; PostgreSQL 17; requests; cryptography; lxml; pytest/pytest-django; Docker Compose. Manter os intervalos atuais de dependências; nenhuma biblioteca de navegador é necessária para o caminho inicial.

**Spec:** [2026-10-19-atf-pb-downloads-design.md](../specs/2026-10-19-atf-pb-downloads-design.md).

## Global Constraints

- SEFAZ-PB, A1 por empresa, notas emitidas, XML e TXT, entrega por ZIP e ausência de NSU.
- Nesta entrega, consultar NF-e modelo 55 como emitente.
- Não resetar banco, reescrever migrations aplicadas ou apagar arquivos de clientes.
- Cookies ficam em memória e não entram em banco, Redis, resultados Celery ou logs.
- Não manter transação ou row lock durante tráfego HTTP.
- Não repetir automaticamente POST de submissão.
- XML e TXT de uma mesma parte temporal são solicitações distintas.
- Preservar o download automático programável, com modo, frequência, horário, fuso, dias configurados e estado ativo/inativo das políticas existentes.
- O default manual e sem agendamento vale apenas para cadastros novos; a migração não desativa políticas existentes nem exige reativação manual após o corte.
- Preservar o TXT original.
- Testes automáticos são offline e sintéticos. Testes de locks precisam de PostgreSQL real.
- Qualquer escolha adicional neste plano é proposta técnica, não preferência previamente atribuída ao cliente.

## Review Focus

1. POST aceito no ATF seguido de timeout/morte do worker: conciliar antes de novo envio, mesmo com lease expirado; testes nas tarefas 5 e 7.
2. Caixa compartilhada, paginação e dois resultados do mesmo período: associação exclusiva e ambiguidade explícita, sem escolher a mensagem mais recente; tarefas 4, 5 e 9.
3. ZIP íntegro contendo eventos de destinatário, XML desconhecido ou arquivo de outra empresa: separar evento/nota, preservar evidência e impedir liberação incorreta; tarefa 6.
4. Banco antigo, caminhos Windows e UUID do cofre divergente: preservar dados e corrigir apenas correspondência criptograficamente comprovada; tarefas 3, 10 e 11.
5. Worker duplicado, certificado renovado e sessão expirada durante anexo: não misturar CNPJ/conta/anexo nem perder progresso; tarefas 4, 5, 7 e 14.

---

## 1. Sequência de entrega e decisões de escopo

**Recomendação: refatoração com substituição do núcleo fiscal, não reinício do projeto.** O ganho real está em reaproveitar autorização por escritório, cadastro, upload A1, cofre, auditoria, storage e infraestrutura. A integração antiga precisa sair; manter dois motores de coleta ativos criaria ambiguidade operacional desnecessária.

| Release | Entrega verificável | Condição para avançar |
| --- | --- | --- |
| A — expansão | Chamadas nacionais desativadas; domínio novo, cliente ATF, tarefas e interface novos; tabelas antigas preservadas; nomes antigos de tarefas reconhecidos como desativados | Suite offline, locks PostgreSQL e fluxo novo comprovados; backup e exportação conferidos |
| B — corte | UI/rotas usam o ATF; histórico legado acessível; modelos/tabelas antigos retirados por migrations novas | Manifesto legado completo, arquivos reconciliados e ensaio de restauração concluído |
| C — limpeza | Sem serviços, telas, configurações, tarefas transitórias ou assets exclusivos da distribuição antiga | Filas e redeliveries antigas esgotadas; instalação vazia e atualização existentes aprovadas |

A/B/C são etapas do mesmo plano. Não encerrar a migração na release A deixando código obsoleto permanentemente. Separar commits por tarefa e releases operacionais por condição de corte.

**Fora do escopo:** destinatários, outras UFs, CT-e, NFC-e, A3, certificado do contador, geração de TXT a partir de XML, importação manual de relatórios, manifestação/emissão/cancelamento fiscal, interpretação contábil completa do TXT e notificações externas.

## 2. Mapa de arquivos e responsabilidades

### Preservar e adaptar

| Área atual | Tratamento |
| --- | --- |
| `apps/accounts/`, `apps/organizations/access.py`, `admin_access.py` | Manter isolamento por escritório e papéis |
| `apps/organizations/models.py`, `admin.py`, `storage.py` | Manter empresas/escritórios/ciclo de vida; retirar ambiente operacional antigo e referências a NSU |
| `apps/certificates/` | Manter upload assíncrono, envelope, cofre e rotação; resolver caminhos e identificação de A1 |
| `apps/operations/models.py`, `services.py` | Manter auditoria/alertas; substituir códigos e contextos exclusivos do protocolo anterior |
| `apps/operations/forms.py`, `views.py`, `config/urls.py` | Trocar operação de sincronização por pedidos com período e formatos |
| `apps/fiscal/services/storage.py`, `schemas.py` | Reaproveitar confinamento de paths e XML seguro; retirar hipóteses de SOAP/docZip |
| `config/settings/`, `config/celery.py`, Compose, Docker e proxy | Manter stack e separação web/worker; adequar tarefas, configurações e limites |

### Criar

| Arquivos | Responsabilidade |
| --- | --- |
| `apps/fiscal/atf/types.py`, `errors.py` | Contratos imutáveis e erros classificados do portal |
| `apps/fiscal/atf/tls.py`, `client.py` | Contexto A1, HTTP, sessão e endpoints permitidos |
| `apps/fiscal/atf/forms.py`, `messages.py`, `correlation.py` | Parsing restrito, paginação, mensagens e candidatos |
| `apps/fiscal/services/periods.py`, `downloads.py`, `leases.py` | Divisão de períodos, pedidos, coordenação e estado persistido |
| `apps/fiscal/services/artifacts.py`, `documents.py` | ZIP/TXT, materialização segura, notas, versões e eventos |
| `apps/fiscal/services/scheduling.py`, `download_recovery.py` | Recorrência de períodos e retomada de etapas |
| `apps/fiscal/services/legacy.py` | Exportação e leitura imutável do histórico anterior |
| `apps/certificates/services/reconciliation.py` | Diagnóstico/reconciliação do banco com o cofre A1 |
| Novos comandos em `apps/fiscal/management/commands/` | Verificação, exportação legada, retomada e smoke ATF explícito |
| `config/settings/test_postgres.py` | Testes transacionais contra banco PostgreSQL exclusivo para testes |
| `tests/fixtures/atf_pb/` | HTML/XML/ZIP/TXT sintéticos, sem dados reais do cliente |

Evitar transformar `views.py` ou `downloads.py` em um arquivo que também implemente TLS, HTML e ZIP. Preservar o padrão atual de organização; subdividir apenas quando a responsabilidade justificar.

### Remover ao final

| Item atual | Substituto / destino |
| --- | --- |
| `NsuControl`, `SyncPolicy.auto_correct_nsu` e serviços `configure_initial_nsu`/`correct_nsu_cursor` | Remoção, sem equivalente de cursor |
| Estrutura antiga de `SyncPolicy`, `SyncRequest` | Adaptar para `DownloadPolicy`, `DownloadRequest`, `DownloadPart`, `DownloadAttempt`, preservando a funcionalidade de agendamento e as configurações existentes |
| `DistributionBatch`, `DistributionItem` | `DownloadArchive`, `ArchiveMember`; histórico antigo em `LegacyFiscalRecord` |
| `FiscalDocument` antigo | Novos `InvoiceDocument`, `InvoiceXmlVersion`, `FiscalEvent`; registros antigos arquivados |
| `apps/fiscal/services/sefaz.py` | `apps/fiscal/atf/client.py`; remover endpoints nacionais, SOAP, distNSU e `docZip` |
| `apps/fiscal/services/distribution.py` | `artifacts.py`/`documents.py`; remover avanço de NSU e reprocessamento SOAP |
| `apps/fiscal/services/sync.py`, `execution.py`, `recovery.py` | `downloads.py`, `scheduling.py`, `download_recovery.py` |
| `recover_sync_request.py` | `recover_download_request.py` |
| Rotas `company-nsu-cursor`, `company-initial-nsu`, `company-sync`, `batch-reprocess` | Rotas de criação, detalhes e retomada de pedidos; NSU e lote antigos retornam 410 |
| `templates/operations/initial_nsu_form.html`, `NsuCursorCorrectionForm`, `CompanyNsuCursorView`, `DistributionBatchReprocessView` | Remoção |
| `ClientCompany.fiscal_environment`, seletor homologação/produção e respectivos bloqueios | Remoção da operação nova; origem antiga fica no snapshot |
| `SEFAZ_ENABLED_ENVIRONMENTS` e mensagens de homologação da distribuição | Configuração explícita ATF-PB, sem ambiente de testes fictício |
| Schemas exclusivos de envelope/distribuição | Remoção seletiva; manter NF-e/eventos e suas dependências/checksums |
| Tarefas antigas de sincronização e lotes | Consumers transitórios de desativação; removidos na release C |
| Plano antigo de TXT manual e operação de homologação | Marcar como superados e apontar para a documentação ATF |

**Não remover:** validade e senha do A1, criptografia, CSRF do app, controle de acesso, alertas úteis, recuperação de worker, testes de isolamento, migrations históricas, XML/XSD de notas/eventos ainda usados ou arquivos de clientes.

## 3. Contratos compartilhados entre tarefas

Definir em `apps/fiscal/atf/types.py`, com dataclasses congeladas e tipos anotados:

- `DownloadFormat = Literal['xml', 'txt']`.
- `Period(start: date, end: date)`; limites inclusivos, `start <= end`, sem datas futuras.
- `IssuerIdentity(cnpj: str, remote_id: str, form_values: Mapping[str, str])`; CNPJ normalizado, campos permitidos apenas.
- `RemoteIdentity(account_key: str)`; hash estável do identificador autenticado, sem login em texto aberto em logs/banco.
- `MessageRef(id: str, parent_id: str | None, sender_code: str, sent_at_raw: str, has_attachment: bool)`.
- `MessagePage(items: tuple[MessageRef, ...], next_page: str | None)`.
- `AttachmentRef(message_id: str, index: int, filename: str | None)`.
- `SubmissionReceipt(accepted: bool)`; `accepted` não representa arquivo pronto nem prova de ID remoto.
- `SubmissionEvidence(part_id: UUID, attempt_id: UUID, baseline_ids: tuple[str, ...], submitted_at: datetime)`.
- `CorrelationResult(outcome: Literal['matched','pending','ambiguous','empty','remote_failed'], candidates: tuple[str, ...], confirmed_period: Period | None)`.
- `DownloadedArchive(staging_path: Path, sha256: str, byte_count: int, content_type: str)`.
- `ArchiveValidation(members: tuple[ValidatedMember, ...], warnings: tuple[str, ...])`; `ValidatedMember` guarda nome normalizado, tipo `invoice|event|txt|unsupported`, hash, tamanho, classificação e metadados validados, nunca o segredo A1.
- `LegacyExportResult(run_id: UUID, counts: Mapping[str, int], verified: bool)`.

Exceções em `errors.py`: `AtfAuthenticationError`, `AtfSessionExpired`, `AtfPermissionError`, `AtfPortalChanged`, `AtfTransientError`, `AtfSubmissionUncertain`, `AtfAmbiguousResult`, `AtfArtifactError`, `AtfIdentityMismatch`. Cada uma tem `safe_code` e contexto permitido; não usa o corpo HTML ou o segredo como mensagem.

Tarefas Celery recebem apenas UUID/ID de domínio e token de etapa quando necessário. Nunca serializar modelos, cookies, A1 ou senha na fila. Todos os horários internos são aware/UTC; datas fiscais seguem o fuso da política. A data bruta de mensagem é evidência auxiliar, não um identificador.

---

## Tarefa 1 — Congelar o fluxo anterior e registrar a linha de base

**Arquivos:** modificar temporariamente `apps/fiscal/services/execution.py`, `apps/fiscal/tasks.py`, `config/settings/base.py`; criar `tests/test_legacy_dfe_retirement.py`. Na execução, registrar baseline fora do Git de dados sensíveis e manter notas técnicas em `docs/`.

**Interfaces:** consumidores antigos mantêm seus nomes durante A/B, mas retornam resultado seguro `legacy_retired`; nenhuma tarefa antiga cria pedido ATF. O agendamento nacional é retirado do beat imediatamente.

- [ ] Abrir workspace isolado conforme a skill de worktrees, preservando alterações do usuário. A inspeção encontrou mudanças em `.dockerignore` e diretório `certs/` não rastreado; não incorporá-los ou apagá-los por acidente.
- [ ] Registrar commits/configuração, contagens de modelos antigos, tarefas do beat, filas e raiz de arquivos; não imprimir conteúdos do cofre nem `.env` completo. Rodar baseline: `.venv/bin/python -m pytest -q` e `.venv/bin/python -m ruff check .`, registrando falhas preexistentes separadamente.
- [ ] Escrever `test_retired_task_never_calls_national_transport` e `test_retired_task_does_not_create_atf_request`; mock de transporte deve falhar se chamado.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_legacy_dfe_retirement.py -q`, confirmar RED e implementar o bloqueio e os consumers transitórios. Repetir, exigir PASS.
- [ ] Descrever procedimento de parar produtores/workers antigos e reconhecer tarefas pendentes sem purgar filas de upload A1. Commit: `chore: freeze legacy DF-e network execution`.

## Tarefa 2 — Adicionar o domínio ATF sem apagar o banco anterior

**Arquivos:** modificar `apps/fiscal/models.py`, `apps/fiscal/admin.py`; criar `apps/fiscal/migrations/0009_atf_download_domain.py`, `tests/test_download_models.py`, `tests/test_download_periods.py`, `apps/fiscal/services/periods.py`; adaptar factories/fixtures compartilhadas somente se existirem. A sequência atual já contém `0008_syncpolicy_auto_correct_nsu.py`; não reutilizar seu número nem alterá-la.

**Interfaces:** modelos descritos na spec; `split_period(period: Period) -> tuple[Period, ...]`, `active_request_key(company_id: int, period: Period, formats: tuple[DownloadFormat, ...]) -> str`. Todos os IDs novos de pedido/parte/tentativa usam UUID; PKs atuais de empresa/usuário não mudam.

- [ ] Escrever testes para formatos ordenados, parte única por pedido/mês/formato, duplicidade ativa, repetição explícita após término e regras de consolidação de `partial`, `empty` e `succeeded`.
- [ ] Incluir testes de 31/01–02/03, ano bissexto, virada de ano, período maior que um ano dividido por meses, datas invertidas e futuras. Rodar os dois módulos, confirmar RED.
- [ ] Criar os novos modelos mantendo os antigos nesta etapa. `DownloadRequest` guarda `repeat_of`; `DownloadPart` guarda baseline, estado remoto, IDs, prazo, `next_poll_at` e versão de etapa; `DownloadAttempt` registra certeza de envio. Manter snapshots legados e manifesto separados. Constraints de evento incluem chave/tipo/sequência/checksum, sem competir com a nota.
- [ ] Criar `RemoteResultBinding` único por conta/grupo e arquivo único por conta/mensagem/índice. `AtfAccessLease` e `RemoteSubmissionBarrier` têm chaves hash, token/generation e vínculo com tentativa; barreira não expira com o lease. `LegacyMigrationRun` guarda hashes e contagens verificadas, sem segredo.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_download_models.py tests/test_download_periods.py -q` e `.venv/bin/python manage.py makemigrations --check --dry-run --settings=config.settings.test`; exigir PASS e ausência de mudanças pendentes. Commit: `feat: add ATF download domain and monthly parts`.

## Tarefa 3 — Reconciliar o A1 e suportar caminhos Windows/Linux

**Arquivos:** modificar `apps/certificates/services/vault.py`, `apps/organizations/storage.py` se necessário e testes atuais de vault; criar `apps/certificates/services/reconciliation.py`, `apps/certificates/management/commands/reconcile_certificate_vault.py`, `tests/test_certificate_reconciliation.py`.

**Interfaces:** `inspect_vault_binding(certificate_id: int) -> VaultBindingReport`; `apply_verified_binding(certificate_id: int, candidate_storage_id: UUID, *, actor_id: int) -> None`. `VaultBindingReport` contém estado `matched|missing|divergent|ambiguous` e referências não secretas. O comando é dry-run por padrão; alteração exige `--apply --certificate-id <id>` e correspondência comprovada.

- [ ] Escrever testes para barras Windows, path traversal, caminho absoluto, UUID/AAD divergente, fingerprint diferente, dois candidatos e senha inválida. Rodar `tests/test_certificate_reconciliation.py`, confirmar RED.
- [ ] Implementar normalização segura de caminhos relativos e diagnóstico sem descriptografar em logs. Comparar fingerprint, CNPJ, validade e senha verificável antes de atualizar paths/storage ID; nunca escolher o primeiro arquivo disponível.
- [ ] Manter envelopes criptografados e chaves atuais, sem gerar outra chave ou sobrescrever o cofre. Se não houver correspondência, manter erro explícito e indicar novo cadastro via upload existente. Registrar auditoria sem senha.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_certificate_vault.py tests/test_certificate_upload_envelope.py tests/test_certificate_uploads.py tests/test_certificate_reconciliation.py -q`; exigir PASS. Rodar comando de diagnóstico local somente com o ambiente correto.
- [ ] Commit: `fix: reconcile A1 vault bindings across Windows and Linux`.

## Tarefa 4 — Implementar transporte A1 e contrato HTTP do portal

**Arquivos:** criar `apps/fiscal/atf/{__init__,types,errors,tls,client,forms,messages}.py`, fixtures sintéticas e `tests/test_atf_authentication.py`, `test_atf_forms.py`, `test_atf_messages.py`; adicionar configurações ATF em `config/settings/base.py`, development/container e `.env.example` conforme tarefa 13.

**Interfaces:** `client_tls_context(certificate_id: int) -> ContextManager[ssl.SSLContext]`; `open_atf_client(company_id: int) -> ContextManager[AtfPbClient]`; métodos `authenticate() -> RemoteIdentity`, `lookup_issuer(cnpj: str) -> IssuerIdentity`, `submit_query(issuer: IssuerIdentity, period: Period, format: DownloadFormat) -> SubmissionReceipt`, `list_messages(cursor: str | None = None, parent_id: str | None = None) -> MessagePage`, `read_message(message_id: str, parent_id: str) -> ParsedMessage`, `download_attachment(ref: AttachmentRef) -> DownloadedArchive`. `ParsedMessage` contém refs, remetente/função, período e filtros extraídos, anexos e resultado tipado, sem HTML bruto persistido.

- [ ] Escrever testes offline para redirects de autenticação, A1 inválido/renovado, TLS recusado, cookie isolado, sessão expirada com HTTP 200, host externo, HTTP sem TLS e contexto fechado após exceção. Rodar `tests/test_atf_authentication.py`, confirmar RED.
- [ ] Implementar TLS com cadeia validada, timeouts, limpeza e backends Linux/Windows definidos na spec. O certificado cliente é configurado apenas nos hosts aprovados; nunca reutilizar um adapter amplo para destino externo.
- [ ] Escrever e rodar testes RED para formulário com ocultos, pesquisa CNPJ/ID interno, atribuições JavaScript maliciosas, codificação declarada, grupo com 0/1/5 filhos, múltiplos anexos, caixa paginada e página desconhecida. O remetente e a conta autenticada devem ser extraídos antes de usar a caixa; ausência desses dados vira `AtfPortalChanged`.
- [ ] Implementar parsing por HTML e literais permitidos, sem `eval`. Confirmar CNPJ consultado. Usar `cmbTpExibicao=3` XML, `2` TXT; `cmbTpDoccmpEmit=2`; recuperar os demais campos da sessão. Campos/identificadores reais do teste não entram como constantes.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_atf_authentication.py tests/test_atf_forms.py tests/test_atf_messages.py -q`, exigir PASS. Commit: `feat: add certificate-authenticated ATF-PB HTTP client`.

**Checagem desta tarefa:** paginação, identidade remota e prova de resultado vazio não foram exercitadas integralmente no spike. Criar fixtures do contrato observado/confirmado; se o portal não fornecer prova suficiente, interromper somente essa capacidade com estado explícito, sem inventar regra de vazio ou correlação.

## Tarefa 5 — Coordenar acesso e vincular resultado remoto com segurança

**Arquivos:** criar `apps/fiscal/services/leases.py`, `apps/fiscal/atf/correlation.py`, `tests/test_atf_leases.py`, `test_atf_correlation.py`, `config/settings/test_postgres.py`.

**Interfaces:** `claim_access(scope: str, part_id: UUID, *, now: datetime) -> LeaseToken | None`; `renew_access(token: LeaseToken, *, now: datetime) -> LeaseToken`; `release_access(token: LeaseToken) -> None`; `begin_submission(part_id: UUID, token: LeaseToken, evidence: SubmissionEvidence) -> None`; `reconcile_result(evidence: SubmissionEvidence, messages: tuple[ParsedMessage, ...]) -> CorrelationResult`; `bind_remote_result(part_id: UUID, account_key: str, parent_id: str, *, actor_id: int | None) -> RemoteResultBinding`. `LeaseToken` tem scope, owner/generation e expiração; toda mutação confere owner/generation.

- [ ] Escrever testes para baseline paginado, resultado concorrente do mesmo período, remetente alheio, formato divergente, grupo já vinculado e IDs iguais em contas diferentes. Rodar `test_atf_correlation.py`, confirmar RED.
- [ ] Implementar correlação combinada e associação exclusiva; não usar último ID/data como seleção. Ler somente mensagens de consultas NF-e candidatas. Ausência de anexo sem confirmação de resultado não é `empty`.
- [ ] Escrever testes transacionais com duas conexões PostgreSQL: lease expirado enquanto POST antigo está em trânsito, mesma empresa em escritórios diferentes, conta compartilhada entre empresas e worker antigo tentando gravar após fencing. Confirmar RED com `--ds=config.settings.test_postgres`.
- [ ] Implementar leases curtos em transações, intervalo de caixa por conta e barreira persistente antes do POST. A barreira impede nova submissão até conciliação, mesmo após expiração do lease. Heartbeat apenas renova posse, não resolve incerteza remota.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_atf_correlation.py -q` e `.venv/bin/python -m pytest tests/test_atf_leases.py --ds=config.settings.test_postgres -q`; exigir PASS real no PostgreSQL. Banco exclusivo, credenciais via ambiente, nenhuma configuração apontando ao banco do cliente. Commit: `feat: coordinate ATF submissions and exclusive result bindings`.

## Tarefa 6 — Receber ZIPs, preservar originais e indexar notas/eventos

**Arquivos:** criar `apps/fiscal/services/artifacts.py`, `documents.py`, `tests/test_download_archives.py`, `test_download_documents.py`, `test_download_txt.py`; adaptar `storage.py`, `schemas.py`, `tests/test_fiscal_storage.py`, `test_fiscal_schemas.py`; adicionar fixtures sintéticas de nota/eventos/relatório.

**Interfaces:** `validate_archive(download: DownloadedArchive, *, company_id: int, period: Period, format: DownloadFormat) -> ArchiveValidation`; `persist_archive(part_id: UUID, ref: AttachmentRef, download: DownloadedArchive, validation: ArchiveValidation) -> DownloadArchive`; `index_archive(archive_id: UUID) -> IndexResult`; `revalidate_archive(archive_id: UUID) -> IndexResult`. `IndexResult` contém contagens por tipo/status e alertas; índices derivados podem ser refeitos sem rede.

- [ ] Escrever testes de stream maior que limite, truncamento, CRC, login HTML como ZIP, traversal, symlink, entrada absoluta, duplicidade normalizada, XML com DTD e bomba de descompressão. Confirmar RED no módulo de arquivos.
- [ ] Implementar streaming/staging privado, hash incremental e publicação atômica. Aplicar limites da spec ao que foi realmente lido, inclusive bytes descompactados durante CRC; não usar `extractall`. O download original permanece imutável e repetição idêntica não duplica o arquivo lógico.
- [ ] Escrever testes para 16 notas + 9 eventos sintéticos, mesmo access key em nota/evento, eventos de destinatário, data do evento fora do período de emissão, tipo/versão XSD desconhecidos, CNPJ/modelo/tpAmb divergentes, repetição e segunda versão do XML. Confirmar RED; implementar classificação e índices separados.
- [ ] Escrever testes de TXT Windows-1252, UTF-8/BOM, arquivo vazio, bytes inválidos, limite e TXT solicitado sozinho. Preservar bytes originais; comparar chaves entre formatos quando ambos disponíveis. Divergência contábil não deve ser silenciosamente corrigida pelo sistema.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_download_archives.py tests/test_download_documents.py tests/test_download_txt.py tests/test_fiscal_storage.py tests/test_fiscal_schemas.py -q`; exigir PASS. Reutilizar schemas válidos; `pending_schema` informa limitação, não afirma assinatura verificada. Commit: `feat: store and validate ATF ZIP XML and TXT artifacts`.

## Tarefa 7 — Orquestrar submissão, espera, download e retomada

**Arquivos:** criar `apps/fiscal/services/downloads.py`, `download_recovery.py`, `apps/fiscal/management/commands/recover_download_request.py`, `tests/test_download_execution.py`, `test_download_recovery.py`; modificar `apps/fiscal/tasks.py` preservando consumers antigos transitórios.

**Interfaces:** `request_download(*, company_id: int, period: Period, formats: tuple[DownloadFormat, ...], actor_id: int | None, trigger: Literal['manual','scheduled'], repeat_of: UUID | None = None) -> DownloadRequest`; `advance_part(part_id: UUID) -> AdvanceResult`; `consolidate_request(request_id: UUID) -> None`; `recover_download_request(request_id: UUID, *, actor_id: int, note: str) -> RecoveryResult`; tasks `process_download_part(part_id: str)`, `poll_download_part(part_id: str)`, `revalidate_download_archive(archive_id: str)`. `AdvanceResult` indica estado e próxima ETA; `RecoveryResult` indica retomada, conciliação ou intervenção exigida, sem presumir novo envio.

- [ ] Escrever testes de fluxo completo com cliente fake, clique duplo, redelivery, pedido XML+TXT, mês vazio, falha de uma parte, múltiplos anexos e solicitação simultânea. Rodar `test_download_execution.py`, confirmar RED.
- [ ] Implementar criação atômica de pedido/partes e enqueue via `transaction.on_commit`; etapas curtas persistidas; formatos/meses sequenciais até a submissão anterior estar associada. Usar tarefas com ETA, nunca `sleep` de espera dentro do worker.
- [ ] Escrever testes para crash antes do POST, POST aceito seguido de timeout, crash antes de persistir binding, crash durante stream, ZIP salvo antes do índice e expiração da sessão entre leitura/anexo. Confirmar RED; implementar retomada com baseline/barreira/IDs e download da mensagem na mesma sessão.
- [ ] Implementar retries somente idempotentes; no máximo três retries, atrasos 60/120/240 segundos, respeitando `Retry-After`. Espera de caixa mínima 60 segundos por conta e prazo inicial de 24 horas. `ambiguous` não vira reenvio automático nem `empty`. Renovação de certificado não autoriza reaproveitar cookies anteriores. Em cancelamento local, parar etapas ainda não iniciadas e preservar arquivos/IDs; não afirmar cancelamento de pedido já aceito no ATF.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_download_execution.py tests/test_download_recovery.py -q`; exigir PASS, incluindo `test_timeout_after_accepted_post_never_resubmits` e `test_restart_reopens_correct_message_before_attachment`. Commit: `feat: orchestrate resumable ATF download requests`.

## Tarefa 8 — Preservar o download automático programável e adaptar a coleta

**Arquivos:** criar `apps/fiscal/services/scheduling.py`, `tests/test_download_scheduling.py`; modificar `apps/fiscal/tasks.py`, `config/settings/base.py`, `apps/operations/forms.py`, `templates/operations/policy_form.html`.

**Interfaces:** `period_for_policy(policy: DownloadPolicy, now: datetime) -> Period`; `enqueue_due_downloads(*, now: datetime) -> int`; task `schedule_due_downloads()`. Preservar modos manual/automático/híbrido, frequência, horário, fuso, dias configurados e ativação; retirar apenas a dependência de `last_nsu` e `next_allowed_at` da distribuição. A pausa de corte é global e temporária, sem mudar `is_active` de cada política.

- [ ] Escrever testes para fuso, dias 28–31, mês anterior, dia anterior, rolling de sete dias, execução atrasada, política manual/inativa, falha parcial e uma única janela por slot agendado. Incluir `test_migration_preserves_active_automatic_schedule`, `test_migration_preserves_hybrid_mode_and_schedule_fields`, `test_inactive_schedule_stays_inactive` e `test_cutover_resumes_active_schedules_without_manual_reactivation`. Confirmar RED em `test_download_scheduling.py`.
- [ ] Implementar estratégias `previous_day`, `previous_month`, `rolling_days`, datas completas e idempotência por ocorrência agendada. Não fazer backfill silencioso ilimitado após meses parado; registrar janelas faltantes e oferecer pedidos explícitos.
- [ ] Adaptar as políticas antigas pelo serviço da tarefa 10, mantendo modo, frequência, horário, fuso, dias e estado ativo/inativo. Mapear diária para `previous_day`, semanal para `rolling_days=7` e mensal para `previous_month`, com XML+TXT inicialmente, todos editáveis. Não exigir recadastro ou reativação manual. Políticas novas continuam com default manual; não sobrescrever um fuso existente com o default de instalação.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_download_scheduling.py tests/test_download_models.py -q`; exigir PASS. Verificar que beat chama somente `schedule_due_downloads` e mantém expiração de uploads de certificados.
- [ ] Commit: `feat: schedule ATF downloads by explicit periods and formats`.

## Tarefa 9 — Trocar telas, ações e downloads autorizados

**Arquivos:** modificar `apps/operations/{forms,views}.py`, `config/urls.py`, `templates/operations/{dashboard,company_form,company_detail,company_list,document_list,policy_form,alert_list}.html`; criar `download_request_form.html`, `download_request_detail.html`, `legacy_record_list.html`, `legacy_record_detail.html`, `remote_result_resolution.html`, `tests/test_download_access.py`, `test_download_views.py`; adaptar testes de workstation/admin.

**Interfaces:** rotas `company-download-create` (`empresas/<int:company_id>/downloads/novo/`), `download-request-detail` (`downloads/<uuid:request_id>/`), `download-request-recover`, `download-archive`, `download-archive-revalidate`, `download-result-resolve`, `legacy-record-list`, `legacy-record-detail`, `legacy-file-download`. Operações de criação/retomada/revalidação/resolução são POST com CSRF; downloads são GET autenticados sem aceitar paths arbitrários.

- [ ] Escrever testes de empresa/pedido/ZIP/nota/evento/TXT/legado de outro escritório e de URL de arquivo forjada, tanto na UI quanto no admin. Confirmar RED; aplicar os filtros existentes de acesso em todos os querysets, sem confiar no company_id enviado pelo browser.
- [ ] Implementar formulário com datas obrigatórias, ambos formatos por padrão e estado por parte. Trocar linguagem de NSU/lote/distribuição por pedido/período/arquivo. Mostrar ZIP original e contagens distintas de notas/eventos; usuário não precisa entender TLS, SOAP ou Celery para operar.
- [ ] Implementar resolução de ambiguidade somente para administrador: confirmar candidato compatível via binding exclusivo e staging validado, ou encerrar localmente a tentativa incerta com justificativa e aviso de que ela pode existir no portal. Nenhuma dessas ações envia outro POST de consulta automaticamente. Registrar ator, motivo e metadados sem corpo das mensagens.
- [ ] Retirar formulários e ações de NSU e lotes. Para URLs antigas conhecidas, retornar 410 sem criar pedido, sem redirects que transformem GET/POST antigo em coleta nova. Preservar acesso a histórico/documentos antigos por rotas de legado e links já guardados com resolução autorizada de IDs, quando houver correspondência inequívoca.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_download_access.py tests/test_download_views.py tests/test_workstation_access.py tests/test_admin_isolation.py tests/test_organizations_admin.py -q`; exigir PASS. Conferir teclado, erros de campo, foco, estados vazios e layout existente, sem redesign alheio ao escopo. Commit: `feat: replace NSU operations with period download workflows`.

## Tarefa 10 — Exportar e preservar o histórico antes de remover tabelas

**Arquivos:** criar `apps/fiscal/services/legacy.py`, comandos `export_legacy_fiscal.py`, `verify_legacy_fiscal.py`, `tests/test_legacy_fiscal_export.py`, `test_legacy_fiscal_access.py`, `test_atf_migration_preservation.py`; adaptar `apps/fiscal/admin.py` para leitura imutável e documentação operacional.

**Interfaces:** `export_legacy_fiscal(*, actor_id: int, dry_run: bool = True) -> LegacyExportResult`; `verify_legacy_fiscal(run_id: UUID, *, check_files: bool = True) -> LegacyExportResult`; `legacy_file_for_record(record_id: UUID, file_key: str, *, user_id: int) -> Path`. Comandos de exportação são dry-run por padrão e usam `--apply` para snapshots persistidos; nenhum remove arquivos.

- [ ] Escrever testes com cada modelo antigo, relações, arquivos presentes/ausentes, ambientes produção/homologação/unknown e caminhos antigos. Confirmar RED em `test_legacy_fiscal_export.py`.
- [ ] Exportar `SyncPolicy`, `NsuControl`, `SyncRequest`, `DistributionBatch`, `DistributionItem` e `FiscalDocument` para snapshots canônicos com versão, origem, PK, empresa e relações. Preservar status/motivo de interrupção das tarefas antigas; não convertê-las em pedidos ATF. Hash de snapshot e manifesto de arquivo são distintos.
- [ ] Implementar comando verificável de contagens/digests/referências e imutabilidade. Não guardar cópias de A1/senha no legado. Auditoria e alertas já existentes permanecem em suas tabelas. Encerrar por migração, com nota e auditoria, alertas exclusivamente obsoletos `sefaz_consumption_block` e `distribution_batch_processing_failed`; códigos genéricos `sync_execution_failed`/`sync_queue_unavailable` só são encerrados se o contexto provar vínculo ao fluxo legado. Não apagar alertas nem marcar falhas novas como resolvidas. Arquivos fiscais ficam nos mesmos caminhos; manifesto registra existência/checksum/tamanho e ausência preexistente explícita.
- [ ] Criar `DownloadPolicy` para cada política atual preservando modo, frequência, horário, fuso, dias da semana/dia do mês e estado ativo/inativo, além da associação de origem. Aplicar o mapeamento de período e formatos da tarefa 8; impedir migração duplicada. Não tratar o histórico de execução por NSU como prova de coleta de um período ATF. Durante o corte, pausar o despachante global e, ao concluir, retomá-lo sem reativação manual das políticas. Resolver A1 por tarefa 3. Ensaio de backup/restauração inclui banco, arquivos de notas, cofre e chaves, mantendo isolamento de permissões e sem versionar o backup.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_legacy_fiscal_export.py tests/test_legacy_fiscal_access.py tests/test_atf_migration_preservation.py -q`; exigir PASS. Registrar manifesto completo e resultado do restore em ambiente separado. Commit: `feat: preserve legacy fiscal history before ATF cutover`.

**Banco existente:** executar exportação/verificação com tabelas antigas ainda presentes, na release A. A release B só fica liberada com `LegacyMigrationRun` verificado e origem congelada. Um banco novo pode emitir manifesto vazio automaticamente, com contagens zero comprovadas; isso não equivale a ignorar um banco antigo não exportado. Manter uma referência explícita ao estado histórico de migrations para que o exportador não dependa de importar modelos removidos na release B.

## Tarefa 11 — Retirar modelos antigos por migrations de corte

**Arquivos:** criar `apps/fiscal/migrations/0010_retire_legacy_distribution_models.py` e `apps/organizations/migrations/0006_remove_fiscal_environment.py`; modificar models/admin/forms/views dependentes; ampliar `tests/test_atf_migration_preservation.py`, `tests/test_organizations_validators.py`, `tests/test_organizations_admin.py`.

**Interfaces:** migração fiscal consulta `LegacyMigrationRun` e revalida os digests/contagens de origem congelada no banco antes de `DeleteModel`; migração de organizações depende da migração fiscal de corte. Não depender de montar o cofre/arquivos no serviço de migrations para esse gate: a verificação de arquivos já foi feita pelo worker e está no manifesto.

- [ ] Escrever teste com `MigrationExecutor` migrando de fiscal `0008_syncpolicy_auto_correct_nsu`/organizações `0005`, populando dados, passando por fiscal `0009`, exportando/verificando e então cortando em `0010`. Confirmar RED. Incluir instalação de banco vazio e corte recusado para manifesto ausente/desatualizado. Os números partem da árvore inspecionada; se houver migrations novas antes da execução, recalcular a sequência sem criar branches conflitantes.
- [ ] Remover somente após o gate os modelos antigos da tabela de remoções. A cópia preservada precisa permitir navegar as relações e baixar arquivos sem importar os modelos apagados. A migration de corte usa `apps.get_model` histórico, não serviços que mudarão futuramente.
- [ ] Retirar `ClientCompany.fiscal_environment`, os validadores/bloqueios que consultam `nsu_controls`/`sync_requests` e escolhas de ambiente na UI/admin. Não transformar documentos legados de homologação em produção ATF; `unknown` permanece `unknown`.
- [ ] Garantir dependências da cadeia de migrations e preservar qualquer helper importado por migrations antigas. Rodar migração do zero e atualização com PostgreSQL em ambiente separado; conferir snapshots, paths e acesso autorizado após corte.
- [ ] Rodar `.venv/bin/python -m pytest tests/test_atf_migration_preservation.py tests/test_organizations_validators.py tests/test_organizations_admin.py -q`; exigir PASS e comparar manifesto antes/depois. Commit: `refactor: retire NSU distribution tables after verified archival`.

**Rollback:** até A, retornar ao código anterior com redes nacionais bloqueadas e backup preservado. Depois de B ou de qualquer pedido novo, pausar tarefas e preservar banco/arquivos atuais; não restaurar backup antigo por cima deles. Recuperar em ambiente separado e reconciliar, ou corrigir adiante. Migrations destrutivas não prometem reversão automática que recrie histórico completo.

## Tarefa 12 — Eliminar serviços, testes e ativos obsoletos

**Arquivos:** remover os serviços/command/template exclusivos listados no mapa; modificar `apps/fiscal/services/__init__.py`, imports em apps/config/tests, admin e tarefas; revisar `vendor/sefaz-schemas/README.md`, `SHA256SUMS` e árvore de schemas; criar `tests/test_no_legacy_fiscal_runtime.py`.

**Interfaces:** nenhuma importação de `NsuControl`, cliente nacional, cursor, SOAP ou lote deve permanecer em código de runtime. Referências históricas em migrations, snapshots, documentação de migração e testes de preservação são intencionais.

- [ ] Escrever teste estrutural enxuto para módulos/rotas/tarefas públicas retiradas e para não existir endpoint nacional configurável no runtime. Não proibir por busca cega a palavra NSU em histórico ou nomes de arquivos de migrations. Confirmar RED.
- [ ] Excluir `sefaz.py`, `distribution.py`, `sync.py`, `execution.py`, `recovery.py` antigos e `recover_sync_request.py`, depois de trocar todos os chamadores. Retirar modelos/forms/views/templates/admin e ações exclusivos, sem deixar aliases permanentes com semântica alterada.
- [ ] Substituir `test_sefaz_distribution.py`, `test_distribution_parser.py`, `test_distribution_reprocessing.py`, `test_sync_services.py` e `test_sync_execution.py` pelas novas suites. Transferir os casos úteis de isolamento, concorrência e preservação antes de excluir. Adaptar `test_fiscal_models.py`, `test_fiscal_regressions.py`, `test_fiscal_preflight.py`, `test_fiscal_concurrency.py`, `test_fiscal_environment_migration.py` ou renomeá-los conforme o novo contrato; não manter testes mortos nem remover cobertura só para passar.
- [ ] Remover apenas XSDs de distribuição e dependências sem referências. Manter schemas de NF-e/eventos, imports/includes e checksums necessários à tarefa 6. Retirar `known_distributed_schema` e classificação por `schema_name` da distribuição, preservando parser XML seguro.
- [ ] Na release C, após inspecionar ready/reserved/active/scheduled/unacked em todos os workers/broker e aguardar a maior janela de redelivery/ETA conhecida, remover consumers transitórios e suas entradas antigas do beat. Nunca purgar toda a fila compartilhada. Rodar `.venv/bin/python -m pytest tests/test_no_legacy_fiscal_runtime.py -q` e suite final. Commit: `refactor: remove obsolete DF-e distribution runtime and assets`.

## Tarefa 13 — Configuração, diagnóstico e documentação da operação nova

**Arquivos:** modificar `config/settings/{base,development,container,production,test}.py`, `.env.example`, `docker-compose.yml`, `Dockerfile`/proxy somente se necessário, `pyproject.toml`, `requirements.txt`, `apps/fiscal/management/commands/verify_fiscal_installation.py`, `README.md`, `PRODUCT.md`, `docs/PRD-IMPLEMENTACAO.md`; criar `docs/OPERACAO-ATF-PB.md`, `tests/test_atf_configuration.py`; marcar os dois documentos antigos de operação/TXT como superados.

**Interfaces:** manter `verify_fiscal_installation --worker --write-notes-probe`, mas verificar ATF, acesso ao cofre e staging privado. Novo comando `probe_atf_pb --company-id <id>` verifica login sem consulta; somente `--submit --start YYYY-MM-DD --end YYYY-MM-DD --formats xml,txt` cria pedido de teste pelo serviço real. Sem opções de envio, nunca gerar solicitação.

- [ ] Escrever testes para configuração incompleta, URL não aprovada, limites inválidos, storage sem escrita, web sem chave privada, smoke sem `--submit` e falta de certificados. Confirmar RED em `test_atf_configuration.py` e adaptar `test_fiscal_preflight.py`.
- [ ] Introduzir `ATF_PB_ENABLED` (default `False`, habilitado no corte), `ATF_PB_BASE_URL` (default `https://www4.sefaz.pb.gov.br`), hosts exatos aprovados, `ATF_CONNECT_TIMEOUT_SECONDS=10`, `ATF_READ_TIMEOUT_SECONDS=60`, `ATF_MAX_HTML_BYTES=10485760`, `ATF_POLL_INTERVAL_SECONDS=60`, `ATF_WAIT_TIMEOUT_SECONDS=86400`, `ATF_ACCESS_LEASE_SECONDS=300`, heartbeat de 30 segundos e limites ZIP da spec. Qualquer override abaixo de 60 para polling deve ser recusado. Lease deve exceder timeout e renovar durante streaming.
- [ ] Introduzir limites de artefato `ATF_MAX_ZIP_BYTES=209715200`, `ATF_MAX_UNCOMPRESSED_BYTES=1073741824`, `ATF_MAX_ZIP_ENTRIES=50000`, `ATF_MAX_XML_BYTES=10485760`, `ATF_MAX_TXT_BYTES=104857600`; CA customizada opcional preserva verificação TLS. Remover `SEFAZ_ENABLED_ENVIRONMENTS` e configurações SOAP; migrar timeouts/CA úteis para nomes ATF, sem compatibilidade silenciosa eterna.
- [ ] Manter mount fiscal read-only no web, cofre/chave só no worker/migrations onde necessário, scheduler sem A1 e staging privado no worker. Manter expiração de upload A1, healthcheck, rede local e bind localhost. Atualizar descrição do pacote para NF-e emitidas SEFAZ-PB. Não adicionar Playwright/Selenium nem ampliar privilégios do container para reproduzir o spike privilegiado.
- [ ] Reescrever instruções para A1, período, XML/TXT, ZIPs, retomada, falta de dados, atualização de portal e corte/rollback. Marcar `docs/PLANO-RELATORIOS-TXT-EMITIDOS.md` e `docs/OPERACAO-HOMOLOGACAO.md` como históricos superados com link novo; atualizar PRD/PRODUCT para remover promessas antigas. Rodar `.venv/bin/python -m pytest tests/test_atf_configuration.py tests/test_fiscal_preflight.py tests/test_development_settings.py tests/test_health.py -q` e `docker compose config --quiet`; exigir PASS sem imprimir `.env`. Commit: `docs: document ATF-PB configuration and operations`.

**Observabilidade incluída:** adicionar testes em `tests/test_operation_alerts.py` para códigos `atf_authentication_failed`, `atf_submission_uncertain`, `atf_result_ambiguous`, `atf_portal_changed`, `atf_artifact_rejected` e `atf_queue_unavailable`, com deduplicação por pedido/parte e resolução auditada. Registrar correlação, etapa, duração, tentativas, bytes e contagens por tipo, com domínios de falha `certificate|authentication|portal|correlation|network|storage|queue|migration`. Não registrar CNPJ, login remoto, cookies, corpos de mensagem, chaves de acesso ou conteúdo de notas. Adaptar dashboard/health aos novos estados; manter funcionamento sem adicionar um serviço de métricas ao escopo.

## Tarefa 14 — Verificar o conjunto e executar aceite controlado

**Arquivos:** completar fixtures sintéticas e `tests/test_atf_end_to_end.py`; registrar resultados em `docs/OPERACAO-ATF-PB.md` e relatório de aceite, sem dados reais de documentos/segredos no Git.

**Interfaces:** o smoke usa o mesmo `request_download` e as mesmas tarefas do produto; não é uma implementação alternativa baseada nos scripts `/tmp` do experimento.

- [ ] Escrever teste offline E2E cobrindo autenticação fake, lookup, XML/TXT, virada de mês, caixa paginada, polling, ZIPs e downloads autorizados; executar RED antes de finalizar os pontos de integração. Incluir recuperação de POST incerto e troca de A1 entre etapas.
- [ ] Executar `.venv/bin/python -m pytest -q`, `.venv/bin/python -m ruff check .`, `.venv/bin/python -m mypy apps config`, `.venv/bin/python manage.py check --settings=config.settings.test` e `makemigrations --check --dry-run` no mesmo settings. Exigir sucesso; falhas preexistentes documentadas não tornam falhas novas aceitáveis.
- [ ] Executar a suite transacional com `--ds=config.settings.test_postgres`, migração vazia e atualização com manifesto. Não considerar testes SQLite com locks ignorados como evidência suficiente de concorrência.
- [ ] Executar smoke ATF com uma empresa reconciliada, A1 válido, datas explícitas e XML+TXT; reutilizar 01/10/2026–18/10/2026 como comparação, se apropriado ao momento da execução. Conferir HTTP, ZIP, CRC/hash, CNPJ/datas das notas, eventos, relatório original e correlação de mensagens. Não fixar permanentemente contagem de 16 notas: o portal pode incorporar eventos ou corrigir resultados.
- [ ] Reiniciar um worker durante espera e confirmar retomada sem pedido duplicado. Conferir acesso negado de outro escritório e ausência final de NSU/SOAP/ambiente nacional nas telas, rotas, tarefas e configuração. Registrar matriz de aceite e limitações reais. Commit: `test: validate ATF migration and end-to-end downloads`.

---

## 4. Critérios de conclusão

- [ ] Pedido manual com datas e XML/TXT entrega os ZIPs corretos pelo app.
- [ ] Download automático programável mantido: configurações e ativação dos agendamentos existentes preservadas, retomada após o corte sem reativação manual, coleta adaptada para período/formato e sem cursor escondido.
- [ ] ZIP original e TXT original preservados; notas, versões e eventos separados.
- [ ] POST incerto, caixa ambígua, vazio confirmado, erro e parcial têm estados e ações distintos.
- [ ] Mensagens/anexos não se misturam entre empresas ou escritórios; mesma conta remota recebe coordenação compartilhada.
- [ ] Certificado e senha não aparecem em HTTP do app, Celery, banco de resultados, logs ou arquivo temporário desprotegido.
- [ ] Cadastro A1 reconciliado; nenhum vínculo foi reparado por tentativa/posição de arquivo.
- [ ] Histórico/arquivos antigos acessíveis com origem preservada; manifesto e restore aprovados.
- [ ] Instalação nova e atualização real passam sem alterar migrations aplicadas.
- [ ] Release C concluída: sem NSU, distribuição nacional, SOAP/docZip, tabelas antigas, telas e tarefas transitórias no runtime.
- [ ] Schemas/documentos/testes ainda úteis preservados; documentação antiga inequivocamente marcada como superada.
- [ ] Todos os checks de aceite têm evidência, e o teste real valida o produto, não apenas um script avulso.

## 5. Dependências e ordem prática

`1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14` é a ordem de referência. Configurações necessárias às tarefas 4–8 são introduzidas nessas tarefas e consolidadas na 13. A exportação/backup da tarefa 10 pode ser preparada logo após 2/3, mas a exclusão da tarefa 11 permanece bloqueada pelo manifesto/restore. A retirada dos consumers transitórios da tarefa 12 só acontece na release C, após a janela observada; não impede desenvolver a configuração/documentação e os testes finais enquanto a janela transcorre.

O plano não exige novo framework, novo produto ou manutenção de uma segunda integração fiscal. O ponto de maior cuidado é substituir o modelo de processamento e preservar os dados já existentes, não simplesmente trocar URLs.
