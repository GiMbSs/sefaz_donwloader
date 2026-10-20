# SEFAZ Downloader — SEFAZ-PB

Estação de trabalho local para escritórios contábeis baixarem XML e TXT de NF-e (55) e NFC-e (65) emitidas, por empresa. O certificado A1 individual autentica o acesso ao ATF da SEFAZ-PB; relatórios chegam pela caixa de mensagens em arquivos ZIP.

Pedidos manuais escolhem o modelo e o período. Políticas automáticas podem coletar ambos os modelos. Cada modelo envia o período completo uma vez por formato selecionado (XML e/ou TXT). NFC-e mantém espera persistente de até sete dias, configurável; veja [operação NFC-e](docs/IMPLEMENTACAO-NFCE-PB.md).

## Operação

- Cadastros e permissões separados por escritório, com administradores e operadores.
- Pedidos manuais com data inicial, data final e formatos XML/TXT.
- Downloads automáticos programáveis por horário, fuso e frequência diária, semanal ou mensal; períodos explícitos e recuperação de ocorrências perdidas durante indisponibilidade.
- Histórico completo de pedidos por empresa, origem manual/automática, usuário solicitante, situação e próxima tentativa.
- Leitura segura do XML, identificação da nota pelo número e chave, separação de eventos e preservação dos ZIPs com seus nomes originais e dos bytes XML/TXT.
- Novos arquivos em `<CNPJ-escritório>/<CNPJ-empresa>/NFe|NFCe/XML|TXT/AAAA-MM-DD/`, usando a data da solicitação original; caminhos anteriores continuam acessíveis.
- Timeouts configuráveis, tentativas curtas e reagendamento automático prolongado para falhas transitórias de pedidos agendados. Envios incertos são conciliados antes de qualquer nova submissão.

A integração nacional SOAP, o controle de NSU e a seleção de ambiente fiscal foram retirados. Dados fiscais gerados pelo motor antigo podem ser descartados pelas migrations; cadastros, usuários, certificados e configurações programáveis são mantidos.

## Stack

Python 3.13, Django 6, Celery/Redis, PostgreSQL 17, requests, cryptography e lxml. Interface em português do Brasil. A web não recebe as chaves privadas do cofre; o worker autentica, consulta e grava arquivos privados.

## Instalação local com Docker

Copiar `.env.example` para `.env`, definir credenciais próprias e os diretórios absolutos `NOTES_HOST_DIR`, `CERTIFICATES_HOST_DIR` e `CERTIFICATE_PUBLIC_HOST_DIR`. Certificados e senhas ficam fora do repositório. Não substituir chaves existentes do cofre.

Antes de atualizar uma instalação existente, seguir a janela de manutenção descrita em [Operação ATF-PB](docs/OPERACAO-ATF-PB.md). A migration fiscal 0013 remove as tabelas antigas; não aplicar enquanto workers do motor anterior ainda estiverem ativos.

```sh
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
docker compose exec worker python manage.py verify_fiscal_installation --worker --write-notes-probe
```

O acesso padrão fica em `http://localhost:8000`. `ATF_PB_ENABLED=False` bloqueia tráfego ATF até a configuração ser conferida. Cadastrar o escritório, a empresa e seu certificado A1; reconciliar vínculos antigos do cofre quando necessário. Após habilitar o ATF, o comando `probe_atf_pb --company-id ID` verifica login e caixa sem criar consulta fiscal.

## Desenvolvimento e testes

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
DEV_MODE=True .venv/bin/python manage.py migrate
DEV_MODE=True .venv/bin/python manage.py runserver
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check apps config tests
.venv/bin/python -m mypy apps config
```

A suíte padrão usa SQLite descartável e dados sintéticos, sem rede SEFAZ. A concorrência e as migrations também são verificadas com `--ds=config.settings.test_postgres`, apontando `TEST_POSTGRES_*` exclusivamente a uma base descartável cujo nome começa com `test_`.

## Limites e documentação

A conferência estrutural/identidade do XML não valida assinatura digital nem o XSD completo de NF-e/eventos; o estado de schema pendente fica explícito. Smoke do backend A1/ACL no Windows permanece necessário. Contratos não observados de paginação JavaScript ou confirmação definitiva de resultado vazio exigem ajuste comprovado do portal.

- [Guia operacional, configuração, retries e corte](docs/OPERACAO-ATF-PB.md)
- [Revisão geral e correções de 20/10/2026](docs/REVISAO-GERAL-2026-10-20.md)
- [Andamento e evidências da implementação](docs/IMPLEMENTACAO-ATF-PB.md)
- [Plano e revisão de requisitos de 20/10/2026](docs/superpowers/plans/2026-10-19-atf-pb-migration.md)
- [Validação anterior do login A1](docs/VALIDACAO-AUTENTICACAO-ATF-PB.md)
- [Validação anterior do download ZIP](docs/VALIDACAO-DOWNLOAD-ATF-PB.md)
