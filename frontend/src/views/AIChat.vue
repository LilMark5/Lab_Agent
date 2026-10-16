<template>
  <div>
    <el-card>
      <template #header>
        <div class="chat-header">
          <span style="font-weight: bold">AI智能助手</span>
          <el-switch
            v-model="includeUploaded"
            size="small"
            active-text="检索上传文档"
          />
        </div>
      </template>

      <div ref="listRef" class="chat-list">
        <div
          v-for="(item, index) in messages"
          :key="index"
          class="chat-row"
          :style="{ justifyContent: item.role === 'user' ? 'flex-end' : 'flex-start' }"
        >
          <div
            class="bubble"
            :style="{
              backgroundColor: item.role === 'user' ? '#409eff' : '#fff',
              color: item.role === 'user' ? '#fff' : '#333'
            }"
          >
            <div
              v-if="item.role === 'assistant' && item.status"
              class="process-status"
            >
              {{ item.status }}
            </div>
            <div v-if="item.role === 'assistant' && item.steps?.length" class="process-status">
              <div v-for="(step, i) in item.steps" :key="i">· {{ step }}</div>
            </div>
            <div v-html="parseMarkdown(item.content)"></div>
          </div>
        </div>
      </div>

      <div class="chat-input">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          placeholder="问问实验室怎么预约、开放时间，或直接说：帮我预约明天下午的实验室"
          @keydown.enter.exact.prevent="handleSend"
          @keydown.enter.shift.stop
        />
        <el-button type="primary" :loading="loading" @click="handleSend">发送</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { nextTick, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

import { chatStreamApi, chatStreamResumeApi } from '@/api/ai'

const messages = ref([
  {
    role: 'assistant',
    content:
      '你好，我是实验室预约助手。可以问规则和开放实验室，也可以说「帮我预约明天下午的实验室」，确认后我会帮你提交。'
  }
])
const input = ref('')
const loading = ref(false)
const listRef = ref()
// 是否把「知识库管理」里上传的文档纳入检索范围。
const includeUploaded = ref(true)

// 一个页面会话一个 thread_id，后端 checkpointer 用它隔离和恢复多轮状态。
const threadId = ref(
  (typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : Date.now().toString(36) + Math.random().toString(36).slice(2))
)

const scrollToBottom = () => {
  nextTick(() => {
    const elem = listRef.value
    if (elem) elem.scrollTop = elem.scrollHeight
  })
}

const parseMarkdown = (text) => {
  if (!text) return ''
  marked.setOptions({ breaks: true })
  const rawHtml = marked.parse(text)
  return DOMPurify.sanitize(rawHtml)
}

const TOOL_LABELS = {
  create_lab_reservation: '提交预约',
  search_lab_docs: '检索实验室知识库',
  list_open_labs: '查询开放实验室',
  list_lab_equipments: '查询实验室设备',
  get_today: '获取今天日期'
}

const applyStreamEvents = (assistant, evt) => {
  if (evt.type === 'status') {
    assistant.status = evt.message || '正在思考…'
  } else if (evt.type === 'tool_start') {
    const label = evt.label || TOOL_LABELS[evt.name] || evt.name || '工具'
    assistant.status = `正在${label}…`
    assistant.steps.push(`开始：${label}`)
  } else if (evt.type === 'tool_end') {
    const label = evt.label || TOOL_LABELS[evt.name] || evt.name || '工具'
    assistant.status = `${label}完成`
    assistant.steps.push(`完成：${label}`)
  } else if (evt.type === 'token') {
    assistant.content += evt.content || ''
    assistant.status = ''
  } else if (evt.type === 'done') {
    assistant.status = ''
  } else if (evt.type === 'approval_required') {
    handleApproval(evt, assistant)
  } else if (evt.type === 'error') {
    assistant.status = ''
    if (!assistant.content) assistant.content = evt.message || '请求失败'
    ElMessage.error(evt.message || '请求失败')
  }
  scrollToBottom()
}

const resumeStream = async (tid, approved, assistant) => {
  loading.value = true
  assistant.status = approved ? '已确认，继续执行…' : '已取消本次操作'
  assistant.steps.push(approved ? '用户已确认' : '用户已取消')
  try {
    await chatStreamResumeApi(
      { thread_id: tid, approved, include_uploaded: includeUploaded.value },
      (evt) => applyStreamEvents(assistant, evt)
    )
  } catch (err) {
    assistant.status = ''
    if (!assistant.content) assistant.content = err.message || '网络异常'
    ElMessage.error(err.message || '网络异常')
  } finally {
    loading.value = false
    assistant.status = ''
    scrollToBottom()
  }
}

const handleApproval = async (evt, assistant) => {
  const payload = evt.payload || {}
  const toolName = payload.tool || '未知工具'
  const label = TOOL_LABELS[toolName] || toolName
  const args = payload.args || {}
  const summary = Object.entries(args)
    .map(([key, value]) => `${key}: ${value}`)
    .join('，')

  try {
    await ElMessageBox.confirm(
      `即将执行「${label}」：${summary || '无参数'}。是否确认？`,
      '操作确认',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await resumeStream(evt.thread_id, true, assistant)
  } catch {
    await resumeStream(evt.thread_id, false, assistant)
  }
}

const handleSend = async () => {
  const text = input.value.trim()
  if (!text || loading.value) return

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  scrollToBottom()

  const assistant = reactive({
    role: 'assistant',
    content: '',
    status: '正在思考…',
    steps: []
  })
  messages.value.push(assistant)

  try {
    // 服务端 checkpointer 已经保存历史，这里只发本轮新增的用户消息。
    await chatStreamApi(
      {
        messages: [{ role: 'user', content: text }],
        thread_id: threadId.value,
        include_uploaded: includeUploaded.value
      },
      (evt) => applyStreamEvents(assistant, evt)
    )
  } catch (err) {
    assistant.status = ''
    if (!assistant.content) assistant.content = err.message || '网络异常'
    ElMessage.error(err.message || '网络异常')
  } finally {
    loading.value = false
    assistant.status = ''
    scrollToBottom()
  }
}
</script>

<style scoped>
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.chat-list {
  height: 480px;
  overflow-y: auto;
  padding: 8px 4px;
  background-color: #fafafa;
  border-radius: 6px;
}
.chat-row {
  display: flex;
  margin-bottom: 12px;
}
.bubble {
  max-width: 70%;
  padding: 10px 12px;
  border-radius: 8px;
  line-height: 1.6;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}
.process-status {
  margin-bottom: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}
.chat-input {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
</style>
