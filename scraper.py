#!/usr/bin/env python3
"""
scraper.py — Baixa a tabela do Brasileirão Série A do Terra
e gera docs/cache_tabela_A.json no formato esperado pelo addon NVDA.
"""

import json
import re
import sys
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser

URL_TERRA = "https://www.terra.com.br/esportes/futebol/brasileiro-serie-a/tabela/"
OUTPUT_FILE = "docs/cache_tabela_A.json"
HTTP_TIMEOUT = 25


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        if resp.status < 200 or resp.status >= 300:
            raise RuntimeError(f"HTTP {resp.status}")
        return resp.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Parser HTML — extrai linhas do <table>
# ---------------------------------------------------------------------------

class TableParser(HTMLParser):
    """Extrai todas as linhas <tr> da tabela de classificação."""

    def __init__(self):
        super().__init__()
        self._in_table = False
        self._in_tbody = False
        self._in_tr = False
        self._in_td = False
        self._tr_class = ""
        self._current_row: list[dict] = []
        self._current_cell: dict = {}
        self._current_text = ""
        self._depth_table = 0
        self.rows: list[dict] = []   # {"class": str, "cells": [{"title": str, "text": str}]}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self._depth_table += 1
            if self._depth_table == 1:
                self._in_table = True
        if not self._in_table:
            return
        if tag == "tbody":
            self._in_tbody = True
        if tag == "tr" and self._in_tbody:
            self._in_tr = True
            self._tr_class = attrs.get("class", "")
            self._current_row = []
        if tag == "td" and self._in_tr:
            self._in_td = True
            self._current_cell = {
                "class": attrs.get("class", ""),
                "title": attrs.get("title", ""),
                "text": "",
            }
            self._current_text = ""

    def handle_endtag(self, tag):
        if tag == "table":
            self._depth_table -= 1
            if self._depth_table == 0:
                self._in_table = False
        if tag == "tbody":
            self._in_tbody = False
        if tag == "tr" and self._in_tr:
            self._in_tr = False
            if self._current_row:
                self.rows.append({
                    "class": self._tr_class,
                    "cells": self._current_row,
                })
        if tag == "td" and self._in_td:
            self._in_td = False
            self._current_cell["text"] = " ".join(self._current_text.split())
            self._current_row.append(self._current_cell)
            self._current_cell = {}
            self._current_text = ""

    def handle_data(self, data):
        if self._in_td:
            self._current_text += data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIGLAS = {
    "Palmeiras": "PAL", "São Paulo": "SAO", "Corinthians": "COR",
    "Bahia": "BAH", "Fluminense": "FLU", "Athletico-PR": "CAP",
    "Bragantino": "BGT", "Grêmio": "GRE", "Chapecoense": "CHA",
    "Mirassol": "MIR", "Flamengo": "FLA", "Coritiba": "CFC",
    "Santos": "SAN", "Botafogo": "BOT", "Vitória": "VIT", "Remo": "REM",
    "Atlético-MG": "CAM", "Internacional": "INT", "Cruzeiro": "CRU",
    "Vasco da Gama": "VAS", "Vasco": "VAS",
}

ZONAS = {
    "libertadores":     lambda c: "zone-1" in c,
    "pre-libertadores": lambda c: "zone-2" in c,
    "sul-americana":    lambda c: "zone-3" in c,
    "rebaixados":       lambda c: "zone-4" in c,
}


def faixa(row_class: str):
    for nome, fn in ZONAS.items():
        if fn(row_class):
            return nome
    return None


def parse_movement(text: str) -> int:
    t = " ".join(text.split())
    m = re.search(r"Subiu\s*(\d+)", t, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"Desceu\s*(\d+)", t, re.I)
    if m:
        return -int(m.group(1))
    return 0


def cell_by_class(cells, cls_fragment: str) -> str:
    for c in cells:
        if cls_fragment in c["class"]:
            return c["text"]
    return ""


def cell_by_title(cells, title: str) -> str:
    for c in cells:
        if c["title"] == title:
            return c["text"]
    return ""


def safe_int(v: str) -> int:
    try:
        return int(v.replace("%", "").strip())
    except Exception:
        return 0


def normalize_name(name: str) -> str:
    name = re.sub(r"\s*>>\s*$", "", name)
    return name.strip()


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------

def parse_standings(html: str) -> list:
    parser = TableParser()
    parser.feed(html)

    dados = []
    for row in parser.rows:
        cells = row["cells"]
        if not cells:
            continue

        pos_text  = cell_by_class(cells, "position")
        pts_text  = cell_by_class(cells, "points")
        name_text = cell_by_class(cells, "team-name")
        move_text = cell_by_class(cells, "movement")

        pos = safe_int(pos_text)
        pts = safe_int(pts_text)
        if pos == 0 and pts == 0 and not name_text:
            continue

        nome = normalize_name(name_text)

        jogos = safe_int(cell_by_title(cells, "Jogos"))
        vits  = safe_int(cell_by_title(cells, "Vitórias"))
        emps  = safe_int(cell_by_title(cells, "Empates"))
        derr  = safe_int(cell_by_title(cells, "Derrotas"))
        gp    = safe_int(cell_by_title(cells, "Gols Pró"))
        gc    = safe_int(cell_by_title(cells, "Gols Contra"))
        sg    = safe_int(cell_by_title(cells, "Saldo de Gols"))
        apr   = safe_int(cell_by_title(cells, "Aproveitamento"))

        dados.append({
            "posicao": pos,
            "pontos":  pts,
            "time": {
                "nome_popular": nome,
                "sigla":        SIGLAS.get(nome),
            },
            "jogos":              jogos,
            "vitorias":           vits,
            "empates":            emps,
            "derrotas":           derr,
            "gols_pro":           gp,
            "gols_contra":        gc,
            "saldo_gols":         sg,
            "aproveitamento":     apr,
            "variacao_posicao":   parse_movement(move_text),
            "ultimos_jogos":      [],
            "faixa_classificacao": faixa(row["class"]),
        })

    return dados


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"Baixando tabela de {URL_TERRA} ...")
    try:
        html = fetch_url(URL_TERRA)
    except Exception as e:
        print(f"ERRO ao baixar HTML: {e}", file=sys.stderr)
        sys.exit(1)

    print("Parseando tabela ...")
    try:
        dados = parse_standings(html)
    except Exception as e:
        print(f"ERRO ao parsear: {e}", file=sys.stderr)
        sys.exit(1)

    if not dados:
        print("ERRO: nenhum time encontrado no HTML.", file=sys.stderr)
        sys.exit(1)

    payload = {"timestamp": int(time.time()), "dados": dados}
    json_str = json.dumps(payload, ensure_ascii=False, indent=2)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(json_str)

    print(f"OK: {len(dados)} times salvos em {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
