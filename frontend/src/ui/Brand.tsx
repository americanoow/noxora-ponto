/** Marca: "Noxora" + o ponto (assinatura), seguido do nome do produto. */
export function Brand() {
  return (
    <div className="brand">
      <span>
        Noxora
        <span className="brand-dot" aria-hidden="true" />
      </span>
      <small>Ponto</small>
    </div>
  );
}
