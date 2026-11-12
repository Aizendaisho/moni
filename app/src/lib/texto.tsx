// Formato mínimo para las respuestas de Moni: títulos (## ), viñetas (- ), **negrita** y
// *cursiva*. Lo justo para que un resumen se lea bien sin mostrar los símbolos de Markdown.
import { Fragment, type ReactNode } from "react";

function enLinea(texto: string, clave: string): ReactNode {
  return texto.split(/(\*\*[^*\n]+\*\*|\*[^*\s][^*\n]*\*)/g).map((parte, i) => {
    if (parte.startsWith("**") && parte.endsWith("**") && parte.length > 4)
      return (
        <strong key={`${clave}-${i}`} className="font-semibold">
          {parte.slice(2, -2)}
        </strong>
      );
    if (parte.startsWith("*") && parte.endsWith("*") && parte.length > 2)
      return <em key={`${clave}-${i}`}>{parte.slice(1, -1)}</em>;
    return <Fragment key={`${clave}-${i}`}>{parte}</Fragment>;
  });
}

export function conFormato(texto: string): ReactNode {
  return texto.split("\n").map((linea, i) => {
    const titulo = linea.match(/^\s*#{1,3}\s+(.*)$/);
    if (titulo)
      return (
        <div key={i} className="mt-2 font-semibold text-cyan-200">
          {enLinea(titulo[1], `t${i}`)}
        </div>
      );
    const vineta = linea.match(/^\s*[-*•]\s+(.*)$/);
    if (vineta)
      return (
        <div key={i} className="pl-4 -indent-3">
          • {enLinea(vineta[1], `v${i}`)}
        </div>
      );
    return (
      <Fragment key={i}>
        {enLinea(linea, `l${i}`)}
        {"\n"}
      </Fragment>
    );
  });
}
