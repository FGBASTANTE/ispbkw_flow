r"""Extrae los resultados finales de los ficheros .out del cálculo BKW (Fortran)
y los guarda en un único CSV.

De cada fichero .out toma:
    - ISP:  último valor de "THE ISP IS" (s).
    - Tc:   primer valor de "The Temperature is" (K, cámara).
    - Te:   último valor de "The Temperature is" (K, salida).
    - M:    "The Molecular Weight is" (g/mol, la que usa ISPBKW).
    - Vgas: "The Volume of the Gas is" (cc/mole), última aparición.
    - Mgas: "Moles of Gas" de esa misma línea.
    - Por cada producto del último bloque "Composition of the Propellant
      Products": moles (<especie>_moles) y entalpía estándar de formación
      (<especie>_Hf), que es el penúltimo valor de la segunda línea de la
      especie.

Cada .out se revisa antes de extraer sus valores (ver ``diagnostico``):

    - error:  ISPBKW ha terminado con su mensaje de error, el cálculo está
              incompleto (sin la expansión hasta la salida) o el fichero no se
              puede leer. Sus valores numéricos se dejan vacíos: el ISP que
              aparece en un .out con error no es válido.
    - revisar: ISPBKW ha aceptado alguna iteración con un residuo mayor que
              el umbral de ``UMBRALES`` ("... accepted was"), o con una
              iteración sin umbral definido. Los valores se extraen.
    - ok:     sin incidencias, o solo con iteraciones aceptadas por debajo de
              su umbral (son habituales: el residuo de la temperatura de
              cámara queda en ~0,04 cal por la precisión simple).

La columna "avisos" resume las iteraciones aceptadas (veces y residuo
máximo); con --avisos se escribe además su detalle (avisos.csv).

Los ficheros se procesan en orden alfabético y, dentro, numérico
(exp1, exp2, exp9, exp10, exp11). El CSV tiene una fila por material, con el
nombre del .out sin sufijo como índice (columna "material"), y las columnas
"estado" y "avisos". Cada producto nuevo que aparece en un fichero añade sus
columnas; en los materiales sin error que no lo contienen se rellenan con 0.

Con --nombres (tabla de correspondencia que escribe zzzcomps.py) las filas
siguen el orden de la tabla, se añaden sus columnas (Compuesto, Formula...)
y cada propelente de la tabla sin .out aparece con estado "sin_out". Así los
resultados se unen a los datos de entrada por nombre, no por posición.

Uso (cmd de Windows):
    python extraer_composicion.py RUTA [SUBDIRECTORIO] [--nombres TABLA]

    RUTA           carpeta con los ficheros .out
    SUBDIRECTORIO  opcional; carpeta donde guardar el CSV (se crea si no
                   existe). Sin indicarlo, se guarda en el directorio actual.
    --nombres      opcional; tabla de correspondencia (zzzcomps_nombres.csv)

Ejemplos:
    python extraer_composicion.py C:\datos\propelentes
    python extraer_composicion.py C:\datos\propelentes resultados
    python extraer_composicion.py userdata resultados --nombres zzzcomps_nombres.csv

Resultado (resultados.csv), por ejemplo con exp1.out y exp2.out:
    material,estado,avisos,ISP,Tc,Te,M,Vgas,Mgas,h2o_moles,h2o_Hf,...
    exp1,ok,,268.770812988,1660.04907227,136314.0,9.00025,1.897162,-57107.0,...
    exp2,error,an error in lfb interating on  gas volume  sys1,,,,,,,...

Uso desde Python (diferencia de entalpía productos - reactivo, en J/kg):
    from extraer_composicion import delta_entalpia
    dh = delta_entalpia("userdata/exp1.out")

Códigos de salida: 0 correcto; distinto de 0 si la ruta no existe, no hay
ficheros .out o el uso es incorrecto. Los .out con error no detienen el
proceso: aparecen en el CSV con estado "error" y se resumen en pantalla.
"""

import argparse
import collections
import csv
import os
import re
import sys

NOMBRE_CSV = "resultados.csv"  # nombre del CSV de salida

MARCA = "Composition of the Propellant Products"
# Línea de especie: nombre (admite espacios, paréntesis y símbolos: "sol c",
# "c(s)", "al2o3(s)"...) seguido de los moles
PATRON = re.compile(r"^\s{0,2}([A-Za-z][A-Za-z0-9 ()+\-.,*/'=]*?)\s+"
                    r"([-+]?\d+\.\d+E[-+]?\d+)\s")
NUM = r"([-+]?\d+\.\d+E[-+]?\d+)"
ISP = re.compile(r"THE ISP IS\s+" + NUM, re.IGNORECASE)
TEMP = re.compile(r"The Temperature is\s+" + NUM, re.IGNORECASE)
GAS = re.compile(r"The Volume of the Gas is\s+" + NUM + r"\s+cc/mole,?\s+" + NUM
                 + r"\s+Moles of Gas", re.IGNORECASE)
PESO_FORMULA = re.compile(r"The Molecular Weight is\s+" + NUM + r"\s*,?\s*grams",
                          re.IGNORECASE)
HF_REACTIVO = re.compile(r"The Heat of Formation at 0 deg K is\s+" + NUM
                         + r"\s*,?\s*calories per Formula Weight", re.IGNORECASE)

CAL_J = 4.184  # julios por caloría termoquímica

# Mensajes de ISPBKW: cabecera de error (formato 990) e iteraciones aceptadas
# sin alcanzar la tolerancia ("vgas    err accepted was 1.2E-05").
ERROR_BKW = re.compile(r"\*+\s*error\s*\*+", re.IGNORECASE)
ACEPTADO = re.compile(r"^\s*(.*?)\s+accepted was\s*(\S*)", re.IGNORECASE)
# Un cálculo completo imprime "THE ISP IS" dos veces: tras la cámara y, con el
# valor final, tras la expansión hasta la salida.
MIN_ISP = 2
NOMBRE_AVISOS = "avisos.csv"  # detalle de las iteraciones aceptadas

# Iteraciones de ISPBKW aceptadas sin alcanzar su tolerancia y umbral del
# residuo por encima del cual el resultado debe revisarse:
#   temp err:    balance de energía en la cámara, cal por peso de fórmula
#                (tolerancia de ISPBKW 0,01). 10 cal cambian el ISP < 1E-4.
#   energy err:  entropía en la expansión hasta la salida, cal/K por peso de
#                fórmula (tolerancia 0,1). 0,2 cal/K cambian el ISP ~0,1 %.
#   equil amaxe: suma de las variaciones de moles entre iteraciones del
#                equilibrio, mol por peso de fórmula.
# Las demás iteraciones (vgas, sys1 amoler, sol vol...) no tienen umbral y
# se marcan para revisar.
UMBRALES = {"temp err": 10.0, "energy err": 0.2, "equil amaxe": 1e-3}


def iteraciones_aceptadas(ruta):
    """Resume las iteraciones que ISPBKW ha aceptado fuera de tolerancia.

    Args:
        ruta: ruta del fichero .out.

    Returns:
        Lista de diccionarios, uno por tipo de iteración, con "iteracion"
        (p. ej. "temp err"), "veces", "residuo_max" (mayor valor absoluto;
        NaN si no se puede leer), "umbral" (de ``UMBRALES``; None si no hay)
        y "clasificacion" ("normal" si residuo_max <= umbral; si no,
        "revisar").
    """
    with open(ruta, encoding="utf-8", errors="replace") as f:
        lineas = f.read().splitlines()
    datos = {}
    for m in map(ACEPTADO.match, lineas):
        if not m:
            continue
        clave = " ".join(m.group(1).split())
        try:
            valor = abs(float(m.group(2)))
        except ValueError:
            valor = float("nan")
        veces, maximo = datos.get(clave, (0, 0.0))
        maximo = valor if valor != valor or valor > maximo else maximo
        datos[clave] = (veces + 1, maximo)
    resumen = []
    for clave, (veces, maximo) in datos.items():
        umbral = UMBRALES.get(clave)
        normal = umbral is not None and maximo <= umbral  # NaN -> revisar
        resumen.append({"iteracion": clave, "veces": veces,
                        "residuo_max": maximo, "umbral": umbral,
                        "clasificacion": "normal" if normal else "revisar"})
    return resumen


def diagnostico(ruta):
    """Revisa si un fichero .out de ISPBKW contiene un resultado válido.

    Args:
        ruta: ruta del fichero .out.

    Returns:
        Tupla (estado, mensaje):

        - ("error", texto) si hay la cabecera de error de ISPBKW (el texto es
          el mensaje que la sigue) o si "THE ISP IS" aparece menos de
          ``MIN_ISP`` veces (cálculo incompleto).
        - ("revisar", texto) si alguna iteración aceptada supera su umbral o
          no lo tiene (ver ``iteraciones_aceptadas``).
        - ("ok", texto) en otro caso. El texto resume las iteraciones
          aceptadas, p. ej. "temp err (1; 3.7E-02)"; vacío si no hay.

    Ejemplo:
        estado, mensaje = diagnostico("exp1.out")   # -> ("ok", "")
    """
    with open(ruta, encoding="utf-8", errors="replace") as f:
        lineas = f.read().splitlines()

    for n, l in enumerate(lineas):
        if ERROR_BKW.search(l):
            texto = next((t.strip() for t in lineas[n + 1:]
                          if t.strip() and not ERROR_BKW.search(t)), "")
            return "error", f"ISPBKW: {texto}" if texto else "ISPBKW: error"
    n_isp = sum(1 for l in lineas if ISP.search(l))
    if n_isp < MIN_ISP:
        return "error", (f"calculo incompleto ({n_isp} resultado(s) de ISP; "
                         f"se esperan {MIN_ISP})")
    aceptadas = iteraciones_aceptadas(ruta)
    texto = "; ".join(f"{a['iteracion']} ({a['veces']}; {a['residuo_max']:.1E})"
                      for a in aceptadas)
    if any(a["clasificacion"] == "revisar" for a in aceptadas):
        return "revisar", texto
    return "ok", texto


def extraer(ruta):
    """Lee un fichero .out y devuelve sus resultados finales.

    Toma la última aparición de cada valor y el último bloque de composición
    de productos del fichero.

    Args:
        ruta: ruta del fichero .out.

    Returns:
        Tupla (isp, temp, vgas, mgas, productos), con isp, temp, vgas y mgas
        como float y productos como lista de [especie, moles, entalpia_formacion],
        en el orden del fichero.

    Raises:
        SystemExit: con un mensaje, si faltan ISP, temperatura o gases, el
        bloque de composición o su cabecera.

    Ejemplo:
        isp, temp, vgas, mgas, productos = extraer("exp1.out")
        # productos -> [['h2o', 1.897162, -57107.0], ['co2', 1.102669, -93968.0], ...]
    """
    with open(ruta, encoding="utf-8", errors="replace") as f:
        lineas = f.read().splitlines()

    # Últimos valores de ISP, temperatura y gases
    isp = temp = vgas = mgas = None
    for l in lineas:
        m = ISP.search(l)
        if m:
            isp = float(m.group(1))
        m = TEMP.search(l)
        if m:
            temp = float(m.group(1))
        m = GAS.search(l)
        if m:
            vgas, mgas = float(m.group(1)), float(m.group(2))
    faltan = [n for n, v in (("ISP", isp), ("temperatura", temp),
                             ("volumen de gases", vgas), ("moles de gases", mgas))
              if v is None]
    if faltan:
        sys.exit(f"Faltan {', '.join(faltan)} en el fichero "
                 f"({os.path.getsize(ruta)} bytes).")

    # Última aparición del bloque de composición
    inicio = None
    for n, l in enumerate(lineas):
        if MARCA.lower() in l.lower():
            inicio = n
    if inicio is None:
        sys.exit("No se encuentra el bloque de composición de productos.")

    # Cabecera "Specie  No of Moles ..." (puede haber líneas en blanco antes)
    cabecera = next((n for n in range(inicio, len(lineas))
                     if lineas[n].strip().startswith("Specie")), None)
    if cabecera is None:
        sys.exit("No se encuentra la cabecera de especies.")

    # Cada especie ocupa dos líneas: la de la especie (nombre, moles,
    # coeficientes) y la de continuación (ICc, ..., Heat For, Covolume). Exigir
    # la segunda evita tomar por especie una línea cualquiera tras el bloque.
    productos = []
    k = cabecera + 1
    while k + 1 < len(lineas):
        m = PATRON.match(lineas[k])
        if not m or not lineas[k + 1].startswith("          "):
            break
        valores = [float(v) for v in lineas[k + 1].split()]
        productos.append([m.group(1).strip(), float(m.group(2)),
                          valores[-2]])  # penúltimo valor = Heat For
        k += 2
    return isp, temp, vgas, mgas, productos


def delta_entalpia(ruta):
    """Diferencia de entalpía de formación entre productos y reactivo, en J/kg.

    Calcula, con los datos del último cálculo del fichero .out:

        DH [cal] = suma(moles_i * Hf_i) - Hf_reactivo

    donde Hf_i es la entalpía de formación de cada producto (penúltimo valor
    de su segunda línea) y Hf_reactivo la de "The Heat of Formation at 0 deg K"
    (cal por peso fórmula). Los moles de los productos están referidos a un
    peso fórmula del reactivo ("The Molecular Weight"), así que:

        DH [J/kg] = DH [cal] * 4.184 / (peso_formula [g] / 1000)

    Un valor negativo indica que los productos tienen menor entalpía de
    formación que el reactivo (reacción exotérmica). Solo cuenta entalpías de
    formación; no incluye la entalpía sensible de los productos a la
    temperatura T.

    Args:
        ruta: ruta del fichero .out.

    Returns:
        Diferencia de entalpía (productos - reactivo) en J por kg de reactivo.

    Raises:
        SystemExit: si faltan el peso molecular o la entalpía de formación del
        reactivo, o los datos que exige ``extraer``.

    Ejemplo:
        dh = delta_entalpia("userdata/exp1.out")   # -> p. ej. -5.69e6 (J/kg)
    """
    with open(ruta, encoding="utf-8", errors="replace") as f:
        lineas = f.read().splitlines()

    peso = hf_reactivo = None
    for l in lineas:
        m = PESO_FORMULA.search(l)
        if m:
            peso = float(m.group(1))
        m = HF_REACTIVO.search(l)
        if m:
            hf_reactivo = float(m.group(1))
    if peso is None or hf_reactivo is None:
        sys.exit("Faltan el peso molecular o la entalpía de formación del "
                 "reactivo en el fichero.")

    productos = extraer(ruta)[4]
    hf_productos = sum(moles * hf for _, moles, hf in productos)
    return (hf_productos - hf_reactivo) * CAL_J / (peso / 1000.0)


def clave_natural(nombre):
    """Clave de ordenación alfabética y, dentro, numérica.

    Args:
        nombre: nombre a ordenar (sin sufijo).

    Returns:
        Lista de textos (en minúsculas) y enteros, apta para ``sorted(key=)``.

    Ejemplo:
        >>> sorted(["exp10", "exp2", "exp11", "exp1", "exp9"], key=clave_natural)
        ['exp1', 'exp2', 'exp9', 'exp10', 'exp11']
    """
    return [int(t) if t.isdigit() else t
            for t in re.split(r"(\d+)", nombre.lower())]


def leer_nombres(ruta):
    """Lee la tabla de correspondencia de nombres que escribe zzzcomps.py.

    Args:
        ruta: CSV con la columna "material" (exp1, exp2...) y columnas de
            identificación (Tipo, Compuesto, Formula...).

    Returns:
        Diccionario ordenado {material: {columna: valor}} sin la columna
        "material".

    Raises:
        SystemExit: si el fichero no existe, no tiene la columna "material"
        o repite algún nombre.
    """
    if not os.path.isfile(ruta):
        sys.exit(f"No existe la tabla de nombres: {ruta}")
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        filas = list(csv.DictReader(f))
    if not filas or "material" not in filas[0]:
        sys.exit(f"La tabla de nombres no tiene la columna 'material': {ruta}")
    tabla = {}
    for fila in filas:
        nombre = fila.pop("material")
        if nombre in tabla:
            sys.exit(f"Nombre repetido en la tabla de nombres: {nombre}")
        tabla[nombre] = fila
    return tabla


def procesar(ruta):
    """Revisa un .out y devuelve su fila de resultados.

    Args:
        ruta: ruta del fichero .out.

    Returns:
        Diccionario con "estado", "avisos" y, si el estado no es "error",
        "ISP", "Tc", "Te", "M", "Vgas", "Mgas" y <especie>_moles,
        <especie>_Hf.
    """
    estado, mensaje = diagnostico(ruta)
    fila = {"estado": estado, "avisos": mensaje}
    if estado == "error":
        return fila
    try:
        isp, temp, vgas, mgas, productos = extraer(ruta)
    except (SystemExit, ValueError, IndexError) as e:
        return {"estado": "error", "avisos": f"lectura: {e}"}
    with open(ruta, encoding="utf-8", errors="replace") as f:
        texto = f.read()
    temps = TEMP.findall(texto)
    pesos = PESO_FORMULA.findall(texto)
    fila.update({"ISP": isp, "Tc": float(temps[0]), "Te": temp,
                 "M": float(pesos[-1]) if pesos else "",
                 "Vgas": vgas, "Mgas": mgas})
    for especie, moles, hf in productos:
        nombre = especie.replace(" ", "_")
        fila[f"{nombre}_moles"] = moles
        fila[f"{nombre}_Hf"] = hf
    return fila


def main(argv=None):
    """Procesa todos los .out de una carpeta y guarda un único CSV.

    Argumentos de línea de comandos:
        RUTA           carpeta con los ficheros .out.
        SUBDIRECTORIO  (opcional) carpeta donde guardar el CSV; se crea si no
                       existe.
        --nombres      (opcional) tabla de correspondencia de zzzcomps.py.

    Sin tabla, los ficheros se ordenan con ``clave_natural``. Con tabla, las
    filas siguen su orden, se añaden sus columnas y los propelentes sin .out
    aparecen con estado "sin_out"; los .out que no están en la tabla se
    añaden al final con un aviso. Las columnas de productos son la unión de
    las de todos los ficheros; en las filas sin error, las ausentes valen 0.
    Al terminar se resume el número de materiales por estado.

    Ejemplos:
        python extraer_composicion.py C:\\datos\\propelentes
        python extraer_composicion.py userdata resultados --nombres zzzcomps_nombres.csv
    """
    parser = argparse.ArgumentParser(
        description="Extrae los resultados de los .out de ISPBKW a un CSV.")
    parser.add_argument("carpeta", help="carpeta con los ficheros .out")
    parser.add_argument("directorio", nargs="?", default="",
                        help="carpeta donde guardar el CSV")
    parser.add_argument("--nombres", default=None,
                        help="tabla de correspondencia (zzzcomps_nombres.csv)")
    parser.add_argument("--avisos", action="store_true",
                        help="escribir también el detalle de las iteraciones "
                             "aceptadas (avisos.csv)")
    args = parser.parse_args(argv)
    carpeta, directorio = args.carpeta, args.directorio

    if not os.path.isdir(carpeta):
        sys.exit(f"No existe la ruta: {carpeta}")
    ficheros = sorted((n for n in os.listdir(carpeta)
                       if n.lower().endswith(".out")),
                      key=lambda n: clave_natural(os.path.splitext(n)[0]))
    if not ficheros:
        sys.exit("No hay ficheros .out en la ruta.")

    tabla = leer_nombres(args.nombres) if args.nombres else {}
    resultados, detalle = {}, []
    for nombre_fichero in ficheros:
        material = os.path.splitext(nombre_fichero)[0]
        ruta = os.path.join(carpeta, nombre_fichero)
        fila = procesar(ruta)
        if fila["estado"] == "error":
            print(f"Error en {nombre_fichero}: {fila['avisos']}")
        resultados[material] = fila
        if args.avisos:
            detalle += [{"material": material, **a}
                        for a in iteraciones_aceptadas(ruta)]

    # Orden de las filas: el de la tabla y, al final, los .out que no estén
    columnas_id = list(next(iter(tabla.values()), {}))
    orden = list(tabla) + [m for m in resultados if m not in tabla]
    if tabla:
        for m in orden:
            if m not in tabla:
                print(f"Aviso: {m}.out no esta en la tabla de nombres")
            elif m not in resultados:
                print(f"Aviso: {m} no tiene fichero .out")

    fijas = ["ISP", "Tc", "Te", "M", "Vgas", "Mgas"]
    filas, productos = [], []
    for m in orden:
        fila = {"material": m, **tabla.get(m, {}),
                **resultados.get(m, {"estado": "sin_out", "avisos": ""})}
        productos += [c for c in fila if c.endswith(("_moles", "_Hf"))
                      and c not in productos]
        filas.append(fila)
    for fila in filas:  # productos ausentes: 0 solo en filas con resultados
        if fila["estado"] in ("ok", "revisar"):
            for c in productos:
                fila.setdefault(c, 0)
    columnas = ["material"] + columnas_id + ["estado", "avisos"] + fijas \
        + productos

    if directorio:
        os.makedirs(directorio, exist_ok=True)
    salida = os.path.join(directorio, NOMBRE_CSV)
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas, restval="")
        w.writeheader()
        w.writerows(filas)
    if args.avisos:
        campos = ["material", "iteracion", "veces", "residuo_max", "umbral",
                  "clasificacion"]
        with open(os.path.join(directorio, NOMBRE_AVISOS), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            w.writerows(detalle)
    cuenta = collections.Counter(f["estado"] for f in filas)
    resumen = ", ".join(f"{k}: {cuenta[k]}" for k in
                        ("ok", "revisar", "error", "sin_out") if cuenta[k])
    print(f"Guardado: {salida} ({len(filas)} materiales; {resumen})")


if __name__ == "__main__":
    main()
