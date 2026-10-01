"""Criação do banco SQLite e da sessão do SQLAlchemy.

A Sprint 01 previa PostgreSQL. No protótipo usamos SQLite (arquivo local, sem
servidor) para qualquer pessoa conseguir rodar; como todo acesso passa pelo
SQLAlchemy, trocar para PostgreSQL é só mudar a URL de conexão.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import CAMINHO_BANCO
from src.db.modelos import Base


def criar_engine(url: str | None = None, recriar: bool = False):
    if url is None:
        CAMINHO_BANCO.parent.mkdir(parents=True, exist_ok=True)
        if recriar and CAMINHO_BANCO.exists():
            CAMINHO_BANCO.unlink()
        url = f"sqlite:///{CAMINHO_BANCO}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


def criar_sessao(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)()
