# SEFAZ Downloader

Estação de trabalho web para escritórios de contabilidade organizarem a coleta
de DF-e de empresas clientes com rastreabilidade. A primeira implantação usa a
distribuição nacional de NF-e (modelo 55); NFC-e e documentos de saída exigem
validação operacional específica antes de serem anunciados como cobertos.

O sistema não emite notas, não manifesta documentos automaticamente e não
automatiza portais, CAPTCHA ou navegação humana da SEFAZ.

## O que o sistema faz

- Cadastra, edita, inativa e arquiva empresas clientes por escritório.
- Marca cada empresa como **Homologação** ou **Produção**.
- Recebe certificado A1 (`.pfx`/`.p12`) e senha durante o cadastro ou em uma
  substituição posterior.
- Agenda sincronizações silenciosas por empresa, com recorrência diária,
  semanal ou mensal.
- Cria pedidos manuais idempotentes e executa a comunicação fiscal somente no
  worker assíncrono.
- Arquiva SOAP, lotes e XMLs originais e permite baixar XMLs a usuários
  autorizados.
- Registra auditoria e alertas para bloqueios, falhas e certificados
  indisponíveis.

## Limites fiscais importantes

- O fluxo usa `NFeDistribuicaoDFe` e `ultNSU`. Ele não prova cobertura de
  documentos emitidos pela própria empresa cliente.
- A resposta `cStat=137` e bloqueios `cStat=656` impõem uma espera mínima de
  uma hora; o sistema nunca escolhe ou retrocede um NSU manualmente.
- Produção só deve ser habilitada após homologação controlada, validação do
  certificado e aprovação operacional registrada.
- Arquivar uma empresa não apaga XMLs, lotes, certificado cifrado nem auditoria.
  A preservação fiscal continua obrigatória.

## Arquitetura operacional

```text
Navegador -> Django web -> PostgreSQL
                         -> Redis <- scheduler (Celery Beat)
                                        |
                                      worker fiscal -> SEFAZ
                                           |
                    cofre privado de certificados + volume de notas
```

- `web`: autenticação, telas, autorizações, auditoria e download autorizado.
- `scheduler`: identifica políticas elegíveis a cada cinco minutos.
- `worker`: abre certificados, consulta a SEFAZ, processa XML e grava arquivos.
- `postgres` e `redis`: respectivamente, estado transacional/auditoria e fila.

O servidor web não consulta a SEFAZ e não monta o cofre privado de
certificados.

## Estrutura de arquivos por empresa

Os volumes de documentos e de certificados permanecem separados para que o
cofre nunca fique disponível via HTTP. Ambos usam a mesma raiz lógica,
separada por escritório e empresa:

```text
<volume>/escritorios/escritorio_<cnpj-do-escritorio>/
  empresa_<cnpj-da-empresa>/
    certificado/     # apenas no volume privado; PFX e senha cifrados
    xmls/             # apenas no volume de notas; ano/mes/modelo/chave.xml
    lotes/            # respostas de distribuição recebidas
    soap/             # envelopes/respostas SOAP arquivados
    txt/              # reservado para relatórios TXT versionados
```

Exemplo de pasta da empresa: `empresa_00000000000191`. O CNPJ, e não a razão
social, compõe o nome para que uma edição cadastral não mova ou quebre os
arquivos. As pastas são criadas de forma atômica quando o worker grava o
primeiro artefato. O segmento do escritório evita mistura de arquivos caso a
mesma instalação atenda a mais de uma contabilidade.

Os relatórios TXT de NF-e/NFC-e ainda são uma fase própria: a pasta `txt/` está
reservada, mas o sistema não promete baixar ou interpretar TXT sem um canal
oficial e layout confirmado. Consulte
[o plano de relatórios TXT](docs/PLANO-RELATORIOS-TXT-EMITIDOS.md).

## Certificado e senha

No cadastro da empresa, o certificado A1 e a senha são opcionais; quando ambos
são informados, são encaminhados cifrados ao worker para validação. Também é
possível enviar ou substituir o certificado pela tela da empresa.

Após validar o PFX, o sistema:

1. Guarda no banco somente `password_hash`, produzido pelo hasher do Django.
2. Grava uma cópia cifrada recuperável da senha e o PFX cifrado no cofre
   privado, pois a automação precisa abrir o PFX sem interação humana.
3. Mantém a chave mestra fora do banco, do repositório, da imagem Docker e dos
   logs.
4. Apaga o envelope temporário de upload após êxito, falha ou expiração.

Um hash sozinho não permite abrir um certificado. Por isso a cópia cifrada
recuperável fica exclusivamente no cofre do worker; a senha nunca é gravada em
texto no banco.

## Cadastro e ciclo de vida da empresa

1. No primeiro acesso, entre com o superusuário e abra **Empresas → Cadastrar
   escritório contábil**. Esse passo cria o tenant e vincula o administrador
   responsável.
2. Em seguida, o sistema abre **Cadastrar empresa**. Informe CNPJ, UF, ambiente
   fiscal e situação.
   - Para empresa que já tem distribuição em outro sistema, informe o último
     NSU processado. A próxima consulta continuará após ele; o valor é gravado
     uma única vez, antes de qualquer solicitação fiscal.
   - Use **Homologação** para testes controlados.
   - Use **Produção** apenas para uma empresa autorizada e infraestrutura já
     liberada.
3. Opcionalmente, anexe o A1 e informe a senha no mesmo cadastro.
4. Abra a empresa e configure a política de sincronização.
5. Ative a política somente depois de verificar certificado, ambiente e janela
   operacional.

Para uma empresa já cadastrada sem histórico no sistema, use **Definir NSU
inicial** na página da empresa antes da primeira solicitação. A tela exige a
confirmação do CNPJ e o aceite da irreversibilidade para evitar uma consulta
acidental desde o início da sequência.

Situações disponíveis:

- **Ativa**: pode receber pedidos manuais e agendados, desde que a política
  também esteja ativa.
- **Inativa**: bloqueia novas sincronizações, mantendo todo o histórico.
- **Arquivada**: resultado da ação “Excluir (arquivar)”; desativa a política e
  retira a empresa da operação diária, sem apagar evidências fiscais.

Para arquivar, a interface mostra o aviso de risco, exige a confirmação do
CNPJ e o aceite de retenção. Essa ação é auditada. Alterar o ambiente depois de
existirem controles NSU ou pedidos fiscais é bloqueado para não misturar os
históricos de homologação e produção.

## Política automática de download

Uma empresa ativa pode ter uma política:

| Modo | Comportamento |
| --- | --- |
| Automática | Somente o scheduler cria pedidos no horário programado. |
| Híbrida | Scheduler e pedido manual autorizado. |
| Manual | Somente pedido manual autorizado. |

A recorrência automática pode ser:

- **Diária**: uma vez por dia no horário e fuso configurados.
- **Semanal**: nos dias da semana selecionados.
- **Mensal**: no dia definido. Se o dia não existir no mês, executa no último
  dia daquele mês.

O scheduler roda silenciosamente em processo próprio e somente enfileira o
pedido. O worker ainda verifica situação da empresa, política, bloqueios NSU,
certificado e se o ambiente foi explicitamente liberado antes de qualquer rede
com a SEFAZ. Não há chamada fiscal dentro da requisição HTTP.

## Desenvolvimento local com SQLite

Use SQLite apenas para desenvolvimento. No PowerShell, defina a variável na
mesma sessão antes dos comandos Django:

```powershell
$env:DEV_MODE = "True"
python manage.py migrate
python manage.py runserver
```

No Bash/WSL:

```bash
export DEV_MODE=True
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

Isso cria `dev.sqlite3` (ignorado pelo Git) e usa por padrão a pasta privada
`.sefaz_downloader` no perfil do usuário para notas, chaves e cofre local. O
`.env` é lido pelos comandos diretos, e as variáveis do terminal ainda têm
prioridade. Defina `DEV_STORAGE_ROOT` se precisar de outro local privado.
`DEV_MODE` não libera tráfego fiscal por si só. Para uma homologação controlada,
configure explicitamente `SEFAZ_ENABLED_ENVIRONMENTS=homologation`; não inclua
`production` nessa variável.

Antes do primeiro envio de certificado A1 no ambiente local, gere as chaves uma
única vez:

```bash
.venv/bin/python manage.py generate_certificate_key --if-missing
.venv/bin/python manage.py generate_certificate_upload_keypair --if-missing
```

No PowerShell, use `python` ou `.venv\Scripts\python.exe` com os mesmos
subcomandos. As chaves ficam no diretório privado de desenvolvimento; não as
copie para o repositório.

Com `DEV_MODE=True`, o processamento do A1 é executado logo após o commit da
requisição, sem Redis ou worker. Isso serve apenas para validar o fluxo local;
as solicitações fiscais continuam a ser executadas exclusivamente pelo worker
e dependem de uma liberação explícita do ambiente.

Para testar uma solicitação fiscal pelo `runserver` local, inicie o Redis do
Compose e o worker no mesmo ambiente virtual. A porta do Redis é publicada
somente em `127.0.0.1`:

```powershell
docker compose up -d redis
celery -A config worker --loglevel=INFO
```

Mantenha os dois processos ativos durante a solicitação. O `runserver` usa por
padrão `redis://127.0.0.1:6379/0`; não altere essa URL para apontar ao nome de
serviço `redis`, que só é resolvido entre containers.

## Instalação local com Docker

1. Copie `.env.example` para `.env`.
2. Defina segredos fortes, banco e caminhos absolutos no computador hospedeiro:
   `NOTES_HOST_DIR`, `CERTIFICATES_HOST_DIR` e
   `CERTIFICATE_PUBLIC_HOST_DIR`.
3. Crie esses diretórios com permissões restritas. O diretório de certificados
   não deve ser compartilhado, sincronizado em nuvem ou incluído em backup sem
   criptografia.
4. Suba a instalação:

   ```bash
   docker compose up --build
   ```

5. Verifique a saúde em `http://127.0.0.1:8000/health/`.
6. Crie o primeiro administrador, se ainda não existir:

   ```bash
   docker compose exec web python manage.py createsuperuser
   ```

O serviço `migrations` prepara chaves privadas e aplica migrations antes dos
serviços dependentes. O web recebe um envelope de upload cifrado, enquanto
somente o worker possui a chave privada e o cofre.

## Variáveis operacionais principais

| Variável | Uso |
| --- | --- |
| `POSTGRES_*`, `DB_HOST`, `DB_PORT` | Banco de produção/container. |
| `REDIS_URL` | Fila Celery e scheduler. |
| `NOTES_HOST_DIR` | Diretório host para `xmls`, `lotes`, `soap` e futuro `txt`. |
| `CERTIFICATES_HOST_DIR` | Cofre privado com PFX e senha cifrados. |
| `CERTIFICATE_ENCRYPTION_KEY_FILE` | Chave mestra do cofre; nunca versionar. |
| `SEFAZ_ENABLED_ENVIRONMENTS` | Ambientes que o worker pode consultar. Inicia vazio. |
| `DEV_MODE=True` | Somente desenvolvimento direto: usa `dev.sqlite3`. |

Para a primeira homologação controlada, configure somente:

```dotenv
SEFAZ_ENABLED_ENVIRONMENTS=homologation
```

Reinicie o worker depois da alteração. Não inclua `production` sem a aprovação
e as evidências descritas em [Operação e homologação](docs/OPERACAO-HOMOLOGACAO.md).

## Verificação antes de habilitar SEFAZ

Execute no worker, antes de qualquer consulta externa:

```bash
docker compose exec worker python manage.py verify_fiscal_installation --worker --write-notes-probe
```

O comando valida migrations, banco, schemas locais, chaves do cofre e escrita
atômica no volume de notas. A sonda é removida no final e não faz chamada à
SEFAZ.

## Monitoramento e recuperação

- A tela da empresa mostra certificado, política, controles NSU, fila, lotes e
  documentos recentes.
- A página **Alertas** concentra falhas de transporte, certificado e bloqueios.
- Lotes com falha local podem ser reprocessados a partir da resposta arquivada;
  essa operação não consulta a SEFAZ novamente.
- Em uma falha incerta de rede ou persistência, o sistema conserva uma espera de
  uma hora antes de nova consulta. Revise o lote e o alerta antes de prosseguir.

Faça backup consistente do PostgreSQL e dos dois volumes privados. Restaurar
somente o banco sem `NOTES_HOST_DIR` ou `CERTIFICATES_HOST_DIR` não recupera os
arquivos associados. Não elimine XMLs antes da política de retenção fiscal
aplicável; para a Paraíba, a referência inicial é 132 meses para os DF-e
abrangidos.

## Testes e checagens

Com o ambiente virtual ativo:

```bash
DEV_MODE=True .venv/bin/python manage.py check
DEV_MODE=True .venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/ruff check . --no-cache
DEV_MODE=True .venv/bin/pytest
```

Em PowerShell, substitua a primeira forma por `$env:DEV_MODE = "True"` e use
os executáveis em `.venv\Scripts\`.

Consulte também [o PRD](docs/PRD-IMPLEMENTACAO.md) para escopo, regras fiscais
e fases de evolução.
