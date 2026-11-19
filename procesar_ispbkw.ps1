<#
.SYNOPSIS
Ejecución rápida
powershell -ExecutionPolicy Bypass -File .\procesar_ispbkw.ps1 -Extraer

Objeto
Automatizar la entrada de datos desde zzzcomps a userbkw.exe y a abispbkw.exe
Resumir los resultados de abispbkw.exe en un fichero csv

Procesa las composiciones con formato de nombre exp1..expN presentes en zzzcomps con userbkw.exe y abispbkw.exe. Opcionalmente, extrae la composicion, y otros datos de los .out que crea abispbkw.exe,
a un fichero CSV (debe de estar instalado python3 y visible en el path).

Las composiciones de zzzcomps deben llamarse exp1, exp2... (zzzcomps.py las
escribe asi, con fin de linea CR LF):

 exp1                 1.00000000000E+00-0.10275330000E+06
 c                    0.50000000000E+01
 h                    0.80000000000E+01
 n                    0.40000000000E+01
 o                    0.12000000000E+02
 zzz                  0.31613500000E+03
 exp2                 1.00000000000E+00 0.15160000000E+03
 c                    0.70000000000E+01
 h                    0.50000000000E+01
 n                    0.30000000000E+01
 o                    0.60000000000E+01
 zzz                  0.22713200000E+03
 ......................................
Los casos a procesar se leen de zzzcomps (todos los expN que contiene) o se
indican con -Casos. Antes de empezar, el script comprueba que:
  - zzzcomps existe, tiene fin de linea CR LF y no repite nombres;
  - todos los casos pedidos estan en zzzcomps (si userbkw.exe no encuentra un
    componente, pasa a modo interactivo y escribe en zzzcomps);
  - los resultados que ya hay en userdata se generaron con los mismos
    zzzcomps, data.txt y primera linea (huella en userdata\huella.txt).

La entrada de datos a userbkw.exe proviene de data.txt. Las lineas que
empiezan por '#' son comentarios y no se envian; el resto se envia tal cual,
salvo las lineas 'exp1', que se sustituyen por el caso actual:

  # Crear nuevo fichero
  1
  # Anadir un mol del explosivo de zzzcomps
  3
  # Nombre del explosivo (se sustituye por exp2, exp3...)
  exp1
  +
  exp1
  +
  # Parametros BKW (1 RDX, 2 TNT, 3 introducirlos, 4 mantener los actuales)
  2
  +
  +
  +
  +
  +
  # Nombre del fichero
  exp1

.DESCRIPTION
Para cada caso expN:
  1. userbkw.exe: recibe las lineas de plantilla_userbkw.txt que no son comentarios, con
     las lineas 'exp1' sustituidas por el caso actual. Genera expN en .\userdata.
  2. Se sustituye la primera linea de userdata\expN por $primeraLinea, para
     generar caso cálculo de impulso, y se escribe la densidad de zzzcomps en
     la linea de densidad, masa y eo. userbkw.exe calcula la densidad con
     variables sin inicializar (subroutine getcomps) y a veces la escribe con
     un valor absurdo (p. ej. 1E-31 g/cc), con el que abispbkw.exe da NaN.
     La sustitucion solo se hace si el fichero corresponde a 1 mol del
     componente de zzzcomps (como en data.txt); si no, se avisa.
  3. abispbkw.exe: solo lee un fichero llamado 'bkwdata', asi que expN se copia
     con ese nombre y se ejecuta abispbkw.exe. Este siempre escribe 'isp.out',
     que se renombra a expN.out y se mueve a .\userdata.
  4. (opcional, -Extraer) extraer_composicion.py procesa todos los .out de
     .\userdata y guarda el CSV en .\resultados. Si existe la tabla
     zzzcomps_nombres.csv (la escribe zzzcomps.py), se le pasa con --nombres
     para unir los resultados por nombre.

Nunca sobrescribe salidas: si para un caso ya existe expN (modos ambos y user)
o expN.out (modos ambos y bkw) en .\userdata, avisa y salta al siguiente caso.
Para repetir un caso hay que borrar antes sus ficheros de salida. En modo
bkw, expN es la entrada y debe existir.

Si userdata contiene resultados de otros zzzcomps, plantilla_userbkw.txt o primera linea
(o de una version anterior del script, sin huella), el script se detiene sin
calcular nada. Con -Reiniciar, la carpeta userdata actual se renombra a
userdata_AAAAMMDD_HHMMSS (no se borra nada) y se empieza de cero.

El script trabaja siempre desde su propia carpeta ($PSScriptRoot), donde deben
estar userbkw.exe, abispbkw.exe, plantilla_userbkw.txt, extraer_composicion.py, zzzcomps y
resto de ficheros zzz (ZZZSOLEQ y ZZZTHERC).

Siempre se debe comprobar si se han procesado sin error todas las
composiciones: el resumen final del extractor y la columna "estado" del CSV
indican los casos con error o con avisos de convergencia. A veces basta
repetir el calculo del caso que fallo.

.PARAMETER Modo
Que ejecutables se usan:
  ambos  userbkw.exe y abispbkw.exe (por defecto)
  user   solo userbkw.exe (pasos 1 y 2)
  bkw    solo abispbkw.exe (paso 3), sobre los expN que ya existan en userdata;
         no necesita data.txt

.PARAMETER Casos
Numeros de los casos a procesar: 1..10, 3,7,12 o combinaciones como
1..5,9 (tambien con powershell -File). Por defecto, todos los expN de
zzzcomps (zzzcomps se puede crear a partir del módulo correspondiente).

.PARAMETER Extraer
Si se indica, al terminar ejecuta extraer_composicion.py sobre los .out de
userdata. Es independiente de -Modo. Por defecto no se ejecuta.

.PARAMETER Reiniciar
Renombra la carpeta userdata actual a userdata_AAAAMMDD_HHMMSS y empieza con
una carpeta vacia. Necesario si se ha cambiado zzzcomps, data.txt o la
primera linea despues de un calculo anterior.

.EXAMPLE
.\procesar_ispbkw.ps1
Ejecuta userbkw.exe y abispbkw.exe para todos los casos, sin extractor.

.EXAMPLE
.\procesar_ispbkw.ps1 -Extraer
Ejecuta userbkw.exe y abispbkw.exe y despues genera resultados\resultados.csv.

.EXAMPLE
.\procesar_ispbkw.ps1 -Casos 1..2
Prueba con exp1 y exp2.

.EXAMPLE
.\procesar_ispbkw.ps1 -Reiniciar -Extraer
Archiva los resultados anteriores y repite todos los casos.

.EXAMPLE
.\procesar_ispbkw.ps1 -Modo user
Solo userbkw.exe: deja los expN en userdata con la primera linea sustituida.

.EXAMPLE
.\procesar_ispbkw.ps1 -Modo bkw -Extraer
Solo abispbkw.exe sobre los expN ya generados, y despues el extractor.

.NOTES
Ayuda: Get-Help .\procesar_ispbkw.ps1 -Full
Si la ejecucion de scripts esta bloqueada:
  powershell -ExecutionPolicy Bypass -File .\procesar_ispbkw.ps1 -Extraer
#>

param(
    [ValidateSet('ambos', 'user', 'bkw')]
    [string]$Modo = 'ambos',

    [string[]]$Casos,

    [switch]$Extraer,

    [switch]$Reiniciar
)

function Stop-Script([string]$mensaje) {
    Write-Host "ERROR: $mensaje" -ForegroundColor Red
    exit 1
}

$cultura = [System.Globalization.CultureInfo]::InvariantCulture

# Lee un numero escrito por FORTRAN (NaN si no se puede leer)
function Read-Fortran([string]$texto) {
    $v = 0.0
    if ([double]::TryParse($texto.Trim(), [System.Globalization.NumberStyles]::Float,
                           $cultura, [ref]$v)) { return $v }
    return [double]::NaN
}

# Escribe un numero con el formato FORTRAN e18.11 (p. ej. ' 0.10000000000E+01')
function ConvertTo-E1811([double]$valor) {
    if ($valor -eq 0) { return ' 0.00000000000E+00' }
    $exp = [math]::Floor([math]::Log10([math]::Abs($valor))) + 1
    $mantisa = ([math]::Abs($valor) / [math]::Pow(10, $exp)).ToString('F11', $cultura)
    if ($mantisa.StartsWith('1')) {                # redondeo a 1.000...
        $exp += 1
        $mantisa = ([math]::Abs($valor) / [math]::Pow(10, $exp)).ToString('F11', $cultura)
    }
    $signo = if ($valor -lt 0) { '-' } else { ' ' }
    $signoExp = if ($exp -lt 0) { '-' } else { '+' }
    return '{0}{1}E{2}{3:00}' -f $signo, $mantisa, $signoExp, [math]::Abs($exp)
}

# Trabajar siempre desde la carpeta donde esta el script
Set-Location $PSScriptRoot

# ---------------------------------------------------------------- Configuracion
$exe          = '.\userbkw.exe'
$exeBkw       = '.\abispbkw.exe'
$ficheroBkw   = 'bkwdata'                    # nombre fijo que lee abispbkw.exe
$ficheroOut   = 'isp.out'                    # nombre fijo que escribe abispbkw.exe
$plantilla    = 'plantilla_userbkw.txt'      # plantilla de entrada de userbkw.exe
$carpeta      = 'userdata'                   # subdirectorio para guardar expN y expN.out

$zzzcomps     = 'zzzcomps'                   # base de componentes de userbkw.exe
$tablaNombres = 'zzzcomps_nombres.csv'       # expN <-> propelente (zzzcomps.py)
$huella       = 'huella.txt'                 # en userdata: con que datos se genero

$primeraLinea = '0002 0001 0000 0001 0001 0000 0000' # solo es relevante el 0002
$pausa        = 0.2                            # segundos entre ejecución lineas de entrada

$python       = 'python'                     # interprete de Python
$extractor    = '.\extraer_composicion.py'   # extractor de composicion
$carpetaCsv   = 'resultados'                 # subdirectorio donde se guarda el CSV
# Si Python se ejecuta dentro de pixi, sustituir en el paso 4 la llamada por:
#   pixi run python $extractor $carpeta $carpetaCsv

# ------------------------------------------------------------------------- Modo
$ejecutaUser = $Modo -in @('ambos', 'user')
$ejecutaBkw  = $Modo -in @('ambos', 'bkw')

# ----------------------------------------------------------- Comprobar zzzcomps
if (-not (Test-Path $zzzcomps)) { Stop-Script "No existe $zzzcomps" }
$rutaZzz = (Resolve-Path $zzzcomps).Path
$texto = [System.IO.File]::ReadAllText($rutaZzz)

# Fin de linea: con LF, userbkw.exe no lee el ultimo componente
if ($texto -match '(?<!\r)\n' -or -not $texto.EndsWith("`r`n")) {
    Stop-Script ("$zzzcomps no tiene fin de linea CR LF en todas sus lineas " +
                 "(userbkw.exe perderia el ultimo componente). " +
                 "Generelo con zzzcomps.py (CR LF por defecto).")
}

# Casos disponibles (lineas ' expN ...') y nombres repetidos
$disponibles = @([regex]::Matches($texto, '(?m)^ exp(\d+) ') |
                 ForEach-Object { [int]$_.Groups[1].Value })
if ($disponibles.Count -eq 0) { Stop-Script "$zzzcomps no contiene casos expN" }
$repetidos = @($disponibles | Group-Object | Where-Object { $_.Count -gt 1 } |
               ForEach-Object { "exp$($_.Name)" })
if ($repetidos.Count -gt 0) {
    Stop-Script "Nombres repetidos en ${zzzcomps}: $($repetidos -join ', ')"
}

# Densidad y atomos por formula de cada expN (para corregir la densidad)
$datosZzz = @{}
$actualZzz = $null
foreach ($l in ($texto -split "`r`n")) {
    if ($l.Length -lt 21) { continue }
    $campo = $l.Substring(1, 20).Trim()
    if ($l -match '^ exp(\d+) ') {
        $actualZzz = @{ 'rho' = (Read-Fortran $l.Substring(21, 18)); 'elem' = @{} }
        $datosZzz[[int]$Matches[1]] = $actualZzz
    } elseif ($campo -eq 'zzz') {
        $actualZzz = $null
    } elseif ($null -ne $actualZzz -and $l.Length -ge 39 -and $l.Length -lt 57) {
        $actualZzz['elem'][$campo] = Read-Fortran $l.Substring(21, 18)
    } elseif ($l.Length -ge 57) {
        $actualZzz = $null                         # otro componente
    }
}

# Casos pedidos: todos los de zzzcomps o los de -Casos, que deben existir
if ($PSBoundParameters.ContainsKey('Casos')) {
    # Admite 1..10, 1-10 y listas separadas por comas (tambien como texto)
    $pedidos = @()
    foreach ($parte in ($Casos -join ',') -split '[,\s]+' | Where-Object { $_ }) {
        if ($parte -match '^(\d+)(\.\.|-)(\d+)$') {
            $pedidos += [int]$Matches[1]..[int]$Matches[3]
        } elseif ($parte -match '^\d+$') {
            $pedidos += [int]$parte
        } else {
            Stop-Script "Valor no valido en -Casos: $parte"
        }
    }
    $Casos = @($pedidos | Select-Object -Unique)
    $faltan = @($Casos | Where-Object { $disponibles -notcontains $_ } |
                ForEach-Object { "exp$_" })
    if ($faltan.Count -gt 0) {
        Stop-Script "Casos que no estan en ${zzzcomps}: $($faltan -join ', ')"
    }
} else {
    $Casos = @($disponibles | Sort-Object)
}
Write-Host "Casos: $($Casos.Count) (de $($disponibles.Count) en $zzzcomps)"

# La tabla de nombres debe corresponder a este zzzcomps
if (Test-Path $tablaNombres) {
    $nTabla = @(Import-Csv $tablaNombres).Count
    if ($nTabla -ne $disponibles.Count) {
        Write-Warning ("$tablaNombres tiene $nTabla filas y $zzzcomps " +
                       "$($disponibles.Count) casos: puede ser de otro zzzcomps")
    }
}

# Leer la plantilla una sola vez, descartando las lineas de comentario (#)
if ($ejecutaUser) {
    if (-not (Test-Path $plantilla)) { Stop-Script "No existe $plantilla" }
    $lineas = @(Get-Content $plantilla | Where-Object { $_ -notmatch '^\s*#' })
}

# ------------------------------------------------- Carpeta de salida y huella
if ($Reiniciar -and (Test-Path $carpeta) -and
    @(Get-ChildItem $carpeta -Force).Count -gt 0) {
    $archivo = '{0}_{1:yyyyMMdd_HHmmss}' -f $carpeta, (Get-Date)
    Rename-Item -Path $carpeta -NewName $archivo
    Write-Host "Carpeta $carpeta archivada como $archivo"
}
New-Item -ItemType Directory -Path $carpeta -Force | Out-Null

# Huella de los datos de entrada: zzzcomps, data.txt y primera linea
$actual = [ordered]@{
    'zzzcomps'     = (Get-FileHash -Algorithm SHA256 -Path $rutaZzz).Hash
    'data.txt'     = if (Test-Path $plantilla) {
                         (Get-FileHash -Algorithm SHA256 -Path $plantilla).Hash
                     } else { '' }
    'primeraLinea' = $primeraLinea
    'version'      = '2'                     # 2: con correccion de densidad
}
$rutaHuella = Join-Path $carpeta $huella
$previos = @(Get-ChildItem $carpeta -File |
             Where-Object { $_.Name -match '^exp\d+(\.out)?$' })
if ($previos.Count -gt 0) {
    if (-not (Test-Path $rutaHuella)) {
        Stop-Script ("$carpeta contiene resultados sin $huella (de una version " +
                     "anterior del script). Use -Reiniciar para archivarlos.")
    }
    $guardada = @{}
    foreach ($l in Get-Content $rutaHuella) {
        $k, $v = $l -split '=', 2
        $guardada[$k] = $v
    }
    $comparar = @('zzzcomps', 'primeraLinea', 'version')
    if ($ejecutaUser) { $comparar += 'data.txt' }  # en modo bkw no se usa
    $difieren = @($comparar | Where-Object { $guardada[$_] -ne $actual[$_] })
    if ($difieren.Count -gt 0) {
        Stop-Script ("Los resultados de $carpeta se generaron con otro " +
                     "$($difieren -join ', '). Use -Reiniciar para archivarlos " +
                     "y repetir el calculo.")
    }
} else {
    $actual.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" } |
        Set-Content -Path $rutaHuella -Encoding ASCII
}

# ------------------------------------------------------------------ Procesado
foreach ($i in $Casos) {
    $nombre    = "exp$i"
    $salida    = Join-Path $carpeta $nombre          # salida de userbkw.exe
    $salidaOut = Join-Path $carpeta "$nombre.out"    # salida de abispbkw.exe

    # No sobrescribir: si ya existe alguna salida que este caso generaria,
    # se avisa y se salta al siguiente
    $existentes = @()
    if ($ejecutaUser -and (Test-Path $salida))    { $existentes += $nombre }
    if ($ejecutaBkw  -and (Test-Path $salidaOut)) { $existentes += "$nombre.out" }
    if ($existentes.Count -gt 0) {
        Write-Warning "Se omite $nombre : ya existe $($existentes -join ' y ') en $carpeta"
        continue
    }

    Write-Host "Procesando $nombre ($Modo) ..."

    if ($ejecutaUser) {
        # 1. Enviar la entrada a userbkw.exe sustituyendo la linea 'exp1' por
        #    el caso actual
        $lineas | ForEach-Object {
            if ($_.Trim() -eq 'exp1') { $nombre } else { $_ }
            Start-Sleep -Seconds $pausa
        } | & $exe

        # Localizar la salida (si el programa la deja en la carpeta actual, se mueve)
        if (-not (Test-Path $salida) -and (Test-Path $nombre)) {
            Move-Item -Path $nombre -Destination $salida -Force
        }
    }

    if (-not (Test-Path $salida)) {
        Write-Warning "No se ha encontrado $salida"
        continue
    }

    if ($ejecutaUser) {
        # 2. Sustituir la primera linea de userdata\expN
        $ruta = (Resolve-Path $salida).Path
        $contenido = [System.IO.File]::ReadAllLines($ruta)
        $contenido[0] = $primeraLinea

        # 2b. Densidad: userbkw.exe la calcula con variables sin inicializar
        #     (totwht y totvol en subroutine getcomps) y puede salir absurda.
        #     Estructura del fichero: linea 3 = m, n, nt; linea 5 = nombres de
        #     los m elementos; despues, sus moles (4 por linea, e18.11); despues,
        #     densidad, masa y eo. Con 1 mol de un componente (data.txt), la
        #     densidad debe ser la de zzzcomps.
        $m = [int]$contenido[2].Substring(0, 5).Trim()
        $iRho = 5 + [math]::Ceiling($m / 4)
        $nombresEl = @($contenido[4].Trim() -split '\s+')
        $moles = @(for ($k = 5; $k -lt $iRho; $k++) {
                       for ($p = 0; $p + 18 -le $contenido[$k].Length; $p += 18) {
                           Read-Fortran $contenido[$k].Substring($p, 18)
                       }
                   })
        $ref = $datosZzz[[int]$i]
        $unMol = ($nombresEl.Count -eq $m) -and ($moles.Count -eq $m) -and
                 ($ref['elem'].Count -eq $m)
        for ($k = 0; $unMol -and $k -lt $m; $k++) {
            $esperado = $ref['elem'][$nombresEl[$k]]
            $unMol = ($null -ne $esperado) -and
                     ([math]::Abs($moles[$k] - $esperado) -le 1e-6 * [math]::Max(1, $esperado))
        }
        if (-not $unMol) {
            Write-Warning ("${nombre}: el fichero no es 1 mol del componente de " +
                           "$zzzcomps; no se corrige la densidad")
        } else {
            $rhoFichero = Read-Fortran $contenido[$iRho].Substring(0, 18)
            if (-not ([math]::Abs($rhoFichero - $ref['rho']) -le 1e-6 * $ref['rho'])) {
                Write-Warning ("${nombre}: densidad de userbkw.exe $rhoFichero " +
                               "sustituida por $($ref['rho']) ($zzzcomps)")
            }
            $contenido[$iRho] = (ConvertTo-E1811 $ref['rho']) +
                                $contenido[$iRho].Substring(18)
        }
        [System.IO.File]::WriteAllLines($ruta, $contenido)
    }

    if ($ejecutaBkw) {
        # 3. Pasar el fichero por abispbkw.exe (lee siempre 'bkwdata'); su salida
        #    es siempre 'isp.out' y se renombra a expN.out en userdata
        Copy-Item -Path $salida -Destination $ficheroBkw -Force
        $inicio = Get-Date
        & $exeBkw

        # El isp.out solo se acepta si se ha escrito despues de lanzar abispbkw.exe
        if ((Test-Path $ficheroOut) -and ((Get-Item $ficheroOut).LastWriteTime -ge $inicio)) {
            Move-Item -Path $ficheroOut -Destination (Join-Path $carpeta "$nombre.out") -Force
        } else {
            Write-Warning "abispbkw.exe no ha generado $ficheroOut para $nombre"
        }
    }
}

# 4. Extraer la composicion de los .out y guardar el CSV (opcional: -Extraer)
if ($Extraer) {
    Write-Host "Extrayendo resultados de $carpeta ..."
    $argumentos = @($extractor, $carpeta, $carpetaCsv)
    if (Test-Path $tablaNombres) { $argumentos += @('--nombres', $tablaNombres) }
    & $python @argumentos
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "extraer_composicion.py ha terminado con error ($LASTEXITCODE)"
    }
}

Write-Host "Terminado."