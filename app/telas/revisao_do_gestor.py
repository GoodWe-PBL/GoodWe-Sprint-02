# Tela 4 - Revisão do gestor.
# Lista as sessões que a IA reteve (status "em_revisao") e deixa o gestor aprovar
# ou rejeitar cada uma. Os dados vêm das tabelas sessao, usuario e fatura; a
# decisão é gravada pela função revisar_sessao de src/rateio/servico.py.
from tkinter import messagebox

import customtkinter as ctk
from sqlalchemy import select

import banco
import componentes
from src.db.modelos import Fatura, Sessao, Usuario
from src.rateio.servico import revisar_sessao, valor_da_sessao


def valor_da_fatura_aberta(db, usuario_id):
    """Total da fatura aberta mais recente do usuário (é nela que entra a sessão aprovada)."""
    fatura = db.scalar(select(Fatura).where(Fatura.usuario_id == usuario_id, Fatura.status == "aberta")
                       .order_by(Fatura.referencia_mes.desc()))
    if fatura is None:
        return 0.0
    return fatura.valor_final


def decidir(area, sessao_id, aprovar):
    """Chamada pelos botões: grava a decisão e redesenha a tela com o aviso do resultado."""
    db = banco.abrir_sessao()
    usuario = db.get(Usuario, db.get(Sessao, sessao_id).usuario_id)
    antes = valor_da_fatura_aberta(db, usuario.id)
    try:
        revisar_sessao(db, sessao_id, aprovar=aprovar)
    except ValueError as erro:  # ex.: usuário sem fatura aberta para receber o ajuste
        db.rollback()
        banco.fechar_sessao(db)
        messagebox.showerror("Revisão", str(erro))
        return
    depois = valor_da_fatura_aberta(db, usuario.id)
    banco.fechar_sessao(db)
    decisao = "aprovada" if aprovar else "rejeitada"
    montar(area, f"Sessão #{sessao_id} {decisao}. Fatura aberta de {usuario.nome}: "
                 f"{componentes.reais(antes)} -> {componentes.reais(depois)}")


def mostrar_cartao(area, db, sessao):
    """Um quadro com os dados de uma sessão retida e os botões de decisão."""
    usuario = db.get(Usuario, sessao.usuario_id)
    fatura_hoje = valor_da_fatura_aberta(db, usuario.id)
    valor_se_aprovada = valor_da_sessao(sessao, usuario.modalidade)

    cartao = ctk.CTkFrame(area)
    cartao.pack(fill="x", pady=5)
    componentes.escrever_texto(
        cartao, f"  Sessão #{sessao.id} - {usuario.nome} - {sessao.inicio:%d/%m/%Y %H:%M} - "
                f"{sessao.energia_kwh:.1f} kWh - {sessao.duracao_minutos / 60:.1f} h")
    componentes.escrever_texto(cartao, f"  Motivo: {sessao.motivo_revisao}")
    componentes.escrever_texto(cartao, f"  Fatura aberta hoje: {componentes.reais(fatura_hoje)}  |  "
                                       f"Valor desta sessão se aprovada: "
                                       f"{componentes.reais(valor_se_aprovada)}")
    botoes = componentes.criar_linha(cartao)
    # Guardamos só o número da sessão: quando o botão for clicado, o "db" desta
    # tela já estará fechado.
    sessao_id = sessao.id
    ctk.CTkButton(botoes, text="Aprovar", width=90,
                  command=lambda: decidir(area, sessao_id, True)).pack(side="left", padx=10)
    ctk.CTkButton(botoes, text="Rejeitar", width=90, fg_color="#c92a2a", hover_color="#a51111",
                  command=lambda: decidir(area, sessao_id, False)).pack(side="left")


def montar(area, aviso=None):
    """Desenha a tela inteira. É chamada de novo depois de cada decisão."""
    componentes.limpar(area)
    componentes.escrever_titulo(area, "Revisão do gestor")
    componentes.escrever_texto(area, "Sessões que a IA reteve. Aprovada: entra na fatura aberta do "
                                     "usuário. Rejeitada: vira \"descartada\" e nunca é cobrada.")
    if aviso:
        componentes.escrever_subtitulo(area, aviso)

    db = banco.abrir_sessao()
    pendentes = db.scalars(select(Sessao).where(Sessao.status == "em_revisao").order_by(Sessao.id)).all()
    if not pendentes:
        componentes.escrever_texto(area, "Nenhuma sessão aguardando revisão.")
    for sessao in pendentes:
        mostrar_cartao(area, db, sessao)
    banco.fechar_sessao(db)
