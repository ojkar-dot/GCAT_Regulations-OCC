"""Parseadores únicos de ficheros NEST (.COS, .SPC, .CFG).

Toda la herramienta (motor y app) lee los ficheros a través de este módulo,
para que solo exista una interpretación de cada formato.

Formatos esperados (separador ';', codificación latin-1):
  .COS  Fecha;ACC;Hora_Ini;Hora_Fin;Configuracion[;Tipo...]
        11/06/2026;LECMCTAS;04:45;05:05;CNF3C;E
  .CFG  ACC;Configuracion;Sector
        LECBCTAW;CNF4CW;LECBG23
  .SPC  Bloques de sector colapsado (A) seguidos de sus componentes (S)
        A;LECBG12;...;CS;2
        S;LECBG1
        S;LECBG2
        Un componente S puede ser a su vez el nombre de otro bloque A
        (anidamiento); se expande de forma recursiva.
"""

__version__ = "2026.11.06-b"  # debe coincidir con APP_VERSION de app.py

import re

import pandas as pd

HORA_RE = re.compile(r"^\d{1,2}:\d{2}$")


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------
def to_bytes(f):
    """Obtiene los bytes de un fichero subido, bytes o str."""
    if f is None:
        return b""
    if isinstance(f, (bytes, bytearray)):
        return bytes(f)
    if isinstance(f, str):
        return f.encode("latin-1", errors="ignore")
    if hasattr(f, "getvalue"):
        return f.getvalue()
    if hasattr(f, "read"):
        data = f.read()
        return data if isinstance(data, bytes) else str(data).encode("latin-1", errors="ignore")
    raise TypeError(f"Tipo de fichero no soportado: {type(f)!r}")


def decode(f):
    return to_bytes(f).decode("latin-1", errors="ignore")


def detect_eol(text):
    """Devuelve el fin de línea dominante del texto ('\\r\\n' o '\\n')."""
    return "\r\n" if "\r\n" in text else "\n"


def is_comment(line):
    s = line.strip()
    return not s or s.startswith("#") or s.startswith(";")


def hhmm_to_min(h):
    """'HH:MM' -> minutos desde las 00:00 (admite 24:00). None si no es válida."""
    h = str(h).strip()
    if not HORA_RE.match(h):
        return None
    hh, mm = (int(x) for x in h.split(":"))
    if hh > 24 or mm > 59 or (hh == 24 and mm > 0):
        return None
    return hh * 60 + mm


def norm_hhmm(h):
    m = hhmm_to_min(h)
    return None if m is None else f"{m // 60:02d}:{m % 60:02d}"


def duracion_min(h_ini, h_fin):
    """Duración del tramo en minutos. Fin <= inicio se interpreta como cruce
    de medianoche (un tramo 00:00-00:00 dura 24 h)."""
    a, b = hhmm_to_min(h_ini), hhmm_to_min(h_fin)
    if a is None or b is None:
        return None
    d = b - a
    if d <= 0:
        d += 1440
    return d


# ---------------------------------------------------------------------------
# .COS
# ---------------------------------------------------------------------------
def parse_cos_line(line):
    """Interpreta una línea de datos .COS. Devuelve None si es comentario,
    cabecera o una línea sin horas válidas."""
    if is_comment(line):
        return None
    p = line.split(";")
    if len(p) < 5:
        return None
    h_ini, h_fin = norm_hhmm(p[2]), norm_hhmm(p[3])
    dur = duracion_min(p[2], p[3])
    cnf = p[4].strip().upper()
    if h_ini is None or h_fin is None or dur is None or not cnf:
        return None
    return {
        "Fecha": p[0].strip(),
        "ACC": p[1].strip().upper(),
        "Hora": h_ini,
        "Hora_Fin": h_fin,
        "Configuracion": cnf,
        "Tipo": p[5].strip().upper() if len(p) > 5 and p[5].strip() else "",
        "Duracion_Min": int(dur),
    }


COS_COLUMNS = ["Archivo", "Linea", "Fecha", "ACC", "Hora", "Hora_Fin",
               "Configuracion", "Tipo", "Duracion_Min"]


def parse_cos_content(file_bytes, filename=""):
    """Devuelve un DataFrame con un registro por tramo del .COS."""
    records = []
    for n, line in enumerate(decode(file_bytes).splitlines(), start=1):
        rec = parse_cos_line(line)
        if rec:
            rec["Archivo"] = filename
            rec["Linea"] = n
            records.append(rec)
    return pd.DataFrame(records, columns=COS_COLUMNS)


# ---------------------------------------------------------------------------
# .CFG
# ---------------------------------------------------------------------------
def parse_cfg_content(file_bytes, filename=""):
    """Devuelve {(ACC, Configuracion): set(sectores)}.

    La clave incluye el ACC porque el mismo nombre de configuración puede
    existir en varios ACC con sectores distintos."""
    cfg = {}
    for line in decode(file_bytes).splitlines():
        if is_comment(line):
            continue
        p = [x.strip().upper() for x in line.split(";")]
        if len(p) >= 3 and p[0] and p[1] and p[2]:
            cfg.setdefault((p[0], p[1]), set()).add(p[2])
    return cfg


# ---------------------------------------------------------------------------
# .SPC
# ---------------------------------------------------------------------------
def parse_spc_content(file_bytes, filename=""):
    """Devuelve los bloques en bruto {CS: set(componentes)}.

    Cada línea 'A' abre un bloque; cada línea 'S' añade un componente al
    bloque abierto. Un componente puede ser un ES o el nombre de otro bloque."""
    blocks = {}
    current = None
    for line in decode(file_bytes).splitlines():
        if is_comment(line):
            continue
        p = [x.strip().upper() for x in line.split(";")]
        if len(p) < 2 or not p[1]:
            continue
        if p[0] == "A":
            current = p[1]
            blocks.setdefault(current, set())
        elif p[0] == "S" and current:
            blocks[current].add(p[1])
    return blocks


def resolve_spc(blocks):
    """Expande recursivamente los bloques a sus ES terminales.

    Devuelve {CS: frozenset(ES)}. Los ciclos se cortan sin error."""
    cache = {}

    def expand(name, stack):
        if name in cache:
            return cache[name]
        if name in stack:
            return frozenset()
        out = set()
        for child in blocks.get(name, ()):
            if child in blocks and child != name:
                out |= expand(child, stack | {name})
            else:
                out.add(child)
        cache[name] = frozenset(out)
        return cache[name]

    return {cs: expand(cs, frozenset()) for cs in blocks}
