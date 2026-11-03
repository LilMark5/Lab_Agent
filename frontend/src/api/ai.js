import { getToken } from '@/utils/auth'
import request from '@/utils/request'

export function chatApi(data) {
  return request({
    url: '/api/ai/chat',
    method: 'post',
    data,
    timeout: 90000
  })
}

export function chatResumeApi(data) {
  return request({
    url: '/api/ai/chat/resume',
    method: 'post',
    data,
    timeout: 90000
  })
}

function streamRequest(path, data, onEvent) {
  const baseURL = import.meta.env.VITE_API_BASE_URL || ''
  const token = getToken()

  return fetch(`${baseURL}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(data)
  }).then(async (res) => {
    if (res.status === 401) {
      throw new Error('登录已失效，请重新登录')
    }
    if (!res.ok || !res.body) {
      throw new Error('流式接口请求失败')
    }

    const contentType = res.headers.get('content-type') || ''
    if (!contentType.includes('text/event-stream')) {
      const payload = await res.json().catch(() => null)
      throw new Error(payload?.message || '流式接口返回异常')
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() || ''

      for (const chunk of chunks) {
        const line = chunk
          .split('\n')
          .map((item) => item.trim())
          .find((item) => item.startsWith('data:'))
        if (!line) continue
        const raw = line.slice(5).trim()
        if (!raw || raw === '[DONE]') continue
        try {
          onEvent(JSON.parse(raw))
        } catch {
          // 半包或脏数据：跳过，等下一帧。
        }
      }
    }
  })
}

/**
 * SSE 流式对话。
 * @param {Object} data 请求体 { messages, thread_id }
 * @param {(evt: object) => void} onEvent 每解析出一条 SSE 数据调用一次
 */
export function chatStreamApi(data, onEvent) {
  return streamRequest('/api/ai/chat/stream', data, onEvent)
}

/**
 * SSE 恢复被人工审批中断的会话。
 * @param {Object} data 请求体 { thread_id, approved }
 * @param {(evt: object) => void} onEvent
 */
export function chatStreamResumeApi(data, onEvent) {
  return streamRequest('/api/ai/chat/stream/resume', data, onEvent)
}
