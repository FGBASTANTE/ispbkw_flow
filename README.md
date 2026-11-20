<p align="center">
  <img src="docs/logo_ispbkw_flow_texto.svg" alt="ispbkw_flow" width="440">
</p>

# ispbkw_flow

*Batch specific-impulse calculations with Mader's ISPBKW code, from a CSV
of propellants to clear result tables, with NASA CEA (RocketCEA) for
comparison.*

Utilidades para calcular el impulso específico con ISPBKW (código BKW de
Mader).

Conjunto de scripts para calcular por lotes el impulso específico de
explosivos y propelentes con **ISPBKW**, la versión del código BKW de
C. L. Mader que resuelve la combustión y la expansión en tobera con la
ecuación de estado BKW.

Los scripts automatizan las cuatro etapas del proceso:

1. Preparar la entalpía de entrada en la referencia que usa ISPBKW.
2. Escribir los propelentes en la base de componentes de USERBKW.
3. Generar los ficheros de entrada con USERBKW y ejecutar ISPBKW.
4. Reunir los resultados en un único CSV.

> **Importante.** USERBKW, ISPBKW y sus bases de datos (`zzztherc`,
> `zzzsoleq`...) son © Mader Consulting Co. y **no se incluyen en este
> repositorio**. Los códigos de Mader se distribuyen, en FORTRAN y
> ejecutables, en el CD-ROM de su libro (ver Referencias)

---

## Contenido

| Fichero | Lenguaje | Función |
|---|---|---|
| `calcular_isp.py` | Python | Ejecuta todo el proceso a partir de un CSV y une los resultados a los datos de entrada. |
| `formula_quimica.py` | Python | Módulo común: lectura de fórmulas químicas y masas atómicas (las de NASA CEA). Lo importan `eo_0k.py` y `zzzcomps.py`. |
| `eo_0k.py` | Python | Calcula `eo_ISPBKW`, la entalpía del propelente en la referencia de ISPBKW (elementos a 0 K), a partir de la entalpía de formación a 298,15 K. |
| `zzzcomps.py` | Python | Escribe los propelentes de un CSV en el formato del fichero `zzzcomps` de USERBKW, con los nombres `exp1`, `exp2`..., y la tabla de correspondencia `zzzcomps_nombres.csv`. |
| `plantilla_userbkw.txt` | Texto | Respuestas que se envían a USERBKW por la entrada estándar para crear el fichero de entrada de un propelente. |
| `procesar_ispbkw.ps1` | PowerShell | Ejecuta USERBKW e ISPBKW para cada propelente `expN` y, opcionalmente, el extractor. |
| `extraer_composicion.py` | Python | Revisa los `.out` de ISPBKW (errores y avisos de convergencia) y genera `resultados.csv`. |
| `impulso_cea.py` | Python | Cálculo independiente con NASA CEA (RocketCEA) a partir del mismo CSV, con funciones de comparación y análisis (ver [Cálculo con NASA CEA](#cálculo-con-nasa-cea-impulso_ceapy)). |

Programas y ficheros de terceros necesarios (no incluidos):

| Fichero | Función |
|---|---|
| `userbkw.exe` | Generador interactivo del fichero de entrada de BKW (`program makedeck`). |
| `abispbkw.exe` | ISPBKW compilado. Lee siempre `bkwdata` y escribe siempre `isp.out`. |
| `zzztherc`, `zzzsoleq` | Datos termodinámicos de los productos gaseosos y sólidos. |
| `zzzdecks` | Lista de ficheros que mantiene USERBKW (lo crea si no existe). |

---

## Requisitos

- **Windows** con PowerShell 5.1 o posterior (los ejecutables son de Windows).
- **Python 3** en el `PATH`, con **pandas** para `eo_0k.py` y `zzzcomps.py`.
  `extraer_composicion.py` solo usa la biblioteca estándar.
- Los scripts de Python deben estar en la misma carpeta (se importan
  entre sí).
- Solo para `impulso_cea.py`: **RocketCEA**, **numpy** y **matplotlib**.
  El flujo de ISPBKW no los necesita.

---

## Flujo de trabajo

```
energ_mat.csv                       CSV con Formula y DeltaH (kcal/mol, 298,15 K)
   │  eo_0k.py
   ▼
energ_mat_eo0K.csv                  + columnas eo_ISPBKW y DeltaH_0K_est
   │  zzzcomps.py --columna eo_ISPBKW
   ▼
zzzcomps, zzzcomps_nombres.csv         exp1 ... expN y su correspondencia
   │  procesar_ispbkw.ps1  (plantilla_userbkw.txt → userbkw.exe → abispbkw.exe)
   ▼
userdata\expN, userdata\expN.out       fichero de entrada y resultado de cada propelente
   │  extraer_composicion.py  (opción -Extraer)
   ▼
resultados\resultados.csv              una fila por propelente
```

Carpeta de trabajo para el paso 3 (el script trabaja siempre desde su
propia carpeta):

```
carpeta_trabajo\
├── procesar_ispbkw.ps1
├── plantilla_userbkw.txt
├── extraer_composicion.py
├── zzzcomps                 generado en el paso 2
├── zzzcomps_nombres.csv     generado en el paso 2 (opcional, recomendado)
├── userbkw.exe              no incluido
├── abispbkw.exe             no incluido
├── zzztherc, zzzsoleq       no incluidos
├── userdata\                se crea al ejecutar
└── resultados\              se crea con -Extraer
```

### Ejecución completa con `calcular_isp.py`

```bat
python calcular_isp.py energ_mat.csv --trabajo C:\bkw
```

`--trabajo` es la carpeta con `userbkw.exe`, `abispbkw.exe`, `zzztherc` y
`zzzsoleq`; si en ella faltan `procesar_ispbkw.ps1` o `plantilla_userbkw.txt`, se
copian desde el repositorio. El script:

1. Lee y valida el CSV: columnas, valores vacíos, fórmulas, elementos
   admitidos y mezclas cuya masa no sea ≈ 100 g (aviso). Solo son
   obligatorias `Formula` y `DeltaH`; el resto se copian al resultado.
   Las columnas de entrada con el nombre de una de resultados (`T`,
   `estado`, `material`, `at_C`, `h2o_moles`...) se renombran con el
   sufijo `_entrada`, con un aviso.
2. Desglosa cada fórmula en elementos (`at_C`, `at_H`...) y calcula su
   masa (`M_g_mol`).
3. Calcula `eo_ISPBKW` y guarda los datos usados en `datos_eo0K.csv`.
4. Escribe `zzzcomps` y `zzzcomps_nombres.csv`.
5. Ejecuta `procesar_ispbkw.ps1` (USERBKW → `bkwdata` → ISPBKW → `.out`).
   Por defecto archiva la carpeta `userdata` anterior y calcula todo.
6. Extrae los resultados de los `.out`.
7. Une los resultados a los datos de entrada por nombre y escribe las
   salidas (ver más abajo). Al terminar, lista los casos con estado
   distinto de `ok` y el motivo.
8. Recoge en `files_HHMMSS_AAAAMMDD` (hora y fecha de inicio), dentro de
   la carpeta de trabajo, todo lo que el proceso ha creado o modificado
   en ella: `userdata`, `resultados`, `bkwdata`, `datos_eo0K.csv`,
   `zzzcomps_nombres.csv`, los `zzzcomps` y `zzzdecks` usados, las
   carpetas `userdata_*` archivadas y las salidas si se escribieron allí.
   `procesar_ispbkw.ps1` y `plantilla_userbkw.txt` se quedan en la carpeta de trabajo,
   también si se han copiado en esta ejecución. `zzzcomps` y `zzzdecks` se restauran como
   estaban, de modo que la carpeta de trabajo queda como al empezar.

Si el proceso falla, los ficheros quedan en la carpeta de trabajo para
poder seguir con `--continuar`. El estado inicial de la carpeta se
registra en `calcular_isp.estado` y las copias de `zzzcomps` y
`zzzdecks` en `*.anterior`; así, la recogida final es la misma aunque el
proceso se complete en varias ejecuciones. Con `--preparar` tampoco se
recoge nada.

| Opción | Descripción |
|---|---|
| `--trabajo` | Carpeta de los programas de Mader (por defecto, la actual). |
| `--salida` | Ruta base de las salidas, sin extensión (por defecto `<entrada>_ISPBKW`). |
| `--columna-fijo`, `--valor-fijo` | Densidad para `zzzcomps` (por defecto 1,0). |
| `--continuar` | No archiva `userdata`: solo calcula los casos que falten. Exige los mismos datos; si cambian, el script se detiene. |
| `--preparar` | Solo escribe `zzzcomps`, sin ejecutar los programas de Mader. |
| `--powershell` | Ejecutable de PowerShell (por defecto `powershell`; `pwsh` para PowerShell 7). |
| `--col-compuesto` | Columna con el nombre del compuesto (por defecto `Compuesto`; opcional). |
| `--col-formula` | Columna con la fórmula (por defecto `Formula`). |
| `--col-deltah` | Columna con la entalpía de formación, kcal/mol a 298,15 K (por defecto `DeltaH`). |

Si el fichero tiene además una columna llamada `Compuesto`, `Formula` o
`DeltaH` que no es la elegida, se renombra con el sufijo `_entrada`.

Desde Python: `from calcular_isp import calcular_isp` y
`df = calcular_isp('energ_mat.csv', r'C:\bkw')` (devuelve el resumen).

### Salidas de `calcular_isp.py`

| Fichero | Contenido |
|---|---|
| `<base>.csv` | **Resumen**: una fila por propelente. |
| `<base>_productos.csv` | Composición de los productos en la salida, mol por kg de propelente. |
| `<base>_especies.csv` | Entalpía de formación a 0 K de cada producto (cal/mol), una vez por especie. |
| `<base>_avisos.csv` | Iteraciones que ISPBKW aceptó fuera de tolerancia, con su residuo y clasificación. |
| `<base>.xlsx` | Las cuatro tablas anteriores en hojas, más la hoja `Entrada` con los datos originales y `material`. Requiere `openpyxl`; si no está instalado, se avisa y solo se escriben los CSV. |

Columnas del resumen:

| Columna | Unidad | Contenido |
|---|---|---|
| `material` | – | Nombre en `zzzcomps` (`expN`). |
| `Compuesto`, `Formula` | – | Nombre (si existe) y fórmula de la entrada. |
| `M_g_mol` | g/mol | Masa de la fórmula (100 g en las mezclas). |
| `DeltaH_298K_kcal_mol` | kcal/mol | Entalpía de formación de la entrada, a 298,15 K. |
| `eo_ISPBKW_kcal_mol` | kcal/mol | Entalpía usada en el cálculo (`eo`, referencia elementos a 0 K). |
| `Isp_s` | s | Impulso específico. |
| `Isp_km_s` | km/s = N·s/g | `Isp_s · 9,80665 / 1000`. |
| `Tc_K`, `Te_K` | K | Temperaturas de cámara y de salida. |
| `estado` | – | `ok`, `revisar`, `error` o `sin_out` (ver el paso 4). |
| `observaciones` | – | Motivo, si el estado no es `ok`. |

En `<base>_productos.csv`, `gas_mol_kg` son los moles de gas y
`<especie>_mol_kg` los de cada producto; las especies con el mínimo de
ISPBKW (10⁻⁸ mol, ausentes) valen 0. Los CSV usan coma como separador y
punto decimal; para revisar a simple vista, el libro Excel.

### Ejecución paso a paso

```bat
python eo_0k.py energ_mat.csv --salida energ_mat_eo0K.csv
python zzzcomps.py energ_mat_eo0K.csv --columna eo_ISPBKW --salida zzzcomps
powershell -ExecutionPolicy Bypass -File .\procesar_ispbkw.ps1 -Extraer
```

---

## Fichero de datos de entrada

CSV con, al menos, estas columnas:

| Columna | Unidad | Contenido |
|---|---|---|
| `Formula` | – | Fórmula química, p. ej. `C3H6N6O6`. Admite subíndices decimales y paréntesis. |
| `DeltaH` | kcal por mol de la fórmula escrita | Entalpía de formación a 298,15 K. |

En las mezclas la fórmula se escribe referida a 100 g (p. ej.
`C2.03H2.64N2.18O2.67`), y `DeltaH` es entonces kcal por 100 g.
Elementos admitidos: los 17 de USERBKW (**H, Li, Be, B, C, N, O, F,
Na, Mg, Al, Si, P, S, Cl, W y Pb**), como máximo 10 por fórmula.

---

## Paso 1. `eo_0k.py`: entalpía de entrada

ISPBKW toma como referencia los **elementos a 0 K**: las entalpías de
los productos son `Hf(0 K) + [H(T) − H(0)]`, y el impulso se calcula a
partir de la diferencia de entalpías entre la cámara y la salida. Por
eso la entalpía del propelente (`eo`) debe darse en esa misma
referencia; introducir `DeltaH` a 298,15 K directamente subestima la
energía disponible y el impulso (del orden de un 2 % de media).

Para un propelente inicialmente a 298,15 K (la misma condición que
NASA CEA), el valor correcto es exacto y no depende de la capacidad
calorífica del propelente:

```
eo = ΔHf(298,15 K) + Σ νi · [H298 − H0](elemento i)
```

con `[H298 − H0]` del estado de referencia de cada elemento tomado de la
base termodinámica de NASA CEA (`thermo.inp`), la misma que usa CEA:

| Elemento | Referencia | [H298 − H0] (J por átomo-gramo) |
|---|---|---|
| H | H2/2 | 4234,05 |
| C | grafito | 1053,50 |
| N | N2/2 | 4335,05 |
| O | O2/2 | 4340,05 |
| Cl | Cl2/2 | 4590,56 |
| P | P blanco | 5360,00 |
| Li | Li(cr) | 4632,00 |
| Be | Be(a) | 1942,07 |
| B | B(b) | 1214,00 |
| F | F2/2 | 4412,55 |
| Na | Na(cr) | 6460,00 |
| Mg | Mg(cr) | 4979,16 |
| Al | Al(cr) | 4540,00 |
| Si | Si(cr) | 3217,47 |
| S | S(a) | 4412,00 |
| W | W(cr) | 4973,00 |
| Pb | Pb(cr) | 6870,00 |

Con esa misma base, las entalpías de formación a 0 K de los productos
principales coinciden con las de `zzztherc` en pocas cal/mol (H2O,
CO2, CO, HCl), lo que confirma que ISPBKW usa los elementos a 0 K como
referencia.

```bat
python eo_0k.py energ_mat.csv --salida energ_mat_eo0K.csv
```

Columnas añadidas:

| Columna | Unidad | Uso |
|---|---|---|
| `eo_ISPBKW` | cal por peso de fórmula | **Entrada de ISPBKW.** Propelente a 298,15 K; exacta. |
| `DeltaH_0K_est` | kcal por mol de fórmula | Entalpía de formación a 0 K en sentido estricto (propelente a 0 K). Estimada con la regla de Kopp modificada (Hurst y Harrison, 1992); solo informativa. |

ISPBKW imprime `eo` con la etiqueta *"Heat of Formation at 0 deg K"*,
aunque con `eo_ISPBKW` es la entalpía del propelente a 298,15 K
referida a los elementos a 0 K.

---

## Paso 2. `zzzcomps.py`: base de componentes de USERBKW

```bat
python zzzcomps.py energ_mat_eo0K.csv --columna eo_ISPBKW --salida zzzcomps
```

| Opción | Por defecto | Descripción |
|---|---|---|
| `--columna` | `eo_ISPBKW` | Columna de entalpía. `DeltaH` y `DeltaH_0K_est` se multiplican por 1000 (kcal → cal). |
| `--factor` | automático | Factor para pasar otra columna a cal por mol de fórmula. |
| `--columna-fijo` | – | Columna de la que se toma el segundo campo (densidad). |
| `--valor-fijo` | `1.0` | Valor del segundo campo si no se usa `--columna-fijo`. |
| `--prefijo` | `exp` | Prefijo de los nombres. |
| `--crlf` / `--lf` | `--crlf` | Fin de línea. Con LF, USERBKW no lee el último componente. |
| `--salida` | `zzzcomps` | Fichero de salida. |
| `--tabla` | `<salida>_nombres.csv` | Tabla de correspondencia de nombres. |

Formato (ancho fijo, formatos FORTRAN de USERBKW `(1x,a20,2e18.11)` y
`(1x,a20,e18.11)`):

```
 exp1                 1.00000000000E+00-0.10275330000E+06
 c                    0.50000000000E+01
 h                    0.80000000000E+01
 n                    0.40000000000E+01
 o                    0.12000000000E+02
 zzz                  0.31613500000E+03
```

- Línea 1: nombre, densidad (g/cm³, `1PE18.11`) y entalpía (cal por mol de fórmula, `E18.11`).
- Una línea por elemento, en minúsculas, con los átomos por fórmula.
- `zzz` y la masa de la fórmula (g/mol), calculada con las masas atómicas de NASA CEA (H 1,00794; C 12,0107; N 14,0067; O 15,9994; Cl 35,453; P 30,973761; resto de elementos en `formula_quimica.py`). USERBKW solo la usa para calcular la densidad (y las cantidades en gramos). La masa molecular que escribe en el fichero de entrada de ISPBKW, y con la que este pasa las energías a cal/g, la recalcula con su propia tabla de masas atómicas (H 1,00797; C 12,01115; N 14,0067; O 15,9994); la diferencia es del orden del 0,001 %.

Los nombres `expN` siguen el orden de las filas del CSV: `exp1` es la
primera fila. La tabla `zzzcomps_nombres.csv` guarda esa
correspondencia (`material`, `Tipo`, `Compuesto`, `Formula`) junto con
la columna de entalpía usada y los valores escritos; el extractor la
usa para unir los resultados por nombre. El fichero generado
**sustituye** al `zzzcomps` de la distribución; conviene guardar una
copia del original.

Con un valor razonable, la densidad apenas influye en el impulso: solo
entra en el término `pc·v0` del balance de la cámara (≈ 1,6 cal/g con
1 g/cm³, frente a 1000–2000 cal/g de salto de entalpía). Un valor
absurdo, en cambio, impide el cálculo (ver el paso 3).

---

## Paso 3. `procesar_ispbkw.ps1`: ejecución por lotes

```bat
powershell -ExecutionPolicy Bypass -File .\procesar_ispbkw.ps1 [-Modo ambos|user|bkw] [-Casos 1..10] [-Extraer] [-Reiniciar]
```

| Parámetro | Descripción |
|---|---|
| `-Modo` | `ambos` (por defecto): pasos 1 a 3. `user`: pasos 1 y 2. `bkw`: paso 3 sobre los `expN` que ya existan en `userdata\`. |
| `-Casos` | Casos a procesar: `1..10`, `3,7,12`, `1..5,9`. Por defecto, todos los `expN` de `zzzcomps`. |
| `-Extraer` | Ejecuta el extractor al terminar. |
| `-Reiniciar` | Renombra `userdata\` a `userdata_AAAAMMDD_HHMMSS` (no borra nada) y empieza con la carpeta vacía. |

Antes de calcular, el script se detiene con un mensaje si:

- `zzzcomps` no existe, no tiene fin de línea CR LF o repite algún nombre;
- algún caso pedido no está en `zzzcomps` (USERBKW pasaría a modo
  interactivo y escribiría en `zzzcomps`);
- `userdata\` contiene resultados generados con otros `zzzcomps`,
  `plantilla_userbkw.txt`, primera línea o con una versión anterior del script. La
  comprobación usa la huella SHA-256 guardada en
  `userdata\huella.txt`; en ese caso hay que usar `-Reiniciar`.

Para cada caso `expN`:

1. Envía a `userbkw.exe` las líneas de `plantilla_userbkw.txt` que no son
   comentarios, sustituyendo cada línea `exp1` por `expN`. USERBKW
   genera el fichero de entrada `expN`, que se mueve a `userdata\`.
2. Sustituye la primera línea de `userdata\expN` por
   `0002 0001 0000 0001 0001 0000 0000`. El primer campo (`ioeq = 2`)
   activa el cálculo del impulso; el programa termina al acabarlo, por
   lo que los demás campos no intervienen.

   Además, escribe la densidad de `zzzcomps` en la línea de densidad,
   masa molecular y `eo` del fichero. USERBKW calcula la densidad con
   dos variables que no inicializa (`totwht` y `totvol`, en
   `subroutine getcomps`), así que a veces la escribe con un valor
   absurdo (se ha observado 1,1·10⁻³¹ g/cm³). Con él, ISPBKW no
   converge: tarda mucho y da NaN. Con un solo componente (1 mol, como
   en `plantilla_userbkw.txt`), la densidad correcta es la de `zzzcomps`. La
   sustitución solo se hace si los moles del fichero coinciden con los
   del componente; si no, se avisa y el fichero no se toca. Cada
   corrección se indica en pantalla.
3. Copia `expN` como `bkwdata`, ejecuta `abispbkw.exe` y guarda
   `isp.out` como `userdata\expN.out`.
4. Con `-Extraer`, ejecuta `extraer_composicion.py userdata resultados`,
   con `--nombres zzzcomps_nombres.csv` si la tabla existe.

Variables de configuración al inicio del script:

| Variable | Valor | Descripción |
|---|---|---|
| `$pausa` | `0.2` | Segundos entre líneas enviadas a USERBKW. |
| `$primeraLinea` | `0002 0001 ...` | Primera línea del fichero de entrada de ISPBKW. |
| `$python` | `python` | Intérprete de Python. |

El script **no sobrescribe**: si ya existe `userdata\expN` o
`userdata\expN.out`, avisa y pasa al siguiente caso. Para repetir un
caso concreto hay que borrar antes sus ficheros; para repetir todo,
`-Reiniciar`.

### `plantilla_userbkw.txt`

Las líneas que empiezan por `#` son comentarios y no se envían.

| Línea | Significado en USERBKW |
|---|---|
| `1` | Crear un fichero de entrada nuevo. |
| `3` | Añadir 1 mol de un componente. |
| `exp1` | Nombre del componente (se busca en `zzzcomps`). |
| `+` | Terminar la lista de componentes. |
| `exp1` | Título del fichero de entrada. |
| `+` | Página siguiente. |
| `2` | Parámetros de la ecuación BKW: `1` RDX, `2` TNT, `3` introducirlos, `4` mantener los actuales (en un fichero nuevo, los de RDX). |
| `+` (×5) | Aceptar las páginas restantes. |
| `exp1` | Nombre del fichero de entrada que se crea. |
| `4` | Salir de USERBKW. |

Las tres líneas `exp1` se sustituyen por el caso en curso. El conjunto
de parámetros BKW elegido (`2`, TNT, en la versión incluida) debe
indicarse al publicar resultados.

---

## Paso 4. `extraer_composicion.py`: resultados

```bat
python extraer_composicion.py RUTA_OUT [CARPETA_CSV] [--nombres zzzcomps_nombres.csv] [--avisos]
```

Cada `.out` se revisa antes de extraer sus valores:

| `estado` | Significado | Valores numéricos |
|---|---|---|
| `ok` | Sin incidencias, o con iteraciones aceptadas por debajo de su umbral. | Sí |
| `revisar` | Alguna iteración aceptada supera su umbral o no lo tiene definido. | Sí |
| `error` | Mensaje de error de ISPBKW, cálculo incompleto (sin la expansión hasta la salida) o fichero ilegible. El ISP que aparece en estos `.out` no es válido. | Vacíos |
| `sin_out` | Propelente de la tabla de nombres sin fichero `.out`. | Vacíos |

ISPBKW acepta a veces una iteración sin alcanzar su tolerancia
(*"... accepted was"*). Es habitual y casi siempre irrelevante: el
residuo de la temperatura de cámara queda en torno a 0,04 cal por la
precisión simple del programa. Por eso cada iteración se compara con un
umbral (`UMBRALES` en `extraer_composicion.py`):

| Iteración | Residuo | Tolerancia de ISPBKW | Umbral | Efecto del umbral en el ISP |
|---|---|---|---|---|
| `temp err` | Balance de energía en la cámara, cal por peso de fórmula | 0,01 | 10 | < 0,01 % |
| `energy err` | Entropía en la expansión, cal/K por peso de fórmula | 0,1 | 0,2 | ≈ 0,1 % |
| `equil amaxe` | Variación de moles entre iteraciones del equilibrio, mol | – | 10⁻³ | despreciable |
| Otras (`vgas err`, `sys1 amoler`, `sol vol err`...) | – | – | sin umbral | se marcan `revisar` |

La columna `avisos` resume las iteraciones aceptadas (veces y residuo
máximo), y `--avisos` escribe además su detalle en `avisos.csv`.

Sin `--nombres`, las filas siguen el orden natural de los `.out`
(`exp1`, `exp2`, ..., `exp10`). Con `--nombres`, siguen el orden de la
tabla, incluyen sus columnas y aparecen todos los propelentes, también
los que no tienen `.out`. Al terminar se muestra el número de casos de
cada estado.

| Columna | Unidad | Contenido |
|---|---|---|
| `material` | – | Nombre del `.out` (`expN`). |
| `Tipo`, `Compuesto`, `Formula`... | – | Columnas de la tabla de nombres (con `--nombres`). |
| `estado`, `avisos` | – | Resultado de la revisión. |
| `ISP` | s | Impulso específico (último *"THE ISP IS"*). |
| `Tc` | K | Temperatura en la cámara (primer bloque de resultados). |
| `Te` | K | Temperatura en la salida de la tobera (último bloque). |
| `M` | g/mol | Masa molecular con la que calcula ISPBKW. |
| `Vgas` | cm³/mol | Volumen del gas en la salida, tal como lo imprime ISPBKW. |
| `Mgas` | mol por peso de fórmula | Moles de gas en la salida. |
| `<especie>_moles` | mol por peso de fórmula | Composición en la salida. |
| `<especie>_Hf` | cal/mol | Entalpía de formación del producto a 0 K. |

Las especies que no aparecen en un propelente se rellenan con 0 (solo
en las filas `ok` y `revisar`).

Desde Python, `delta_entalpia(ruta)` devuelve
`Σ moles·Hf(productos) − eo` en J/kg: la diferencia de entalpías de
formación entre los productos de salida y el reactivo, sin la entalpía
sensible.

---

## Cálculo con NASA CEA (`impulso_cea.py`)

Calcula el mismo CSV con NASA CEA a través de RocketCEA, de forma
independiente del flujo de ISPBKW. Cada propelente se define como
monopropelente a 298,15 K con su `DeltaH` (CEA usa esa referencia, sin
conversión a 0 K) y se expande desde la cámara hasta la salida con dos
hipótesis: equilibrio (`Equilibrium`) y composición congelada desde la
cámara (`Frozen`).

```bat
python impulso_cea.py energ_mat.csv [--salida FICHERO] [--pc-bar 68.9476] [--pe-bar 1.01325] [--pamb-bar P]
    [--col-compuesto Compuesto] [--col-formula Formula] [--col-deltah DeltaH]
```

Como en `calcular_isp.py`, las columnas de compuesto (opcional),
fórmula y entalpía se llaman por defecto `Compuesto`, `Formula` y
`DeltaH`, y con `--col-…` (o `col_compuesto`, `col_formula`,
`col_deltah` en `calcular_cea` y `barrido_pc`) se indican otros nombres.
La salida conserva los nombres originales.

Por defecto: cámara a 1000 psi (68,9476 bar), salida a 1 atm y presión
ambiente igual a la de salida (tobera adaptada). El impulso se calcula de
dos formas que deben coincidir con tobera adaptada: `ve = √(2·(hc − he))`
y la función `estimate_Ambient_Isp` de RocketCEA.

Columnas principales de la salida (`<h>` = `Equilibrium` o `Frozen`):

| Columna | Unidad | Contenido |
|---|---|---|
| `Ve_CEA_<h>` | km/s | Velocidad de escape (= Isp en N·s/g). |
| `Isp_CEA_<h>_s` | s | `ve / g0`. |
| `Isp_amb_<h>_s`, `Isp_amb_<h>_kms` | s, km/s | Isp de `estimate_Ambient_Isp` a la presión ambiente. |
| `Modo_tobera_<h>`, `eps_<h>` | – | Régimen de la tobera y relación de áreas Ae/At. |
| `T_chamber`, `T_exit_<h>` | K | Temperaturas de cámara y de salida. |
| `h_c_kJ_kg`, `h_e_<h>_kJ_kg`, `Q_c_kJ_kg`, `Q_e_<h>_kJ_kg` | kJ/kg | Balance de energía (entalpías absolutas y calor liberado). |
| `Comp_Chamber`, `Comp_Exit_Eq` | – | Fracciones molares de los productos (JSON). |
| `n_gas_…`, `n_cond_…`, `M_gas_…`, `fm_gas_…` | mol/kg, g/mol, – | Composición por fases en cámara y salida. |

Funciones disponibles desde Python:

| Función | Uso |
|---|---|
| `calcular_cea(ruta, pc_bar, pe_bar, pamb_bar, col_…)` | Calcula todos los propelentes de un CSV. |
| `calcular(nombre, formula, dh, pc_bar, pe_bar)` | Calcula un solo propelente. |
| `balance_energia(formula, dh, ...)` | Imprime y devuelve el balance de energía cámara → salida. |
| `estadisticos(real, pred)` | Sesgo, MAE, RMSE, R², error máximo y ajuste lineal entre dos series. |
| `metricas(df, ref)` | Estadísticos de `Ve_CEA_<h>` e `Isp_amb_<h>_kms` frente a una columna de referencia. |
| `graficar_comparacion(df, ref, pred, ...)` | Gráfico de paridad con estadísticos. |
| `barrido_pc(ruta, pcs, ...)` | Estadísticos frente a la referencia para varias presiones de cámara. |
| `mapa_correlaciones(df, ...)` | Correlaciones entre energías, composición e Isp. |
| `barrido_composicion(al, htpb, ...)` | Propelentes AP/Al/HTPB con contenido de Al variable. |
| `barrido_mr(ox, fuel, mr, ...)`, `graficar_mr(df, ...)` | Biergol frente a la relación de mezcla O/F. |

### Comparabilidad con ISPBKW

| | ISPBKW | CEA (`impulso_cea.py`) |
|---|---|---|
| Presión de cámara | 68,9473 bar | 68,9476 bar (1000 psi) |
| Presión de salida | 1,01325 bar | 1,01325 bar |
| Tobera | adaptada | adaptada (por defecto) |
| Química en la expansión | equilibrio | equilibrio y congelada |
| Estado inicial del propelente | 298,15 K (`eo_ISPBKW`) | 298,15 K (`DeltaH`) |
| Ecuación de estado de los gases | BKW | gas ideal |
| Datos termodinámicos | `zzztherc`, `zzzsoleq` | `thermo.inp` (NASA) |
| Constante del impulso | 9,330 (0,02 % sobre √(2·4184)/g0) | `ve / g0` |
| Trabajo `pc·v0` del propelente | incluido (≈ 0,05 % con 1 g/cm³) | no |

Con los valores por defecto, las condiciones coinciden (la diferencia de
presión de cámara es de 4·10⁻⁶ en términos relativos). Las diferencias
entre ambos resultados proceden de la ecuación de estado y de los datos
termodinámicos de los productos. Si se cambian las presiones de
`impulso_cea.py`, deja de ser comparable con ISPBKW, cuyas presiones son
fijas.

---

## Condiciones de cálculo y unidades de ISPBKW

| Magnitud | Valor | Dónde |
|---|---|---|
| Presión de cámara | 68,9473 bar (1000 psi) | Fijada en la subrutina `isp`. |
| Presión de salida | 1,01325 bar (1 atm) | Fijada en la subrutina `isp`. |
| Cámara | Equilibrio químico, combustión a entalpía constante. | |
| Tobera | Expansión isentrópica en equilibrio, tobera adaptada. | |
| Impulso | `ISP = 9,330 · √(hc − he)`, con h en cal/g; resultado en s. | |

Para cambiar las presiones hay que modificar `pc` y `pe` en
`subroutine isp` (en Mbar) y recompilar.

Conversión a km/s (N·s/g): `Isp [km/s] = ISP [s] · 9,80665 / 1000`.
No debe usarse `ISP / 100`: da valores parecidos, pero con un error
sistemático del 1,9 %.

---

## Limitaciones conocidas

- **Elementos**: se admiten los 17 elementos de USERBKW, pero que un
  elemento se acepte no garantiza un cálculo correcto: ISPBKW necesita
  especies de productos con ese elemento en `zzztherc` y `zzzsoleq`
  (p. ej., el P del PBX-9404 no da ningún producto), y con aluminio
  rige la limitación de las especies 19 y 20.
- **Dimensiones de ISPBKW**: como máximo 10 elementos, 25 especies y 5
  sólidos.
- **Densidad en USERBKW**: el error de inicialización descrito en el
  paso 3 está en el propio USERBKW. El script lo corrige para ficheros
  de un componente; con varios componentes (otro `plantilla_userbkw.txt`) hay que
  revisar la densidad a mano o corregir USERBKW (iniciar `totwht` y
  `totvol` a cero en `getcomps`) y recompilarlo.
- **Especies 19 y 20**: la subrutina `isp` sustituye siempre sus
  coeficientes por los de Al2O3 sólido y líquido. Solo es correcto si
  esas especies son Al2O3; con menos de 19 especies no influye.
- **Presiones fijas**: 1000 psi en cámara y 1 atm en la salida.
- **Datos de `zzztherc`**: las entalpías de formación a 0 K de algunas
  especies minoritarias difieren de las de NASA CEA: OH (3,56 frente a
  8,85 kcal/mol), CCl4 (−25,5 frente a −22,3) y NO (21,48 frente a
  21,69). Puede influir en las formulaciones más calientes, donde el OH
  no es despreciable.
- **Convergencia**: ISPBKW puede no converger o aceptar soluciones con
  tolerancia relajada. El extractor lo señala en la columna `estado`;
  los casos `error` y `revisar` deben revisarse o repetirse.
- **Correspondencia de nombres**: `expN` ↔ propelente se basa en el
  orden de las filas del CSV de entrada. Para unir resultados y datos
  hay que usar la tabla `zzzcomps_nombres.csv`, no la posición.

---

## Referencias

- C. Taylor, *RocketCEA: Python wrapper for the NASA CEA code*, v1.2.3,
  2026. Código: https://github.com/sonofeft/RocketCEA ·
  Documentación: https://rocketcea.readthedocs.io ·
  PyPI: https://pypi.org/project/rocketcea/
- S. Gordon y B. J. McBride, *Computer Program for Calculation of Complex
  Chemical Equilibrium Compositions and Applications. I. Analysis*,
  NASA RP-1311, NASA Lewis Research Center, Cleveland, 1994.
- B. J. McBride y S. Gordon, *Computer Program for Calculation of Complex
  Chemical Equilibrium Compositions and Applications. II. Users Manual
  and Program Description*, NASA RP-1311-P2, NASA Lewis Research Center,
  Cleveland, 1996.
- NASA Glenn Research Center, *Chemical Equilibrium with Applications
  (CEA)*: https://www.nasa.gov/glenn/research/chemical-equilibrium-with-applications
- C. L. Mader, *Numerical Modeling of Explosives and Propellants*,
  3.ª ed., CRC Press, Boca Raton, 2008 (ISBN 978-1-4200-5238-1).
  Incluye un CD-ROM con los códigos FORTRAN y ejecutables de la familia
  BKW y las bases de datos de explosivos.
- J. E. Hurst y B. K. Harrison, *Estimation of liquid and solid heat
  capacities using a modified Kopp's rule*, Chem. Eng. Commun. 112,
  21–30, 1992 (contribuciones atómicas para `DeltaH_0K_est`).
- B. J. McBride, M. J. Zehe y S. Gordon, *NASA Glenn Coefficients for
  Calculating Thermodynamic Properties of Individual Species*,
  NASA/TP-2002-211556, 2002 (base `thermo.inp` de CEA).
- Frem, D. (2018). *A Reliable Method for Predicting the Specific Impulse of Chemical Propellants.*
  Journal of Aerospace Technology and Management, 10, e3318. DOI: 10.5028/jatm.v10.945
  (https://doi.org/10.5028/jatm.v10.945)

---

## Ejemplos de uso

Los ejemplos de línea de comandos son para `cmd` de Windows (`^` continúa
la línea). `C:\bkw` es la carpeta con los programas de Mader.

### ISPBKW: `calcular_isp.py`

**Cálculo completo con los valores por defecto**
```bat
python calcular_isp.py energ_mat.csv --trabajo C:\bkw
```
Escribe `energ_mat_ISPBKW.csv`, `_productos.csv`, `_especies.csv`,
`_avisos.csv` y `.xlsx` junto al CSV de entrada.

**Columnas con otros nombres**
```bat
python calcular_isp.py mis_datos.csv --trabajo C:\bkw ^
    --col-compuesto Nombre --col-formula Form --col-deltah Hf_kcal
```
Útil cuando el CSV no usa `Compuesto`, `Formula` y `DeltaH`.

**Densidad real de cada propelente**
```bat
python calcular_isp.py energ_mat.csv --trabajo C:\bkw --columna-fijo Densidad
```
Toma la densidad (g/cm³) de la columna `Densidad`; su efecto en el
impulso es pequeño (término `pc·v0`).

**Salidas con otro nombre o en otra carpeta**
```bat
python calcular_isp.py energ_mat.csv --trabajo C:\bkw --salida resultados\serie_A
```
Escribe `resultados\serie_A.csv`, `serie_A_productos.csv`... y `serie_A.xlsx`.

**Seguir tras una interrupción**
```bat
python calcular_isp.py energ_mat.csv --trabajo C:\bkw --continuar
```
Calcula solo los casos sin resultado; se detiene si los datos han
cambiado desde la ejecución interrumpida.

**Con PowerShell 7**
```bat
python calcular_isp.py energ_mat.csv --trabajo C:\bkw --powershell pwsh
```

**Preparar los datos y ejecutar solo algunos casos**
```bat
python calcular_isp.py energ_mat.csv --trabajo C:\bkw --preparar
cd C:\bkw
powershell -ExecutionPolicy Bypass -File .\procesar_ispbkw.ps1 -Casos 1..5,12 -Reiniciar -Extraer
```
`--preparar` deja `zzzcomps` listo; el script de PowerShell calcula los
casos indicados (útil para probar o repetir casos concretos).

**Repetir un caso que ha fallado** (con `userdata` en la carpeta de
trabajo, es decir, tras usar el script de PowerShell directamente; al
terminar, `calcular_isp.py` la mueve a `files_…`)
```bat
cd C:\bkw
del userdata\exp7.out
powershell -ExecutionPolicy Bypass -File .\procesar_ispbkw.ps1 -Modo bkw -Casos 7 -Extraer
```
Vuelve a ejecutar ISPBKW sobre el fichero de entrada ya generado.

**Desde Python**
```python
from calcular_isp import calcular_isp

resumen = calcular_isp('energ_mat.csv', r'C:\bkw')
print(resumen[['Compuesto', 'Isp_s', 'Isp_km_s', 'Tc_K', 'estado']])
print(resumen[resumen['estado'] != 'ok'])        # casos a revisar
```

**Leer el libro de resultados**
```python
import pandas as pd

hojas = pd.read_excel('energ_mat_ISPBKW.xlsx', sheet_name=None)
resumen, productos = hojas['Resumen'], hojas['Productos']
print(productos.set_index('Compuesto').loc['RDX'].filter(like='_mol_kg'))
```

### ISPBKW: paso a paso

**Entalpía de entrada de un compuesto**
```python
from eo_0k import eo_ispbkw, correccion_0k

eo_ispbkw('C3H6N6O6', 14.71)        # 33977.6 cal por fórmula (RDX)
correccion_0k('C3H6N6O6')           # términos de la conversión 298 K -> 0 K
```

**Tabla con `eo_ISPBKW` y `zzzcomps`**
```bat
python eo_0k.py energ_mat.csv --salida energ_mat_eo0K.csv
python zzzcomps.py energ_mat_eo0K.csv --columna eo_ISPBKW --salida C:\bkw\zzzcomps
```

**`zzzcomps` con `DeltaH` a 298 K** (para reproducir cálculos antiguos)
```bat
python zzzcomps.py energ_mat_eo0K.csv --columna DeltaH --salida C:\bkw\zzzcomps
```
`DeltaH` se multiplica por 1000 (kcal → cal); el impulso sale un 2 %
más bajo de media.

**Extraer resultados de una carpeta de `.out`**
```bat
python extraer_composicion.py C:\bkw\userdata resultados --nombres C:\bkw\zzzcomps_nombres.csv --avisos
```
Escribe `resultados\resultados.csv` y `resultados\avisos.csv`.

**Diagnóstico de un `.out`**
```python
from extraer_composicion import diagnostico, iteraciones_aceptadas, delta_entalpia

diagnostico('userdata/exp4.out')            # p. ej. ('ok', 'temp err (1; 3.7E-02); ...')
iteraciones_aceptadas('userdata/exp4.out')  # residuos frente a los umbrales
delta_entalpia('userdata/exp4.out')         # J/kg, productos - reactivo
```

### NASA CEA: `impulso_cea.py`

**Cálculo del CSV con las condiciones de ISPBKW**
```bat
python impulso_cea.py energ_mat.csv --salida energ_mat_CEA.csv
```
Imprime además los estadísticos frente a `Isp_BKW` e `Isp_Doc` si el
CSV tiene esas columnas.

**Columnas con otros nombres**
```bat
python impulso_cea.py mis_datos.csv --col-compuesto Nombre --col-formula Form --col-deltah Hf_kcal
```
```python
from impulso_cea import calcular_cea
df = calcular_cea('mis_datos.csv', col_compuesto='Nombre', col_formula='Form',
                  col_deltah='Hf_kcal')
```

**Otras condiciones de tobera**
```bat
python impulso_cea.py energ_mat.csv --pc-bar 100 --pe-bar 0.5 --salida cea_100bar.csv
python impulso_cea.py energ_mat.csv --pamb-bar 1.01325 --pe-bar 0.2 --salida cea_sobreexpandida.csv
```
La segunda expande hasta 0,2 bar con 1 atm de ambiente: `Isp_amb_*`
recoge la pérdida por sobreexpansión (o el desprendimiento) y
`Modo_tobera_*` lo indica. Estos resultados ya no son comparables con
ISPBKW.

**Un solo propelente**
```python
from impulso_cea import calcular, PC_1000PSI, ATM_BAR

r = calcular('RDX', 'C3H6N6O6', 14.71, PC_1000PSI, ATM_BAR)
r['Isp_amb_Equilibrium_s'], r['T_chamber'], r['Modo_tobera_Equilibrium']
```

**Balance de energía**
```python
from impulso_cea import balance_energia

b = balance_energia('C3H6N6O6', 14.71)                # equilibrio
b = balance_energia('C3H6N6O6', 14.71, frozen=True)   # composición congelada
```
Imprime las entalpías de cámara y salida, el calor liberado y el
rendimiento cinético `ve²/2 / Q`.

**Comparar con una referencia y dibujar la paridad**
```python
from impulso_cea import calcular_cea, metricas, graficar_comparacion

df = calcular_cea('energ_mat.csv')
metricas(df, ref='Isp_BKW')
graficar_comparacion(df, ref='Isp_BKW', pred='Ve_CEA_Equilibrium', ajuste=True)
```

**Sensibilidad a la presión de cámara**
```python
from impulso_cea import barrido_pc
barrido_pc('energ_mat.csv', pcs=(50, 68.9476, 100, 150))
```
Tabla de sesgo, MAE, RMSE y R² frente a `Isp_BKW` para cada presión e
hipótesis.

**Mapa de correlaciones** (requiere las columnas `Q`, `Ng` e `Isp_BKW`)
```python
from impulso_cea import calcular_cea, mapa_correlaciones
mapa_correlaciones(calcular_cea('energ_mat.csv'), hipotesis='Equilibrium', metodo='spearman')
```

**Propelente compuesto AP/Al/HTPB**
```python
from impulso_cea import barrido_composicion
df = barrido_composicion(al=range(10, 22, 2), htpb=12)
df[['AP', 'Al', 'Isp_Equilibrium_s', 'Isp_Frozen_s', 'T_chamber']]
```

**Biergol frente a la relación de mezcla**
```python
from impulso_cea import barrido_mr, graficar_mr
df = barrido_mr('LOX', 'RP-1', mr=[1.8 + 0.05 * i for i in range(30)])
graficar_mr(df, titulo='LOX/RP-1', mr_estq=3.4)
```

### ISPBKW frente a CEA

**Estadísticos de la diferencia entre ambos códigos**
```python
import pandas as pd
from impulso_cea import calcular_cea, estadisticos, graficar_comparacion

cea = calcular_cea('energ_mat.csv')              # mismo CSV de entrada
bkw = pd.read_csv('energ_mat_ISPBKW.csv')        # resumen de calcular_isp.py
assert (cea['Formula'].values == bkw['Formula'].values).all()   # mismo orden

df = cea.assign(Isp_ISPBKW_kms=bkw['Isp_km_s'].values)
estadisticos(df['Ve_CEA_Equilibrium'], df['Isp_ISPBKW_kms'])
graficar_comparacion(df, ref='Ve_CEA_Equilibrium', pred='Isp_ISPBKW_kms',
                     titulo='ISPBKW frente a CEA (equilibrio)', ajuste=True)
```
Ambas salidas conservan todas las filas en el orden de la entrada (los
casos con error quedan vacíos y `estadisticos` los ignora), así que se
unen por posición; la comprobación de `Formula` lo garantiza. Si la
entrada usa otro nombre para la fórmula, en `cea` es ese nombre (en el
resumen de ISPBKW siempre es `Formula`).

**Diferencia por compuesto**
```python
df['dif_%'] = 100 * (df['Isp_ISPBKW_kms'] / df['Ve_CEA_Equilibrium'] - 1)
df.groupby('Tipo')['dif_%'].describe()
df.nlargest(10, 'dif_%')[['Compuesto', 'Formula', 'dif_%']]
```