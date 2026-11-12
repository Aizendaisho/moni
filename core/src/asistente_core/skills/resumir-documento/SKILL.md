---
name: resumir-documento
title: Resumir un documento largo
description: Resumir un ARCHIVO que ya está en la PC (PDF, Word, texto) o una URL concreta que da el usuario, por partes; si es un libro, en segundo plano.
examples:
  - resume este pdf
  - hazme un resumen del libro que está en descargas
  - resume el documento informe.docx
  - ¿de qué trata este pdf?
  - resume esta página https://es.wikipedia.org/wiki/Don_Quijote
  - resume el libro y guárdalo en un word
---
1. Llama a resumir_documento con el archivo o la URL que dijo el usuario. Si pidió guardarlo,
   pon guardar_como ("pdf" o "word"). Si no dijo qué archivo, pregúntale.
2. Si el resultado trae "resumen", muéstralo tal cual (puedes acortarlo si es muy largo) y di
   si quedó guardado en un documento.
3. Si trae estado "en segundo plano": di en una o dos frases que empezaste, cuántas partes son,
   cuántos minutos más o menos tardará y que avisarás aquí al terminar. NO escribas ningún
   resumen todavía ni inventes de qué trata.
4. Si falla (por ejemplo un PDF escaneado sin texto), di el motivo tal cual.
