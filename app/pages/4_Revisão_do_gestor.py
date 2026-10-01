# Tela 4 - Revisão do gestor.
# Lista as sessões que a IA reteve (status "em_revisao") e deixa o gestor aprovar
# ou rejeitar cada uma. Os dados vêm das tabelas sessao, usuario e fatura; a
# decisão é gravada pela função revisar_sessao de src/rateio/servico.py.
import streamlit as st
from sqlalchemy import select

import apoio
from src.db.modelos import Fatura, Sessao, Usuario
from src.rateio.servico import revisar_sessao, valor_da_sessao


def valor_da_fatura_aberta(db, usuario_id):
    """Total da fatura aberta mais recente do usuário (é nela que entra a sessão aprovada)."""
    fatura = db.scalar(select(Fatura).where(Fatura.usuario_id == usuario_id, Fatura.status == "aberta")
                       .order_by(Fatura.referencia_mes.desc()))
    if fatura is None:
        return 0.0
    return fatura.valor_final


def decidir(db, sessao, usuario, aprovar):
    antes = valor_da_fatura_aberta(db, usuario.id)
    try:
        revisar_sessao(db, sessao.id, aprovar=aprovar)
    except ValueError as erro:  # ex.: usuário sem fatura aberta para receber o ajuste
        db.rollback()
        st.error(str(erro))
        return
    depois = valor_da_fatura_aberta(db, usuario.id)
    decisao = "aprovada" if aprovar else "rejeitada"
    # Guardamos o aviso porque a página vai ser recarregada e a sessão some da lista.
    st.session_state["aviso_revisao"] = (
        f"Sessão #{sessao.id} {decisao}. Fatura aberta de {usuario.nome}: "
        f"{apoio.reais(antes)} -> {apoio.reais(depois)}")
    apoio.fechar_sessao(db)
    st.cache_data.clear()  # o banco mudou: as outras telas precisam ler de novo
    st.rerun()


apoio.iniciar_tela("Revisão do gestor")
st.write("Sessões que a IA reteve. Aprovada: entra na fatura aberta do usuário. "
         "Rejeitada: vira \"descartada\" e nunca é cobrada.")

if "aviso_revisao" in st.session_state:
    st.success(apoio.escapar_cifrao(st.session_state.pop("aviso_revisao")))

db = apoio.abrir_sessao()
pendentes = db.scalars(select(Sessao).where(Sessao.status == "em_revisao").order_by(Sessao.id)).all()
if not pendentes:
    st.info("Nenhuma sessão aguardando revisão.")

for sessao in pendentes:
    usuario = db.get(Usuario, sessao.usuario_id)
    with st.container(border=True):
        st.write(f"**Sessão #{sessao.id}** - {usuario.nome} - {sessao.inicio:%d/%m/%Y %H:%M} - "
                 f"{sessao.energia_kwh:.1f} kWh - {sessao.duracao_minutos / 60:.1f} h")
        st.write(f"Motivo: {sessao.motivo_revisao}")
        st.write(apoio.escapar_cifrao(
            f"Fatura aberta hoje: {apoio.reais(valor_da_fatura_aberta(db, usuario.id))} | "
            f"Valor desta sessão se aprovada: {apoio.reais(valor_da_sessao(sessao, usuario.modalidade))}"))
        coluna_aprovar, coluna_rejeitar, _ = st.columns([1, 1, 6])
        # key: cada botão precisa de um nome único, senão o Streamlit os confunde.
        if coluna_aprovar.button("Aprovar", key=f"aprovar_{sessao.id}"):
            decidir(db, sessao, usuario, aprovar=True)
        if coluna_rejeitar.button("Rejeitar", key=f"rejeitar_{sessao.id}"):
            decidir(db, sessao, usuario, aprovar=False)

apoio.fechar_sessao(db)
