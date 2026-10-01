"""
Modelo de dados do EV ChargeOps (segue o diagrama ER da Sprint 01).

Campos acrescentados em relação à Sprint 01, necessários para a IA e o rateio:
  USUARIO.modalidade        -> "mensal" (Modalidade A) ou "avulso" (Modalidade B)
  USUARIO.perfil            -> rótulo atribuído pelo clustering
  SESSAO.origem             -> "real" (Charging Record) ou "simulada"
  SESSAO.score_anomalia     -> score do Isolation Forest
  SESSAO.motivo_revisao     -> por que a IA segurou ou descartou a sessão
  SESSAO.ociosidade_min     -> minutos plugado sem carregar (calculado da telemetria)
  SESSAO.mes_competencia    -> mês em que a sessão é faturada (pelo horário de fim)
  ITEM_FATURA.tipo_item     -> "energia" ou "ociosidade"
  FATURA.modalidade / valor_fixo / valor_ociosidade / pre_autorizado / estorno
O MÉTODO_PAGAMENTO foi omitido no protótipo porque não há gateway de pagamento.
"""
from datetime import datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer,
                        String, Text, Time)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Condominio(Base):
    __tablename__ = "condominio"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(200))
    endereco: Mapped[str] = mapped_column(String(300))
    cidade: Mapped[str] = mapped_column(String(100))
    uf: Mapped[str] = mapped_column(String(2))
    codigo_ibge: Mapped[int] = mapped_column(Integer)
    cnpj: Mapped[str] = mapped_column(String(18))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Usuario(Base):
    __tablename__ = "usuario"
    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominio.id"))
    nome: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    apartamento: Mapped[str | None] = mapped_column(String(20), nullable=True)
    modalidade: Mapped[str] = mapped_column(String(10))  # mensal | avulso
    perfil: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime)

    veiculos = relationship("Veiculo", back_populates="usuario")


class Veiculo(Base):
    __tablename__ = "veiculo"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    marca: Mapped[str] = mapped_column(String(50))
    modelo: Mapped[str] = mapped_column(String(100))
    ano: Mapped[int] = mapped_column(Integer)
    placa: Mapped[str] = mapped_column(String(10))
    capacidade_bateria_kwh: Mapped[float] = mapped_column(Float)
    potencia_obc_kw: Mapped[float] = mapped_column(Float)  # carregador de bordo (limita a potência AC)

    usuario = relationship("Usuario", back_populates="veiculos")


class Carregador(Base):
    __tablename__ = "carregador"
    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominio.id"))
    serial_number: Mapped[str] = mapped_column(String(50), unique=True)
    modelo: Mapped[str] = mapped_column(String(50))
    potencia_maxima_kw: Mapped[float] = mapped_column(Float)
    protocolo_comunicacao: Mapped[str] = mapped_column(String(30))
    real: Mapped[bool] = mapped_column(Boolean, default=False)


class Tarifa(Base):
    __tablename__ = "tarifa"
    id: Mapped[int] = mapped_column(primary_key=True)
    condominio_id: Mapped[int] = mapped_column(ForeignKey("condominio.id"))
    nome: Mapped[str] = mapped_column(String(100))
    valor_kwh: Mapped[float] = mapped_column(Float)
    taxa_ocupacao_hora: Mapped[float] = mapped_column(Float)
    tipo_horario: Mapped[str] = mapped_column(String(20))
    horario_inicio = mapped_column(Time)
    horario_fim = mapped_column(Time)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)


class Sessao(Base):
    __tablename__ = "sessao"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    veiculo_id: Mapped[int] = mapped_column(ForeignKey("veiculo.id"))
    carregador_id: Mapped[int] = mapped_column(ForeignKey("carregador.id"))
    inicio: Mapped[datetime] = mapped_column(DateTime)
    fim: Mapped[datetime] = mapped_column(DateTime)
    energia_kwh: Mapped[float] = mapped_column(Float)
    duracao_minutos: Mapped[int] = mapped_column(Integer)
    potencia_media_kw: Mapped[float] = mapped_column(Float)
    potencia_maxima_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    ociosidade_min: Mapped[int] = mapped_column(Integer, default=0)
    autonomia_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    # registrada -> (IA) -> validada | em_revisao | descartada ; erro = falhou na validação
    # interrompida é tratada como validada para cobrança, mas fica sinalizada em encerramento
    status: Mapped[str] = mapped_column(String(20), default="registrada")
    encerramento: Mapped[str] = mapped_column(String(20), default="normal")  # normal | interrompida
    origem: Mapped[str] = mapped_column(String(10))
    mes_competencia: Mapped[str] = mapped_column(String(7))
    score_anomalia: Mapped[float | None] = mapped_column(Float, nullable=True)
    motivo_revisao: Mapped[str | None] = mapped_column(Text, nullable=True)
    faturada: Mapped[bool] = mapped_column(Boolean, default=False)

    telemetria = relationship("Telemetria", back_populates="sessao",
                              order_by="Telemetria.timestamp")


class Telemetria(Base):
    __tablename__ = "telemetria"
    id: Mapped[int] = mapped_column(primary_key=True)
    sessao_id: Mapped[int] = mapped_column(ForeignKey("sessao.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    potencia_instantanea_kw: Mapped[float] = mapped_column(Float)
    energia_acumulada_kwh: Mapped[float] = mapped_column(Float)
    work_state: Mapped[str] = mapped_column(String(30))
    estimada: Mapped[bool] = mapped_column(Boolean, default=False)

    sessao = relationship("Sessao", back_populates="telemetria")


class Fatura(Base):
    __tablename__ = "fatura"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    referencia_mes: Mapped[str] = mapped_column(String(7))
    modalidade: Mapped[str] = mapped_column(String(10))
    total_kwh: Mapped[float] = mapped_column(Float, default=0)
    valor_energia: Mapped[float] = mapped_column(Float, default=0)
    valor_ociosidade: Mapped[float] = mapped_column(Float, default=0)
    valor_fixo: Mapped[float] = mapped_column(Float, default=0)
    valor_final: Mapped[float] = mapped_column(Float, default=0)
    pre_autorizado: Mapped[float] = mapped_column(Float, default=0)  # só avulso
    estorno: Mapped[float] = mapped_column(Float, default=0)          # só avulso
    sessoes_em_revisao: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(15), default="aberta")  # aberta | fechada
    vencimento = mapped_column(Date)

    itens = relationship("ItemFatura", back_populates="fatura")


class ItemFatura(Base):
    __tablename__ = "item_fatura"
    id: Mapped[int] = mapped_column(primary_key=True)
    fatura_id: Mapped[int] = mapped_column(ForeignKey("fatura.id"))
    sessao_id: Mapped[int] = mapped_column(ForeignKey("sessao.id"))
    tarifa_id: Mapped[int] = mapped_column(ForeignKey("tarifa.id"))
    tipo_item: Mapped[str] = mapped_column(String(12))  # energia | ociosidade
    tipo_horario_aplicado: Mapped[str] = mapped_column(String(20))
    energia_kwh: Mapped[float] = mapped_column(Float, default=0)
    horas_ociosidade: Mapped[float] = mapped_column(Float, default=0)
    valor_unitario: Mapped[float] = mapped_column(Float)
    valor_total_item: Mapped[float] = mapped_column(Float)
    ajuste_mes_anterior: Mapped[bool] = mapped_column(Boolean, default=False)

    fatura = relationship("Fatura", back_populates="itens")


class InsightIA(Base):
    __tablename__ = "insight_ia"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    fatura_id: Mapped[int | None] = mapped_column(ForeignKey("fatura.id"), nullable=True)
    tipo: Mapped[str] = mapped_column(String(20))
    mensagem: Mapped[str] = mapped_column(Text)
    valor_referencia: Mapped[float | None] = mapped_column(Float, nullable=True)
    periodo_referencia: Mapped[str] = mapped_column(String(20))
    gerado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PrevisaoConsumo(Base):
    """Saída do modelo de previsão, guardada para o rateio/insights e para auditoria."""
    __tablename__ = "previsao_consumo"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    mes_base: Mapped[str] = mapped_column(String(7))
    mes_previsto: Mapped[str] = mapped_column(String(7))
    kwh_previsto: Mapped[float] = mapped_column(Float)
    valor_previsto: Mapped[float] = mapped_column(Float)
    metodo: Mapped[str] = mapped_column(String(30))
