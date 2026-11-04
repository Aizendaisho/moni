---
name: explicar-amenaza
title: Explicar una amenaza
description: Explicar qué es un ataque, una técnica de hackeo, un malware conocido (Emotet, un ransomware) o por qué un programa de Windows puede ser peligroso, con datos de MITRE ATT&CK y LOLBAS.
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
2. Si preguntan por un ataque, una técnica, un id (T1566, S0367) o un malware, llama a
   consultar_attack. Pasa la consulta en inglés y corta ("ransomware", "keylogging",
   "phishing", "Emotet").
3. Explica en español sencillo, en 3 a 5 frases: qué es, cómo llega o qué hace, y cómo
   protegerse (usa "como_protegerse" si viene). Traduce tú los nombres técnicos.
4. Termina con la fuente, por ejemplo "(Fuente: MITRE ATT&CK T1486)".
5. No des instrucciones para atacar ni comandos de abuso: solo explica y protege.
6. Si la herramienta no encuentra nada, usa investigar.
7. Si la pregunta es sobre su propia PC ("¿tengo un keylogger?"), ofrece hacer el chequeo
   de seguridad o revisar sus descargas.
