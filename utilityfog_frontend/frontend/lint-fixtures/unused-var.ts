// Ownership fixture: an unused variable that ESLint must IGNORE (tsc owns
// unused checks). The rule-liveness script asserts silence.
const deliberatelyUnused = 1
export {}
