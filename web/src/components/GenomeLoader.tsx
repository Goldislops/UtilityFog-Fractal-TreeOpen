import React, { useCallback, useRef } from 'react'

interface Props {
  onLoad: (json: string) => void
}

const btnStyle: React.CSSProperties = {
  background: 'rgba(99, 102, 241, 0.15)',
  border: '1px solid rgba(99, 102, 241, 0.3)',
  color: '#a5b4fc',
  padding: '6px 12px',
  borderRadius: 6,
  cursor: 'pointer',
  fontSize: 12,
  fontFamily: 'monospace',
  transition: 'all 0.2s',
}

export default function GenomeLoader({ onLoad }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFile = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        onLoad(reader.result)
      }
    }
    reader.readAsText(file)
  }, [onLoad])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') onLoad(reader.result)
    }
    reader.readAsText(file)
  }, [onLoad])

  return (
    <div
      onDrop={handleDrop}
      onDragOver={(e) => e.preventDefault()}
    >
      <input
        ref={fileRef}
        type="file"
        accept=".json,.genome.json"
        onChange={handleFile}
        style={{ display: 'none' }}
      />
      <button
        style={btnStyle}
        onClick={() => fileRef.current?.click()}
        onMouseEnter={(e) => {
          (e.target as HTMLElement).style.background = 'rgba(99, 102, 241, 0.3)'
        }}
        onMouseLeave={(e) => {
          (e.target as HTMLElement).style.background = 'rgba(99, 102, 241, 0.15)'
        }}
      >
        Load Genome
      </button>
    </div>
  )
}
