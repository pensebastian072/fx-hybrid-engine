import { NavItem } from '@/types';

/**
 * Navigation configuration with RBAC support
 *
 * This configuration is used for both the sidebar navigation and Cmd+K bar.
 *
 * RBAC Access Control:
 * Each navigation item can have an `access` property that controls visibility
 * based on permissions, plans, features, roles, and organization context.
 *
 * Examples:
 *
 * 1. Require organization:
 *    access: { requireOrg: true }
 *
 * 2. Require specific permission:
 *    access: { requireOrg: true, permission: 'org:teams:manage' }
 *
 * 3. Require specific plan:
 *    access: { plan: 'pro' }
 *
 * 4. Require specific feature:
 *    access: { feature: 'premium_access' }
 *
 * 5. Require specific role:
 *    access: { role: 'admin' }
 *
 * 6. Multiple conditions (all must be true):
 *    access: { requireOrg: true, permission: 'org:teams:manage', plan: 'pro' }
 *
 * Note: The `visible` function is deprecated but still supported for backward compatibility.
 * Use the `access` property for new items.
 */
export const navItems: NavItem[] = [
  {
    title: 'Dashboard',
    url: '/dashboard/algo',
    icon: 'dashboard',
    isActive: true,
    shortcut: ['d', 'd'],
    items: []
  },
  {
    title: 'Regime',
    url: '/dashboard/regime',
    icon: 'chart',
    isActive: false,
    shortcut: ['r', 'r'],
    items: []
  },
  {
    title: 'Pairs',
    url: '/dashboard/pairs',
    icon: 'gitFork',
    isActive: false,
    shortcut: ['p', 'p'],
    items: []
  },
  {
    title: 'Walk-Forward',
    url: '/dashboard/walkforward',
    icon: 'barChart',
    isActive: false,
    shortcut: ['w', 'w'],
    items: []
  },
  {
    title: 'Risk',
    url: '/dashboard/risk',
    icon: 'shield',
    isActive: false,
    shortcut: ['k', 'k'],
    items: []
  },
  {
    title: 'Trades',
    url: '/dashboard/trades',
    icon: 'post',
    isActive: false,
    shortcut: ['t', 'r'],
    items: []
  },
  {
    title: 'Paper',
    url: '/dashboard/paper',
    icon: 'shield',
    isActive: false,
    shortcut: ['p', 'o'],
    items: []
  },
  {
    title: 'Settings',
    url: '/dashboard/settings',
    icon: 'settings',
    isActive: false,
    shortcut: ['s', 's'],
    items: []
  }
];
