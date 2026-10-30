import { type ReactNode, useEffect, useRef, useSyncExternalStore } from "react";
import { useRouter } from "../lib/router";
import { Icon } from "./icons";

/** Tela com título grande e barra de ações (como `.navigationTitle` + `.toolbar`). */
export function Screen({
  title,
  subtitle,
  toolbar,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  toolbar?: ReactNode;
  children: ReactNode;
}) {
  const router = useRouter();
  const depth = useSyncExternalStore(router.subscribe, () => router.state.path.length);
  useEffect(() => {
    document.title = `${title} — Noxora Ponto`;
  }, [title]);
  return (
    <div className="screen">
      <header className="navbar">
        {depth > 1 && (
          <button className="plain back" onClick={router.pop}>
            <Icon name="chevronLeft" /> Voltar
          </button>
        )}
        <h1>
          {title}
          {subtitle && <span className="subtitle">{subtitle}</span>}
        </h1>
        {toolbar && <div className="toolbar">{toolbar}</div>}
      </header>
      {children}
    </div>
  );
}

/** Seção de lista agrupada (como `Section` dentro de `List(.insetGrouped)`). */
export function Group({
  title,
  aside,
  footer,
  padded,
  children,
}: {
  title?: ReactNode;
  aside?: ReactNode;
  footer?: ReactNode;
  padded?: boolean;
  children: ReactNode;
}) {
  return (
    <section className="group">
      {(title || aside) && (
        <header>
          {title && <h2>{title}</h2>}
          {aside && <span className="aside">{aside}</span>}
        </header>
      )}
      <div className={padded ? "group-body padded" : "group-body"}>{children}</div>
      {footer && <footer>{footer}</footer>}
    </section>
  );
}

export function Row({
  title,
  subtitle,
  value,
  accessory,
  onClick,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  value?: ReactNode;
  accessory?: ReactNode;
  onClick?: () => void;
}) {
  const body = (
    <>
      <span className="title">
        {title}
        {subtitle && <small>{subtitle}</small>}
      </span>
      {value !== undefined && <span className="value">{value}</span>}
      {accessory}
      {onClick && (
        <span className="chevron">
          <Icon name="chevronRight" size={16} />
        </span>
      )}
    </>
  );
  return onClick ? (
    <button className="row" onClick={onClick}>
      {body}
    </button>
  ) : (
    <div className="row">{body}</div>
  );
}

export function Badge({
  tone,
  children,
}: {
  tone?: "tint" | "amber" | "seal" | "night";
  children: ReactNode;
}) {
  return <span className={tone ? `badge ${tone}` : "badge"}>{children}</span>;
}

export function Stats({ children }: { children: ReactNode }) {
  return <div className="stats">{children}</div>;
}

export function Stat({
  label,
  figure,
  tone,
}: {
  label: string;
  figure: ReactNode;
  tone?: "tint" | "amber" | "seal";
}) {
  return (
    <div className={tone ? `stat ${tone}` : "stat"}>
      <div className="label">{label}</div>
      <div className="figure">{figure}</div>
    </div>
  );
}

/** O "ponto" da marca: preenchido = estado/registro real; vazado = pendente; sem estado = decorativo. */
export function Dot({ state }: { state?: "on" | "warn" | "bad" | "hollow" | "hollow-warn" }) {
  const cls = state === "hollow-warn" ? "dot hollow warn" : state ? `dot ${state}` : "dot deco";
  return <span className={cls} aria-hidden="true" />;
}

/** Indicador que abre a lista correspondente. */
export function Kpi({
  label,
  figure,
  hint,
  tone,
  dot,
  onClick,
}: {
  label: string;
  figure: ReactNode;
  hint?: ReactNode;
  tone?: "tint" | "amber" | "seal";
  dot?: "on" | "warn" | "bad" | "hollow";
  onClick: () => void;
}) {
  return (
    <button className={tone ? `kpi ${tone}` : "kpi"} onClick={onClick}>
      <span className="label">
        {dot && <Dot state={dot} />}
        {label}
        <span className="go">
          <Icon name="chevronRight" size={16} />
        </span>
      </span>
      <span className="figure">{figure}</span>
      {hint && <span className="hint">{hint}</span>}
    </button>
  );
}

export function Loading({ label = "Carregando…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" /> {label}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function ErrorText({ message }: { message: string | null | undefined }) {
  return message ? <p role="alert">{message}</p> : null;
}

/** Rodapé de listas paginadas: diz quantos itens aparecem do total real e oferece "Mostrar mais". */
export function LoadMore({
  shown,
  total,
  hasMore,
  loading,
  onMore,
}: {
  shown: number;
  total: number;
  hasMore: boolean;
  loading: boolean;
  onMore: () => void;
}) {
  if (!total) return null;
  return (
    <p
      className="muted"
      style={{ display: "flex", gap: 12, alignItems: "center", margin: "8px 0" }}
    >
      <span>
        Mostrando {shown} de {total}.
      </span>
      {hasMore && (
        <button className="plain" disabled={loading} onClick={onMore}>
          {loading ? "Carregando…" : "Mostrar mais"}
        </button>
      )}
    </p>
  );
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <label className="field">
      {label}
      {children}
      {hint && <small style={{ color: "var(--ink-3)" }}>{hint}</small>}
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: [T, string][];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([key, text]) => (
        <button key={key} type="button" aria-pressed={value === key} onClick={() => onChange(key)}>
          {text}
        </button>
      ))}
    </div>
  );
}

/** Folha modal (como `.sheet`). Fecha com Esc, no botão ou ao concluir. */
export function Sheet({
  title,
  open,
  onClose,
  children,
  side,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  side?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);
  if (!open) return null;
  return (
    <dialog
      ref={ref}
      className={side ? "sheet side" : "sheet"}
      aria-label={title}
      onCancel={onClose}
      onClose={onClose}
    >
      <div className="sheet-header">
        <h2>{title}</h2>
        <button className="plain" onClick={onClose} aria-label="Fechar">
          <Icon name="x" size={18} /> {side ? "Fechar" : "Cancelar"}
        </button>
      </div>
      <div className="sheet-body">{children}</div>
    </dialog>
  );
}

export function Download({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a className="button" href={href} download>
      <Icon name="download" size={16} />
      {children}
    </a>
  );
}
