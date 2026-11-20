"""Isp y balance de energía de propelentes con NASA CEA (RocketCEA).

Para cada propelente se simula la combustión adiabática en la cámara a
la presión ``pc_bar`` y la expansión isentrópica hasta ``pe_bar``
(tobera adaptada) con dos hipótesis de composición:

* ``Equilibrium``: composición de equilibrio en cada punto.
* ``Frozen``: composición congelada desde la cámara.

La velocidad de escape es ``ve = sqrt(2 (h_c - h_e))`` y el impulso
específico es ``Isp = ve / g0``. Las entalpías son absolutas (incluyen
la de formación; referencia: elementos a 298,15 K) y las energías se
expresan en kJ/kg.

Como comprobación independiente, el impulso específico se calcula
también con ``CEA_Obj.estimate_Ambient_Isp`` de RocketCEA a la presión
ambiente ``pamb_bar`` (por defecto, la de salida). Con tobera adaptada
(``pamb = pe``) ambos valores deben coincidir.

Unidades del impulso específico: ``Ve_*`` e ``Isp_*_kms`` en km/s
(= N·s/g, la unidad de las columnas ``Isp_BKW`` e ``Isp_Doc``) e
``Isp_*_s`` en s; ``Isp [s] = 1000 * Isp [km/s] / g0``.

Las entalpías estándar de formación de los productos se leen de
``thermo.inp``, la base de datos termodinámica que distribuye
RocketCEA.

Forma parte de ``ispbkw_flow``: necesita ``formula_quimica.py`` en la
misma carpeta (lectura de fórmulas).

Uso desde la línea de comandos::

    python impulso_cea.py datos.csv --pc-bar 68.9476 --pe-bar 1.01325
"""

__all__ = [
    'HIPOTESIS', 'G0', 'PC_1000PSI', 'ATM_BAR', 'parse_formula', 'hf_especies',
    'isp_ambiente', 'calcular', 'balance_energia', 'calcular_cea',
    'estadisticos', 'metricas', 'graficar_comparacion', 'mapa_correlaciones',
    'barrido_pc', 'barrido_composicion', 'barrido_mr', 'graficar_mr',
    'main',
]

import argparse
import json
import re
import zlib
from functools import lru_cache
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rocketcea
from rocketcea import py_cea
from rocketcea.cea_obj import add_new_propellant
from rocketcea.cea_obj_w_units import CEA_Obj

from formula_quimica import parse_formula  # noqa: F401 (se reexporta)

# Valor del indicador ``frozen`` de CEA para cada hipótesis.
HIPOTESIS = {'Equilibrium': 0, 'Frozen': 1}
G0 = 9.80665  # Gravedad estándar, m/s2.
PSI_BAR = 0.0689475729  # bar por psi.
PC_1000PSI = 1000 * PSI_BAR  # 1000 psi en bar (68,9476).
ATM_BAR = 1.01325  # Presión atmosférica normal (1 atm), bar.
KCAL_J = 4184.0  # J por kcal termoquímica.
MIN_FRACCION = 5e-6  # Fracción molar mínima que se conserva.


@lru_cache(maxsize=None)
def _thermo():
    """Lee ``thermo.inp``, la base de datos termodinámica de CEA.

    Returns:
        dict[str, tuple[float, float, int]]: ``{especie: (M, Hf,
        fase)}`` con la masa molar M en g/mol, la entalpía de
        formación Hf a 298,15 K en J/mol y el indicador de fase (0
        gas; distinto de 0, condensado).
    """
    ruta = Path(rocketcea.__file__).parent / 'thermo.inp'
    lineas = ruta.read_text(encoding='ascii', errors='ignore')
    lineas = lineas.splitlines()
    # Segunda línea de cada especie (ancho fijo): fase en las columnas
    # 51-52, masa molar en 53-65 y entalpía de formación en 66-80.
    return {
        lineas[i - 1][:18].strip(): (float(lineas[i][52:65]),
                                     float(lineas[i][65:80]),
                                     int(lineas[i][50:52]))
        for i in range(1, len(lineas))
        if re.match(r'^ \d ', lineas[i])
    }


@lru_cache(maxsize=None)
def hf_especies():
    """Devuelve la entalpía de formación de cada especie de CEA.

    Returns:
        dict[str, float]: Entalpía estándar de formación a 298,15 K,
        en J/mol, indexada por el nombre de la especie en
        ``thermo.inp`` (p. ej. ``'CO2'`` o ``'AL2O3(L)'``).
    """
    return {k: v[1] for k, v in _thermo().items()}


def _expansion(cea, pc_bar, pe_bar, mr, frozen):
    """Resuelve con CEA la expansión de ``pc_bar`` a ``pe_bar``.

    Args:
        cea (CEA_Obj): Objeto de RocketCEA con unidades de bar, K y
            J/kg (ver ``_cea``).
        pc_bar (float): Presión de cámara, bar.
        pe_bar (float): Presión de salida, bar.
        mr (float): Relación oxidante/combustible. Se ignora en los
            monopropelentes (usar 0.0).
        frozen (int): 0 para equilibrio, 1 para flujo congelado desde
            la cámara.

    Returns:
        dict | None: ``None`` si CEA no converge (devuelve eps = 0).
        En otro caso, un dict con ``kw`` (argumentos para nuevas
        llamadas a CEA), ``eps`` (Ae/At que da ``pe_bar``), ``ve``
        (km/s), ``hc`` (J/kg) y ``tc`` y ``te`` (K, cámara y salida).
    """
    kw = dict(Pc=pc_bar, MR=mr, frozen=frozen)
    eps = cea.get_eps_at_PcOvPe(PcOvPe=pc_bar / pe_bar, **kw)
    if eps <= 0:
        return None
    hc, _, he = cea.get_Enthalpies(eps=eps, **kw)
    tc, _, te = cea.get_Temperatures(eps=eps, **kw)
    return dict(kw=kw, eps=eps, ve=np.sqrt(2 * (hc - he)) / 1e3,
                hc=hc, tc=tc, te=te)


def isp_ambiente(cea, r, pamb_bar, frozen):
    """Calcula el Isp con ``estimate_Ambient_Isp`` de RocketCEA.

    Se llama al objeto base de RocketCEA (``cea.cea_obj``), cuyas
    unidades están documentadas y son fijas: presiones en psia e Isp
    en s. Las conversiones se hacen aquí de forma explícita:
    ``p [psia] = p [bar] / PSI_BAR`` e
    ``Isp [km/s] = Isp [s] * g0 / 1000``.

    RocketCEA calcula ``IspAmb = IspVac - c* · Pamb · eps / (Pc · g0)``
    y, si la tobera está sobreexpandida hasta el punto de desprenderse
    el flujo, corrige el resultado. Con ``pamb_bar`` igual a la presión
    de salida (tobera adaptada) el resultado equivale a ``ve / g0``.

    Args:
        cea (CEA_Obj): Objeto de RocketCEA con unidades (ver ``_cea``).
        r (dict): Resultado de ``_expansion`` (fija Pc, MR y eps).
        pamb_bar (float): Presión ambiente, bar.
        frozen (int): 0 para equilibrio, 1 para flujo congelado desde
            la cámara.

    Returns:
        tuple[float, float, str]: Isp en s, Isp en km/s (= N·s/g) y
        modo de la tobera según RocketCEA (``UnderExpanded``,
        ``OverExpanded`` o ``Separated``, con la presión de salida o de
        separación en psia).
    """
    isp_s, modo = cea.cea_obj.estimate_Ambient_Isp(
        Pc=r['kw']['Pc'] / PSI_BAR, MR=r['kw']['MR'], eps=r['eps'],
        Pamb=pamb_bar / PSI_BAR, frozen=frozen)
    return isp_s, isp_s * G0 / 1e3, modo


def _composicion(cea, r):
    """Lee de CEA la composición de los productos en cada estación.

    ``CEA_Obj.get_SpeciesMoleFractions`` de RocketCEA conserva una sola
    de las entradas repetidas de una especie condensada (CEA crea una
    por cada intervalo de temperatura de sus datos, p. ej. tres para
    ``C(gr)``) y omite los moles que están en las demás. Esta función
    los suma.

    Args:
        cea (CEA_Obj): Objeto de RocketCEA con unidades (ver ``_cea``).
        r (dict): Resultado de ``_expansion``.

    Returns:
        tuple[dict, dict]: ``(masas, x)`` con la masa molar de cada
        especie (g/mol) y sus fracciones molares ``{especie: [inyector,
        cámara, garganta, salida]}``. Se omiten las especies con
        fracción menor que ``MIN_FRACCION`` en todas las estaciones.
    """
    cea.get_SpeciesMoleFractions(eps=r['eps'], **r['kw'])  # ejecuta CEA
    base = cea.cea_obj
    est = (base.i_injface, base.i_chm, base.i_thrt, base.i_exit)
    totn = py_cea.prtout.totn
    x, masas = {}, {}
    for k in range(py_cea.indx.ngc):
        nombre = py_cea.cdata.prod[k].decode('utf-8').strip()
        if not nombre:
            continue
        fila = x.setdefault(nombre, [0.0] * len(est))
        for j, i in enumerate(est):
            fila[j] += py_cea.comp.en[k - 1, i] / totn[i]
        masas[nombre] = py_cea.therm.mw[k - 1]
    x = {s: v for s, v in x.items() if max(v) >= MIN_FRACCION}
    return {s: masas[s] for s in x}, x


def _entalpias(cea, r, frozen):
    """Calcula las entalpías de una expansión ya resuelta.

    Args:
        cea (CEA_Obj): Objeto de RocketCEA con unidades (ver ``_cea``).
        r (dict): Resultado de ``_expansion``.
        frozen (int): 0 para equilibrio, 1 para flujo congelado. En
            flujo congelado la composición de salida es la de cámara.

    Returns:
        dict: ``hc`` y ``he`` (entalpía en cámara y en salida, J/kg),
        ``hp_c`` y ``hp_e`` (entalpía de formación de los productos
        con la composición de cámara y de salida, J/kg) y ``x``
        (fracciones molares ``{especie: [inyector, cámara, garganta,
        salida]}``) y ``masas`` (masa molar de cada especie, g/mol).
    """
    termo = _thermo()
    masas, x = _composicion(cea, r)

    def hf_prod(i):
        num = sum(v[i] * termo[s.lstrip('*')][1] for s, v in x.items())
        den = sum(v[i] * masas[s] for s, v in x.items())
        return 1e3 * num / den

    return dict(hc=r['hc'], he=r['hc'] - (r['ve'] * 1e3) ** 2 / 2,
                hp_c=hf_prod(1), hp_e=hf_prod(1 if frozen else 3),
                x=x, masas=masas)


def _fases(x, masas, i):
    """Resume una composición de CEA en fase gaseosa y condensada.

    Las fracciones de CEA son proporcionales a los moles de cada
    especie (gaseosa o condensada), de modo que los moles por kg de
    productos son ``1e3 * x_s / sum(x_j * M_j)``.

    Args:
        x (dict): Fracciones molares ``{especie: [inyector, cámara,
            garganta, salida]}`` (ver ``_entalpias``).
        masas (dict): Masa molar de cada especie, g/mol.
        i (int): Columna de ``x``: 1 para la cámara, 3 para la salida.

    Returns:
        dict: ``n_gas`` y ``n_cond`` (mol por kg de productos en fase
        gaseosa y condensada), ``m_gas`` (masa molar media de los
        gases, g/mol) y ``fm_gas`` (fracción en masa de gases).
    """
    termo = _thermo()
    gas = {s: v[i] for s, v in x.items() if termo[s.lstrip('*')][2] == 0}
    cond = {s: v[i] for s, v in x.items() if termo[s.lstrip('*')][2] != 0}
    masa_gas = sum(v * masas[s] for s, v in gas.items())
    masa_cond = sum(v * masas[s] for s, v in cond.items())
    total = masa_gas + masa_cond
    return dict(n_gas=1e3 * sum(gas.values()) / total,
                n_cond=1e3 * sum(cond.values()) / total,
                m_gas=masa_gas / sum(gas.values()),
                fm_gas=masa_gas / total)


def _resultados(cea, pc_bar, pe_bar, mr=0.0, pamb_bar=None):
    """Calcula Ve, temperaturas, energías y composición con CEA.

    Se evalúan el equilibrio y el flujo congelado. En cámara,
    ``h_c = h_0`` (cámara adiabática), ``Q_c = h_c - Hf(productos en
    cámara)`` y ``Q_e = h_c - Hf(productos en salida)``.

    Args:
        cea (CEA_Obj): Propelente ya definido (ver ``_cea``).
        pc_bar (float): Presión de cámara, bar.
        pe_bar (float): Presión de salida, bar.
        mr (float): Relación oxidante/combustible (0.0 en
            monopropelentes).
        pamb_bar (float | None): Presión ambiente para
            ``estimate_Ambient_Isp``, bar. ``None`` usa ``pe_bar``
            (tobera adaptada).

    Returns:
        dict: Con ``<h>`` = ``Equilibrium`` o ``Frozen``:
        ``Ve_CEA_<h>`` (km/s), ``Isp_CEA_<h>_s`` (s; ``Ve / g0``),
        ``Isp_amb_<h>_s`` (s), ``Isp_amb_<h>_kms`` (km/s) y
        ``Modo_tobera_<h>`` (los tres de ``estimate_Ambient_Isp``, ver
        ``isp_ambiente``), ``eps_<h>`` (Ae/At), ``T_exit_<h>`` (K) y
        ``h_e_<h>_kJ_kg``, ``Hf_prod_salida_<h>_kJ_kg`` y
        ``Q_e_<h>_kJ_kg`` (kJ/kg). Del equilibrio también: ``T_chamber``
        (K), ``h_c_kJ_kg``, ``Hf_prod_camara_kJ_kg``, ``Q_c_kJ_kg``
        (kJ/kg), ``Comp_Chamber`` y ``Comp_Exit_Eq`` (fracciones
        molares en JSON) y, en cámara (``camara``) y en la salida de
        equilibrio (``salida_Equilibrium``): ``n_gas_<p>_mol_kg``,
        ``n_cond_<p>_mol_kg``, ``M_gas_<p>_g_mol`` y ``fm_gas_<p>``.
        Si CEA no converge en una hipótesis, sus columnas valen NaN.
    """
    out = {}
    pamb_bar = pe_bar if pamb_bar is None else pamb_bar
    for h, fr in HIPOTESIS.items():
        cols = (f'Ve_CEA_{h}', f'Isp_CEA_{h}_s', f'Isp_amb_{h}_s',
                f'Isp_amb_{h}_kms', f'Modo_tobera_{h}', f'eps_{h}',
                f'T_exit_{h}', f'h_e_{h}_kJ_kg',
                f'Hf_prod_salida_{h}_kJ_kg', f'Q_e_{h}_kJ_kg')
        r = _expansion(cea, pc_bar, pe_bar, mr, fr)
        if r is None:
            out.update(dict.fromkeys(cols, np.nan))
            continue
        isp_s, isp_kms, modo = isp_ambiente(cea, r, pamb_bar, fr)
        e = _entalpias(cea, r, fr)
        out.update(zip(cols, (r['ve'], r['ve'] * 1e3 / G0, isp_s, isp_kms,
                              modo, r['eps'], r['te'], e['he'] / 1e3,
                              e['hp_e'] / 1e3,
                              (e['hc'] - e['hp_e']) / 1e3)))
        if fr == 0:
            out.update(T_chamber=r['tc'], h_c_kJ_kg=e['hc'] / 1e3,
                       Hf_prod_camara_kJ_kg=e['hp_c'] / 1e3,
                       Q_c_kJ_kg=(e['hc'] - e['hp_c']) / 1e3)
            for suf, i in (('camara', 1), (f'salida_{h}', 3)):
                f = _fases(e['x'], e['masas'], i)
                out.update({f'n_gas_{suf}_mol_kg': f['n_gas'],
                            f'n_cond_{suf}_mol_kg': f['n_cond'],
                            f'M_gas_{suf}_g_mol': f['m_gas'],
                            f'fm_gas_{suf}': f['fm_gas']})
            for col, i in (('Comp_Chamber', 1), ('Comp_Exit_Eq', 3)):
                out[col] = json.dumps({
                    s.lstrip('*'): float(f'{v[i]:.4g}')
                    for s, v in e['x'].items() if v[i] > 0})
    return out


def _cea(nombre):
    """Crea el objeto CEA de un propelente definido con nombre.

    Args:
        nombre (str): Nombre con el que se registró el propelente en
            RocketCEA.

    Returns:
        CEA_Obj: Objeto con presiones en bar, temperaturas en K y
        entalpías en J/kg.
    """
    return CEA_Obj(propName=nombre, pressure_units='Bar',
                   temperature_units='K', enthalpy_units='J/kg')


def _nombre_unico(formula, dh_kcal_mol):
    """Genera un nombre de propelente que depende de sus datos.

    RocketCEA guarda resultados en una caché indexada por el nombre
    del propelente. Si se reutiliza un nombre con otra fórmula u otra
    entalpía, podría devolver resultados del propelente anterior.

    Args:
        formula (str): Fórmula química.
        dh_kcal_mol (float): Entalpía de formación, kcal/mol.

    Returns:
        str: Nombre de 9 caracteres, p. ej. ``'M1a2b3c4d'``.
    """
    clave = f'{formula}|{float(dh_kcal_mol)!r}'.encode()
    return f'M{zlib.crc32(clave):08x}'


def _monopropelente(nombre, formula, dh_kcal_mol):
    """Registra en RocketCEA un monopropelente a 298,15 K.

    CEA interpreta ``h,cal`` en cal por mol de la fórmula escrita, no
    por gramo; por eso ``dh_kcal_mol`` debe estar referida a esa misma
    fórmula.

    Args:
        nombre (str): Nombre con el que se registra el propelente.
        formula (str): Fórmula química (ver ``parse_formula``).
        dh_kcal_mol (float): Entalpía de formación, kcal/mol.

    Returns:
        dict[str, float]: Átomos de cada elemento de la fórmula.

    Raises:
        ValueError: Si algún elemento no existe en ``thermo.inp`` o los
            paréntesis de la fórmula no están balanceados.
    """
    comp = parse_formula(formula)
    hf = hf_especies()
    desconocidos = [e for e in comp if e not in hf and e.upper() not in hf]
    if desconocidos:
        raise ValueError(f'elementos desconocidos para CEA: {desconocidos}')
    # Símbolos en mayúsculas (CL, AL...), como en las tarjetas de
    # RocketCEA y en la tabla de masas atómicas de CEA.
    elementos = ' '.join(f'{e.upper()} {c:g}' for e, c in comp.items())
    add_new_propellant(
        nombre, f'name {nombre} {elementos} wt%=100\n'
                f'h,cal={dh_kcal_mol * 1000:.1f} t(k)=298.15')
    return comp


def calcular(nombre, formula, dh_kcal_mol, pc_bar, pe_bar, pamb_bar=None):
    """Calcula las magnitudes de un monopropelente en CEA.

    Args:
        nombre (str): Nombre con el que se registra el propelente.
        formula (str): Fórmula química (ver ``parse_formula``).
        dh_kcal_mol (float): Entalpía de formación, kcal/mol, por mol
            de la fórmula escrita.
        pc_bar (float): Presión de cámara, bar.
        pe_bar (float): Presión de salida, bar.
        pamb_bar (float | None): Presión ambiente para
            ``estimate_Ambient_Isp``, bar. ``None`` usa ``pe_bar``.

    Returns:
        dict: Magnitudes en equilibrio y congelado (ver
        ``calcular_cea`` para la lista de claves y sus unidades).

    Raises:
        ValueError: Si la fórmula tiene paréntesis sin balancear o
            elementos desconocidos para CEA.
    """
    _monopropelente(nombre, formula, dh_kcal_mol)
    return _resultados(_cea(nombre), pc_bar, pe_bar, pamb_bar=pamb_bar)


def balance_energia(formula, dh_kcal_mol, pc_bar=PC_1000PSI, pe_bar=ATM_BAR,
                    frozen=False, imprimir=True):
    """Calcula el balance de energía de un monopropelente.

    Tres tramos, con entalpías absolutas (incluyen la de formación):

    1. Inicial -> cámara (adiabático, sin trabajo): ``h_c = h_0``.
       La energía química liberada ``Q_c = h_0 - Hf(productos en
       cámara)`` pasa a calor sensible de los productos.
    2. Cámara -> salida: ``h_c = h_e + ve**2 / 2``.
    3. Inicial -> salida: ``Q_e = h_0 - Hf(productos en salida)`` es
       la suma del calor sensible residual y de ``ve**2 / 2``.

    Args:
        formula (str): Fórmula química (ver ``parse_formula``).
        dh_kcal_mol (float): Entalpía de formación, kcal/mol, por mol
            de la fórmula escrita.
        pc_bar (float): Presión de cámara, bar. Por defecto 1000 psi.
        pe_bar (float): Presión de salida, bar.
        frozen (bool): ``True`` para flujo congelado desde la cámara.
        imprimir (bool): Si es ``True``, imprime el balance con
            unidades.

    Returns:
        dict[str, float]: Claves con la unidad en el nombre:
        ``h0_kJ_kg`` (calculada con ``dh_kcal_mol`` y las masas de
        ``thermo.inp``), ``hc_kJ_kg``, ``cierre_kJ_kg`` (``h_0 - h_c``),
        ``Hf_prod_camara_kJ_kg``, ``Q_camara_kJ_kg``, ``he_kJ_kg``,
        ``ke_kJ_kg`` (``ve**2 / 2``), ``Hf_prod_salida_kJ_kg``,
        ``Q_salida_kJ_kg``, ``sensible_salida_kJ_kg``, ``Tc_K``,
        ``Te_K``, ``ve_m_s`` y ``rendimiento`` (``ke / Q_e``,
        adimensional).

    Raises:
        RuntimeError: Si CEA no converge (típico del flujo congelado
            con sólidos condensados).
        ValueError: Si la fórmula es inválida o tiene elementos
            desconocidos para CEA.
    """
    nombre = _nombre_unico(formula, dh_kcal_mol)
    comp = _monopropelente(nombre, formula, dh_kcal_mol)
    termo, cea, fr = _thermo(), _cea(nombre), int(frozen)
    r = _expansion(cea, pc_bar, pe_bar, 0.0, fr)
    if r is None:
        raise RuntimeError('CEA no converge en esta hipótesis '
                           '(típico del flujo congelado con sólidos '
                           'condensados)')
    e = _entalpias(cea, r, fr)
    hc, he, hp_c, hp_e = e['hc'], e['he'], e['hp_c'], e['hp_e']  # J/kg
    masa = sum(c * (termo.get(el) or termo[el.upper()])[0]
               for el, c in comp.items())  # g/mol del reactivo
    h0 = dh_kcal_mol * KCAL_J / masa * 1e3  # J/kg
    ke = hc - he  # ve**2 / 2
    energias = dict(h0=h0, hc=hc, cierre=h0 - hc, Hf_prod_camara=hp_c,
                    Q_camara=h0 - hp_c, he=he, ke=ke,
                    Hf_prod_salida=hp_e, Q_salida=h0 - hp_e,
                    sensible_salida=he - hp_e)
    b = {f'{k}_kJ_kg': v / 1e3 for k, v in energias.items()}
    b.update(Tc_K=r['tc'], Te_K=r['te'], ve_m_s=r['ve'] * 1e3,
             rendimiento=ke / (h0 - hp_e))
    if imprimir:
        u = 'kJ/kg'
        hip = 'congelado' if frozen else 'equilibrio'

        def fila(etiqueta, clave, extra=''):
            return f"     {etiqueta:<38s}= {b[clave]:10.1f} {u}{extra}"

        print('\n'.join([
            f"Balance de energía ({hip}), Pc = {pc_bar:.2f} bar, "
            f"Pe = {pe_bar:g} bar  (energías en {u})",
            "1) INICIAL -> CÁMARA (adiabático, sin trabajo):  h_c = h_0",
            fila('h_0 = Hf reactivo (298,15 K)', 'h0_kJ_kg'),
            fila(f"h_c (CEA, T_c = {b['Tc_K']:.0f} K)", 'hc_kJ_kg',
                 f"   (cierre h_0 - h_c = {b['cierre_kJ_kg']:+.2f} {u})"),
            fila('Q_c = h_0 - Hf(productos cámara)', 'Q_camara_kJ_kg',
                 '   -> calor sensible de los productos a T_c'),
            "2) CÁMARA -> SALIDA (adiabático, sin trabajo):  "
            "h_c = h_e + ve²/2",
            fila(f"h_e (T_e = {b['Te_K']:.0f} K)", 'he_kJ_kg'),
            fila('ve²/2 = h_c - h_e', 'ke_kJ_kg',
                 f"   (ve = {b['ve_m_s']:.0f} m/s)"),
            "3) INICIAL -> SALIDA:  h_0 = h_e + ve²/2   <=>   "
            "Q_e = calor sensible residual + energía cinética",
            fila('Q_e = h_0 - Hf(productos salida)', 'Q_salida_kJ_kg'),
            fila('    = calor sensible en la salida',
                 'sensible_salida_kJ_kg'),
            fila('    + energía cinética ve²/2', 'ke_kJ_kg'),
            f"     {'Rendimiento cinético ve²/2 / Q_e':<38s}= "
            f"{b['rendimiento']:.1%}"]))
    return b


def calcular_cea(ruta, pc_bar=PC_1000PSI, pe_bar=ATM_BAR, pamb_bar=None,
                 col_compuesto='Compuesto', col_formula='Formula',
                 col_deltah='DeltaH'):
    """Calcula con CEA los monopropelentes de un fichero CSV.

    Cada fila se define como monopropelente a 298,15 K y se expande de
    ``pc_bar`` a ``pe_bar``. Si una fila falla, se imprime su causa y
    sus columnas de resultados quedan en NaN. Si el CSV ya contiene
    columnas de resultados, se sustituyen.

    Args:
        ruta (str | os.PathLike): CSV con las columnas obligatorias de
            fórmula (str) y entalpía de formación a 298,15 K (kcal/mol,
            por mol de la fórmula escrita), y la opcional de nombre del
            compuesto, que solo se usa en los mensajes de error. Sus
            nombres se indican con ``col_formula``, ``col_deltah`` y
            ``col_compuesto``; en el resultado conservan su nombre.
        pc_bar (float): Presión de cámara, bar. Por defecto 1000 psi.
        pe_bar (float): Presión de salida, bar. Por defecto 1 atm
            (1,01325 bar).
        pamb_bar (float | None): Presión ambiente para
            ``estimate_Ambient_Isp``, bar. ``None`` usa ``pe_bar``
            (tobera adaptada).
        col_compuesto (str): Columna con el nombre del compuesto
            (opcional: si es la de por defecto y no existe, se usa el
            número de fila en los mensajes).
        col_formula (str): Columna con la fórmula química.
        col_deltah (str): Columna con la entalpía de formación.

    Returns:
        pandas.DataFrame: Las columnas del CSV más ``Ve_CEA_<h>``
        (km/s), ``Isp_CEA_<h>_s`` (s), ``Isp_amb_<h>_s`` (s),
        ``Isp_amb_<h>_kms`` (km/s), ``Modo_tobera_<h>``, ``eps_<h>``
        (Ae/At), ``T_exit_<h>`` (K), ``h_e_<h>_kJ_kg``,
        ``Hf_prod_salida_<h>_kJ_kg``, ``Q_e_<h>_kJ_kg`` para
        ``<h>`` = ``Equilibrium`` y ``Frozen``, y, solo en equilibrio,
        ``T_chamber`` (K), ``h_c_kJ_kg``, ``Hf_prod_camara_kJ_kg``,
        ``Q_c_kJ_kg`` (kJ/kg), ``Comp_Chamber`` y ``Comp_Exit_Eq``
        (fracciones molares en JSON) y la composición por fases en
        cámara (``camara``) y en la salida de equilibrio
        (``salida_Equilibrium``): ``n_gas_<p>_mol_kg``,
        ``n_cond_<p>_mol_kg``, ``M_gas_<p>_g_mol`` y ``fm_gas_<p>``.

    Raises:
        FileNotFoundError: Si ``ruta`` no existe.
        KeyError: Si faltan las columnas de fórmula o entalpía, o la de
            compuesto cuando no es la de por defecto.
        ValueError: Si se indica la misma columna para dos datos.
    """
    df = pd.read_csv(ruta)
    pedidas = [col_formula, col_deltah]
    if col_compuesto != 'Compuesto' or col_compuesto in df.columns:
        pedidas.append(col_compuesto)
    faltan = [c for c in pedidas if c not in df.columns]
    if faltan:
        raise KeyError(f'faltan columnas en {ruta}: {faltan}; columnas '
                       f'del fichero: {list(df.columns)}')
    if len(set(pedidas)) != len(pedidas):
        raise ValueError(f'la misma columna para dos datos: {pedidas}')
    filas = []
    for i, r in df.iterrows():
        try:
            dh = float(r[col_deltah])
            filas.append(calcular(_nombre_unico(r[col_formula], dh),
                                  r[col_formula], dh, pc_bar, pe_bar,
                                  pamb_bar))
        except Exception as e:
            print(f"[{i}] {r.get(col_compuesto, i)}: "
                  f"{type(e).__name__}: {e}")
            filas.append({})
    res = pd.DataFrame(filas, index=df.index)
    df = df.drop(columns=res.columns, errors='ignore')
    return pd.concat([df, res], axis=1)


def estadisticos(real, pred):
    """Calcula los estadísticos de error entre dos series.

    Ignora las parejas con NaN. Los errores se definen como
    ``pred - real``.

    Args:
        real (pandas.Series): Valores de referencia.
        pred (pandas.Series): Valores predichos, con el mismo índice.

    Returns:
        dict: ``n`` (parejas válidas), ``R2`` (``1 - SSres / SStot``
        respecto a la recta y = x), ``sesgo`` (error medio), ``MAE``,
        ``RMSE``, ``max_err`` (error de mayor valor absoluto, con
        signo), ``idx_max`` (su índice) y el ajuste
        ``real = intercepto + pendiente * pred`` por mínimos
        cuadrados: ``pendiente``, ``intercepto``, ``R2_pearson``
        (cuadrado del coeficiente de correlación) y ``RMSE_ajustado``
        (RMSE tras aplicar el ajuste). Las magnitudes de error tienen
        la unidad de las series.
    """
    d = pd.concat([real, pred], axis=1).dropna()
    r, p = d.iloc[:, 0], d.iloc[:, 1]
    e = p - r
    b, a = np.polyfit(p, r, 1)
    return dict(
        n=len(d), R2=1 - (e ** 2).sum() / ((r - r.mean()) ** 2).sum(),
        sesgo=e.mean(), MAE=e.abs().mean(), RMSE=np.sqrt((e ** 2).mean()),
        max_err=e[e.abs().idxmax()], idx_max=e.abs().idxmax(),
        pendiente=b, intercepto=a, R2_pearson=np.corrcoef(p, r)[0, 1] ** 2,
        RMSE_ajustado=np.sqrt(((a + b * p - r) ** 2).mean()))


def metricas(df, ref='Isp_BKW'):
    """Imprime los estadísticos de Ve de CEA frente a una referencia.

    Se evalúan ``Ve_CEA_<h>`` (balance de entalpía) y, si existe,
    ``Isp_amb_<h>_kms`` (``estimate_Ambient_Isp``). También se imprime
    la mayor diferencia entre ambas, que debe ser despreciable cuando
    la presión ambiente es la de salida.

    Args:
        df (pandas.DataFrame): Resultado de ``calcular_cea`` con la
            columna de referencia.
        ref (str): Columna de referencia, en km/s.

    Raises:
        KeyError: Si faltan ``ref`` o las columnas ``Ve_CEA_<h>``.
    """
    print(f'Referencia: {ref} (km/s)')
    for h in HIPOTESIS:
        for col in (f'Ve_CEA_{h}', f'Isp_amb_{h}_kms'):
            if col not in df:
                continue
            s = estadisticos(df[ref], df[col])
            print(f"{col:28s} n={s['n']}  sesgo={s['sesgo']:+.4f}  "
                  f"MAE={s['MAE']:.4f}  RMSE={s['RMSE']:.4f}  "
                  f"max={s['max_err']:+.4f} km/s  R2={s['R2']:.4f}")
        if f'Isp_amb_{h}_kms' in df:
            d = (df[f'Isp_amb_{h}_kms'] - df[f'Ve_CEA_{h}']).abs().max()
            print(f"{'':28s} max |Isp_amb - Ve_CEA| = {d:.5f} km/s")


def graficar_comparacion(df, ref='Isp_BKW', pred='Ve_CEA_Equilibrium',
                         color_por='Tipo', etiqueta='Compuesto',
                         unidades='km/s', titulo=None, ajuste=False):
    """Dibuja la dispersión ``pred`` frente a ``ref`` con estadísticos.

    Incluye la recta y = x, el cuadro de estadísticos (n, R2, RMSE,
    MAE, sesgo y error máximo) y señala el punto de mayor error.

    Args:
        df (pandas.DataFrame): Datos con las columnas ``ref`` y
            ``pred``.
        ref (str): Columna de referencia (eje x).
        pred (str): Columna predicha (eje y).
        color_por (str | None): Columna categórica para colorear los
            puntos; se omite si no existe.
        etiqueta (str): Columna con el nombre del punto de mayor
            error; si no existe se usa el índice.
        unidades (str): Unidades de ``ref`` y ``pred`` para las
            etiquetas.
        titulo (str | None): Título; por defecto ``"<pred> vs <ref>"``.
        ajuste (bool): Si es ``True``, dibuja también la recta
            ``ref = intercepto + pendiente * pred`` y añade su
            pendiente, intercepto, r2 de Pearson y RMSE recalibrado.

    Raises:
        KeyError: Si faltan ``ref`` o ``pred`` en ``df``.
    """
    s = estadisticos(df[ref], df[pred])
    d = df.dropna(subset=[ref, pred])
    fig, ax = plt.subplots(figsize=(8, 7))
    grupos = d.groupby(color_por) if color_por in d else [(None, d)]
    for nombre, g in grupos:
        ax.scatter(g[ref], g[pred], s=35, alpha=.8, label=nombre)
    lim = [min(d[ref].min(), d[pred].min()),
           max(d[ref].max(), d[pred].max())]
    margen = 0.03 * (lim[1] - lim[0])
    lim = [lim[0] - margen, lim[1] + margen]
    ax.plot(lim, lim, 'k--', lw=1, label='y = x')
    if ajuste:
        xs = np.array(lim)
        ax.plot(xs, (xs - s['intercepto']) / s['pendiente'], 'r-',
                lw=1.5, label='Ajuste lineal')
    i = s['idx_max']
    nombre_max = d.loc[i, etiqueta] if etiqueta in d else i
    ax.annotate(f"{nombre_max}\n(error máx {s['max_err']:+.3f})",
                (d.loc[i, ref], d.loc[i, pred]), xytext=(0.30, 0.10),
                textcoords='axes fraction', fontsize=9,
                arrowprops=dict(arrowstyle='->'))
    texto = (f"n = {s['n']}\nR² = {s['R2']:.4f}\n"
             f"RMSE = {s['RMSE']:.4f} {unidades}\n"
             f"MAE = {s['MAE']:.4f} {unidades}\n"
             f"Sesgo = {s['sesgo']:+.4f} {unidades}\n"
             f"Error máx = {s['max_err']:+.4f} {unidades}")
    if ajuste:
        texto += (f"\n\nAjuste: {ref} = {s['intercepto']:+.4f} + "
                  f"{s['pendiente']:.4f}·{pred}\n"
                  f"r² (Pearson) = {s['R2_pearson']:.4f}\n"
                  f"RMSE recalibrado = {s['RMSE_ajustado']:.4f} "
                  f"{unidades}")
    ax.text(0.03, 0.97, texto, transform=ax.transAxes, va='top',
            fontsize=10, bbox=dict(boxstyle='round', fc='white', ec='gray'))
    ax.set(xlim=lim, ylim=lim, xlabel=f'{ref} ({unidades})',
           ylabel=f'{pred} ({unidades})', title=titulo or f'{pred} vs {ref}')
    ax.set_aspect('equal')
    ax.grid(alpha=.3)
    ax.legend(loc='lower right', fontsize=8)
    plt.tight_layout()
    plt.show()


def barrido_pc(ruta, pcs=(60, PC_1000PSI, 78, 100, 125, 150, 200),
               pe_bar=ATM_BAR, ref='Isp_BKW', **columnas):
    """Evalúa Ve de CEA frente a una referencia para varias Pc.

    Args:
        ruta (str | os.PathLike): CSV de entrada (ver
            ``calcular_cea``) que incluye la columna ``ref``.
        pcs (iterable[float]): Presiones de cámara, bar.
        pe_bar (float): Presión de salida, bar.
        ref (str): Columna de referencia, en km/s.
        **columnas: ``col_compuesto``, ``col_formula`` y
            ``col_deltah``, que se pasan a ``calcular_cea``.

    Returns:
        pandas.DataFrame: Una fila por presión e hipótesis, con las
        columnas ``Pc_bar``, ``hipotesis``, ``n``, ``sesgo``, ``MAE``,
        ``RMSE``, ``R2`` y ``RMSE_ajustado`` (ver ``estadisticos``).
    """
    filas = []
    for pc in pcs:
        df = calcular_cea(ruta, pc_bar=pc, pe_bar=pe_bar, **columnas)
        for h in HIPOTESIS:
            s = estadisticos(df[ref], df[f'Ve_CEA_{h}'])
            claves = ('n', 'sesgo', 'MAE', 'RMSE', 'R2', 'RMSE_ajustado')
            filas.append({'Pc_bar': round(pc, 2), 'hipotesis': h,
                          **{k: s[k] for k in claves}})
    return pd.DataFrame(filas)


def mapa_correlaciones(df, hipotesis='Equilibrium', metodo='pearson',
                       columnas=None, titulo=None):
    """Dibuja el mapa de correlaciones de las variables de energía.

    Muestra solo el triángulo inferior, sin pares repetidos. Por
    defecto incluye ``Q``, ``Ng``, ``Isp_BKW``, las variables de
    cámara (``h_c``, ``Hf`` de los productos, ``Q_c``), las de salida
    de la hipótesis elegida (``h_e``, ``Hf`` de los productos, ``Q_e``),
    ``ve2_2`` = ``h_c - h_e`` (energía cinética, kJ/kg) y la
    composición por fases: moles de gas y de condensado por kg, masa
    molar media del gas y fracción en masa de gas, en cámara y, solo
    si existen (equilibrio), en la salida.

    Args:
        df (pandas.DataFrame): Resultado de ``calcular_cea`` con las
            columnas ``Q``, ``Ng`` e ``Isp_BKW``.
        hipotesis (str): ``'Equilibrium'`` o ``'Frozen'``.
        metodo (str): ``'pearson'``, ``'spearman'`` o ``'kendall'``.
        columnas (list[str] | None): Columnas a correlacionar; por
            defecto las indicadas arriba. Puede incluir ``'ve2_2'``.
        titulo (str | None): Título del gráfico.

    Returns:
        pandas.DataFrame: Submatriz de correlaciones mostrada.

    Raises:
        KeyError: Si faltan las columnas necesarias en ``df``.
    """
    h = hipotesis
    d = df.assign(ve2_2=df['h_c_kJ_kg'] - df[f'h_e_{h}_kJ_kg'])
    etiq = {'Q': 'Q (BKW)', 'Ng': 'Ng', 'Isp_BKW': 'Isp_BKW',
            'h_c_kJ_kg': 'h_c', 'Hf_prod_camara_kJ_kg': 'Hf prod. cámara',
            'Q_c_kJ_kg': 'Q_c', f'h_e_{h}_kJ_kg': 'h_e',
            f'Hf_prod_salida_{h}_kJ_kg': 'Hf prod. salida',
            f'Q_e_{h}_kJ_kg': 'Q_e', 've2_2': 've²/2',
            'n_gas_camara_mol_kg': 'n gas cámara',
            'n_cond_camara_mol_kg': 'n cond. cámara',
            'M_gas_camara_g_mol': 'M gas cámara',
            'fm_gas_camara': 'fm gas cámara'}
    if f'n_gas_salida_{h}_mol_kg' in d:
        etiq.update({f'n_gas_salida_{h}_mol_kg': 'n gas salida',
                     f'n_cond_salida_{h}_mol_kg': 'n cond. salida',
                     f'M_gas_salida_{h}_g_mol': 'M gas salida',
                     f'fm_gas_salida_{h}': 'fm gas salida'})
    cols = columnas or list(etiq)
    lado = max(8, 0.55 * len(cols) + 3)
    letra = 10 if len(cols) <= 12 else 8
    # Se omiten la primera fila y la última columna (pares repetidos).
    c = d[cols].corr(method=metodo).iloc[1:, :-1]
    mascara = np.triu(np.ones(c.shape, bool), k=1)
    fig, ax = plt.subplots(figsize=(lado + 1.5, lado))
    im = ax.imshow(np.ma.array(c.values, mask=mascara), cmap='RdBu_r',
                   vmin=-1, vmax=1)
    for i in range(c.shape[0]):
        for j in range(i + 1):
            ax.text(j, i, f'{c.iat[i, j]:.2f}', ha='center', va='center',
                    fontsize=letra,
                    color='white' if abs(c.iat[i, j]) > 0.6 else 'black')
    ax.set_xticks(range(c.shape[1]))
    ax.set_xticklabels([etiq.get(k, k) for k in c.columns],
                       rotation=45, ha='right')
    ax.set_yticks(range(c.shape[0]))
    ax.set_yticklabels([etiq.get(k, k) for k in c.index])
    ax.set_xticks(np.arange(-.5, c.shape[1]), minor=True)
    ax.set_yticks(np.arange(-.5, c.shape[0]), minor=True)
    ax.grid(which='minor', color='white', lw=2)
    ax.tick_params(which='minor', length=0)
    fig.colorbar(im, ax=ax, shrink=.8,
                 label=f'Correlación de {metodo.capitalize()}')
    n = int(d[cols].dropna().shape[0])
    ax.set_title(titulo or f'Correlaciones - expansión en {h} (n = {n})',
                 fontweight='bold')
    fig.text(0.5, 0.01, 'Energías en kJ/kg; n en mol/kg; M en g/mol; '
             'fm sin unidades; Isp_BKW en km/s; '
             'Q y Ng: columnas del fichero de datos',
             ha='center', fontsize=8)
    plt.tight_layout(rect=(0, 0.03, 1, 1))
    plt.show()
    return c


def barrido_composicion(al=range(12, 25), htpb=14, pc_bar=PC_1000PSI,
                        pe_bar=ATM_BAR):
    """Evalúa propelentes AP/Al/HTPB variando el contenido de Al.

    El HTPB se mantiene fijo y el Al aumenta a costa del AP:
    ``AP = 100 - Al - HTPB`` (% en masa). Datos de los componentes:
    AP (``NH4CLO4(I)``) de ``thermo.inp``; Al con entalpía de formación
    nula; HTPB (``C 7.3165 H 10.3360 O 0.1063``, ``h,cal = 1200`` por
    esa fórmula) de la tarjeta R-45 de RocketCEA.

    Args:
        al (iterable[float]): Contenidos de Al, % en masa.
        htpb (float): Contenido de HTPB, % en masa.
        pc_bar (float): Presión de cámara, bar.
        pe_bar (float): Presión de salida, bar.

    Returns:
        pandas.DataFrame: Una fila por contenido de Al, con ``AP``,
        ``Al``, ``HTPB`` (% en masa), las columnas de
        ``calcular_cea`` e ``Isp_<h>_s`` (s) para ``<h>`` =
        ``Equilibrium`` y ``Frozen``.

    Raises:
        ValueError: Si ``AP = 100 - Al - HTPB`` no es positivo.
    """
    filas = []
    for a in al:
        ap = 100 - a - htpb
        if ap <= 0:
            raise ValueError(f'AP = {ap} % no es positivo (Al = {a} %, '
                             f'HTPB = {htpb} %)')
        nombre = f'AP{ap}_Al{a}'
        tarjeta = '\n'.join([
            f'name NH4CLO4(I) wt%={ap} t(k)=298.15',
            f'name Aluminum AL 1 wt%={a}',
            'h,cal=0.0 t(k)=298.15',
            f'name HTPB C 7.3165 H 10.3360 O 0.1063 wt%={htpb}',
            'h,cal=1200.0 t(k)=298.15'])
        add_new_propellant(nombre, '\n' + tarjeta)
        filas.append({'AP': ap, 'Al': a, 'HTPB': htpb,
                      **_resultados(_cea(nombre), pc_bar, pe_bar)})
    df = pd.DataFrame(filas)
    for h in HIPOTESIS:
        df[f'Isp_{h}_s'] = df[f'Ve_CEA_{h}'] * 1e3 / G0
    return df


def barrido_mr(ox='LOX', fuel='LH2', mr=None, pc_bar=PC_1000PSI,
               pe_bar=ATM_BAR):
    """Evalúa un biergol frente a la relación de mezcla O/F.

    Imprime el MR óptimo y el Isp máximo de cada hipótesis.

    Args:
        ox (str): Oxidante, nombre de la base de datos de RocketCEA.
        fuel (str): Combustible, nombre de la base de datos de
            RocketCEA.
        mr (iterable[float] | None): Relaciones O/F; por defecto 50
            valores entre 3 y 8.
        pc_bar (float): Presión de cámara, bar.
        pe_bar (float): Presión de salida, bar.

    Returns:
        pandas.DataFrame: Una fila por MR, con ``MR``, ``Ve_<h>_kms``
        (km/s) e ``Isp_<h>_s`` (s) para ``<h>`` = ``Equilibrium`` y
        ``Frozen``. Valen NaN donde CEA no converge.
    """
    mr = np.linspace(3.0, 8.0, 50) if mr is None else mr
    cea = CEA_Obj(oxName=ox, fuelName=fuel, pressure_units='Bar',
                  temperature_units='K', enthalpy_units='J/kg')
    filas = []
    for m in mr:
        fila = {'MR': m}
        for h, fr in HIPOTESIS.items():
            r = _expansion(cea, pc_bar, pe_bar, m, fr)
            fila[f'Ve_{h}_kms'] = r['ve'] if r else np.nan
            fila[f'Isp_{h}_s'] = r['ve'] * 1e3 / G0 if r else np.nan
        filas.append(fila)
    df = pd.DataFrame(filas)
    print(f'=== {ox}/{fuel} (Pc={pc_bar:g} bar, Pe={pe_bar:g} bar) ===')
    for h in HIPOTESIS:
        if df[f'Isp_{h}_s'].notna().any():
            o = df.loc[df[f'Isp_{h}_s'].idxmax()]
            print(f"{h:12s} MR óptimo = {o['MR']:.2f}   "
                  f"Isp = {o[f'Isp_{h}_s']:.1f} s "
                  f"({o[f'Ve_{h}_kms']:.3f} km/s)")
    return df


def graficar_mr(df, titulo='Isp vs MR', mr_estq=None):
    """Dibuja las curvas Isp(MR) de ``barrido_mr``.

    Args:
        df (pandas.DataFrame): Resultado de ``barrido_mr``.
        titulo (str): Título del gráfico.
        mr_estq (float | None): MR estequiométrico; si se indica, se
            dibuja como línea vertical (p. ej. 7.94 en LOX/LH2).

    Raises:
        KeyError: Si faltan las columnas ``MR`` o ``Isp_<h>_s``.
    """
    plt.figure(figsize=(10, 6))
    for h, color, ls in (('Equilibrium', 'blue', '-'),
                         ('Frozen', 'red', '--')):
        col = f'Isp_{h}_s'
        plt.plot(df['MR'], df[col], color=color, ls=ls, lw=2, label=h)
        if df[col].notna().any():
            o = df.loc[df[col].idxmax()]
            plt.scatter(o['MR'], o[col], color=color, s=100, zorder=5,
                        label=(f"Máx {h} (MR={o['MR']:.2f}, "
                               f"Isp={o[col]:.1f} s)"))
    if mr_estq:
        plt.axvline(mr_estq, color='gray', ls=':',
                    label=f'Estequiométrica (MR={mr_estq:g})')
    plt.title(titulo, fontsize=14, fontweight='bold')
    plt.xlabel('Relación de mezcla O/F (MR)')
    plt.ylabel('Isp (s)')
    plt.grid(alpha=.3)
    plt.legend(loc='lower center', bbox_to_anchor=(0.5, -0.25), ncol=2)
    plt.tight_layout()
    plt.show()


def main(argv=None):
    """Calcula con CEA los propelentes de un CSV y guarda el resultado.

    Si el CSV tiene la columna ``Isp_BKW``, imprime además las métricas
    de Ve de CEA frente a ella.

    Args:
        argv (list[str] | None): Argumentos de la línea de comandos;
            ``None`` usa ``sys.argv[1:]``.

    Returns:
        int: Código de salida (0 si termina sin error).
    """
    parser = argparse.ArgumentParser(
        description='Ve, temperaturas, energías y composición con CEA '
                    '(equilibrio y congelado).')
    parser.add_argument('entrada', help='CSV con la fórmula y la entalpía '
                        'de formación (kcal/mol, 298,15 K)')
    parser.add_argument('--salida',
                        default='Impulso_data_con_CEA_hipotesis_'
                                'comparativa.csv',
                        help='CSV de salida')
    parser.add_argument('--pc-bar', type=float, default=PC_1000PSI,
                        help='presión de cámara, bar (por defecto '
                             '1000 psi)')
    parser.add_argument('--pe-bar', type=float, default=ATM_BAR,
                        help='presión de salida, bar (por defecto 1 atm '
                             '= 1.01325)')
    parser.add_argument('--pamb-bar', type=float, default=None,
                        help='presión ambiente para estimate_Ambient_Isp, '
                             'bar (por defecto, la de salida)')
    parser.add_argument('--col-compuesto', default='Compuesto',
                        help='columna con el nombre del compuesto (opcional; '
                             'por defecto Compuesto)')
    parser.add_argument('--col-formula', default='Formula',
                        help='columna con la fórmula (por defecto Formula)')
    parser.add_argument('--col-deltah', default='DeltaH',
                        help='columna con la entalpía de formación, '
                             'kcal/mol a 298,15 K (por defecto DeltaH)')
    args = parser.parse_args(argv)
    try:
        df = calcular_cea(args.entrada, pc_bar=args.pc_bar,
                          pe_bar=args.pe_bar, pamb_bar=args.pamb_bar,
                          col_compuesto=args.col_compuesto,
                          col_formula=args.col_formula,
                          col_deltah=args.col_deltah)
    except (KeyError, ValueError) as e:
        print(f'ERROR: {e}')
        return 1
    df.to_csv(args.salida, index=False)
    for ref in ('Isp_BKW', 'Isp_Doc'):
        if ref in df:
            metricas(df, ref)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
