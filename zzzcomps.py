"""Escribe los propelentes de un CSV en el formato ``zzzcomps`` de USERBKW.

``zzzcomps`` es el fichero de componentes que lee USERBKW (generador
de datos de entrada de BKW/ISPBKW). Cada componente ocupa un bloque
de líneas de ancho fijo, con los formatos FORTRAN de ``userbkw.f``::

    (1x,a20,2e18.11)   nombre, densidad, entalpía de formación
    (1x,a20,e18.11)    elemento, átomos por fórmula   (una por elemento)
    (1x,a20,e18.11)    'zzz', masa de la fórmula

Ejemplo (PETN, entalpía en cal por mol de fórmula)::

     exp1                 1.00000000000E+00-0.12870000000E+06
     c                    0.50000000000E+01
     h                    0.80000000000E+01
     n                    0.40000000000E+01
     o                    0.12000000000E+02
     zzz                  0.31613500000E+03

Los componentes se nombran ``exp1``, ``exp2``... en el orden del CSV.
El segundo campo (USERBKW lo lee como densidad, g/cm3) vale por defecto
``1.00000000000E+00`` en todos los componentes; con ``--columna-fijo``
se toma de una columna del CSV. Se escribe siempre con el formato del
valor por defecto (``1PE18.11``: una cifra entera no nula y 11
decimales). La entalpía se escribe en cal por mol de la fórmula
escrita (``E18.11``); la columna de origen la elige el usuario (para
ISPBKW, ``eo_ISPBKW``; ver ``eo_0k.py``).

El fichero se escribe por defecto con fin de línea de Windows (CR LF):
con LF, USERBKW no lee el último componente. ``--lf`` lo cambia.

Junto a ``zzzcomps`` se escribe una tabla de correspondencia
(``<salida>_nombres.csv``) con el nombre ``expN`` de cada propelente,
sus columnas de identificación (``Tipo``, ``Compuesto``, ``Formula``)
y los valores escritos. ``extraer_composicion.py --nombres`` la usa
para unir los resultados por nombre y no por posición.

Uso desde la línea de comandos::

    python zzzcomps.py Impulso_data_eo0K.txt --columna eo_ISPBKW
    python zzzcomps.py Impulso_data_eo0K.txt --columna-fijo Densidad
"""

__all__ = ['COLUMNAS_KCAL', 'VALOR_FIJO',
           'COLUMNAS_ID', 'e18_11', 'es18_11', 'bloque', 'escribir_zzzcomps',
           'main']

import argparse
import csv

import pandas as pd

from formula_quimica import masa_formula, parse_formula

# Columnas de entalpía en kcal/mol; se multiplican por 1000. Las demás
# se suponen ya en cal/mol.
COLUMNAS_KCAL = ('DeltaH', 'DeltaH_0K_est')

# Columnas de identificación que se copian, si existen, a la tabla de
# correspondencia de nombres.
COLUMNAS_ID = ('Tipo', 'Compuesto', 'Formula')

# Valor por defecto del segundo campo de la primera línea de cada
# bloque (se escribe como ' 1.60000000000E+00').
VALOR_FIJO = 1.6


def e18_11(valor):
    """Formatea un número como el descriptor ``E18.11`` de FORTRAN.

    Mantisa entre 0,1 y 1 con 11 decimales, exponente de dos cifras con
    signo y alineación a la derecha en 18 caracteres.

    Args:
        valor (float): Número a escribir.

    Returns:
        str: Cadena de 18 caracteres.

    Raises:
        ValueError: Si el exponente no cabe en dos cifras.

    Example:
        >>> e18_11(-128700.0)
        '-0.12870000000E+06'
        >>> e18_11(5)
        ' 0.50000000000E+01'
    """
    if valor == 0:
        return ' 0.00000000000E+00'
    mantisa, exp = f'{abs(valor):.10E}'.split('E')
    exp = int(exp) + 1
    if abs(exp) > 99:
        raise ValueError(f'exponente fuera de rango: {valor}')
    signo = '-' if valor < 0 else ' '
    return f"{signo}0.{mantisa.replace('.', '')}E{exp:+03d}"


def es18_11(valor):
    """Formatea un número como el descriptor ``1PE18.11`` de FORTRAN.

    Es el formato del campo fijo: una cifra entera no nula, 11
    decimales, exponente de dos cifras con signo y alineación a la
    derecha en 18 caracteres.

    Args:
        valor (float): Número a escribir.

    Returns:
        str: Cadena de 18 caracteres.

    Raises:
        ValueError: Si el valor no es finito o el exponente no cabe en
            dos cifras.

    Example:
        >>> es18_11(1.0)
        ' 1.00000000000E+00'
        >>> es18_11(1.891)
        ' 1.89100000000E+00'
    """
    texto = f'{float(valor):18.11E}'
    if len(texto) != 18 or 'E' not in texto:
        raise ValueError(f'valor no representable en 1PE18.11: {valor}')
    return texto


def bloque(nombre, formula, entalpia_cal, valor_fijo=VALOR_FIJO):
    """Genera las líneas de un componente en formato ``zzzcomps``.

    Los elementos se escriben en minúsculas y en el orden en que
    aparecen en la fórmula.

    Args:
        nombre (str): Nombre del componente (máximo 20 caracteres).
        formula (str): Fórmula química (ver ``parse_formula``).
        entalpia_cal (float): Entalpía de formación, cal por mol de la
            fórmula escrita.
        valor_fijo (float): Segundo campo de la primera línea (por
            defecto ``VALOR_FIJO`` = 1,0).

    Returns:
        list[str]: Líneas del bloque, sin salto de línea final.

    Raises:
        ValueError: Si el nombre es demasiado largo, la fórmula está
            vacía o contiene un elemento sin masa atómica (ver
            ``formula_quimica.MASA``).
    """
    comp = parse_formula(formula)
    masa = masa_formula(comp)
    if len(nombre) > 20:
        raise ValueError(f'nombre de más de 20 caracteres: {nombre}')
    lineas = [f' {nombre:<20s}{es18_11(valor_fijo)}'
              f'{e18_11(entalpia_cal)}']
    lineas += [f' {e.lower():<20s}{e18_11(c)}' for e, c in comp.items()]
    lineas.append(f" {'zzz':<20s}{e18_11(masa)}")
    return lineas


def escribir_zzzcomps(ruta, salida, columna='eo_ISPBKW', factor=None,
                      prefijo='exp', crlf=True, columna_fijo=None,
                      valor_fijo=VALOR_FIJO, tabla=''):
    """Convierte un CSV de propelentes a un fichero ``zzzcomps``.

    Args:
        ruta (str | os.PathLike): CSV con la columna ``Formula`` y la
            columna de entalpía elegida.
        salida (str | os.PathLike): Fichero de salida.
        columna (str): Columna de entalpía de formación.
        factor (float | None): Factor que convierte la columna a cal
            por mol de fórmula. ``None`` usa 1000 si la columna está en
            ``COLUMNAS_KCAL`` (kcal/mol) y 1 en otro caso.
        prefijo (str): Prefijo de los nombres (``exp1``, ``exp2``...).
        crlf (bool): Si es ``True`` (por defecto), usa fin de línea de
            Windows; con ``False``, LF (USERBKW pierde el último
            componente).
        columna_fijo (str | None): Columna de la que se toma el segundo
            campo de cada componente. ``None`` usa ``valor_fijo`` en
            todos.
        valor_fijo (float): Valor del segundo campo cuando
            ``columna_fijo`` es ``None``.
        tabla (str | os.PathLike | None): Tabla de correspondencia de
            nombres (CSV). ``''`` usa ``<salida>_nombres.csv``; ``None``
            no la escribe. Columnas: ``material`` (``expN``), las de
            ``COLUMNAS_ID`` presentes en el CSV, ``origen_entalpia``
            (columna usada), ``entalpia_cal`` y ``densidad`` (valores
            escritos).

    Returns:
        int: Número de componentes escritos.

    Raises:
        FileNotFoundError: Si ``ruta`` no existe.
        KeyError: Si faltan ``Formula``, ``columna`` o ``columna_fijo``
            en el CSV.
        ValueError: Si alguna fórmula no es válida o ``columna_fijo``
            tiene valores vacíos o no numéricos.
    """
    df = pd.read_csv(ruta)
    faltan = {'Formula', columna, columna_fijo or 'Formula'} - set(df.columns)
    if faltan:
        raise KeyError(f'faltan columnas en {ruta}: {sorted(faltan)}')
    if factor is None:
        factor = 1000.0 if columna in COLUMNAS_KCAL else 1.0
    if columna_fijo is None:
        fijos = [valor_fijo] * len(df)
    else:
        fijos = pd.to_numeric(df[columna_fijo], errors='coerce')
        malos = [i + 1 for i, v in enumerate(fijos) if pd.isna(v)]
        if malos:
            raise ValueError(f'valores vacíos o no numéricos en '
                             f'{columna_fijo}, filas {malos}')
    lineas, nombres = [], []
    filas = zip(df.to_dict('records'), df[columna], fijos)
    for i, (fila, h, v) in enumerate(filas, 1):
        nombre, h_cal = f'{prefijo}{i}', float(h) * factor
        lineas += bloque(nombre, fila['Formula'], h_cal, float(v))
        nombres.append({'material': nombre,
                        **{c: fila[c] for c in COLUMNAS_ID if c in fila},
                        'origen_entalpia': columna,
                        'entalpia_cal': round(h_cal, 6),
                        'densidad': float(v)})
    with open(salida, 'w', encoding='ascii',
              newline='\r\n' if crlf else '\n') as fh:
        fh.write('\n'.join(lineas) + '\n')
    if tabla is not None:
        tabla = tabla or f'{salida}_nombres.csv'
        with open(tabla, 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=list(nombres[0]))
            w.writeheader()
            w.writerows(nombres)
    return len(df)


def main(argv=None):
    """Convierte un CSV de propelentes al formato ``zzzcomps``.

    Args:
        argv (list[str] | None): Argumentos de la línea de comandos;
            ``None`` usa ``sys.argv[1:]``.

    Returns:
        int: Código de salida (0 si termina sin error).
    """
    parser = argparse.ArgumentParser(
        description='Escribe los propelentes de un CSV en el formato '
                    'zzzcomps de USERBKW.')
    parser.add_argument('entrada', help='CSV con la columna Formula y '
                        'la de entalpía')
    parser.add_argument('--salida', default='zzzcomps',
                        help='fichero de salida')
    parser.add_argument('--columna', default='eo_ISPBKW',
                        help='columna de entalpía de formación')
    parser.add_argument('--factor', type=float, default=None,
                        help='factor para pasar la columna a cal/mol '
                             '(por defecto 1000 para DeltaH y '
                             'DeltaH_0K_est, 1 para las demás)')
    parser.add_argument('--prefijo', default='exp',
                        help='prefijo de los nombres')
    fin = parser.add_mutually_exclusive_group()
    fin.add_argument('--crlf', dest='crlf', action='store_true',
                     default=True,
                     help='fin de línea de Windows, CR LF (por defecto)')
    fin.add_argument('--lf', dest='crlf', action='store_false',
                     help='fin de línea LF (USERBKW pierde el último '
                          'componente)')
    parser.add_argument('--tabla', default='',
                        help='tabla de correspondencia de nombres (por '
                             'defecto <salida>_nombres.csv)')
    parser.add_argument('--columna-fijo', default=None,
                        help='columna de la que se toma el segundo campo '
                             '(por defecto, el valor fijo en todos)')
    parser.add_argument('--valor-fijo', type=float, default=VALOR_FIJO,
                        help='valor del segundo campo si no se indica '
                             '--columna-fijo (por defecto 1.0)')
    args = parser.parse_args(argv)
    n = escribir_zzzcomps(args.entrada, args.salida, args.columna,
                          args.factor, args.prefijo, args.crlf,
                          args.columna_fijo, args.valor_fijo, args.tabla)
    fijo = (f'columna {args.columna_fijo}' if args.columna_fijo
            else f'{args.valor_fijo:g}')
    print(f'{n} componentes escritos en {args.salida} '
          f'(entalpía: columna {args.columna}; campo fijo: {fijo}; '
          f"fin de línea: {'CR LF' if args.crlf else 'LF'})")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
