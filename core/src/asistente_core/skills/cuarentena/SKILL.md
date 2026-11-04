---
name: cuarentena
title: Cuarentena
description: Apartar un archivo peligroso en la cuarentena, ver qué archivos hay apartados en ella o devolver uno.
examples:
  - pon ese archivo en cuarentena
  - aparta factura.exe
  - ¿qué hay en la cuarentena?
  - saca el pdf de la cuarentena
  - devuelve el archivo que apartaste
  - mueve ese virus a cuarentena
---
1. Para apartar un archivo: llama a poner_en_cuarentena con la ruta o el nombre y un motivo
   corto. La herramienta muestra la ventana de Sí/No: no preguntes tú antes por chat.
2. Para ver qué hay: llama a ver_cuarentena y di nombre, de dónde vino y por qué se apartó.
3. Para devolver uno: llama a sacar_de_cuarentena con el nombre o el id. Si se apartó por
   ser peligroso, recuérdalo en una frase antes de llamar a la herramienta.
4. La cuarentena no borra nada. Si piden borrar del todo, explica que todavía no lo haces
   tú: pueden borrarlo ellos desde la carpeta data\cuarentena.
5. Si el usuario dice que no en la ventana, respétalo y no insistas.
