export type Verdict = 'Supported' | 'Contradicted' | 'Mixed' | 'Insufficient'
export type Stance = 'supports' | 'refutes' | 'neutral'
export type InputKind = 'text' | 'url' | 'image' | 'document' | 'audio' | 'video'

export interface Evidence {
  id: string
  title: string
  url: string
  publisher: string
  domain: string
  tier: string
  date?: string
  snippet?: string
  passage?: string
  via: string
  stance: Stance
  relevance: number
  quote?: string
}

export interface ClaimResult {
  text: string
  central: boolean
  verdict: Verdict
  confidence: number
  score: { support: number; refute: number; n_support: number; n_refute: number; balance: number }
  explanation: string
  discrepancies: string[]
  entities: Record<string, string[]>
  keywords: string[]
  queries: string[]
  evidence: Evidence[]
}

export interface Report {
  id: string
  share_id?: string | null
  created_at: string
  verdict: Verdict
  confidence: number
  summary: string
  explanation: string
  context_gaps: string[]
  bias_indicators: string[]
  missing_information: string[]
  claims: ClaimResult[]
  input: { kind: InputKind; text: string; label: string; meta: Record<string, string>; notes: string[] }
  engines: Record<string, string>
  degraded: string | boolean
  elapsed: number
}

export interface HistoryRow {
  verification_id: string
  input_type: InputKind
  input_content: string
  status: 'completed' | 'failed' | 'processing'
  verdict: Verdict | null
  confidence: number | null
  created_at: string
}

export interface StepEvent {
  type: 'step'
  step: 'read' | 'claims' | 'evidence' | 'analysis' | 'verdict'
  state: 'active' | 'done'
  detail: string
  claims?: string[]
  notes?: string[]
}

export interface User {
  user_id: number
  name: string
  email: string
}
