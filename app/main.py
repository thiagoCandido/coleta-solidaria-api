"""API do MVP Coleta Solidária: persistência local e integração ViaCEP."""
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

DB_PATH = Path(os.getenv("DATABASE_PATH", "data/coletas.db"))


@contextmanager
def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        db.row_factory = sqlite3.Row
        yield db


def init_db():
    with connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS coletas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL, categoria TEXT NOT NULL, descricao TEXT NOT NULL,
            cep TEXT NOT NULL, logradouro TEXT NOT NULL, bairro TEXT NOT NULL,
            cidade TEXT NOT NULL, uf TEXT NOT NULL, numero TEXT NOT NULL,
            complemento TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pendente',
            criado_em TEXT NOT NULL)""")


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(
    title="Coleta Solidária API", version="1.0.0",
    description="Organização de coletas de doações com SQLite e consulta de endereços no ViaCEP. "
                "MVP acadêmico sem autenticação: utilize apenas dados fictícios.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(","),
    allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"],
)


class Categoria(str, Enum):
    alimentos = "alimentos"
    roupas = "roupas"
    livros = "livros"
    brinquedos = "brinquedos"
    outros = "outros"


class Status(str, Enum):
    pendente = "pendente"
    agendada = "agendada"
    concluida = "concluida"


class Endereco(BaseModel):
    cep: str
    logradouro: str
    bairro: str
    cidade: str
    uf: str


class NovaColeta(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    nome: str = Field(min_length=2, max_length=80, examples=["Pessoa de exemplo"])
    categoria: Categoria
    descricao: str = Field(min_length=3, max_length=300, examples=["Uma caixa de livros infantis"])
    cep: str = Field(pattern=r"^\d{5}-?\d{3}$", examples=["01001000"])
    numero: str = Field(min_length=1, max_length=15, examples=["100"])
    complemento: str = Field(default="", max_length=100)


class AtualizarStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status


class Coleta(Endereco):
    id: int
    nome: str
    categoria: Categoria
    descricao: str
    numero: str
    complemento: str
    status: Status
    criado_em: str


async def consultar_cep(cep: str) -> dict:
    normalized = cep.replace("-", "")
    if len(normalized) != 8 or not normalized.isascii() or not normalized.isdigit():
        raise HTTPException(422, "Informe um CEP com oito dígitos.")
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            result = await client.get(f"https://viacep.com.br/ws/{normalized}/json/")
            result.raise_for_status()
            data = result.json()
        if not isinstance(data, dict):
            raise ValueError("Resposta inválida")
        if data.get("erro"):
            raise HTTPException(404, "CEP não encontrado no ViaCEP.")
        if not data.get("localidade") or not data.get("uf"):
            raise ValueError("Endereço incompleto")
        return dict(cep=normalized, logradouro=data.get("logradouro", ""),
                    bairro=data.get("bairro", ""), cidade=data["localidade"], uf=data["uf"])
    except httpx.TimeoutException:
        raise HTTPException(504, "O ViaCEP demorou a responder. Tente novamente.")
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Não foi possível consultar o ViaCEP. Tente novamente.")


@app.get("/enderecos/{cep}", response_model=Endereco, tags=["Endereços"],
         summary="Consultar endereço na API externa ViaCEP")
async def obter_endereco(cep: str):
    return await consultar_cep(cep)


@app.get("/coletas", response_model=list[Coleta], tags=["Coletas"],
         summary="Listar coletas, com filtros opcionais")
def listar_coletas(status: Status | None = None, categoria: Categoria | None = None,
                  busca: str = Query(default="", max_length=80)):
    clauses, params = [], []
    for field, value in (("status", status), ("categoria", categoria)):
        if value is not None:
            clauses.append(f"{field} = ?")
            params.append(value.value)
    if busca.strip():
        clauses.append("(nome LIKE ? OR descricao LIKE ? OR cidade LIKE ?)")
        params.extend([f"%{busca.strip()}%"] * 3)
    sql = "SELECT * FROM coletas"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    with connection() as db:
        return [dict(row) for row in db.execute(sql + " ORDER BY id DESC", params).fetchall()]


@app.post("/coletas", response_model=Coleta, status_code=201, tags=["Coletas"],
          summary="Cadastrar coleta com endereço validado pelo ViaCEP")
async def criar_coleta(coleta: NovaColeta):
    endereco = await consultar_cep(coleta.cep)
    values = coleta.model_dump(mode="json") | endereco
    values.update(status="pendente", criado_em=datetime.now(timezone.utc).isoformat())
    with connection() as db:
        cursor = db.execute(
            f"INSERT INTO coletas ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
            list(values.values()),
        )
        return dict(db.execute("SELECT * FROM coletas WHERE id = ?", (cursor.lastrowid,)).fetchone())


@app.patch("/coletas/{coleta_id}", response_model=Coleta, tags=["Coletas"],
           summary="Avançar coleta: pendente → agendada → concluída")
def atualizar_status(coleta_id: int, atualizacao: AtualizarStatus):
    with connection() as db:
        row = db.execute("SELECT * FROM coletas WHERE id = ?", (coleta_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Coleta não encontrada.")
        next_status = {"pendente": "agendada", "agendada": "concluida"}
        if atualizacao.status.value != row["status"] and next_status.get(row["status"]) != atualizacao.status.value:
            raise HTTPException(409, "Transição inválida. Siga: pendente → agendada → concluída.")
        db.execute("UPDATE coletas SET status = ? WHERE id = ?", (atualizacao.status.value, coleta_id))
        return dict(db.execute("SELECT * FROM coletas WHERE id = ?", (coleta_id,)).fetchone())


@app.delete("/coletas/{coleta_id}", status_code=204, tags=["Coletas"],
            summary="Excluir uma solicitação de coleta")
def excluir_coleta(coleta_id: int):
    with connection() as db:
        cursor = db.execute("DELETE FROM coletas WHERE id = ?", (coleta_id,))
        if not cursor.rowcount:
            raise HTTPException(404, "Coleta não encontrada.")
    return Response(status_code=204)
