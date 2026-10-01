"""
Cadastro do cenário: condomínio, carregadores, tarifas, usuários e veículos.

- O carregador 57000HPA247L0002 é o equipamento real do Energy Innovation Lab;
  as sessões dele vêm do Charging Record (dados reais) e pertencem ao usuário
  "Energy Innovation Lab".
- Os carregadores 2 a 4 e os moradores/visitantes são simulados, para termos
  vários usuários dividindo a infraestrutura (o Charging Record tem um único cartão).
"""
from datetime import datetime

from src import config
from src.db.modelos import Carregador, Condominio, Tarifa, Usuario, Veiculo

CONDOMINIO = dict(id=1, nome="Edifício Solar Park (cenário EV ChargeOps)",
                  endereco="Rua Aclimação, 422 - Aclimação", cidade="São Paulo", uf="SP",
                  codigo_ibge=3550308, cnpj="12.345.678/0001-90")

CARREGADORES = [
    dict(id=1, serial_number="57000HPA247L0002", modelo="GW7K-HCA-20", potencia_maxima_kw=7.0,
         protocolo_comunicacao="Modbus TCP", real=True),
    dict(id=2, serial_number="SIM-HCA-0002", modelo="GW7K-HCA-20", potencia_maxima_kw=7.0,
         protocolo_comunicacao="Modbus TCP", real=False),
    dict(id=3, serial_number="SIM-HCA-0003", modelo="GW7K-HCA-20", potencia_maxima_kw=7.0,
         protocolo_comunicacao="Modbus TCP", real=False),
    dict(id=4, serial_number="SIM-HCA-0004", modelo="GW7K-HCA-20", potencia_maxima_kw=7.0,
         protocolo_comunicacao="Modbus TCP", real=False),
]

# perfil_simulacao descreve o COMPORTAMENTO usado para gerar os dados. A IA não
# lê esse campo: ela descobre o perfil sozinha pelo clustering.
USUARIOS = [
    dict(id=1, nome="Energy Innovation Lab (dados reais)", email="lab@fiap.com.br",
         apartamento="Lab L1", modalidade="mensal", criado_em=datetime(2026, 1, 20)),
    dict(id=2, nome="Maria Oliveira", email="maria.oliveira@email.com", apartamento="Apto 202",
         modalidade="mensal", criado_em=datetime(2026, 2, 10)),
    dict(id=3, nome="Carlos Oliveira", email="carlos.oliveira@email.com", apartamento="Apto 202",
         modalidade="mensal", criado_em=datetime(2026, 3, 5)),
    dict(id=4, nome="Ana Souza", email="ana.souza@email.com", apartamento="Apto 305",
         modalidade="mensal", criado_em=datetime(2026, 2, 1)),
    dict(id=5, nome="Rafael Lima", email="rafael.lima@email.com", apartamento="Apto 401",
         modalidade="mensal", criado_em=datetime(2026, 3, 12)),
    dict(id=6, nome="Beatriz Costa", email="beatriz.costa@email.com", apartamento="Apto 502",
         modalidade="mensal", criado_em=datetime(2026, 2, 20)),
    dict(id=7, nome="Fernando Rocha", email="fernando.rocha@email.com", apartamento="Apto 603",
         modalidade="mensal", criado_em=datetime(2026, 1, 30)),
    dict(id=8, nome="Paulo Teixeira", email="paulo.teixeira@email.com", apartamento="Apto 104",
         modalidade="mensal", criado_em=datetime(2026, 8, 1)),
    dict(id=9, nome="Lucas Mendes (visitante)", email="lucas.mendes@email.com", apartamento=None,
         modalidade="avulso", criado_em=datetime(2026, 4, 2)),
    dict(id=10, nome="Juliana Prado (visitante)", email="juliana.prado@email.com", apartamento=None,
         modalidade="avulso", criado_em=datetime(2026, 4, 15)),
]

VEICULOS = [
    # o veículo do laboratório não é identificado no Charging Record; a potência
    # de 3,5 kW é a máxima registrada para esse carregador na API SEMS+ (Sprint 01)
    dict(id=1, usuario_id=1, marca="N/D", modelo="Veículo de testes do laboratório", ano=2025,
         placa="LAB0001", capacidade_bateria_kwh=38.0, potencia_obc_kw=3.5),
    dict(id=2, usuario_id=2, marca="GWM", modelo="ORA 03", ano=2025, placa="XYZ4E56",
         capacidade_bateria_kwh=48.0, potencia_obc_kw=6.6),
    dict(id=3, usuario_id=3, marca="Volvo", modelo="EX30", ano=2026, placa="QWE7F89",
         capacidade_bateria_kwh=51.0, potencia_obc_kw=11.0),
    dict(id=4, usuario_id=4, marca="BYD", modelo="Dolphin Mini", ano=2025, placa="ABC1D23",
         capacidade_bateria_kwh=38.0, potencia_obc_kw=6.6),
    dict(id=5, usuario_id=4, marca="BYD", modelo="Seal", ano=2025, placa="SEA2L45",
         capacidade_bateria_kwh=82.5, potencia_obc_kw=11.0),
    dict(id=6, usuario_id=5, marca="Renault", modelo="Kwid E-Tech", ano=2024, placa="KWD3E21",
         capacidade_bateria_kwh=26.8, potencia_obc_kw=7.0),
    dict(id=7, usuario_id=6, marca="BYD", modelo="Dolphin", ano=2025, placa="DLP5H67",
         capacidade_bateria_kwh=44.9, potencia_obc_kw=6.6),
    dict(id=8, usuario_id=7, marca="Volvo", modelo="EX30", ano=2025, placa="FRN6R88",
         capacidade_bateria_kwh=51.0, potencia_obc_kw=11.0),
    dict(id=9, usuario_id=8, marca="GWM", modelo="ORA 03", ano=2026, placa="PTX8T90",
         capacidade_bateria_kwh=48.0, potencia_obc_kw=6.6),
    dict(id=10, usuario_id=9, marca="BYD", modelo="Dolphin Mini", ano=2025, placa="LCM9M12",
         capacidade_bateria_kwh=38.0, potencia_obc_kw=6.6),
    dict(id=11, usuario_id=10, marca="BYD", modelo="Dolphin", ano=2024, placa="JLP1P34",
         capacidade_bateria_kwh=44.9, potencia_obc_kw=6.6),
]


def popular_cadastro(db):
    """Insere o cenário no banco (idempotente: só insere se estiver vazio)."""
    if db.get(Condominio, 1):
        return
    db.add(Condominio(**CONDOMINIO))
    db.add_all(Carregador(condominio_id=1, **c) for c in CARREGADORES)
    db.add_all(Tarifa(condominio_id=1, nome=t["nome"], valor_kwh=t["valor_kwh"],
                      taxa_ocupacao_hora=t["taxa_ocupacao_hora"], tipo_horario=t["tipo_horario"],
                      horario_inicio=t["inicio"], horario_fim=t["fim"])
               for t in config.TARIFAS)
    db.add_all(Usuario(condominio_id=1, **u) for u in USUARIOS)
    db.add_all(Veiculo(**v) for v in VEICULOS)
    db.commit()
