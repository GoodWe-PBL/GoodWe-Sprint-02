"""
Extrai as sessões do relatório "Charging Record" exportado do portal SEMS+ (PDF)
e gera data/raw/charging_record.csv.

Uso:
    python scripts/extrair_charging_record.py caminho/Charging_Record.pdf

Cada linha da tabela do PDF tem o formato:
    <card_id> MM/DD/AAAA HH:MM MM/DD/AAAA HH:MM HH:MM:SS <kwh>
"""
import csv
import re
import sys
from pathlib import Path

# Expressão regular de uma linha da tabela. Cada (?P<nome>...) captura um campo:
# \d = dígito, {2} = exatamente dois, \s+ = um ou mais espaços.
PADRAO_LINHA = re.compile(
    r"(?P<card>[0-9A-Z]{16})\s+"
    r"(?P<inicio>\d{2}/\d{2}/\d{4} \d{2}:\d{2})\s+"
    r"(?P<fim>\d{2}/\d{2}/\d{4} \d{2}:\d{2})\s+"
    r"(?P<duracao>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<kwh>\d+\.\d{2})"
)
PADRAO_NUMERO_DE_SERIE = re.compile(r"EV Charger SN:\s*(\S+)")
PADRAO_TOTAL = re.compile(r"Total Energy Charged:\s*([\d.]+)")


def extrair_texto(caminho_pdf):
    """Devolve o texto de todas as páginas do PDF, uma embaixo da outra."""
    import pdfplumber  # importado aqui para o resto do módulo não depender dele

    with pdfplumber.open(caminho_pdf) as pdf:
        return "\n".join(pagina.extract_text() or "" for pagina in pdf.pages)


def ler_relatorio(texto):
    """Devolve (número de série do carregador, total declarado em kWh, lista de sessões).
    Cada sessão é um dicionário com card, inicio, fim, duracao e kwh (todos em texto)."""
    achou_serie = PADRAO_NUMERO_DE_SERIE.search(texto)
    achou_total = PADRAO_TOTAL.search(texto)
    numero_de_serie = achou_serie.group(1) if achou_serie else None
    total_declarado = float(achou_total.group(1)) if achou_total else None
    sessoes = [linha.groupdict() for linha in PADRAO_LINHA.finditer(texto)]
    return numero_de_serie, total_declarado, sessoes


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    origem = Path(sys.argv[1])
    if origem.suffix.lower() == ".pdf":
        texto = extrair_texto(origem)
    else:
        texto = origem.read_text()  # também aceita o relatório já convertido em texto
    numero_de_serie, total_declarado, sessoes = ler_relatorio(texto)

    soma = round(sum(float(sessao["kwh"]) for sessao in sessoes), 2)
    print(f"Carregador: {numero_de_serie} | sessões lidas: {len(sessoes)} | soma: {soma} kWh "
          f"| total no relatório: {total_declarado} kWh")
    if total_declarado is not None and abs(soma - total_declarado) > 0.05:
        print("ATENÇÃO: a soma das sessões não bate com o total do relatório.")

    destino = Path(__file__).resolve().parents[1] / "data" / "raw" / "charging_record.csv"
    with open(destino, "w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(["serial_carregador", "card_id", "inicio", "fim", "duracao", "energia_kwh"])
        # o relatório vem do mais recente para o mais antigo; gravamos em ordem cronológica
        for sessao in reversed(sessoes):
            escritor.writerow([numero_de_serie, sessao["card"], sessao["inicio"], sessao["fim"],
                               sessao["duracao"], sessao["kwh"]])
    print(f"CSV gravado em {destino}")


if __name__ == "__main__":
    main()
