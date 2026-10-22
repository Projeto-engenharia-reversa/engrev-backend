# Catalogo de Streaming

Plataforma de streaming de musica, dividida em quatro servicos que evoluiram em
epocas diferentes e por isso cada um descreve seu schema no formato que estava em
uso na epoca.

## Servicos

| Servico | Contrato | Banco |
|---|---|---|
| Billing | `prisma/schema.prisma` | Postgres `billing` |
| Catalogo | `proto/catalogo.proto` (interno) e `openapi/api.yaml` (publico) | Postgres `catalogo` |
| BFF do player | `graphql/schema.graphql` | nao tem banco proprio |
| Telemetria | `db/changelog.xml` | Postgres `eventos` |
| Recomendacao | `src/Recomendacao/Models/` (EF Core) | Postgres `recomendacao` |

## Rodando localmente

```
docker compose up -d
npx prisma migrate deploy
dotnet run --project src/Recomendacao
```

## Modelo de Dados

O dominio se divide em tres blocos que quase nao se tocam:

- **Assinatura**: um `Assinante` esta sempre em exatamente um `Plano`, e pode ter
  varios `Dispositivo`. A `Cobranca` e mensal por assinante, uma por competencia.
- **Catalogo**: um `Artista` tem varios `Album`, e um `Album` tem varias `Faixa`.
  `Genero` e hierarquico -- aponta para si mesmo pelo pai.
- **Uso**: `Reproducao` e `Avaliacao` registram o que o assinante consumiu.
  `Playlist` pertence a um assinante e reune faixas atraves de `ItemPlaylist`,
  que guarda a posicao de cada faixa na lista.

Referencias entre blocos (por exemplo `assinante_id` na telemetria) sao apenas
identificadores logicos: como cada servico tem banco proprio, nao existe
integridade referencial entre eles, e a resolucao e feita pela aplicacao.

## Convencoes

- `Artista` e `Album` aparecem no proto e no OpenAPI de proposito: um e o
  contrato interno, o outro o publico. Divergencia entre os dois e bug.
- Migracoes de billing sao geradas pelo Prisma; as de telemetria sao escritas na
  mao em Liquibase.
