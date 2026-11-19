"""Fórmulas químicas y masas atómicas comunes a las utilidades.

Admite los 17 elementos de USERBKW (H, Li, Be, B, C, N, O, F, Na, Mg, Al,
Si, P, S, Cl, W y Pb). Las masas atómicas son las de la base
termodinámica de NASA CEA (``thermo.inp``, McBride, Zehe y Gordon,
NASA/TP-2002-211556), de modo que las masas de fórmula coinciden con
las que usa CEA.
"""

__all__ = ['MASA', 'parse_formula', 'masa_formula']

import re

# Masas atómicas, g/mol (NASA CEA, thermo.inp). Los mismos 17 elementos
# que USERBKW; los seis primeros son los habituales en explosivos.
MASA = {'H': 1.00794, 'C': 12.0107, 'N': 14.0067, 'O': 15.9994,
        'Cl': 35.453, 'P': 30.973761,
        'Li': 6.941, 'Be': 9.012182, 'B': 10.811, 'F': 18.9984032,
        'Na': 22.98977, 'Mg': 24.305, 'Al': 26.981538, 'Si': 28.0855,
        'S': 32.065, 'W': 183.84, 'Pb': 207.2}


def parse_formula(formula):
    """Descompone una fórmula química en átomos por elemento.

    Admite paréntesis anidados y subíndices decimales, acumula los
    elementos que aparecen más de una vez y conserva el orden de
    aparición. Ignora los caracteres que no forman parte de la sintaxis
    (p. ej. los espacios).

    Args:
        formula (str): Fórmula, p. ej. ``'C(NO2)4'`` o
            ``'C2.03H2.64N2.18O2.67'``.

    Returns:
        dict[str, float]: Número de átomos de cada elemento.

    Raises:
        ValueError: Si los paréntesis no están balanceados.

    Example:
        >>> parse_formula('C(NO2)4')
        {'C': 1.0, 'N': 4.0, 'O': 8.0}
    """
    pila = [{}]
    patron = r'([A-Z][a-z]?|[()])(\d*\.?\d*)'
    for tok, n in re.findall(patron, str(formula)):
        n = float(n) if n else 1.0
        if tok == '(':
            pila.append({})
        elif tok == ')':
            if len(pila) == 1:
                raise ValueError(f'paréntesis sin abrir en {formula}')
            for e, c in pila.pop().items():
                pila[-1][e] = pila[-1].get(e, 0) + c * n
        else:
            pila[-1][tok] = pila[-1].get(tok, 0) + n
    if len(pila) != 1:
        raise ValueError(f'paréntesis sin cerrar en {formula}')
    return pila[0]


def masa_formula(formula):
    """Calcula la masa de una fórmula química.

    Args:
        formula (str | dict[str, float]): Fórmula (ver
            ``parse_formula``) o su composición ya descompuesta.

    Returns:
        float: Masa de la fórmula, g/mol.

    Raises:
        ValueError: Si la fórmula está vacía o contiene un elemento sin
            masa en ``MASA``.

    Example:
        >>> round(masa_formula('C3H6N6O6'), 4)
        222.1163
    """
    comp = formula if isinstance(formula, dict) else parse_formula(formula)
    faltan = [e for e in comp if e not in MASA]
    if not comp or faltan:
        raise ValueError(f'fórmula no válida: {formula} {faltan}')
    return sum(c * MASA[e] for e, c in comp.items())
