"""
Fluxo principal do EV ChargeOps — um ciclo por mês, na ordem da Sprint 01:

  1. Ingestão e normalização das sessões encerradas no mês
  2. IA: detecção de anomalias  -> decide o que pode ser cobrado
  3. IA: clustering de perfis    -> atualiza o perfil de cada usuário
  4. Rateio e geração das faturas (só sessões validadas)
  5. IA: previsão do próximo mês (usa o perfil como variável)
  6. IA: otimização de horário + insights anexados às faturas
  7. Fecha as faturas do mês anterior

A IA está no meio do caminho do dinheiro: sem a etapa 2 nenhuma sessão chega
ao status "validada" e nenhuma fatura recebe itens.
"""
from collections import defaultdict

import pandas as pd
from sqlalchemy import select

from src import config
from src.db.modelos import (Carregador, Fatura, InsightIA, PrevisaoConsumo, Sessao,
                            Usuario, Veiculo)
from src.ia import anomalias, horarios, insights, perfis, previsao
from src.ingestao.ingestor import ingerir, leituras_da_sessao
from src.rateio.calculo import comparar_modalidades
from src.rateio.servico import gerar_faturas_do_mes
from src.rateio.tarifas import dividir_energia_por_faixa, ociosidade_cobravel_por_faixa


class EstadoPipeline:
    """Guarda cálculos caros entre os meses (energia por faixa de cada sessão)."""

    def __init__(self):
        self.faixas: dict[int, dict[str, float]] = {}
        self.ocio_pico_h: dict[int, float] = {}
        self.log: list[str] = []

    def registrar(self, msg: str):
        self.log.append(msg)
        print(msg)


# ---------------------------------------------------------------------------
# Apoio: DataFrame de sessões
# ---------------------------------------------------------------------------
def _faixas_da_sessao(estado, s: Sessao) -> dict[str, float]:
    if s.id not in estado.faixas:
        leituras = leituras_da_sessao(s)
        faixas = dividir_energia_por_faixa(leituras)
        total = sum(faixas.values())
        estado.faixas[s.id] = ({f: v * s.energia_kwh / total for f, v in faixas.items()}
                               if total > 0 else {})
        estado.ocio_pico_h[s.id] = ociosidade_cobravel_por_faixa(leituras, tolerancia_min=0).get("pico", 0.0)
    return estado.faixas[s.id]


def sessoes_df(db, estado, status: tuple = ("validada",), ate_mes: str | None = None,
               apenas_mes: str | None = None) -> pd.DataFrame:
    q = select(Sessao, Veiculo.capacidade_bateria_kwh).join(Veiculo, Veiculo.id == Sessao.veiculo_id) \
        .where(Sessao.status.in_(status))
    if ate_mes:
        q = q.where(Sessao.mes_competencia <= ate_mes)
    if apenas_mes:
        q = q.where(Sessao.mes_competencia == apenas_mes)
    linhas = []
    for s, bateria in db.execute(q).all():
        f = _faixas_da_sessao(estado, s) if s.status == "validada" else {}
        linhas.append({"id": s.id, "usuario_id": s.usuario_id, "veiculo_id": s.veiculo_id,
                       "carregador_id": s.carregador_id,
                       "inicio": s.inicio, "fim": s.fim, "duracao_minutos": s.duracao_minutos,
                       "energia_kwh": s.energia_kwh, "potencia_media_kw": s.potencia_media_kw,
                       "ociosidade_min": s.ociosidade_min, "bateria_kwh": bateria,
                       "mes_competencia": s.mes_competencia,
                       "energia_pico_kwh": f.get("pico", 0.0),
                       "energia_inter_kwh": f.get("intermediario", 0.0),
                       "energia_fora_kwh": f.get("fora_pico", 0.0),
                       "ocio_pico_h": estado.ocio_pico_h.get(s.id, 0.0)})
    df = pd.DataFrame(linhas)
    if not df.empty:
        df["inicio"] = pd.to_datetime(df["inicio"])
        df["fim"] = pd.to_datetime(df["fim"])
    return df


# ---------------------------------------------------------------------------
# Etapa 2 — anomalias
# ---------------------------------------------------------------------------
def etapa_anomalias(db, estado, novas: list[Sessao], mes: str):
    candidatas = [s for s in novas if s.status == "registrada"]
    historico = sessoes_df(db, estado, ate_mes=str(pd.Period(mes) - 1))

    # camada 1: regras
    para_modelo = []
    for s in candidatas:
        veiculo = db.get(Veiculo, s.veiculo_id)
        decisao, motivos = anomalias.aplicar_regras(s, veiculo.capacidade_bateria_kwh,
                                                    leituras_da_sessao(s))
        if decisao:
            s.status, s.motivo_revisao = decisao, "; ".join(motivos)
        else:
            para_modelo.append((s, veiculo.capacidade_bateria_kwh))
    if not para_modelo:
        return

    novas_df = pd.DataFrame([{
        "id": s.id, "usuario_id": s.usuario_id, "veiculo_id": s.veiculo_id,
        "inicio": pd.Timestamp(s.inicio),
        "duracao_minutos": s.duracao_minutos, "energia_kwh": s.energia_kwh,
        "potencia_media_kw": s.potencia_media_kw, "ociosidade_min": s.ociosidade_min,
        "bateria_kwh": b} for s, b in para_modelo]).set_index("id")

    # camada 2: Isolation Forest (partida a frio: no 1º mês treina com o próprio mês)
    base_treino = historico if len(historico) >= config.MIN_AMOSTRAS_TREINO_IF else \
        pd.concat([historico, novas_df.reset_index()], ignore_index=True)
    detector = anomalias.DetectorAnomalias().treinar(base_treino)
    resultado = detector.pontuar(novas_df)
    feats_ref = anomalias.montar_features(base_treino)

    for s, _ in para_modelo:
        score, anomala = resultado.loc[s.id, "score"], bool(resultado.loc[s.id, "anomala"])
        s.score_anomalia = None if pd.isna(score) else round(float(score), 4)
        motivos = []
        # sessão interrompida já tem explicação (perda de conexão) e a regra da
        # Sprint 01 manda cobrar o que foi registrado; o modelo não a segura
        if anomala and s.encerramento == "normal":
            motivos.append("Isolation Forest: " + anomalias.explicar(
                anomalias.montar_features(novas_df.loc[[s.id]]).iloc[0], feats_ref))
        # sessão interrompida tem energia baixa por definição: não comparamos
        if s.encerramento == "normal" and not historico.empty:
            hist_v = historico[historico["veiculo_id"] == s.veiculo_id]["energia_kwh"]
            z = anomalias.zscore_veiculo(s.energia_kwh, hist_v)
            if z is not None and abs(z) > config.LIMITE_Z_VEICULO:
                motivos.append(f"energia fora do padrão do veículo (z={z:.1f}, média "
                               f"{hist_v.mean():.1f} kWh)")
        if motivos:
            s.status, s.motivo_revisao = "em_revisao", "; ".join(motivos)
        else:
            s.status = "validada"
    estado.registrar(f"   IA anomalias: modelo treinado com {detector.n_treino} sessões")


# ---------------------------------------------------------------------------
# Etapas 3, 5 e 6 — perfil, previsão, horário e insights
# ---------------------------------------------------------------------------
def _meses_ativos(usuarios, meses_ate_agora):
    return {u.id: sum(1 for m in meses_ate_agora if pd.Period(m) >= pd.Period(u.criado_em, "M"))
            for u in usuarios}


def etapa_perfis(db, estado, mes, meses_ate_agora):
    usuarios = db.scalars(select(Usuario)).all()
    hist = sessoes_df(db, estado, ate_mes=mes)
    feats = perfis.features_por_usuario(hist, _meses_ativos(usuarios, meses_ate_agora))
    resultado, centros = perfis.agrupar(feats)
    for u in usuarios:
        u.perfil = resultado.loc[u.id, "perfil"] if u.id in resultado.index else "Sem uso no período"
    return resultado, centros


def etapa_previsao(db, estado, mes, meses_ate_agora, resultado_perfis):
    usuarios = db.scalars(select(Usuario)).all()
    udf = pd.DataFrame([{"id": u.id, "criado_em": u.criado_em} for u in usuarios])
    hist = sessoes_df(db, estado, ate_mes=mes)
    tab = previsao.tabela_mensal(hist, udf, meses_ate_agora)
    media_geral = resultado_perfis["kwh_mes"].mean()
    tab["kwh_cluster"] = tab["usuario_id"].map(
        resultado_perfis.groupby("perfil")["kwh_mes"].transform("mean")).fillna(media_geral)

    modelo = previsao.PrevisorConsumo().treinar(tab)
    atual = tab[tab["mes"] == mes]
    prev = modelo.prever(atual).set_index("usuario_id")
    prox = previsao.proximo_mes(mes)

    # mistura de faixas do histórico do usuário para converter kWh previsto em R$
    mix = hist.groupby("usuario_id")[["energia_pico_kwh", "energia_inter_kwh", "energia_fora_kwh"]].sum()
    saida = {}
    for u in usuarios:
        if u.id not in prev.index:
            continue
        kwh = float(prev.loc[u.id, "kwh_previsto"])
        if u.id in mix.index and mix.loc[u.id].sum() > 0:
            m = mix.loc[u.id] / mix.loc[u.id].sum()
            faixas = {"pico": kwh * m["energia_pico_kwh"], "intermediario": kwh * m["energia_inter_kwh"],
                      "fora_pico": kwh * m["energia_fora_kwh"]}
        else:
            faixas = {"intermediario": kwh}
        custos = comparar_modalidades(faixas)
        valor = custos[u.modalidade] if kwh > 0 or u.modalidade == "mensal" else 0.0
        db.add(PrevisaoConsumo(usuario_id=u.id, mes_base=mes, mes_previsto=prox, kwh_previsto=kwh,
                               valor_previsto=valor, metodo=prev.loc[u.id, "metodo"]))
        linha = atual[atual["usuario_id"] == u.id].iloc[0]
        saida[u.id] = {"kwh_previsto": kwh, "valor_previsto": valor, "custos": custos,
                       "kwh_media_hist": float(linha["kwh_media_hist"])}
    estado.registrar(f"   IA previsão: {modelo.n_treino} pares mês->mês de treino, "
                     f"método {'Ridge' if modelo.treinado else 'média do cluster (partida a frio)'}")
    return saida


def etapa_insights(db, estado, mes, faturas, prev, resultado_perfis):
    n_carregadores = len(db.scalars(select(Carregador)).all())
    hist = sessoes_df(db, estado, ate_mes=mes)
    ocup = horarios.ocupacao_por_hora(hist, n_carregadores)
    do_mes = hist[hist["mes_competencia"] == mes]
    prox = previsao.proximo_mes(mes)
    t = {x["tipo_horario"]: x for x in config.TARIFAS}

    # média de kWh do mês por perfil (só quem usou)
    kwh_usuario_mes = do_mes.groupby("usuario_id")["energia_kwh"].sum()
    perfil_de = {u.id: u.perfil for u in db.scalars(select(Usuario))}
    media_grupo = defaultdict(list)
    for uid, kwh in kwh_usuario_mes.items():
        media_grupo[perfil_de[uid]].append(kwh)

    total_insights = 0
    for fatura in faturas:
        u = db.get(Usuario, fatura.usuario_id)
        g = do_mes[do_mes["usuario_id"] == u.id]
        kwh = float(g["energia_kwh"].sum())
        e_pico, e_fora = float(g["energia_pico_kwh"].sum()), float(g["energia_fora_kwh"].sum())
        hist_u = hist[hist["usuario_id"] == u.id]
        dur_media = hist_u["duracao_minutos"].mean() / 60 if not hist_u.empty else 4
        hora = horarios.sugerir_janela(ocup, min(dur_media, 9))
        revisao = db.scalars(select(Sessao).where(Sessao.usuario_id == u.id, Sessao.mes_competencia == mes,
                                                  Sessao.status == "em_revisao")).all()
        p = prev.get(u.id, {})
        rec = None
        if p.get("kwh_previsto", 0) > 0:
            outra = "avulso" if u.modalidade == "mensal" else "mensal"
            economia = p["custos"][u.modalidade] - p["custos"][outra]
            if economia >= 5:
                rec = {"atual": u.modalidade, "sugerida": outra, "economia": round(economia, 2)}
        ctx = {
            "mes": mes, "proximo_mes": prox, "modalidade": u.modalidade, "perfil": u.perfil,
            "kwh_mes": kwh,
            "pct_pico": e_pico / kwh if kwh else 0, "pct_fora_pico": e_fora / kwh if kwh else 0,
            "sessoes_em_revisao": [{"id": s.id, "motivo": s.motivo_revisao} for s in revisao],
            "kwh_previsto": p.get("kwh_previsto"), "valor_previsto": p.get("valor_previsto", 0),
            "kwh_media_hist": p.get("kwh_media_hist", 0),
            "economia_horario": horarios.economia_potencial(e_pico, float(g["ocio_pico_h"].sum())),
            "hora_sugerida": hora, "ocupacao_sugerida": float(ocup[hora]),
            "economia_noturno": round(e_fora * (t["pico"]["valor_kwh"] - t["fora_pico"]["valor_kwh"]), 2),
            "media_grupo_kwh": float(pd.Series(media_grupo.get(u.perfil, [0])).mean()),
            "recomendacao_modalidade": rec,
        }
        for i in insights.insights_usuario(ctx):
            db.add(InsightIA(usuario_id=u.id, fatura_id=fatura.id, tipo=i["tipo"], mensagem=i["mensagem"],
                             valor_referencia=i["valor"], periodo_referencia=mes))
            total_insights += 1

    # visão do gestor
    todas = db.scalars(select(Sessao).where(Sessao.mes_competencia == mes)).all()
    ctx_g = {
        "mes": mes, "proximo_mes": prox,
        "n_validadas": sum(s.status == "validada" for s in todas),
        "kwh_total": sum(s.energia_kwh for s in todas if s.status == "validada"),
        "receita": sum(f.valor_energia + f.valor_ociosidade for f in faturas),
        "receita_fixa": sum(f.valor_fixo for f in faturas),
        "n_revisao": sum(s.status == "em_revisao" for s in todas),
        "kwh_revisao": sum(s.energia_kwh for s in todas if s.status == "em_revisao"),
        "n_descartadas": sum(s.status == "descartada" for s in todas),
        "kwh_previsto_total": sum(v["kwh_previsto"] for v in prev.values()),
        "hora_pico_ocupacao": int(ocup.idxmax()), "ocupacao_maxima": float(ocup.max()),
    }
    for i in insights.insights_gestor(ctx_g):
        db.add(InsightIA(usuario_id=None, fatura_id=None, tipo=i["tipo"], mensagem=i["mensagem"],
                         valor_referencia=i["valor"], periodo_referencia=mes))
    return total_insights


# ---------------------------------------------------------------------------
# Ciclo completo
# ---------------------------------------------------------------------------
def executar_mes(db, estado, mes: str, registros: list[dict], meses_ate_agora: list[str]):
    estado.registrar(f"\n=== Ciclo {mes} ===")

    # 7 (do ciclo anterior): fecha as faturas dos meses passados
    for f in db.scalars(select(Fatura).where(Fatura.status == "aberta", Fatura.referencia_mes < mes)):
        f.status = "fechada"

    novas = [ingerir(r, db) for r in registros]
    db.flush()
    erros = sum(s.status == "erro" for s in novas)
    estado.registrar(f"1. Ingestão: {len(novas)} sessões recebidas, {erros} rejeitada(s) na validação")

    etapa_anomalias(db, estado, novas, mes)
    cont = defaultdict(int)
    for s in novas:
        cont[s.status] += 1
    estado.registrar(f"2. IA anomalias: {cont['validada']} validadas, {cont['em_revisao']} em revisão, "
                     f"{cont['descartada']} descartadas")

    resultado_perfis, centros = etapa_perfis(db, estado, mes, meses_ate_agora)
    estado.registrar(f"3. IA perfis: {len(centros)} grupos -> " + ", ".join(centros["perfil"]))

    faturas = gerar_faturas_do_mes(db, mes)
    estado.registrar(f"4. Rateio: {len(faturas)} faturas, total R$ "
                     f"{sum(f.valor_final for f in faturas):.2f}")

    prev = etapa_previsao(db, estado, mes, meses_ate_agora, resultado_perfis)
    estado.registrar(f"5. IA previsão: {len(prev)} usuários com projeção para {previsao.proximo_mes(mes)}")

    n = etapa_insights(db, estado, mes, faturas, prev, resultado_perfis)
    estado.registrar(f"6. IA insights: {n} insights anexados às faturas")
    db.commit()


def executar_tudo(db, registros: list[dict]) -> EstadoPipeline:
    estado = EstadoPipeline()
    por_mes = defaultdict(list)
    for r in registros:
        por_mes[r["fim"].strftime("%Y-%m")].append(r)
    meses = sorted(por_mes)
    for i, mes in enumerate(meses):
        executar_mes(db, estado, mes, por_mes[mes], meses[: i + 1])
    return estado
