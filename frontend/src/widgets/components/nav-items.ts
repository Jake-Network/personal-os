import { Briefcase, CalendarDays, FileText, House, type LucideIcon, MessagesSquare, NotebookPen, Settings, Wallet } from 'lucide-react';

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  /** Short label for the mobile tab bar. */
  short?: string;
}

export const NAV_ITEMS: NavItem[] = [
  { href: '/', label: '홈', icon: House, end: true },
  { href: '/advisor', label: '상담', icon: MessagesSquare },
  { href: '/plan', label: '할 일·일정', short: '일정', icon: CalendarDays },
  { href: '/finance', label: '자산', icon: Wallet },
  { href: '/career', label: '커리어', icon: Briefcase },
  { href: '/reflect', label: '기록·회고', short: '회고', icon: NotebookPen },
  { href: '/documents', label: '문서함', short: '문서', icon: FileText },
];

export const SETTINGS_ITEM: NavItem = { href: '/settings', label: '설정', icon: Settings };

/** Shown in the mobile tab bar; everything else is under 더보기. */
export const MOBILE_TABS = ['/', '/advisor', '/plan', '/finance'];
