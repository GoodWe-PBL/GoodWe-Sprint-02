"""
Motor de rateio ligado ao banco (Etapas 6 e 7 da Sprint 01): transforma sessões
validadas pela IA em itens de fatura e fecha a fatura mensal de cada usuário.
"""
from datetime import date

import pandas as pd
from sqlalchemy import select

from src.db.modelos import Fatura, ItemFatura, Sessao, Tarifa, Usuario
from src.ingestao.ingestor import leituras_da_sessao
from src.rateio.calculo import fechar_fatura, itens_da_sessao, valor_sessao
from src.rateio.tarifas import dividir_energia_por_faixa, ociosidade_cobravel_por_faixa


def energia_cobrada_por_faixa(sessao):
    """{faixa: kWh} da sessão, somando exatamente o kWh do medidor.

    A telemetria pode ter pequenas diferenças de arredondamento em relação ao
    medidor; o kWh cobrado é o do medidor, distribuído na proporção da telemetria.
    """
    energia_por_faixa = dividir_energia_por_faixa(leituras_da_sessao(sessao))
    total_da_telemetria = sum(energia_por_faixa.values())
    if total_da_telemetria > 0:
        for faixa, kwh in energia_por_faixa.items():
            energia_por_faixa[faixa] = kwh * sessao.energia_kwh / total_da_telemetria
    return energia_por_faixa


def calcular_itens(sessao, modalidade):
    """Itens de cobrança (energia e ociosidade) de uma sessão gravada no banco."""
    energia_por_faixa = energia_cobrada_por_faixa(sessao)
    ociosidade_por_faixa = ociosidade_cobravel_por_faixa(leituras_da_sessao(sessao))
    return itens_da_sessao(energia_por_faixa, ociosidade_por_faixa, modalidade)


def gravar_itens(db, fatura, sessao, itens, ajuste=False):
    """Grava os itens na fatura e marca a sessão como faturada."""
    # nome da faixa -> id da tarifa ativa no banco
    id_da_tarifa = {}
    for tarifa in db.scalars(select(Tarifa).where(Tarifa.ativa)):
        id_da_tarifa[tarifa.tipo_horario] = tarifa.id

    for item in itens:
        db.add(ItemFatura(fatura_id=fatura.id, sessao_id=sessao.id,
                          tarifa_id=id_da_tarifa[item["faixa"]],
                          tipo_item=item["tipo_item"], tipo_horario_aplicado=item["faixa"],
                          energia_kwh=item["energia_kwh"], horas_ociosidade=item["horas_ociosidade"],
                          valor_unitario=item["valor_unitario"], valor_total_item=item["valor"],
                          ajuste_mes_anterior=ajuste))
    sessao.faturada = True


def recalcular_totais(db, fatura):
    """Soma de novo todos os itens da fatura e atualiza os campos de total."""
    db.flush()  # envia ao banco os itens recém-criados, para a consulta abaixo enxergá-los
    itens_gravados = db.scalars(select(ItemFatura).where(ItemFatura.fatura_id == fatura.id)).all()

    itens = []
    valor_por_sessao = {}  # sessao_id -> valor total da sessão (usado no estorno do avulso)
    for item in itens_gravados:
        itens.append({"tipo_item": item.tipo_item, "energia_kwh": item.energia_kwh,
                      "valor": item.valor_total_item})
        valor_por_sessao[item.sessao_id] = valor_por_sessao.get(item.sessao_id, 0.0) + item.valor_total_item

    totais = fechar_fatura(fatura.modalidade, itens, n_sessoes=len(valor_por_sessao),
                           valores_por_sessao=list(valor_por_sessao.values()))
    fatura.total_kwh = totais["total_kwh"]
    fatura.valor_energia = totais["valor_energia"]
    fatura.valor_ociosidade = totais["valor_ociosidade"]
    fatura.valor_fixo = totais["valor_fixo"]
    fatura.valor_final = totais["valor_final"]
    fatura.pre_autorizado = totais["pre_autorizado"]
    fatura.estorno = totais["estorno"]


def data_de_vencimento(mes):
    """A fatura de um mês vence no dia 10 do mês seguinte."""
    mes_seguinte = pd.Period(mes) + 1
    return date(mes_seguinte.year, mes_seguinte.month, 10)


def gerar_faturas_do_mes(db, mes):
    """Uma fatura por usuário cadastrado no mês. Só entram sessões com status
    'validada' (decisão da IA). Sessões em revisão ficam contadas, não cobradas."""
    faturas = []
    fim_do_mes = pd.Period(mes).end_time.to_pydatetime()
    usuarios = db.scalars(select(Usuario).where(Usuario.criado_em <= fim_do_mes)).all()
    for usuario in usuarios:
        sessoes = db.scalars(select(Sessao).where(
            Sessao.usuario_id == usuario.id, Sessao.mes_competencia == mes)).all()
        validadas = [s for s in sessoes if s.status == "validada" and not s.faturada]
        em_revisao = [s for s in sessoes if s.status == "em_revisao"]
        if usuario.modalidade == "avulso" and not validadas and not em_revisao:
            continue  # avulso sem uso: nenhuma cobrança, nenhum extrato

        fatura = Fatura(usuario_id=usuario.id, referencia_mes=mes, modalidade=usuario.modalidade,
                        sessoes_em_revisao=len(em_revisao), vencimento=data_de_vencimento(mes))
        db.add(fatura)
        db.flush()  # gera o id da fatura, usado nos itens
        for sessao in validadas:
            gravar_itens(db, fatura, sessao, calcular_itens(sessao, usuario.modalidade))
        recalcular_totais(db, fatura)
        faturas.append(fatura)
    db.flush()
    return faturas


def revisar_sessao(db, sessao_id, aprovar, observacao=""):
    """Decisão do gestor sobre uma sessão retida pela IA.
    Aprovada -> entra como ajuste na fatura aberta mais recente do usuário.
    Rejeitada -> vira "descartada" e nunca é cobrada."""
    sessao = db.get(Sessao, sessao_id)
    if sessao is None or sessao.status != "em_revisao":
        raise ValueError(f"Sessão {sessao_id} não está em revisão.")

    # registra a decisão do gestor junto do motivo que a IA tinha dado
    nota = f" | gestor: {'aprovada' if aprovar else 'rejeitada'}"
    if observacao:
        nota += f" ({observacao})"
    sessao.motivo_revisao = (sessao.motivo_revisao or "") + nota

    if not aprovar:
        sessao.status = "descartada"
        diminuir_contagem_em_revisao(db, sessao)
        db.commit()
        return sessao

    sessao.status = "validada"
    usuario = db.get(Usuario, sessao.usuario_id)
    fatura = db.scalar(select(Fatura).where(Fatura.usuario_id == usuario.id, Fatura.status == "aberta")
                       .order_by(Fatura.referencia_mes.desc()))
    if fatura is None:
        raise ValueError("Usuário não tem fatura aberta para receber o ajuste.")
    # se a sessão é de um mês que já fechou, o item entra marcado como ajuste
    e_ajuste = fatura.referencia_mes != sessao.mes_competencia
    gravar_itens(db, fatura, sessao, calcular_itens(sessao, usuario.modalidade), ajuste=e_ajuste)
    diminuir_contagem_em_revisao(db, sessao)
    recalcular_totais(db, fatura)
    db.commit()
    return sessao


def diminuir_contagem_em_revisao(db, sessao):
    """A fatura do mês da sessão guarda quantas sessões estão retidas; tira uma."""
    fatura = db.scalar(select(Fatura).where(Fatura.usuario_id == sessao.usuario_id,
                                            Fatura.referencia_mes == sessao.mes_competencia))
    if fatura and fatura.sessoes_em_revisao > 0:
        fatura.sessoes_em_revisao -= 1


def valor_da_sessao(sessao, modalidade):
    """Quanto a sessão custaria (usado para mostrar o valor antes de aprovar)."""
    return valor_sessao(calcular_itens(sessao, modalidade))
