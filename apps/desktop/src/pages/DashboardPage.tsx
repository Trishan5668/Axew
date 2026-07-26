/**
 * DashboardPage — wraps the AXEW main editor (MainLayout) and adds the
 * UserMenu in the top-right via a small overlay. The editor itself is
 * unchanged; this page is just the auth-protected shell.
 *
 * In local-only mode (cloud disabled), UserMenu returns null, so this
 * page renders identically to the original index.
 */

import { MainLayout } from '../components/layout/MainLayout'
import { UserMenu } from '../components/UserMenu'
import { CreditMeter } from '../components/CreditMeter'

export function DashboardPage(): JSX.Element {
  return (
    <div className="relative h-full w-full">
      <div className="pointer-events-none absolute right-3 top-1.5 z-40 flex items-center gap-2">
        <div className="pointer-events-auto"><CreditMeter /></div>
        <div className="pointer-events-auto"><UserMenu /></div>
      </div>
      <MainLayout />
    </div>
  )
}
