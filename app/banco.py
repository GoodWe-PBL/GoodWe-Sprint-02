# Acesso ao banco de dados para as telas.
import sys
from pathlib import Path

# A interface roda a partir da pasta app/. Para "import main" e "from src..."
# funcionarem, a raiz do projeto precisa estar na lista de pastas onde o Python
# procura módulos.
RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd
from sqlalchemy import text

from src.db.conexao import criar_engine, criar_sessao, fechar_sessao


def consultar(sql, **parametros):
    """Roda um SELECT e devolve o resultado como tabela (DataFrame)."""
    engine = criar_engine()
    tabela = pd.read_sql(text(sql), engine, params=parametros)
    # Fecha a conexão. No Windows um arquivo em uso não pode ser apagado, e o
    # pipeline precisa apagar o banco para recriá-lo.
    engine.dispose()
    return tabela


def abrir_sessao():
    """Sessão do SQLAlchemy, para as telas que usam as funções de src/ (ex.: revisão).
    Quem abre precisa chamar fechar_sessao(db) no final."""
    return criar_sessao(criar_engine())
