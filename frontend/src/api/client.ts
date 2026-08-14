export interface Conversation {
  id: string
  title: string | null
  created_at: string
}

export interface ChatMessage {
  id?: string
  content: string
  role: 'user' | 'assistant' | 'tool' | 'system'
  placement: 'start' | 'end'
  loading?: boolean
  activities?: AgentActivity[]
}

export type AgentActivityStatus = 'running' | 'completed' | 'waiting' | 'error'

export interface AgentActivity {
  id: string
  label: string
  status: AgentActivityStatus
}

export interface ConfirmationRequest {
  toolName: string
  description: string
}

export interface FormField {
  name: string
  label?: string
  type?: 'text' | 'select'
  required?: boolean
  options?: Array<string | { label: string; value: string }>
}

export interface FormRequest {
  formName: string
  title: string
  fields: FormField[]
  prefilledValues: Record<string, string>
}

export type StreamEvent =
  | { type: 'token'; content: string }
  | { type: 'tool_start'; name: string }
  | { type: 'tool_end'; name: string }
  | { type: 'confirmation_required'; confirmation: ConfirmationRequest }
  | { type: 'form_required'; form: FormRequest }
  | { type: 'done' }
  | { type: 'error'; message: string }

const apiToken = import.meta.env.VITE_API_TOKEN as string | undefined

function headers(): HeadersInit {
  return {
    Authorization: `Bearer ${apiToken || ''}`,
    'Content-Type': 'application/json',
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, headers: { ...headers(), ...init.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ message: response.statusText }))
    throw new Error(body.message || 'Request failed')
  }
  return response.json() as Promise<T>
}

export function listConversations(staffId: string): Promise<{ items: Conversation[] }> {
  return request(`/agent/api/conversations?staff_id=${encodeURIComponent(staffId)}&page=1&page_size=50`)
}

export function createConversation(staffId: string): Promise<Conversation> {
  return request('/agent/api/conversations', { method: 'POST', body: JSON.stringify({ staff_id: staffId }) })
}

export async function listMessages(conversationId: string, staffId: string): Promise<ChatMessage[]> {
  const messages = await request<Array<{ id: string; role: ChatMessage['role']; content: string }>>(
    `/agent/api/conversations/${conversationId}/messages?staff_id=${encodeURIComponent(staffId)}`,
  )
  return messages.map((message) => ({
    ...message,
    placement: message.role === 'user' ? 'end' : 'start',
  }))
}

export async function streamMessage(
  conversationId: string,
  payload: Record<string, string>,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(`/agent/api/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(payload),
  })
  await readSse(response, onEvent)
}

export async function confirmTool(
  conversationId: string,
  payload: Record<string, unknown>,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(`/agent/api/conversations/${conversationId}/tool-confirmations`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(payload),
  })
  await readSse(response, onEvent)
}

async function readSse(response: Response, onEvent: (event: StreamEvent) => void): Promise<void> {
  if (!response.ok || response.body === null) {
    throw new Error('Unable to open the streaming response')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const chunk = await reader.read()
    if (chunk.done) return
    buffer += decoder.decode(chunk.value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      parseEvent(block, onEvent)
    }
  }
}

function parseEvent(block: string, onEvent: (event: StreamEvent) => void): void {
  const event = block.match(/^event: (.+)$/m)?.[1]
  const text = block.match(/^data: (.+)$/m)?.[1]
  if (!event || !text) return
  const data = JSON.parse(text) as Record<string, unknown>
  if (event === 'token') onEvent({ type: 'token', content: String(data.content || '') })
  if (event === 'tool_start') onEvent({ type: 'tool_start', name: String(data.name || 'tool') })
  if (event === 'tool_end') onEvent({ type: 'tool_end', name: String(data.name || 'tool') })
  if (event === 'confirmation_required') {
    onEvent({ type: 'confirmation_required', confirmation: { toolName: String(data.tool_name || 'tool'), description: String(data.description || 'Confirm tool execution') } })
  }
  if (event === 'form_required') {
    const fields = Array.isArray(data.fields) ? data.fields as FormField[] : []
    const prefilledValues = data.prefilled_values && typeof data.prefilled_values === 'object'
      ? data.prefilled_values as Record<string, string>
      : {}
    onEvent({ type: 'form_required', form: {
      formName: String(data.form_name || 'resource_form'),
      title: String(data.title || 'Resource information'),
      fields,
      prefilledValues,
    } })
  }
  if (event === 'done') onEvent({ type: 'done' })
  if (event === 'error') onEvent({ type: 'error', message: String(data.message || 'Agent execution failed') })
}
