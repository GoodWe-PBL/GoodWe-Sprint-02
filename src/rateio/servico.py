"""
Motor de rateio ligado ao banco (Etapas 6 e 7 da Sprint 01): transforma sessões
validadas pela IA em itens de fatura e fecha a fatura mensal de cada usuário.
"""
from collections import defaultdict
from datetime import date

import pandas as pd
from sqlalchemy import select

from src.db.modelos import Fatura, ItemFatura, Sessao, Tarifa, Usuario
from src.ingestao.ingestor import leituras_da_sessao
from src.rateio.calculo import fechar_fatura, itens_da_sessao, valor_sessao
from src.rateio.tarifas import dividir_energia_por_faixa, ociosidade_cobravel_por_faixa


def _ids_tarifa(db) -> dict[str, int]:
    return {t.tipo_horario: t.id for t in db.scalars(select(Tarifa).where(Tarifa.ativa))}


def calcular_itens(sessao: Sessao, modalidade: str) -> list[dict]:
    leituras = leituras_da_sessao(sessao)
    energia_faixa = dividir_energia_por_faixa(leituras)
    # a telemetria pode ter pequenas diferenças de arredondamento em relação ao
    # medidor; o kWh cobrado é o do medidor, distribuído na proporção da telemetria
    total_tel = sum(energia_faixa.values())
    if total_tel > 0:
        energia_faixa = {f: kwh * sessao.energia_kwh / total_tel for f, kwh in energia_faixa.items()}
    ociosidade = ociosidade_cobravel_por_faixa(leituras)
    return itens_da_sessao(energia_faixa, ociosidade, modalidade)


def _gravar_itens(db, fatura: Fatura, sessao: Sessao, itens: list[dict], ajuste=False):
    ids = _ids_tarifa(db)
    for i in itens:
        db.add(ItemFatura(fatura_id=fatura.id, sessao_id=sessao.id, tarifa_id=ids[i["faixa"]],
                          tipo_item=i["tipo_item"], tipo_horario_aplicado=i["faixa"],
                          energia_kwh=i["energia_kwh"], horas_ociosidade=i["horas_ociosidade"],
                          valor_unitario=i["valor_unitario"], valor_total_item=i["valor"],
                          ajuste_mes_anterior=ajuste))
    sessao.faturada = True


def recalcular_totais(db, fatura: Fatura):
    db.flush()
    itens = db.scalars(select(ItemFatura).where(ItemFatura.fatura_id == fatura.id)).all()
    dicts = [{"tipo_item": i.tipo_item, "energia_kwh": i.energia_kwh, "valor": i.valor_total_item}
             for i in itens]
    por_sessao = defaultdict(float)
    for i in itens:
        por_sessao[i.sessao_id] += i.valor_total_item
    totais = fechar_fatura(fatura.modalidade, dicts, n_sessoes=len(por_sessao),
                           valores_por_sessao=list(por_sessao.values()))
    for campo, valor in totais.items():
        setattr(fatura, campo, valor)


def _vencimento(mes: str) -> date:
    p = pd.Period(mes) + 1
    return date(p.year, p.month, 10)


def gerar_faturas_do_mes(db, mes: str) -> list[Fatura]:
    """Uma fatura por usuário cadastrado no mês. Só entram sessões com status
    'validada' (decisão da IA). Sessões em revisão ficam contadas, não cobradas."""
    faturas = []
    fim_mes = pd.Period(mes).end_time.to_pydatetime()
    usuarios = db.scalars(select(Usuario).where(Usuario.criado_em <= fim_mes)).all()
    for u in usuarios:
        sessoes = db.scalars(select(Sessao).where(
            Sessao.usuario_id == u.id, Sessao.mes_competencia == mes)).all()
        validadas = [s for s in sessoes if s.status == "validada" and not s.faturada]
        em_revisao = [s for s in sessoes if s.status == "em_revisao"]
        if u.modalidade == "avulso" and not validadas and not em_revisao:
            continue  # avulso sem uso: nenhuma cobrança, nenhum extrato
        fatura = Fatura(usuario_id=u.id, referencia_mes=mes, modalidade=u.modalidade,
                        sessoes_em_revisao=len(em_revisao), vencimento=_vencimento(mes))
        db.add(fatura)
        db.flush()
        for s in validadas:
            _gravar_itens(db, fatura, s, calcular_itens(s, u.modalidade))
        recalcular_totais(db, fatura)
        faturas.append(fatura)
    db.flush()
    return faturas


def revisar_sessao(db, sessao_id: int, aprovar: bool, observacao: str = "") -> Sessao:
    """Decisão do gestor sobre uma sessão retida pela IA.
    Aprovada -> entra como ajuste na fatura aberta mais recente do usuário."""
    sessao = db.get(Sessao, sessao_id)
    if sessao is None or sessao.status != "em_revisao":
        raise ValueError(f"Sessão {sessao_id} não está em revisão.")
    nota = f" | gestor: {'aprovada' if aprovar else 'rejeitada'}" + (f" ({observacao})" if observacao else "")
    sessao.motivo_revisao = (sessao.motivo_revisao or "") + nota
    if not aprovar:
        sessao.status = "descartada"
        _atualizar_contagem_revisao(db, sessao)
        db.commit()
        return sessao

    sessao.status = "validada"
    usuario = db.get(Usuario, sessao.usuario_id)
    fatura = db.scalar(select(Fatura).where(Fatura.usuario_id == usuario.id, Fatura.status == "aberta")
                       .order_by(Fatura.referencia_mes.desc()))
    if fatura is None:
        raise ValueError("Usuário não tem fatura aberta para receber o ajuste.")
    ajuste = fatura.referencia_mes != sessao.mes_competencia
    _gravar_itens(db, fatura, sessao, calcular_itens(sessao, usuario.modalidade), ajuste=ajuste)
    _atualizar_contagem_revisao(db, sessao)
    recalcular_totais(db, fatura)
    db.commit()
    return sessao


def _atualizar_contagem_revisao(db, sessao):
    fatura = db.scalar(select(Fatura).where(Fatura.usuario_id == sessao.usuario_id,
                                            Fatura.referencia_mes == sessao.mes_competencia))
    if fatura and fatura.sessoes_em_revisao > 0:
        fatura.sessoes_em_revisao -= 1


def valor_da_sessao(sessao: Sessao, modalidade: str) -> float:
    return valor_sessao(calcular_itens(sessao, modalidade))
