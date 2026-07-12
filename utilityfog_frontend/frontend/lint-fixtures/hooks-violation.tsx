// Deliberate violation fixture: rules-of-hooks must fire here.
import { useState } from 'react'
export function Broken({ flag }: { flag: boolean }) {
  if (flag) {
    const [x] = useState(0)
    return <span>{x}</span>
  }
  return null
}
