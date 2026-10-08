# Operação e homologação controlada

Este procedimento prepara uma instalação local para validar NF-e modelo 55 no
ambiente de homologação. Ele não autoriza produção, NFC-e ou uma nova consulta
por si só.

## Limites obrigatórios

- Use uma empresa, certificado A1 e CNPJ explicitamente autorizados para o
  teste. Não use dados fiscais reais somente como fixture.
- Mantenha `SEFAZ_ENABLED_ENVIRONMENTS` vazio até concluir a pré-validação.
  Para o primeiro teste, o único valor permitido é `homologation`.
- Não altere NSU, arquivos de lote ou estado do banco manualmente.
- Interrompa o procedimento se houver migration pendente, volume inacessível,
  chave privada exposta ou backup/restauração ainda não verificados.
- A habilitação de `production` depende de evidência de homologação aprovada e
  de autorização operacional registrada. Ela não é coberta por este roteiro.

## Pré-requisitos no host

1. Crie `.env` a partir de `.env.example`, usando caminhos absolutos fora do
   repositório e segredos novos. O arquivo não deve ser versionado.
2. Inicie os containers sem liberar ambientes SEFAZ.
3. No worker, execute:

   ```bash
   docker compose exec worker python manage.py verify_fiscal_installation --worker --write-notes-probe
   ```

   O resultado deve confirmar banco, migrations, schemas, chaves privadas,
   par de chaves de upload e escrita atômica no volume. A sonda é removida e
   não cria consulta fiscal.
4. Registre uma verificação de backup e restauração antes do teste. Ela deve
   abranger, separadamente:

   | Ativo | Evidência mínima |
   | --- | --- |
   | PostgreSQL | dump restaurado em banco descartável com migrations e contagens verificadas |
   | `NOTES_HOST_DIR` | cópia consistente restaurada e XML de amostra com SHA-256 conferido |
   | `CERTIFICATES_HOST_DIR` | cópia cifrada protegida e recuperação testada com a chave mestra mantida fora do backup comum |
   | chaves de upload | par correspondente preservado ou procedimento de rotação documentado |

   Não marque essa etapa como concluída apenas porque os volumes Docker existem.

## Homologação NF-e modelo 55

1. Após os passos anteriores, configure
   `SEFAZ_ENABLED_ENVIRONMENTS=homologation` no `.env` e reinicie somente o
   worker. Não inclua `production`.
2. Crie uma solicitação manual no ambiente **Homologação** para a empresa de
   teste. O botão apenas enfileira; o worker é o único processo que pode abrir
   o certificado e chamar o serviço fiscal.
3. Acompanhe a solicitação, o lote e os alertas. Para uma resposta sem novos
   documentos, espere `tpAmb=2`, `cStat=137`, `ultNSU=0`, `maxNSU=0` e nenhum
   `docZip` antes de criar outra solicitação.
4. Se houver documento, confirme o lote bruto e o SOAP arquivados, o hash e o
   arquivo XML externo antes de confirmar o avanço do NSU.
5. Para uma falha local já arquivada, use exclusivamente o botão
   **Reprocessar localmente**. Ele não consulta a SEFAZ. Não envie uma nova
   solicitação para contornar a falha.
6. Ao encerrar o teste, remova `homologation` de
   `SEFAZ_ENABLED_ENVIRONMENTS` e reinicie o worker. Registre o resultado na
   evidência abaixo.

## Condições de parada e suporte

| Sinal | Ação segura |
| --- | --- |
| `cStat=137` ou `656` | aguarde pelo menos uma hora e respeite `next_allowed_at`; não altere o NSU |
| alerta de certificado | corrija o cadastro/validade do A1; nenhuma consulta foi enviada se o worker não tinha certificado válido |
| `sefaz_transport_not_enabled` | confirme o ambiente em `.env`; não libere produção para resolver o alerta |
| lote com falha local | use o reprocessamento local e preserve o lote bruto para análise |
| schema, hash ou volume inválido | pare o teste, restaure a capacidade local e registre a falha; não repita a consulta |

## Registro de evidência

Preencha um registro por execução, sem senhas, PFX, XML integral, chaves
privadas ou CNPJ completo quando não forem necessários:

```text
Data e fuso:
Operador responsável:
Commit e imagem executada:
Ambiente liberado: homologation
Empresa de teste (identificador mascarado):
Resultado do preflight:
Backup/restauração verificados em:
Solicitação e lote (IDs locais):
cStat, ultNSU e maxNSU recebidos:
SOAP/lote/XML preservados e hashes conferidos: sim/não
Alertas e resolução:
Resultado final e próximo passo:
```

Sem esse registro e a evidência de restauração, a instalação permanece em
pré-homologação.
