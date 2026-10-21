# Cancelar e excluir pedidos

Administradores do escritório podem administrar pedidos das suas empresas. Superusuários podem administrar todos os pedidos. Operadores não têm acesso às ações, inclusive pelas URLs diretas.

## Cancelar

No detalhe do pedido, use **Cancelar pedido**, informe o motivo e confirme. Todas as partes ainda não concluídas, inclusive XML e TXT, serão canceladas. Partes concluídas e arquivos baixados permanecem disponíveis nesta etapa. Pedidos já concluídos ou sem notas não oferecem cancelamento.

O cancelamento é local. Uma consulta que já foi enviada pode continuar sendo processada pela SEFAZ-PB. Um worker em execução reconhece o encerramento na próxima verificação; tarefas antigas não reativam o pedido. O sistema não tenta interromper à força uma conexão HTTP em andamento. A retomada daquele pedido é desabilitada.

O cancelamento de um pedido agendado não desativa a política da empresa. Para parar futuras execuções, ajuste o agendamento.

## Excluir pedido cancelado

Após cancelar, use **Excluir pedido cancelado**, informe o motivo e confirme. O pedido deixa de aparecer nas listas, no dashboard e na página da empresa.

- ZIPs, XMLs e TXTs exclusivos do pedido são removidos, incluindo seus vínculos locais e notas/versões sem outra origem.
- Arquivos e notas que também são utilizados por outros pedidos são preservados. As referências são conferidas novamente imediatamente antes da remoção física.
- O registro mínimo do pedido e a auditoria administrativa são mantidos. A exclusão não altera dados na SEFAZ.

A remoção física é executada pelo worker em lotes de até 500 arquivos. Novos lotes são encaminhados em seguida; falhas de armazenamento e publicações perdidas são recuperadas pelo scheduler a cada minuto. A limpeza prioriza pedidos com menos tentativas para evitar que falhas persistentes bloqueiem outros pedidos.

Em PostgreSQL, publicadores de arquivos usam uma trava compartilhada de armazenamento e a limpeza usa a mesma trava em modo exclusivo, por transação. Isso também protege arquivos em pastas antigas quando uma empresa muda de escritório ou CNPJ. As travas de partes da limpeza não incluem as linhas dos pedidos relacionados.

## Acompanhar a limpeza

O worker registra `event=atf_file_cleanup` com `request_id`, `removed`, `shared` e `pending`. Uma falha ao publicar a limpeza registra `atf_file_cleanup_dispatch_failed`; a tarefa permanece no banco para recuperação.

No painel técnico `/admin/`, os registros `DownloadFileDeletion` são somente para leitura, limitados ao escritório autorizado. `completed_at` vazio indica pendência; `storage_unavailable` indica falha de armazenamento; `shared` indica referência preservada por outro pedido.

## Atualizar a instalação

Esta funcionalidade adiciona a migration `fiscal.0016_download_cancellation`. Atualize as imagens e execute as migrations antes de iniciar os serviços com o novo código. O Compose já contém o serviço `migrations`:

```bash
docker compose build web worker scheduler migrations
docker compose run --rm migrations
docker compose up -d web worker scheduler
```

Não é necessário remover volumes, banco ou filas.
