/** Ícones de traço simples (estilo SF Symbols), 18 px, herdam a cor do texto. */
const paths: Record<string, string> = {
  today: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  sheet: "M4 6h16M4 12h16M4 18h10",
  inbox: "M4 13h4l2 3h4l2-3h4M5 5h14l1 8v6H4v-6l1-8Z",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z",
  people:
    "M16 19v-1a4 4 0 0 0-8 0v1M12 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM20 19v-1a3 3 0 0 0-2-2.8M16.5 5.2a3 3 0 0 1 0 5.6",
  pulse: "M3 12h4l2-5 4 10 2-5h6",
  list: "M8 6h13M8 12h13M8 18h13M4 6h.01M4 12h.01M4 18h.01",
  building: "M4 21V5l8-2v18M12 21V9l8 2v10M4 21h16M8 8h.01M8 12h.01M8 16h.01",
  calendar: "M4 7h16v13H4zM4 11h16M8 4v3M16 4v3",
  tablet: "M6 3h12v18H6zM11 18h2",
  scale: "M12 4v16M5 8h14M7 8l-3 6a3 3 0 0 0 6 0L7 8ZM17 8l-3 6a3 3 0 0 0 6 0l-3-6Z",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  card: "M3 6h18v12H3zM3 10h18",
  key: "M15 7a4 4 0 1 1-3.5 6H9v2H7v2H4v-3l6.5-6.5A4 4 0 0 1 15 7Z",
  person: "M18 20v-1a5 5 0 0 0-10 0v1M13 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  chevronLeft: "M15 18l-6-6 6-6",
  chevronRight: "M9 6l6 6-6 6",
  chevronDown: "M6 9l6 6 6-6",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  plus: "M12 5v14M5 12h14",
  check: "M5 12l5 5 9-10",
  x: "M6 6l12 12M18 6 6 18",
  menu: "M4 7h16M4 12h16M4 17h16",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3Z",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01",
  alert: "M12 4l9 16H3L12 4ZM12 10v4M12 17h.01",
  receipt: "M6 3h12v18l-3-2-3 2-3-2-3 2V3ZM9 8h6M9 12h6",
  home: "M4 11l8-7 8 7v9H4z",
};

export type IconName = keyof typeof paths;

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
