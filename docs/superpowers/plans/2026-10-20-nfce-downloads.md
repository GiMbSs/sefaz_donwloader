# Downloads NFC-e — Implementation Plan

> **For agentic workers:** usar executing-plans, execução inline, testes antes do código e revisão independente final.

**Goal:** adicionar NFC-e modelo 65 em XML/TXT ao fluxo ATF existente, com identificação FIS_1484 e espera persistente para anexos demorados.

**Architecture:** pedidos continuam de um único modelo, explicitado no banco, formulário, histórico e idempotência. Políticas podem selecionar NF-e, NFC-e ou ambos, criando pedidos separados por modelo. Reusar autenticação, leases e barreiras. Perfil do documento define endpoint, remetente e limites de espera; anexos só são publicados após conferir o modelo solicitado.

**Tech Stack:** Django/Celery/PostgreSQL/requests/lxml existentes; sem nova dependência.

**Spec:** guia NFC-e fornecido pelo usuário em 20/10/2026 e decisões abaixo.

## Global Constraints

- NFC-e: endpoint público `https://www.sefaz.pb.gov.br/servirtual/documentos-fiscais/nfc-e/consulta-por-emitente`; iframe observado aponta `/atf/fis/FISf_ConsultaGenericaEmitenteNFCe.do`.
- Certificado A1 individual, emitente CNPJ, datas inicial/final e XML/TXT, mesma caixa de mensagens e download por anexo da NF-e.
- Distinguir `FIS_1484` de `FIS_1322` em todos os filtros e na correlação; não fixar a quantidade de mensagens no grupo.
- Preservar todos os pedidos/agendamentos NF-e existentes; novos campos têm default NF-e, sem ativar NFC-e implicitamente.
- Decisão técnica: NFC-e dividida em dias completos ou no próprio intervalo diário solicitado, janela de geração de 7 dias configurável, polling crescente entre 60 s e 15 min enquanto saudável. Manter consulta mínima global à caixa e não dormir no worker.
- Pedidos manuais e agendados permanecem em espera por geração durante toda a janela, inclusive após 24 h. O scheduler recupera etapas vencidas. Após prazo final, pedido manual requer retomada; agendado segue reagendamento longo existente sem reenviar POST incerto/aceito.
- Persistir candidatos pendentes; quando um grupo ainda tem mensagens pendentes, não finalizar antecipadamente por já existir um anexo em outro filho.
- Limites de ZIP permanecem configuráveis e não serão desativados por alto volume. Preservar hierarquia CNPJ/formato/data/pedido/parte; o modelo é distinguido pelo pedido, metadados e nome do ZIP, sem alterar caminhos existentes.
- XML e TXT devem conter modelo 65 para pedidos NFC-e e modelo 55 para NF-e; conservar número da nota, identidade e período. TXT original intocado.
- Não migrar banco do cliente, alterar certificados reais ou implantar nesta implementação. Eventual inspeção autenticada de formulário será somente leitura, sem enviar consulta.

## Review Focus

1. NF-e/NFC-e da mesma empresa e período não se coalescem nem trocam anexos.
2. Grupo FIS_1484 pode existir antes do anexo, demorar dias e ter quantidade variável de filhos; resultado parcial não encerra coleta enquanto há pendência explícita.
3. Worker reiniciado, sessão expirada, timeout de POST e atraso de geração não reenviam uma consulta já aceita.
4. ZIP/TXT de modelo errado ou outra empresa é rejeitado antes da publicação; múltiplos anexos são processados idempotentemente.
5. Migração mantém os pedidos/agendamentos NF-e e novas seleções são aplicadas nos modos manual e automático.

## Task 1 — Modelo e divisão de períodos

Arquivos: `atf/profiles.py`, `download_models.py`, migration nova, `services/periods.py`, `services/downloads.py`, `services/scheduling.py`.

- [x] RED: pedidos 55/65 coexistem no mesmo período; NFC-e tem partes diárias; política aceita ambos e agendamento gera pedidos dos modelos selecionados.
- [x] GREEN: perfis e campos `DownloadRequest.document_model` e `DownloadPolicy.document_models`; identidade inclui modelo, preservando chave antiga de NF-e.
- [x] Verificar migration sem drift e suíte do domínio/agendamento.

## Task 2 — Cliente, correlação e espera

Arquivos: `atf/client.py`, `forms.py`, `messages.py`, `correlation.py`, `services/leases.py`, `downloads.py`, configuração.

- [x] RED: endpoint/formulário NFC-e, FIS_1484, remetentes misturados, grupo com pendência e anexo, anexo liberado após 24 h, timeout incerto sem reenvio.
- [x] GREEN: perfil no lookup/submissão, parsing/correlação por modelo, espera persistida e polling progressivo com prazo maior de NFC-e.
- [x] Verificar reinício/atraso e barreiras no fluxo real sintético, sem rede fiscal.

## Task 3 — Artefatos e operação

Arquivos: `services/artifacts.py`, `documents.py`, formulários/telas de operação, `probe_atf_pb`, templates.

- [x] RED: XML/TXT modelo 65 aceitos com número; 55/65 incompatível rejeitado; formulário/política/histórico mostram modelo.
- [x] GREEN: propagar modelo na validação/indexação/revalidação, permitir escolha manual e automática, exibir e filtrar tipo de documento.
- [x] Verificar acesso por escritório e múltiplos anexos.

## Task 4 — Verificação e documentação

- [x] Documentar parâmetros de espera, limites e diagnóstico; atualizar escopo NF-e/NFC-e.
- [x] Executar suíte SQLite/PostgreSQL, Ruff, mypy, Django checks e migrations de instalação/atualização.
- [ ] Revisão independente final e correção de problemas importantes com testes RED/GREEN.

Revisão independente parcial: identificou conclusão prematura quando um filho pendente continha o período solicitado, mas não a expressão de processamento. Caso reproduzido em teste RED, corrigido e validado GREEN. O revisor atingiu o limite de uso antes de concluir a revisão completa.

Inspeção autenticada A1 do formulário NFC-e concluída somente em leitura. Não houve nova solicitação fiscal nem download real NFC-e. Evidência e limites operacionais em `docs/IMPLEMENTACAO-NFCE-PB.md`.

Verificação final: SQLite 148 passaram / 1 ignorado (locks exclusivos PostgreSQL); PostgreSQL descartável 149 passaram; Ruff e formatação 123 arquivos; mypy 83 arquivos; Django check sem problemas; makemigrations sem alterações; git diff --check sem erros. Migração 0013→0015 testada preservando política ativa, pedido NF-e e chave existente.
