import { AssignWorkComposer } from './AssignWorkComposer'
import { SessionCard } from './SessionCard'
import { OnboardingCard } from './OnboardingCard'
import { onboardingCards, sessions } from '../../mocks/home'
import styles from './HomePage.module.css'

export function HomePage() {
  const hero = onboardingCards.filter((c) => c.size === 'hero')
  const small = onboardingCards.filter((c) => c.size === 'small')
  return (
    <div className={styles.page}>
      <AssignWorkComposer />
      <div className={styles.grid3}>
        {sessions.map((s) => <SessionCard key={s.id} session={s} />)}
      </div>
      <div className={styles.grid3}>
        {hero.map((c) => <OnboardingCard key={c.id} card={c} />)}
      </div>
      <div className={styles.grid3}>
        {small.map((c) => <OnboardingCard key={c.id} card={c} />)}
      </div>
    </div>
  )
}
