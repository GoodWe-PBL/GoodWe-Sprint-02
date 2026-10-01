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
import pandas as pd
from sqlalchemy import select

from src import config
from src.db.modelos import (Carregador, Fatura, InsightIA, PrevisaoConsumo, Sessao,
                            Usuario, Veiculo)
from src.ia import anomalias, horarios, insights, perfis, previsao
from src.ingestao.ingestor import ingerir, leituras_da_sessao
from src.rateio.calculo import comparar_modalidades, tarifas_por_faixa
from src.rateio.servico import energia_cobrada_por_faixa, gerar_faturas_do_mes
from src.rateio.tarifas import ociosidade_cobravel_por_faixa


class EstadoPipeline:
    """Memória do pipeline entre um mês e outro.

    Guarda a energia por faixa de cada sessão (cálculo caro, feito uma vez só)
    e as mensagens de log da execução.
    """

    def __init__(self):
        self.energia_por_faixa = {}   # sessao_id -> {faixa: kWh}
        self.horas_ociosas_no_pico = {}  # sessao_id -> horas paradas no horário de pico
        self.log = []

    def registrar(self, mensagem):
        self.log.append(mensagem)
        print(mensagem)


# ---------------------------------------------------------------------------
# Apoio: tabela (DataFrame) de sessões usada pelos modelos de IA
# ---------------------------------------------------------------------------
def energia_por_faixa_da_sessao(estado, sessao):
    """{faixa: kWh} da sessão. Calcula na primeira vez e guarda no estado."""
    if sessao.id not in estado.energia_por_faixa:
        estado.energia_por_faixa[sessao.id] = energia_cobrada_por_faixa(sessao)
        # tolerancia_min=0: aqui interessa todo o tempo parado no pico, sem desconto
        horas_ociosas = ociosidade_cobravel_por_faixa(leituras_da_sessao(sessao), tolerancia_min=0)
        estado.horas_ociosas_no_pico[sessao.id] = horas_ociosas.get("pico", 0.0)
    return estado.energia_por_faixa[sessao.id]


def sessoes_df(db, estado, status=("validada",), ate_mes=None, apenas_mes=None):
    """Tabela com uma linha por sessão, já com a bateria do veículo e a energia por faixa.

    status: quais status entram; ate_mes: só sessões até esse mês; apenas_mes: só desse mês.
    """
    consulta = select(Sessao, Veiculo.capacidade_bateria_kwh) \
        .join(Veiculo, Veiculo.id == Sessao.veiculo_id) \
        .where(Sessao.status.in_(status))
    if ate_mes:
        consulta = consulta.where(Sessao.mes_competencia <= ate_mes)
    if apenas_mes:
        consulta = consulta.where(Sessao.mes_competencia == apenas_mes)

    linhas = []
    for sessao, bateria_kwh in db.execute(consulta).all():
        if sessao.status == "validada":
            energia = energia_por_faixa_da_sessao(estado, sessao)
        else:
            energia = {}
        linhas.append({"id": sessao.id, "usuario_id": sessao.usuario_id, "veiculo_id": sessao.veiculo_id,
                       "carregador_id": sessao.carregador_id,
                       "inicio": sessao.inicio, "fim": sessao.fim,
                       "duracao_minutos": sessao.duracao_minutos,
                       "energia_kwh": sessao.energia_kwh, "potencia_media_kw": sessao.potencia_media_kw,
                       "ociosidade_min": sessao.ociosidade_min, "bateria_kwh": bateria_kwh,
                       "mes_competencia": sessao.mes_competencia,
                       "energia_pico_kwh": energia.get("pico", 0.0),
                       "energia_inter_kwh": energia.get("intermediario", 0.0),
                       "energia_fora_kwh": energia.get("fora_pico", 0.0),
                       "ocio_pico_h": estado.horas_ociosas_no_pico.get(sessao.id, 0.0)})
    tabela = pd.DataFrame(linhas)
    if not tabela.empty:
        tabela["inicio"] = pd.to_datetime(tabela["inicio"])
        tabela["fim"] = pd.to_datetime(tabela["fim"])
    return tabela


# ---------------------------------------------------------------------------
# Etapa 2 — anomalias
# ---------------------------------------------------------------------------
def etapa_anomalias(db, estado, novas, mes):
    """Decide o status de cada sessão nova: validada, em_revisao ou descartada."""
    mes_anterior = str(pd.Period(mes) - 1)
    historico = sessoes_df(db, estado, ate_mes=mes_anterior)

    # camada 1: regras. O que as regras não decidem segue para o modelo.
    para_o_modelo = []  # pares (sessão, bateria do veículo)
    for sessao in novas:
        if sessao.status != "registrada":
            continue  # sessão com erro de validação não passa pela IA
        veiculo = db.get(Veiculo, sessao.veiculo_id)
        bateria_kwh = veiculo.capacidade_bateria_kwh
        decisao, motivos = anomalias.aplicar_regras(sessao, bateria_kwh, leituras_da_sessao(sessao))
        if decisao:
            sessao.status = decisao
            sessao.motivo_revisao = "; ".join(motivos)
        else:
            para_o_modelo.append((sessao, bateria_kwh))
    if not para_o_modelo:
        return

    linhas = []
    for sessao, bateria_kwh in para_o_modelo:
        linhas.append({"id": sessao.id, "usuario_id": sessao.usuario_id, "veiculo_id": sessao.veiculo_id,
                       "inicio": pd.Timestamp(sessao.inicio),
                       "duracao_minutos": sessao.duracao_minutos, "energia_kwh": sessao.energia_kwh,
                       "potencia_media_kw": sessao.potencia_media_kw,
                       "ociosidade_min": sessao.ociosidade_min, "bateria_kwh": bateria_kwh})
    novas_df = pd.DataFrame(linhas).set_index("id")

    # camada 2: Isolation Forest. Partida a frio: enquanto o histórico é pequeno
    # (1º mês), o modelo treina também com as sessões do próprio mês.
    if len(historico) >= config.MIN_AMOSTRAS_TREINO_IF:
        base_de_treino = historico
    else:
        base_de_treino = pd.concat([historico, novas_df.reset_index()], ignore_index=True)
    detector = anomalias.DetectorAnomalias().treinar(base_de_treino)
    resultado = detector.pontuar(novas_df)
    features_de_referencia = anomalias.montar_features(base_de_treino)

    for sessao, _ in para_o_modelo:
        score = resultado.loc[sessao.id, "score"]
        anomala = bool(resultado.loc[sessao.id, "anomala"])
        sessao.score_anomalia = None if pd.isna(score) else round(float(score), 4)

        motivos = []
        # Sessão interrompida já tem explicação (perda de conexão) e a regra da
        # Sprint 01 manda cobrar o que foi registrado: o modelo não a segura, e
        # como ela tem energia baixa por definição também não a comparamos com
        # o histórico do veículo.
        if sessao.encerramento == "normal":
            if anomala:
                features_da_sessao = anomalias.montar_features(novas_df.loc[[sessao.id]]).iloc[0]
                motivos.append("Isolation Forest: "
                               + anomalias.explicar(features_da_sessao, features_de_referencia))
            if not historico.empty:
                energia_do_veiculo = historico[historico["veiculo_id"] == sessao.veiculo_id]["energia_kwh"]
                z = anomalias.zscore_veiculo(sessao.energia_kwh, energia_do_veiculo)
                if z is not None and abs(z) > config.LIMITE_Z_VEICULO:
                    motivos.append(f"energia fora do padrão do veículo (z={z:.1f}, média "
                                   f"{energia_do_veiculo.mean():.1f} kWh)")

        if motivos:
            sessao.status = "em_revisao"
            sessao.motivo_revisao = "; ".join(motivos)
        else:
            sessao.status = "validada"
    estado.registrar(f"   IA anomalias: modelo treinado com {detector.n_treino} sessões")


# ---------------------------------------------------------------------------
# Etapas 3, 5 e 6 — perfil, previsão, horário e insights
# ---------------------------------------------------------------------------
def meses_de_cadastro(usuarios, meses_ate_agora):
    """{usuario_id: em quantos dos meses processados o usuário já estava cadastrado}."""
    contagem = {}
    for usuario in usuarios:
        mes_do_cadastro = pd.Period(usuario.criado_em, "M")
        contagem[usuario.id] = 0
        for mes in meses_ate_agora:
            if pd.Period(mes) >= mes_do_cadastro:
                contagem[usuario.id] += 1
    return contagem


def etapa_perfis(db, estado, mes, meses_ate_agora):
    """Agrupa os usuários com o K-Means e grava o perfil de cada um."""
    usuarios = db.scalars(select(Usuario)).all()
    historico = sessoes_df(db, estado, ate_mes=mes)
    features = perfis.features_por_usuario(historico, meses_de_cadastro(usuarios, meses_ate_agora))
    resultado, centros = perfis.agrupar(features)
    for usuario in usuarios:
        if usuario.id in resultado.index:
            usuario.perfil = resultado.loc[usuario.id, "perfil"]
        else:
            usuario.perfil = "Sem uso no período"
    return resultado, centros


def etapa_previsao(db, estado, mes, meses_ate_agora, resultado_perfis):
    """Prevê o kWh e o valor da fatura do próximo mês de cada usuário.
    Devolve {usuario_id: dados da previsão}, usado depois nos insights."""
    usuarios = db.scalars(select(Usuario)).all()
    tabela_usuarios = pd.DataFrame([{"id": u.id, "criado_em": u.criado_em} for u in usuarios])
    historico = sessoes_df(db, estado, ate_mes=mes)
    tabela = previsao.tabela_mensal(historico, tabela_usuarios, meses_ate_agora)

    # kwh_cluster: consumo médio do grupo (perfil) de cada usuário.
    # Quem ainda não tem perfil fica com a média geral.
    media_do_perfil = resultado_perfis.groupby("perfil")["kwh_mes"].mean()          # perfil -> média
    media_do_grupo_do_usuario = resultado_perfis["perfil"].map(media_do_perfil)     # usuário -> média
    media_geral = resultado_perfis["kwh_mes"].mean()
    tabela["kwh_cluster"] = tabela["usuario_id"].map(media_do_grupo_do_usuario).fillna(media_geral)

    modelo = previsao.PrevisorConsumo().treinar(tabela)
    linhas_do_mes = tabela[tabela["mes"] == mes]
    kwh_previsto = modelo.prever(linhas_do_mes).set_index("usuario_id")
    proximo_mes = previsao.proximo_mes(mes)

    # Para converter o kWh previsto em reais, supomos que o usuário vai repetir a
    # mesma divisão entre faixas horárias que teve até hoje.
    colunas_das_faixas = ["energia_pico_kwh", "energia_inter_kwh", "energia_fora_kwh"]
    energia_historica = historico.groupby("usuario_id")[colunas_das_faixas].sum()

    previsoes = {}
    for usuario in usuarios:
        if usuario.id not in kwh_previsto.index:
            continue
        kwh = float(kwh_previsto.loc[usuario.id, "kwh_previsto"])
        if usuario.id in energia_historica.index and energia_historica.loc[usuario.id].sum() > 0:
            proporcao = energia_historica.loc[usuario.id] / energia_historica.loc[usuario.id].sum()
            kwh_por_faixa = {"pico": kwh * proporcao["energia_pico_kwh"],
                             "intermediario": kwh * proporcao["energia_inter_kwh"],
                             "fora_pico": kwh * proporcao["energia_fora_kwh"]}
        else:
            kwh_por_faixa = {"intermediario": kwh}  # sem histórico: supõe tudo na faixa do dia

        custos = comparar_modalidades(kwh_por_faixa)  # quanto custaria no mensal e no avulso
        if kwh > 0 or usuario.modalidade == "mensal":
            valor = custos[usuario.modalidade]
        else:
            valor = 0.0  # avulso sem consumo previsto não paga nada
        db.add(PrevisaoConsumo(usuario_id=usuario.id, mes_base=mes, mes_previsto=proximo_mes,
                               kwh_previsto=kwh, valor_previsto=valor,
                               metodo=kwh_previsto.loc[usuario.id, "metodo"]))
        linha_do_usuario = linhas_do_mes[linhas_do_mes["usuario_id"] == usuario.id].iloc[0]
        previsoes[usuario.id] = {"kwh_previsto": kwh, "valor_previsto": valor, "custos": custos,
                                 "kwh_media_hist": float(linha_do_usuario["kwh_media_hist"])}

    metodo = "Ridge" if modelo.treinado else "média do cluster (partida a frio)"
    estado.registrar(f"   IA previsão: {modelo.n_treino} pares mês->mês de treino, método {metodo}")
    return previsoes


def recomendar_modalidade(usuario, previsao_do_usuario):
    """Se a outra modalidade sair pelo menos R$ 5 mais barata no mês previsto,
    devolve a recomendação; senão devolve None."""
    if previsao_do_usuario.get("kwh_previsto", 0) <= 0:
        return None
    outra = "avulso" if usuario.modalidade == "mensal" else "mensal"
    custos = previsao_do_usuario["custos"]
    economia = custos[usuario.modalidade] - custos[outra]
    if economia >= 5:
        return {"atual": usuario.modalidade, "sugerida": outra, "economia": round(economia, 2)}
    return None


def contexto_do_usuario(db, usuario, mes, historico, ocupacao, previsao_do_usuario, media_do_grupo_kwh):
    """Junta os números do usuário no mês que os templates de insight vão usar."""
    historico_do_usuario = historico[historico["usuario_id"] == usuario.id]
    sessoes_do_mes = historico_do_usuario[historico_do_usuario["mes_competencia"] == mes]
    kwh = float(sessoes_do_mes["energia_kwh"].sum())
    kwh_pico = float(sessoes_do_mes["energia_pico_kwh"].sum())
    kwh_fora_pico = float(sessoes_do_mes["energia_fora_kwh"].sum())

    # hora de início sugerida: a menos ocupada da janela noturna
    if historico_do_usuario.empty:
        duracao_media_h = 4
    else:
        duracao_media_h = historico_do_usuario["duracao_minutos"].mean() / 60
    hora_sugerida = horarios.sugerir_janela(ocupacao, min(duracao_media_h, 9))

    retidas = db.scalars(select(Sessao).where(Sessao.usuario_id == usuario.id,
                                              Sessao.mes_competencia == mes,
                                              Sessao.status == "em_revisao")).all()
    tarifa = tarifas_por_faixa()
    diferenca_pico_noturno = tarifa["pico"]["valor_kwh"] - tarifa["fora_pico"]["valor_kwh"]
    return {
        "mes": mes, "proximo_mes": previsao.proximo_mes(mes),
        "modalidade": usuario.modalidade, "perfil": usuario.perfil,
        "kwh_mes": kwh,
        "pct_pico": kwh_pico / kwh if kwh else 0,
        "pct_fora_pico": kwh_fora_pico / kwh if kwh else 0,
        "sessoes_em_revisao": [{"id": s.id, "motivo": s.motivo_revisao} for s in retidas],
        "kwh_previsto": previsao_do_usuario.get("kwh_previsto"),
        "valor_previsto": previsao_do_usuario.get("valor_previsto", 0),
        "kwh_media_hist": previsao_do_usuario.get("kwh_media_hist", 0),
        "economia_horario": horarios.economia_potencial(kwh_pico, float(sessoes_do_mes["ocio_pico_h"].sum())),
        "hora_sugerida": hora_sugerida, "ocupacao_sugerida": float(ocupacao[hora_sugerida]),
        "economia_noturno": round(kwh_fora_pico * diferenca_pico_noturno, 2),
        "media_grupo_kwh": media_do_grupo_kwh,
        "recomendacao_modalidade": recomendar_modalidade(usuario, previsao_do_usuario),
    }


def contexto_do_gestor(db, mes, faturas, previsoes, ocupacao):
    """Junta os números do condomínio no mês para os insights do gestor."""
    sessoes = db.scalars(select(Sessao).where(Sessao.mes_competencia == mes)).all()
    validadas = [s for s in sessoes if s.status == "validada"]
    em_revisao = [s for s in sessoes if s.status == "em_revisao"]
    descartadas = [s for s in sessoes if s.status == "descartada"]
    return {
        "mes": mes, "proximo_mes": previsao.proximo_mes(mes),
        "n_validadas": len(validadas),
        "kwh_total": sum(s.energia_kwh for s in validadas),
        "receita": sum(f.valor_energia + f.valor_ociosidade for f in faturas),
        "receita_fixa": sum(f.valor_fixo for f in faturas),
        "n_revisao": len(em_revisao),
        "kwh_revisao": sum(s.energia_kwh for s in em_revisao),
        "n_descartadas": len(descartadas),
        "kwh_previsto_total": sum(p["kwh_previsto"] for p in previsoes.values()),
        "hora_pico_ocupacao": int(ocupacao.idxmax()), "ocupacao_maxima": float(ocupacao.max()),
    }


def etapa_insights(db, estado, mes, faturas, previsoes):
    """Gera os textos de insight de cada fatura e os do gestor. Devolve quantos
    insights de usuário foram gravados."""
    n_carregadores = len(db.scalars(select(Carregador)).all())
    historico = sessoes_df(db, estado, ate_mes=mes)
    ocupacao = horarios.ocupacao_por_hora(historico, n_carregadores)

    # kWh de cada perfil no mês (só de quem usou), para comparar o usuário com o seu grupo
    sessoes_do_mes = historico[historico["mes_competencia"] == mes]
    kwh_por_usuario = sessoes_do_mes.groupby("usuario_id")["energia_kwh"].sum()
    perfil_do_usuario = {u.id: u.perfil for u in db.scalars(select(Usuario))}
    kwh_do_perfil = {}  # perfil -> lista com o kWh de cada usuário do perfil
    for usuario_id, kwh in kwh_por_usuario.items():
        kwh_do_perfil.setdefault(perfil_do_usuario[usuario_id], []).append(kwh)

    total_de_insights = 0
    for fatura in faturas:
        usuario = db.get(Usuario, fatura.usuario_id)
        media_do_grupo_kwh = float(pd.Series(kwh_do_perfil.get(usuario.perfil, [0])).mean())
        contexto = contexto_do_usuario(db, usuario, mes, historico, ocupacao,
                                       previsoes.get(usuario.id, {}), media_do_grupo_kwh)
        for insight in insights.insights_usuario(contexto):
            db.add(InsightIA(usuario_id=usuario.id, fatura_id=fatura.id, tipo=insight["tipo"],
                             mensagem=insight["mensagem"], valor_referencia=insight["valor"],
                             periodo_referencia=mes))
            total_de_insights += 1

    # visão do gestor: insights sem usuário e sem fatura
    for insight in insights.insights_gestor(contexto_do_gestor(db, mes, faturas, previsoes, ocupacao)):
        db.add(InsightIA(usuario_id=None, fatura_id=None, tipo=insight["tipo"],
                         mensagem=insight["mensagem"], valor_referencia=insight["valor"],
                         periodo_referencia=mes))
    return total_de_insights


# ---------------------------------------------------------------------------
# Ciclo completo
# ---------------------------------------------------------------------------
def contar_por_status(sessoes, status):
    return len([s for s in sessoes if s.status == status])


def executar_mes(db, estado, mes, registros, meses_ate_agora):
    """Roda as 7 etapas para as sessões encerradas em um mês."""
    estado.registrar(f"\n=== Ciclo {mes} ===")

    # 7 (do ciclo anterior): fecha as faturas dos meses passados
    for fatura in db.scalars(select(Fatura).where(Fatura.status == "aberta", Fatura.referencia_mes < mes)):
        fatura.status = "fechada"

    novas = [ingerir(registro, db) for registro in registros]
    db.flush()
    estado.registrar(f"1. Ingestão: {len(novas)} sessões recebidas, "
                     f"{contar_por_status(novas, 'erro')} rejeitada(s) na validação")

    etapa_anomalias(db, estado, novas, mes)
    estado.registrar(f"2. IA anomalias: {contar_por_status(novas, 'validada')} validadas, "
                     f"{contar_por_status(novas, 'em_revisao')} em revisão, "
                     f"{contar_por_status(novas, 'descartada')} descartadas")

    resultado_perfis, centros = etapa_perfis(db, estado, mes, meses_ate_agora)
    estado.registrar(f"3. IA perfis: {len(centros)} grupos -> " + ", ".join(centros["perfil"]))

    faturas = gerar_faturas_do_mes(db, mes)
    estado.registrar(f"4. Rateio: {len(faturas)} faturas, total R$ "
                     f"{sum(f.valor_final for f in faturas):.2f}")

    previsoes = etapa_previsao(db, estado, mes, meses_ate_agora, resultado_perfis)
    estado.registrar(f"5. IA previsão: {len(previsoes)} usuários com projeção para "
                     f"{previsao.proximo_mes(mes)}")

    total_de_insights = etapa_insights(db, estado, mes, faturas, previsoes)
    estado.registrar(f"6. IA insights: {total_de_insights} insights anexados às faturas")
    db.commit()


def executar_tudo(db, registros):
    """Separa os registros por mês de encerramento e roda um ciclo para cada mês,
    do mais antigo para o mais recente. Devolve o estado (com o log)."""
    registros_por_mes = {}
    for registro in registros:
        mes = registro["fim"].strftime("%Y-%m")
        registros_por_mes.setdefault(mes, []).append(registro)

    estado = EstadoPipeline()
    meses = sorted(registros_por_mes)
    for posicao, mes in enumerate(meses):
        meses_ate_agora = meses[: posicao + 1]
        executar_mes(db, estado, mes, registros_por_mes[mes], meses_ate_agora)
    return estado
