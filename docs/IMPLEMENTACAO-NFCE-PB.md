# Downloads NFC-e na SEFAZ-PB

Implementação originada na branch `feat/atf-pb-downloads`, no worktree `.worktrees/atf-pb`, e consolidada no diretório principal em 20/10/2026 durante a revisão do frontend. O código atual está disponível na raiz do projeto.

## Consulta e identificação

O perfil 65 usa `FISf_ConsultaGenericaEmitenteNFCe.do`, componente `FISf_ConsultaGenericaEmitenteNFCe_cmpEmit` e remetente `FIS_1484`. O perfil 55 mantém o endpoint NF-e e `FIS_1322`. A autenticação usa o A1 individual da empresa.

Pedidos manuais exigem modelo, data inicial e final. Políticas automáticas permitem NF-e, NFC-e ou ambos, gerando pedidos separados. Migrações 0014/0015 mantêm os defaults NF-e dos cadastros existentes; a identidade de pedidos NF-e permanece compatível.

## Espera por alto volume

- NFC-e envia o intervalo completo solicitado uma vez por formato (XML e/ou TXT), assim como NF-e. Pedidos manuais e programados seguem a mesma regra.
- `ATF_NFCE_WAIT_TIMEOUT_SECONDS` define a janela de geração: padrão 604800 segundos (sete dias).
- `ATF_POLL_INTERVAL_SECONDS` define o intervalo inicial: padrão 60 segundos. O intervalo cresce a cada três consultas saudáveis até `ATF_NFCE_MAX_POLL_INTERVAL_SECONDS`, padrão 900 segundos.
- Prazo, candidatos, etapas e contador de consultas ficam no banco. Reinícios não perdem a espera. Nenhum POST aceito ou de resultado incerto é reenviado automaticamente.
- O código percorre os filhos e anexos, sem assumir duas mensagens. Um anexo pronto no grupo identificado é baixado sem aguardar que notificações antigas de processamento mudem. Sem anexo disponível, a espera continua; candidatos em grupos diferentes exigem conferência.
- Após esgotar tentativas, pedidos agendados mantêm o reagendamento persistente existente; pedidos manuais permitem retomada explícita. Esperar geração saudável não consome o orçamento de falhas de conexão.

Os limites configuráveis de ZIP continuam ativos. A barreira de conta pode serializar outras partes enquanto uma consulta aguarda geração; é uma proteção conservadora contra associação incorreta de resultados.

## Arquivos e histórico

XML e TXT precisam corresponder ao modelo solicitado, CNPJ e período. O número da nota é indexado; o XML tem conferência estrutural e de identidade, com validação completa de XSD/assinatura ainda pendente e indicada no sistema. O TXT original é preservado.

A estrutura privada por escritório permanece `empresas/CNPJ/XML|TXT/ano/mês/dia-da-solicitação/pedido/parte/arquivo.zip`. O nome de download distingue `nfe` e `nfce`. Histórico, detalhes e lista de documentos identificam o modelo; a lista oferece filtro por NF-e/NFC-e.

## Evidência e limites

Em 20/10/2026, uma inspeção autenticada com A1 confirmou o formulário NFC-e e as opções TXT=2/XML=3. Foi somente leitura: nenhuma nova consulta fiscal ou coleta NFC-e real foi enviada. Os testes automatizados exercitam geração após mais de 24 horas, reinício, resultado incerto, múltiplos anexos e rejeição de modelo incorreto.

O download real de um lote NFC-e ainda precisa de validação operacional. Não foram aplicadas migrações ao banco do cliente. Contratos ainda não observados de paginação JavaScript e confirmação definitiva de resultado vazio continuam exigindo evidência do portal.

Verificação final em banco descartável: 148 testes passaram no SQLite (um teste de locks ignorado) e 149 no PostgreSQL. Ruff, formatação, mypy (83 arquivos), Django check, ausência de drift nas migrações e git diff --check passaram. A atualização 0013→0015 preserva a política ativa, o modelo NF-e e a chave do pedido existente.

A revisão inicial adotou o bloqueio por um filho pendente. A revisão posterior de espera corrigiu essa regra: notificações de processamento permanecem na caixa após a geração do ZIP e não devem bloquear um anexo pronto no mesmo grupo. A regra atual tem regressões com mensagens processadas pelo parser dos dois modelos; veja [espera e retomada](ESPERA-RETOMADA-ATF-PB.md).
