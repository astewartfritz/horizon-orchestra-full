// Orchestra — SVG icons (inline, stroke-based, 20px default)
// All icons use currentColor. size parameter adjusts width/height.

const svgOpen = (size = 18, extra = '') =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" ${extra}>`;

const icons = {
  // Orchestra logo: elegant mark — curve + dot + circuit node
  logo: (size = 28) => `
    <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 32 32" fill="none" aria-label="Orchestra">
      <defs>
        <linearGradient id="og1" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stop-color="#8282F7"/>
          <stop offset="1" stop-color="#00C9B8"/>
        </linearGradient>
      </defs>
      <path d="M6 23C6 14 11 8 18 8c4 0 7 2 8 5" stroke="url(#og1)" stroke-width="2" stroke-linecap="round"/>
      <circle cx="18" cy="22" r="3.2" fill="url(#og1)"/>
      <circle cx="26" cy="13" r="1.8" fill="#00C9B8"/>
      <path d="M18 19V12" stroke="url(#og1)" stroke-width="1.8" stroke-linecap="round"/>
    </svg>`,

  miles: (size = 20) => `
    <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none">
      <path d="M12 3l2.3 5.2L20 9l-4 3.9.9 5.6L12 15.9 7.1 18.5 8 12.9 4 9l5.7-.8L12 3z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="12" cy="11" r="2" fill="currentColor"/>
    </svg>`,

  home: (s=18)=>`${svgOpen(s)}<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h14V10"/></svg>`,
  chat: (s=18)=>`${svgOpen(s)}<path d="M4 5h16v11H8l-4 4V5z"/></svg>`,
  agents: (s=18)=>`${svgOpen(s)}<circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.5 3-6 7-6s7 2.5 7 6"/></svg>`,
  verticals: (s=18)=>`${svgOpen(s)}<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>`,
  coord: (s=18)=>`${svgOpen(s)}<circle cx="12" cy="12" r="2"/><circle cx="5" cy="5" r="1.6"/><circle cx="19" cy="5" r="1.6"/><circle cx="5" cy="19" r="1.6"/><circle cx="19" cy="19" r="1.6"/><path d="M6.3 6.4l4.4 4.4M17.7 6.4l-4.4 4.4M6.3 17.6l4.4-4.4M17.7 17.6l-4.4-4.4"/></svg>`,
  tools: (s=18)=>`${svgOpen(s)}<path d="M14 3.5a4 4 0 0 1 5 5l-8 8-5 1 1-5 7-9z"/><path d="M13 6l5 5"/></svg>`,
  tasks: (s=18)=>`${svgOpen(s)}<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l2 2 4-4"/><path d="M7 15h8"/></svg>`,
  settings: (s=18)=>`${svgOpen(s)}<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>`,
  search: (s=16)=>`${svgOpen(s)}<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>`,
  bell: (s=18)=>`${svgOpen(s)}<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/></svg>`,
  send: (s=16)=>`${svgOpen(s)}<path d="M4 12 20 4l-8 16-2-7z"/></svg>`,
  plus: (s=16)=>`${svgOpen(s)}<path d="M12 5v14M5 12h14"/></svg>`,
  paperclip: (s=16)=>`${svgOpen(s)}<path d="M21 11l-8.7 8.7a5 5 0 1 1-7-7L14 4a3.5 3.5 0 1 1 5 5l-9.2 9.2a2 2 0 1 1-2.8-2.8L14 9"/></svg>`,
  chevronDown: (s=14)=>`${svgOpen(s)}<path d="m6 9 6 6 6-6"/></svg>`,
  chevronRight: (s=14)=>`${svgOpen(s)}<path d="m9 6 6 6-6 6"/></svg>`,
  chevronLeft: (s=14)=>`${svgOpen(s)}<path d="m15 6-6 6 6 6"/></svg>`,
  check: (s=12)=>`${svgOpen(s, 'stroke-width="2.5"')}<path d="m5 12 4 4 10-10"/></svg>`,
  x: (s=14)=>`${svgOpen(s)}<path d="M18 6 6 18M6 6l12 12"/></svg>`,
  menu: (s=18)=>`${svgOpen(s)}<path d="M3 6h18M3 12h18M3 18h18"/></svg>`,
  collapse: (s=14)=>`${svgOpen(s)}<path d="M9 4v16M4 9l-2 3 2 3M20 9l2 3-2 3"/></svg>`,
  copy: (s=14)=>`${svgOpen(s)}<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>`,
  globe: (s=14)=>`${svgOpen(s)}<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18"/></svg>`,
  terminal: (s=14)=>`${svgOpen(s)}<path d="m5 8 4 4-4 4M13 16h6"/><rect x="2" y="4" width="20" height="16" rx="2"/></svg>`,
  file: (s=14)=>`${svgOpen(s)}<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>`,
  folder: (s=14)=>`${svgOpen(s)}<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>`,
  sparkles: (s=14)=>`${svgOpen(s)}<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/></svg>`,
  trend: (s=12)=>`${svgOpen(s, 'stroke-width="2"')}<path d="m3 17 6-6 4 4 8-8"/><path d="M14 7h7v7"/></svg>`,
  trendDown: (s=12)=>`${svgOpen(s, 'stroke-width="2"')}<path d="m3 7 6 6 4-4 8 8"/><path d="M14 17h7v-7"/></svg>`,
  arrow: (s=14)=>`${svgOpen(s)}<path d="M5 12h14M13 6l6 6-6 6"/></svg>`,
  arrowUpRight: (s=14)=>`${svgOpen(s)}<path d="M7 17 17 7M8 7h9v9"/></svg>`,
  play: (s=14)=>`${svgOpen(s)}<path d="M6 4v16l14-8z" fill="currentColor"/></svg>`,
  heart: (s=14)=>`${svgOpen(s)}<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8z"/></svg>`,
  star: (s=14)=>`${svgOpen(s)}<path d="m12 3 2.6 5.9L21 10l-5 4.5L17.3 21 12 17.7 6.7 21 8 14.5 3 10l6.4-1.1L12 3z"/></svg>`,
  cpu: (s=14)=>`${svgOpen(s)}<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>`,
  activity: (s=14)=>`${svgOpen(s)}<path d="m3 12 4-1 3-8 4 16 3-7h4"/></svg>`,
  shield: (s=14)=>`${svgOpen(s)}<path d="M12 2 4 5v6c0 5 3.5 9 8 11 4.5-2 8-6 8-11V5l-8-3z"/><path d="m9 12 2 2 4-4"/></svg>`,
  lock: (s=14)=>`${svgOpen(s)}<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 1 1 8 0v4"/></svg>`,
  key: (s=14)=>`${svgOpen(s)}<circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 10-10M16 6l3 3M18 4l3 3"/></svg>`,
  eye: (s=14)=>`${svgOpen(s)}<path d="M2 12s4-8 10-8 10 8 10 8-4 8-10 8S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>`,
  eyeOff: (s=14)=>`${svgOpen(s)}<path d="M18 6 6 18"/><path d="M17 17a10 10 0 0 1-5 2c-6 0-10-7-10-7a15 15 0 0 1 4-4.5M8.5 8.5A3 3 0 0 0 12 15a3 3 0 0 0 3-3"/><path d="M9.8 5.2A10 10 0 0 1 12 5c6 0 10 7 10 7a15.5 15.5 0 0 1-3.3 4"/></svg>`,
  user: (s=14)=>`${svgOpen(s)}<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>`,
  logout: (s=14)=>`${svgOpen(s)}<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>`,
  github: (s=18)=>`${svgOpen(s)}<path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.9a3.4 3.4 0 0 0-.9-2.5c3-.3 6.2-1.5 6.2-6.6 0-1.3-.5-2.5-1.4-3.5.4-1.2.4-2.5 0-3.7 0 0-1.1-.3-3.7 1.4a12.6 12.6 0 0 0-6.6 0C6.9 1.4 5.8 1.8 5.8 1.8a5.2 5.2 0 0 0 0 3.7A5 5 0 0 0 4.4 9c0 5 3.1 6.2 6.1 6.6a3.4 3.4 0 0 0-.9 2.5V22"/></svg>`,
  mail: (s=18)=>`${svgOpen(s)}<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>`,
  calendar: (s=18)=>`${svgOpen(s)}<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>`,
  slack: (s=18)=>`${svgOpen(s)}<rect x="13" y="2" width="3" height="8" rx="1.5"/><rect x="14" y="14" width="8" height="3" rx="1.5"/><rect x="8" y="14" width="3" height="8" rx="1.5"/><rect x="2" y="7" width="8" height="3" rx="1.5"/></svg>`,
  notion: (s=18)=>`${svgOpen(s)}<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 8v8l8-8v8"/></svg>`,
  figma: (s=18)=>`${svgOpen(s)}<path d="M8 3h4v6H8a3 3 0 1 1 0-6zM16 3h-4v6h4a3 3 0 1 0 0-6zM8 9h4v6H8a3 3 0 1 1 0-6zM12 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM16 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/></svg>`,
  medical: (s=18)=>`${svgOpen(s)}<path d="M19 14h-5v5h-4v-5H5v-4h5V5h4v5h5v4z"/></svg>`,
  gavel: (s=18)=>`${svgOpen(s)}<path d="m14 13 3-3M11 10l3-3M8 7l9 9"/><path d="m4 20 6-6M19 20l2-2"/></svg>`,
  truck: (s=18)=>`${svgOpen(s)}<path d="M1 7h13v10H1zM14 10h5l3 3v4h-8"/><circle cx="6" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg>`,
  wallet: (s=18)=>`${svgOpen(s)}<path d="M3 7a2 2 0 0 1 2-2h14v4"/><rect x="3" y="7" width="18" height="13" rx="2"/><circle cx="17" cy="14" r="1.5" fill="currentColor"/></svg>`,
  factory: (s=18)=>`${svgOpen(s)}<path d="M4 20V9l5 3V9l5 3V9l5 3v8H4z"/><path d="M8 14v3M12 14v3M16 14v3"/></svg>`,
  shop: (s=18)=>`${svgOpen(s)}<path d="M3 9h18l-1.5 10.5A2 2 0 0 1 17.5 21h-11a2 2 0 0 1-2-1.5L3 9z"/><path d="M8 9V6a4 4 0 0 1 8 0v3"/></svg>`,
  bolt: (s=18)=>`${svgOpen(s)}<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" fill="currentColor"/></svg>`,
  building: (s=18)=>`${svgOpen(s)}<path d="M3 21V7l9-4 9 4v14"/><path d="M9 9v12M15 9v12M3 13h18"/></svg>`,
  nursing: (s=18)=>`${svgOpen(s)}<circle cx="12" cy="7" r="3"/><path d="M6 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2"/><path d="M10 10h4v3h-4z"/></svg>`,
  dna: (s=18)=>`${svgOpen(s)}<path d="M4 2c4 4 4 12 16 20M20 2C16 6 16 14 4 22"/><path d="M7 6h10M8 10h8M8 14h8M7 18h10"/></svg>`,
  flag: (s=14)=>`${svgOpen(s)}<path d="M4 22V4M4 4h13l-2 4 2 4H4"/></svg>`,
  clock: (s=12)=>`${svgOpen(s)}<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>`,
  info: (s=14)=>`${svgOpen(s)}<circle cx="12" cy="12" r="9"/><path d="M12 8v0M12 11v5"/></svg>`,
  zap: (s=14)=>`${svgOpen(s)}<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/></svg>`,
  more: (s=14)=>`${svgOpen(s)}<circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></svg>`,
  refresh: (s=14)=>`${svgOpen(s)}<path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5"/></svg>`,
  thumbUp: (s=14)=>`${svgOpen(s)}<path d="M7 10v12M15 5.9 14 10h6a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 18.6 21H7V10l5-9a2 2 0 0 1 2 2v3z"/></svg>`,
  thumbDown: (s=14)=>`${svgOpen(s)}<path d="M17 14V2M9 18.1 10 14H4a2 2 0 0 1-2-2.3l1.4-7A2 2 0 0 1 5.4 3H17v11l-5 9a2 2 0 0 1-2-2v-3z"/></svg>`,
  trash: (s=14)=>`${svgOpen(s)}<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>`,
  command: (s=14)=>`${svgOpen(s)}<path d="M9 6a3 3 0 1 1 3 3h0M9 9a3 3 0 1 1-3 3h6a3 3 0 1 1-3 3v-6M15 9v6"/></svg>`,
  beaker: (s=14)=>`${svgOpen(s)}<path d="M9 3h6M10 3v8L4 21h16L14 11V3"/></svg>`,
  graph: (s=14)=>`${svgOpen(s)}<path d="M3 3v18h18M7 15l4-4 3 3 5-6"/></svg>`,
  users: (s=14)=>`${svgOpen(s)}<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c0-3 3-5 6-5s6 2 6 5M16 14c3 0 5 2 5 5"/></svg>`,
};

// Global exposure for non-module scripts
window.icons = icons;
