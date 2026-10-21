# Cancelamento e exclusão administrativa de pedidos

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que administradores cancelem todo um pedido e excluam pedidos cancelados das telas operacionais.

**Architecture:** Cancelamento local transacional e auditável; partes pendentes passam a canceladas. Workers verificam o cancelamento antes de novas operações e gravações. Exclusão retira o pedido da operação, remove metadados exclusivos e agenda remoção persistente dos arquivos; referências compartilhadas e auditoria são preservadas.

**Tech Stack:** Django, PostgreSQL, Celery e templates existentes.

**Spec:** Requisito do usuário de 21/10/2026: cancelar e excluir pedido cancelado em nível admin; decisões de implementação abaixo.

## Global Constraints

- Administrador do escritório gerencia apenas suas empresas; superusuário gerencia a instalação. Operadores e usuários inativos não executam estas ações.
- Ações por POST com CSRF, confirmação e motivo; GET apenas apresenta confirmação.
- Cancelamento não cancela o processamento remoto da SEFAZ nem desativa o agendamento futuro da empresa.
- O usuário confirmou: excluir também ZIPs, XMLs e TXTs baixados pelo pedido. Manter somente arquivos e notas usados por outros pedidos, além da auditoria.
- Sem apagar dados reais, reiniciar serviços, mudar a `.dockerignore` já alterada ou fazer commit automaticamente.

## Review Focus

- Worker já autenticado ou com HTTP em andamento deve parar nas próximas verificações e não reativar o pedido.
- Partes concluídas e arquivos permanecem após cancelar; após excluir, somente referências compartilhadas permanecem.
- Tarefas antigas e ticks do scheduler não retomam pedidos cancelados/excluídos.
- Exclusão de pedido ainda ativo é recusada; ações não atravessam escritórios.
- Retomada ou resolução antiga não reativa pedido cancelado; barreiras locais podem ser liberadas com reconhecimento explícito da situação remota.

### Task 1: Estado, serviços e interrupção cooperativa

**Files:** `apps/fiscal/download_models.py`, migration `0016`, `services/download_lifecycle.py`, `services/download_deletion.py`, `services/storage_coordination.py`, `services/leases.py`, `services/downloads.py`, `services/artifacts.py`, `services/documents.py`, `services/download_recovery.py`, `tasks.py`, configuração do beat e testes de ciclo de vida, exclusão e concorrência.

- [x] Escrever regressões e observar falhas: permissões, cancelamento de todas as partes pendentes, confirmação/motivo, tentativas antigas, concorrência durante submit/poll/download/erros e preservação de originais.
- [x] Implementar serviços transacionais `cancel_download_request` e `delete_cancelled_download_request`, auditoria, `deleted_at`, remoção dos metadados exclusivos e limpeza de arquivos persistida em `DownloadFileDeletion`.
- [x] Cercar gravações e pontos de retomada com verificação de cancelamento; manter leases de trabalho em andamento até liberação/expiração, sem matar workers ou revogar outras empresas.
- [x] Rodar regressões, incluindo bloqueios PostgreSQL quando disponíveis.

### Task 2: Fluxo administrativo

**Files:** `apps/operations/download_forms.py`, `download_views.py`, `views.py`, `config/urls.py`, templates de confirmação/detalhe, `tests/test_download_lifecycle_views.py`.

- [x] Testar POST/CSRF, isolamento, ausência de ações para operador, confirmação obrigatória e exclusão apenas após cancelar.
- [x] Adicionar ações no detalhe do pedido, com páginas de confirmação e mensagens claras.
- [x] Excluir registros ocultos de listas, página da empresa, dashboard e retomada pela URL; impedir recriação de arquivos por indexadores antigos e repetir limpezas de armazenamento falhas.
- [x] Conferir fluxo completo no navegador com banco e empresa fictícios, desktop e celular.

### Task 3: Verificação e documentação

- [x] Executar suíte, Ruff, mypy, Django e consistência de migrations.
- [x] Revisão independente do conjunto, corrigindo problemas encontrados.
- [x] Documentar operação, limites do cancelamento remoto e atualização com migration.

## Execução

- Planejamento: a implementação será feita no checkout fornecido, como nas alterações anteriores já autorizadas; apenas `.dockerignore` estava alterada no início.
- Estado inicial: funcionalidade inexistente; cancelamento local de uma tentativa isolada já existia.
- Revisão: usar bloqueio de empresa `no_key=True` antes das partes em cancelamento/limpeza/retomada, permitindo verificações FK durante indexação. Revalidar autorização após adquirir o bloqueio da empresa.
- Revisão: limitar `select_for_update` às partes (`of=("self",)`) para não bloquear pedidos unidos antes da hora. Publicadores adquirem trava compartilhada de armazenamento antes da parte; limpeza adquire a trava exclusiva antes de empresa/partes. Isso também protege namespaces históricos de CNPJ.
- Revisão: a manutenção prioriza a menor quantidade de tentativas por pedido; a regressão com 100 limpezas falhas e uma nova reproduziu a inanição antes da correção e passou depois dela.
- Resultado: suíte completa com **372 aprovados e 11 ignorados**; os ignorados exigem PostgreSQL, indisponível no ambiente SQLite desta validação. Após o último ajuste de normalização do UUID da tarefa, **37 regressões focadas aprovadas**. Ruff, formatação (140 arquivos), mypy (76 arquivos), Django e consistência das migrations aprovados.
- Navegador: fluxo completo em desktop/celular com empresa fictícia; cancelamento, exclusão, lista sem o pedido e remoção dos três arquivos sintéticos conferidos. Servidor e navegador de prévia encerrados; nenhuma consulta real à SEFAZ ou exclusão de dados do cliente.
