---
name: pc-lenta
title: PC lenta
description: Averiguar por qué la computadora está lenta o qué programa la está cargando (CPU, RAM).
examples:
  - la pc está lenta
  - ¿por qué mi computadora va tan lenta?
  - se me está trabando la laptop
  - ¿qué está consumiendo tanto?
  - el ventilador suena mucho, ¿qué está usando la cpu?
  - la compu está pegada
---
1. Llama a estado_sistema para ver CPU, RAM, disco y batería.
2. Llama a listar_procesos con ordenar_por="cpu" y limite=5.
3. Si la RAM pasa del 80 %, llama también a listar_procesos con ordenar_por="memoria".
4. Si el disco tiene menos de 10 GB libres, dilo: eso también vuelve lenta la PC.
5. Explica en dos o tres frases qué es lo que más carga y sugiere algo concreto, por ejemplo
   cerrar un programa que no se esté usando. Si propones cerrar uno, ofrécelo; no lo cierres
   sin que el usuario lo pida.
6. Nunca sugieras cerrar procesos de Windows ni los de Moni.
