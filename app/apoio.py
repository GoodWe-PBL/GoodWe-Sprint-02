# Funções usadas por mais de uma tela: começo da tela, acesso ao banco e formatação.
import sys
from pathlib import Path

# O Streamlit roda a partir da pasta app/. Para "import main" e "from src..."
# funcionarem, a raiz do projeto precisa estar na lista de pastas onde o Python
# procura módulos.
RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd
import streamlit as st
from sqlalchemy import text

import main
from src import config
from src.db.conexao import criar_engine, criar_sessao


# cache_resource: a engine (conexão com o banco) é criada uma vez e reaproveitada.
@st.cache_resource
def engine_do_banco():
    return criar_engine()


def soltar_banco():
    """Fecha as conexões abertas. No Windows um arquivo em uso não pode ser apagado,
    e o pipeline precisa apagar o banco para recriá-lo."""
    engine_do_banco().dispose()


def abrir_sessao():
    """Sessão do SQLAlchemy, para as telas que usam as funções de src/ (ex.: revisão)."""
    return criar_sessao(engine_do_banco())


def fechar_sessao(db):
    db.close()
    soltar_banco()


# cache_data: guarda o resultado de cada consulta para não reler o banco a cada
# clique. Quando o banco muda (revisão ou reexecução), o cache é limpo.
@st.cache_data
def consultar(sql, **parametros):
    """Roda um SELECT e devolve o resultado como tabela (DataFrame)."""
    tabela = pd.read_sql(text(sql), engine_do_banco(), params=parametros)
    soltar_banco()
    return tabela


def reexecutar_pipeline():
    main.cmd_executar(None)  # a mesma função de "python main.py executar"
    st.cache_data.clear()    # o banco é novo: as consultas guardadas não valem mais


def iniciar_tela(titulo):
    """Começo igual em todas as telas: barra lateral, aviso se o banco não existir e título."""
    st.set_page_config(page_title="EV ChargeOps", layout="wide")
    st.sidebar.warning("Reexecutar recria o banco do zero e apaga as revisões feitas pelo gestor.")
    if st.sidebar.button("Reexecutar pipeline"):
        with st.spinner("Executando o pipeline (leva alguns segundos)..."):
            reexecutar_pipeline()
    if not config.CAMINHO_BANCO.exists():
        st.info("O banco de dados ainda não existe. Clique em \"Reexecutar pipeline\" na barra "
                "lateral ou rode no terminal: python main.py executar")
        st.stop()
    st.title(titulo)


def reais(valor):
    """1234.5 -> 'R$ 1.234,50'"""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def escapar_cifrao(texto):
    """O Streamlit trata o que fica entre dois $ como fórmula matemática e estraga
    frases com dois valores em reais. A barra antes do $ desliga isso."""
    return texto.replace("$", "\\$")


def mostrar_insights(insights):
    """Mostra uma caixa azul para cada linha da tabela insight_ia."""
    for insight in insights.itertuples():
        st.info(escapar_cifrao(f"[{insight.tipo}] {insight.mensagem}"))
