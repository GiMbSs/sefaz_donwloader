# SEFAZ Downloader

Aplicação local para escritórios de contabilidade obterem e organizarem DF-e
com segurança operacional. A primeira implantação é voltada à Paraíba.

## Desenvolvimento local com Docker

1. Copie `.env.example` para `.env` e substitua todos os segredos e caminhos
   absolutos do computador hospedeiro.
2. Crie, com permissões adequadas, as pastas indicadas em `NOTES_HOST_DIR`,
   `CERTIFICATES_HOST_DIR` e `CERTIFICATE_PUBLIC_HOST_DIR`. A última contém
   somente a chave pública que protege envios de certificados; o worker cria
   esse arquivo na primeira inicialização.
3. Execute `docker compose up --build`.
4. Acesse `http://127.0.0.1:8000/health/` para verificar a aplicação.

O web container recebe o PFX e a senha somente durante o POST, cifra ambos
com a chave pública do worker e não monta o cofre de certificados. O envelope
é apagado após êxito, falha ou expiração. O serviço `migrations`, que tem acesso
ao cofre privado, prepara as chaves e o banco antes de iniciar os demais serviços.

Após a validação, cada empresa possui sua própria pasta privada em
`clientes/<id-da-empresa>/certificados/`. O PFX e a credencial recuperável para
assinatura ficam cifrados em arquivos nessa pasta; o banco persiste apenas o
hash da senha (`password_hash`) para verificação, nunca a senha reversível.
Certificados, senhas e chaves privadas nunca devem entrar no repositório, em
variáveis de exemplo ou em logs.

O proxy publicado em `127.0.0.1` limita uploads a 6 MB; o formulário aceita
PFX/P12 de até 5 MB. A integração SEFAZ real ainda não é ativada nesta fundação.

Consulte [o PRD](docs/PRD-IMPLEMENTACAO.md) antes de habilitar qualquer fluxo
fiscal em ambiente de produção.
