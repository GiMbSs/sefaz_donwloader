# SEFAZ Downloader

Aplicação local para escritórios de contabilidade obterem e organizarem DF-e
com segurança operacional. A primeira implantação é voltada à Paraíba.

## Desenvolvimento local com Docker

1. Copie `.env.example` para `.env` e substitua todos os segredos e caminhos
   absolutos do computador hospedeiro.
2. Crie, com permissões adequadas, as pastas indicadas em `NOTES_HOST_DIR` e
   `CERTIFICATES_HOST_DIR`.
3. Execute `docker compose up --build`.
4. Acesse `http://127.0.0.1:8000/health/` para verificar a aplicação.

O container nunca deve receber certificados ou senhas pelo repositório, por
variáveis de exemplo ou por logs. A integração SEFAZ real ainda não é ativada
nesta fundação.

Consulte [o PRD](docs/PRD-IMPLEMENTACAO.md) antes de habilitar qualquer fluxo
fiscal em ambiente de produção.

