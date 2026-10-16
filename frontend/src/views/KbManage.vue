<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span style="font-weight: bold">知识库文档管理</span>
          <el-button link type="primary" @click="loadDocuments">刷新</el-button>
        </div>
      </template>

      <el-upload
        drag
        :show-file-list="false"
        :accept="acceptTypes"
        :http-request="handleUpload"
        :disabled="uploading"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          把 Markdown / TXT / PDF / DOCX 拖到这里，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            支持 .md .txt .pdf .docx，单个不超过 20MB；相同内容会自动去重。
          </div>
        </template>
      </el-upload>

      <el-table
        v-loading="loading"
        :data="documents"
        style="margin-top: 16px"
        empty-text="还没有文档，先上传一份试试"
      >
        <el-table-column prop="filename" label="文件名" min-width="220" />
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ formatSize(row.size_bytes) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ready' ? 'success' : 'danger'">
              {{ row.status === 'ready' ? '已就绪' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="180">
          <template #default="{ row }">{{ formatTime(row.create_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openSearch(row)">检索</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="searchVisible"
      :title="`在「${currentDoc?.filename || ''}」中检索`"
      width="640px"
    >
      <div class="search-bar">
        <el-input
          v-model="searchQuery"
          placeholder="输入问题，例如：开放时间"
          @keydown.enter="doSearch"
        />
        <el-button type="primary" :loading="searching" @click="doSearch">检索</el-button>
      </div>
      <pre class="search-result">{{ searchResult || '（暂无结果）' }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  deleteDocumentApi,
  listDocumentsApi,
  searchDocumentApi,
  uploadDocumentApi
} from '@/api/kb'

const acceptTypes = '.md,.txt,.pdf,.docx'

const documents = ref([])
const loading = ref(false)
const uploading = ref(false)

const searchVisible = ref(false)
const currentDoc = ref(null)
const searchQuery = ref('')
const searching = ref(false)
const searchResult = ref('')

const formatSize = (bytes = 0) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

const formatTime = (value) => (value ? value.replace('T', ' ').slice(0, 19) : '')

const loadDocuments = async () => {
  loading.value = true
  try {
    const res = await listDocumentsApi()
    documents.value = res.data || []
  } finally {
    loading.value = false
  }
}

const handleUpload = async (options) => {
  uploading.value = true
  try {
    const res = await uploadDocumentApi(options.file)
    ElMessage.success('上传成功，文档已入库')
    await loadDocuments()
    options.onSuccess?.(res)
  } catch (err) {
    options.onError?.(err)
  } finally {
    uploading.value = false
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.filename}」及其全部向量吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await deleteDocumentApi(row.id)
  ElMessage.success('已删除')
  await loadDocuments()
}

const openSearch = (row) => {
  currentDoc.value = row
  searchQuery.value = ''
  searchResult.value = ''
  searchVisible.value = true
}

const doSearch = async () => {
  const query = searchQuery.value.trim()
  if (!query || !currentDoc.value) return
  searching.value = true
  try {
    const res = await searchDocumentApi(currentDoc.value.id, query)
    searchResult.value = res.data?.answer || '（没有命中相关内容）'
  } finally {
    searching.value = false
  }
}

onMounted(loadDocuments)
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.search-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.search-result {
  max-height: 320px;
  overflow: auto;
  margin: 0;
  padding: 12px;
  background: #f7f8fa;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  font-family: inherit;
}
</style>
