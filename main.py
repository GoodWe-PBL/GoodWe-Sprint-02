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
from src.db.conexao import criar_engine, criar_sessao
from src.db.modelos import Fatura, InsightIA, ItemFatura, Sessao, Usuario


def _db(recriar=False):
    if not recriar and not config.CAMINHO_BANCO.exists():
        sys.exit("Banco não encontrado. Rode primeiro: python main.py executar")
    return criar_sessao(criar_engine(recriar=recriar))


def _r(v):
    return f"R$ {v:>9,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def cmd_executar(_):
    from src.pipeline import executar_tudo
    from src.relatorios import exportar_csvs, gerar_graficos, resumo_execucao
    from src.simulacao.cadastro import popular_cadastro
    from src.simulacao.gerador import carregar_registros_reais, gerar_registros_simulados

    db = _db(recriar=True)
    popular_cadastro(db)
    reais = carregar_registros_reais()
    simulados = gerar_registros_simulados()
    print(f"Registros: {len(reais)} reais (Charging Record) + {len(simulados)} simulados")
    estado = executar_tudo(db, reais + simulados)
    exportar_csvs(db)
    gerar_graficos(db, estado)
    texto = resumo_execucao(db, estado)
    (config.PASTA_SAIDA / "relatorio_execucao.txt").write_text(texto, encoding="utf-8")
    print(f"\nSaídas em {config.PASTA_SAIDA}: banco SQLite, CSVs, gráficos PNG e relatorio_execucao.txt")


def cmd_pendencias(_):
    db = _db()
    pend = db.scalars(select(Sessao).where(Sessao.status == "em_revisao").order_by(Sessao.id)).all()
    if not pend:
        print("Nenhuma sessão aguardando revisão.")
        return
    print(f"{len(pend)} sessão(ões) retida(s) pela IA:\n")
    for s in pend:
        u = db.get(Usuario, s.usuario_id)
        print(f"  #{s.id:<4} {u.nome:<36} {s.inicio:%d/%m %H:%M}  {s.energia_kwh:6.1f} kWh  "
              f"{s.duracao_minutos / 60:5.1f} h\n        motivo: {s.motivo_revisao}")


def cmd_revisar(args):
    from src.rateio.servico import revisar_sessao
    db = _db()
    antes = {f.id: f.valor_final for f in db.scalars(select(Fatura).where(Fatura.status == "aberta"))}
    s = revisar_sessao(db, args.sessao_id, aprovar=args.aprovar, observacao=args.obs or "")
    print(f"Sessão #{s.id} -> {s.status}")
    if args.aprovar:
        f = db.scalar(select(Fatura).where(Fatura.usuario_id == s.usuario_id, Fatura.status == "aberta"))
        print(f"Fatura {f.referencia_mes} do usuário {s.usuario_id}: "
              f"{_r(antes.get(f.id, 0)).strip()} -> {_r(f.valor_final).strip()}")


def cmd_fatura(args):
    db = _db()
    u = db.get(Usuario, args.usuario_id)
    if u is None:
        sys.exit("Usuário não encontrado.")
    q = select(Fatura).where(Fatura.usuario_id == u.id)
    q = q.where(Fatura.referencia_mes == args.mes) if args.mes else q.order_by(Fatura.referencia_mes.desc())
    f = db.scalars(q).first()
    if f is None:
        sys.exit("Fatura não encontrada para esse mês.")
    print(f"\nFATURA {f.referencia_mes} — {u.nome} ({u.apartamento or 'sem unidade'})")
    print(f"Modalidade: {'A - plano mensal' if f.modalidade == 'mensal' else 'B - carga avulsa'} | "
          f"Perfil (IA): {u.perfil} | Status: {f.status} | Vencimento: {f.vencimento:%d/%m/%Y}")
    print("-" * 86)
    itens = db.scalars(select(ItemFatura).where(ItemFatura.fatura_id == f.id)
                       .order_by(ItemFatura.sessao_id, ItemFatura.tipo_item)).all()
    for i in itens:
        s = db.get(Sessao, i.sessao_id)
        qtd = f"{i.energia_kwh:6.2f} kWh" if i.tipo_item == "energia" else f"{i.horas_ociosidade:6.2f} h  "
        aj = " (ajuste mês anterior)" if i.ajuste_mes_anterior else ""
        print(f"  #{s.id:<4} {s.inicio:%d/%m %H:%M}  {i.tipo_item:<10} {i.tipo_horario_aplicado:<13} "
              f"{qtd} x {i.valor_unitario:.2f} = {_r(i.valor_total_item)}{aj}")
    print("-" * 86)
    linhas = [(f"Energia ({f.total_kwh:.1f} kWh)", f.valor_energia), ("Ociosidade (P)", f.valor_ociosidade)]
    if f.modalidade == "mensal":
        linhas.append(("Contribuição fixa (C)", f.valor_fixo))
    linhas.append(("TOTAL", f.valor_final))
    for rotulo, valor in linhas:
        print(f"  {rotulo:<70}{_r(valor)}")
    if f.modalidade == "avulso":
        print(f"  Pré-autorizado: {_r(f.pre_autorizado).strip()} | estornado: {_r(f.estorno).strip()}")
    if f.sessoes_em_revisao:
        print(f"  {f.sessoes_em_revisao} sessão(ões) do mês retida(s) pela IA, fora desta cobrança")
    print("\nInsights da IA:")
    for i in db.scalars(select(InsightIA).where(InsightIA.fatura_id == f.id)):
        print(f"  [{i.tipo}] {i.mensagem}")


def cmd_gestor(args):
    db = _db()
    mes = args.mes or db.scalar(select(Fatura.referencia_mes).order_by(Fatura.referencia_mes.desc()))
    print(f"\nVISÃO DO GESTOR — {mes}")
    for i in db.scalars(select(InsightIA).where(InsightIA.usuario_id.is_(None),
                                               InsightIA.periodo_referencia == mes)):
        print(f"  [{i.tipo}] {i.mensagem}")
    print()
    for f in db.scalars(select(Fatura).where(Fatura.referencia_mes == mes)):
        u = db.get(Usuario, f.usuario_id)
        print(f"  {u.id:>2} {u.nome:<36} {f.modalidade:<7} {f.total_kwh:7.1f} kWh {_r(f.valor_final)}"
              + (f"  ({f.sessoes_em_revisao} em revisão)" if f.sessoes_em_revisao else ""))


def cmd_usuarios(_):
    db = _db()
    for u in db.scalars(select(Usuario)):
        print(f"  {u.id:>2} {u.nome:<36} {u.modalidade:<7} perfil: {u.perfil}")


def main():
    p = argparse.ArgumentParser(description="EV ChargeOps — protótipo Sprint 02")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("executar")
    sub.add_parser("pendencias")
    r = sub.add_parser("revisar")
    r.add_argument("sessao_id", type=int)
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--aprovar", action="store_true")
    g.add_argument("--rejeitar", action="store_true")
    r.add_argument("--obs")
    f = sub.add_parser("fatura")
    f.add_argument("usuario_id", type=int)
    f.add_argument("--mes")
    ge = sub.add_parser("gestor")
    ge.add_argument("--mes")
    sub.add_parser("usuarios")
    args = p.parse_args()
    comandos = {"executar": cmd_executar, "pendencias": cmd_pendencias, "revisar": cmd_revisar,
                "fatura": cmd_fatura, "gestor": cmd_gestor, "usuarios": cmd_usuarios}
    comandos.get(args.cmd or "executar")(args)


if __name__ == "__main__":
    main()
