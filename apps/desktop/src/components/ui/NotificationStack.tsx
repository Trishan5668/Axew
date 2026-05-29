import { AnimatePresence, motion } from 'framer-motion'
import { X } from 'lucide-react'
import { cn } from '../../lib/cn'
import { useUIStore } from '../../stores/uiStore'

export function NotificationStack() {
  const { notifications, removeNotification } = useUIStore()

  return (
    <div className="pointer-events-none fixed bottom-12 right-4 z-[100] flex flex-col gap-2">
      <AnimatePresence>
        {notifications.map((n) => (
          <motion.div
            key={n.id}
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 40 }}
            className={cn(
              'pointer-events-auto flex max-w-xs items-start gap-2 rounded-lg border px-3 py-2 shadow-panel',
              n.type === 'success' && 'border-axew-success/30 bg-axew-panel',
              n.type === 'error' && 'border-axew-error/30 bg-axew-panel',
              n.type === 'warning' && 'border-axew-warning/30 bg-axew-panel',
              n.type === 'info' && 'border-axew-border bg-axew-panel',
            )}
          >
            <span className="flex-1 text-xs text-axew-text">{n.message}</span>
            <button
              type="button"
              className="text-axew-textDim hover:text-axew-text"
              onClick={() => removeNotification(n.id)}
            >
              <X size={12} />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
