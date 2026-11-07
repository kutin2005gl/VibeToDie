import { ArrowRight } from '../../components/icons'
import type { MockOnboardingCard } from '../../mocks/home'
import styles from './OnboardingCard.module.css'

export function OnboardingCard({ card }: { card: MockOnboardingCard }) {
  return (
    <article className={`${styles.card} ${styles[card.tone]} ${card.size === 'hero' ? styles.hero : ''}`}>
      <h3>{card.title}</h3>
      <p>{card.description}</p>
      {card.action && (
        <a href="#card" onClick={(e) => e.preventDefault()}>
          {card.action} <ArrowRight size={12} />
        </a>
      )}
    </article>
  )
}
