import type { ReactNode } from "react";

type IconName =
  | "lock"
  | "shield"
  | "badge"
  | "memory"
  | "speed"
  | "hash"
  | "mail"
  | "key"
  | "eye"
  | "eyeOff"
  | "building"
  | "tag"
  | "info"
  | "warning"
  | "close"
  | "check"
  | "folder"
  | "person"
  | "users"
  | "globe"
  | "inbox"
  | "plus"
  | "copy"
  | "grid"
  | "filter"
  | "file"
  | "share"
  | "menu"
  | "search"
  | "chevron";

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg aria-hidden="true" fill="none" height={size} stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" width={size}>
      {paths[name]}
    </svg>
  );
}

const paths: Record<IconName, ReactNode> = {
  lock: (
    <>
      <rect height="11" rx="2" width="14" x="5" y="11" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </>
  ),
  shield: <path d="M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6l8-3z" />,
  badge: (
    <>
      <path d="M12 3l2.2 1.6 2.6-.4 1.2 2.4 2.4 1.2-.4 2.6L21 12l-1 2.6.4 2.6-2.4 1.2-1.2 2.4-2.6-.4L12 21l-2.2-1.6-2.6.4-1.2-2.4-2.4-1.2.4-2.6L3 12l1-2.6-.4-2.6 2.4-1.2 1.2-2.4 2.6.4L12 3z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  memory: (
    <>
      <rect height="10" rx="1" width="10" x="7" y="7" />
      <path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" />
    </>
  ),
  speed: (
    <>
      <path d="M12 13l4-4" />
      <path d="M5 19a9 9 0 1 1 14 0" />
    </>
  ),
  hash: (
    <>
      <path d="M7 8h10M7 16h10M9 4l-2 16M17 4l-2 16" />
    </>
  ),
  mail: (
    <>
      <rect height="14" rx="2" width="18" x="3" y="5" />
      <path d="M3 7l9 7 9-7" />
    </>
  ),
  key: (
    <>
      <circle cx="8" cy="15" r="4" />
      <path d="M11.5 12.5L21 3M16 8l3 3M18 6l2 2" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  eyeOff: (
    <>
      <path d="M3 3l18 18" />
      <path d="M10.6 6.2A10.7 10.7 0 0 1 12 6c6.5 0 10 6 10 6a17 17 0 0 1-3.2 3.8" />
      <path d="M6.1 6.1C3.6 7.8 2 12 2 12s3.5 6 10 6a10 10 0 0 0 4-.8" />
    </>
  ),
  building: (
    <>
      <rect height="18" rx="1" width="14" x="5" y="3" />
      <path d="M9 21v-4h6v4M9 7h.01M12 7h.01M15 7h.01M9 11h.01M12 11h.01M15 11h.01M9 15h.01M12 15h.01M15 15h.01" />
    </>
  ),
  tag: (
    <>
      <path d="M20 13l-7 7-9-9V4h7l9 9z" />
      <circle cx="7.5" cy="7.5" r="1" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6M12 8h.01" />
    </>
  ),
  warning: (
    <>
      <path d="M12 3l9 16H3L12 3z" />
      <path d="M12 10v4M12 17h.01" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6L6 18" />,
  check: <path d="M5 12l5 5L20 7" />,
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />,
  person: (
    <>
      <circle cx="12" cy="8" r="3" />
      <path d="M5 19a7 7 0 0 1 14 0" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3 19a6 6 0 0 1 12 0" />
      <path d="M16 11a3 3 0 1 0 0-6" />
      <path d="M17 19a6 6 0 0 0-3-5.2" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </>
  ),
  inbox: (
    <>
      <path d="M3 13l2-8h14l2 8" />
      <path d="M3 13h5l1 3h6l1-3h5v6H3v-6z" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  copy: (
    <>
      <rect height="12" rx="1" width="10" x="8" y="8" />
      <path d="M6 16H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" />
    </>
  ),
  grid: (
    <>
      <rect height="7" rx="1" width="7" x="3" y="3" />
      <rect height="7" rx="1" width="7" x="14" y="3" />
      <rect height="7" rx="1" width="7" x="3" y="14" />
      <rect height="7" rx="1" width="7" x="14" y="14" />
    </>
  ),
  filter: <path d="M4 5h16l-6 7v6l-4 2v-8L4 5z" />,
  file: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" />
      <path d="M14 3v5h5" />
    </>
  ),
  share: (
    <>
      <circle cx="6" cy="12" r="2" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="16" cy="17" r="2" />
      <path d="M8 11l6-3M8 13l6 3" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="M16 16l4 4" />
    </>
  ),
  chevron: <path d="M9 6l6 6-6 6" />,
};
