import React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Building2, Database, FileText, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'

const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation()
  const isWorkspacePage = location.pathname.startsWith('/outline/') || location.pathname.startsWith('/workbench/')
  const navItems = [
    { path: '/new', label: '首页', icon: Plus },
    { path: '/knowledge', label: '知识库', icon: Database },
    { path: '/companies', label: '公司管理', icon: Building2 },
    { path: '/projects', label: '项目列表', icon: FileText },
  ]

  return (
    <div className="flex h-screen bg-neutral-100">
      <div className={cn('bg-white border-r border-neutral-200 flex flex-col', isWorkspacePage ? 'w-36' : 'w-60')}>
        <div className={cn('border-b border-neutral-200', isWorkspacePage ? 'p-3' : 'p-6')}>
          <h1 className={cn('font-semibold text-neutral-900', isWorkspacePage ? 'text-base' : 'text-xl')}>投标业务智能体</h1>
          <p className={cn('text-neutral-500 mt-1', isWorkspacePage ? 'text-xs' : 'text-sm')}>投标专属工具</p>
        </div>
        <nav className={cn('flex-1 space-y-1', isWorkspacePage ? 'p-3' : 'p-4')}>
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = location.pathname === item.path
            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  'flex items-center rounded-md text-sm font-medium transition-colors',
                  isWorkspacePage ? 'space-x-2 px-2 py-2' : 'space-x-3 px-3 py-2',
                  isActive ? 'bg-blue-50 text-blue-700' : 'text-neutral-700 hover:bg-neutral-100',
                )}
              >
                <Icon className={cn('shrink-0', isWorkspacePage ? 'w-4 h-4' : 'w-5 h-5')} />
                <span>{item.label}</span>
              </Link>
            )
          })}
        </nav>
        <div className={cn('border-t border-neutral-200', isWorkspacePage ? 'p-3' : 'p-4')}>
          <div className="text-xs text-neutral-500">
            <p>BusinessAgent</p>
            <p className="mt-1">版本 v1.0.0</p>
          </div>
        </div>
      </div>
      <div className={cn('flex-1', isWorkspacePage ? 'overflow-hidden' : 'overflow-auto')}>
        <main className={cn(isWorkspacePage ? 'h-full min-h-0 p-2 max-w-none' : 'p-6 max-w-7xl mx-auto')}>{children}</main>
      </div>
    </div>
  )
}

export default Layout
