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
1. Llama a revisar_eventos_de_windows. Usa los días que diga el usuario (7 si no dice).
   Pon completo=true solo si pide la revisión completa, el registro de Seguridad, o
   pregunta si alguien entró a su cuenta; avísale en una frase que Windows le va a pedir
   permiso de administrador.
2. Si no hay alertas, dilo claro: "No encontré nada raro en los últimos N días".
3. Si hay alertas, empieza por las de nivel crítico y alto: qué es cada una en palabras
   sencillas, cuántas veces y cuándo. Las de nivel medio resúmelas en una frase.
4. Recuerda que una alerta no es prueba de ataque: muchos programas legítimos las disparan.
   Si en el "ejemplo" se ve un programa que el usuario seguramente usa (un instalador,
   Visual Studio Code, Ollama, Moni, el antivirus), dilo como probable falsa alarma.
5. Si una alerta nombra una técnica o un programa de Windows y hace falta explicarla, usa
   consultar_attack o consultar_programa_windows.
6. Si fue la revisión sin administrador, menciona que el registro de Seguridad no se revisó.
