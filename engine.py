"""Motor de desdoblamiento de sectores colapsados (CS) para ficheros NEST.

Flujo:
  1. Cargar COS / SPC / CFG (vía parsers.py).
  2. Calcular las particiones mínimas de un CS en piezas definidas en el SPC
     (CS intermedios o ES), mediante búsqueda exacta de recubrimiento.
  3. Sustituir en los .COS cada configuración que abre el CS por la
     configuración equivalente con el CS desdoblado (existente en el CFG o
     nueva) y generar los ficheros NEST de salida.
"""

__version__ = "2026.11.06-b"  # debe coincidir con APP_VERSION de app.py

import io
import math
import re
import zipfile

import pandas as pd

from parsers import (
    decode,
    detect_eol,
    hhmm_to_min,
    parse_cfg_content,
    parse_cos_content,
    parse_cos_line,
    parse_spc_content,
    resolve_spc,
    to_bytes,
)

DIAS_ES = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
           4: "Viernes", 5: "Sábado", 6: "Domingo"}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def get_shift(h_str):
    """Clasifica una hora HH:MM en un turno operativo ATC."""
    try:
        hour = int(str(h_str)[:2])
    except Exception:
        return "N/A"
    if 7 <= hour < 15:
        return "Mañana"
    if 15 <= hour < 22:
        return "Tarde"
    return "Noche"


def iter_files(files, default_name="archivo"):
    """Itera (nombre, bytes) sobre ficheros subidos, bytes o tuplas (nombre, bytes)."""
    if not files:
        return
    if not isinstance(files, (list, tuple)) or (
        len(files) == 2 and isinstance(files[0], str) and isinstance(files[1], (bytes, bytearray))
    ):
        files = [files]
    for i, f in enumerate(files):
        if isinstance(f, tuple) and len(f) == 2:
            yield f[0], to_bytes(f[1])
        else:
            yield getattr(f, "name", f"{default_name}_{i + 1}"), to_bytes(f)


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------
def load_cos(cos_files):
    dfs = [parse_cos_content(b, name) for name, b in iter_files(cos_files, "archivo.cos")]
    dfs = [d for d in dfs if not d.empty]
    if not dfs:
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True)
    df["Turno"] = df["Hora"].apply(get_shift)
    return df


def load_cfg(cfg_files):
    """{(ACC, CNF): frozenset(sectores)} combinando todos los .CFG."""
    merged = {}
    for name, b in iter_files(cfg_files, "archivo.cfg"):
        for key, secs in parse_cfg_content(b, name).items():
            merged.setdefault(key, set()).update(secs)
    return {k: frozenset(v) for k, v in merged.items()}


def load_spc(spc_files):
    """Devuelve (bloques_brutos, es_map) con es_map = {CS: frozenset(ES)}."""
    blocks = {}
    for name, b in iter_files(spc_files, "archivo.spc"):
        for cs, comps in parse_spc_content(b, name).items():
            blocks.setdefault(cs, set()).update(comps)
    return blocks, resolve_spc(blocks)


def build_cfg_map(cfg_files):
    """Compatibilidad: carga los .CFG con clave (ACC, CNF)."""
    return load_cfg(cfg_files)


def elementary_sectors(es_map):
    out = set()
    for es in es_map.values():
        out |= es
    return out


def cnf_map_for_acc(cfg_map, acc):
    """Catálogo {CNF: sectores} de un ACC.

    Devuelve (mapa, exacto). Si el ACC no aparece en el CFG se devuelve el
    catálogo combinado por nombre (exacto=False) para no dejar la vista vacía."""
    acc = str(acc).strip().upper()
    own = {cnf: secs for (a, cnf), secs in cfg_map.items() if a == acc}
    if own or not cfg_map:
        return own, True
    merged = {}
    for (_, cnf), secs in cfg_map.items():
        merged.setdefault(cnf, set()).update(secs)
    return {k: frozenset(v) for k, v in merged.items()}, False


def classify_sector(name, es_map):
    """'CS' si el sector agrupa más de un ES según el SPC, 'ES' en otro caso.
    Sin SPC se usa una heurística por nombre (terminado en dígito -> ES)."""
    if es_map:
        es = es_map.get(name)
        if es is not None:
            return "CS" if len(es) > 1 else "ES"
        if name in elementary_sectors(es_map):
            return "ES"
    return "ES" if name[-1:].isdigit() else "CS"


def cs_options_for_acc(acc, cfg_map, es_map):
    """CS desdoblables de un ACC: sectores abiertos en sus configuraciones que
    el SPC define con 2 o más ES."""
    acc = str(acc).strip().upper()
    in_acc = set()
    for (a, _), secs in cfg_map.items():
        if a == acc:
            in_acc |= secs
    pool = in_acc if in_acc else set(es_map)
    return sorted(s for s in pool if len(es_map.get(s, ())) >= 2)


TURNOS = ["Mañana", "Tarde", "Noche"]
USO_COLS = ["Minutos", "Dias", "Tramos"] + TURNOS


def explode_sectors(df, cnf_map):
    """Una fila por (tramo .COS, sector abierto en su configuración).

    Es la base común de la Inspección Jerárquica y del Motor: ambos calculan
    el uso de un sector a partir de aquí."""
    if df is None or df.empty:
        return pd.DataFrame(columns=list(df.columns if df is not None else []) + ["Sector"])
    out = df.assign(Sector=df["Configuracion"].map(lambda c: sorted(cnf_map.get(c, ()))))
    return out.explode("Sector").dropna(subset=["Sector"]).reset_index(drop=True)


def usage_table(df_exploded):
    """Uso por sector: minutos, días y tramos con el sector abierto y minutos por turno."""
    if df_exploded is None or df_exploded.empty:
        return pd.DataFrame(columns=USO_COLS)
    g = df_exploded.groupby("Sector")
    t = pd.DataFrame({"Minutos": g["Duracion_Min"].sum(), "Dias": g["Fecha"].nunique(), "Tramos": g.size()})
    turnos = (df_exploded.pivot_table(index="Sector", columns="Turno", values="Duracion_Min",
                                      aggfunc="sum", fill_value=0)
              .reindex(columns=TURNOS, fill_value=0))
    return t.join(turnos).fillna(0).astype(int)[USO_COLS].sort_values("Minutos", ascending=False)


def sector_usage_table(df_cos, cfg_map, acc, df_scope=None):
    """Tabla de uso de los sectores de un ACC en todo el ciclo (o en `df_scope`)."""
    acc = str(acc).strip().upper()
    cnf_map, _ = cnf_map_for_acc(cfg_map, acc)
    if df_scope is None:
        df_scope = df_cos[df_cos["ACC"] == acc] if df_cos is not None and not df_cos.empty else None
    return usage_table(explode_sectors(df_scope, cnf_map))


def sector_config_usage(df_cos, cfg_map, acc, sector):
    """Configuraciones del .COS en las que se abrió `sector`, con minutos y tramos."""
    acc = str(acc).strip().upper()
    cnf_map, _ = cnf_map_for_acc(cfg_map, acc)
    cols = ["Configuracion", "Minutos", "Tramos", "Dias"]
    if df_cos is None or df_cos.empty:
        return pd.DataFrame(columns=cols)
    sub = df_cos[(df_cos["ACC"] == acc) & df_cos["Configuracion"].map(lambda c: sector in cnf_map.get(c, ()))]
    if sub.empty:
        return pd.DataFrame(columns=cols)
    g = sub.groupby("Configuracion")
    return (pd.DataFrame({"Minutos": g["Duracion_Min"].sum(), "Tramos": g.size(), "Dias": g["Fecha"].nunique()})
            .reset_index().sort_values("Minutos", ascending=False)[cols])


def configs_used(df_cos, acc):
    """Configuraciones que aparecen en el .COS del ACC."""
    if df_cos is None or df_cos.empty:
        return set()
    return set(df_cos.loc[df_cos["ACC"] == str(acc).strip().upper(), "Configuracion"])


def sector_minutes(df_cos, cfg_map, acc):
    """Minutos totales que cada sector ha estado abierto en el ACC."""
    if df_cos is None or df_cos.empty:
        return {}
    return sector_usage_table(df_cos, cfg_map, acc)["Minutos"].to_dict()


# ---------------------------------------------------------------------------
# Particiones mínimas (recubrimiento exacto de cardinalidad mínima)
# ---------------------------------------------------------------------------
def candidate_pieces(target, es_map):
    """Piezas válidas para desdoblar `target`: bloques del SPC cuyo conjunto de
    ES es un subconjunto propio del de `target`, más cada ES suelto.

    Si varios bloques cubren el mismo espacio se usa el primero por orden
    alfabético y el resto queda como alias. Un ES sin bloque propio se marca
    con own_cs=False (puede no ser abrible como sector en NEST)."""
    universe = es_map.get(target, frozenset())
    by_set = {}
    for cs in sorted(es_map):
        es = es_map[cs]
        if cs == target or not es or not es < universe:
            continue
        by_set.setdefault(es, []).append(cs)
    pieces = [
        {"name": names[0], "es": es, "aliases": names[1:], "own_cs": True}
        for es, names in by_set.items()
    ]
    for e in sorted(universe):
        if frozenset([e]) not in by_set:
            pieces.append({"name": e, "es": frozenset([e]), "aliases": [], "own_cs": False})
    return pieces


def minimal_partitions(target, es_map, max_solutions=200):
    """Todas las particiones exactas de `target` con el menor número de piezas
    (>= 2), hasta `max_solutions`. Cada solución es una lista de piezas."""
    universe = sorted(es_map.get(target, ()))
    if len(universe) < 2:
        return []
    bit = {e: 1 << i for i, e in enumerate(universe)}
    full = (1 << len(universe)) - 1
    pieces = candidate_pieces(target, es_map)
    masks = [sum(bit[e] for e in p["es"]) for p in pieces]
    max_size = max(len(p["es"]) for p in pieces)

    by_elem = {e: [] for e in universe}
    for i, p in enumerate(pieces):
        for e in p["es"]:
            by_elem[e].append(i)
    for e in by_elem:  # piezas grandes primero: encuentra antes soluciones cortas
        by_elem[e].sort(key=lambda i: (-len(pieces[i]["es"]), not pieces[i]["own_cs"], pieces[i]["name"]))

    best = [len(universe)]
    solutions = []

    def dfs(covered, chosen):
        if covered == full:
            k = len(chosen)
            if k < best[0]:
                best[0] = k
                solutions.clear()
            if k == best[0] and len(solutions) < max_solutions:
                solutions.append(list(chosen))
            return
        remaining = len(universe) - bin(covered).count("1")
        if len(chosen) + math.ceil(remaining / max_size) > best[0]:
            return
        # primer ES sin cubrir: cada partición se genera una sola vez
        e = next(x for x in universe if not covered & bit[x])
        for i in by_elem[e]:
            if masks[i] & covered:
                continue
            chosen.append(i)
            dfs(covered | masks[i], chosen)
            chosen.pop()

    dfs(0, [])
    return [[pieces[i] for i in sol] for sol in solutions]


def rank_partitions(acc, target, partitions, cfg_map, sector_min=None, cnfs_usadas=None):
    """Ordena las particiones mínimas por criterio operativo:
      1. menos piezas sin CS propio en el SPC,
      2. menos configuraciones nuevas a crear en el CFG,
      3. más minutos históricos de apertura de las piezas.

    Si se pasa `cnfs_usadas`, solo cuentan las configuraciones que aparecen en
    el .COS (las únicas que el motor reescribirá)."""
    acc = str(acc).strip().upper()
    sector_min = sector_min or {}
    own = {cnf: secs for (a, cnf), secs in cfg_map.items() if a == acc}
    affected = {cnf: secs for cnf, secs in own.items()
                if target in secs and (cnfs_usadas is None or cnf in cnfs_usadas)}
    catalog = set(own.values())

    rows = []
    for part in partitions:
        names = [p["name"] for p in part]
        nuevas = sum(1 for secs in affected.values()
                     if ((secs - {target}) | set(names)) not in catalog)
        rows.append({
            "Nº piezas": len(part),
            "Partición": " + ".join(names),
            "Configs existentes": len(affected) - nuevas,
            "Configs nuevas": nuevas,
            "Piezas sin CS propio": sum(1 for p in part if not p["own_cs"]),
            "Minutos históricos piezas": sum(sector_min.get(n, 0) for n in names),
            "Parámetro": ";".join(names),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(
        by=["Piezas sin CS propio", "Configs nuevas", "Minutos históricos piezas", "Partición"],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)


def parse_tokens(text):
    return [t.strip().upper() for t in re.split(r"[,;\s]+", str(text)) if t.strip()]


def validate_partition(target, tokens, es_map):
    """Comprueba que `tokens` cubre exactamente y sin solapes el CS `target`."""
    universe = es_map.get(target, frozenset())
    elem = elementary_sectors(es_map)
    desconocidos, solapes, duplicados = [], set(), []
    seen, union = set(), set()
    for t in tokens:
        if t in seen:
            duplicados.append(t)
            continue
        seen.add(t)
        if t in es_map:
            es = es_map[t]
        elif t in elem:
            es = frozenset([t])
        else:
            desconocidos.append(t)
            continue
        solapes |= union & es
        union |= es
    faltantes = universe - union
    sobrantes = union - universe
    es_el_propio = target in seen
    ok = not (desconocidos or solapes or duplicados or faltantes or sobrantes or es_el_propio) and len(seen) >= 2
    return {
        "ok": ok,
        "faltantes": sorted(faltantes),
        "sobrantes": sorted(sobrantes),
        "solapes": sorted(solapes),
        "desconocidos": desconocidos,
        "duplicados": duplicados,
        "es_el_propio": es_el_propio,
        "piezas": len(seen),
    }


# ---------------------------------------------------------------------------
# Ejecución del desdoblamiento sobre los .COS
# ---------------------------------------------------------------------------
def make_new_cnf_name(cnf_pre, n_post, taken, sufijo="_D"):
    """Nombre para una configuración nueva: renumera con el recuento real de
    sectores (CNF3C -> CNF5C) y añade un sufijo distintivo, evitando choques."""
    m = re.match(r"^(.*?CNF)(\d+)(.*)$", cnf_pre)
    if m:
        base = f"{m.group(1)}{n_post}{m.group(3)}"
    else:
        m = re.match(r"^(\d+)(.*)$", cnf_pre)
        base = f"{n_post}{m.group(2)}" if m else cnf_pre
    name, i = f"{base}{sufijo}", 2
    while name in taken:
        name = f"{base}{sufijo}{i}"
        i += 1
    return name


def _replace_field(field, value):
    lead = field[: len(field) - len(field.lstrip())]
    trail = field[len(field.rstrip()):]
    return f"{lead}{value}{trail}"


def run_desdoble_audit(spc_files, cos_files, cfg_files, acc, cs_integrated, pieces,
                       sufijo="_D", max_len=None):
    """Aplica el desdoblamiento de `cs_integrated` en `pieces` a las líneas del
    ACC `acc` de todos los .COS.

    Devuelve un dict con: ok, error, validacion, df_audit, df_cambios,
    df_nuevas, zip_bytes, avisos, log."""
    res = {"ok": False, "error": "", "validacion": None, "df_audit": pd.DataFrame(),
           "df_cambios": pd.DataFrame(), "df_nuevas": pd.DataFrame(),
           "zip_bytes": b"", "avisos": [], "log": []}

    acc = str(acc).strip().upper()
    cs = str(cs_integrated).strip().upper()
    tokens = parse_tokens(pieces) if isinstance(pieces, str) else [str(p).strip().upper() for p in pieces]
    cos_list = list(iter_files(cos_files, "archivo.cos"))
    cfg_list = list(iter_files(cfg_files, "archivo.cfg"))

    if not cos_list or not cfg_list or not cs or not tokens:
        res["error"] = "Faltan parámetros obligatorios (COS, CFG, CS o piezas)."
        return res

    cfg_map = load_cfg(cfg_list)
    _, es_map = load_spc(spc_files)
    if cs not in es_map:
        res["error"] = f"{cs} no está definido en el SPC."
        return res

    val = validate_partition(cs, tokens, es_map)
    res["validacion"] = val
    if not val["ok"]:
        res["error"] = "La partición no cubre el CS de forma exacta y disjunta."
        return res

    own = {cnf: set(secs) for (a, cnf), secs in cfg_map.items() if a == acc}
    if not own:
        res["error"] = f"El ACC {acc} no tiene configuraciones en el CFG."
        return res

    piezas = set(tokens)
    inverse = {}
    for cnf in sorted(own):
        inverse.setdefault(frozenset(own[cnf]), cnf)
    taken = set(own)
    decided = {}      # CNF_PRE -> (CNF_POST, resultado)
    nuevas = {}       # CNF_POST -> {"Desde": CNF_PRE, "Sectores": set}

    # Aviso de solape geométrico con vecinos (no debería ocurrir)
    es_piezas = set().union(*(es_map.get(t, frozenset([t])) for t in piezas))

    rows, out_files = [], []
    otros_acc = 0
    for fname, data in cos_list:
        text = decode(data)
        out = []
        for n, raw in enumerate(text.splitlines(keepends=True), start=1):
            body = raw.rstrip("\r\n")
            end = raw[len(body):]
            rec = parse_cos_line(body)
            if rec is None:
                out.append(raw)
                continue
            if rec["ACC"] != acc:
                otros_acc += 1
                out.append(raw)
                continue

            c_pre = rec["Configuracion"]
            pre = own.get(c_pre)
            base_row = {"Archivo": fname, "Linea": n, "Fecha": rec["Fecha"],
                        "Hora": rec["Hora"], "Hora_Fin": rec["Hora_Fin"],
                        "HH": rec["Hora"][:2], "Turno": get_shift(rec["Hora"]),
                        "Duracion_Min": rec["Duracion_Min"], "CNF_PRE": c_pre}

            if pre is None:
                rows.append({**base_row, "CNF_POST": c_pre, "Resultado": "CNF no definida en CFG",
                             "Cambio": 0, "Sectores_PRE": "", "Sectores_POST": "", "Transicion": ""})
                out.append(raw)
                continue
            if cs not in pre:
                s = ", ".join(sorted(pre))
                rows.append({**base_row, "CNF_POST": c_pre, "Resultado": "Sin cambio", "Cambio": 0,
                             "Sectores_PRE": s, "Sectores_POST": s,
                             "Transicion": f"{len(pre)} > {len(pre)}"})
                out.append(raw)
                continue

            post = (pre - {cs}) | piezas
            if c_pre not in decided:
                vecinos_es = set().union(*(es_map.get(v, frozenset([v])) for v in pre - {cs}))
                if vecinos_es & es_piezas:
                    res["avisos"].append(
                        f"{c_pre}: las piezas se solapan con sectores vecinos "
                        f"({', '.join(sorted(vecinos_es & es_piezas))}).")
                fpost = frozenset(post)
                if fpost in inverse:
                    decided[c_pre] = (inverse[fpost], "Existente en CFG")
                else:
                    name = make_new_cnf_name(c_pre, len(post), taken, sufijo)
                    taken.add(name)
                    inverse[fpost] = name
                    nuevas[name] = {"Desde": c_pre, "Sectores": post}
                    decided[c_pre] = (name, "Nueva")
                    if max_len and len(name) > max_len:
                        res["avisos"].append(
                            f"El nombre {name} tiene {len(name)} caracteres (límite indicado: {max_len}).")
            c_post, resultado = decided[c_pre]
            rows.append({**base_row, "CNF_POST": c_post, "Resultado": resultado, "Cambio": 1,
                         "Sectores_PRE": ", ".join(sorted(pre)),
                         "Sectores_POST": ", ".join(sorted(post)),
                         "Transicion": f"{len(pre)} > {len(post)}"})
            p = body.split(";")
            p[4] = _replace_field(p[4], c_post)
            out.append(";".join(p) + end)
        out_files.append((fname, "".join(out)))
        res["log"].append(f"Archivo procesado: {fname}")

    if otros_acc:
        res["log"].append(f"{otros_acc} tramos de otros ACC se han copiado sin cambios.")

    df = pd.DataFrame(rows)
    df_c = df[df["Cambio"] == 1].copy() if not df.empty else pd.DataFrame()
    df_n = pd.DataFrame([
        {"CNF_NUEVA": k, "Desde": v["Desde"], "Nº sectores": len(v["Sectores"]),
         "Sectores": ", ".join(sorted(v["Sectores"]))}
        for k, v in sorted(nuevas.items())
    ])

    # ---- Ficheros de salida -------------------------------------------------
    cfg_text0 = decode(cfg_list[0][1])
    eol = detect_eol(cfg_text0)
    lineas_nuevas = [f"{acc};{name};{sec}"
                     for name in sorted(nuevas) for sec in sorted(nuevas[name]["Sectores"])]
    cfg_nuevo = eol.join(lineas_nuevas) + (eol if lineas_nuevas else "")

    fusion = ""
    for _, b in cfg_list:
        t = decode(b)
        if t and not t.endswith(("\n", "\r")):
            t += eol
        fusion += t
    fusion += cfg_nuevo

    leeme = eol.join([
        "Desdoblamiento de sectores - resumen",
        f"ACC: {acc}",
        f"CS desdoblado: {cs} ({len(es_map[cs])} ES)",
        f"Piezas ({len(tokens)}): {';'.join(tokens)}",
        f"Tramos modificados: {len(df_c)}",
        f"Configuraciones reutilizadas del CFG: {sum(1 for v in decided.values() if v[1] != 'Nueva')}",
        f"Configuraciones nuevas: {len(nuevas)}",
        "",
        "Ficheros:",
        "  AUDIT_<fichero>.cos             COS con las configuraciones sustituidas",
        f"  NUEVAS_CONFIGURACIONES_{acc}.cfg  solo las configuraciones nuevas",
        f"  CFG_FUSIONADO_{acc}.cfg          CFG original + configuraciones nuevas",
        "  AUDITORIA_<ACC>_<CS>.csv       detalle tramo a tramo",
    ] + ([""] + ["Avisos:"] + [f"  {a}" for a in res["avisos"]] if res["avisos"] else [])) + eol

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in out_files:
            zf.writestr(f"AUDIT_{fname}", content.encode("latin-1", errors="replace"))
        zf.writestr(f"NUEVAS_CONFIGURACIONES_{acc}.cfg", cfg_nuevo.encode("latin-1", errors="replace"))
        zf.writestr(f"CFG_FUSIONADO_{acc}.cfg", fusion.encode("latin-1", errors="replace"))
        if not df.empty:
            zf.writestr(f"AUDITORIA_{acc}_{cs}.csv", df.to_csv(index=False, sep=";").encode("utf-8-sig"))
        zf.writestr("LEEME.txt", leeme.encode("latin-1", errors="replace"))

    res.update(ok=True, df_audit=df, df_cambios=df_c, df_nuevas=df_n, zip_bytes=buf.getvalue())
    return res


# ---------------------------------------------------------------------------
# Asistente predictivo
# ---------------------------------------------------------------------------
def predict_atc_behavior(df_acc, cnf_map, hora_consulta="13:30", fecha_referencia=None, ventana_min=15):
    """Probabilidad histórica de desdoble / fusión / estabilidad alrededor de
    una hora, usando los días de la misma semana que `fecha_referencia`
    (o todos los días si no se indica una fecha válida).

    El cambio de sectores se calcula sobre la secuencia completa de cada día y
    después se filtra la ventana, para no perder el tramo anterior."""
    res = {"dia_semana": "Todos", "total_muestras": 0, "prob_estable": 0,
           "prob_desdoble": 0, "prob_fusion": 0,
           "tendencia_principal": "Sin datos", "sector_objetivo": "N/A"}
    if df_acc is None or df_acc.empty or not cnf_map:
        return res
    q = hhmm_to_min(hora_consulta)
    if q is None:
        res["tendencia_principal"] = "Hora no válida"
        return res

    df = df_acc.sort_values(["Archivo", "Fecha", "Hora"]).copy()
    df["N"] = df["Configuracion"].map(lambda c: len(cnf_map.get(c, ())))
    df["N_prev"] = df.groupby(["Archivo", "Fecha"])["N"].shift(1)
    df = df.dropna(subset=["N_prev"])
    df["Delta"] = df["N"] - df["N_prev"]
    df["Fecha_dt"] = pd.to_datetime(df["Fecha"], dayfirst=True, errors="coerce")

    ref = pd.to_datetime(fecha_referencia, dayfirst=True, errors="coerce") if fecha_referencia else pd.NaT
    if pd.notna(ref):
        res["dia_semana"] = DIAS_ES[ref.dayofweek]
        mismo = df[df["Fecha_dt"].dt.dayofweek == ref.dayofweek]
        if not mismo.empty:
            df = mismo

    def en_ventana(h):
        m = hhmm_to_min(h)
        if m is None:
            return False
        d = abs(m - q)
        return min(d, 1440 - d) <= ventana_min

    df = df[df["Hora"].apply(en_ventana)]
    total = len(df)
    if total == 0:
        return res

    des, fus, est = (df["Delta"] > 0).sum(), (df["Delta"] < 0).sum(), (df["Delta"] == 0).sum()
    res.update(total_muestras=int(total),
               prob_desdoble=int(round(des / total * 100)),
               prob_fusion=int(round(fus / total * 100)),
               prob_estable=int(round(est / total * 100)))
    if des > fus and des > est:
        res["tendencia_principal"], sel = "🟢 DESDOBLAMIENTO (apertura por tráfico)", df["Delta"] > 0
    elif fus > des and fus > est:
        res["tendencia_principal"], sel = "🔴 INTEGRACIÓN (colapso)", df["Delta"] < 0
    else:
        res["tendencia_principal"], sel = "⚪ ESTABLE (se mantiene la capacidad)", df["Delta"] == 0
    top = df[sel]["Configuracion"].value_counts()
    res["sector_objetivo"] = top.index[0] if not top.empty else "N/A"
    return res
