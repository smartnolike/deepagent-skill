<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { BubbleList, Thinking, XSender } from 'vue-element-plus-x'
import { MarkdownRenderer } from 'x-markdown-vue'
import 'x-markdown-vue/style'

import {
  confirmTool,
  createConversation,
  listConversations,
  listMessages,
  streamMessage,
  type ChatMessage,
  type AgentActivity,
  type ConfirmationRequest,
  type Conversation,
  type FormRequest,
  type StreamEvent,
} from './api/client'

const staffId = ref(import.meta.env.VITE_STAFF_ID || 'staff-demo')
const conversations = ref<Conversation[]>([])
const activeConversationId = ref<string>()
const messages = ref<ChatMessage[]>([])
// XSender 不支持 v-model；通过组件暴露的 getModelValue() 读取富文本编辑器内容。
const sender = ref<InstanceType<typeof XSender> | null>(null)
const loading = ref(false)
const confirmation = ref<ConfirmationRequest>()
const formRequest = ref<FormRequest>()
const formValues = reactive<Record<string, string>>({})

// Danaan 基础资料候选数据暂时固定在前端；后续可替换为受控配置或目录服务接口。
const mockDanaanProfiles = [
  {
    resourceOnboardRegion: 'ASP',
    applicationName: 'payment-platform',
    eimId: 'EIM-100001',
    envName: 'dev',
    useCaseShortName: 'payments',
  },
  {
    resourceOnboardRegion: 'EUR',
    applicationName: 'analytics-platform',
    eimId: 'EIM-100002',
    envName: 'prod',
    useCaseShortName: 'analytics',
  },
]

const activeConversation = computed(() => conversations.value.find((item) => item.id === activeConversationId.value))

onMounted(loadConversations)

async function loadConversations(): Promise<void> {
  try {
    conversations.value = (await listConversations(staffId.value)).items
    if (!activeConversationId.value && conversations.value[0]) await selectConversation(conversations.value[0].id)
  } catch (error) {
    ElMessage.error(messageOf(error))
  }
}

async function startConversation(): Promise<void> {
  try {
    const conversation = await createConversation(staffId.value)
    conversations.value.unshift(conversation)
    activeConversationId.value = conversation.id
    messages.value = []
    confirmation.value = undefined
    formRequest.value = undefined
  } catch (error) {
    ElMessage.error(messageOf(error))
  }
}

async function selectConversation(conversationId: string): Promise<void> {
  activeConversationId.value = conversationId
  confirmation.value = undefined
  formRequest.value = undefined
  try {
    messages.value = await listMessages(conversationId, staffId.value)
  } catch (error) {
    ElMessage.error(messageOf(error))
  }
}

async function send(): Promise<void> {
  const content = sender.value?.getModelValue().text.trim() || ''
  if (!content || loading.value) return
  if (!activeConversationId.value) await startConversation()
  if (!activeConversationId.value) return
  messages.value.push({ content, role: 'user', placement: 'end' })
  sender.value?.clear()
  loading.value = true
  // 流式更新必须修改 Vue reactive 对象；普通对象入数组后再从原引用修改不会触发界面刷新。
  const assistant = createAssistantMessage()
  messages.value.push(assistant)
  try {
    await streamMessage(activeConversationId.value, { staff_id: staffId.value, content }, (event) => handleEvent(event, assistant))
  } catch (error) {
    assistant.content = messageOf(error)
    ElMessage.error(assistant.content)
  } finally {
    finalizeActivities(assistant)
    assistant.loading = false
    loading.value = false
  }
}

async function resolveConfirmation(action: 'approve' | 'reject'): Promise<void> {
  if (!activeConversationId.value || !confirmation.value || loading.value) return
  loading.value = true
  confirmation.value = undefined
  const assistant = createAssistantMessage()
  messages.value.push(assistant)
  try {
    await confirmTool(activeConversationId.value, { staff_id: staffId.value, action }, (event) => handleEvent(event, assistant))
  } catch (error) {
    assistant.content = messageOf(error)
    ElMessage.error(assistant.content)
  } finally {
    finalizeActivities(assistant)
    assistant.loading = false
    loading.value = false
  }
}

function selectDanaanProfile(profile: Record<string, string>): void {
  Object.assign(formValues, profile)
}

function optionValue(option: string | { label: string; value: string }): string {
  return typeof option === 'string' ? option : option.value
}

function optionLabel(option: string | { label: string; value: string }): string {
  return typeof option === 'string' ? option : option.label
}

async function submitForm(): Promise<void> {
  if (!activeConversationId.value || !formRequest.value || loading.value) return
  const submittedFormName = formRequest.value.formName
  loading.value = true
  formRequest.value = undefined
  const assistant = createAssistantMessage()
  messages.value.push(assistant)
  try {
    await confirmTool(
      activeConversationId.value,
      {
        staff_id: staffId.value,
        action: 'respond',
        form_name: submittedFormName,
        response: { ...formValues },
      },
      (event) => handleEvent(event, assistant),
    )
  } catch (error) {
    assistant.content = messageOf(error)
    ElMessage.error(assistant.content)
  } finally {
    finalizeActivities(assistant)
    assistant.loading = false
    loading.value = false
    if (!formRequest.value) Object.keys(formValues).forEach((key) => delete formValues[key])
  }
}

function handleEvent(event: StreamEvent, assistant: ChatMessage): void {
  if (event.type === 'token') assistant.content += event.content
  if (event.type === 'tool_start') upsertActivity(assistant, `tool:${event.name}`, `Calling ${event.name}`, 'running')
  if (event.type === 'tool_end') completeLatestActivity(assistant)
  if (event.type === 'confirmation_required') {
    completeLatestActivity(assistant)
    upsertActivity(assistant, `confirmation:${event.confirmation.toolName}`, 'Waiting for your confirmation', 'waiting')
    confirmation.value = event.confirmation
  }
  if (event.type === 'form_required') {
    completeLatestActivity(assistant)
    upsertActivity(assistant, `form:${event.form.formName}`, 'Waiting for your input', 'waiting')
    confirmation.value = undefined
    formRequest.value = event.form
    Object.keys(formValues).forEach((key) => delete formValues[key])
    Object.assign(formValues, event.form.prefilledValues)
  }
  if (event.type === 'done') finalizeActivities(assistant)
  if (event.type === 'error') {
    assistant.content = event.message
    markLatestActivityFailed(assistant)
  }
}

function createAssistantMessage(): ChatMessage {
  return reactive({
    content: '',
    role: 'assistant',
    placement: 'start',
    loading: true,
    activities: [{ id: 'agent', label: 'Processing request', status: 'running' }],
  })
}

function upsertActivity(
  assistant: ChatMessage,
  id: string,
  label: string,
  status: AgentActivity['status'],
): void {
  const activities = assistant.activities || (assistant.activities = [])
  const existing = activities.find((activity) => activity.id === id)
  if (existing) {
    existing.label = label
    existing.status = status
    return
  }
  activities.push({ id, label, status })
}

function completeLatestActivity(assistant: ChatMessage): void {
  const latest = [...(assistant.activities || [])].reverse().find((activity) => activity.status === 'running')
  if (latest) latest.status = 'completed'
}

function markLatestActivityFailed(assistant: ChatMessage): void {
  const latest = [...(assistant.activities || [])].reverse().find((activity) => activity.status === 'running')
  if (latest) latest.status = 'error'
}

function finalizeActivities(assistant: ChatMessage): void {
  for (const activity of assistant.activities || []) {
    if (activity.status === 'running') activity.status = 'completed'
  }
}

function thinkingContent(activities: AgentActivity[] | undefined): string {
  return (activities || [])
    .map((activity) => {
      const marker = { running: '◌', completed: '✓', waiting: '•', error: '!' }[activity.status]
      return `${marker} ${activity.label}`
    })
    .join('\n')
}

function thinkingStatus(item: ChatMessage): 'thinking' | 'end' | 'error' {
  if (item.activities?.some((activity) => activity.status === 'error')) return 'error'
  if (item.activities?.some((activity) => activity.status === 'running')) return 'thinking'
  return 'end'
}

function hasUnclosedCodeFence(content: string): boolean {
  // 流式响应尚未收齐结束围栏时，避免 MarkdownRenderer 反复解析不完整 JSON。
  return (content.match(/```/g) || []).length % 2 === 1
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed. Please verify that the service is running.'
}
</script>

<template>
  <el-container class="application-shell">
    <el-aside width="280px" class="conversation-panel">
      <div class="brand">DeepAgent Platform</div>
      <el-button type="primary" class="new-chat" @click="startConversation">New conversation</el-button>
      <el-scrollbar class="conversation-list">
        <button
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-item"
          :class="{ active: conversation.id === activeConversationId }"
          @click="selectConversation(conversation.id)"
        >
          {{ conversation.title || 'Untitled conversation' }}
        </button>
      </el-scrollbar>
      <el-divider />
      <el-input v-model="staffId" size="small" placeholder="staff_id" @change="loadConversations" />
    </el-aside>

    <el-main class="chat-panel">
      <header class="chat-header">
        <div>
          <strong>{{ activeConversation?.title || 'DeepAgent conversation' }}</strong>
          <span>Staff: {{ staffId }}</span>
        </div>
      </header>

      <main class="message-area">
        <el-empty v-if="!messages.length" description="Start a resource request or another supported task" />
        <BubbleList v-else :list="messages" class="bubble-list">
          <template #header="{ item }">
            <Thinking
              v-if="item.role === 'assistant' && item.activities?.length"
              class="agent-thinking"
              :content="thinkingContent(item.activities)"
              :status="thinkingStatus(item)"
              auto-collapse
              max-width="100%"
            />
          </template>
          <template #content="{ item }">
            <pre
              v-if="item.role === 'assistant' && item.loading && hasUnclosedCodeFence(item.content)"
              class="assistant-streaming-code"
            >{{ item.content }}</pre>
            <MarkdownRenderer
              v-else-if="item.role === 'assistant'"
              :markdown="item.content"
              :enable-animate="Boolean(item.loading)"
              class="assistant-markdown"
            />
            <span v-else class="plain-message">{{ item.content }}</span>
          </template>
        </BubbleList>
      </main>

      <section v-if="confirmation" class="confirmation-card">
        <div>
          <strong>Confirmation required</strong>
          <p>{{ confirmation.description }} ({{ confirmation.toolName }})</p>
        </div>
        <div>
          <el-button :disabled="loading" @click="resolveConfirmation('reject')">Cancel</el-button>
          <el-button type="primary" :loading="loading" @click="resolveConfirmation('approve')">Confirm and run</el-button>
        </div>
      </section>

      <section v-if="formRequest" class="resource-form-card">
        <div class="resource-form-header">
          <div>
            <strong>{{ formRequest.title }}</strong>
            <p>Select a suggested profile or enter values manually. All fields can be changed before submission.</p>
          </div>
        </div>

        <el-table
          v-if="formRequest.formName === 'danaan-base-context'"
          :data="mockDanaanProfiles"
          size="small"
          class="danaan-profile-table"
        >
          <el-table-column prop="resourceOnboardRegion" label="Region" width="92" />
          <el-table-column prop="applicationName" label="Application" min-width="160" />
          <el-table-column prop="eimId" label="EIM ID" width="130" />
          <el-table-column prop="envName" label="Environment" width="110" />
          <el-table-column prop="useCaseShortName" label="Use Case" width="120" />
          <el-table-column label="Action" width="108">
            <template #default="scope">
              <el-button link type="primary" @click="selectDanaanProfile(scope.row)">Use this profile</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-form label-position="top" class="resource-form-grid">
          <el-form-item v-for="field in formRequest.fields" :key="field.name" :required="field.required" :label="field.label || field.name">
            <el-select
              v-if="field.type === 'select'"
              v-model="formValues[field.name]"
              :placeholder="`Select ${field.label || field.name}`"
            >
              <el-option v-for="option in field.options || []" :key="optionValue(option)" :label="optionLabel(option)" :value="optionValue(option)" />
            </el-select>
            <el-input v-else v-model="formValues[field.name]" :placeholder="`Enter ${field.label || field.name}`" />
          </el-form-item>
        </el-form>
        <div class="resource-form-actions">
          <el-button type="primary" :loading="loading" @click="submitForm">Submit to Agent</el-button>
        </div>
      </section>

      <footer class="sender-area">
        <XSender
          ref="sender"
          placeholder="Enter a message and press Enter to send"
          :loading="loading"
          :disabled="Boolean(confirmation || formRequest)"
          @submit="send"
        />
      </footer>
    </el-main>
  </el-container>
</template>
