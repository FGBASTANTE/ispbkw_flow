"""Calcula con ISPBKW el impulso específico de los propelentes de un CSV.

Encadena todo el proceso:

1. Lee y valida el CSV (columnas ``Formula`` y ``DeltaH`` en kcal por
   mol de la fórmula escrita, a 298,15 K).
2. Desglosa cada fórmula en elementos y calcula su masa.
3. Calcula ``eo_ISPBKW`` (``eo_0k.py``).
4. Escribe ``zzzcomps`` y ``zzzcomps_nombres.csv`` en la carpeta de
   trabajo (``zzzcomps.py``).
5. Ejecuta ``procesar_ispbkw.ps1``, que genera con USERBKW los ficheros
   de entrada (``bkwdata``) y con ISPBKW los ``.out``.
6. Extrae los resultados (``extraer_composicion.py``).
7. Une los resultados a los datos de entrada por nombre (``expN``) y
   escribe las salidas (ver ``escribir_resultados``): un resumen claro
   (nombre, fórmula, masa, entalpías, ISP en s y km/s, temperaturas de
   cámara y salida y estado), la composición de los productos, la tabla
   de especies y las iteraciones aceptadas, en CSV y en un libro Excel.
8. Si todo termina sin error, mueve a ``files_HHMMSS_AAAAMMDD`` (hora y
   fecha de inicio) lo que el proceso ha creado o modificado en la
   carpeta de trabajo, y restaura ``zzzcomps`` y ``zzzdecks`` como
   estaban (ver ``recoger_ficheros``). Si hay un error, todo queda en
   su sitio para poder seguir con ``--continuar``; el estado inicial
   de la carpeta se guarda en ``calcular_isp.estado`` para que la
   recogida final sea la misma aunque el proceso se complete en varias
   ejecuciones.

La carpeta de trabajo debe contener ``userbkw.exe``, ``abispbkw.exe``,
``zzztherc`` y ``zzzsoleq``. Si faltan ``procesar_ispbkw.ps1`` o
``plantilla_userbkw.txt``, se copian desde la carpeta de este script.

Las columnas de entrada se llaman por defecto ``Compuesto``,
``Formula`` y ``DeltaH``; con ``--col-compuesto``, ``--col-formula`` y
``--col-deltah`` se indican otros nombres, que se conservan en el CSV
final.

Uso (cmd de Windows)::

    python calcular_isp.py datos.csv --trabajo C:\\bkw
    python calcular_isp.py datos.csv --trabajo C:\\bkw ^
        --col-compuesto Nombre --col-formula Form --col-deltah Hf
    python calcular_isp.py datos.csv --trabajo C:\\bkw --continuar
    python calcular_isp.py datos.csv --trabajo C:\\bkw --preparar
"""

__all__ = ['G0', 'FICHEROS_BKW', 'RESERVADAS', 'es_reservada',
           'renombrar_reservadas', 'comprobar_modulos', 'asignar_columnas',
           'validar', 'estado_inicial', 'recoger_ficheros',
           'tablas_resultados', 'escribir_resultados',
           'calcular_isp', 'main']

import argparse
import filecmp
import inspect
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

import eo_0k
import extraer_composicion
import zzzcomps
from eo_0k import anadir_eo_0k
from formula_quimica import MASA, masa_formula, parse_formula
from zzzcomps import escribir_zzzcomps

G0 = 9.80665  # Gravedad estándar, m/s2.
AQUI = Path(__file__).resolve().parent
# Ficheros de Mader que deben estar en la carpeta de trabajo.
FICHEROS_BKW = ('userbkw.exe', 'abispbkw.exe', 'zzztherc', 'zzzsoleq')
# Ficheros de este repositorio que se copian si faltan.
FICHEROS_REPO = ('procesar_ispbkw.ps1', 'plantilla_userbkw.txt')
# Productos del proceso en la carpeta de trabajo que se recogen al final
# aunque ya existieran al empezar (p. ej. de una ejecución interrumpida).
PRODUCTOS = ('userdata', 'resultados', 'bkwdata', 'isp.out',
             'datos_eo0K.csv', 'zzzcomps_nombres.csv')
# Ficheros que el proceso modifica y que se restauran al final; la
# versión usada se guarda en la carpeta de la ejecución.
RESTAURAR = ('zzzcomps', 'zzzdecks')
ANTERIOR = '.anterior'  # sufijo de la copia de seguridad de RESTAURAR
ESTADO = 'calcular_isp.estado'  # entradas de la carpeta al empezar
TOL_MEZCLA = 1.0  # g: tolerancia de la masa de una mezcla respecto a 100 g.
MOLES_MIN = 1.0000001e-8  # mol: valor mínimo de ISPBKW (especie ausente)
MAX_ELEMENTOS = 10  # elementos por fórmula admitidos por USERBKW e ISPBKW
# Columnas que añade el proceso. Además, las de los elementos (at_<e>) y
# las de los productos (<especie>_moles, <especie>_Hf).
RESERVADAS = ('material', 'M_g_mol', 'eo_ISPBKW', 'DeltaH_0K_est',
              'origen_entalpia', 'entalpia_cal', 'densidad', 'estado',
              'avisos', 'ISP', 'ISP_s', 'ISP_km_s', 'T', 'Vgas', 'Mgas')
SUFIJO_ENTRADA = '_entrada'


def es_reservada(columna):
    """Indica si el proceso añade una columna con ese nombre.

    Args:
        columna (str): Nombre de una columna del CSV de entrada.

    Returns:
        bool: ``True`` si coincide con una columna de resultados.

    Example:
        >>> es_reservada('T'), es_reservada('h2o_moles'), es_reservada('Q')
        (True, True, False)
    """
    columna = str(columna)
    return (columna in RESERVADAS or columna.startswith('at_')
            or columna.endswith(('_moles', '_Hf')))


def comprobar_modulos():
    """Comprueba que los módulos importados son las versiones actuales.

    Evita que, tras horas de cálculo, el proceso falle al final por una
    copia antigua de un módulo en la carpeta de los scripts.

    Raises:
        RuntimeError: Si algún módulo es de una versión anterior; el
            mensaje indica su ruta.
    """
    requisitos = (
        (extraer_composicion, 'diagnostico',
         'argv' in inspect.signature(extraer_composicion.main).parameters),
        (zzzcomps, 'tabla',
         'tabla' in inspect.signature(escribir_zzzcomps).parameters),
        (eo_0k, 'eo_ispbkw', hasattr(eo_0k, 'eo_ispbkw')),
    )
    antiguos = [m.__file__ for m, _, ok in requisitos if not ok]
    if not hasattr(extraer_composicion, 'diagnostico'):
        antiguos.append(extraer_composicion.__file__)
    if antiguos:
        raise RuntimeError('versión anterior de: '
                           + ', '.join(sorted(set(antiguos)))
                           + '. Sustitúyala por la del repositorio.')


def asignar_columnas(df, compuesto='Compuesto', formula='Formula',
                     deltah='DeltaH'):
    """Da a las columnas de datos los nombres internos del proceso.

    Los módulos usan ``Compuesto``, ``Formula`` y ``DeltaH``. Las
    columnas indicadas se renombran a esos nombres; si el fichero tiene
    además otra columna con alguno de ellos, esa se renombra con el
    sufijo ``_entrada`` para no confundirla.

    Args:
        df (pandas.DataFrame): Datos de entrada.
        compuesto (str | None): Columna con el nombre del compuesto.
            Opcional: si es la de por defecto y no existe, se ignora.
        formula (str): Columna con la fórmula química.
        deltah (str): Columna con la entalpía de formación, kcal por
            mol de la fórmula escrita, 298,15 K.

    Returns:
        tuple[pandas.DataFrame, dict[str, str]]: Datos con los nombres
        internos y correspondencia ``{nombre interno: nombre
        original}`` para restaurarlos en el resultado.

    Raises:
        ValueError: Si falta alguna de las columnas indicadas (la de
            compuesto solo si no es la de por defecto) o si se indica
            la misma columna para dos datos.
    """
    pedidas = {'Formula': formula, 'DeltaH': deltah}
    if compuesto and (compuesto in df.columns or compuesto != 'Compuesto'):
        pedidas['Compuesto'] = compuesto
    faltan = [f'{v} ({k})' for k, v in pedidas.items() if v not in df.columns]
    if faltan:
        raise ValueError(f'faltan columnas: {faltan}; columnas del '
                         f'fichero: {list(df.columns)}')
    if len(set(pedidas.values())) != len(pedidas):
        raise ValueError(f'la misma columna para dos datos: {pedidas}')
    # Columnas que ya se llaman como un nombre interno sin serlo
    usados, cambios = set(df.columns), {}
    for interno, original in pedidas.items():
        if interno in df.columns and interno != original:
            nuevo, k = f'{interno}{SUFIJO_ENTRADA}', 2
            while nuevo in usados:
                nuevo, k = f'{interno}{SUFIJO_ENTRADA}{k}', k + 1
            cambios[interno] = nuevo
            usados.add(nuevo)
            dato = {'Formula': 'la fórmula', 'DeltaH': 'la entalpía',
                    'Compuesto': 'el compuesto'}[interno]
            print(f'Aviso: para {dato} se usa la columna {original}; la '
                  f'columna {interno} se renombra a {nuevo}')
    df = df.rename(columns=cambios)
    df = df.rename(columns={v: k for k, v in pedidas.items()})
    return df, {k: v for k, v in pedidas.items() if k != v}


def renombrar_reservadas(df):
    """Renombra las columnas de entrada que coinciden con las de resultados.

    Sin este paso, el valor de la entrada sustituiría al calculado (p.
    ej. una columna ``T``) o el proceso fallaría al final (``material``).
    Se añade el sufijo ``_entrada`` (y un número si ya existe).

    Args:
        df (pandas.DataFrame): Datos de entrada.

    Returns:
        tuple[pandas.DataFrame, dict[str, str]]: Datos con las columnas
        renombradas y correspondencia ``{nombre original: nombre
        nuevo}`` (vacía si no hay coincidencias).
    """
    cambios, usados = {}, set(df.columns)
    for c in df.columns:
        if es_reservada(c):
            nuevo, k = f'{c}{SUFIJO_ENTRADA}', 2
            # Un nombre terminado en _entrada no coincide con at_<e> (los
            # elementos son de 1-2 letras) ni con <especie>_moles/_Hf.
            while nuevo in usados or nuevo in RESERVADAS:
                nuevo, k = f'{c}{SUFIJO_ENTRADA}{k}', k + 1
            cambios[c] = nuevo
            usados.add(nuevo)
    for viejo, nuevo in cambios.items():
        print(f'Aviso: la columna de entrada {viejo} coincide con una de '
              f'resultados; se renombra a {nuevo}')
    return df.rename(columns=cambios), cambios


def validar(df):
    """Comprueba el CSV de entrada y añade el desglose de elementos.

    Args:
        df (pandas.DataFrame): Datos con ``Formula`` y ``DeltaH``.

    Returns:
        pandas.DataFrame: Copia de ``df`` con ``M_g_mol`` (masa de la
        fórmula) y ``at_<elemento>`` (átomos por fórmula) para cada
        elemento presente.

    Raises:
        ValueError: Si faltan columnas, hay valores vacíos o no
            numéricos, o alguna fórmula no es válida, contiene
            elementos no admitidos o más de ``MAX_ELEMENTOS``. El
            mensaje indica las filas (1 = primera fila de datos).
    """
    faltan = {'Formula', 'DeltaH'} - set(df.columns)
    if faltan:
        raise ValueError(f'faltan columnas: {sorted(faltan)}')
    errores = []
    comps = []
    for i, (f, dh) in enumerate(zip(df['Formula'], df['DeltaH']), 1):
        try:
            if pd.isna(f) or pd.isna(pd.to_numeric(dh, errors='coerce')):
                raise ValueError('Formula o DeltaH vacíos o no numéricos')
            comp = parse_formula(f)
            masa_formula(comp)  # comprueba los elementos
            if len(comp) > MAX_ELEMENTOS:
                raise ValueError(f'{len(comp)} elementos; USERBKW e ISPBKW '
                                 f'admiten {MAX_ELEMENTOS}')
            comps.append(comp)
        except ValueError as e:
            errores.append(f'fila {i} ({f}): {e}')
            comps.append({})
    if errores:
        raise ValueError('datos no válidos:\n  ' + '\n  '.join(errores))
    df = df.copy()
    df['M_g_mol'] = [round(masa_formula(c), 5) for c in comps]
    for e in MASA:
        if any(e in c for c in comps):
            df[f'at_{e}'] = [c.get(e, 0.0) for c in comps]
    # Mezclas (coeficientes no enteros): fórmula referida a 100 g
    for i, (c, m) in enumerate(zip(comps, df['M_g_mol']), 1):
        if any(v != int(v) for v in c.values()) and abs(m - 100) > TOL_MEZCLA:
            print(f'Aviso: fila {i} ({df["Formula"].iloc[i - 1]}) parece '
                  f'una mezcla y su masa es {m:.3f} g, no 100 g')
    return df


def estado_inicial(trabajo):
    """Registra el estado inicial de la carpeta de trabajo.

    Guarda en ``ESTADO`` los nombres de sus entradas y copia
    ``zzzcomps`` y ``zzzdecks`` como ``<nombre>.anterior``. Si ``ESTADO``
    ya existe (ejecución anterior sin terminar), se usa el registrado
    entonces y no se rehacen las copias.

    Args:
        trabajo (pathlib.Path): Carpeta de trabajo.

    Returns:
        set[str]: Nombres de las entradas al empezar el proceso.
    """
    estado = trabajo / ESTADO
    if estado.exists():
        previos = set(estado.read_text(encoding='utf-8').splitlines())
        print(f'Estado inicial de la carpeta: el registrado en {ESTADO} '
              f'(ejecución anterior sin terminar)')
    else:
        previos = {r.name for r in trabajo.iterdir()}
        estado.write_text('\n'.join(sorted(previos)), encoding='utf-8')
    for nombre in RESTAURAR:
        ruta, copia = trabajo / nombre, trabajo / (nombre + ANTERIOR)
        if nombre in previos and ruta.exists() and not copia.exists():
            shutil.copy2(ruta, copia)
    return previos


def recoger_ficheros(trabajo, previos, marca):
    """Recoge en una subcarpeta lo creado o modificado por el proceso.

    Mueve a ``trabajo/files_<marca>``:

    * las entradas (ficheros y carpetas) que no existían al empezar,
      p. ej. ``userdata_<fecha>`` archivadas, salvo los ficheros de
      configuración de ``FICHEROS_REPO`` (``procesar_ispbkw.ps1`` y
      ``plantilla_userbkw.txt``), que se quedan en la carpeta de trabajo aunque se
      hayan copiado en esta ejecución;
    * los productos de ``PRODUCTOS`` aunque existieran al empezar;
    * el ``CSV`` final si se escribió en la carpeta de trabajo.

    ``zzzcomps`` y ``zzzdecks`` se mueven a la subcarpeta y, si existían
    al empezar, se restauran desde ``<nombre>.anterior``. Por último se
    elimina ``ESTADO``.

    Args:
        trabajo (pathlib.Path): Carpeta de trabajo.
        previos (set[str]): Nombres de las entradas al empezar (ver
            ``estado_inicial``).
        marca (str): Hora y fecha de inicio, ``HHMMSS_AAAAMMDD``.

    Returns:
        pathlib.Path: Subcarpeta creada.
    """
    destino = trabajo / f'files_{marca}'
    destino.mkdir()
    for nombre in RESTAURAR:
        ruta, copia = trabajo / nombre, trabajo / (nombre + ANTERIOR)
        if ruta.exists():
            shutil.move(str(ruta), str(destino / nombre))
        if copia.exists():
            shutil.move(str(copia), str(ruta))
    # Los ficheros de configuración (procesar_ispbkw.ps1, plantilla_userbkw.txt) se
    # quedan aunque se hayan copiado en esta ejecución.
    internos = (set(RESTAURAR) | {n + ANTERIOR for n in RESTAURAR}
                | {ESTADO} | set(FICHEROS_REPO))
    for ruta in sorted(trabajo.iterdir()):
        if ruta == destino or ruta.name in internos:
            continue
        if ruta.name not in previos or ruta.name in PRODUCTOS:
            shutil.move(str(ruta), str(destino / ruta.name))
    (trabajo / ESTADO).unlink(missing_ok=True)
    return destino


def tablas_resultados(datos, res, avisos=None):
    """Organiza los resultados en tablas claras.

    Args:
        datos (pandas.DataFrame): Datos de entrada procesados, con
            ``material``, ``Formula``, ``DeltaH``, ``M_g_mol``,
            ``eo_ISPBKW`` y, si existe, ``Compuesto``.
        res (pandas.DataFrame): ``resultados.csv`` del extractor.
        avisos (pandas.DataFrame | None): ``avisos.csv`` del extractor.

    Returns:
        dict[str, pandas.DataFrame]: Tablas ``Resumen`` (una fila por
        propelente: nombre, fórmula, masa, ``DeltaH`` a 298,15 K y
        ``eo_ISPBKW`` en kcal/mol, ISP en s y km/s, temperaturas de
        cámara y salida, estado y observaciones), ``Productos``
        (composición en la salida, mol por kg de propelente; las
        especies con el mínimo de ISPBKW, 1E-8 mol, valen 0),
        ``Especies`` (entalpía de formación a 0 K de cada producto,
        cal/mol) y ``Avisos`` (iteraciones aceptadas, ver
        ``extraer_composicion.iteraciones_aceptadas``).
    """
    ident = ['material'] + (['Compuesto'] if 'Compuesto' in datos else []) \
        + ['Formula']
    base = datos[ident + ['M_g_mol', 'DeltaH', 'eo_ISPBKW']]
    res = res[['material'] + [c for c in res.columns if c not in base]]
    r = base.merge(res, on='material', how='left')
    resumen = r[ident].copy()
    resumen['M_g_mol'] = r['M_g_mol'].round(3)
    resumen['DeltaH_298K_kcal_mol'] = r['DeltaH'].round(3)
    resumen['eo_ISPBKW_kcal_mol'] = (r['eo_ISPBKW'] / 1e3).round(3)
    resumen['Isp_s'] = r['ISP'].round(2)
    resumen['Isp_km_s'] = (r['ISP'] * G0 / 1e3).round(4)
    resumen['Tc_K'] = r['Tc'].round(1)
    resumen['Te_K'] = r['Te'].round(1)
    resumen['estado'] = r['estado']
    resumen['observaciones'] = r['avisos'].where(r['estado'] != 'ok', '')

    especies = [c[:-6] for c in res.columns if c.endswith('_moles')]
    productos = r[ident].copy()
    kg = 1e3 / r['M']  # moles por fórmula -> mol/kg
    productos['gas_mol_kg'] = r['Mgas'] * kg
    for e in especies:
        moles = r[f'{e}_moles'].where(r[f'{e}_moles'] > MOLES_MIN, 0.0)
        productos[f'{e}_mol_kg'] = moles.where(r['ISP'].notna()) * kg

    tabla_hf = pd.DataFrame({
        'especie': [e.replace('_', ' ') for e in especies],
        'Hf_0K_cal_mol': [res[f'{e}_Hf'].dropna().iloc[0]
                          if res[f'{e}_Hf'].notna().any() else None
                          for e in especies]})
    if avisos is None or avisos.empty:
        avisos = pd.DataFrame(columns=['material', 'iteracion', 'veces',
                                       'residuo_max', 'umbral',
                                       'clasificacion'])
    avisos = datos[ident].merge(avisos, on='material', how='inner')
    return {'Resumen': resumen, 'Productos': productos,
            'Especies': tabla_hf, 'Avisos': avisos}


def escribir_resultados(tablas, base, entrada=None):
    """Escribe las tablas de resultados en CSV y en un libro Excel.

    Args:
        tablas (dict[str, pandas.DataFrame]): Resultado de
            ``tablas_resultados``.
        base (pathlib.Path): Ruta sin extensión de las salidas.
        entrada (pandas.DataFrame | None): Datos de entrada originales,
            que se añaden al libro en la hoja ``Entrada``.

    Returns:
        list[pathlib.Path]: Ficheros escritos: ``<base>.csv`` (resumen),
        ``<base>_productos.csv``, ``<base>_especies.csv``,
        ``<base>_avisos.csv`` y ``<base>.xlsx`` (este, solo si está
        instalado openpyxl).
    """
    rutas = []
    for nombre, tabla in tablas.items():
        ruta = base.with_name(base.name + ('' if nombre == 'Resumen'
                                           else f'_{nombre.lower()}')
                              + '.csv')
        tabla.to_csv(ruta, index=False, float_format='%.6g')
        rutas.append(ruta)
    try:
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ImportError:
        print('Aviso: openpyxl no está instalado; no se escribe el libro '
              'Excel (pip install openpyxl)')
        return rutas
    formatos = {'M_g_mol': '0.000', 'DeltaH_298K_kcal_mol': '0.000',
                'eo_ISPBKW_kcal_mol': '0.000', 'Isp_s': '0.00',
                'Isp_km_s': '0.0000', 'Tc_K': '0.0', 'Te_K': '0.0'}
    hojas = dict(tablas)
    if entrada is not None:
        hojas['Entrada'] = entrada
    ruta = base.with_suffix('.xlsx')
    with pd.ExcelWriter(ruta, engine='openpyxl') as libro:
        for nombre, tabla in hojas.items():
            tabla.to_excel(libro, sheet_name=nombre, index=False)
            hoja = libro.sheets[nombre]
            hoja.freeze_panes = 'A2'
            for j, col in enumerate(tabla.columns, 1):
                letra = get_column_letter(j)
                hoja[f'{letra}1'].font = Font(bold=True)
                ancho = max([len(str(col))] + [len(str(v)) for v in
                                               tabla[col].head(200)])
                hoja.column_dimensions[letra].width = min(ancho + 2, 45)
                if col in formatos:
                    for celda in hoja[letra][1:]:
                        celda.number_format = formatos[col]
    rutas.append(ruta)
    return rutas


def calcular_isp(entrada, trabajo, salida=None, columna_fijo=None,
                 valor_fijo=1.0, continuar=False, preparar=False,
                 powershell='powershell', col_compuesto='Compuesto',
                 col_formula='Formula', col_deltah='DeltaH'):
    """Calcula con ISPBKW el impulso de los propelentes de un CSV.

    Args:
        entrada (str | os.PathLike): CSV con ``Formula`` y ``DeltaH``
            (kcal por mol de la fórmula escrita, 298,15 K). Las demás
            columnas se conservan en el resultado; las que coinciden
            con una de resultados se renombran con el sufijo
            ``_entrada`` (ver ``renombrar_reservadas``).
        trabajo (str | os.PathLike): Carpeta con los programas de Mader.
        salida (str | os.PathLike | None): Ruta base de las salidas (se
            ignora la extensión). Por defecto, ``<entrada>_ISPBKW`` junto
            a la entrada (ver ``escribir_resultados``).
        columna_fijo (str | None): Columna con la densidad (g/cm3) para
            el segundo campo de ``zzzcomps``. ``None`` usa
            ``valor_fijo``.
        valor_fijo (float): Densidad común si no hay ``columna_fijo``.
        continuar (bool): Si es ``True``, no archiva ``userdata`` y solo
            calcula los casos que falten (exige el mismo ``zzzcomps``).
            Si es ``False``, la carpeta ``userdata`` anterior se
            archiva y se calcula todo.
        preparar (bool): Si es ``True``, se detiene tras escribir
            ``zzzcomps`` (no ejecuta los programas de Mader); los
            ficheros quedan en la carpeta de trabajo.
        powershell (str): Ejecutable de PowerShell.
        col_compuesto (str): Columna con el nombre del compuesto
            (opcional; ver ``asignar_columnas``).
        col_formula (str): Columna con la fórmula química.
        col_deltah (str): Columna con la entalpía de formación (kcal
            por mol de la fórmula escrita, 298,15 K).

    Returns:
        pandas.DataFrame | None: Resultado final (ver ``main``), o
        ``None`` si ``preparar`` es ``True``.

    Raises:
        FileNotFoundError: Si no existen la entrada, la carpeta de
            trabajo o los ficheros de Mader.
        ValueError: Si los datos de entrada no son válidos.
        RuntimeError: Si falla ``procesar_ispbkw.ps1`` o la extracción.
    """
    comprobar_modulos()
    marca = datetime.now().strftime('%H%M%S_%Y%m%d')
    entrada, trabajo = Path(entrada), Path(trabajo).resolve()
    base = (Path(salida).with_suffix('') if salida
            else entrada.with_name(f'{entrada.stem}_ISPBKW'))

    # 1-2. Lectura, columnas con nombres de resultados, validación y
    # desglose de elementos
    datos, originales = asignar_columnas(pd.read_csv(entrada), col_compuesto,
                                         col_formula, col_deltah)
    if columna_fijo in originales.values():
        raise ValueError(f'--columna-fijo {columna_fijo} es una columna de '
                         f'datos (compuesto, fórmula o entalpía)')
    datos, cambios = renombrar_reservadas(datos)
    columna_fijo = cambios.get(columna_fijo, columna_fijo)
    datos = validar(datos)
    print(f'{len(datos)} propelentes leídos de {entrada}')

    # Comprobar la carpeta de trabajo antes de escribir nada en ella
    if not trabajo.is_dir():
        raise FileNotFoundError(f'no existe la carpeta de trabajo {trabajo}')
    if not preparar:
        faltan = [f for f in FICHEROS_BKW if not (trabajo / f).exists()]
        if faltan:
            raise FileNotFoundError(f'faltan en {trabajo}: {faltan}')
    previos = estado_inicial(trabajo)
    for f in FICHEROS_REPO:
        if not (trabajo / f).exists():
            shutil.copy2(AQUI / f, trabajo / f)
            print(f'Copiado {f} a {trabajo}')
        elif (AQUI / f).exists() and not filecmp.cmp(AQUI / f, trabajo / f,
                                                      shallow=False):
            print(f'Aviso: {trabajo / f} es distinto de la versión del '
                  f'repositorio ({AQUI / f}); se usa el de la carpeta de '
                  f'trabajo')

    # 3. eo_ISPBKW (se guarda una copia de los datos usados)
    ruta_eo = trabajo / 'datos_eo0K.csv'
    datos.to_csv(ruta_eo, index=False)
    datos = anadir_eo_0k(ruta_eo)
    datos.to_csv(ruta_eo, index=False)

    # 4. zzzcomps y tabla de nombres (el zzzcomps inicial está copiado
    # en zzzcomps.anterior, ver estado_inicial)
    zzz, tabla = trabajo / 'zzzcomps', trabajo / 'zzzcomps_nombres.csv'
    n = escribir_zzzcomps(ruta_eo, zzz, columna='eo_ISPBKW',
                          columna_fijo=columna_fijo, valor_fijo=valor_fijo,
                          tabla=tabla)
    print(f'{n} componentes escritos en {zzz}')
    if preparar:
        return None

    # 5. USERBKW e ISPBKW
    orden = [powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-File', str(trabajo / 'procesar_ispbkw.ps1')]
    if not continuar:
        orden.append('-Reiniciar')
    if subprocess.run(orden, cwd=trabajo).returncode != 0:
        raise RuntimeError('procesar_ispbkw.ps1 ha terminado con error; '
                           'los ficheros quedan en la carpeta de trabajo '
                           '(se puede seguir con --continuar)')

    # 6. Extracción de resultados
    carpeta_csv = trabajo / 'resultados'
    try:
        extraer_composicion.main([str(trabajo / 'userdata'),
                                  str(carpeta_csv), '--nombres', str(tabla),
                                  '--avisos'])
    except SystemExit as e:
        if e.code not in (None, 0):
            raise RuntimeError(f'extracción: {e.code}') from None
    res = pd.read_csv(carpeta_csv / extraer_composicion.NOMBRE_CSV)
    ruta_avisos = carpeta_csv / extraer_composicion.NOMBRE_AVISOS
    avisos = pd.read_csv(ruta_avisos) if ruta_avisos.exists() else None

    # 7. Tablas de resultados (unión por nombre) y salidas
    materiales = pd.read_csv(tabla)['material']
    datos.insert(0, 'material', materiales)
    tablas = tablas_resultados(datos, res, avisos)
    original = pd.read_csv(entrada)
    original.insert(0, 'material' if 'material' not in original
                    else 'material_ISPBKW', materiales)
    rutas = escribir_resultados(tablas, base, original)

    # 8. Recoger lo creado o modificado en la carpeta de trabajo
    destino = recoger_ficheros(trabajo, previos, marca)
    rutas = [destino / r.name if r.resolve().parent == trabajo else r
             for r in rutas]
    print(f'Ficheros del proceso movidos a {destino}')

    resumen = tablas['Resumen']
    cuenta = resumen['estado'].value_counts()
    print('Resultados (' + ', '.join(f'{k}: {v}' for k, v in cuenta.items())
          + '):\n  ' + '\n  '.join(str(r) for r in rutas))
    for _, f in resumen[resumen['estado'] != 'ok'].iterrows():
        nombre = f.get('Compuesto', f['Formula'])
        print(f"  {f['material']} {nombre}: {f['estado']} "
              f"{f['observaciones']}")
    return resumen


def main(argv=None):
    """Interfaz de línea de comandos de ``calcular_isp``.

    Salidas (ver ``escribir_resultados``): ``<base>.csv`` (resumen),
    ``<base>_productos.csv``, ``<base>_especies.csv``,
    ``<base>_avisos.csv`` y ``<base>.xlsx`` con esas tablas y la hoja
    ``Entrada`` (datos originales y ``material``).

    Args:
        argv (list[str] | None): Argumentos; ``None`` usa
            ``sys.argv[1:]``.

    Returns:
        int: 0 si termina sin error; 1 en otro caso.
    """
    p = argparse.ArgumentParser(
        description='Impulso específico con ISPBKW a partir de un CSV.')
    p.add_argument('entrada', help='CSV con Formula y DeltaH (kcal/mol)')
    p.add_argument('--trabajo', default='.',
                   help='carpeta con los programas de Mader (por defecto, '
                        'la actual)')
    p.add_argument('--salida', default=None,
                   help='ruta base de las salidas (por defecto '
                        '<entrada>_ISPBKW)')
    p.add_argument('--columna-fijo', default=None,
                   help='columna con la densidad, g/cm3')
    p.add_argument('--valor-fijo', type=float, default=1.0,
                   help='densidad común si no se indica --columna-fijo')
    p.add_argument('--continuar', action='store_true',
                   help='no archivar userdata; calcular solo lo que falte')
    p.add_argument('--preparar', action='store_true',
                   help='solo escribir zzzcomps, sin ejecutar ISPBKW')
    p.add_argument('--powershell', default='powershell',
                   help='ejecutable de PowerShell')
    p.add_argument('--col-compuesto', default='Compuesto',
                   help='columna con el nombre del compuesto (opcional; '
                        'por defecto Compuesto)')
    p.add_argument('--col-formula', default='Formula',
                   help='columna con la fórmula (por defecto Formula)')
    p.add_argument('--col-deltah', default='DeltaH',
                   help='columna con la entalpía de formación, kcal/mol '
                        'a 298,15 K (por defecto DeltaH)')
    a = p.parse_args(argv)
    try:
        calcular_isp(a.entrada, a.trabajo, a.salida, a.columna_fijo,
                     a.valor_fijo, a.continuar, a.preparar, a.powershell,
                     a.col_compuesto, a.col_formula, a.col_deltah)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
