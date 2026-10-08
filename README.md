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
PFX/P12 de até 5 MB. Cada solicitação de sincronização é registrada antes de
ser enviada ao worker: somente ele abre o certificado, faz a chamada mTLS e
arquiva o SOAP e o retorno de distribuição. A requisição HTTP nunca consulta a
SEFAZ diretamente.

Uma tarefa já em execução não é consultada novamente em uma redelivery. Se a
comunicação ou a persistência do retorno não puder ser confirmada, a solicitação
falha e o cursor recebe uma espera conservadora de uma hora; não há nova
consulta automática. Analise o histórico, o lote arquivado e o estado do NSU
antes de criar uma nova solicitação. Nunca ajuste o NSU manualmente nem use um
cursor arbitrário para "recuperar" documentos.

A execução em produção continua dependendo de certificado autorizado, ambiente
correto, volume persistente e teste controlado. Esta implementação não é
evidência de cobertura de NFC-e ou de operação homologada/produção.

## Pré-validação antes de homologar

Depois de iniciar os containers e antes de qualquer consulta fiscal, execute no
worker:

```bash
docker compose exec worker python manage.py verify_fiscal_installation --worker --write-notes-probe
```

O comando verifica conexão com o banco, migrations, checksums dos schemas
locais, chaves de certificado e leitura/escrita atômica no volume de notas. A
sonda de escrita é removida ao fim e o comando nunca faz uma chamada à SEFAZ.
Corrija qualquer falha antes de realizar uma homologação controlada.

O transporte fiscal começa bloqueado. Somente após essa pré-validação, habilite
explicitamente o ambiente de homologação no `.env` com
`SEFAZ_ENABLED_ENVIRONMENTS=homologation` e reinicie o worker. Não habilite
`production` sem a evidência de homologação e a autorização operacional
registradas.

Consulte [o PRD](docs/PRD-IMPLEMENTACAO.md) antes de habilitar qualquer fluxo
fiscal em ambiente de produção.
