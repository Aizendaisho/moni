---
name: explicar-programa
title: Qué hace un programa
description: Explicar qué puede hacer un programa (.exe o .dll) por dentro, sin ejecutarlo: si usa internet, el teclado, la pantalla, el registro u otros programas, y con qué tecnología está hecho.
examples:
  - ¿qué hace este programa por dentro?
  - ¿qué puede hacer setup.exe?
  - ¿ese exe se conecta a internet?
  - analiza el programa por dentro
  - ¿este programa puede leer lo que escribo?
  - ¿con qué está hecho este programa?
  - haz ingeniería inversa de este exe
---
1. Llama a explicar_programa con el nombre o la ruta que dijo el usuario. Si no dijo cuál,
   pregúntale. La primera vez puede tardar porque instala REA.
2. Explica en 3 a 5 frases, en lenguaje sencillo, lo que dice "puede". Empieza por lo de
   "a_vigilar" si lo hay (teclado, pantalla, memoria de otros programas) y explica por qué
   llama la atención.
3. Menciona la tecnología si viene (.NET, Go) y si tiene certificado incrustado.
4. Deja claro que es lo que PUEDE hacer según su estructura, no una prueba de que lo haga ni
   de que sea malicioso. Para saber si tiene virus, ofrece revisar_archivo.
5. Si falla porque falta Node.js, dilo tal cual y sugiere instalar Node.js 22 desde nodejs.org.
6. Nunca ofrezcas ejecutar el programa, depurarlo ni modificarlo.
