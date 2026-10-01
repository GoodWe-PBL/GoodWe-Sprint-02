"""
Etapa 4 do fluxo da Sprint 01 — Ingestão e normalização.

Recebe o registro bruto do carregador (SN, duração, kWh, potência, leituras de
telemetria) já vinculado ao usuário autenticado no app, valida, converte e grava
como SESSAO + TELEMETRIA com status "registrada". Daqui a sessão segue para a IA
(detecção de anomalias), que decide se ela pode ou não ser faturada.

Os nomes dos campos do registro (chargePileSN, chargeTimeLength,
currentChargeQuantity, maxCharP) são os da API SEMS+ do carregador.
"""
from sqlalchemy import select

from src import config
from src.db.modelos import Carregador, Sessao, Telemetria, Usuario, Veiculo
from src.rateio.tarifas import minutos_ociosos

KM_POR_KWH = 5.0  # mesma razão do exemplo da API SEMS+ (14,6 kWh -> 73 km)


def buscar_carregador(db, numero_de_serie):
    return db.scalar(select(Carregador).where(Carregador.serial_number == numero_de_serie))


def validar(registro, db):
    """Checagens de integridade. Devolve a lista de problemas (vazia = ok)."""
    problemas = []
    inicio, fim = registro["inicio"], registro["fim"]
    if fim < inicio:
        problemas.append("fim anterior ao início")
    else:
        duracao_real = (fim - inicio).total_seconds() / 60
        duracao_informada = registro["chargeTimeLength"]
        if abs(duracao_real - duracao_informada) > config.TOLERANCIA_DURACAO_MIN:
            problemas.append(f"duração informada ({duracao_informada} min) não bate "
                             f"com fim-início ({duracao_real:.0f} min)")
    if registro["currentChargeQuantity"] < 0:
        problemas.append("energia negativa")

    usuario = db.get(Usuario, registro["usuario_id"])
    veiculo = db.get(Veiculo, registro["veiculo_id"])
    if usuario is None or not usuario.ativo:
        problemas.append("usuário inexistente ou inativo")
    if veiculo is None or veiculo.usuario_id != registro["usuario_id"]:
        problemas.append("veículo não pertence ao usuário")
    if buscar_carregador(db, registro["chargePileSN"]) is None:
        problemas.append(f"carregador {registro['chargePileSN']} não cadastrado")
    return problemas


def ingerir(registro, db):
    """Valida, normaliza e grava uma sessão. Registros inválidos também são
    gravados (status "erro") para ficarem auditáveis, mas nunca são cobrados."""
    problemas = validar(registro, db)
    carregador = buscar_carregador(db, registro["chargePileSN"])
    energia = max(0.0, float(registro["currentChargeQuantity"]))
    duracao_min = int(registro["chargeTimeLength"])
    leituras = registro.get("leituras") or []

    if duracao_min > 0:
        potencia_media = round(energia / (duracao_min / 60), 3)
    else:
        potencia_media = 0.0

    sessao = Sessao(
        usuario_id=registro["usuario_id"],
        veiculo_id=registro["veiculo_id"],
        carregador_id=carregador.id if carregador else 0,
        inicio=registro["inicio"], fim=registro["fim"],
        energia_kwh=round(energia, 3),
        duracao_minutos=duracao_min,
        potencia_media_kw=potencia_media,
        potencia_maxima_kw=registro.get("maxCharP"),
        ociosidade_min=minutos_ociosos(leituras) if leituras else 0,
        autonomia_km=round(energia * KM_POR_KWH, 1),
        encerramento=registro.get("encerramento", "normal"),
        origem=registro["origem"],
        mes_competencia=registro["fim"].strftime("%Y-%m"),  # fatura pelo mês de encerramento
        status="erro" if problemas else "registrada",
        motivo_revisao="; ".join(problemas) if problemas else None,
    )
    db.add(sessao)
    db.flush()  # gera o id da sessão, usado na telemetria

    if not problemas:
        for leitura in leituras:
            db.add(Telemetria(sessao_id=sessao.id, timestamp=leitura["timestamp"],
                              potencia_instantanea_kw=leitura["potencia_kw"],
                              energia_acumulada_kwh=leitura["energia_kwh"],
                              work_state=leitura["work_state"],
                              estimada=registro.get("telemetria_estimada", False)))
    return sessao


def leituras_da_sessao(sessao):
    """Converte a telemetria gravada para o formato usado pelo rateio."""
    leituras = []
    for telemetria in sessao.telemetria:
        leituras.append({"timestamp": telemetria.timestamp,
                         "potencia_kw": telemetria.potencia_instantanea_kw,
                         "energia_kwh": telemetria.energia_acumulada_kwh})
    return leituras
