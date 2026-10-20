# Validação do download de NF-e — SEFAZ-PB

Data: 19/10/2026, America/Fortaleza.

## Resultado

O fluxo completo funcionou por HTTP direto: autenticação A1, pesquisa do emitente por CNPJ, solicitação por período e formato, identificação das novas mensagens e download do anexo ZIP. Foram executadas duas solicitações de consulta, uma para XML e outra para TXT, no período de **01/10/2026 a 18/10/2026**. Não foi necessária automação de navegador.

| Formato solicitado | Arquivo salvo em `D:\sefaz-data\exemplos` | ZIP recebido | Conteúdo |
| --- | --- | --- | --- |
| XML | `nfe_xml_2026-10-01_2026-10-18.zip` | 104.198 bytes | 16 NF-e e 9 eventos, totalizando 25 XMLs |
| TXT | `nfe_txt_2026-10-01_2026-10-18.zip` | 5.354 bytes | 1 TXT de 56.879 bytes |

## Verificações realizadas

- Ambos os downloads retornaram HTTP 200, `Content-Type: application/zip` e um ZIP reconhecido pela biblioteca `zipfile`.
- A descompressão e a verificação CRC de todos os membros passaram.
- Os 25 XMLs foram analisados com resolução de entidades externas desabilitada.
- As 16 notas são do modelo 55; todos os emitentes correspondem à empresa do A1 e todas as datas de emissão pertencem ao intervalo solicitado. As emissões presentes vão de 02/10/2026 a 15/10/2026.
- Os 9 arquivos de eventos são documentos `procEventoNFe`, e suas chaves correspondem a notas presentes no mesmo ZIP. Eles devem ser tratados separadamente dos documentos `nfeProc`.
- O TXT é decodificável em Windows-1252, tem 57 linhas não vazias e usa `|` como separador. As 16 chaves das notas do ZIP XML estão presentes no relatório.
- As mensagens dos dois pedidos confirmaram o período solicitado e a conclusão com sucesso. Foram distinguidas das mensagens existentes antes do teste.
- O teste abriu as mensagens geradas para acessar os anexos; a leitura pode atualizar a indicação de mensagem lida no portal. Não foram acionadas operações de emissão, cancelamento ou manifestação.

### SHA-256 dos ZIPs

```text
nfe_xml_2026-10-01_2026-10-18.zip
c88cccd9fff489936ed23f6668b7e3de01298436adf2a00a05a8cca9dceb379c

nfe_txt_2026-10-01_2026-10-18.zip
7d21304ee6c60d151e25df75ef1e36ac524b37b4e15894470737155001a13ebf
```

## Contrato observado no portal

Todos os caminhos abaixo pertencem a `https://www4.sefaz.pb.gov.br`. Estes são endpoints do portal ATF observados em uma sessão real, sem garantia de estabilidade de uma API pública.

1. Autenticar pelo formulário `FormLogin` de `/atf/seg/SEGf_LoginSERVirtual.jsp`, preservando campos ocultos e cookies e usando `hidAcao=logarCertificadoDigital`. O redirecionamento é para `/atf/seg/SEGf_LoginCertificadoSERvirtual.do`, com apresentação do A1 no TLS.
2. Abrir `/atf/fis/FISf_ConsultarNFeXml2.do?idSERVirtual=S` para iniciar a consulta e o componente de emitente.
3. Carregar `/atf/componentes/CodDescLstBS.jsp?id=FISf_ConsultarNFeXml2_cmpEmit`. Pesquisar o CNPJ no formulário `iform` com `hidAcao=botao`, `hidSqTpDocHumanoInst=2`, `hidTpNatureza=I`, `hidOpcaoListagem=3` e `hidNrDocumentocmpEmit` igual ao CNPJ. Preservar os demais campos do formulário.
4. A resposta da pesquisa atribui os dados da empresa aos campos ocultos do formulário pai por JavaScript. Uma integração HTTP precisa extrair esses valores como dados, sem executar JavaScript arbitrário. Em especial, `hidSqHumanoInstcmpEmit` é necessário. Não fixar o identificador interno, CNPJ, nome ou timestamp encontrados neste teste no código de produção.
5. Enviar o formulário `frmConsultar` para `/atf/fis/FISf_ConsultarNFeXml2.do` com `hidAcao=consultar`, `edtDtInicial`, `edtDtFinal`, identificação do emitente e `cmbTpExibicao=3` para XML ou `2` para TXT. A opção CNPJ de `cmbTpDoccmpEmit` tem valor `2`. O portal confirmou que o resultado seria enviado para a caixa de mensagens.
6. A caixa é `/atf/seg/SEGf_MinhasMensagens.do`. A ação de atualização envia `hidAcao=listar`. Registrar os identificadores existentes antes do pedido ajuda a distinguir novos grupos; em produção, combinar isso com dados do pedido e período, pois a caixa pode ser compartilhada e receber outras solicitações.
7. `abrirFilhas(id, quantidade)` com filhos envia `hidAcao=listar` ao mesmo endpoint, com `hidsqMensagem=id` na query string. Os dois grupos gerados neste teste tinham três mensagens cada.
8. Selecionar a mensagem filha com a imagem de anexo `clips.gif` / `alt="Anexo"`. Abrir por POST em `/atf/seg/SEGf_LerMensagem.do?hidsqMensagem=<filha>&sqMensagemPai=<pai>`, com `hidAcao=lerMensagem` e os campos do formulário. Confirmar período e resultado.
9. `mostrarArquivo(0)` envia POST para `/atf/seg/SEGf_MostrarArquivo.do?hidAnexo=0`, com `hidAcao=mostrarArquivo`. O contexto da mensagem é mantido na sessão; o índice zero é relativo à mensagem aberta, não um identificador global do arquivo. A integração deverá processar os anexos de forma sequencial dentro da mesma sessão.

## Implicações para a implementação

- Reaproveitar o cofre A1 e criar uma sessão independente por empresa, com cookies em memória e verificação TLS habilitada.
- Separar os estados de solicitação, processamento, descoberta de mensagem, download e validação, sem NSU.
- Preservar o ZIP original e distinguir XML de nota, XML de evento e relatório TXT. A quantidade de XMLs não corresponde necessariamente à quantidade de notas.
- Não esperar um download direto ao clicar em Consultar: a geração é assíncrona e o resultado aparece na caixa de mensagens.
- A interface do ATF libera a atualização da caixa após 60 segundos; implementar consulta periódica com intervalo, limite de espera e retomada, evitando polling agressivo.
- Não inferir TXT em UTF-8: este relatório foi recebido em Windows-1252.
- O JavaScript da consulta limita o intervalo de datas a um ano; validar o comportamento no servidor e dividir períodos maiores antes de automatizá-los.
- Resolver a divergência entre o identificador do certificado no banco do workspace e o arquivo atual no cofre, registrada na validação de autenticação.

## Limites

Esta validação usa um certificado e um período. Não valida concorrência, múltiplas empresas, sessão expirada, falhas de rede, períodos sem notas, anos diferentes ou processamento prolongado. Os diagnósticos ficaram em scripts temporários sob `/tmp`; não foi adicionada integração ao código de produção nem alterado o banco. As sessões locais foram fechadas ao terminar; não foi realizado logout explícito no servidor.
