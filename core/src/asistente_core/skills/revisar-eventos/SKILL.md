---
name: revisar-eventos
title: Revisar los registros de Windows
description: Buscar señales de ataques o actividad sospechosa en los registros de eventos de Windows (lo que pasó en la PC los últimos días).
examples:
  - revisa los registros de eventos
  - ¿ha pasado algo raro en mi pc esta semana?
  - busca actividad sospechosa en los logs de windows
  - revisa los eventos de seguridad
  - ¿alguien entró a mi computadora?
  - haz un análisis de los registros de windows de los últimos 3 días
---
1. Llama a revisar_eventos_de_windows con los días que diga el usuario (7 si no dice).
   Solo si pide literalmente la revisión completa o el registro de Seguridad, usa
   revisar_eventos_completo (pide permiso con una ventana; no preguntes tú antes).
2. Si la herramienta falló, di que no se pudo revisar y por qué. Nunca digas que no hay
   alertas si no se pudo revisar.
   Si funcionó y no hay alertas, dilo claro: "No encontré nada raro en los últimos N días".
   Si solo hay alertas de nivel medio, empieza con "Nada grave: no hay alertas críticas ni
   altas" y después resume las medias; no digas "nada raro" si hay alertas.
3. Si hay alertas, empieza por las de nivel crítico y alto: qué es cada una en palabras
   sencillas, cuántas veces y cuándo. Las de nivel medio resúmelas en una frase.
4. Recuerda que una alerta no es prueba de ataque: muchos programas legítimos las disparan.
   Si en el "ejemplo" se ve un programa que el usuario seguramente usa (un instalador,
   Visual Studio Code, Ollama, Moni, el antivirus), dilo como probable falsa alarma.
5. Si una alerta nombra una técnica o un programa de Windows y hace falta explicarla, usa
   consultar_attack o consultar_programa_windows.
6. Si fue la revisión sin administrador, menciona en una frase que el registro de Seguridad
   no se revisó y que puede pedir la revisión completa.
