# Armazenamento fiscal compacto

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Salvar novos arquivos em `<CNPJ-escritório>/<CNPJ-empresa>/NFe|NFCe/XML|TXT/AAAA-MM-DD/`, usando a data original da solicitação.

**Architecture:** Um helper fiscal define a pasta. O ZIP mantém o nome original SEFAZ, e conteúdos extraídos usam hash completo para preservar versões. Colisões de nome com conteúdo diferente usam `versoes/<SHA-256>/<nome-original.zip>`; o basename original é preservado. Caminhos já persistidos continuam válidos; certificados não mudam de lugar.

**Tech Stack:** Python, Django, pathlib, armazenamento atômico existente.

**Spec:** Estrutura aprovada na conversa em 20/10/2026, com data única como `2026-10-20` e referência à data da solicitação.

## Global Constraints

- Manter isolamento por CNPJ do escritório e da empresa, além de modelo e formato.
- A data vem de `DownloadRequest.requested_on`, inclusive em retomadas em outro dia.
- Não mover arquivos existentes, modificar certificados, enviar consultas SEFAZ ou exigir migração de banco.
- Preservar ZIP e bytes XML/TXT originais, versões distintas e histórico dos pedidos.
- Manter o nome original do ZIP recebido da SEFAZ; o arquivo temporário usado no recebimento é independente. Só usar nome por hash quando não houver nome original utilizável.
- Manter a task de revalidação e o acesso aos caminhos antigos.

## Review Focus

- NF-e e NFC-e da mesma empresa e dia não devem se misturar.
- Pedidos repetidos e diferentes versões não podem sobrescrever conteúdo distinto.
- O mesmo CNPJ em escritórios diferentes deve permanecer isolado.
- Retomada/reindexação não deve trocar a data por emissão ou processamento.
- Reindexar arquivo antigo deve respeitar os caminhos dos membros já registrados.

### Task 1: Pasta compacta e publicação dos arquivos

**Files:** `apps/fiscal/services/storage.py`, `artifacts.py`, `documents.py`; `tests/test_download_documents.py`, novo `tests/test_compact_fiscal_storage.py`.

**Interfaces:** `download_storage_directory(company, *, document_model, format, requested_on) -> Path`; `persist_archive` e `index_archive` mantêm suas interfaces públicas.

- [x] Escrever testes de publicação/leitura real para ambos os modelos e formatos, isolamento por escritório, data original, versões distintas, idempotência e caminhos antigos.
- [x] Executar os testes e confirmar falhas da estrutura antiga.
- [x] Implementar o helper e a nova pasta de ZIP; extrair membros diretamente na pasta, reutilizando caminhos já registrados.
- [x] Executar regressões específicas e suíte completa, Ruff, mypy, Django e verificação de migrations.
- [x] Atualizar README, guia operacional e descrição do produto; registrar evidências neste plano.
- [x] Solicitar revisão independente das mudanças e resolver achados relevantes.

## Execução

Implementação na workspace atual, preservando as correções da revisão geral ainda não commitadas e a alteração preexistente de `.dockerignore`. Não criar commit ou mover dados do cliente automaticamente.

Evidências: 12 falhas esperadas antes da implementação; 18 testes específicos passaram após a correção. Suíte completa SQLite: 289 passaram e seis testes exclusivos de bloqueios PostgreSQL foram ignorados. Ruff, formatação, mypy (84 arquivos), verificações Django e ausência de migrations novas aprovados. Revisão independente sem achados bloqueantes. Sem consultas remotas ou movimentação de arquivos do cliente.

## Complemento: nome original do ZIP

O nome recebido em `Content-Disposition` é preservado na pasta externa e na interface. Há suporte a `filename` e `filename*`, incluindo espaços e caracteres UTF-8. Um nome válido do anexo é usado como fallback; sem nome utilizável, mantém-se a identificação por hash. Não são aceitos caminhos remotos como nomes locais.

A publicação é atômica e não substitui outro arquivo: conteúdo idêntico pode reutilizar o ZIP existente; conteúdo diferente com o mesmo nome vai para `versoes/<SHA-256>/<nome-original.zip>`. O temporário de recebimento é independente, e o tratamento não modifica o ZIP publicado.

As novas regressões falharam antes da implementação. Após a correção, 46 testes específicos passaram; a suíte completa passou com 304 testes e seis testes exclusivos de PostgreSQL ignorados. Ruff, formatação, mypy (85 arquivos), Django e ausência de migrations novas aprovados. Revisão independente sem achados bloqueantes.

Sondas de filesystem: criação de hard link no volume montado da workspace aprovada, com remoção dos arquivos sintéticos. A sonda completa nesse volume foi interrompida no `chmod` pelo sandbox; a tentativa adicional fora do sandbox não foi executada porque a revisão automática de permissão expirou. O fluxo completo de publicação foi validado no filesystem temporário da suíte. Nenhum arquivo do cliente foi usado ou alterado.
