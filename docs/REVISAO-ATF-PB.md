# Revisão independente — 20/10/2026

Revisão de toda a implementação ATF-PB, incluindo alterações ainda sem commit, contra o plano e a revisão de requisitos de 20/10/2026. Não houve acesso ao portal, certificados ou banco do cliente.

O revisor identificou três problemas importantes, todos reproduzidos com testes falhando antes das correções:

1. Tarefa duplicada sem lease podia sobrescrever o estado concluído. A aquisição recusada agora apenas relê o estado; transições de espera exigem lease válido e conferência da linha bloqueada. As verificações de empresa/política também ocorrem após aquisição do lease.
2. Scheduler recuperado após indisponibilidade ignorava ocorrências anteriores. Agora deriva as ocorrências desde o checkpoint persistido, com limite de 366 datas por ciclo para permitir recuperação gradual. Testes cobrem frequências diária, semanal e mensal e ausência de duplicação.
3. Corrupção no bloco comprimido do ZIP podia escapar da classificação de erro. Erros de descompressão são convertidos em erro de artefato e o staging é removido em `finally`, inclusive se a validação ou indexação falhar.

As correções passaram na suíte completa em PostgreSQL descartável: 123 testes aprovados. A suíte SQLite e as verificações estáticas estão registradas em `IMPLEMENTACAO-ATF-PB.md`.

Limitações aceitas e documentadas: ausência de XSD completo/validação de assinatura, smoke Windows de TLS/ACL pendente, contratos ainda não observados de paginação JavaScript e confirmação definitiva de resposta sem dados. A preservação do histórico fiscal anterior foi dispensada pelo usuário.
