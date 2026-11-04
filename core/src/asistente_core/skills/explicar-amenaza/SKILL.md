---
name: explicar-amenaza
title: Explicar una amenaza
description: Explicar qué es un ataque, una técnica de hackeo, un malware conocido (Emotet, un ransomware) o por qué un programa de Windows puede ser peligroso, con datos de MITRE ATT&CK y LOLBAS.
run_first: consultar_attack
examples:
  - ¿qué es un ransomware?
  - explícame qué es el phishing
  - ¿qué es un keylogger?
  - ¿qué hace Emotet?
  - ¿qué es la técnica T1059?
  - ¿mshta es peligroso?
  - ¿para qué usan los hackers certutil?
  - ¿cómo me protejo de los troyanos?
  - ¿qué es mimikatz?
---
1. Si preguntan por un programa de Windows (algo que termina en .exe, como mshta, certutil,
   rundll32, powershell), llama a consultar_programa_windows.
2. Ya recibiste el resultado de consultar_attack con el mensaje del usuario. Si no trae lo
   que preguntan, llama otra vez a consultar_attack con palabras clave cortas en inglés
   ("keylogging", "phishing", el nombre del malware).
3. Explica en español sencillo, en 3 a 5 frases: qué es, cómo llega o qué hace, y cómo
   protegerse (usa "como_protegerse" si viene). Traduce tú los nombres técnicos.
4. Termina con la fuente usando el id exacto que aparece en el resultado que usaste, con el
   formato "(Fuente: MITRE ATT&CK <id>)". Si no usaste ningún resultado, no pongas fuente.
5. No des instrucciones para atacar ni comandos de abuso: solo explica y protege.
6. Si la herramienta no encuentra nada, usa investigar.
7. Si la pregunta es sobre su propia PC ("¿tengo un keylogger?"), ofrece hacer el chequeo
   de seguridad o revisar sus descargas.
