"""Testes isolados: banco temporário e respostas controladas da API externa."""
import httpx
import pytest
from fastapi.testclient import TestClient
from app import main

ADDRESS = {"cep": "01001000", "logradouro": "Praça da Sé", "bairro": "Sé", "cidade": "São Paulo", "uf": "SP"}
PAYLOAD = {"nome": "Doador fictício", "categoria": "livros", "descricao": "Dez livros infantis", "cep": "01001000", "numero": "100"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    async def address(cep):
        return ADDRESS
    monkeypatch.setattr(main, "consultar_cep", address)
    with TestClient(main.app) as client:
        yield client


def test_complete_flow_and_persistence(client):
    created = client.post("/coletas", json=PAYLOAD)
    assert created.status_code == 201
    item = created.json()
    assert item["status"] == "pendente"
    assert item["cidade"] == "São Paulo"
    main.init_db()
    assert len(client.get("/coletas").json()) == 1
    assert len(client.get("/coletas?categoria=livros&busca=infantis").json()) == 1
    assert client.get("/coletas?status=concluida").json() == []
    path = f'/coletas/{item["id"]}'
    assert client.patch(path, json={"status": "concluida"}).status_code == 409
    assert client.patch(path, json={"status": "agendada"}).status_code == 200
    assert client.patch(path, json={"status": "concluida"}).json()["status"] == "concluida"
    assert client.patch(path, json={"status": "pendente"}).status_code == 409
    assert client.delete(path).status_code == 204
    assert client.get("/coletas").json() == []
    assert client.delete(path).status_code == 404


def test_invalid_input_and_missing_resource(client):
    assert client.post("/coletas", json=PAYLOAD | {"nome": " "}).status_code == 422
    assert client.post("/coletas", json=PAYLOAD | {"cep": "123"}).status_code == 422
    assert client.post("/coletas", json=PAYLOAD | {"categoria": "inexistente"}).status_code == 422
    assert client.patch("/coletas/999", json={"status": "agendada"}).status_code == 404
    assert client.get("/coletas?status=inexistente").status_code == 422


@pytest.mark.parametrize("mode,expected", [("missing", 404), ("timeout", 504), ("invalid", 502)])
def test_external_api_errors(tmp_path, monkeypatch, mode, expected):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            if mode == "timeout": raise httpx.ReadTimeout("timeout")
            data = {"erro": True} if mode == "missing" else []
            return httpx.Response(200, json=data, request=httpx.Request("GET", url))
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    with TestClient(main.app) as client:
        assert client.get("/enderecos/01001000").status_code == expected
        assert client.post("/coletas", json=PAYLOAD).status_code == expected
        assert client.get("/coletas").json() == []


def test_swagger_documents_required_methods(client):
    schema = client.get("/openapi.json").json()
    assert "get" in schema["paths"]["/coletas"]
    assert "post" in schema["paths"]["/coletas"]
    assert "patch" in schema["paths"]["/coletas/{coleta_id}"]
    assert "delete" in schema["paths"]["/coletas/{coleta_id}"]
