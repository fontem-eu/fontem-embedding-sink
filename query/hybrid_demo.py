"""End-to-end hybrid search demo — one file, no framework, real numbers."""
import json
import os
import sys
import time
import urllib.request

import psycopg


def embed(text: str, linguistics_url: str, backend: str = "mistral-embed") -> tuple[list[float], str]:
    """Ask linguistics for a query embedding. Returns (vector, encoder_id)."""
    req = urllib.request.Request(
        linguistics_url.rstrip("/") + "/embed",
        data=json.dumps({"text": text, "backend": backend}).encode(),
        headers={"Content-Type": "application/json"},
    )
    r = json.loads(urllib.request.urlopen(req, timeout=15).read())
    return r["vector"], r["encoder_id"]


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def hybrid(
    conn: psycopg.Connection, query: str, qvec: list[float], encoder_id: str,
    country: str | None = None, types: list[str] | None = None, limit: int = 10,
) -> tuple[list[dict], float]:
    sql = open(os.path.join(os.path.dirname(__file__), "hybrid.sql")).read()
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql, {"q": query, "qvec": _vec_literal(qvec), "enc": encoder_id, "country": country, "types": types, "limit": limit})
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return rows, (time.perf_counter() - t0) * 1000


def run(query: str, country: str | None, types: list[str] | None, limit: int) -> None:
    dsn = os.environ["SEARCH_DATABASE_URL"]
    ling = os.environ["LINGUISTICS_URL"]

    t0 = time.perf_counter()
    qvec, enc_id = embed(query, ling)
    t_embed = (time.perf_counter() - t0) * 1000

    with psycopg.connect(dsn) as conn:
        rows, t_query = hybrid(conn, query, qvec, enc_id, country, types, limit)

    print(f"\nQuery: {query!r}")
    if country: print(f"  country filter: {country}")
    if types:   print(f"  type filter:    {types}")
    print(f"  timing: embed {t_embed:5.1f} ms  |  hybrid SQL {t_query:5.1f} ms  |  total {t_embed + t_query:5.1f} ms")
    print(f"  results ({len(rows)}):")
    print()
    print(f"    {'#':<3} {'score':>7}  {'lex':>4}  {'vec':>4}  {'type':<9}  text")
    print(f"    {'':<3} {'':>7}  {'':>4}  {'':>4}  {'':<9}  " + "─" * 78)
    for i, r in enumerate(rows, 1):
        text = (r["embed_text"] or "")[:80]
        lex = r["lex_rank"] if r["lex_rank"] is not None else "—"
        vec = r["vec_rank"] if r["vec_rank"] is not None else "—"
        print(f"    {i:<3} {r['rrf_score']:>7}  {str(lex):>4}  {str(vec):>4}  {r['entity_type']:<9}  {text}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--country")
    ap.add_argument("--types", help="comma-separated entity types")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    types = a.types.split(",") if a.types else None
    run(a.query, a.country, types, a.limit)
