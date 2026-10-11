"""Lector de bases de datos de Microsoft Access (.mdb) en Python puro.

Lee las tablas de usuario de archivos Jet 3 (Access 97) y Jet 4 (Access
2000-2003) sin drivers ni programas externos. Solo lectura. Sigue la
descripción del formato del proyecto mdbtools (archivo HACKING).

Uso:
    base = BaseAccess("archivo.mdb")
    base.tablas()             # nombres de las tablas de usuario
    base.filas("Components")  # lista de diccionarios {columna: valor}
"""

import datetime
import struct
import uuid

# Tipos de columna
BOOLEANO, BYTE, ENTERO, ENTERO_LARGO, MONEDA, SIMPLE, DOBLE, FECHA = range(1, 9)
BINARIO, TEXTO, OLE, MEMO = 0x09, 0x0A, 0x0B, 0x0C
GUID = 0x0F

PAGINA_DATOS, PAGINA_TABLA, PAGINA_MAPA = 0x01, 0x02, 0x05
FILA_BORRADA, FILA_DESBORDADA, MASCARA_POSICION = 0x8000, 0x4000, 0x1FFF
COLUMNA_FIJA = 0x01
PAGINA_TABLA_SISTEMA = 2  # MSysObjects
OBJETO_TABLA = 1
FECHA_BASE = datetime.datetime(1899, 12, 30)


class ErrorMdb(Exception):
    """El archivo no es una base de Access legible."""


class _Formato:
    def __init__(self, jet3):
        self.jet3 = jet3
        self.pagina = 2048 if jet3 else 4096
        self.inicio_filas = 8 if jet3 else 12  # posición del número de filas en una página de datos
        # Definición de la tabla (TDEF)
        self.tdef_num_columnas_var = 23 if jet3 else 43
        self.tdef_num_columnas = 25 if jet3 else 45
        self.tdef_num_indices_reales = 31 if jet3 else 51
        self.tdef_mapa_uso = 35 if jet3 else 55
        self.tdef_inicio_indices = 43 if jet3 else 63
        self.tamano_indice = 8 if jet3 else 12
        self.tamano_columna = 18 if jet3 else 25
        self.columna_numero = 1 if jet3 else 5
        self.columna_offset_v = 3 if jet3 else 7
        self.columna_bits = 13 if jet3 else 15
        self.columna_offset_f = 14 if jet3 else 21
        self.columna_largo = 16 if jet3 else 23


class Columna:
    def __init__(self, nombre, tipo, numero, indice_variable, posicion_fija, largo, fija):
        self.nombre = nombre
        self.tipo = tipo
        self.numero = numero
        self.indice_variable = indice_variable
        self.posicion_fija = posicion_fija
        self.largo = largo
        self.fija = fija

    def __repr__(self):
        return f"Columna({self.nombre!r}, tipo={self.tipo})"


class BaseAccess:
    def __init__(self, ruta, codificacion_jet3="cp1252"):
        with open(ruta, "rb") as archivo:
            self.datos = archivo.read()
        if len(self.datos) < 2048 or self.datos[0] != 0 or self.datos[4:19] not in (
                b"Standard Jet DB", b"Standard ACE DB"):
            raise ErrorMdb("El archivo no es una base de datos de Microsoft Access (.mdb).")
        self.formato = _Formato(jet3=self.datos[0x14] == 0)
        self.codificacion_jet3 = codificacion_jet3
        self._tablas = None

    # ------------------------------------------------------------ páginas

    def _pagina(self, numero):
        tamano = self.formato.pagina
        inicio = numero * tamano
        if numero < 0 or inicio + tamano > len(self.datos):
            raise ErrorMdb(f"Página {numero} fuera del archivo.")
        return self.datos[inicio:inicio + tamano]

    def _limites_fila(self, pagina, fila):
        """(inicio, fin, banderas) de una fila de una página de datos; fin no incluido."""
        base = self.formato.inicio_filas
        num_filas = struct.unpack_from("<H", pagina, base)[0]
        if fila >= num_filas:
            raise ErrorMdb("Puntero a una fila inexistente.")
        bruto = struct.unpack_from("<H", pagina, base + 2 + 2 * fila)[0]
        fin = self.formato.pagina if fila == 0 else \
            struct.unpack_from("<H", pagina, base + 2 * fila)[0] & MASCARA_POSICION
        return bruto & MASCARA_POSICION, fin, bruto & ~MASCARA_POSICION

    def _fila_apuntada(self, puntero):
        """Bytes de la fila indicada por un puntero de 4 bytes (fila: 1 byte, página: 3 bytes)."""
        pagina = self._pagina(puntero >> 8)
        inicio, fin, _ = self._limites_fila(pagina, puntero & 0xFF)
        return pagina[inicio:fin]

    # ------------------------------------------------------------ tablas

    def tablas(self):
        """Nombres de las tablas de usuario."""
        return list(self._catalogo())

    def _catalogo(self):
        if self._tablas is None:
            self._tablas = {}
            columnas, paginas = self._definicion(PAGINA_TABLA_SISTEMA)
            for fila in self._recorrer(PAGINA_TABLA_SISTEMA, columnas, paginas):
                nombre = fila.get("Name") or ""
                if (fila.get("Type") == OBJETO_TABLA and not nombre.startswith("MSys")
                        and not (fila.get("Flags") or 0) & 0x80000002):
                    self._tablas[nombre] = fila["Id"] & 0x00FFFFFF
        return self._tablas

    def columnas(self, tabla):
        return [c.nombre for c in self._definicion(self._pagina_tabla(tabla))[0]]

    def filas(self, tabla):
        """Filas de una tabla como diccionarios {nombre de columna: valor}."""
        pagina = self._pagina_tabla(tabla)
        columnas, paginas = self._definicion(pagina)
        return list(self._recorrer(pagina, columnas, paginas))

    def _pagina_tabla(self, tabla):
        catalogo = self._catalogo()
        if tabla not in catalogo:
            raise KeyError(f"La base no tiene la tabla «{tabla}».")
        return catalogo[tabla]

    def _definicion(self, numero_pagina):
        """Columnas de una tabla y las páginas de datos que usa."""
        f = self.formato
        pagina = self._pagina(numero_pagina)
        if pagina[0] != PAGINA_TABLA:
            raise ErrorMdb(f"La página {numero_pagina} no es una definición de tabla.")
        tdef = bytearray(pagina)
        siguiente = struct.unpack_from("<I", pagina, 4)[0]
        while siguiente:  # definición repartida en varias páginas
            otra = self._pagina(siguiente)
            tdef += otra[8:]
            siguiente = struct.unpack_from("<I", otra, 4)[0]

        num_columnas = struct.unpack_from("<H", tdef, f.tdef_num_columnas)[0]
        num_indices_reales = struct.unpack_from("<I", tdef, f.tdef_num_indices_reales)[0]
        mapa_uso = struct.unpack_from("<I", tdef, f.tdef_mapa_uso)[0]
        posicion = f.tdef_inicio_indices + num_indices_reales * f.tamano_indice
        crudas = []
        for _ in range(num_columnas):
            c = tdef[posicion:posicion + f.tamano_columna]
            crudas.append((c[0], struct.unpack_from("<H", c, f.columna_numero)[0],
                           struct.unpack_from("<H", c, f.columna_offset_v)[0],
                           struct.unpack_from("<H", c, f.columna_offset_f)[0],
                           struct.unpack_from("<H", c, f.columna_largo)[0],
                           bool(c[f.columna_bits] & COLUMNA_FIJA)))
            posicion += f.tamano_columna
        columnas = []
        for tipo, numero, indice_v, posicion_f, largo, fija in crudas:
            if f.jet3:
                largo_nombre = tdef[posicion]
                nombre = bytes(tdef[posicion + 1:posicion + 1 + largo_nombre]).decode(
                    self.codificacion_jet3, "replace")
                posicion += 1 + largo_nombre
            else:
                largo_nombre = struct.unpack_from("<H", tdef, posicion)[0]
                nombre = bytes(tdef[posicion + 2:posicion + 2 + largo_nombre]).decode("utf-16-le", "replace")
                posicion += 2 + largo_nombre
            columnas.append(Columna(nombre, tipo, numero, indice_v, posicion_f, largo, fija))
        columnas.sort(key=lambda c: c.numero)
        return columnas, self._paginas_en_uso(mapa_uso, numero_pagina)

    def _paginas_en_uso(self, puntero_mapa, pagina_tabla):
        """Páginas de datos de la tabla según su mapa de uso."""
        try:
            mapa = self._fila_apuntada(puntero_mapa)
            paginas = self._leer_mapa(mapa)
        except (ErrorMdb, struct.error, IndexError):
            paginas = range(len(self.datos) // self.formato.pagina)  # recorrido completo
        tamano = self.formato.pagina
        return [p for p in paginas
                if (p + 1) * tamano <= len(self.datos)
                and self.datos[p * tamano] == PAGINA_DATOS
                and struct.unpack_from("<I", self.datos, p * tamano + 4)[0] == pagina_tabla]

    def _leer_mapa(self, mapa):
        paginas = []
        if mapa[0] == 0:  # mapa en línea: página inicial + mapa de bits
            inicio = struct.unpack_from("<I", mapa, 1)[0]
            for i, byte in enumerate(mapa[5:]):
                paginas.extend(inicio + 8 * i + b for b in range(8) if byte >> b & 1)
        elif mapa[0] == 1:  # mapa por referencias: páginas que contienen los mapas de bits
            bits_por_pagina = (self.formato.pagina - 4) * 8
            for j in range((len(mapa) - 1) // 4):
                pagina_mapa = struct.unpack_from("<I", mapa, 1 + 4 * j)[0]
                if not pagina_mapa:
                    continue
                bits = self._pagina(pagina_mapa)
                if bits[0] != PAGINA_MAPA:
                    raise ErrorMdb("Mapa de uso dañado.")
                for i, byte in enumerate(bits[4:]):
                    paginas.extend(j * bits_por_pagina + 8 * i + b for b in range(8) if byte >> b & 1)
        else:
            raise ErrorMdb("Tipo de mapa de uso desconocido.")
        return paginas

    # ------------------------------------------------------------ filas

    def _recorrer(self, pagina_tabla, columnas, paginas):
        normales, desbordadas, destinos = [], [], set()
        for numero in paginas:
            pagina = self._pagina(numero)
            num_filas = struct.unpack_from("<H", pagina, self.formato.inicio_filas)[0]
            for fila in range(num_filas):
                inicio, fin, banderas = self._limites_fila(pagina, fila)
                if banderas & FILA_BORRADA or fin <= inicio:
                    continue
                if banderas & FILA_DESBORDADA:  # la fila se movió a otra página
                    puntero = struct.unpack_from("<I", pagina, inicio)[0]
                    desbordadas.append(puntero)
                    destinos.add(puntero)
                else:
                    normales.append((numero << 8 | fila, pagina[inicio:fin]))
        for puntero, datos in normales:
            if puntero not in destinos:
                yield self._decodificar_fila(datos, columnas)
        for puntero in desbordadas:
            yield self._decodificar_fila(self._fila_apuntada(puntero), columnas)

    def _decodificar_fila(self, fila, columnas):
        jet3 = self.formato.jet3
        bytes_conteo = 1 if jet3 else 2
        num_columnas = fila[0] if jet3 else struct.unpack_from("<H", fila, 0)[0]
        largo = len(fila)
        tamano_nulos = (num_columnas + 7) // 8
        nulos = fila[largo - tamano_nulos:]

        num_variables = 0
        posiciones = []
        if any(not c.fija for c in columnas):
            if jet3:
                num_variables = fila[largo - tamano_nulos - 1]
                posiciones = self._posiciones_jet3(fila, tamano_nulos, num_variables)
            else:
                num_variables = struct.unpack_from("<H", fila, largo - tamano_nulos - 2)[0]
                posiciones = [struct.unpack_from("<H", fila, largo - tamano_nulos - 4 - 2 * i)[0]
                              for i in range(num_variables + 1)]

        resultado = {}
        fijas_encontradas = 0
        fijas_en_fila = num_columnas - num_variables
        for c in columnas:
            presente = c.numero // 8 < len(nulos) and bool(nulos[c.numero // 8] >> (c.numero % 8) & 1)
            if c.tipo == BOOLEANO:
                resultado[c.nombre] = presente
                continue
            datos = None
            if c.fija and fijas_encontradas < fijas_en_fila:
                inicio = bytes_conteo + c.posicion_fija
                datos = fila[inicio:inicio + c.largo]
                fijas_encontradas += 1
            elif not c.fija and c.indice_variable < num_variables:
                datos = fila[posiciones[c.indice_variable]:posiciones[c.indice_variable + 1]]
            resultado[c.nombre] = self._valor(c, datos) if presente and datos is not None else None
        return resultado

    @staticmethod
    def _posiciones_jet3(fila, tamano_nulos, num_variables):
        """Posiciones de las columnas variables (1 byte cada una, con tabla de saltos de 256 bytes)."""
        largo = len(fila)
        fin = largo - 1  # último byte de la fila
        saltos = (largo - 1) // 256
        puntero = fin - tamano_nulos - saltos - 1
        if (puntero - num_variables) // 256 < saltos:  # el último salto es de relleno
            saltos -= 1
        usados = 0
        posiciones = []
        for i in range(num_variables + 1):
            while usados < saltos and i == fila[fin - tamano_nulos - usados - 1]:
                usados += 1
            posiciones.append(fila[puntero - i] + 256 * usados)
        return posiciones

    def _valor(self, columna, datos):
        tipo = columna.tipo
        try:
            if tipo == BYTE:
                return datos[0]
            if tipo == ENTERO:
                return struct.unpack_from("<h", datos)[0]
            if tipo == ENTERO_LARGO:
                return struct.unpack_from("<i", datos)[0]
            if tipo == MONEDA:
                return struct.unpack_from("<q", datos)[0] / 10000.0
            if tipo == SIMPLE:
                # Precisión simple: siete cifras, como las muestra Access (0.719 y no 0.71899998).
                return float(f"{struct.unpack_from('<f', datos)[0]:.7g}")
            if tipo == DOBLE:
                return struct.unpack_from("<d", datos)[0]
            if tipo == FECHA:
                return FECHA_BASE + datetime.timedelta(days=struct.unpack_from("<d", datos)[0])
            if tipo == TEXTO:
                return self._texto(datos)
            if tipo == MEMO:
                return self._texto(self._valor_largo(datos))
            if tipo == OLE:
                return self._valor_largo(datos)
            if tipo == GUID:
                return str(uuid.UUID(bytes_le=bytes(datos[:16])))
        except (struct.error, IndexError, ValueError, OverflowError, ErrorMdb):
            return None
        return bytes(datos)  # binario y tipos sin interpretar (p. ej. decimal)

    def _texto(self, datos):
        datos = bytes(datos)
        if self.formato.jet3:
            return datos.decode(self.codificacion_jet3, "replace")
        if datos[:2] == b"\xff\xfe":  # Unicode comprimido de Jet 4
            caracteres, comprimido, i = [], True, 2
            while i < len(datos):
                if datos[i] == 0:
                    comprimido = not comprimido
                    i += 1
                elif comprimido:
                    caracteres.append(chr(datos[i]))
                    i += 1
                else:
                    caracteres.append(datos[i:i + 2].decode("utf-16-le", "replace"))
                    i += 2
            return "".join(caracteres)
        return datos.decode("utf-16-le", "replace")

    def _valor_largo(self, datos):
        """Contenido de un memo u objeto OLE: en la fila o en páginas de valores largos."""
        cabecera = struct.unpack_from("<I", datos, 0)[0]
        largo = cabecera & 0x3FFFFFFF
        if cabecera & 0x80000000:
            return bytes(datos[12:12 + largo])
        puntero = struct.unpack_from("<I", datos, 4)[0]
        if cabecera & 0x40000000:
            return self._fila_apuntada(puntero)[:largo]
        partes = []
        while puntero and sum(map(len, partes)) < largo:
            fila = self._fila_apuntada(puntero)
            puntero = struct.unpack_from("<I", fila, 0)[0]
            partes.append(fila[4:])
        return b"".join(partes)[:largo]
