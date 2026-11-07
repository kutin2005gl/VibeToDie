import type * as React from 'react'
import Link from 'next/link'
import { cn } from '@/lib/utils'

// Breadcrumb của shadcn (theo fiurozz-fe), link đi qua next/link. Mũi tên vẽ tay theo bộ icon BOA
// (components/icons.tsx): nét 2, đầu bo tròn, đường hơi cong như nét bút.
// Màu và gạch chân của link cần `!`: luật `a` trong global.css không thuộc layer nên thắng utilities của Tailwind.

function Arrow({ d, className }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" className={className}>
      <path d={d} />
    </svg>
  )
}

function Breadcrumb({ className, ...props }: React.ComponentProps<'nav'>) {
  return <nav aria-label="Đường dẫn" data-slot="breadcrumb" className={cn('flex items-center gap-2.5', className)} {...props} />
}

function BreadcrumbList({ className, ...props }: React.ComponentProps<'ol'>) {
  return (
    <ol
      data-slot="breadcrumb-list"
      className={cn(
        'm-0 flex min-w-0 list-none flex-wrap items-center gap-1 p-0 text-(length:--fs-caption) break-words text-(--text-secondary) sm:gap-1.5',
        className,
      )}
      {...props}
    />
  )
}

function BreadcrumbItem({ className, ...props }: React.ComponentProps<'li'>) {
  return <li data-slot="breadcrumb-item" className={cn('inline-flex min-w-0 items-center gap-1.5', className)} {...props} />
}

function BreadcrumbLink({ className, ...props }: React.ComponentProps<typeof Link>) {
  return (
    <Link
      data-slot="breadcrumb-link"
      className={cn('rounded-sm text-(--text-secondary)! no-underline! transition-colors hover:text-foreground! focus-visible:shadow-[0_0_0_3px_var(--focus-ring)] focus-visible:outline-none', className)}
      {...props}
    />
  )
}

function BreadcrumbPage({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      data-slot="breadcrumb-page"
      role="link"
      aria-disabled="true"
      aria-current="page"
      className={cn('truncate font-medium text-foreground', className)}
      {...props}
    />
  )
}

function BreadcrumbSeparator({ children, className, ...props }: React.ComponentProps<'li'>) {
  return (
    <li
      data-slot="breadcrumb-separator"
      role="presentation"
      aria-hidden="true"
      className={cn('inline-flex text-muted-foreground [&>svg]:size-3.5', className)}
      {...props}
    >
      {children ?? <Arrow d="M9.6 6.6c2 1.7 3.8 3.5 5.3 5.4-1.6 1.9-3.4 3.7-5.4 5.4" />}
    </li>
  )
}

/** Nút lùi một cấp, đặt đầu đường dẫn: vùng bấm 32px, luôn hiện kể cả trên màn hẹp khi các mắt xích giữa bị ẩn. */
function BreadcrumbBack({ label, className, ...props }: React.ComponentProps<typeof Link> & { label: string }) {
  return (
    <Link
      data-slot="breadcrumb-back"
      aria-label={`Quay lại ${label}`}
      title={`Quay lại ${label}`}
      className={cn(
        'group inline-flex size-8 shrink-0 items-center justify-center rounded-md text-(--text-secondary)! no-underline!',
        'transition-colors duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]',
        'hover:bg-(--bg-subtle) hover:text-foreground!',
        'focus-visible:shadow-[0_0_0_3px_var(--focus-ring)] focus-visible:outline-none',
        className,
      )}
      {...props}
    >
      <Arrow
        d="M19 12.7c-3.9-.9-8.4-1-13.3-.5M10.4 7.3c-1.8 1.7-3.3 3.2-4.7 4.9 1.5 1.5 3.1 2.9 4.9 4.4"
        className="size-4 transition-transform duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-x-0.5 motion-reduce:transition-none motion-reduce:group-hover:translate-x-0"
      />
    </Link>
  )
}

export { Breadcrumb, BreadcrumbList, BreadcrumbItem, BreadcrumbLink, BreadcrumbPage, BreadcrumbSeparator, BreadcrumbBack }
