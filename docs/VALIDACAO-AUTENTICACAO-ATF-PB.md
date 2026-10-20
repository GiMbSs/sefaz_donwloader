# Validação de autenticação na SEFAZ-PB

Data: 19/10/2026 (America/Fortaleza).

Atualização: o fluxo de solicitação e download de XML e TXT foi testado posteriormente e está registrado em [VALIDACAO-DOWNLOAD-ATF-PB.md](VALIDACAO-DOWNLOAD-ATF-PB.md). Os limites abaixo descrevem apenas a etapa inicial de autenticação.

## Resultado

A autenticação com o A1 disponível em `D:\sefaz-data` funcionou por HTTP em Python, usando certificado cliente TLS e mantendo os cookies em uma sessão `requests.Session`. Não foi necessário navegador, Java, programa assinador ou interação com uma janela de seleção de certificados neste teste.

O teste carregou um único A1 do cofre existente, com chave privada e validade vigente. O certificado e a senha foram descriptografados em memória. A cadeia e a chave privada foram apresentadas ao contexto TLS por um descritor de memória do Linux; não foram gravados arquivos PEM no disco. A verificação do certificado TLS do servidor permaneceu habilitada. Certificado, senha, cookies e conteúdo de mensagens não foram impressos.

## Fluxo observado

1. `GET https://www4.sefaz.pb.gov.br/atf/seg/SEGf_LoginSERVirtual.jsp`: HTTP 200, obtenção do formulário e dos cookies.
2. `POST` no mesmo endereço, com os campos ocultos do formulário e `hidAcao=logarCertificadoDigital`: HTTP 302.
3. Redirecionamento para `/atf/seg/SEGf_LoginCertificadoSERvirtual.do`: HTTP 200 com o A1, sem formulário de senha e com opção de encerrar a sessão. Uma tentativa anterior sem certificado recebeu HTTP 401 nesse endpoint.
4. Na mesma sessão, `GET /atf/fis/FISf_ConsultarNFeXml2.do?idSERVirtual=S`: HTTP 200 e formulário de consulta de NF-e disponível.
5. A página pública de caixa de mensagens apontou para o iframe `/atf/seg/SEGf_MinhasMensagens.do`. O acesso ao iframe na sessão autenticada retornou HTTP 200, sem formulário de senha, com o manipulador `abrirFilhas` presente.

## Campos confirmados na consulta

| Finalidade | Nome do campo | Observação |
| --- | --- | --- |
| Data inicial | `edtDtInicial` | Campo de texto |
| Data final | `edtDtFinal` | Campo de texto |
| Identificação do emitente | `cmbTpDoccmpEmit` | Inclui a opção CNPJ |
| Identificação do destinatário | `cmbTpDoccmpDest` | Inclui a opção CNPJ |
| Tipo de exibição | `cmbTpExibicao` | Opções HTML, TXT e XML |
| Consultar | `btnConsultar` | Botão com id `btnConsulta` |

Os campos dinâmicos de pesquisa do CNPJ e os valores internos das opções ainda precisam ser mapeados antes de enviar consultas.

## Limites da validação

- Não foram enviados pedidos fiscais, nem solicitados XML ou TXT.
- Nenhuma mensagem foi aberta e nenhum anexo foi baixado.
- O teste confirma a autenticação e a abertura das duas páginas com este A1. Não comprova a conclusão de uma consulta, as permissões sobre outros CNPJs, a geração de arquivos ou o download.
- Duração da sessão, expiração, concorrência e comportamento com outros certificados ainda não foram validados.
- O banco SQLite do workspace referencia um identificador de armazenamento diferente do arquivo encontrado no cofre. O experimento usou o único par de arquivos criptografados do cofre e seu identificador, sem alterar o banco. Essa divergência deve ser resolvida antes da integração com o cadastro do projeto.
- O diagnóstico foi executado por um script temporário em `/tmp/sefaz_atf_auth_probe.py`; não constitui implementação de produção. As sessões foram fechadas ao terminar o processo, sem persistência de cookies. Não foi realizado logout explícito no servidor.

## Próximo passo

Reaproveitar o cofre A1 existente e construir uma integração ATF com sessão independente por empresa. Mapear a pesquisa do CNPJ e o envio de uma consulta por período e formato, depois correlacionar o pedido com as mensagens e os anexos. O novo fluxo deve controlar solicitações e downloads, sem NSU. O transporte de autenticação pode partir de HTTP direto, conforme demonstrado, sujeito à validação do restante do fluxo.
