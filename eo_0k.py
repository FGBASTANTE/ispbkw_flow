"""Calcula el ``eo`` de ISPBKW a partir de la entalpía a 298,15 K.

ISPBKW (BKW de Mader) trabaja con referencia a 0 K: las entalpías de
los productos son ``Hf(0 K) + [H(T) - H(0)]``, es decir, relativas a
los elementos a 0 K. El impulso sale de ``ec - ee`` y la entalpía de
cámara es ``ec = eo / M + pc * vo``: ``eo`` es la entalpía del
propelente en su estado inicial, en esa misma referencia.

Se calculan dos valores:

1. ``eo_ISPBKW`` (recomendado para comparar con CEA): propelente a
   298,15 K, como en CEA. Es exacto y no depende de la capacidad
   calorífica del propelente::

       eo = dHf(298) + sum_i nu_i * [H298 - H0](elemento i)

   porque ``H_comp(298) - sum H_elem(0) = dHf(298) + sum [H298 -
   H0](elementos)``.

2. ``DeltaH_0K_est``: entalpía de formación a 0 K en sentido estricto
   (definición del manual de BKW; equivale a un propelente
   inicialmente a 0 K)::

       dHf(0) = eo - [H298 - H0](compuesto)

   El término del compuesto exige su capacidad calorífica entre 0 y
   298,15 K, que no suele estar disponible. Aquí se ESTIMA como::

       [H298 - H0](compuesto) ~= F_CP * Cp(298) * 298,15

   con ``Cp(298)`` de la regla de Kopp modificada por Hurst y
   Harrison (1991) para sólidos (contribuciones atómicas aditivas) y
   ``F_CP = 0,5``, valor típico de sólidos moleculares orgánicos. La
   incertidumbre de este término es del orden del +-25 %, y es mayor
   en líquidos y en las fórmulas globales de biergoles e híbridos.
   Las contribuciones atómicas son las de Hurst y Harrison en
   cal/(mol K) (``KOPP_CAL``); los elementos sin valor propio (p. ej.
   el P) usan el de "Otros".

Los valores ``[H298 - H0]`` de los elementos (estado de referencia de
cada uno) y las masas atómicas son los de la base termodinámica de NASA
CEA (``thermo.inp``; McBride, Zehe y Gordon, NASA/TP-2002-211556), la
misma que usa ``impulso_cea``. Con esa base, las entalpías de formación
a 0 K de los productos principales coinciden con las de ISPBKW
(``zzztherc``) en pocas cal/mol (H2O, CO2, CO, HCl), lo que confirma la
referencia de elementos a 0 K.

Unidades: ``DeltaH`` en kcal por mol de la fórmula escrita (igual que
en ``impulso_cea``); ``eo`` en cal por peso de fórmula (entrada de
ISPBKW).

Uso desde la línea de comandos::

    python eo_0k.py energ_mat.csv --salida energ_mat_eo0K.csv
"""

__all__ = ['H298_H0_ELEMENTO', 'KOPP_CAL', 'CP_KOPP', 'F_CP', 'T_REF',
           'KCAL_KJ',
           'correccion_0k', 'eo_ispbkw', 'eo_0k', 'anadir_eo_0k', 'main']

import argparse
from pathlib import Path

import pandas as pd

from formula_quimica import masa_formula, parse_formula

KCAL_KJ = 4.184  # kJ por kcal termoquímica.
T_REF = 298.15  # Temperatura de referencia, K.
F_CP = 0.5  # [H298 - H0] / (Cp(298) * T_REF) del compuesto (estimado).

# [H298 - H0] del elemento en su estado de referencia, kJ por
# átomo-gramo (NASA CEA, thermo.inp), para los 17 elementos de USERBKW:
# H2/2, C(gr), N2/2, O2/2, CL2/2, P(cr) (fósforo blanco), Li(cr),
# Be(a), B(b), F2/2, Na(cr), Mg(cr), AL(cr), Si(cr), S(a), W(cr), Pb(cr).
H298_H0_ELEMENTO = {'H': 8.468102 / 2, 'C': 1.0535, 'N': 8.670104 / 2,
                    'O': 8.680104 / 2, 'Cl': 9.181110 / 2, 'P': 5.360,
                    'Li': 4.632, 'Be': 1.942068, 'B': 1.214,
                    'F': 8.825106 / 2, 'Na': 6.460, 'Mg': 4.979161,
                    'Al': 4.540, 'Si': 3.217471, 'S': 4.412, 'W': 4.973,
                    'Pb': 6.870}

# Contribución atómica a Cp(298) de un sólido, cal/(mol K): regla de
# Kopp modificada (Hurst y Harrison, Chem. Eng. Commun. 112, 21-30,
# 1992). Tabla completa de los autores; "Otros" se aplica a los
# elementos sin valor propio.
KOPP_CAL = {
    'C': 2.602, 'H': 1.806, 'O': 3.206, 'N': 4.477, 'S': 2.953,
    'F': 6.250, 'Cl': 5.898, 'Br': 6.059, 'I': 6.042, 'Al': 4.317,
    'B': 2.413, 'Ba': 7.733, 'Be': 2.979, 'Ca': 6.749, 'Co': 6.142,
    'Cu': 6.431, 'Fe': 6.947, 'Hg': 6.658, 'K': 6.876, 'Li': 5.554,
    'Mg': 5.421, 'Mn': 6.704, 'Mo': 7.033, 'Na': 6.257, 'Ni': 6.082,
    'Pb': 7.549, 'Si': 4.061, 'Sr': 6.787, 'Ti': 6.508, 'V': 7.014,
    'W': 7.375, 'Zr': 6.407, 'Otros': 6.362}

# Las mismas contribuciones en J/(mol K) para los 17 elementos de USERBKW
# (el P usa el valor de "Otros").
CP_KOPP = {e: KCAL_KJ * KOPP_CAL.get(e, KOPP_CAL['Otros'])
           for e in H298_H0_ELEMENTO}


def correccion_0k(formula, f_cp=F_CP):
    """Calcula los términos de la conversión de 298,15 K a 0 K.

    Args:
        formula (str): Fórmula química (ver ``parse_formula``).
        f_cp (float): Cociente ``[H298 - H0] / (Cp(298) * 298,15)``
            supuesto para el compuesto.

    Returns:
        dict[str, float]: ``masa_g_mol`` (masa de la fórmula),
        ``elementos_kcal`` (suma exacta de ``[H298 - H0]`` de los
        elementos), ``compuesto_kcal`` (``[H298 - H0]`` estimado del
        compuesto) y ``correccion_kcal`` (``elementos - compuesto``),
        las tres en kcal por mol de fórmula.

    Raises:
        ValueError: Si la fórmula contiene un elemento sin datos.
    """
    comp = parse_formula(formula)
    faltan = [e for e in comp if e not in H298_H0_ELEMENTO]
    if faltan:
        raise ValueError(f'elementos sin datos: {faltan}')
    elementos = sum(c * H298_H0_ELEMENTO[e] for e, c in comp.items())
    cp = sum(c * CP_KOPP[e] for e, c in comp.items())  # J/(mol K)
    compuesto = f_cp * cp * T_REF / 1e3  # kJ/mol
    return dict(masa_g_mol=masa_formula(comp),
                elementos_kcal=elementos / KCAL_KJ,
                compuesto_kcal=compuesto / KCAL_KJ,
                correccion_kcal=(elementos - compuesto) / KCAL_KJ)


def eo_ispbkw(formula, dh_kcal_mol):
    """Calcula el ``eo`` de ISPBKW de un propelente a 298,15 K.

    Es la entalpía del propelente a 298,15 K respecto a los elementos
    a 0 K. No depende de la capacidad calorífica del propelente.

    Args:
        formula (str): Fórmula química (ver ``parse_formula``).
        dh_kcal_mol (float): Entalpía de formación a 298,15 K, kcal
            por mol de la fórmula escrita.

    Returns:
        float: ``eo`` en cal por peso de fórmula.

    Example:
        >>> round(eo_ispbkw('C3H6N6O6', 14.71))
        33978
    """
    return 1e3 * (dh_kcal_mol + correccion_0k(formula)['elementos_kcal'])


def eo_0k(formula, dh_kcal_mol, f_cp=F_CP):
    """Estima la entalpía de formación a 0 K de un propelente.

    Corresponde a un propelente inicialmente a 0 K; para comparar con
    CEA (reactivo a 298,15 K) debe usarse ``eo_ispbkw``.

    Args:
        formula (str): Fórmula química (ver ``parse_formula``).
        dh_kcal_mol (float): Entalpía de formación a 298,15 K, kcal
            por mol de la fórmula escrita.
        f_cp (float): Ver ``correccion_0k``.

    Returns:
        float: Entalpía de formación a 0 K estimada, kcal por mol de
        la fórmula escrita.

    Example:
        >>> round(eo_0k('C3H6N6O6', 14.71), 2)
        24.33
    """
    return dh_kcal_mol + correccion_0k(formula, f_cp)['correccion_kcal']


def anadir_eo_0k(ruta, f_cp=F_CP):
    """Añade a un CSV de propelentes las columnas de ``eo``.

    Args:
        ruta (str | os.PathLike): CSV con las columnas ``Formula`` y
            ``DeltaH`` (kcal/mol a 298,15 K, por mol de la fórmula
            escrita).
        f_cp (float): Ver ``correccion_0k``.

    Returns:
        pandas.DataFrame: Las columnas del CSV más ``eo_ISPBKW``
        (cal por peso de fórmula; propelente a 298,15 K, exacto; ver
        ``eo_ispbkw``) y ``DeltaH_0K_est`` (kcal por mol de fórmula;
        entalpía de formación a 0 K estimada; ver ``eo_0k``). Si ya
        existen, se sustituyen; se elimina ``eo_0K_est`` de versiones
        anteriores.

    Raises:
        FileNotFoundError: Si ``ruta`` no existe.
        KeyError: Si faltan las columnas ``Formula`` o ``DeltaH``.
        ValueError: Si alguna fórmula tiene elementos sin datos.
    """
    df = pd.read_csv(ruta)
    faltan = {'Formula', 'DeltaH'} - set(df.columns)
    if faltan:
        raise KeyError(f'faltan columnas en {ruta}: {sorted(faltan)}')
    pares = list(zip(df['Formula'], df['DeltaH'].astype(float)))
    df = df.drop(columns=['eo_0K_est'], errors='ignore')
    df['eo_ISPBKW'] = [round(eo_ispbkw(f, dh), 1) for f, dh in pares]
    df['DeltaH_0K_est'] = [round(eo_0k(f, dh, f_cp), 3) for f, dh in pares]
    return df


def main(argv=None):
    """Añade las columnas de ``eo`` a un CSV y lo guarda.

    Args:
        argv (list[str] | None): Argumentos de la línea de comandos;
            ``None`` usa ``sys.argv[1:]``.

    Returns:
        int: Código de salida (0 si termina sin error).
    """
    parser = argparse.ArgumentParser(
        description='Calcula el eo de ISPBKW (referencia 0 K) a '
                    'partir de la entalpía de formación a 298,15 K.')
    parser.add_argument('entrada', help='CSV con columnas Formula y '
                        'DeltaH (kcal/mol a 298,15 K)')
    parser.add_argument('--salida', default=None,
                        help='CSV de salida (por defecto <entrada>_eo0K.csv)')
    parser.add_argument('--f-cp', type=float, default=F_CP,
                        help='[H298 - H0] / (Cp(298) * 298,15) del '
                             'compuesto (por defecto 0,5)')
    args = parser.parse_args(argv)
    salida = args.salida or str(
        Path(args.entrada).with_name(Path(args.entrada).stem + '_eo0K.csv'))
    anadir_eo_0k(args.entrada, args.f_cp).to_csv(salida, index=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
