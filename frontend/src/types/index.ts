export type Intent = 'order_query' | 'knowledge' | 'transfer_human' | 'chitchat'
export interface ChatPayload {
  request_id?: string
  message: string
  session_id?: string
}
export interface ToolTrace {
  summary?: string
  sources?: { title: string; url: string }[]
  step: number
  tool: string
  status: string
  elapsed_ms?: number
  result_chars?: number
}
export interface ProductImage {
  model: string
  url: string
  alt: string
  source_url: string
}
export interface ChatResult {
  documents?: SavedDocument[]
  run_id?: string
  reply: string
  session_id: string
  intents: Intent[]
  memory_hits: string[]
  tool_trace?: ToolTrace[]
  stop_reason?: string
  degraded?: boolean
  retryable?: boolean
  product_images?: ProductImage[]
}
export type StreamEvent =
  | { type: 'task'; run_id: string; session_id: string; request_id: string }
  | { type: 'token'; content: string }
  | ({ type: 'done' } & ChatResult)
  | {
      type: 'error'
      content: string
      session_id: string
      run_id?: string
      retryable?: boolean
    }
export interface Message {
  documents?: SavedDocument[]
  id: string
  role: 'user' | 'assistant'
  content: string
  time: string
  state?: 'pending' | 'done' | 'error' | 'stopped'
  intents?: Intent[]
  memoryHits?: string[]
  toolTrace?: ToolTrace[]
  stopReason?: string
  productImages?: ProductImage[]
  runId?: string
  requestId?: string
  retryable?: boolean
}
export interface Conversation {
  id: string
  sessionId: string
  userId: string
  title: string
  updatedAt: string
  messages: Message[]
}
export interface SavedDocument {
  id: string
  title: string
  format: 'pdf'
  download_url: string
  created: number
}
export interface ServiceStatus {
  status: 'ok' | 'degraded'
  services: Record<'redis' | 'mysql' | 'milvus', 'online' | 'offline'>
}
export interface KnowledgeCollection {
  name: string
  label: string
  chunks: number
}
export interface UploadResult {
  inserted?: number
  reused?: boolean
  document_id?: string
  message: string
  chunks: number
  filename: string
  collection: string
}
export const intentLabels: Record<Intent, string> = {
  order_query: '订单查询',
  knowledge: '知识问答',
  transfer_human: '人工转接',
  chitchat: '日常沟通',
}
