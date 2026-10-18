export type Intent = 'order_query' | 'knowledge' | 'transfer_human' | 'chitchat'
export interface ChatPayload {
  user_id: string
  message: string
  session_id?: string
}
export interface ChatResult {
  reply: string
  session_id: string
  intents: Intent[]
  memory_hits: string[]
  degraded?: boolean
}
export type StreamEvent =
  | { type: 'token'; content: string }
  | ({ type: 'done' } & ChatResult)
  | { type: 'error'; content: string; session_id: string }
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  time: string
  state?: 'pending' | 'done' | 'error' | 'stopped'
  intents?: Intent[]
  memoryHits?: string[]
}
export interface Conversation {
  id: string
  sessionId: string
  userId: string
  title: string
  updatedAt: string
  messages: Message[]
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
