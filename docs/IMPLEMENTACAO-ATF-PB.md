# Execução da migração ATF-PB

Plano: `docs/superpowers/plans/2026-10-19-atf-pb-migration.md`, com diretrizes revisadas pelo usuário em 20/10/2026. Operação: `docs/OPERACAO-ATF-PB.md`.

## Resultado da implementação

- Cliente ATF-PB autenticado com A1 individual, formulários restritos, identidade de conta, caixa de mensagens e downloads ZIP.
- Domínio de políticas, pedidos, partes, tentativas, anexos, notas, versões e eventos. Barreiras persistentes evitam repetição de POST incerto; leases coordenam workers e contas compartilhadas.
- Agendamento programável mantido com modo, frequência, horário, fuso, dias, ativação e períodos explícitos. Ocorrências perdidas por indisponibilidade são recuperadas desde o checkpoint.
- Lentidão tratada com timeout configurável, heartbeat, tentativas curtas e novo ciclo persistido para pedidos agendados após esgotamento. Desativação da política impede execução futura desses pedidos.
- XML analisado no download com conferência de empresa, modelo, período, chave e número `ide/nNF`; número indexado, exibido e pesquisável. Eventos permanecem separados. TXT é conferido pelos campos do contrato observado e preservado sem alteração.
- ZIPs e conteúdos em `escritorios/escritorio_<CNPJ>/empresas/<CNPJ>/XML|TXT/AAAA/MM/DD/<pedido>/<parte>/`, com a data original da solicitação no fuso configurado.
- Histórico completo por empresa, com origem, usuário manual, período, formatos, estado e próxima tentativa. Inputs manuais de data inicial/final obrigatórios.
- Motor nacional SOAP/NSU, modelos, serviços, telas e configurações obsoletos retirados. Gates e recursos de exportação/restauração do legado removidos conforme autorização expressa do usuário.
- Migrations 0009–0012 adicionam/adaptam o novo domínio; fiscal 0013 remove as tabelas antigas e organizações 0006 remove o ambiente fiscal. Cadastros, usuários, certificados e políticas adaptadas permanecem.

## Verificação

- PostgreSQL 17 descartável: **123 testes aprovados**, incluindo concorrência real e atualização das migrations.
- SQLite: **122 testes aprovados, 1 ignorado** por exigir locks reais de PostgreSQL.
- Mypy: **sem erros em 82 arquivos de código**, excluindo migrations históricas da análise estática.
- Ruff: **todos os checks aprovados**.
- `makemigrations --check --dry-run`: nenhuma alteração pendente.
- Instalação vazia ensaiada em SQLite separado de demonstração; nenhuma migration foi executada na base do cliente.
- Playwright: login local sintético, histórico por empresa com origem/usuário/próxima tentativa e formulário com datas e formatos conferidos. Captura local em `output/playwright/atf-company-history.png` (ignorada pelo Git).
- Revisão independente: três problemas importantes reproduzidos e corrigidos; ver `REVISAO-ATF-PB.md`.

## Estado do workspace

Implementação originada em `/mnt/d/py_projetos/sefaz_downloader/.worktrees/atf-pb` e consolidada no diretório principal em 20/10/2026 durante a revisão do frontend. O worktree isolado anterior permanece uma cópia pausada e não deve receber novas alterações. A consolidação atualizou os arquivos de código; não houve implantação, reset, migration em banco do cliente, exclusão de arquivos fiscais ou alteração do cofre real nesta etapa.

## Limites antes da operação real

- Windows: backend TLS/ACL implementado, mas smoke na plataforma permanece pendente.
- XML: validação estrutural e identidade implementadas; XSD completo e assinatura digital não validados. Estado `pending_schema` explícito.
- Paginação JavaScript e confirmação definitiva de resposta sem dados não observadas exigem evidência antes de ampliar o parser.
- Login/download reais foram comprovados na investigação anterior; a implementação atual foi validada offline e em demonstração local, sem novo tráfego ao portal nesta etapa.

O descarte autorizado refere-se aos dados do motor fiscal anterior. Certificados, chaves, cadastros e arquivos do cliente não foram descartados. Aplicar o corte apenas seguindo o guia operacional, com serviços e filas antigas parados.
