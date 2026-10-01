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


def _tarifa_por_tipo(tarifas=None) -> dict[str, dict]:
    return {t["tipo_horario"]: t for t in (tarifas or config.TARIFAS)}


def itens_da_sessao(energia_por_faixa: dict[str, float],
                    ociosidade_por_faixa: dict[str, float],
                    modalidade: str,
                    tarifas=None,
                    ociosidade_ativa: bool | None = None) -> list[dict]:
    """Gera os itens de cobrança de uma sessão (um por faixa e por tipo)."""
    if modalidade not in ("mensal", "avulso"):
        raise ValueError(f"Modalidade desconhecida: {modalidade}")
    ociosidade_ativa = config.OCIOSIDADE_ATIVA if ociosidade_ativa is None else ociosidade_ativa
    tarifas_tipo = _tarifa_por_tipo(tarifas)
    margem = config.M_MARGEM_AVULSA if modalidade == "avulso" else 0.0

    itens = []
    for faixa, kwh in energia_por_faixa.items():
        if kwh <= 0:
            continue
        unitario = tarifas_tipo[faixa]["valor_kwh"] + margem
        itens.append({"tipo_item": "energia", "faixa": faixa, "energia_kwh": round(kwh, 3),
                      "horas_ociosidade": 0.0, "valor_unitario": round(unitario, 4),
                      "valor": round(kwh * unitario, 2)})

    if ociosidade_ativa:
        for faixa, horas in ociosidade_por_faixa.items():
            taxa = tarifas_tipo[faixa]["taxa_ocupacao_hora"]
            if horas <= 0 or taxa <= 0:
                continue  # no noturno a taxa é zero: nada a cobrar
            itens.append({"tipo_item": "ociosidade", "faixa": faixa, "energia_kwh": 0.0,
                          "horas_ociosidade": round(horas, 3), "valor_unitario": taxa,
                          "valor": round(horas * taxa, 2)})
    return itens


def valor_sessao(itens: list[dict]) -> float:
    return round(sum(i["valor"] for i in itens), 2)


def liquidar_avulso(valor_pre_autorizado: float, valor_real: float) -> dict:
    """Carga avulsa é paga antes (pré-autorização). Ao final:
    sobra -> estorno automático; falta -> cobrança complementar."""
    return {"estorno": round(max(0.0, valor_pre_autorizado - valor_real), 2),
            "complemento": round(max(0.0, valor_real - valor_pre_autorizado), 2)}


def fechar_fatura(modalidade: str, itens: list[dict], n_sessoes: int = 0,
                  valores_por_sessao: list[float] | None = None) -> dict:
    """Totaliza a fatura do mês.

    Regras da Sprint 01 para o mês sem consumo:
      - plano mensal: paga só o C fixo;
      - avulso: nenhuma cobrança.
    """
    energia = round(sum(i["valor"] for i in itens if i["tipo_item"] == "energia"), 2)
    ociosidade = round(sum(i["valor"] for i in itens if i["tipo_item"] == "ociosidade"), 2)
    kwh = round(sum(i["energia_kwh"] for i in itens), 3)

    if modalidade == "mensal":
        fixo = config.C_FIXO_MENSAL
        return {"total_kwh": kwh, "valor_energia": energia, "valor_ociosidade": ociosidade,
                "valor_fixo": fixo, "valor_final": round(energia + ociosidade + fixo, 2),
                "pre_autorizado": 0.0, "estorno": 0.0}

    valores_por_sessao = valores_por_sessao or []
    pre = config.PRE_AUTORIZACAO_AVULSA * n_sessoes
    estorno = sum(liquidar_avulso(config.PRE_AUTORIZACAO_AVULSA, v)["estorno"]
                  for v in valores_por_sessao)
    return {"total_kwh": kwh, "valor_energia": energia, "valor_ociosidade": ociosidade,
            "valor_fixo": 0.0, "valor_final": round(energia + ociosidade, 2),
            "pre_autorizado": round(pre, 2), "estorno": round(estorno, 2)}


def comparar_modalidades(energia_por_faixa_mes: dict[str, float], tarifas=None) -> dict:
    """Quanto o mesmo consumo custaria em cada modalidade (sem ociosidade)."""
    tarifas_tipo = _tarifa_por_tipo(tarifas)
    base = sum(kwh * tarifas_tipo[f]["valor_kwh"] for f, kwh in energia_por_faixa_mes.items())
    kwh = sum(energia_por_faixa_mes.values())
    return {"mensal": round(base + config.C_FIXO_MENSAL, 2),
            "avulso": round(base + kwh * config.M_MARGEM_AVULSA, 2)}
