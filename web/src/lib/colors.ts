// State colors matching vis/observatory/constants.py
export const STATE_COLORS = {
  VOID: 0x0a0a0f,
  STRUCTURAL: 0x3b82f6,  // Blue
  COMPUTE: 0x10b981,     // Green
  ENERGY: 0xf59e0b,      // Amber
  SENSOR: 0xa855f7,      // Purple
} as const

export const STATE_OPACITY = {
  STRUCTURAL: 0.25,  // Translucent shell
  COMPUTE: 0.95,     // Bright ganglia
  ENERGY: 0.70,      // Warm glow
  SENSOR: 0.50,      // Semi-transparent
} as const

export function stateColor(state: number): number {
  switch (state) {
    case 1: return STATE_COLORS.STRUCTURAL
    case 2: return STATE_COLORS.COMPUTE
    case 3: return STATE_COLORS.ENERGY
    case 4: return STATE_COLORS.SENSOR
    default: return STATE_COLORS.VOID
  }
}

export function stateOpacity(state: number): number {
  switch (state) {
    case 1: return STATE_OPACITY.STRUCTURAL
    case 2: return STATE_OPACITY.COMPUTE
    case 3: return STATE_OPACITY.ENERGY
    case 4: return STATE_OPACITY.SENSOR
    default: return 0.0
  }
}

export const STATE_NAMES = ['VOID', 'STRUCTURAL', 'COMPUTE', 'ENERGY', 'SENSOR']
