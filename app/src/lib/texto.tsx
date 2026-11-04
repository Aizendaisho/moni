// Formato mínimo para las respuestas de Moni. El modelo a veces usa **negritas** aunque se le
// pida texto plano; en vez de mostrar los asteriscos, se convierten en negrita de verdad.
import { Fragment, type ReactNode } from "react";

export function conFormato(texto: string): ReactNode {
  return texto.split(/(\*\*[^*\n]+\*\*)/g).map((parte, i) =>
    parte.startsWith("**") && parte.endsWith("**") && parte.length > 4 ? (
      <strong key={i} className="font-semibold">
        {parte.slice(2, -2)}
      </strong>
    ) : (
      <Fragment key={i}>{parte}</Fragment>
    ),
  );
}
