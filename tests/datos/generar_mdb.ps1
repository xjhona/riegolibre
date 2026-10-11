# Genera las bases de prueba irricad_jet3.mdb e irricad_jet4.mdb (datos ficticios con la
# estructura de una base de IRRICAD). Necesita el PowerShell de 32 bits de Windows, que trae
# el proveedor Microsoft.Jet.OLEDB.4.0:
#   C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe -File tests\datos\generar_mdb.ps1
param([string]$carpeta = $PSScriptRoot)

function Crear-Base($ruta, $motor, $comp) {
    if (Test-Path $ruta) { Remove-Item $ruta }
    $catalogo = New-Object -ComObject ADOX.Catalog
    [void]$catalogo.Create("Provider=Microsoft.Jet.OLEDB.4.0;Data Source=$ruta;Jet OLEDB:Engine Type=$motor")
    $catalogo.ActiveConnection.Close()
    $c = New-Object System.Data.OleDb.OleDbConnection("Provider=Microsoft.Jet.OLEDB.4.0;Data Source=$ruta")
    $c.Open()
    function Sql($texto, $parametros = @()) {
        $cmd = $c.CreateCommand(); $cmd.CommandText = $texto
        foreach ($p in $parametros) { [void]$cmd.Parameters.AddWithValue("?", $p) }
        [void]$cmd.ExecuteNonQuery()
    }
    $reales = (1..8 | % { "Reals$_ SINGLE" }) + (1..4 | % { "Rextra$_ SINGLE" })
    Sql ("CREATE TABLE Components ([Component Key] LONG, [Database Number] BYTE, Description TEXT(40) $comp, " +
         "[Warehouse Code] TEXT(32), [Supplier Code] TEXT(4), [Usage] TEXT(4), Major1 TEXT(6), Minor1 TEXT(6), " +
         "Major2 TEXT(6), Minor2 TEXT(6), " + ($reales -join ", ") + ", [Item Type] TEXT(4), Flags LONG)")
    Sql ("CREATE TABLE Tapes ([Pipe Key] LONG, [Flow Calc Type] TEXT(4), " +
         ((1..6 | % { "Reals$_ SINGLE" }) + (1..4 | % { "Rextra$_ SINGLE" }) -join ", ") + ")")

    # Clave, pestaña, descripción, código, proveedor, uso, Major1, Minor1, Major2, Reals1-8, Rextra1-4
    $componentes = @(
        @(1, 5, "*** NO PIPE SELECTED ***", "............", "SUP1", "LZM", "PVC", "", "", 1, 0.1, 100, 100, 0, 0, 0, 0, 0, 0, 0, 0),
        @(10, 1, "63 mm C-7.5 PVC Prueba", "", "SUP1", "M", "PVC", "", "63/7.5", 63, 58.4, 150, 73, 0, 0, 0.719, 0.8, 0, 0, 0, 0),
        @(11, 1, '1½" C-10 PVC Caño', "COD-11", "SUP1", "ZM", "PVC", "", "", 48, 43.4, 150, 100, 0, 0, 1.2, 1.5, 0, 0, 0, 0),
        @(12, 1, "110 mm PN6 HDPE Prueba", "", "SUP1", "", "HDP", "", "", 110, 101.6, 150, 60, 0, 0, 0, 0, 0, 0, 0, 0),
        @(13, 1, "16 mm LDPE Manguera", "", "SUP1", "L", "LDPE", "", "", 16, 13.8, 140, 25, 0, 0, 0.1, 0.1, 0, 0, 0, 0),
        @(20, 1, "Gotero PC 2.0 l/h @0.5m 16mm", "GOT-20", "ERDP", "L", "LDP", "", "", 16, 13.8, 140, 30, 0, 0, 0.2, 0.25, 0, 0, 0.03, 5),
        @(21, 1, "Cinta 1.0 l/h @0.2m 16mm", "", "ERDP", "L", "LDP", "", "", 16, 16.1, 140, 10, 0, 0, 0.1, 0.1, 0, 0, 0.03, 0),
        @(30, 2, 'Válvula 2" Prueba', 'VAL 2"', "ERDP", "Y", "NPT FY", "NPT FY", '2"', 63, 63, 0.00387828, 2.01454, 2, 0, 10, 12, 10, 25, 0, 0),
        @(31, 2, "Válvula oculta", "", "SUP1", "", "NPT FS", "NPT FS", "", 50, 50, 0.01, 2, 0, 0, 0, 0, 0, 10, 0, 0),
        @(40, 3, "Filtro 10 mca", "", "YMT", "Y", "FLA FF", "FLA FF", "Filtro", 400, 400, 10, 0, 0, 0, 5000, 5000, 0, 1000, 0, 0),
        @(41, 3, "Hidrociclón", "", "SUP1", "Y", "NPT MT", "NPT MT", "", 100, 100, 0.002, 2, 0.5, 0, 800, 900, 5, 60, 0, 0),
        @(42, 3, "Hidrociclón", "", "SUP1", "Y", "NPT MT", "NPT MT", "", 100, 100, 0.003, 2, 0.5, 0, 800, 900, 5, 60, 0, 0),
        @(50, 11, "Codo 90° 63 mm", "", "SUP1", "Y", "PVC", "", "", 63, 63, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0),
        @(99, 1, "Fila borrada", "", "SUP1", "L", "PVC", "", "", 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    )
    $marcas = (1..21 | % { "?" }) -join ", "
    foreach ($f in $componentes) {
        Sql ("INSERT INTO Components ([Component Key], [Database Number], Description, [Warehouse Code], " +
             "[Supplier Code], [Usage], Major1, Minor1, Major2, Reals1, Reals2, Reals3, Reals4, Reals5, Reals6, " +
             "Reals7, Reals8, Rextra1, Rextra2, Rextra3, Rextra4) VALUES ($marcas)") $f
    }
    Sql "DELETE FROM Components WHERE [Component Key] = 99"
    # Clave, tipo de cálculo, K, x, factor de inserción, espaciamiento, presión de entrada,
    # caudal específico, presión mínima, máxima, tolerancia sobre y bajo
    foreach ($f in @(@(20, "ITER", 2, 0, 0.8, 0.5, 10, 4, 7, 30, 20, 0),
                     @(21, "ITER", 0.352, 0.45, 0.06, 0.2, 10, 5, 7.1, 10, 30, 10))) {
        Sql "INSERT INTO Tapes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)" $f
    }

    # Tabla para probar los tipos de columna del lector.
    Sql "CREATE TABLE Tipos ([Id] COUNTER, [Texto] TEXT(255) $comp, [Nota] MEMO $comp, [Fecha] DATETIME, [Si] BIT, [Dinero] CURRENCY, [Doble] DOUBLE, [Corto] SHORT, [Octeto] BYTE)"
    $largo = ("Riego por goteo con eñe y tilde á. " * 7).Substring(0, 240)
    Sql "INSERT INTO Tipos (Texto, Nota, Fecha, Si, Dinero, Doble, Corto, Octeto) VALUES (?, ?, ?, ?, ?, ?, ?, ?)" @(
        $largo, "Memo corto", [datetime]"2026-10-11 08:30:00", $true, [decimal]1234.5678, 3.14159265358979, -12, 200)
    Sql "INSERT INTO Tipos (Texto) VALUES (NULL)"
    Sql "INSERT INTO Tipos (Texto, Nota, Si) VALUES (?, ?, ?)" @("Memo largo", ("0123456789" * 1000), $false)
    Sql "ALTER TABLE Tipos ADD COLUMN Agregada LONG"
    Sql "INSERT INTO Tipos (Texto, Nota, Agregada) VALUES (?, ?, ?)" @("Con columna agregada", ("abcdefghij" * 150), 42)
    $c.Close()
}

Crear-Base (Join-Path $carpeta "irricad_jet3.mdb") 4 ""
Crear-Base (Join-Path $carpeta "irricad_jet4.mdb") 5 "WITH COMPRESSION"
