export function Icon({
  name,
  size = 20,
}: {
  name:
    | "sound"
    | "muted"
    | "settings"
    | "close"
    | "history"
    | "chevron"
    | "arrow"
    | "play"
    | "skip"
    | "pause"
    | "log"
    | "bookmark"
    | "user";
  size?: number;
}) {
  const paths = {
    sound: (
      <>
        <path d="M11 4 6 8H3v8h3l5 4Z" />
        <path d="M15 8a6 6 0 0 1 0 8M18 5a10 10 0 0 1 0 14" />
      </>
    ),
    muted: (
      <>
        <path d="M11 4 6 8H3v8h3l5 4Z" />
        <path d="m16 9 6 6m0-6-6 6" />
      </>
    ),
    pause: <path d="M8 5v14M16 5v14" />,
    log: (
      <>
        <path d="M4 4h16v16H4Z" />
        <path d="M8 9h8M8 13h8M8 17h4" />
      </>
    ),
    bookmark: <path d="M6 3h12v18l-6-4-6 4Z" />,
    user: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21v-2a8 8 0 0 1 16 0v2" />
      </>
    ),
    settings: (
      <>
        <path
          d="m9.5 3 .6-1h3.8l.6 1 .5 2 1.8 1 2-.5 1.1.1 1.9 3.3-.5 1-1.5 1.5v2.1l1.5 1.5.5 1-1.9 3.3-1.1.1-2-.5-1.8 1-.5 2-.6 1h-3.8l-.6-1-.5-2-1.8-1-2 .5-1.1-.1L.3 16l.5-1 1.5-1.5v-2.1L.8 9.9l-.5-1 1.9-3.3 1.1-.1 2 .5 1.8-1Z"
          transform="translate(1 0) scale(.92)"
        />
        <circle cx="12" cy="12" r="3.2" />
      </>
    ),
    close: <path d="m6 6 12 12M18 6 6 18" />,
    history: (
      <>
        <path d="M3 11a9 9 0 1 1 1.8 6M3 4v7h7" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    chevron: <path d="m9 5 7 7-7 7" />,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    play: <path d="m8 4 12 8-12 8Z" />,
    skip: (
      <>
        <path d="m4 5 10 7-10 7Z" />
        <path d="M19 5v14" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
