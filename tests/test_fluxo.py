"""Teste de ponta a ponta: roda o fluxo completo em banco em memória e verifica
que a decisão da IA controla o que é cobrado."""
import pytest
from sqlalchemy import func, select

from src.db.conexao import criar_engine, criar_sessao
from src.db.modelos import Fatura, ItemFatura, Sessao
from src.pipeline import executar_tudo
from src.rateio.servico import revisar_sessao
from src.simulacao.cadastro import popular_cadastro
from src.simulacao.gerador import carregar_registros_reais, gerar_registros_simulados


@pytest.fixture(scope="module")
def db():
    sessao = criar_sessao(criar_engine("sqlite://"))
    popular_cadastro(sessao)
    executar_tudo(sessao, carregar_registros_reais() + gerar_registros_simulados())
    return sessao


def test_dados_reais_ingeridos_integralmente(db):
    total = db.scalar(select(func.sum(Sessao.energia_kwh)).where(Sessao.origem == "real"))
    assert total == pytest.approx(769.27, abs=0.01)


def test_somente_sessoes_validadas_sao_cobradas(db):
    ids_cobrados = set(db.scalars(select(ItemFatura.sessao_id)))
    status = {s.id: s.status for s in db.scalars(select(Sessao))}
    assert ids_cobrados, "nenhuma sessão foi cobrada"
    assert all(status[i] == "validada" for i in ids_cobrados)
    assert any(s == "em_revisao" for s in status.values())


def test_cada_sessao_validada_cobrada_uma_vez(db):
    validadas = db.scalar(select(func.count()).where(Sessao.status == "validada"))
    cobradas = db.scalar(select(func.count(func.distinct(ItemFatura.sessao_id))))
    assert validadas == cobradas


def test_registro_invalido_rejeitado(db):
    assert db.scalar(select(func.count()).where(Sessao.status == "erro")) >= 1


def test_aprovacao_do_gestor_entra_na_fatura_aberta(db):
    pendente = db.scalars(select(Sessao).where(Sessao.status == "em_revisao")).first()
    fatura = db.scalar(select(Fatura).where(Fatura.usuario_id == pendente.usuario_id,
                                            Fatura.status == "aberta"))
    antes = fatura.valor_final
    revisar_sessao(db, pendente.id, aprovar=True)
    assert pendente.status == "validada"
    assert fatura.valor_final > antes
