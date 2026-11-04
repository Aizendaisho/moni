/*
  Reglas YARA propias de Moni (MIT, como el resto del proyecto).

  Son heurísticas generales: detectan técnicas que usa el malware común (descargar y ejecutar
  código, PowerShell ofuscado, robo de contraseñas del navegador, ejecutables escondidos dentro
  de documentos...), no familias concretas. Un acierto significa "mira esto con cuidado", no
  "es un virus seguro".

  Cada regla lleva:
    gravedad    = "alta" | "media" | "baja"
    descripcion = explicación corta en español, la que Moni le muestra al usuario

  Para añadir reglas de la comunidad (por ejemplo signature-base de Neo23x0, licencia DRL 1.1),
  copia los archivos .yar a data/reglas-yara/. Moni los compila junto con estas.
*/

rule Moni_Prueba_EICAR
{
    meta:
        gravedad = "alta"
        descripcion = "Archivo de prueba EICAR: no es dañino, existe para comprobar que los antivirus funcionan"
    strings:
        $eicar = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    condition:
        $eicar at 0 or ($eicar and filesize < 256)
}

rule Moni_PowerShell_Codificado
{
    meta:
        gravedad = "media"
        descripcion = "Lanza PowerShell con un comando codificado en Base64, una forma típica de esconder lo que hace"
    strings:
        $a = /powershell(\.exe)?["']?\s[^\n]{0,80}\s-(e|en|enc|enco|encod|encode|encoded|encodedc|encodedcommand)\s+[A-Za-z0-9+\/=]{40,}/ nocase
        $b = /powershell(\.exe)?["']?\s[^\n]{0,80}-w(indowstyle)?\s+h(idden)?[^\n]{0,80}-e(nc|ncodedcommand)?\s/ nocase
    condition:
        any of them
}

rule Moni_Descarga_Y_Ejecuta
{
    meta:
        gravedad = "media"
        descripcion = "Descarga código de internet y lo ejecuta al momento (técnica de los descargadores de malware)"
    strings:
        $d1 = "DownloadString" nocase
        $d2 = "DownloadFile" nocase
        $d3 = "Invoke-WebRequest" nocase
        $d4 = "Net.WebClient" nocase
        $d5 = "URLDownloadToFile" nocase
        $d6 = "MSXML2.XMLHTTP" nocase
        $d7 = "WinHttp.WinHttpRequest" nocase
        $e1 = "Invoke-Expression" nocase
        $e2 = /\biex\b/ nocase
        $e3 = "Start-Process" nocase
        $e4 = "WScript.Shell" nocase
        $e5 = "Shell.Application" nocase
        $e6 = /\.(Run|ShellExecute)\s*\(/ nocase
    condition:
        uint16(0) != 0x5A4D and any of ($d*) and any of ($e*)
}

rule Moni_LOLBin_Remoto
{
    meta:
        gravedad = "media"
        descripcion = "Usa programas de Windows (mshta, regsvr32, certutil, bitsadmin, rundll32) para traer o ejecutar código remoto"
    strings:
        $a = /mshta(\.exe)?["']?\s+["']?(https?:|javascript:|vbscript:)/ nocase
        $b = /regsvr32(\.exe)?[^\n]{0,60}\/i:https?:[^\n]{0,200}scrobj/ nocase
        $c = /certutil(\.exe)?[^\n]{0,40}-urlcache[^\n]{0,40}-f/ nocase
        $d = /certutil(\.exe)?[^\n]{0,40}-decode/ nocase
        $e = /bitsadmin(\.exe)?[^\n]{0,40}\/transfer/ nocase
        $f = /rundll32(\.exe)?[^\n]{0,40}javascript:/ nocase
    condition:
        uint16(0) != 0x5A4D and any of them
}

rule Moni_Ladron_De_Contrasenas
{
    meta:
        gravedad = "media"
        descripcion = "Programa que busca contraseñas, cookies o carteras guardadas de navegadores y apps (comportamiento de los 'stealers')"
    strings:
        $a = "\\Login Data" ascii wide nocase
        $b = "logins.json" ascii wide nocase
        $c = "wallet.dat" ascii wide nocase
        $d = "\\Local Storage\\leveldb" ascii wide nocase
        $e = "Telegram Desktop\\tdata" ascii wide nocase
        $f = "\\Network\\Cookies" ascii wide nocase
        $g = "key4.db" ascii wide nocase
        $h = "Exodus\\exodus.wallet" ascii wide nocase
    condition:
        uint16(0) == 0x5A4D and 4 of them
}

rule Moni_Nota_De_Rescate
{
    meta:
        gravedad = "alta"
        descripcion = "Texto típico de ransomware: dice que tus archivos fueron cifrados y pide un pago"
    strings:
        $a = "files have been encrypted" ascii wide nocase
        $b = "archivos han sido cifrados" ascii wide nocase
        $c = "archivos han sido encriptados" ascii wide nocase
        $d = "decrypt your files" ascii wide nocase
        $p1 = "bitcoin" ascii wide nocase
        $p2 = "monero" ascii wide nocase
        $p3 = ".onion" ascii wide nocase
        $p4 = "BTC" ascii wide
    condition:
        any of ($a, $b, $c, $d) and any of ($p*)
}

rule Moni_Ejecutable_Escondido
{
    meta:
        gravedad = "media"
        descripcion = "Lleva un programa de Windows (.exe) escondido dentro de un archivo que no es un programa"
    strings:
        $dos = "This program cannot be run in DOS mode"
    condition:
        uint16(0) != 0x5A4D and uint32(0) != 0x04034B50 and $dos in (64..filesize)
}

rule Moni_RTF_Con_Objetos_Peligrosos
{
    meta:
        gravedad = "alta"
        descripcion = "Documento RTF con objetos que se usan en ataques conocidos de Office (Editor de ecuaciones, OLE Package)"
    strings:
        $rtf = "{\\rt"
        $o1 = "\\objupdate" nocase
        $o2 = "4571756174696F6E2E33" nocase   // "Equation.3" en hex
        $o3 = "Equation.3" nocase
        $o4 = "5061636b616765" nocase         // "Package" en hex
        $o5 = "\\objdata" nocase
    condition:
        $rtf at 0 and $o5 and any of ($o1, $o2, $o3, $o4)
}

rule Moni_HTML_Contrabando
{
    meta:
        gravedad = "media"
        descripcion = "Página HTML que arma un archivo dentro del navegador y lo descarga sola (HTML smuggling)"
    strings:
        $h = "<html" nocase
        $a = "msSaveOrOpenBlob" nocase
        $b = "atob(" nocase
        $c = "new Blob(" nocase
        $d = ".download" nocase
        $e = "createObjectURL" nocase
    condition:
        $h and ($a or ($b and $c and $d and $e)) and filesize < 20MB
}

rule Moni_Acceso_Directo_Sospechoso
{
    meta:
        gravedad = "media"
        descripcion = "Acceso directo (.lnk) que lanza PowerShell, cmd, mshta o un script: así se disfrazan muchos ataques"
    strings:
        $p1 = "powershell" ascii wide nocase
        $p2 = "cmd.exe" ascii wide nocase
        $p3 = "mshta" ascii wide nocase
        $p4 = "wscript" ascii wide nocase
        $p5 = "cscript" ascii wide nocase
        $p6 = "rundll32" ascii wide nocase
    condition:
        uint32(0) == 0x0000004C and any of them
}
