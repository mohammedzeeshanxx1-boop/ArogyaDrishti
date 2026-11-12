import type { SVGProps } from "react";

// Small inline icon set (24×24, stroke), so no icon dependency is needed.
const base = (d: React.ReactNode) => (props: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"
    aria-hidden="true" width={20} height={20} {...props}>{d}</svg>
);

export const IconGrid = base(<><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>);
export const IconUsers = base(<><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5" /><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.8c1.9.7 3.1 2.4 3.5 5.2" /></>);
export const IconBell = base(<><path d="M6 9a6 6 0 1 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9Z" /><path d="M10 20a2 2 0 0 0 4 0" /></>);
export const IconPulse = base(<path d="M3 12h4l2.5-6 4 12 2.5-6H21" />);
export const IconHeart = base(<path d="M12 20s-7.5-4.4-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10C19.5 15.6 12 20 12 20Z" />);
export const IconDrop = base(<path d="M12 3.5s6 6.4 6 10.8a6 6 0 0 1-12 0C6 9.9 12 3.5 12 3.5Z" />);
export const IconWind = base(<><path d="M3 9h11a3 3 0 1 0-3-3" /><path d="M3 15h15a3 3 0 1 1-3 3" /><path d="M3 12h7" /></>);
export const IconThermo = base(<><path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0Z" /><path d="M12 9v7" /></>);
export const IconChart = base(<><path d="M4 20V4" /><path d="M4 20h16" /><path d="m7 15 4-4 3 3 5-6" /></>);
export const IconFile = base(<><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></>);
export const IconUser = base(<><circle cx="12" cy="8" r="4" /><path d="M4 21c1-4.5 4.3-7 8-7s7 2.5 8 7" /></>);
export const IconLogout = base(<><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" /><path d="m10 16-4-4 4-4M6 12h10" /></>);
export const IconMenu = base(<path d="M4 6h16M4 12h16M4 18h16" />);
export const IconX = base(<path d="M6 6l12 12M18 6 6 18" />);
export const IconSearch = base(<><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>);
export const IconUp = base(<path d="m6 15 6-6 6 6" />);
export const IconDown = base(<path d="m6 9 6 6 6-6" />);
export const IconFlat = base(<path d="M5 12h14" />);
export const IconShield = base(<><path d="M12 3 4.5 6v6c0 4.4 3.2 7.8 7.5 9 4.3-1.2 7.5-4.6 7.5-9V6Z" /><path d="m9 12 2 2 4-4" /></>);
export const IconClock = base(<><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>);
export const IconFlask = base(<><path d="M9 3h6M10 3v6L4.8 18a2 2 0 0 0 1.7 3h11a2 2 0 0 0 1.7-3L14 9V3" /><path d="M7.5 14h9" /></>);
export const IconChevron = base(<path d="m9 6 6 6-6 6" />);
export const IconEye = base(<><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" /><circle cx="12" cy="12" r="2.8" /></>);
