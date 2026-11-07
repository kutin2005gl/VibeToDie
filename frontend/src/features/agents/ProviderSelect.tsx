'use client'

import { MotionConfig } from 'motion/react'
import { Check, ChevronDown } from '../../components/icons'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuHighlight,
  DropdownMenuHighlightItem,
  DropdownMenuItemIndicator,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '../../components/animate-ui/primitives/radix/dropdown-menu'
import styles from './ProviderSelect.module.css'

export function ProviderSelect({ value, options, onChange, disabled }: {
  value: string
  options: string[]
  onChange: (value: string) => void
  disabled: boolean
}) {
  return (
    <MotionConfig reducedMotion="user">
      <DropdownMenu>
        <DropdownMenuTrigger className={styles.trigger} disabled={disabled} aria-label="Provider của hệ thống" aria-busy={disabled}>
          <span>{value}</span>
          <ChevronDown size={14} aria-hidden="true" />
        </DropdownMenuTrigger>
        <DropdownMenuContent className={styles.content} align="end" sideOffset={6} collisionPadding={8}>
          <DropdownMenuRadioGroup value={value} onValueChange={onChange} aria-label="Provider của hệ thống">
            <DropdownMenuHighlight className={styles.highlight}>
              {options.map((option) => (
                <DropdownMenuHighlightItem key={option} value={option}>
                  <DropdownMenuRadioItem value={option} data-value={option} className={styles.item}>
                    <span className={styles.optionText}>{option}</span>
                    <DropdownMenuItemIndicator className={styles.indicator}>
                      <Check size={15} aria-hidden="true" />
                    </DropdownMenuItemIndicator>
                  </DropdownMenuRadioItem>
                </DropdownMenuHighlightItem>
              ))}
            </DropdownMenuHighlight>
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </MotionConfig>
  )
}
