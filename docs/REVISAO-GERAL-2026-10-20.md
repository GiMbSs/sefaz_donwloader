# Revisão geral do projeto — 20/10/2026

## Escopo

Revisão do fluxo SEFAZ-PB para NF-e e NFC-e, autenticação A1, uploads de certificados, pedidos manuais e programados, associação de mensagens, retomadas, permissões, interface e armazenamento. Os testes usam dados sintéticos e bancos descartáveis; esta revisão não cria consultas na SEFAZ nem modifica certificados ou pedidos do cliente.

## Correções

| Problema encontrado | Alteração |
| --- | --- |
| Um A1 de outra empresa ou ainda fora da validade podia substituir o certificado ativo. | Conferência do CNPJ e de todo o intervalo de validade antes da substituição. |
| Um upload vencido podia absorver uma nova tentativa de envio. | Expiração e descarte do envelope antigo antes de aceitar o novo arquivo. |
| Falha ao publicar o upload na fila escapava após a confirmação no banco. | Tratamento da falha com diagnóstico sem credenciais, preservação do envelope cifrado e recuperação periódica dos uploads pendentes ainda válidos. |
| Retomar um pedido antigo enquanto um equivalente estava ativo provocava erro de unicidade. | Serialização por empresa e mensagem de validação, preservando o pedido em andamento. |
| Worker e retomada podiam adquirir bloqueios em ordem inversa e travar no PostgreSQL. | A retomada bloqueia as partes antes do pedido; consultas com relações carregadas bloqueiam somente a parte necessária. |
| Uma busca numérica longa podia provocar erro interno. | Busca pelo número da nota limitada aos nove dígitos previstos; pesquisa por chave de acesso preservada. |
| O CNPJ composto apenas por zeros passava pela validação matemática. | Rejeição explícita desse identificador. |

Metadados ausentes nas mensagens não passam a ser prova de identidade: múltiplos candidatos continuam exigindo conferência. A validação do conteúdo dos anexos permanece obrigatória.

## Limpeza e desempenho

- Removido o template `operations/home.html`, sem rota ou uso e com informação obsoleta sobre a integração.
- Removido o wrapper sem uso `artifacts.revalidate_archive`; a ação de revalidação continua utilizando `documents.index_archive` por meio da task existente.
- Removido um bloco vazio de `TYPE_CHECKING` no armazenamento fiscal.
- A task antiga `poll_download_part` delega ao processamento atual; seu nome continua aceito para mensagens já enfileiradas.
- A consulta de documentos deixa de carregar todas as versões XML, que não são exibidas na listagem.
- O dashboard conta pedidos em espera diretamente no banco, sem carregar todos os registros e suas empresas.

Migrations históricas e leitores do cofre usados por elas foram mantidos. Rotas antigas que respondem como desativadas também permanecem para impedir a execução de operações retiradas. Essas referências não representam um motor NSU/SOAP em atividade.

## Comportamentos preservados

Downloads manuais e automáticos continuam enviando o período completo uma vez por formato, com separação por modelo, histórico e usuário solicitante. A espera prolongada de NFC-e, os reagendamentos, as barreiras contra reenvio incerto e a separação por escritório permanecem.

Não há mudança de esquema do banco nesta revisão. Reiniciar os serviços com a imagem atualizada aplica as mudanças de código.

## Validação

- Suíte completa no PostgreSQL descartável: **284 testes passaram**, incluindo concorrência entre worker e retomada e os bloqueios das consultas com relações.
- Suíte completa no SQLite descartável: **278 testes passaram**; seis testes de bloqueio exclusivos de PostgreSQL foram ignorados nesse banco e executados no PostgreSQL.
- As regressões foram reproduzidas antes das correções. Não foram realizadas solicitações fiscais nesta revisão.
- Ruff e formatação aprovados; mypy sem erros em 84 arquivos; verificações do Django, ausência de migrations novas e configuração do Docker Compose aprovadas.

## Limites

Esta revisão não substitui uma validação ao vivo do portal nem o smoke do A1/ACL no Windows. A conferência de XML continua estrutural e de identidade, com schema pendente; não passa a validar assinatura digital ou XSD completo.

Os exemplos observados de mensagens permitem conferir remetente, período e anexos, mas não comprovam campos de CNPJ/formato no corpo da mensagem. Por isso, esses campos não são inferidos de texto livre: a identidade é conferida no conteúdo do ZIP. Um anexo incompatível continua exigindo revisão; esta revisão não automatiza sua substituição por outro grupo de mensagens.
