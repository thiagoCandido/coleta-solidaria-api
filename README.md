# Coleta Solidária — API

API REST para organizar solicitações de coleta de doações. Desenvolvida para o MVP da pós-graduação PUC-Rio, com FastAPI, SQLite e integração real com o ViaCEP.

## Problema e escopo

Pequenas iniciativas solidárias precisam organizar o recebimento de doações. A aplicação registra doador, categoria, descrição e endereço; permite consultar e filtrar solicitações, acompanhar o status e excluir registros.

O projeto é uma demonstração acadêmica sem autenticação. Use somente dados fictícios. Não existe serviço de transporte real nem reserva de data: “agendada” representa a confirmação operacional da coleta.

## Arquitetura

Cenário 1.1 do enunciado: interface → API própria → API externa, com banco conectado à API própria. A interface e a API são componentes executados em contêineres separados e mantidos em repositórios separados. Isso não pretende representar um ecossistema completo de microsserviços.

- Interface: HTML, CSS e JavaScript, servidos por Nginx.
- API: Python/FastAPI, contratos HTTP/JSON documentados em Swagger.
- Persistência: SQLite, acessível somente por esta API.
- Componente externo: ViaCEP, consultado pela API em tempo de execução.

## Executar com Docker

Pré-requisito: Docker Desktop iniciado em modo de contêineres Linux (ou Docker Engine no Linux).

```bash
docker build -t coleta-solidaria-api .
docker run --name coleta-api -p 8000:8000 -v coletas_data:/app/data coleta-solidaria-api
```

- Swagger: http://localhost:8000/docs
- OpenAPI: http://localhost:8000/openapi.json
- Para executar também a interface, consulte o README do repositório `coleta-solidaria-front`, que contém o Docker Compose.

O volume `coletas_data` preserva o banco entre execuções. `docker compose down` preserva o volume; a opção `-v` apaga os dados e não deve ser usada se você quiser mantê-los.

## Executar localmente

Requer Python 3.12.

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Caso o PowerShell não permita ativar o ambiente, execute diretamente `.venv\Scripts\python.exe -m pip install -r requirements.txt` e `.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`.

Variáveis opcionais:

| Variável | Padrão | Finalidade |
|---|---|---|
| `DATABASE_PATH` | `data/coletas.db` | Caminho do SQLite; no Docker é `/app/data/coletas.db` |
| `CORS_ORIGINS` | `http://localhost:8080,http://127.0.0.1:8080` | Origens permitidas, separadas por vírgula |

## Rotas

| Método | Rota | Comportamento |
|---|---|---|
| GET | `/coletas` | Lista por ordem de cadastro, da mais recente para a mais antiga |
| POST | `/coletas` | Valida o CEP no ViaCEP, grava no SQLite e retorna 201 |
| PATCH | `/coletas/{coleta_id}` | Atualiza o status e retorna o registro |
| DELETE | `/coletas/{coleta_id}` | Exclui o registro e retorna 204 |
| GET | `/enderecos/{cep}` | Consulta e normaliza o endereço da API externa |

Filtros combináveis: `/coletas?status=pendente&categoria=livros&busca=infantis`. A busca considera nome, descrição e cidade. Categorias: `alimentos`, `roupas`, `livros`, `brinquedos`, `outros`.

Exemplo de POST:

```json
{
  "nome": "Pessoa de exemplo",
  "categoria": "livros",
  "descricao": "Uma caixa com livros infantis",
  "cep": "01001000",
  "numero": "100",
  "complemento": "Exemplo fictício"
}
```

Exemplo de PATCH: `{"status":"agendada"}`. Depois, `{"status":"concluida"}`.

As transições permitidas são `pendente → agendada → concluida`. Repetir o status atual é permitido; saltar etapas ou voltar retorna 409. Essa regra preserva o fluxo do domínio.

## Integração externa: ViaCEP

- Documentação: https://viacep.com.br/
- Rota utilizada: `GET https://viacep.com.br/ws/{cep}/json/`.
- Serviço público gratuito; a consulta documentada não requer cadastro, token ou chave.
- Formato: JSON. Utilizamos CEP, logradouro, bairro, localidade e UF.
- A documentação consultada não especifica uma licença de redistribuição da base de dados. Este projeto somente consulta o serviço; não redistribui sua base nem atribui a ela uma licença própria.
- A documentação alerta que uso massivo para validar bases locais pode causar bloqueio. Este MVP realiza consultas individuais sob demanda.
- A aplicação trata os dados internamente, sem redirecionar o usuário.

O cadastro consulta o ViaCEP novamente no servidor para evitar confiar em um endereço informado pelo navegador. Se o serviço externo falhar, o registro não é gravado. CEPs genéricos podem retornar cidade/UF sem logradouro; número e complemento ajudam a detalhar o local.

Erros: 422 para dados inválidos, 404 para CEP/coleta inexistente, 409 para transição inválida, 502 para erro de integração e 504 para tempo limite de oito segundos no ViaCEP.

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Os testes usam banco temporário e respostas controladas do ViaCEP: fluxo completo, persistência após reinicialização, filtros, validação, transições inválidas, recurso inexistente, erro/timeout externo e presença dos métodos no OpenAPI. O teste manual de integração real deve ser feito pelo Swagger e pela interface com internet disponível.

## Organização

```text
app/main.py             Rotas, validação, integração externa e persistência
tests/test_api.py       Testes automatizados
Dockerfile             Empacotamento do componente
requirements.txt       Dependências de execução
requirements-dev.txt   Dependências de teste
```

## Decisões e limites

REST simplifica a comunicação; SQLite permite persistência sem um terceiro contêiner próprio; FastAPI gera a documentação do contrato. Consultas SQL usam parâmetros para dados de usuário. Não há autenticação, entrega real, pagamento ou geolocalização. Para uso público real seriam necessários autenticação/autorização, proteção de dados, limites de requisição, backups e monitoramento. O projeto usa código original criado para este domínio.
