"""
EV ChargeOps — protótipo (Sprint 02)

Comandos:
  python main.py executar                         roda o fluxo completo (recria o banco)
  python main.py pendencias                       sessões retidas pela IA aguardando o gestor
  python main.py revisar <sessao_id> --aprovar    gestor aprova (entra na fatura aberta)
  python main.py revisar <sessao_id> --rejeitar   gestor rejeita (nunca é cobrada)
  python main.py fatura <usuario_id> [--mes AAAA-MM]
  python main.py gestor [--mes AAAA-MM]           visão do gestor
  python main.py usuarios                         lista usuários e perfis
"""
import argparse
import sys

from sqlalchemy import select

from src import config
from src.db.conexao import criar_engine, criar_sessao, fechar_sessao
from src.db.modelos import Fatura, InsightIA, ItemFatura, Sessao, Usuario


def abrir_banco(recriar=False):
    """Devolve uma sessão do banco. Se o banco ainda não existe, avisa e encerra."""
    if not recriar and not config.CAMINHO_BANCO.exists():
        sys.exit("Banco não encontrado. Rode primeiro: python main.py executar")
    return criar_sessao(criar_engine(recriar=recriar))


def reais(valor):
    """1234.5 -> 'R$  1.234,50' (alinhado à direita em 9 posições)."""
    return f"R$ {valor:>9,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def cmd_executar(_):
    # imports aqui dentro: só este comando precisa carregar o pipeline e a IA
    from src.pipeline import executar_tudo
    from src.relatorios import exportar_csvs, gerar_graficos, resumo_execucao
    from src.simulacao.cadastro import popular_cadastro
    from src.simulacao.gerador import carregar_registros_reais, gerar_registros_simulados

    db = abrir_banco(recriar=True)
    popular_cadastro(db)
    registros_reais = carregar_registros_reais()
    registros_simulados = gerar_registros_simulados()
    print(f"Registros: {len(registros_reais)} reais (Charging Record) + "
          f"{len(registros_simulados)} simulados")
    estado = executar_tudo(db, registros_reais + registros_simulados)
    exportar_csvs(db)
    gerar_graficos(db, estado)
    texto = resumo_execucao(db, estado)
    (config.PASTA_SAIDA / "relatorio_execucao.txt").write_text(texto, encoding="utf-8")
    print(f"\nSaídas em {config.PASTA_SAIDA}: banco SQLite, CSVs, gráficos PNG e relatorio_execucao.txt")
    fechar_sessao(db)


def cmd_pendencias(_):
    db = abrir_banco()
    pendentes = db.scalars(select(Sessao).where(Sessao.status == "em_revisao").order_by(Sessao.id)).all()
    if not pendentes:
        print("Nenhuma sessão aguardando revisão.")
    else:
        print(f"{len(pendentes)} sessão(ões) retida(s) pela IA:\n")
    for sessao in pendentes:
        usuario = db.get(Usuario, sessao.usuario_id)
        print(f"  #{sessao.id:<4} {usuario.nome:<36} {sessao.inicio:%d/%m %H:%M}  "
              f"{sessao.energia_kwh:6.1f} kWh  {sessao.duracao_minutos / 60:5.1f} h\n"
              f"        motivo: {sessao.motivo_revisao}")
    fechar_sessao(db)


def cmd_revisar(args):
    from src.rateio.servico import revisar_sessao

    db = abrir_banco()
    # valor de cada fatura aberta antes da decisão, para mostrar o "antes -> depois"
    valor_antes = {}
    for fatura in db.scalars(select(Fatura).where(Fatura.status == "aberta")):
        valor_antes[fatura.id] = fatura.valor_final

    sessao = revisar_sessao(db, args.sessao_id, aprovar=args.aprovar, observacao=args.obs or "")
    print(f"Sessão #{sessao.id} -> {sessao.status}")
    if args.aprovar:
        fatura = db.scalar(select(Fatura).where(Fatura.usuario_id == sessao.usuario_id,
                                                Fatura.status == "aberta"))
        antes = valor_antes.get(fatura.id, 0)
        print(f"Fatura {fatura.referencia_mes} do usuário {sessao.usuario_id}: "
              f"{reais(antes).strip()} -> {reais(fatura.valor_final).strip()}")
    fechar_sessao(db)


def cmd_fatura(args):
    db = abrir_banco()
    usuario = db.get(Usuario, args.usuario_id)
    if usuario is None:
        sys.exit("Usuário não encontrado.")

    # com --mes: a fatura daquele mês; sem --mes: a mais recente
    consulta = select(Fatura).where(Fatura.usuario_id == usuario.id)
    if args.mes:
        consulta = consulta.where(Fatura.referencia_mes == args.mes)
    else:
        consulta = consulta.order_by(Fatura.referencia_mes.desc())
    fatura = db.scalars(consulta).first()
    if fatura is None:
        sys.exit("Fatura não encontrada para esse mês.")

    modalidade = "A - plano mensal" if fatura.modalidade == "mensal" else "B - carga avulsa"
    print(f"\nFATURA {fatura.referencia_mes} — {usuario.nome} ({usuario.apartamento or 'sem unidade'})")
    print(f"Modalidade: {modalidade} | Perfil (IA): {usuario.perfil} | Status: {fatura.status} | "
          f"Vencimento: {fatura.vencimento:%d/%m/%Y}")
    print("-" * 86)

    itens = db.scalars(select(ItemFatura).where(ItemFatura.fatura_id == fatura.id)
                       .order_by(ItemFatura.sessao_id, ItemFatura.tipo_item)).all()
    for item in itens:
        sessao = db.get(Sessao, item.sessao_id)
        if item.tipo_item == "energia":
            quantidade = f"{item.energia_kwh:6.2f} kWh"
        else:
            quantidade = f"{item.horas_ociosidade:6.2f} h  "
        ajuste = " (ajuste mês anterior)" if item.ajuste_mes_anterior else ""
        print(f"  #{sessao.id:<4} {sessao.inicio:%d/%m %H:%M}  {item.tipo_item:<10} "
              f"{item.tipo_horario_aplicado:<13} {quantidade} x {item.valor_unitario:.2f} = "
              f"{reais(item.valor_total_item)}{ajuste}")
    print("-" * 86)

    linhas_de_total = [(f"Energia ({fatura.total_kwh:.1f} kWh)", fatura.valor_energia),
                       ("Ociosidade (P)", fatura.valor_ociosidade)]
    if fatura.modalidade == "mensal":
        linhas_de_total.append(("Contribuição fixa (C)", fatura.valor_fixo))
    linhas_de_total.append(("TOTAL", fatura.valor_final))
    for rotulo, valor in linhas_de_total:
        print(f"  {rotulo:<70}{reais(valor)}")
    if fatura.modalidade == "avulso":
        print(f"  Pré-autorizado: {reais(fatura.pre_autorizado).strip()} | "
              f"estornado: {reais(fatura.estorno).strip()}")
    if fatura.sessoes_em_revisao:
        print(f"  {fatura.sessoes_em_revisao} sessão(ões) do mês retida(s) pela IA, fora desta cobrança")

    print("\nInsights da IA:")
    for insight in db.scalars(select(InsightIA).where(InsightIA.fatura_id == fatura.id)):
        print(f"  [{insight.tipo}] {insight.mensagem}")
    fechar_sessao(db)


def cmd_gestor(args):
    db = abrir_banco()
    # sem --mes: usa o mês mais recente que tem fatura
    mes = args.mes or db.scalar(select(Fatura.referencia_mes).order_by(Fatura.referencia_mes.desc()))
    print(f"\nVISÃO DO GESTOR — {mes}")
    # insight sem usuário (usuario_id nulo) é o que a IA escreveu para o gestor
    insights_do_gestor = db.scalars(select(InsightIA).where(InsightIA.usuario_id.is_(None),
                                                            InsightIA.periodo_referencia == mes))
    for insight in insights_do_gestor:
        print(f"  [{insight.tipo}] {insight.mensagem}")
    print()
    for fatura in db.scalars(select(Fatura).where(Fatura.referencia_mes == mes)):
        usuario = db.get(Usuario, fatura.usuario_id)
        em_revisao = f"  ({fatura.sessoes_em_revisao} em revisão)" if fatura.sessoes_em_revisao else ""
        print(f"  {usuario.id:>2} {usuario.nome:<36} {fatura.modalidade:<7} {fatura.total_kwh:7.1f} kWh "
              f"{reais(fatura.valor_final)}{em_revisao}")
    fechar_sessao(db)


def cmd_usuarios(_):
    db = abrir_banco()
    for usuario in db.scalars(select(Usuario)):
        print(f"  {usuario.id:>2} {usuario.nome:<36} {usuario.modalidade:<7} perfil: {usuario.perfil}")
    fechar_sessao(db)


def main():
    leitor = argparse.ArgumentParser(description="EV ChargeOps — protótipo Sprint 02")
    comandos = leitor.add_subparsers(dest="cmd")
    comandos.add_parser("executar")
    comandos.add_parser("pendencias")

    revisar = comandos.add_parser("revisar")
    revisar.add_argument("sessao_id", type=int)
    decisao = revisar.add_mutually_exclusive_group(required=True)  # exige um dos dois, nunca ambos
    decisao.add_argument("--aprovar", action="store_true")
    decisao.add_argument("--rejeitar", action="store_true")
    revisar.add_argument("--obs")

    fatura = comandos.add_parser("fatura")
    fatura.add_argument("usuario_id", type=int)
    fatura.add_argument("--mes")

    gestor = comandos.add_parser("gestor")
    gestor.add_argument("--mes")
    comandos.add_parser("usuarios")

    args = leitor.parse_args()
    funcoes = {"executar": cmd_executar, "pendencias": cmd_pendencias, "revisar": cmd_revisar,
               "fatura": cmd_fatura, "gestor": cmd_gestor, "usuarios": cmd_usuarios}
    funcao = funcoes[args.cmd or "executar"]  # sem comando nenhum, roda o fluxo completo
    funcao(args)


if __name__ == "__main__":
    main()
