// Deliberate violation fixture: no-unknown-property must fire OUTSIDE viz3d.
export function Bad() {
  return <div intensity={0.5} />
}
