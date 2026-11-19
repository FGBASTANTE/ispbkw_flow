r"""Extrae los resultados finales de los ficheros .out del cálculo BKW (Fortran)
y los guarda en un único CSV.

De cada fichero .out toma:
    - ISP:  último valor de "THE ISP IS".
    - T:    último valor de "The Temperature is" (K).
    - Vgas: "The Volume of the Gas is" (cc/mole), última aparición.
    - Mgas: "Moles of Gas" de esa misma línea.
    - Por cada producto del último bloque "Composition of the Propellant
      Products": moles (<especie>_moles) y entalpía estándar de formación
      (<especie>_Hf), que es el penúltimo valor de la segunda línea de la
      especie.

Los ficheros se procesan en orden alfabético y, dentro, numérico
(exp1, exp2, exp9, exp10, exp11). El CSV tiene una fila por material, con el
nombre del .out sin sufijo como índice (columna "material"). Cada producto
nuevo que aparece en un fichero añade sus columnas; en los materiales que no
lo contienen se rellenan con 0.

Uso (cmd de Windows):
    python extraer_composicion.py RUTA [SUBDIRECTORIO]

    RUTA           carpeta con los ficheros .out
    SUBDIRECTORIO  opcional; carpeta donde guardar el CSV (se crea si no
                   existe). Sin indicarlo, se guarda en el directorio actual.

Ejemplos:
    python extraer_composicion.py C:\datos\propelentes
    python extraer_composicion.py C:\datos\propelentes resultados
    python extraer_composicion.py . salida\csv

Resultado (resultados.csv), por ejemplo con exp1.out y exp2.out:
    material,ISP,T,Vgas,Mgas,h2o_moles,h2o_Hf,...
    exp1,268.770812988,1660.04907227,136314.0,9.00025,1.897162,-57107.0,...
    exp2,268.770812988,1660.04907227,136314.0,9.00025,1.897162,-57107.0,...

Uso desde Python (diferencia de entalpía productos - reactivo, en J/kg):
    from extraer_composicion import delta_entalpia
    dh = delta_entalpia("userdata/exp1.out")

Códigos de salida: 0 correcto; distinto de 0 si la ruta no existe, no hay
ficheros .out o el uso es incorrecto. Los .out sin los valores necesarios se
omiten con un aviso y no detienen el proceso.
"""

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


def main():
    """Procesa todos los .out de una carpeta y guarda un único CSV.

    Argumentos de línea de comandos:
        RUTA           carpeta con los ficheros .out.
        SUBDIRECTORIO  (opcional) carpeta donde guardar el CSV; se crea si no
                       existe.

    Los ficheros se ordenan con ``clave_natural``. Las columnas son la unión
    de los productos de todos los ficheros (las ausentes se rellenan con 0).
    Un .out sin los valores necesarios se omite con un aviso.

    Ejemplos:
        python extraer_composicion.py C:\\datos\\propelentes
        python extraer_composicion.py C:\\datos\\propelentes resultados
    """
    if len(sys.argv) not in (2, 3):
        sys.exit("Uso: python extraer_composicion.py ruta_ficheros_out "
                 "[subdirectorio_salida]")
    carpeta = sys.argv[1]
    directorio = sys.argv[2] if len(sys.argv) == 3 else ""

    if not os.path.isdir(carpeta):
        sys.exit(f"No existe la ruta: {carpeta}")
    ficheros = sorted((n for n in os.listdir(carpeta)
                       if n.lower().endswith(".out")),
                      key=lambda n: clave_natural(os.path.splitext(n)[0]))
    if not ficheros:
        sys.exit("No hay ficheros .out en la ruta.")

    columnas = ["material", "ISP", "T", "Vgas", "Mgas"]
    filas = []
    for nombre_fichero in ficheros:
        material = os.path.splitext(nombre_fichero)[0]
        try:
            isp, temp, vgas, mgas, productos = extraer(
                os.path.join(carpeta, nombre_fichero))
        except SystemExit as e:
            print(f"Omitido {nombre_fichero}: {e}")
            continue

        fila = {"material": material, "ISP": isp, "T": temp,
                "Vgas": vgas, "Mgas": mgas}
        for especie, moles, hf in productos:
            nombre = especie.replace(" ", "_")
            fila[f"{nombre}_moles"] = moles
            fila[f"{nombre}_Hf"] = hf
        columnas += [c for c in fila if c not in columnas]
        filas.append(fila)

    if not filas:
        sys.exit("No se ha extraído ningún material; no se escribe el CSV.")

    if directorio:
        os.makedirs(directorio, exist_ok=True)
    salida = os.path.join(directorio, NOMBRE_CSV)
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas, restval=0)
        w.writeheader()
        w.writerows(filas)
    print(f"Guardado: {salida} ({len(filas)} materiales)")


if __name__ == "__main__":
    main()
