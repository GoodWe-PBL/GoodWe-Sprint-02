"""
Modelo de rateio da Sprint 01, em funções puras (sem banco), para poder testar.

  Modalidade A — Plano mensal:   F = Σ(E × T) + C + [P]
  Modalidade B — Carga avulsa:   V = E × (T + M) + [P]

  E = energia (kWh) de cada faixa horária
  T = tarifa da faixa (R$/kWh)
  C = contribuição fixa mensal
  M = margem avulsa (R$/kWh)
  P = penalidade de ociosidade (horas cobráveis × taxa da faixa)
"""
from src import config


def tarifas_por_faixa(tarifas=None):
    """Transforma a lista de tarifas em dicionário: nome da faixa -> tarifa."""
    tarifas = tarifas or config.TARIFAS
    return {tarifa["tipo_horario"]: tarifa for tarifa in tarifas}


def itens_da_sessao(energia_por_faixa, ociosidade_por_faixa, modalidade, tarifas=None,
                    ociosidade_ativa=None):
    """Gera os itens de cobrança de uma sessão (um por faixa e por tipo).

    energia_por_faixa:    {faixa: kWh}
    ociosidade_por_faixa: {faixa: horas cobráveis}
    """
    if modalidade not in ("mensal", "avulso"):
        raise ValueError(f"Modalidade desconhecida: {modalidade}")
    if ociosidade_ativa is None:
        ociosidade_ativa = config.OCIOSIDADE_ATIVA
    tarifa_da_faixa = tarifas_por_faixa(tarifas)
    margem = config.M_MARGEM_AVULSA if modalidade == "avulso" else 0.0  # só o avulso paga M

    itens = []
    for faixa, kwh in energia_por_faixa.items():
        if kwh <= 0:
            continue
        valor_do_kwh = tarifa_da_faixa[faixa]["valor_kwh"] + margem  # T, ou T + M no avulso
        itens.append({"tipo_item": "energia", "faixa": faixa, "energia_kwh": round(kwh, 3),
                      "horas_ociosidade": 0.0, "valor_unitario": round(valor_do_kwh, 4),
                      "valor": round(kwh * valor_do_kwh, 2)})

    if ociosidade_ativa:
        for faixa, horas in ociosidade_por_faixa.items():
            taxa_por_hora = tarifa_da_faixa[faixa]["taxa_ocupacao_hora"]
            if horas <= 0 or taxa_por_hora <= 0:
                continue  # no noturno a taxa é zero: nada a cobrar
            itens.append({"tipo_item": "ociosidade", "faixa": faixa, "energia_kwh": 0.0,
                          "horas_ociosidade": round(horas, 3), "valor_unitario": taxa_por_hora,
                          "valor": round(horas * taxa_por_hora, 2)})
    return itens


def valor_sessao(itens):
    """Soma o valor de todos os itens de uma sessão."""
    return round(sum(item["valor"] for item in itens), 2)


def liquidar_avulso(valor_pre_autorizado, valor_real):
    """Carga avulsa é paga antes (pré-autorização). Ao final:
    sobra -> estorno automático; falta -> cobrança complementar."""
    return {"estorno": round(max(0.0, valor_pre_autorizado - valor_real), 2),
            "complemento": round(max(0.0, valor_real - valor_pre_autorizado), 2)}


def fechar_fatura(modalidade, itens, n_sessoes=0, valores_por_sessao=None):
    """Totaliza a fatura do mês. Devolve um dicionário com os totais.

    Regras da Sprint 01 para o mês sem consumo:
      - plano mensal: paga só o C fixo;
      - avulso: nenhuma cobrança.
    """
    energia = round(sum(item["valor"] for item in itens if item["tipo_item"] == "energia"), 2)
    ociosidade = round(sum(item["valor"] for item in itens if item["tipo_item"] == "ociosidade"), 2)
    kwh = round(sum(item["energia_kwh"] for item in itens), 3)

    if modalidade == "mensal":
        # F = Σ(E × T) + C + P
        fixo = config.C_FIXO_MENSAL
        return {"total_kwh": kwh, "valor_energia": energia, "valor_ociosidade": ociosidade,
                "valor_fixo": fixo, "valor_final": round(energia + ociosidade + fixo, 2),
                "pre_autorizado": 0.0, "estorno": 0.0}

    # Avulso: V = E × (T + M) + P. Cada sessão teve uma pré-autorização; o que
    # sobrou de cada uma é estornado.
    valores_por_sessao = valores_por_sessao or []
    pre_autorizado = config.PRE_AUTORIZACAO_AVULSA * n_sessoes
    estorno = 0
    for valor in valores_por_sessao:
        estorno += liquidar_avulso(config.PRE_AUTORIZACAO_AVULSA, valor)["estorno"]
    return {"total_kwh": kwh, "valor_energia": energia, "valor_ociosidade": ociosidade,
            "valor_fixo": 0.0, "valor_final": round(energia + ociosidade, 2),
            "pre_autorizado": round(pre_autorizado, 2), "estorno": round(estorno, 2)}


def comparar_modalidades(energia_por_faixa_mes, tarifas=None):
    """Quanto o mesmo consumo custaria em cada modalidade (sem ociosidade)."""
    tarifa_da_faixa = tarifas_por_faixa(tarifas)
    custo_da_energia = sum(kwh * tarifa_da_faixa[faixa]["valor_kwh"]
                           for faixa, kwh in energia_por_faixa_mes.items())
    kwh_total = sum(energia_por_faixa_mes.values())
    return {"mensal": round(custo_da_energia + config.C_FIXO_MENSAL, 2),
            "avulso": round(custo_da_energia + kwh_total * config.M_MARGEM_AVULSA, 2)}
