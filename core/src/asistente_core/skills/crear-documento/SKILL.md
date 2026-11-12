---
name: crear-documento
title: Crear un documento
description: Escribir un documento nuevo (PDF o Word) con un resumen, un informe, apuntes o lo que pida el usuario, y guardarlo en Documentos\Moni.
examples:
  - haz un resumen del Quijote y guárdalo en un PDF
  - crea un documento de Word con lo que investigaste
  - guárdame eso en un pdf para leerlo después
  - escribe un informe sobre la energía solar en Word
  - pásame esto a un documento
  - hazme unos apuntes de la revolución francesa en pdf
---
1. Si el documento necesita información que no tienes en la conversación, consíguela
   primero: recordar (tu memoria) o investigar (internet). No inventes datos.
2. Escribe TODO el contenido del documento tú, en español, en Markdown sencillo: un párrafo
   de introducción, secciones con "## " y viñetas con "- ". Entre 300 y 900 palabras salvo
   que pidan otra cosa. Al final, una línea "Fuentes:" con las páginas que usaste.
3. Llama a crear_documento con un título claro, ese contenido completo y el formato que
   pidió ("pdf" si no dijo; "word" si dijo Word).
4. Responde corto: qué documento creaste y dónde quedó. Ofrece abrirlo (abrir_documento).
5. Si el usuario da un archivo largo (un libro en PDF) para resumir, usa resumir_documento
   con guardar_como en vez de escribirlo tú.
